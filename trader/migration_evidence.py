"""Pure forward-receipt and joint-budget audits; never trading admission.

Receipts attest supplied observations, not exchange truth. Content addressing
detects changes against a retained digest; it cannot create a durable registry or
retroactively qualify legacy history. No database, provider or model is imported.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, InvalidOperation, localcontext
import hashlib
import json
import re

from .migration_costs import OrderCostScenario, SCENARIO_KEYS, evaluate_order_costs


MAX_RECEIPTS = 50_000
FINGERPRINT_KEYS = ("source", "strategy", "configuration", "ai_review", "execution", "cost_method")
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                        r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)\Z", re.ASCII)
_ENVIRONMENTS = {"SPOT": {"SPOT_TESTNET", "PAPER"}, "FUTURES": {"FUTURES_DEMO", "PAPER"},
                 "AI_MARKET_PULSE": {"SHADOW"}, "QUANT_ARBITRAGE": {"SHADOW"}}
REGISTRATION_KEYS = {"schema", "cohort_id", "engine", "environment", "registered_at", "starts_at",
                     "cadence_seconds", "max_receipt_delay_seconds", "fingerprints"}
RECEIPT_KEYS = {"receipt_id", "cohort_digest", "environment", "fingerprints", "interval_start",
                "interval_end", "available_at", "decided_at", "received_at", "evidence_kind",
                "evidence_digest", "source_complete", "reconciled", "costs_complete",
                "cashflows_complete", "protections_complete"}
_COMPLETE_KEYS = ("source_complete", "reconciled", "costs_complete", "cashflows_complete", "protections_complete")
_RECEIPT_ERRORS = {"CLOSED_RECEIPT_REQUIRED", "RECEIPT_ID_REQUIRED", "COHORT_OR_ENVIRONMENT_CHANGED",
    "CLOSED_FINGERPRINTS_REQUIRED", "SHA256_FINGERPRINTS_REQUIRED", "FROZEN_FINGERPRINT_CHANGED",
    "RETROSPECTIVE_OR_COUNTERFACTUAL_EVIDENCE_REJECTED", "SOURCE_EVIDENCE_DIGEST_REQUIRED",
    "INCOMPLETE_SOURCE_COST_CASHFLOW_RECONCILIATION_OR_PROTECTION", "EXPLICIT_UTC_TIMESTAMP_REQUIRED",
    "CADENCE_WINDOW_MISMATCH", "FUTURE_OR_UNAVAILABLE_DECISION_EVIDENCE", "LATE_BACKFILL_RECEIPT_REJECTED",
    "CONFLICTING_RECEIPT_ID", "CONFLICTING_RECEIPTS_FOR_WINDOW"}


def _authority():
    return {"execution_enabled": False, "promotion_allowed": False, "financial_authorization": False,
            "risk_change_allowed": False, "reservations_enabled": False, "automatic_activation": False,
            "live_implemented": False, "ready_for_live": False, "controls_enabled": False,
            "can_veto": False, "autonomy_level": 0}


def _closed(value, keys, code):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(code)
    return value


def _time(value):
    if type(value) is not str or not _TIMESTAMP.fullmatch(value):
        raise ValueError("EXPLICIT_UTC_TIMESTAMP_REQUIRED")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        raise ValueError("EXPLICIT_UTC_TIMESTAMP_REQUIRED") from None
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError("EXPLICIT_UTC_TIMESTAMP_REQUIRED")
    return result.astimezone(UTC)


def _iso(value):
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _fingerprints(value):
    _closed(value, FINGERPRINT_KEYS, "CLOSED_FINGERPRINTS_REQUIRED")
    if any(type(item) is not str or not _HASH.fullmatch(item) for item in value.values()):
        raise ValueError("SHA256_FINGERPRINTS_REQUIRED")
    return tuple((key, value[key]) for key in FINGERPRINT_KEYS)


@dataclass(frozen=True)
class ForwardCohort:
    """Validated immutable value; the owner must retain its digest independently."""
    cohort_id: str
    engine: str
    environment: str
    registered_at: datetime
    starts_at: datetime
    cadence_seconds: int
    max_receipt_delay_seconds: int
    fingerprints: tuple[tuple[str, str], ...]

    def as_dict(self):
        return {"schema": 1, "cohort_id": self.cohort_id, "engine": self.engine,
                "environment": self.environment, "registered_at": _iso(self.registered_at),
                "starts_at": _iso(self.starts_at), "cadence_seconds": self.cadence_seconds,
                "max_receipt_delay_seconds": self.max_receipt_delay_seconds,
                "fingerprints": dict(self.fingerprints)}

    @property
    def digest(self):
        return _digest(self.as_dict())


def register_forward_cohort(value):
    """Validate supplied prospective registration; does not save or backdate it."""
    _closed(value, REGISTRATION_KEYS, "CLOSED_REGISTRATION_REQUIRED")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("REGISTRATION_SCHEMA_REQUIRED")
    if type(value["cohort_id"]) is not str or not _ID.fullmatch(value["cohort_id"]):
        raise ValueError("COHORT_ID_REQUIRED")
    engine, environment = value["engine"], value["environment"]
    if (type(engine) is not str or engine not in _ENVIRONMENTS or type(environment) is not str
            or environment not in _ENVIRONMENTS[engine]):
        raise ValueError("OBSERVATION_ENVIRONMENT_REQUIRED")
    registered, starts = _time(value["registered_at"]), _time(value["starts_at"])
    if registered > starts:
        raise ValueError("RETROSPECTIVE_REGISTRATION_REJECTED")
    cadence, delay = value["cadence_seconds"], value["max_receipt_delay_seconds"]
    if type(cadence) is not int or not 60 <= cadence <= 86400 or 86400 % cadence:
        raise ValueError("CADENCE_MUST_DIVIDE_A_UTC_DAY")
    if type(delay) is not int or not 0 <= delay <= cadence:
        raise ValueError("RECEIPT_DELAY_BOUNDS")
    return ForwardCohort(value["cohort_id"], engine, environment, registered, starts,
                         cadence, delay, _fingerprints(value["fingerprints"]))


def _receipt_slot(row, cohort, instant):
    _closed(row, RECEIPT_KEYS, "CLOSED_RECEIPT_REQUIRED")
    if type(row["receipt_id"]) is not str or not _ID.fullmatch(row["receipt_id"]):
        raise ValueError("RECEIPT_ID_REQUIRED")
    if row["cohort_digest"] != cohort.digest or row["environment"] != cohort.environment:
        raise ValueError("COHORT_OR_ENVIRONMENT_CHANGED")
    if _fingerprints(row["fingerprints"]) != cohort.fingerprints:
        raise ValueError("FROZEN_FINGERPRINT_CHANGED")
    if row["evidence_kind"] != "OBSERVED_FORWARD":
        raise ValueError("RETROSPECTIVE_OR_COUNTERFACTUAL_EVIDENCE_REJECTED")
    if type(row["evidence_digest"]) is not str or not _HASH.fullmatch(row["evidence_digest"]):
        raise ValueError("SOURCE_EVIDENCE_DIGEST_REQUIRED")
    if any(type(row[key]) is not bool or not row[key] for key in _COMPLETE_KEYS):
        raise ValueError("INCOMPLETE_SOURCE_COST_CASHFLOW_RECONCILIATION_OR_PROTECTION")
    start, end, available, decision, received = (_time(row[key]) for key in
        ("interval_start", "interval_end", "available_at", "decided_at", "received_at"))
    difference = start - cohort.starts_at
    offset_us = (difference.days * 86400 + difference.seconds) * 1_000_000 + difference.microseconds
    cadence_us = cohort.cadence_seconds * 1_000_000
    if (offset_us < 0 or offset_us % cadence_us
            or end - start != timedelta(seconds=cohort.cadence_seconds)):
        raise ValueError("CADENCE_WINDOW_MISMATCH")
    if not start <= available <= decision or not end <= decision <= received <= instant:
        raise ValueError("FUTURE_OR_UNAVAILABLE_DECISION_EVIDENCE")
    if received - end > timedelta(seconds=cohort.max_receipt_delay_seconds):
        raise ValueError("LATE_BACKFILL_RECEIPT_REJECTED")
    return offset_us // cadence_us


def evaluate_forward_cohort(registration, receipts, *, now, expected_digest=None):
    """Count only complete supplied cadence receipts; never certify an account.

    Full days are rounded down within each uninterrupted run; disconnected partial
    days cannot be added into a qualified day. A historical span without receipts
    stays UNKNOWN. Thirty days never waives independent readiness requirements.
    """
    result = {"schema": 1, "mode": "READ_ONLY_FORWARD_RECEIPTS", "state": "INVALID_INPUT",
              **_authority(), "at": None, "cohort_id": None, "cohort_digest": None,
              "engine": None, "environment": None, "reported_span_days": None,
              "qualified_days": None, "continuous_qualified_days": None,
              "receipt_complete_days": None, "continuous_receipt_complete_days": None,
              "covered_seconds": 0, "matured_windows": 0, "missing_windows": None,
              "valid_receipts": 0, "invalid_receipts": 0, "duplicate_receipts": 0,
              "pending_windows": 0, "reason_codes": [], "receipt_rejections": {}, "receipt_set_digest": None,
              "closed_episodes": None, "net_return": None, "fees": None, "cashflow_adjusted_equity": None,
              "statistical_edge": "NOT_EVALUATED", "ai_attribution": "NOT_EVALUABLE",
              "limitations": ["SUPPLIED_RECEIPTS_NOT_EXCHANGE_CERTIFICATION",
                  "CONTENT_ADDRESSED_REGISTRATION_NOT_DURABLE_TRUST_ANCHOR",
                  "NO_LEGACY_BACKFILL_OR_SELL_ROW_EPISODE_INFERENCE",
                  "NO_FINANCIAL_METRICS_INFERRED_FROM_COMPLETENESS_FLAGS",
                  "NO_AUTOMATIC_THIRTY_DAY_APPROVAL", "INDEPENDENT_OOS_AND_OWNER_REVIEW_REQUIRED"]}
    try:
        instant = _time(now)
        cohort = register_forward_cohort(registration)
        if expected_digest is not None and (type(expected_digest) is not str
                or not _HASH.fullmatch(expected_digest) or expected_digest != cohort.digest):
            raise ValueError("RETAINED_REGISTRATION_DIGEST_MISMATCH")
        if cohort.registered_at > instant:
            raise ValueError("FUTURE_REGISTRATION_REJECTED")
        if type(receipts) is not list or len(receipts) > MAX_RECEIPTS:
            raise ValueError("BOUNDED_RECEIPT_LIST_REQUIRED")
        result.update(at=_iso(instant), cohort_id=cohort.cohort_id, cohort_digest=cohort.digest,
                      engine=cohort.engine, environment=cohort.environment)
        difference = instant - cohort.starts_at
        elapsed = max(0, difference.days * 86400 + difference.seconds)
        completed = elapsed // cohort.cadence_seconds
        matured = max(0, elapsed - cohort.max_receipt_delay_seconds) // cohort.cadence_seconds
        result.update(reported_span_days=elapsed / 86400, matured_windows=matured,
                      pending_windows=completed - matured)
        ids, windows, conflicts, reasons = {}, {}, set(), set()
        for row in receipts:
            try:
                slot = _receipt_slot(row, cohort, instant)
                digest = _digest(row)
                identity = row["receipt_id"]
                if identity in ids:
                    if ids[identity] == (digest, slot):
                        result["duplicate_receipts"] += 1
                        continue
                    conflicts.add(slot)
                    conflicts.add(ids[identity][1])
                    raise ValueError("CONFLICTING_RECEIPT_ID")
                ids[identity] = (digest, slot)
                if slot in windows:
                    conflicts.add(slot)
                    raise ValueError("CONFLICTING_RECEIPTS_FOR_WINDOW")
                windows[slot] = digest
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                result["invalid_receipts"] += 1
                # Closed diagnostic codes only; never echo supplied text.
                reasons.add("RECEIPT_REJECTED")
                code = str(error) if type(error) is ValueError and str(error) in _RECEIPT_ERRORS else "RECEIPT_INVALID"
                result["receipt_rejections"][code] = result["receipt_rejections"].get(code, 0) + 1
        for slot in conflicts:
            windows.pop(slot, None)
        slots = sorted(windows)
        result["valid_receipts"] = len(slots)
        result["covered_seconds"] = len(slots) * cohort.cadence_seconds
        result["missing_windows"] = matured - sum(slot < matured for slot in slots)
        result["receipt_set_digest"] = _digest([[slot, windows[slot]] for slot in slots])
        if slots:
            runs, length, previous = [], 0, None
            for slot in slots:
                if previous is not None and slot != previous + 1:
                    runs.append(length)
                    length = 0
                length += 1
                previous = slot
            runs.append(length)
            days = [length * cohort.cadence_seconds // 86400 for length in runs]
            result.update(receipt_complete_days=sum(days), continuous_receipt_complete_days=max(days))
            if expected_digest is not None:
                result.update(qualified_days=sum(days), continuous_qualified_days=max(days))
        else:
            reasons.add("NO_VALID_FORWARD_RECEIPTS")
        if result["missing_windows"]:
            reasons.add("MISSING_CADENCE_WINDOWS")
        if not expected_digest:
            reasons.add("RETAINED_REGISTRATION_ANCHOR_NOT_SUPPLIED")
        result["state"] = ("UNKNOWN" if not slots else "INCOMPLETE" if reasons
                           else "SUPPLIED_FORWARD_COVERAGE_ONLY")
        result["reason_codes"] = sorted(reasons) or ["NO_FINANCIAL_OR_LIVE_AUTHORITY"]
    except (ValueError, TypeError, KeyError, OverflowError):
        result["reason_codes"] = ["COHORT_INPUT_UNAVAILABLE_OR_INVALID"]
    return result


def _decimal(value):
    if type(value) is int:
        if value.bit_length() > 128:
            raise ValueError("DECIMAL_BOUNDS")
        value = str(value)
    if type(value) is str and 1 <= len(value) <= 80 and value == value.strip():
        try:
            value = Decimal(value)
        except InvalidOperation:
            raise ValueError("DECIMAL_REQUIRED") from None
    if (type(value) is not Decimal or not value.is_finite() or value.is_signed()
            or len(value.as_tuple().digits) > 48 or not -30 <= value.as_tuple().exponent <= 18
            or value > Decimal("1e18")):
        raise ValueError("DECIMAL_BOUNDS")
    return value


def _text(value):
    raw = format(value, "f")
    return raw.rstrip("0").rstrip(".") if "." in raw else raw


JOINT_KEYS = {"schema", "quote_asset", "capital_basis", "total_capital_usdt",
              "combined_stop_risk_cap_usdt", "proposal_amount_usd", "engines"}
JOINT_ENGINE_KEYS = {"engine", "environment", "allocation_usdt", "scenario"}


def evaluate_joint_budget(value):
    """Two explicit allocations under one hypothetical envelope, never wallets.

    Allocation and risk-budget sums are checked before sizing. There is no netting
    of LONG and SHORT stop risk, transfer, conversion, reservation or order call.
    """
    result = {"schema": 1, "mode": "HYPOTHETICAL_JOINT_BUDGET", "state": "INVALID_INPUT",
              **_authority(), "quote_asset": "USDT", "capital_basis": "EXPLICIT_HYPOTHETICAL_ALLOCATION",
              "feasible_hypothesis": False, "proposal_amount_usd": None,
              "total_capital_usdt": None, "allocated_capital_usdt": None,
              "unallocated_capital_usdt": None, "combined_stop_risk_cap_usdt": None,
              "combined_requested_risk_usdt": None, "combined_estimated_stop_risk_usdt": None,
              "combined_capital_required_usdt": None, "joint_scenario_digest": None,
              "reason_codes": [], "engines": [],
              "limitations": ["NOT_OBSERVED_WALLET_BALANCES_OR_SHARED_ACCOUNT_CERTIFICATION",
                  "SPOT_AND_FUTURES_ENVIRONMENTS_REMAIN_SEPARATE", "NO_USD_USDT_CONVERSION",
                  "NO_TRANSFERS_OR_CAPITAL_RESERVATIONS", "FUTURES_MARGIN_IS_UNCALIBRATED_PROXY",
                  "NO_EXISTING_POSITIONS_OR_ORDERS_IN_HYPOTHETICAL_ENVELOPE",
                  "NO_FUNDING_LIQUIDATION_OR_FEE_ASSET_SETTLEMENT_MODEL",
                  "STOP_RISK_IS_NOT_MAXIMUM_LOSS_GUARANTEE", "NO_STRATEGY_EDGE_OR_OWNER_POLICY_APPROVAL"]}
    try:
        _closed(value, JOINT_KEYS, "CLOSED_JOINT_SCENARIO_REQUIRED")
        if (type(value["schema"]) is not int or value["schema"] != 1
                or value["quote_asset"] != "USDT"
                or value["capital_basis"] != "EXPLICIT_HYPOTHETICAL_ALLOCATION"
                or type(value["engines"]) is not list or len(value["engines"]) != 2):
            raise ValueError("EXPLICIT_TWO_ENGINE_SIMULATION_REQUIRED")
        total, cap = _decimal(value["total_capital_usdt"]), _decimal(value["combined_stop_risk_cap_usdt"])
        if total <= 0 or cap <= 0:
            raise ValueError("POSITIVE_EXPLICIT_BUDGETS_REQUIRED")
        proposal = None if value["proposal_amount_usd"] is None else _decimal(value["proposal_amount_usd"])
        if proposal is not None and proposal <= 0:
            raise ValueError("POSITIVE_USD_PROPOSAL_REQUIRED")
        allocations, scenarios, identifiers = [], [], set()
        for row in value["engines"]:
            _closed(row, JOINT_ENGINE_KEYS, "CLOSED_ENGINE_SCENARIO_REQUIRED")
            engine = row["engine"]
            if type(engine) is not str or engine not in {"SPOT", "FUTURES"} or engine in identifiers:
                raise ValueError("ONE_SPOT_AND_ONE_FUTURES_REQUIRED")
            identifiers.add(engine)
            environment = "SPOT_SIMULATION" if engine == "SPOT" else "LINEAR_FUTURES_SIMULATION"
            if row["environment"] != environment:
                raise ValueError("SEPARATE_SIMULATION_ENVIRONMENTS_REQUIRED")
            _closed(row["scenario"], SCENARIO_KEYS, "CLOSED_ORDER_SCENARIO_REQUIRED")
            scenario = OrderCostScenario(**row["scenario"])
            allocation = _decimal(row["allocation_usdt"])
            if (scenario.venue != environment or scenario.quote_asset != "USDT"
                    or _decimal(scenario.available_capital) != allocation):
                raise ValueError("SCENARIO_CAPITAL_MUST_MATCH_EXPLICIT_ALLOCATION")
            allocations.append(allocation)
            scenarios.append((engine, environment, scenario))
        with localcontext(Context(prec=256, Emin=-999, Emax=999)):
            allocated = sum(allocations, Decimal(0))
            requested_risk = sum((_decimal(row[2].risk_budget) for row in scenarios), Decimal(0))
            result.update(total_capital_usdt=_text(total), allocated_capital_usdt=_text(allocated),
                proposal_amount_usd=_text(proposal) if proposal is not None else None,
                combined_stop_risk_cap_usdt=_text(cap), combined_requested_risk_usdt=_text(requested_risk))
            reasons = []
            if allocated > total:
                reasons.append("ALLOCATION_SUM_EXCEEDS_TOTAL_ENVELOPE")
            else:
                result["unallocated_capital_usdt"] = _text(total - allocated)
            if requested_risk > cap:
                reasons.append("REQUESTED_RISK_SUM_EXCEEDS_COMBINED_CAP")
            for engine, environment, scenario in scenarios:
                evaluated = evaluate_order_costs(scenario)
                result["engines"].append({"engine": engine, "environment": environment,
                    "allocation_usdt": _text(_decimal(scenario.available_capital)), "scenario": evaluated})
            result["joint_scenario_digest"] = _digest({"schema": 1, "total_capital_usdt": _text(total),
                "combined_stop_risk_cap_usdt": _text(cap), "proposal_amount_usd": result["proposal_amount_usd"],
                "engines": sorted([[row["engine"], row["allocation_usdt"], row["scenario"]["scenario_digest"]]
                                   for row in result["engines"]])})
            if any(not row["scenario"]["feasible_hypothesis"] for row in result["engines"]):
                reasons.append("ONE_OR_MORE_ENGINES_INFEASIBLE_OR_UNKNOWN")
            if all(row["scenario"]["estimated_stop_risk"] is not None for row in result["engines"]):
                stop_risk = sum((Decimal(row["scenario"]["estimated_stop_risk"]) for row in result["engines"]), Decimal(0))
                required = sum((Decimal(row["scenario"]["conservative_capital_required"]) for row in result["engines"]), Decimal(0))
                result.update(combined_estimated_stop_risk_usdt=_text(stop_risk), combined_capital_required_usdt=_text(required))
                if stop_risk > cap:
                    reasons.append("ESTIMATED_STOP_RISK_EXCEEDS_COMBINED_CAP")
                if required > total:
                    reasons.append("ESTIMATED_CAPITAL_EXCEEDS_TOTAL_ENVELOPE")
            result.update(state="REJECTED_HYPOTHESIS" if reasons else "FEASIBLE_HYPOTHESIS",
                          feasible_hypothesis=not reasons,
                          reason_codes=reasons or ["EXPLICIT_JOINT_MATHEMATICAL_RULES_SATISFIED_ONLY"])
    except (ValueError, TypeError, KeyError, InvalidOperation, ArithmeticError):
        result["reason_codes"] = ["JOINT_INPUT_UNAVAILABLE_OR_INVALID"]
    return result
