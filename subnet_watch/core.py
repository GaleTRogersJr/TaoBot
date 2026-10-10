"""UI-independent price and alert rules. Monetary values use Decimal."""
from dataclasses import dataclass, asdict, field
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from uuid import uuid4
import math

STALE_SECONDS = 180


def number(value):
    try:
        if len(str(value)) > 512:
            return None
        result = Decimal(str(value))
        return result if result.is_finite() and -100 <= result.adjusted() <= 100 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def price_text(value):
    if value is None:
        return "Unavailable"
    if value != 0 and abs(value) < Decimal("0.00000001"):
        return format(value, ".6g")
    return format(value, ".10f").rstrip("0").rstrip(".") or "0"


def change_text(value):
    return "Unavailable" if value is None else f"{value:+.2f}%"


def local_time(value):
    if not value:
        return "Unavailable"
    try:
        local = datetime.fromtimestamp(value).astimezone()
    except (TypeError, ValueError, OverflowError, OSError):
        return "Timestamp outside supported range"
    offset = local.strftime("%z")
    return local.strftime("%b %d, %H:%M:%S") + f" (UTC{offset[:3]}:{offset[3:]})"


@dataclass
class Sample:
    key: str
    netuid: int
    name: str
    price: Decimal | None
    change_24h: Decimal | None
    source_time: float | None
    observed_time: float
    source: str
    metrics: dict = field(default_factory=dict)
    cached: bool = False

    def fresh(self, now):
        return (not self.cached and self.price is not None and self.price.is_finite() and self.price > 0
                and self.source_time is not None and math.isfinite(self.source_time)
                and -30 <= now - self.source_time <= STALE_SECONDS
                and -30 <= now - self.observed_time <= STALE_SECONDS)

    def to_dict(self):
        return {"key": self.key, "netuid": self.netuid, "name": self.name,
                "price": str(self.price) if self.price is not None else None,
                "change_24h": str(self.change_24h) if self.change_24h is not None else None,
                "source_time": self.source_time, "observed_time": self.observed_time, "source": self.source,
                "metrics": {key: str(value) if isinstance(value, Decimal) else value for key, value in self.metrics.items()}}

    @classmethod
    def from_dict(cls, body, cached=True):
        return cls(body["key"], body["netuid"], body["name"], number(body["price"]), number(body["change_24h"]),
                   body["source_time"], body["observed_time"], body["source"],
                   {key: number(value) if isinstance(value, str) else value for key, value in body.get("metrics", {}).items()}, cached)


@dataclass
class Alert:
    key: str
    name: str
    kind: str
    direction: str
    amount: str
    repeat: bool = False
    cooldown: int = 300
    baseline: str | None = None
    baseline_time: float | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    enabled: bool = True
    done: bool = False
    armed: bool = True
    last_met: bool | None = None
    last_seen: float | None = None
    last_trigger: float | None = None
    gap: bool = True

    @property
    def target(self):
        amount = Decimal(self.amount)
        if self.kind == "target":
            return amount
        return self.upper_target if self.direction in ("up", "either") else self.lower_target

    @property
    def upper_target(self):
        return Decimal(self.baseline) * (1 + Decimal(self.amount) / 100)

    @property
    def lower_target(self):
        return Decimal(self.baseline) * (1 - Decimal(self.amount) / 100)

    @property
    def description(self):
        if self.kind == "target":
            return f"At or {'above' if self.direction == 'up' else 'below'} {price_text(self.target)} TAO / alpha"
        if self.direction == "either":
            return f"Rise or fall {self.amount}% → ≥ {price_text(self.upper_target)} or ≤ {price_text(self.lower_target)} TAO / alpha"
        return f"{'Rise' if self.direction == 'up' else 'Fall'} {self.amount}% → {price_text(self.target)} TAO / alpha"

    @property
    def status(self):
        if self.done:
            return "Triggered (one-shot)"
        if not self.enabled:
            return "Paused"
        return "Active" if self.armed else "Waiting to rearm"

    def to_dict(self):
        return asdict(self)


def make_alert(sample, kind, direction, amount, repeat, cooldown, now):
    if len(str(amount)) > 64:
        raise ValueError("Use a value with at most 64 characters.")
    amount = number(amount)
    if kind not in ("target", "percent") or direction not in ("up", "down", "either") or (kind == "target" and direction == "either"):
        raise ValueError("Choose a valid alert type and direction.")
    if amount is None or amount <= 0:
        raise ValueError("Enter a positive, finite value.")
    if not -24 <= amount.adjusted() <= 12:
        raise ValueError("Value must be between 0.000000000000000000000001 and 9999999999999.")
    if kind == "percent" and direction in ("down", "either") and amount >= 100:
        raise ValueError("A fall or either-direction percentage must be less than 100%.")
    if not 0 <= cooldown <= 86400:
        raise ValueError("Cooldown must be 0–86400 seconds.")
    if kind == "percent" and not sample.fresh(now):
        raise ValueError("A percentage alert needs a fresh, valid price. Refresh first.")
    return Alert(sample.key, sample.name, kind, direction, str(amount), repeat, cooldown,
                 str(sample.price) if kind == "percent" else None,
                 sample.source_time if kind == "percent" else None)


def evaluate(alert, sample, now):
    """Return an event or None, updating persisted trigger state.

    Repeats rearm on a clear observation. A rearmed condition reached during
    cooldown waits until the next valid observation after cooldown expires.
    No stale/invalid/duplicate/out-of-order observation can emit an event.
    """
    if not alert.enabled or alert.done or sample.key != alert.key:
        return None
    if not sample.fresh(now):
        alert.gap = True
        return None
    if alert.last_seen is not None and sample.source_time <= alert.last_seen:
        return None
    had_gap = alert.gap or (alert.last_seen is not None and sample.source_time - alert.last_seen > STALE_SECONDS)
    first = alert.last_seen is None
    previous_met = alert.last_met
    alert.last_seen = sample.source_time
    alert.gap = False
    reached_target = alert.target
    if alert.kind == "percent" and alert.direction == "either":
        met = sample.price >= alert.upper_target or sample.price <= alert.lower_target
        reached_target = alert.upper_target if sample.price >= alert.upper_target else alert.lower_target
    else:
        met = sample.price >= alert.target if alert.direction == "up" else sample.price <= alert.target
    alert.last_met = met
    if not met:
        alert.armed = True
        return None
    if not alert.armed or (alert.last_trigger is not None and now - alert.last_trigger < alert.cooldown):
        return None
    reason = ("Target already met at first observation" if first else
              "Target met on current observation after a monitoring gap" if had_gap else
              "Observed threshold crossing" if previous_met is False else
              "Target still met after cooldown")
    alert.armed = False
    alert.last_trigger = now
    if not alert.repeat:
        alert.done = True
    return {"id": uuid4().hex, "alert_id": alert.id, "key": sample.key, "name": sample.name,
            "price": str(sample.price), "target": str(reached_target), "condition": alert.description,
            "reason": reason, "source_time": sample.source_time, "observed_time": now,
            "source": sample.source}
