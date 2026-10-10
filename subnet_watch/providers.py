"""Read-only providers. Live credentials never enter the database or logs."""
from decimal import Decimal
import json
import math
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from .core import Sample, number, timestamp


class ProviderError(Exception):
    pass


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

    def __init__(self, api_key, transport=None):
        if not api_key.strip():
            raise ProviderError("Enter a Taostats API key in Settings to connect.")
        self.api_key = api_key.strip()
        self.transport = transport or self._request
        self.names = {}
        self.metadata_at = 0
        self.warning = ""

    def _request(self, path, page):
        req = Request(f"{self.base}{path}?page={page}&limit=200",
                      headers={"Authorization": self.api_key, "Accept": "application/json",
                               "User-Agent": "GR-Subnet-Watch/0.1"})
        try:
            with build_opener(NoRedirect).open(req, timeout=20) as response:
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ProviderError("Provider response exceeds the safe size limit.")
                return json.loads(raw)
        except HTTPError as exc:
            explanations = {401: "API key was rejected.", 403: "API key lacks access.",
                            429: "Provider rate limit reached. Increase the refresh interval."}
            raise ProviderError(explanations.get(exc.code, f"Taostats returned HTTP {exc.code}.")) from None
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
            if page is not None and (not isinstance(page, int) or page < 1):
                raise ProviderError("Provider returned an invalid next page.")
        return rows

    @staticmethod
    def parse_pool(row, names, now):
        try:
            netuid = row["netuid"]
            if not isinstance(netuid, int) or isinstance(netuid, bool) or netuid < 0:
                raise ValueError()
            price = number(row.get("price"))
            if price is not None and price <= 0:
                price = None
            # Official response details: price already in TAO; daily change in %.
            return Sample(f"taostats:{netuid}", netuid, names.get(netuid) or str(row.get("name") or f"Subnet {netuid}"),
                          price, number(row.get("price_change_1_day")), timestamp(row.get("timestamp")), now, "taostats")
        except (KeyError, TypeError, ValueError):
            raise ProviderError("Provider schema changed: invalid subnet identity.") from None

    def fetch(self):
        now = time.time()
        if now - self.metadata_at > 3600:
            try:
                names = {}
                for row in self._pages(self.identity_path):
                    if isinstance(row, dict) and isinstance(row.get("netuid"), int) and isinstance(row.get("subnet_name"), str):
                        names[row["netuid"]] = row["subnet_name"].strip()
                self.names, self.metadata_at, self.warning = names, now, ""
            except ProviderError:
                # Prices can still be useful when optional friendly names fail.
                # Retain known names and retry metadata after five minutes.
                self.metadata_at = now - 3300
                self.warning = "Subnet name lookup unavailable; using known or pool names."
        rows = self._pages(self.pool_path)
        observed = time.time()
        samples = [self.parse_pool(row, self.names, observed) for row in rows]
        # Root is TAO, not subnet alpha; include only actual subnet pools.
        return sorted((s for s in samples if s.netuid > 0), key=lambda s: s.netuid)
