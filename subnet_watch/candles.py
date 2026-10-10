"""Validated subnet candles and a bounded, on-demand history cache."""
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
import math
import threading
import time
from .core import number
from .providers import ProviderError


TIMEFRAMES = {
    "15 min · 24 hours": ("15", 86400, 900),
    "1 hour · 7 days": ("60", 7 * 86400, 3600),
    "1 day · 30 days": ("1D", 30 * 86400, 86400),
}


@dataclass(frozen=True)
class Candle:
    time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class HistoryWait(ProviderError):
    """Local request spacing; the chart can schedule this user's pending view."""
    def __init__(self, seconds):
        self.seconds = max(1, math.ceil(seconds))
        super().__init__(f"Loading this chart in {self.seconds} seconds to limit API usage…")


def parse_candles(payload, start, end):
    if not isinstance(payload, dict):
        raise ProviderError("Taostats returned an invalid candle response.")
    if payload.get("s") == "no_data":
        return []
    if payload.get("s") != "ok":
        raise ProviderError("Candle history is unavailable for this subnet.")
    columns = [payload.get(key) for key in ("t", "o", "h", "l", "c")]
    if not all(isinstance(column, list) for column in columns) or len({len(column) for column in columns}) != 1:
        raise ProviderError("Taostats returned mismatched candle data.")
    if len(columns[0]) > 500:
        raise ProviderError("Taostats returned too many candles for this chart.")
    candles, seen = [], set()
    for stamp, *values in zip(*columns):
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0 or stamp in seen:
            raise ProviderError("Taostats returned invalid or duplicate candle times.")
        seen.add(stamp)
        o, h, low, c = [number(value) for value in values]
        if any(value is None or value <= 0 for value in (o, h, low, c)) or not low <= min(o, c) <= max(o, c) <= h:
            raise ProviderError("Taostats returned invalid candle prices.")
        if start <= stamp <= end:
            candles.append(Candle(stamp, o, h, low, c))
    return sorted(candles, key=lambda candle: candle.time)


class CandleHistory:
    """One history request at a time, at least 30 seconds apart; cache 32 views."""
    def __init__(self):
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self.next_allowed = 0

    def load(self, provider, netuid, timeframe, force=False):
        cache_key = (provider.source, netuid, timeframe)
        now = time.time()
        with self.lock:
            cached = self.cache.get(cache_key)
            if not force and cached and 0 <= now - cached[1] < 300:
                self.cache.move_to_end(cache_key)
                return cached[0], cached[1], True
            if now < self.next_allowed:
                raise HistoryWait(self.next_allowed-now)
            self.next_allowed = now + 30
            resolution, span, seconds = TIMEFRAMES[timeframe]
            end = int(now)
            start = (end - span) // seconds * seconds
            try:
                candles = provider.fetch_candles(netuid, resolution, start, end)
            except ProviderError as error:
                if error.retry_after is not None:
                    self.next_allowed = max(self.next_allowed, time.time() + error.retry_after)
                raise
            fetched = time.time()
            self.cache[cache_key] = (candles, fetched)
            self.cache.move_to_end(cache_key)
            while len(self.cache) > 32:
                self.cache.popitem(last=False)
            return candles, fetched, False
