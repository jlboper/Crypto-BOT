"""Pure, unintegrated admission simulation with explicitly supplied risk budgets.

Every account/actor/policy identity is SIM_*. Values use the Capital Manager's
integer micro-USDT units. No broker, network, filesystem or model is consulted.
Inputs are synthetic assertions, not certification of Binance accounts. Existing
protective orders and trading decisions cannot call or depend on this module.
Loss states are snapshot assessments, without persistent loss latches or UTC
resets. Margin/cost floors are conservative hypotheses, not exchange calibration.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .capital_manager_shadow import AccountScope, MAX_INTEGER, SimulationError


STATES = ("NORMAL", "CAUTION", "RISK_REDUCED", "ENTRY_HALTED", "RECOVERY_REQUIRED")
ID = re.compile(r"^SIM_[A-Za-z0-9_-]{1,80}$")
SYMBOL = re.compile(r"^[A-Z0-9]{2,24}USDT$")


def _id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise SimulationError("EXPLICIT_SIMULATION_ID_REQUIRED")


def _units(value, *, positive=False, signed=False):
    if (type(value) is not int or abs(value) > MAX_INTEGER
            or not signed and value < 0 or positive and value <= 0):
        raise SimulationError("INTEGER_ATOMIC_MONEY_REQUIRED")


def _at(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 253402300799:
        raise SimulationError("INVALID_SIMULATION_TIME")


def _fact(value):
    if value is not None and type(value) is not bool:
        raise SimulationError("EXPLICIT_SIMULATION_FACT_REQUIRED")


@dataclass(frozen=True)
class Exposure:
    exposure_id: str
    engine_id: str
    symbol: str
    direction: str
    gross_units: int
    inclusive_stop_risk_units: int | None
    leverage_milli: int
    correlation_group: str
    market_at: float
    protection_verified: bool | None

    def __post_init__(self):
        for value in (self.exposure_id, self.engine_id, self.correlation_group):
            _id(value)
        if not isinstance(self.symbol, str) or not SYMBOL.fullmatch(self.symbol) or self.direction not in {"LONG", "SHORT"}:
            raise SimulationError("INVALID_SIMULATED_EXPOSURE")
        _units(self.gross_units, positive=True)
        if self.inclusive_stop_risk_units is not None:
            _units(self.inclusive_stop_risk_units, positive=True)
        if type(self.leverage_milli) is not int or not 1000 <= self.leverage_milli <= 125000:
            raise SimulationError("EXPLICIT_SIMULATED_LEVERAGE_REQUIRED")
        _at(self.market_at)
        _fact(self.protection_verified)


@dataclass(frozen=True)
class RiskPolicy:
    policy_id: str
    scope: AccountScope
    approved_at: float
    gross_limit_units: int
    stop_risk_limit_units: int
    max_positions: int
    max_leverage_milli: int
    # (identity, gross limit, inclusive stop-risk limit), supplied for every group.
    engine_limits: tuple[tuple[str, int, int], ...]
    asset_limits: tuple[tuple[str, int, int], ...]
    correlation_limits: tuple[tuple[str, int, int], ...]
    daily_loss_limit_units: int
    weekly_loss_limit_units: int
    drawdown_limit_units: int
    caution_fraction_ppm: int
    reduced_fraction_ppm: int
    reduced_candidate_risk_cap_units: int
    max_data_age_seconds: int
    max_slippage_bps: int
    max_spread_bps: int

    def __post_init__(self):
        _id(self.policy_id)
        if not isinstance(self.scope, AccountScope):
            raise SimulationError("EXPLICIT_SIMULATION_SCOPE_REQUIRED")
        _at(self.approved_at)
        for value in (self.gross_limit_units, self.stop_risk_limit_units, self.daily_loss_limit_units,
                      self.weekly_loss_limit_units, self.drawdown_limit_units, self.reduced_candidate_risk_cap_units):
            _units(value, positive=True)
        if self.reduced_candidate_risk_cap_units > self.stop_risk_limit_units:
            raise SimulationError("REDUCED_CAP_CANNOT_INCREASE_POLICY")
        if (type(self.max_positions) is not int or not 1 <= self.max_positions <= 100
                or type(self.max_leverage_milli) is not int or not 1000 <= self.max_leverage_milli <= 125000
                or type(self.caution_fraction_ppm) is not int or type(self.reduced_fraction_ppm) is not int
                or not 0 < self.caution_fraction_ppm < self.reduced_fraction_ppm < 1_000_000
                or type(self.max_data_age_seconds) is not int or not 1 <= self.max_data_age_seconds <= 3600
                or type(self.max_slippage_bps) is not int or not 0 <= self.max_slippage_bps <= 10000
                or type(self.max_spread_bps) is not int or not 0 <= self.max_spread_bps <= 10000):
            raise SimulationError("BOUNDED_EXPLICIT_POLICY_REQUIRED")
        for category, rows in (("engine", self.engine_limits), ("asset", self.asset_limits), ("correlation", self.correlation_limits)):
            if not isinstance(rows, tuple) or not 1 <= len(rows) <= 32:
                raise SimulationError("COMPLETE_IMMUTABLE_SCOPE_LIMITS_REQUIRED")
            seen = set()
            for row in rows:
                if not isinstance(row, tuple) or len(row) != 3:
                    raise SimulationError("COMPLETE_IMMUTABLE_SCOPE_LIMITS_REQUIRED")
                key, gross, risk = row
                if category == "asset":
                    if not isinstance(key, str) or not SYMBOL.fullmatch(key):
                        raise SimulationError("INVALID_SIMULATED_ASSET")
                else:
                    _id(key)
                _units(gross, positive=True); _units(risk, positive=True)
                if key in seen or gross > self.gross_limit_units or risk > self.stop_risk_limit_units:
                    raise SimulationError("SCOPE_LIMIT_CANNOT_INCREASE_GLOBAL_POLICY")
                seen.add(key)


@dataclass(frozen=True)
class Inventory:
    scope: AccountScope
    observed_at: float
    account_identity_verified: bool | None
    inventory_complete: bool | None
    reconciliation_complete: bool | None
    available_margin_units: int | None
    margin_is_net_of_commitments: bool | None
    daily_pnl_units: int | None
    weekly_pnl_units: int | None
    drawdown_units: int | None
    loss_baselines_verified: bool | None
    correlation_evidence_verified: bool | None
    exchange_state: str
    manual_entry_halt: bool
    positions: tuple[Exposure, ...]
    pending: tuple[Exposure, ...]

    def __post_init__(self):
        if not isinstance(self.scope, AccountScope):
            raise SimulationError("EXPLICIT_SIMULATION_SCOPE_REQUIRED")
        _at(self.observed_at)
        for value in (self.account_identity_verified, self.inventory_complete, self.reconciliation_complete,
                      self.margin_is_net_of_commitments, self.loss_baselines_verified, self.correlation_evidence_verified):
            _fact(value)
        if self.available_margin_units is not None:
            _units(self.available_margin_units)
        for value in (self.daily_pnl_units, self.weekly_pnl_units):
            if value is not None:
                _units(value, signed=True)
        if self.drawdown_units is not None:
            _units(self.drawdown_units)
        if self.exchange_state not in {"READY", "UNAVAILABLE", "UNKNOWN"} or type(self.manual_entry_halt) is not bool:
            raise SimulationError("INVALID_SIMULATED_OPERATIONAL_STATE")
        for rows in (self.positions, self.pending):
            if not isinstance(rows, tuple) or len(rows) > 100 or any(not isinstance(row, Exposure) for row in rows):
                raise SimulationError("BOUNDED_IMMUTABLE_INVENTORY_REQUIRED")
        ids = [row.exposure_id for row in self.positions+self.pending]
        if len(ids) != len(set(ids)):
            raise SimulationError("DUPLICATE_SIMULATED_EXPOSURE")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    scope: AccountScope
    observed_at: float
    legs: tuple[Exposure, ...]
    required_margin_units: int
    estimated_fee_bps: int | None
    estimated_slippage_bps: int | None
    spread_bps: int | None
    liquidity_verified: bool | None

    def __post_init__(self):
        _id(self.candidate_id)
        if not isinstance(self.scope, AccountScope):
            raise SimulationError("EXPLICIT_SIMULATION_SCOPE_REQUIRED")
        _at(self.observed_at)
        if (not isinstance(self.legs, tuple) or not 1 <= len(self.legs) <= 4
                or any(not isinstance(row, Exposure) for row in self.legs)
                or len({row.exposure_id for row in self.legs}) != len(self.legs)):
            raise SimulationError("COMPLETE_ATOMIC_LEGS_REQUIRED")
        _units(self.required_margin_units, positive=True)
        for value in (self.estimated_fee_bps, self.estimated_slippage_bps, self.spread_bps):
            if value is not None and (type(value) is not int or not 0 <= value <= 10000):
                raise SimulationError("INVALID_SIMULATED_EXECUTION_COST")
        _fact(self.liquidity_verified)


def assess_risk(policy: RiskPolicy, inventory: Inventory, candidate: Candidate, *, now: float):
    """Produce an explainable before/after simulation, without reserving money.

    Gross notional and inclusive stop risk add every leg, including opposite
    directions and pending entries. No offset or automatic hedge credit exists.
    Reduced risk uses the explicit scenario cap; it never raises another limit.
    Unknown evidence fails closed locally in this simulation only.
    """
    if not isinstance(policy, RiskPolicy) or not isinstance(inventory, Inventory) or not isinstance(candidate, Candidate):
        raise SimulationError("TYPED_SIMULATION_INPUTS_REQUIRED")
    _at(now)
    reasons, recovery = [], []
    inventory_scope_matches = policy.scope == inventory.scope
    candidate_scope_matches = policy.scope == candidate.scope
    if not inventory_scope_matches or not candidate_scope_matches:
        recovery.append("ACCOUNT_OR_ENVIRONMENT_SCOPE_MISMATCH")
    if policy.approved_at > now:
        recovery.append("POLICY_NOT_AVAILABLE_AT_DECISION")
    if inventory.account_identity_verified is not True:
        recovery.append("ACCOUNT_IDENTITY_UNVERIFIED")
    if inventory.inventory_complete is not True:
        recovery.append("INVENTORY_INCOMPLETE_OR_UNKNOWN")
    if inventory.reconciliation_complete is not True:
        recovery.append("ORDER_RECONCILIATION_INCOMPLETE_OR_UNKNOWN")
    if inventory.available_margin_units is None or inventory.margin_is_net_of_commitments is not True:
        recovery.append("AVAILABLE_MARGIN_UNKNOWN")
    if inventory.loss_baselines_verified is not True or any(value is None for value in (
        inventory.daily_pnl_units, inventory.weekly_pnl_units, inventory.drawdown_units)):
        recovery.append("LOSS_BASELINES_OR_METRICS_UNKNOWN")
    if inventory.correlation_evidence_verified is not True:
        recovery.append("CORRELATION_GROUP_EVIDENCE_UNVERIFIED")
    if inventory.exchange_state != "READY":
        reasons.append("EXCHANGE_NOT_READY")
    if inventory.manual_entry_halt:
        reasons.append("MANUAL_ENTRY_HALT")
    all_existing = inventory.positions+inventory.pending if inventory_scope_matches else ()
    candidate_legs = candidate.legs if candidate_scope_matches else ()
    all_after = all_existing+candidate_legs
    if len({row.exposure_id for row in all_after}) != len(all_after):
        recovery.append("DUPLICATE_EXPOSURE_ID")
    if any(row.protection_verified is not True for row in all_existing):
        recovery.append("EXISTING_PROTECTION_MISSING_OR_UNKNOWN")
    if any(row.protection_verified is not True for row in candidate_legs):
        reasons.append("CANDIDATE_PROTECTION_PLAN_UNVERIFIED")
    if any(row.inclusive_stop_risk_units is None for row in all_after):
        recovery.append("INCLUSIVE_STOP_RISK_UNKNOWN")
    times = (inventory.observed_at, candidate.observed_at)+tuple(row.market_at for row in all_after)
    if any(at > now or now-at > policy.max_data_age_seconds for at in times):
        reasons.append("STALE_OR_FUTURE_DATA")
    if candidate.liquidity_verified is not True:
        reasons.append("LIQUIDITY_UNVERIFIED")
    if (candidate.estimated_slippage_bps is None or candidate.spread_bps is None
            or candidate.estimated_slippage_bps > policy.max_slippage_bps or candidate.spread_bps > policy.max_spread_bps):
        reasons.append("EXECUTION_COSTS_UNKNOWN_OR_EXCESSIVE")
    if candidate.estimated_fee_bps is None:
        reasons.append("EXECUTION_FEES_UNKNOWN")
    minimum_margin = cost_floor = None
    if candidate.estimated_fee_bps is not None and candidate.estimated_slippage_bps is not None:
        # Independent integer ceilings for every leg: no cross-leg margin or
        # hedge credit. Reserve full round-trip fees/slippage as a conservative
        # buffer. This is not a Binance margin, liquidation or fee-tier formula.
        floor_by_leg = [(row.gross_units*(2*candidate.estimated_fee_bps+2*candidate.estimated_slippage_bps)+9999)//10000
                        for row in candidate_legs]
        cost_floor = sum(floor_by_leg)
        principal_floor = sum((row.gross_units*1000+row.leverage_milli-1)//row.leverage_milli
                              for row in candidate_legs)
        minimum_margin = principal_floor+cost_floor
        if candidate.required_margin_units < minimum_margin:
            reasons.append("REQUIRED_MARGIN_BELOW_CONSERVATIVE_FLOOR")
        if any(row.inclusive_stop_risk_units is not None and row.inclusive_stop_risk_units < floor
               for row,floor in zip(candidate_legs,floor_by_leg)):
            reasons.append("INCLUSIVE_STOP_RISK_BELOW_COST_FLOOR")
    if inventory.available_margin_units is not None and candidate.required_margin_units > inventory.available_margin_units:
        reasons.append("INSUFFICIENT_AVAILABLE_MARGIN")
    if any(row.leverage_milli > policy.max_leverage_milli for row in all_after):
        reasons.append("LEVERAGE_LIMIT_EXCEEDED")
    if len(all_after) > policy.max_positions:
        reasons.append("POSITION_LIMIT_EXCEEDED")
    gross_before = sum(row.gross_units for row in all_existing)
    gross_after = sum(row.gross_units for row in all_after)
    risk_known = all(row.inclusive_stop_risk_units is not None for row in all_after)
    risk_before = (sum(row.inclusive_stop_risk_units for row in all_existing)
                   if all(row.inclusive_stop_risk_units is not None for row in all_existing) else None)
    risk_after = sum(row.inclusive_stop_risk_units for row in all_after) if risk_known else None
    candidate_risk = (sum(row.inclusive_stop_risk_units for row in candidate_legs)
                      if all(row.inclusive_stop_risk_units is not None for row in candidate_legs) else None)
    aggregate_overflow = any(value is not None and value > MAX_INTEGER
                             for value in (gross_before,gross_after,risk_before,risk_after,candidate_risk,minimum_margin,cost_floor))
    if aggregate_overflow:
        recovery.append("AGGREGATE_ATOMIC_MONEY_RANGE_EXCEEDED")
    if gross_after > policy.gross_limit_units:
        reasons.append("GLOBAL_GROSS_LIMIT_EXCEEDED")
    if risk_after is not None and risk_after > policy.stop_risk_limit_units:
        reasons.append("GLOBAL_STOP_RISK_LIMIT_EXCEEDED")
    for category, rows, key in (("ENGINE", policy.engine_limits, "engine_id"),
                                ("ASSET", policy.asset_limits, "symbol"),
                                ("CORRELATION", policy.correlation_limits, "correlation_group")):
        limits = {name:(gross,risk) for name,gross,risk in rows}
        for name in dict.fromkeys(getattr(row,key) for row in all_after):
            members = [row for row in all_after if getattr(row,key) == name]
            if name not in limits:
                recovery.append(category+"_BUDGET_UNKNOWN")
            else:
                gross_cap, risk_cap = limits[name]
                if sum(row.gross_units for row in members) > gross_cap:
                    reasons.append(category+"_GROSS_LIMIT_EXCEEDED")
                if all(row.inclusive_stop_risk_units is not None for row in members) and sum(row.inclusive_stop_risk_units for row in members) > risk_cap:
                    reasons.append(category+"_STOP_RISK_LIMIT_EXCEEDED")
    caution = reduced = False
    for metric, value, cap in (("DAILY_LOSS", None if inventory.daily_pnl_units is None else max(0,-inventory.daily_pnl_units), policy.daily_loss_limit_units),
                               ("WEEKLY_LOSS", None if inventory.weekly_pnl_units is None else max(0,-inventory.weekly_pnl_units), policy.weekly_loss_limit_units),
                               ("DRAWDOWN", inventory.drawdown_units, policy.drawdown_limit_units)):
        if value is None:
            continue
        if value >= cap:
            reasons.append(metric+"_LIMIT_REACHED")
        elif value*1_000_000 >= cap*policy.reduced_fraction_ppm:
            reduced = True
        elif value*1_000_000 >= cap*policy.caution_fraction_ppm:
            caution = True
    if reduced and candidate_risk is not None and candidate_risk > policy.reduced_candidate_risk_cap_units:
        reasons.append("REDUCED_CANDIDATE_RISK_CAP_EXCEEDED")
    state = ("RECOVERY_REQUIRED" if recovery else "ENTRY_HALTED" if reasons else
             "RISK_REDUCED" if reduced else "CAUTION" if caution else "NORMAL")
    return {"schema":1, "mode":"SHADOW", "authority":"UNINTEGRATED_SIMULATION_ONLY", "state":state,
        "policy_id":policy.policy_id, "candidate_id":candidate.candidate_id,
        "environment":policy.scope.environment, "account_id":policy.scope.account_id,
        "at":float(now), "hypothetical_admission":not recovery and not reasons,
        "reasons":list(dict.fromkeys(recovery+reasons)),
        "before":{"gross_units":gross_before if inventory_scope_matches and gross_before <= MAX_INTEGER else None,
                  "inclusive_stop_risk_units":risk_before if inventory_scope_matches and (risk_before is None or risk_before <= MAX_INTEGER) else None,
                  "positions":len(all_existing) if inventory_scope_matches else None},
        "after":{"gross_units":gross_after if inventory_scope_matches and candidate_scope_matches and gross_after <= MAX_INTEGER else None,
                 "inclusive_stop_risk_units":risk_after if inventory_scope_matches and candidate_scope_matches and (risk_after is None or risk_after <= MAX_INTEGER) else None,
                 "positions":len(all_after) if inventory_scope_matches and candidate_scope_matches else None},
        "candidate_inclusive_stop_risk_units":candidate_risk if candidate_scope_matches and (candidate_risk is None or candidate_risk <= MAX_INTEGER) else None,
        "conservative_margin_floor_units":minimum_margin if candidate_scope_matches and minimum_margin is not None and minimum_margin <= MAX_INTEGER else None,
        "roundtrip_cost_floor_units":cost_floor if candidate_scope_matches and cost_floor is not None and cost_floor <= MAX_INTEGER else None,
        "reduced_candidate_risk_cap_units":policy.reduced_candidate_risk_cap_units if reduced else None,
        "execution_enabled":False, "controls_enabled":False, "can_veto":False,
        "reservations_enabled":False, "promotion_allowed":False,
        "limitation":"SYNTHETIC_ASSERTIONS_NOT_ACCOUNT_CERTIFICATION_OR_EXCHANGE_EXECUTION_VALIDATION"}
