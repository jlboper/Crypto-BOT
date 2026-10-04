from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
import math
import json

from .config import PaperSettings
from .domain import Position


SPOT_CYCLE_STATES = {"RUNNING", "NO_OPPORTUNITIES", "FILTERED", "LIMITED", "OPENED", "PAUSED", "RISK_HALT", "ATTENTION", "ERROR"}
SPOT_CYCLE_COUNTS = ("universe", "evaluated", "signals", "candidates", "reviews", "opened")
SPOT_CYCLE_REASONS = {
    "BELOW_SCORE", "ALREADY_HELD", "MISSING_CANDLES", "QUOTE_UNAVAILABLE", "PRICE_OUTSIDE_RANGE",
    "POSITION_COUNT_LIMIT", "TOTAL_EXPOSURE_LIMIT", "EQUITY_LIMIT", "AI_CYCLE_LIMIT", "AI_DAILY_LIMIT",
    "CANDLE_ALREADY_CHECKED", "AI_REJECTED", "AI_UNAVAILABLE", "SIZE_LIMIT", "PAUSED", "LOSS_LIMIT",
    "EXCHANGE_RULES_UNAVAILABLE", "EXCHANGE_FILTER_PREFLIGHT", "POSITION_SIZE_LIMIT", "PER_TRADE_RISK_LIMIT",
    "LOCAL_ALLOCATION_LIMIT", "LOCAL_CASH_LIMIT", "PRICE_MOVED_OUTSIDE_SIGNAL_RANGE", "EXCHANGE_FILTER_REJECTED",
    "TESTNET_BALANCE_LIMIT", "CYCLE_ERROR",
}
SPOT_CYCLE_ERRORS = {
    "ORDER_RECONCILIATION_PENDING", "BTC_REGIME_UNAVAILABLE", "FRESH_PRICES_UNAVAILABLE",
    "INVALID_SPOT_QUOTE", "HELD_QUOTE_MISSING", "HELD_QUOTE_INVALID", "UNEXPECTED_VALUE_ERROR",
    "TESTNET_EXECUTION_ERROR", "UNEXPECTED_ERROR",
}


def spot_cycle_status(raw, cycle_seconds, now=None):
    """Project only bounded counters/codes; absent legacy data is never inferred as success."""
    try:
        report = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(report, dict) or report.get("state") not in SPOT_CYCLE_STATES:
            return None
        at = _parse_time(report.get("at"))
        current = now or datetime.now(UTC)
        if at is None or (at - current).total_seconds() > 120:
            return None
        counts = {key: report.get(key) for key in SPOT_CYCLE_COUNTS}
        if any(type(value) is not int or not 0 <= value <= 10000 for value in counts.values()):
            return None
        reasons = report.get("reasons")
        if not isinstance(reasons, dict) or any(
            key not in SPOT_CYCLE_REASONS or type(value) is not int or not 0 < value <= 10000
            for key, value in reasons.items()
        ):
            return None
        score = report.get("minimum_score")
        regime = report.get("btc_bullish")
        error = report.get("error_code")
        risk_halt = report.get("risk_halt")
        if risk_halt is not None:
            if (not isinstance(risk_halt, dict)
                    or set(risk_halt) - {"periods", "daily_return_pct", "weekly_return_pct",
                                         "daily_limit_pct", "weekly_limit_pct", "resets_at"}):
                return None
            periods = risk_halt.get("periods")
            if (not isinstance(periods, list) or not 1 <= len(periods) <= 2
                    or len(set(periods)) != len(periods)
                    or any(period not in {"daily", "weekly"} for period in periods)
                    or any(type(risk_halt.get(key)) not in (int, float) or not math.isfinite(risk_halt[key])
                           for key in ("daily_return_pct", "weekly_return_pct", "daily_limit_pct", "weekly_limit_pct"))
                    or not isinstance(risk_halt.get("resets_at"), str)
                    or _parse_time(risk_halt["resets_at"]) is None):
                return None
        if (type(score) is not int or not 0 <= score <= 100 or
                (regime is not None and type(regime) is not bool) or
                (error is not None and error not in SPOT_CYCLE_ERRORS)):
            return None
        activity = activity_status(at.isoformat(), cycle_seconds, current)
        return {"state": report["state"], "at": at.isoformat(), **counts, "reasons": reasons,
                "minimum_score": score, "btc_bullish": regime, "error_code": error,
                "risk_halt": risk_halt,
                "age_seconds": activity["age_seconds"], "fresh": activity["state"] == "operational"}
    except (ValueError, TypeError, AttributeError):
        return None


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
