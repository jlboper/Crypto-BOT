"""Closed, credential-free research readiness; never a promotion decision.

The matrix describes evidence contained in an archived Research Lab run. It does
not infer the health, balances, profitability or authorization of operating bots.
Arbitrary text and model/provider content are deliberately not projected.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
import math
import time


ENGINES = ("SPOT", "FUTURES", "AI_MARKET_PULSE", "QUANT_ARBITRAGE")
MAX_BYTES = 12_000
REQUIREMENTS = ("VERIFIED_ACCOUNT_IDENTITY_AND_STARTING_INVENTORY",
    "FULL_ENTRY_EXIT_PARTIAL_CANCEL_AND_UNKNOWN_ORDER_RECONCILIATION",
    "COMMON_TRANSACTIONAL_RESERVATION_PROTOCOL",
    "APPROVED_GLOBAL_RISK_LIMITS_AND_PROTECTION_COVERAGE",
    "RESTART_AND_SIGNED_ROLLBACK_RECOVERY",
    "INDEPENDENT_FORWARD_AND_OUT_OF_SAMPLE_REVIEW")


def _dict(value):
    return value if isinstance(value, dict) else {}


def _rows(value, limit):
    return value[:limit] if isinstance(value, list) else []


def _count(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def _iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _at(value, cutoff):
    try:
        if not isinstance(value, str) or len(value) > 40:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        at = parsed.timestamp() if parsed.tzinfo is not None else None
        return _iso(at) if at is not None and 0 < at <= cutoff else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _method(present):
    return "METHODOLOGY_PRESENT_NOT_EXECUTION_VALIDATED" if present else "NOT_REPORTED"


def _review_attribution():
    return {"individual_ai": "NOT_EVALUABLE_NO_MATCHED_COUNTERFACTUAL_COHORT",
        "guardian": "NOT_EVALUABLE_LEVEL_0_NO_CONTROL_COHORT",
        "estimated_pnl_without_ai": None, "estimated_losses_avoided": None,
        "causal_claim_allowed": False}


def build_validation_summary(report, *, now=None):
    """Summarize known evidence without ranking incomparable environments.

    Passing a positive return, successful replay or an untrusted ``approved``
    field can never change any authority bit. Spot/Futures historical results
    describe the public-market research models, not the installed execution or
    AI-filtered strategy. An absent denominator remains unknown, including zero
    activity versus unavailable evidence.
    """
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now) or not 0 < now < 253402300799:
        raise ValueError("Invalid validation cutoff")
    report = _dict(report)
    source_at = _at(report.get("generated_at"), now)
    trusted = (source_at is not None and report.get("mode") == "RESEARCH_ONLY"
               and report.get("auto_promotion") is False)
    source = report if trusted else {}
    source_cutoff = datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00")).timestamp() if trusted else 0
    methodology = _dict(source.get("methodology"))
    forward = [_dict(row) for row in _rows(source.get("forward_observation"), 2)]
    baselines = [_dict(row) for row in _rows(source.get("operating_baselines"), 2)]
    engines = []
    for engine, key, maximum in (("SPOT", "assets", 30), ("FUTURES", "futures_assets", 15)):
        assets = [_dict(row) for row in _rows(source.get(key), maximum)]
        valid_assets = [row for row in assets if isinstance(row.get("symbol"), str)
                        and 1 <= len(row["symbol"]) <= 20]
        baseline = next((row for row in baselines if row.get("market") == engine
            and row.get("evidence") == "SIGNAL_PARITY_ONLY"
            and row.get("profitability_evaluated") is False), {})
        observation = next((row for row in forward if row.get("market") == engine), {})
        forward_state = observation.get("status")
        if forward_state not in {"OBSERVING", "WAITING_NEW_DATA", "DATA_UNAVAILABLE", "HISTORY_GAP"}:
            forward_state = "NOT_REPORTED"
        engines.append({"engine": engine, "evidence_environment": "PUBLIC_MARKET_RESEARCH",
            "state": "EXPLORATORY_RESEARCH_PRESENT" if valid_assets else "NOT_REPORTED",
            "evidence_at": source_at if trusted else None, "strategies_or_assets": len(valid_assets) if trusted else None,
            "operating_signal_reference": "SIGNAL_PARITY_ONLY" if baseline else "NOT_REPORTED",
            "execution_validated": False, "operational_profitability_evaluated": False,
            "walk_forward": _method(bool(valid_assets and methodology.get("validation"))),
            "reserved_holdout": _method(any(isinstance(row.get("holdout"), dict) for row in valid_assets)),
            "cost_stress": _method(any(isinstance(row.get("double_cost_holdout"), dict)
                or isinstance(_dict(row.get("holdout")).get("double_costs"), dict) for row in valid_assets)),
            "forward_state": forward_state, "replay": None,
            "attribution": _review_attribution(),
            "limitations": ["PUBLIC_MARKET_MODELS_NOT_OPERATING_FILLS_OR_AI_FILTER_REPLAY",
                "REPEATED_HOLDOUT_INSPECTION_IS_NOT_NEW_INDEPENDENT_EVIDENCE",
                "UNIVERSE_AND_MODEL_SELECTION_MULTIPLICITY_REMAIN"] +
                (["LIQUIDATION_STRESS_NOT_CONTRACT_CALIBRATED"] if engine == "FUTURES" else [])})
    pulse = _dict(source.get("market_pulse_observation"))
    pulse_at = _at(pulse.get("captured_at"), source_cutoff)
    pulse_valid = (pulse.get("engine") == "AI_MARKET_PULSE" and pulse.get("mode") == "SHADOW"
                   and pulse.get("automatic_promotion") is False and pulse_at is not None)
    pulse_replay = _dict(pulse.get("replay"))
    pulse_counts = [_count(pulse_replay.get(key)) for key in ("checked", "mismatches", "invalid_timestamps")]
    replay = None if not pulse_valid or any(value is None or value > 1000 for value in pulse_counts) else dict(
        zip(("checked", "mismatches", "invalid_timestamps"), pulse_counts))
    engines.append({"engine": "AI_MARKET_PULSE", "evidence_environment": "SHADOW",
        "state": "FORWARD_SHADOW_ONLY" if pulse_valid else "NOT_REPORTED",
        "evidence_at": pulse_at if pulse_valid else None,
        "strategies_or_assets": None, "operating_signal_reference": "NOT_APPLICABLE",
        "execution_validated": False, "operational_profitability_evaluated": False,
        "walk_forward": "NOT_REPORTED", "reserved_holdout": "NOT_REPORTED", "cost_stress": "NOT_REPORTED",
        "forward_state": "OBSERVED_JOURNAL" if pulse_valid and _count(pulse.get("decisions")) else "NOT_REPORTED",
        "replay": replay, "attribution": _review_attribution(),
        "limitations": ["CONTEMPORANEOUS_HISTORICAL_NEWS_AND_TICKS_INCOMPLETE",
            "FROZEN_SCORE_REPLAY_NOT_PORTFOLIO_OR_FILL_REPLAY", "FORWARD_OBSERVATION_NOT_INDEPENDENT_OOS"]})
    quant = _dict(source.get("quant_observation"))
    quant_at = _at(quant.get("captured_at"), source_cutoff)
    quant_valid = (quant.get("schema") == 1 and quant.get("engine") == "QUANT_ARBITRAGE"
        and quant.get("mode") == "SHADOW" and quant.get("execution_enabled") is False
        and quant.get("automatic_promotion") is False and quant_at is not None)
    quant_state = quant.get("state") if quant_valid else None
    if quant_state not in {"NOT_STARTED", "AVAILABLE", "PARTIAL", "UNAVAILABLE"}:
        quant_state = "NOT_REPORTED"
    quant_replay = _dict(quant.get("replay"))
    quant_checks = [_count(quant_replay.get(key)) for key in ("checked", "matches", "mismatches", "unavailable", "sampled")]
    coherent = (all(value is not None and value <= 16 for value in quant_checks)
                and quant_checks[0] == quant_checks[1]+quant_checks[2]
                and quant_checks[4] == quant_checks[0]+quant_checks[3])
    replay = None if not quant_valid or not coherent else dict(
        zip(("checked", "matches", "mismatches", "unavailable", "sampled"), quant_checks))
    engines.append({"engine": "QUANT_ARBITRAGE", "evidence_environment": "SHADOW",
        "state": quant_state, "evidence_at": quant_at if quant_valid else None,
        "strategies_or_assets": 2 if quant_valid and quant_state in {"AVAILABLE", "PARTIAL"} else None,
        "operating_signal_reference": "NOT_APPLICABLE", "execution_validated": False,
        "operational_profitability_evaluated": False, "walk_forward": "NOT_REPORTED",
        "reserved_holdout": "NOT_REPORTED", "cost_stress": "SIMULATION_HYPOTHESES_NOT_EXECUTION_VALIDATED",
        "forward_state": "OBSERVED_JOURNAL" if quant_valid and _count(_dict(quant.get("counts")).get("decisions")) else "NOT_REPORTED",
        "replay": replay, "attribution": _review_attribution(),
        "limitations": ["TWO_LEGS_ARE_NOT_AN_ATOMIC_EXCHANGE_HEDGE",
            "PER_LEG_FEES_SLIPPAGE_FUNDING_BASIS_AND_LEGGING_STRESS_ARE_HYPOTHESES",
            "MODEL_REPLAY_IS_A_BOUNDED_SAMPLE_NOT_EXECUTION_OR_OOS_VALIDATION",
            "STATISTICAL_ENTRIES_REMAIN_BLOCKED_CORRELATION_IS_INSUFFICIENT"]})
    result = {"schema": 1, "mode": "SHADOW", "autonomy_level": 0,
        "captured_at": _iso(now), "source_generated_at": source_at if trusted else None,
        "freshness": "ARCHIVED_RESEARCH_NOT_ENGINE_HEARTBEAT",
        "state": "EVIDENCE_PARTIAL" if trusted else "NOT_REPORTED",
        "execution_enabled": False, "controls_enabled": False, "reservations_enabled": False,
        "promotion_allowed": False, "engines": engines,
        "comparison": {"state": "NOT_COMPARABLE_NO_MATCHED_EXECUTION_COHORT",
            "aggregate_capital": None, "best_strategy": None,
            "reason": "ENVIRONMENTS_PERIODS_METHODS_AND_EXECUTION_EVIDENCE_DIFFER"},
        "control_preconditions": [{"id": item, "state": "NOT_CERTIFIED_BY_THIS_REPORT"} for item in REQUIREMENTS] +
            [{"id": "EXPLICIT_OWNER_AUTHORIZATION_FOR_EACH_AUTONOMY_TRANSITION", "state": "SEPARATE_AUTHORIZATION_REQUIRED"}],
        "limitations": ["METHODOLOGY_PRESENCE_DOES_NOT_CERTIFY_A_VALID_RESULT",
            "NO_AUTOMATIC_PROMOTION_OR_EFFECTIVE_CONTROL", "NO_LIVE_IMPLEMENTATION_OR_AUTHORIZATION"]}
    if len(json.dumps(result, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")) > MAX_BYTES:
        raise ValueError("Validation summary exceeds closed projection budget")
    return result
