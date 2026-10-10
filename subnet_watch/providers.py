"""Read-only providers. Live credentials never enter the database or logs."""
from decimal import Decimal
import json
import math
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from .core import Sample, number, timestamp
from .credentials import validate_key, CredentialError
from .polling import METADATA_INTERVAL, retry_after_seconds


class ProviderError(Exception):
    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward Authorization to any redirect target.
        return None


class DemoProvider:
    source = "demo"

    def __init__(self):
        self.step = 0

    def fetch(self):
        self.step += 1
        now = time.time()
        # Explicitly synthetic names/IDs; no mapping to real subnet projects.
        names = ["Demo · Atlas", "Demo · Meridian", "Demo · Horizon", "Demo · Forge",
                 "Demo · Beacon", "Demo · Mosaic", "Demo · Orbit", "Demo · Cascade"]
        result = []
        for i, name in enumerate(names, 1):
            base = Decimal(["0.2184", "0.04721", "0.3021", "0.00675", "0.1289", "0.01945", "0.0726", "0.00412"][i-1])
            wave = Decimal(str(round(math.sin(self.step * .4 + i) * .018, 6)))
            price = base * (1 + wave)
            change = None if i == 8 else Decimal(str(round(math.sin(i + self.step * .05) * 12, 2)))
            result.append(Sample(f"demo:{i}", i, name, price, change, now, now, self.source))
        return result


class TaostatsProvider:
    source = "taostats"
    base = "https://api.taostats.io"
    pool_path = "/api/dtao/pool/latest/v1"
    identity_path = "/api/subnet/identity/v1"
    candle_path = "/api/dtao/tradingview/udf/history"

    def __init__(self, api_key, transport=None, names=None, metadata_at=0):
        try:
            self.api_key = validate_key(api_key)
        except CredentialError:
            raise ProviderError("Enter a valid Taostats API key in Settings to connect.") from None
        self.transport = transport or self._request
        self.names = names or {}
        self.metadata_at = metadata_at
        self.warning = ""
        self.page_counts = {self.pool_path: 1, self.identity_path: 1}
        self.advisory_error = None

    def _request(self, path, page):
        parameters = page if isinstance(page, dict) else {"page": page, "limit": 200}
        if path == self.pool_path:
            parameters["order"] = "netuid_asc"
        req = Request(f"{self.base}{path}?{urlencode(parameters)}",
                      headers={"Authorization": self.api_key, "Accept": "application/json",
                               "User-Agent": "GR-Subnet-Watch/0.1"})
        try:
            with build_opener(NoRedirect).open(req, timeout=20) as response:
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ProviderError("Provider response exceeds the safe size limit.")
                return json.loads(raw, parse_float=Decimal)
        except HTTPError as exc:
            explanations = {401: "API key was rejected.", 403: "API key lacks access.",
                            429: "Provider rate limit reached. Increase the refresh interval."}
            raise ProviderError(explanations.get(exc.code, f"Taostats returned HTTP {exc.code}."), exc.code,
                                retry_after_seconds(exc.headers.get("Retry-After"), time.time()) if exc.code == 429 else None) from None
        except (URLError, TimeoutError, OSError):
            raise ProviderError("Could not reach Taostats. Check the connection and retry.") from None
        except (ValueError, UnicodeError):
            raise ProviderError("Taostats returned an unreadable response.") from None

    def _pages(self, path):
        page, seen, rows = 1, set(), []
        while page is not None:
            if page in seen:
                raise ProviderError("Provider pagination repeated a page; refresh was stopped.")
            seen.add(page)
            payload = self.transport(path, page)
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ProviderError("Provider schema changed: expected a data list.")
            pagination = payload.get("pagination")
            if not isinstance(pagination, dict) or "next_page" not in pagination:
                raise ProviderError("Provider schema changed: pagination is missing.")
            rows.extend(payload["data"])
            page = pagination["next_page"]
            if page is not None and (not isinstance(page, int) or isinstance(page, bool) or page < 1):
                raise ProviderError("Provider returned an invalid next page.")
        self.page_counts[path] = len(seen)
        identities = [row.get("netuid") for row in rows if isinstance(row, dict)]
        if len(identities) != len(rows) or len(set(identities)) != len(identities):
            raise ProviderError("Provider pagination returned duplicate or invalid subnet rows; keeping the previous catalog.")
        return rows

    def fetch_candles(self, netuid, resolution, start, end):
        from .candles import parse_candles
        if isinstance(netuid, bool) or not isinstance(netuid, int) or netuid <= 0 or resolution not in ("15", "60", "1D"):
            raise ProviderError("Select a valid subnet and candle timeframe.")
        payload = self.transport(self.candle_path, {"symbol": f"SUB-{netuid}", "resolution": resolution,
                                                  "from": start, "to": end, "countback": 200})
        return parse_candles(payload, start, end)

    @staticmethod
    def parse_pool(row, names, now):
        try:
            netuid = row["netuid"]
            if not isinstance(netuid, int) or isinstance(netuid, bool) or netuid < 0:
                raise ValueError()
            price = number(row.get("price"))
            if price is not None and price <= 0:
                price = None
            metrics = {}
            for field_name in ("price_change_1_hour", "price_change_1_week", "price_change_1_month"):
                metrics[field_name] = number(row.get(field_name))
            # Official legacy response details give these balances/volumes in
            # rao. Both alpha and TAO use1e9 base units. Price is NOT scaled.
            for field_name in ("liquidity", "market_cap", "total_tao", "total_alpha", "alpha_in_pool", "alpha_staked",
                               "tao_volume_24_hr", "tao_buy_volume_24_hr", "tao_sell_volume_24_hr"):
                raw = number(row.get(field_name))
                metrics[field_name] = raw / Decimal("1000000000") if raw is not None and raw >= 0 else None
            for field_name in ("buys_24_hr", "sells_24_hr", "buyers_24_hr", "sellers_24_hr", "block_number"):
                raw = number(row.get(field_name))
                metrics[field_name] = int(raw) if raw is not None and raw >= 0 and raw == raw.to_integral_value() else None
            # Official response details: price already in TAO; daily change in %.
            return Sample(f"taostats:{netuid}", netuid, names.get(netuid) or str(row.get("name") or f"Subnet {netuid}"),
                          price, number(row.get("price_change_1_day")), timestamp(row.get("timestamp")), now, "taostats", metrics)
        except (KeyError, TypeError, ValueError):
            raise ProviderError("Provider schema changed: invalid subnet identity.") from None

    def fetch(self):
        now = time.time()
        self.advisory_error = None
        # Price failures, especially auth/rate limits, stop before any optional
        # endpoint is attempted. Refresh every pool; no per-watch requests.
        rows = self._pages(self.pool_path)
        if now - self.metadata_at >= METADATA_INTERVAL:
            try:
                names = {}
                for row in self._pages(self.identity_path):
                    if isinstance(row, dict) and isinstance(row.get("netuid"), int) and isinstance(row.get("subnet_name"), str):
                        names[row["netuid"]] = row["subnet_name"].strip()
                self.names, self.metadata_at, self.warning = names, now, ""
            except ProviderError as error:
                # Prices can still be useful when optional friendly names fail.
                # Names are optional. Avoid retrying them every price poll.
                self.metadata_at = now
                self.warning = "Subnet name lookup unavailable; using known or pool names."
                if error.status == 429:
                    self.advisory_error = error
        observed = time.time()
        samples = [self.parse_pool(row, self.names, observed) for row in rows]
        # Root is TAO, not subnet alpha; include only actual subnet pools.
        return sorted((s for s in samples if s.netuid > 0), key=lambda s: s.netuid)
