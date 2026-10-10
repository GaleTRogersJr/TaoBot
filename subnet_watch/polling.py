"""Nonblocking, bounded retry scheduling and free-plan budget estimates."""
import math
from email.utils import parsedate_to_datetime

DEFAULT_INTERVAL = 30
METADATA_INTERVAL = 6 * 3600


def retry_after_seconds(value, now):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0, seconds) if math.isfinite(seconds) else None


class PollingPolicy:
    max_failures = 6

    def __init__(self, interval=DEFAULT_INTERVAL):
        self.interval = interval
        self.failures = 0
        self.next_allowed = 0
        self.auth_failed = False

    def success(self, now):
        self.failures = 0
        self.auth_failed = False
        self.next_allowed = now + self.interval

    def fail(self, error, now):
        self.failures = min(self.max_failures, self.failures + 1)
        self.auth_failed = getattr(error, "status", None) in (401, 403)
        delay = min(3600, max(self.interval, 30) * 2 ** min(self.failures-1, 6))
        if getattr(error, "retry_after", None) is not None:
            delay = max(delay, error.retry_after)
        self.next_allowed = now + delay

    def automatic_allowed(self, now):
        return not self.auth_failed and now >= self.next_allowed

    def manual_allowed(self, now):
        # Manual refresh never bypasses Retry-After or authentication failure.
        if self.auth_failed or now < self.next_allowed:
            return False
        return True

    def to_dict(self):
        return {"failures": self.failures, "next_allowed": self.next_allowed,
                "auth_failed": self.auth_failed}

    def restore(self, body):
        if not isinstance(body, dict):
            return
        self.failures = max(0, min(self.max_failures, int(body.get("failures", 0))))
        self.next_allowed = float(body.get("next_allowed", 0))
        self.auth_failed = bool(body.get("auth_failed", False))


def monthly_estimate(pool_pages, metadata_pages, interval):
    # Conservative 31-day calculation. Actual plan charging must be checked.
    return math.ceil(31*86400/interval) * max(1, pool_pages) + math.ceil(31*86400/METADATA_INTERVAL) * max(1, metadata_pages)
