"""Pure Guardian Shadow assessment; no files, network, databases or executors.

Thresholds are descriptive initial hypotheses, not
calibrated strategy parameters or permission to enter a trading account.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from statistics import pstdev
from typing import Literal, TypedDict

from trader.portfolio_guardian import build_guardian, guardian_unavailable

MAX_BYTES = 12_000
MAX_INPUT_BYTES = 256_000
ENGINES = ("SPOT", "FUTURES", "AI_MARKET_PULSE", "QUANT_ARBITRAGE")
SOURCE_KEYS = dict(zip(ENGINES, ("spot", "futures", "pulse", "quant")))
MAX_AGES = {"SPOT": 600, "FUTURES": 600, "AI_MARKET_PULSE": 30, "QUANT_ARBITRAGE": 90}
POLICY = {
    "id": "guardian-intelligence-shadow-v1", "calibrated": False,
    "regime_method": "BTC_SPOT_CLOSED_1M_60M_DESCRIPTIVE_PROXY",
    "window_minutes": 60, "minimum_closed_bars": 61,
    "maximum_bar_age_seconds": 90, "direction_return_pct": 1.0,
    "high_realized_volatility_pct": 1.5,
    "liquidity_max_spread_bps": 20.0, "liquidity_min_partial_depth_usdt": 10_000.0,
    "liquidity_drop_pct": -50.0,
    "source_maximum_age_seconds": dict(MAX_AGES),
}
LIMITATIONS = [
    "SHADOW_LEVEL_0_NO_ADMISSION_OR_EXECUTION",
    "INITIAL_DESCRIPTIVE_HYPOTHESES_NOT_CALIBRATED",
    "SCOPED_LEDGER_OBSERVATION_NOT_EXCHANGE_ACCOUNT_AUTHORITY",
    "NO_CROSS_ENVIRONMENT_FINANCIAL_TOTAL_OR_ASSUMED_HEDGE",
    "NOMINAL_STOP_DISTANCE_IS_NOT_INCLUSIVE_RISK",
    "MULTILEDGER_CAPTURE_IS_NOT_ATOMIC_PRE_SUBMIT_EVIDENCE",
    "CORRELATION_AND_COUNTERFACTUAL_EFFECTIVENESS_UNKNOWN",
    "HISTORICAL_BARS_RECEIVED_NOW_ARE_NOT_FORWARD_OOS",
]
_SYMBOL = re.compile(r"^[A-Z0-9]{2,24}USDT$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/-]{1,100}$")


class SourceMetadata(TypedDict):
    state: Literal["FRESH", "STALE", "UNKNOWN"]
    reason: str | None
    captured_at: str | None
    source_at: str | None
    available_at: str | None
    positions_seen: int | None
    positions_returned: int
    inventory_complete: bool


class ClosedBar(TypedDict):
    at: int
    received_at: float
    known_at: float
    price: float


class GuardianCapture(TypedDict):
    captured_at: str
    cutoff_at: float
    dashboard: dict
    source_metadata: dict[str, SourceMetadata]
    btc_closed_bars: list[ClosedBar]


def _dict(value):
    return value if isinstance(value, dict) else {}


def _num(value, minimum=None):
    if type(value) not in (int, float):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and (minimum is None or result >= minimum) else None


def _time(value):
    if isinstance(value, datetime):
        try:
            return value.timestamp() if value.tzinfo is not None and value.timestamp() > 0 else None
        except (ValueError, OverflowError, OSError):
            return None
    number = _num(value, 0)
    if number is not None:
        return number if 0 < number <= 253402300799 else None
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None and parsed.timestamp() > 0 else None
    except (ValueError, OverflowError, OSError):
        return None


def _iso(value):
    try:
        return datetime.fromtimestamp(value, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else None
    except (ValueError, OverflowError, OSError):
        return None


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _identifier(value):
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _fresh(stamp, cutoff, now, maximum):
    at = _time(stamp)
    return at is not None and at <= cutoff and 0 <= now-at <= maximum


def _liquidity(dashboard, cutoff, now):
    rows = _dict(dashboard.get("market_pulse")).get("market")
    result = {"state": "UNKNOWN", "at": None, "spread_bps": None,
              "partial_depth_usdt": None, "liquidity_change_pct": None}
    if not isinstance(rows, list):
        return result
    matches = [row for row in rows[:10] if isinstance(row, dict) and row.get("symbol") == "BTCUSDT"]
    if len(matches) != 1:
        return result
    row = matches[0]
    if row.get("fresh") is not True or row.get("complete") is not True or not _fresh(row.get("at"), cutoff, now, 30):
        return result
    spread, depth, change = _num(row.get("spread_bps"), 0), _num(row.get("depth_quote"), 0), _num(row.get("liquidity_change_pct"))
    if spread is None or depth is None or spread > 10_000 or depth > 1e18:
        return result
    stress = (spread >= POLICY["liquidity_max_spread_bps"] or depth < POLICY["liquidity_min_partial_depth_usdt"]
              or change is not None and change <= POLICY["liquidity_drop_pct"])
    result.update(state="STRESS" if stress else "OBSERVED", at=_iso(_time(row["at"])),
                  spread_bps=spread, partial_depth_usdt=depth, liquidity_change_pct=change)
    return result


def _regime(capture, dashboard, cutoff, now):
    result = {"state": "INSUFFICIENT_DATA", "method": POLICY["regime_method"],
              "window_minutes": 60, "observation_count": 0, "return_pct": None,
              "realized_volatility_pct": None, "first_market_at": None,
              "last_market_at": None, "latest_available_at": None,
              "evidence_cutoff": _iso(cutoff), "reason": "CLOSED_BAR_WINDOW_UNAVAILABLE",
              "liquidity": _liquidity(dashboard, cutoff, now)}
    raw = capture.get("btc_closed_bars")
    if not isinstance(raw, list) or len(raw) > 121:
        return result
    selected = {}
    for row in raw:
        if not isinstance(row, dict) or set(row) != {"at", "received_at", "known_at", "price"}:
            result["reason"] = "INVALID_CLOSED_BAR_EVIDENCE"
            return result
        at, received, known, price = (_num(row.get(key)) for key in ("at", "received_at", "known_at", "price"))
        if any(value is None for value in (at, received, known, price)):
            result["reason"] = "INVALID_CLOSED_BAR_EVIDENCE"
            return result
        if at > cutoff or received > cutoff or known > cutoff:
            continue  # Facts not yet known cannot enter this cutoff or replay.
        if at <= 0 or at % 60 or not at+5 <= received <= known or not 1e-12 <= price <= 1e12:
            result["reason"] = "INVALID_CLOSED_BAR_EVIDENCE"
            return result
        if at in selected:
            result["reason"] = "CONFLICTING_OR_DUPLICATE_CLOSED_BAR"
            return result
        selected[at] = row
    rows = sorted(selected.values(), key=lambda row: row["at"])[-61:]
    result["observation_count"] = len(rows)
    if len(rows) < 61:
        return result
    result.update(first_market_at=_iso(rows[0]["at"]), last_market_at=_iso(rows[-1]["at"]),
                  latest_available_at=_iso(max(row["known_at"] for row in rows)))
    if now-rows[-1]["at"] > 90:
        result["reason"] = "STALE_CLOSED_BAR_WINDOW"
        return result
    if any(b["at"]-a["at"] != 60 for a, b in zip(rows, rows[1:])):
        result["reason"] = "NONCONTIGUOUS_CLOSED_BAR_WINDOW"
        return result
    logs = [math.log(row["price"]) for row in rows]
    returns = [b-a for a, b in zip(logs, logs[1:])]
    change = (rows[-1]["price"]/rows[0]["price"]-1)*100
    volatility = pstdev(returns)*math.sqrt(60)*100
    state = ("LIQUIDITY_STRESS" if result["liquidity"]["state"] == "STRESS" else
             "HIGH_VOLATILITY" if volatility >= POLICY["high_realized_volatility_pct"] else
             "BULLISH" if change >= POLICY["direction_return_pct"] else
             "BEARISH" if change <= -POLICY["direction_return_pct"] else "SIDEWAYS")
    result.update(state=state, reason="INITIAL_DESCRIPTIVE_PROXY_ONLY", return_pct=change,
                  realized_volatility_pct=volatility)
    return result


def _review(dashboard, engine, cutoff):
    if engine == "SPOT":
        rows = dashboard.get("ai_reviews", dashboard.get("reviews", []))
    elif engine == "FUTURES":
        rows = _dict(dashboard.get("futures_forward")).get("last_ai_reviews", {})
        rows = list(rows.values())[:15] if isinstance(rows, dict) else rows
    else:
        return {"state": "NOT_APPLICABLE_OR_NOT_PROJECTED", "id": None, "at": None,
                "verdict": None, "confidence": None, "model": None}
    allowed = {"ALLOW", "REJECT", "REDUCE"} if engine == "SPOT" else {"ALLOW", "REJECT"}
    valid = []
    for row in rows[:50] if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        at = _time(row.get("created_at", row.get("at")))
        confidence = _num(row.get("confidence"), 0)
        if (at is not None and at <= cutoff and isinstance(row.get("verdict"), str)
                and row["verdict"] in allowed and confidence is not None and confidence <= 1):
            valid.append((at, row))
    if not valid:
        return {"state": "UNAVAILABLE", "id": None, "at": None, "verdict": None, "confidence": None, "model": None}
    at, row = max(valid, key=lambda item: item[0])
    identity = row.get("id")
    identity = str(identity) if type(identity) is int and identity >= 0 else _identifier(identity)
    return {"state": "OBSERVED_METADATA_ONLY", "id": identity, "at": _iso(at), "verdict": row["verdict"],
            "confidence": _num(row["confidence"]), "model": _identifier(row.get("model"))}


def _scope(engine, observed, metadata, alerts, dashboard, cutoff, now, input_valid):
    meta = _dict(metadata.get(SOURCE_KEYS[engine]))
    raw = (_dict(dashboard.get("status")) if engine == "SPOT" else _dict(dashboard.get("futures_forward")) if engine == "FUTURES"
           else _dict(dashboard.get("market_pulse")) if engine == "AI_MARKET_PULSE" else _dict(dashboard.get("quant")))
    positions = dashboard.get("positions") if engine == "SPOT" else raw.get("positions")
    source_at, available_at = _time(meta.get("source_at")), _time(meta.get("available_at"))
    count_seen, count_returned = meta.get("positions_seen"), meta.get("positions_returned")
    complete = (input_valid and meta.get("inventory_complete") is True
                and type(count_seen) is int and type(count_returned) is int
                and 0 <= count_seen == count_returned <= 40
                and isinstance(positions, list) and len(positions) == count_returned
                and meta.get("state") == "FRESH"
                and available_at is not None and available_at <= cutoff)
    assets = observed.get("assets", [])
    priced_by_cutoff = all(_time(asset.get("priced_at")) is not None and
                          _time(asset["priced_at"]) <= cutoff for asset in assets)
    fresh = (complete and _fresh(source_at, cutoff, now, MAX_AGES[engine])
             and observed.get("state") == "FRESH" and priced_by_cutoff)
    reasons = ["ACCOUNT_IDENTITY_AND_FULL_ORDER_INVENTORY_UNVERIFIED", "INCLUSIVE_GLOBAL_RISK_NOT_CERTIFIED"]
    state, allocation = "CAUTION", "KEEP_UNASSIGNED"
    if not complete:
        reasons.append("INCOMPLETE_OR_UNAVAILABLE_SOURCE")
    elif not fresh:
        reasons.append("STALE_OR_UNPRICED_SOURCE")
    scoped = {row.get("code") for row in alerts if row.get("scope") == engine}
    if scoped & {"INVALID_POSITION", "DUPLICATE_POSITION", "PROTECTIVE_THRESHOLD_CROSSED", "NATIVE_PROTECTION_UNCONFIRMED"}:
        state, allocation = "RECOVERY_REQUIRED", "REVIEW_PROTECTION_AND_RECONCILIATION"
        reasons.append("PROTECTION_OR_INVENTORY_REVIEW_REQUIRED")
    budgets = _dict(observed.get("budget_status"))
    if fresh and (budgets.get("gross") == "EXCEEDED" or budgets.get("stop_risk") == "OBSERVED_EXCEEDED"):
        if state != "RECOVERY_REQUIRED":
            state, allocation = "ENTRY_HALTED", "REVIEW_CURRENT_BUDGET_EXCESS"
        reasons.append("EXISTING_ENGINE_BUDGET_EXCEEDED")
    paused = raw.get("killed") is True or raw.get("paused") is True or raw.get("state") == "PAUSED"
    if paused and state != "RECOVERY_REQUIRED":
        state, allocation = "ENTRY_HALTED", "REVIEW_EXISTING_PAUSE"
        reasons.append("ORIGINAL_ENGINE_ENTRY_PAUSE_OBSERVED")
    if fresh and state == "CAUTION":
        gross, limit = _num(observed.get("gross_usdt"), 0), _num(_dict(observed.get("limits")).get("gross_usdt"), 0)
        if limit is not None and gross is not None and limit > 0 and gross == limit:
            state, allocation = "RISK_REDUCED", "REVIEW_NO_OBSERVED_GROSS_HEADROOM"
            reasons.append("EXISTING_GROSS_CEILING_REACHED")
    reported = raw.get("state")
    reported = reported if isinstance(reported, str) and reported in {"RUNNING", "PAUSED", "WAITING", "STOPPED", "NOT_STARTED", "DEGRADED", "SHADOW"} else None
    environment = observed.get("environment")
    environment = environment if isinstance(environment, str) and environment in {"SPOT_TESTNET", "FUTURES_DEMO", "PAPER", "SHADOW"} else "UNKNOWN"
    review_known = available_at is not None and available_at <= cutoff
    review = _review(dashboard if review_known else {}, engine, cutoff)
    return {"id": engine, "source_id": SOURCE_KEYS[engine], "environment": environment,
            "risk_state": state, "assessment": "WOULD_REVIEW", "authoritative": False,
            "reasons": reasons, "source_at": _iso(source_at), "available_at": _iso(available_at),
            "captured_at": _iso(_time(meta.get("captured_at"))), "inventory_complete": bool(complete),
            "data_state": "FRESH" if fresh else "UNKNOWN", "position_count": count_seen if complete else None,
            "current_caps": {key: _num(_dict(observed.get("limits")).get(key), 0) for key in ("gross_usdt", "stop_risk_usdt")},
            "observed_gross_usdt": _num(observed.get("gross_usdt"), 0) if fresh else None,
            "allocation": allocation, "reported_engine_state": reported, "liveness": "NOT_ASSERTED_BY_DATA_AGE",
            "latest_original_review": review}


def build_intelligence(capture: GuardianCapture | dict | None,
                       now: float | datetime | str | None = None) -> dict:
    """Return a bounded deterministic Shadow assessment; input is never mutated.

    With no explicit now, cutoff_at is the replay instant, never wall-clock time.
    Original metadata is contemporaneous observation, not a complete proposal.
    """
    valid = isinstance(capture, dict)
    capture = capture if valid else {}
    try:
        encoded = _json(capture).encode()
        if len(encoded) > MAX_INPUT_BYTES:
            raise ValueError("Unbounded capture")
        digest = hashlib.sha256(encoded).hexdigest()
    except (ValueError, TypeError, OverflowError, RecursionError):
        capture, valid = {}, False
        digest = _digest({"invalid_capture": True})
    if (type(capture.get("schema", 1)) is not int or capture.get("schema", 1) != 1
            or any(capture.get(flag, False) is not False
            for flag in ("execution_enabled", "promotion_allowed"))):
        capture, valid = {}, False
    cutoff = _time(capture.get("cutoff_at"))
    instant = _time(now) if now is not None else cutoff
    if cutoff is None or instant is None or instant < cutoff:
        capture, valid, cutoff, instant = {}, False, 1.0, 1.0
    dashboard = _dict(capture.get("dashboard"))
    try:
        observed = build_guardian(dashboard, now=instant)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        observed, valid = guardian_unavailable(instant), False
    lookup = {row["id"]: row for row in observed["scopes"]}
    metadata = _dict(capture.get("source_metadata"))
    scopes = [_scope(engine, lookup[engine], metadata, observed["alerts"], dashboard, cutoff, instant, valid) for engine in ENGINES]
    for scope in scopes:
        scope["evidence_id"] = _digest({"capture_digest": digest, "engine": scope["id"], "cutoff": cutoff})
    conflicts = []
    for row in observed["overlaps"][:10]:
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            continue
        members = sorted({(scope["id"], asset["direction"]) for scope in observed["scopes"] for asset in scope["assets"]
                          if asset.get("symbol") == symbol and asset.get("direction") in {"LONG", "SHORT", "UNKNOWN"}})
        conflicts.append({"symbol": symbol, "members": [{"engine": engine, "direction": direction} for engine, direction in members],
                          "classification": "OPPOSING_CROSS_SCOPE_OBSERVATION" if {direction for _, direction in members} >= {"LONG", "SHORT"} else "SAME_ASSET_CROSS_SCOPE_OBSERVATION",
                          "hedge_verified": False, "allocation_action": "REVIEW_CROSS_SCOPE_OVERLAP"})
    result = {"schema": 1, "engine": "GUARDIAN_INTELLIGENCE", "mode": "SHADOW", "autonomy_level": 0,
              "controls_enabled": False, "can_veto": False, "execution_enabled": False, "reservations_enabled": False,
              "promotion_allowed": False,
              "assessment_id": _digest({"source_digest": digest, "policy": POLICY, "cutoff": cutoff, "as_of": instant}),
              "policy": json.loads(_json(POLICY)), "at": _iso(instant) if valid else None, "captured_at": _iso(_time(capture.get("captured_at"))),
              "cutoff_at": _iso(cutoff) if valid else None,
              "state": "OBSERVING" if valid and all(scope["data_state"] == "FRESH" for scope in scopes) else "PARTIAL",
              "regime": _regime(capture, dashboard, cutoff, instant), "scopes": scopes, "conflicts": conflicts,
              "correlation": {"state": "UNKNOWN", "reason": "JOINT_VALIDATED_HISTORY_NOT_AVAILABLE"},
              "counterfactual": {"state": "UNKNOWN", "losses_avoided": None, "without_ai_pnl": None,
                                 "reason": "COMPARABLE_PREREGISTERED_COHORT_NOT_AVAILABLE"},
              "evidence": {"source_digest": digest, "source_ids": [SOURCE_KEYS[engine] for engine in ENGINES],
                           "original_decision_completeness": "NOT_PRE_SUBMIT_COMPLETE", "input_valid": bool(valid)},
              "limitations": list(LIMITATIONS), "truncation": {"conflicts_omitted": 0}}
    if not valid:
        result["regime"]["evidence_cutoff"] = None
    while len(_json(result).encode()) > MAX_BYTES and result["conflicts"]:
        result["conflicts"].pop()
        result["truncation"]["conflicts_omitted"] += 1
    if len(_json(result).encode()) > MAX_BYTES:
        raise ValueError("Guardian Intelligence projection exceeds fixed bound")
    return result
