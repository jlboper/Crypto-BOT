"""Read-only future migration evidence, never admission or LIVE implementation.

The dashboard is a cached, partial observation, not an exchange account inventory.
No field supplied by it can approve a strategy, account, risk policy or execution.
Thirty calendar days between equity points are reported only as an unqualified
span. Existing trading decisions and protective exits never depend on this file.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re


MAX_BYTES = 8000
MAX_PROPOSAL_BYTES = 2048
ENGINES = ("SPOT", "FUTURES", "AI_MARKET_PULSE", "QUANT_ARBITRAGE")
GLOBAL_BLOCKERS = (
    "OWNER_POLICY_INCOMPLETE", "OWNER_LIVE_AUTHORIZATION_REQUIRED",
    "VERIFIED_ACCOUNT_IDENTITY_MISSING", "COMPLETE_EXCHANGE_INVENTORY_MISSING",
    "ACCOUNT_BASELINE_AND_CASHFLOWS_MISSING", "COMMON_CAPITAL_PROTOCOL_NOT_INTEGRATED",
    "PERSISTENT_GLOBAL_RISK_NOT_INTEGRATED", "RECOVERY_AND_DISCONNECT_VALIDATION_REQUIRED",
    "FROZEN_COHORT_AND_QUALIFIED_DAYS_MISSING", "INDEPENDENT_OOS_EVIDENCE_MISSING",
)
ENGINE_BLOCKERS = (
    "OBSERVATION_SPAN_INSUFFICIENT", "OBSERVATION_SPAN_UNKNOWN", "QUALIFIED_OBSERVATION_UNKNOWN",
    "SOURCE_STALE", "SOURCE_UNKNOWN", "NATIVE_PROTECTION_UNCONFIRMED",
    "NATIVE_PROTECTION_UNKNOWN", "ENGINE_BUDGET_EXCEEDED", "ENGINE_BUDGET_UNKNOWN",
    "SHADOW_PROMOTION_NOT_AUTHORIZED",
)
_AMOUNT = re.compile(r"(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,2})?\Z", re.ASCII)
_SYMBOL = re.compile(r"[A-Z0-9]{2,24}USDT\Z", re.ASCII)


def _dict(value):
    return value if type(value) is dict else {}


def _time(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _now(value):
    if value is None:
        return datetime.now(UTC)
    result = value.astimezone(UTC) if isinstance(value, datetime) and value.tzinfo is not None else _time(value)
    if result is None:
        raise ValueError("Explicit UTC evaluation time required")
    return result


def _iso(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else None


def _number(value, *, maximum):
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if math.isfinite(value) and 0 <= value <= maximum else None
    except (ValueError, OverflowError):
        return None


def _decimal(value):
    if type(value) not in (str, int, float):
        return None
    try:
        raw = str(value)
        if len(raw) > 48:
            return None
        result = Decimal(raw)
        if (not result.is_finite() or not 0 <= result <= Decimal("1000000000000")
                or result.as_tuple().exponent < -12):
            return None
        return result
    except (InvalidOperation, ValueError):
        return None


def _text(value):
    if not value:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _proposal(value):
    if type(value) is not dict or set(value) != {"schema", "amount_usd"} or type(value["schema"]) is not int or value["schema"] != 1:
        return None
    amount = value["amount_usd"]
    if not isinstance(amount, str) or not _AMOUNT.fullmatch(amount):
        return None
    number = Decimal(amount)
    if not 0 < number <= Decimal("1000000000"):
        return None
    return {"schema": 1, "amount_usd": _text(number)}


def _closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON fields")
        result[key] = value
    return result


def read_proposal(path):
    """Read only an explicitly supplied small proposal; never create any file.

    Exact format: {"schema":1,"amount_usd":"100"}. Invalid, missing, linked or
    oversized files are absent evidence. An amount is never funded or approved.
    """
    try:
        source = Path(path)
        if source.is_symlink() or not source.is_file():
            return None
        with source.open("rb") as stream:
            raw = stream.read(MAX_PROPOSAL_BYTES + 1)
        if len(raw) > MAX_PROPOSAL_BYTES:
            return None
        value = json.loads(raw, object_pairs_hook=_closed_object,
                           parse_constant=lambda _: None)
        return _proposal(value)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return None


def _freshness(stamp, now, maximum):
    at = _time(stamp)
    if at is None or maximum is None or at > now:
        return "UNKNOWN"
    return "FRESH" if (now - at).total_seconds() <= maximum else "STALE"


def _latest_time(rows):
    if type(rows) is not list or not rows or len(rows) > 1000:
        return None
    # Source projections use chronological equity; do not search arbitrary text.
    return _dict(rows[-1]).get("created_at")


def _protection(rows, native, now, maximum):
    if type(rows) is not list or len(rows) > 100:
        return "UNKNOWN"
    if not rows:
        return "NOT_APPLICABLE"
    records = _dict(_dict(native).get("positions"))
    unknown = False
    for row in rows:
        row = _dict(row)
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            return "UNKNOWN"
        record = _dict(records.get(symbol))
        if not record or record.get("status") not in {"ARMED", "PENDING", "ERROR", "UNAVAILABLE", "RECONCILING", "REJECTED", "UNCONFIRMED", "SENDING", "UNSENT"}:
            unknown = True
            continue
        if record.get("status") != "ARMED":
            return "UNCONFIRMED"
        quantity, protected, unprotected = (_decimal(row.get("quantity")),
            _decimal(record.get("quantity")), _decimal(record.get("unprotected_quantity")))
        if (quantity is None or quantity <= 0 or protected is None or protected < quantity
                or unprotected is None or unprotected > 0
                or _freshness(record.get("confirmed_at"), now, maximum) != "FRESH"):
            unknown = True
    return "UNKNOWN" if unknown else "ARMED"


def _unknown_budget():
    return {"state": "UNKNOWN", "inclusive_stop_risk_usdt": None,
            "stop_risk_limit_usdt": None, "at": None}


def _budget(source, guardrails, now, maximum):
    source = _dict(source)
    risk, limit = _decimal(source.get("stop_loss_usdt")), _decimal(source.get("stop_loss_limit_usdt"))
    configured_limit = _decimal(_dict(guardrails).get("forward_total_stop_loss_usdt"))
    if (risk is None or limit is None or limit <= 0 or configured_limit != limit
            or _freshness(source.get("at"), now, maximum) != "FRESH"):
        return _unknown_budget()
    return {"state": "EXCEEDED" if risk > limit else "WITHIN_OBSERVED_LIMIT",
            "inclusive_stop_risk_usdt": _text(risk), "stop_risk_limit_usdt": _text(limit),
            "at": _iso(_time(source["at"]))}


def evaluate_live_preparation(payload, proposal=None, now=None):
    """Derive bounded observations; known gaps cannot be waived by input flags.

    No constructor, database, network, environment, model or trading API is used.
    Cached protection/budget observations certify neither future coverage nor a
    global account policy. Even a wholly positive input always remains BLOCKED.
    """
    instant, payload = _now(now), _dict(payload)
    status, futures = _dict(payload.get("status")), _dict(payload.get("futures_forward"))
    pulse, quant = _dict(payload.get("market_pulse")), _dict(payload.get("quant"))
    cycle = _number(status.get("cycle_seconds"), maximum=86400)
    maximum = cycle * 2 if cycle is not None and cycle >= 1 else None
    pulse_age = 30
    quant_age = _number(_dict(quant.get("limits")).get("stale_seconds"), maximum=3600)
    proposal = _proposal(proposal)
    result = {"schema": 1, "engine": "LIVE_PREPARATION", "mode": "READ_ONLY",
        "at": _iso(instant), "state": "BLOCKED", "autonomy_level": 0,
        "controls_enabled": False, "can_veto": False, "execution_enabled": False,
        "reservations_enabled": False, "promotion_allowed": False,
        "observation_days_required": 30, "automatic_activation": False,
        "capital_proposal": {"amount_usd": proposal["amount_usd"] if proposal else None,
            "status": "PROPOSED_NOT_ALLOCATED" if proposal else "NOT_PROVIDED",
            "daily_loss_limit_usd": None, "max_drawdown_pct": None},
        "blockers": list(GLOBAL_BLOCKERS), "engines": []}
    sources = (
        ("SPOT", "SPOT_TESTNET" if status.get("mode") == "TESTNET" else "PAPER" if status.get("mode") == "PAPER" else "UNKNOWN",
            _dict(payload.get("paper_scorecard")).get("observed_days"), _latest_time(payload.get("equity")), maximum,
            payload.get("positions"), status.get("native_protection")),
        ("FUTURES", "FUTURES_DEMO", _dict(futures.get("scorecard")).get("observed_days"),
            _latest_time(futures.get("equity")), maximum, futures.get("positions"), futures.get("native_protection")),
        ("AI_MARKET_PULSE", "SHADOW", _dict(pulse.get("performance")).get("observation_days"),
            pulse.get("updated_at"), pulse_age, None, None),
        ("QUANT_ARBITRAGE", "SHADOW", _dict(quant.get("performance")).get("observation_days"),
            quant.get("updated_at"), quant_age, None, None),
    )
    for identifier, environment, raw_days, stamp, max_age, positions, native in sources:
        days = _number(raw_days, maximum=36500)
        span = "UNKNOWN" if days is None else "SPAN_ONLY" if days >= 30 else "BELOW_30_DAYS"
        freshness = _freshness(stamp, instant, max_age)
        shadow = identifier in ENGINES[2:]
        protection = "NOT_APPLICABLE" if shadow or environment == "PAPER" else _protection(positions, native, instant, max_age)
        budget = _budget(futures.get("portfolio_budget"), futures.get("guardrails"), instant, max_age) if identifier == "FUTURES" else _unknown_budget()
        blockers = ["QUALIFIED_OBSERVATION_UNKNOWN"]
        if span != "SPAN_ONLY":
            blockers.append("OBSERVATION_SPAN_UNKNOWN" if days is None else "OBSERVATION_SPAN_INSUFFICIENT")
        if freshness != "FRESH":
            blockers.append("SOURCE_STALE" if freshness == "STALE" else "SOURCE_UNKNOWN")
        if protection in {"UNKNOWN", "UNCONFIRMED"}:
            blockers.append("NATIVE_PROTECTION_UNKNOWN" if protection == "UNKNOWN" else "NATIVE_PROTECTION_UNCONFIRMED")
        if budget["state"] != "WITHIN_OBSERVED_LIMIT":
            blockers.append("ENGINE_BUDGET_EXCEEDED" if budget["state"] == "EXCEEDED" else "ENGINE_BUDGET_UNKNOWN")
        if shadow:
            blockers.append("SHADOW_PROMOTION_NOT_AUTHORIZED")
        result["engines"].append({"id": identifier, "environment": environment, "state": "BLOCKED",
            "reported_span_days": days, "span_gate": span, "qualified_days": None,
            "qualified_state": "UNKNOWN", "freshness": freshness, "protection": protection,
            "budget": budget, "blockers": blockers})
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("Preparation projection exceeds closed budget")
    return result
