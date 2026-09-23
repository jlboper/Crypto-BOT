from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
import math

from .config import PaperSettings
from .domain import Position


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def activity_status(last_cycle_at: str | None, cycle_seconds: int, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    last = _parse_time(last_cycle_at)
    if last is None:
        return {
            "state": "starting",
            "age_seconds": None,
            "last_cycle_at": None,
            "next_expected_at": None,
        }

    age = max(0.0, (current - last).total_seconds())
    healthy_until = max(cycle_seconds * 1.5, cycle_seconds + 120)
    delayed_until = cycle_seconds * 3
    if age <= healthy_until:
        state = "operational"
    elif age <= delayed_until:
        state = "delayed"
    else:
        state = "offline"
    return {
        "state": state,
        "age_seconds": round(age, 1),
        "last_cycle_at": last.isoformat(),
        "next_expected_at": (last + timedelta(seconds=cycle_seconds)).isoformat(),
    }


def usable_price(price: object, prices_at: str | None, cycle_seconds: int,
                 now: datetime | None = None) -> float | None:
    instant = _parse_time(prices_at)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    max_age = max(cycle_seconds * 1.5, cycle_seconds + 120)
    if (instant is None or not -120 <= (current - instant).total_seconds() <= max_age
            or type(price) not in (int, float) or not math.isfinite(price) or price <= 0):
        return None
    return float(price)


def position_metrics(position: Position, market_price: float | None, paper: PaperSettings) -> dict[str, Any]:
    payload = position.to_dict()
    if market_price is None:
        payload.update({"market_price": None, "market_value": None,
                        "unrealized_pnl": None, "unrealized_pct": None})
        return payload
    estimated_fill = market_price * (1.0 - paper.slippage_rate)
    market_value = position.quantity * market_price
    exit_fee = position.quantity * estimated_fill * paper.fee_rate
    unrealized_pnl = (
        (estimated_fill - position.entry_price) * position.quantity
        - position.entry_fee
        - exit_fee
    )
    invested = position.entry_price * position.quantity + position.entry_fee
    payload.update({
        "market_price": market_price,
        "market_value": market_value,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pct": (unrealized_pnl / invested * 100.0) if invested else 0.0,
    })
    return payload
