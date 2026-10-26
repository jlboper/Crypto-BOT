"""Prepared deterministic capital/risk boundary, never an exchange executor.

One designated SQLite file binds one (account, environment, settlement currency)
and one immutable, explicit policy. Loss observations, latches, gross/stop-risk
admission, reservations and single submission intentions share BEGIN IMMEDIATE.
No netting, timeout release, automatic order retry, credential, network or AI exists.

observe() records real proposals without veto/reservation. The only capability
issuer in this module is simulation_capability(), restricted to SHADOW/PAPER.
TESTNET/DEMO/LIVE reserve/claim require an explicitly injected external verifier
and its signed/otherwise authenticated owner capability. Absent verifier fails
closed. Policy and exact proposal terms, scope, approval ID and expiry are bound.
Protective exits must never depend on this entry-only component.

Facts are typed caller attestations, not independent account certification. The
store is durable/transactional, not tamper-proof, and cannot make multiple exchange
legs atomic. Cashflow-adjusted drawdown uses observed peaks only. No background
collector, account valuation, stop execution or cross-wallet sum is performed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time


APP = "CENTRAL_ADMISSION_V1"
MAX_UNITS = 9_000_000_000_000_000
_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_SYMBOL = re.compile(r"^[A-Z0-9]{2,24}USDT$")
_ENVIRONMENTS = {"SHADOW", "PAPER", "SPOT_TESTNET", "FUTURES_DEMO", "SPOT_LIVE", "FUTURES_LIVE"}
_ACTIVE = {"RESERVED", "SUBMITTING", "UNKNOWN", "PARTIAL", "OPEN", "RECOVERY_REQUIRED"}
_CAPABILITY_SECRET = object()


class AdmissionError(ValueError):
    """Closed, non-secret-bearing validation or store identity failure."""


def _id(value):
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise AdmissionError("BOUNDED_ID_REQUIRED")


def _units(value, *, positive=False, signed=False):
    if (type(value) is not int or abs(value) > MAX_UNITS
            or not signed and value < 0 or positive and value <= 0):
        raise AdmissionError("INTEGER_MICRO_USDT_REQUIRED")
    return value


def _at(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 253402300799:
        raise AdmissionError("VALID_UTC_TIME_REQUIRED")
    return float(value)


def _bool(value):
    if type(value) is not bool:
        raise AdmissionError("EXPLICIT_BOOLEAN_REQUIRED")


def _json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    if len(encoded) > 262144:
        raise AdmissionError("BOUNDED_INPUT_REQUIRED")
    return encoded


def _hash(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _periods(at):
    day = datetime.fromtimestamp(at, UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"DAY": day.timestamp(), "WEEK": (day-timedelta(days=day.weekday())).timestamp()}


@dataclass(frozen=True)
class Scope:
    account_id: str
    environment: str
    currency: str

    def __post_init__(self):
        _id(self.account_id)
        if self.environment not in _ENVIRONMENTS or self.currency != "USDT":
            raise AdmissionError("EXPLICIT_SEPARATE_USDT_SCOPE_REQUIRED")


@dataclass(frozen=True)
class AdmissionPolicy:
    policy_id: str
    approval_reference: str
    approved_at: float
    capital_budget_units: int
    gross_limit_units: int
    stop_risk_limit_units: int
    per_trade_stop_risk_limit_units: int
    max_positions: int
    max_leverage_milli: int
    # identity, capital budget, gross limit, inclusive stop-risk limit
    engine_limits: tuple[tuple[str, int, int, int], ...]
    # symbol/group, gross limit, inclusive stop-risk limit
    asset_limits: tuple[tuple[str, int, int], ...]
    correlation_limits: tuple[tuple[str, int, int], ...]
    daily_loss_limit_units: int
    weekly_loss_limit_units: int
    drawdown_limit_units: int
    caution_fraction_ppm: int
    reduced_fraction_ppm: int
    reduced_candidate_risk_cap_units: int
    max_data_age_seconds: int
    max_reservation_age_seconds: int
    max_fee_bps: int
    max_slippage_bps: int
    max_spread_bps: int

    def __post_init__(self):
        _id(self.policy_id); _id(self.approval_reference); _at(self.approved_at)
        for value in (self.capital_budget_units, self.gross_limit_units, self.stop_risk_limit_units,
                      self.per_trade_stop_risk_limit_units,
                      self.daily_loss_limit_units, self.weekly_loss_limit_units,
                      self.drawdown_limit_units, self.reduced_candidate_risk_cap_units):
            _units(value, positive=True)
        if (type(self.max_positions) is not int or not 1 <= self.max_positions <= 100
                or type(self.max_leverage_milli) is not int or not 1000 <= self.max_leverage_milli <= 125000
                or type(self.caution_fraction_ppm) is not int or type(self.reduced_fraction_ppm) is not int
                or not 0 < self.caution_fraction_ppm < self.reduced_fraction_ppm < 1_000_000
                or self.reduced_candidate_risk_cap_units > self.stop_risk_limit_units
                or self.per_trade_stop_risk_limit_units > self.stop_risk_limit_units
                or type(self.max_data_age_seconds) is not int or not 1 <= self.max_data_age_seconds <= 3600
                or type(self.max_reservation_age_seconds) is not int or not 1 <= self.max_reservation_age_seconds <= 3600):
            raise AdmissionError("BOUNDED_EXPLICIT_POLICY_REQUIRED")
        for value in (self.max_fee_bps, self.max_slippage_bps, self.max_spread_bps):
            if type(value) is not int or not 0 <= value <= 10000:
                raise AdmissionError("BOUNDED_COST_POLICY_REQUIRED")
        for category, rows in (("ENGINE", self.engine_limits), ("ASSET", self.asset_limits),
                               ("CORRELATION", self.correlation_limits)):
            if not isinstance(rows, tuple) or not 1 <= len(rows) <= 64:
                raise AdmissionError("EXPLICIT_IMMUTABLE_LIMITS_REQUIRED")
            seen = set()
            for row in rows:
                if not isinstance(row, tuple) or len(row) != (4 if category == "ENGINE" else 3):
                    raise AdmissionError("EXPLICIT_IMMUTABLE_LIMITS_REQUIRED")
                key = row[0]
                if category == "ASSET":
                    if not isinstance(key, str) or not _SYMBOL.fullmatch(key):
                        raise AdmissionError("VALID_ASSET_REQUIRED")
                else:
                    _id(key)
                if key in seen:
                    raise AdmissionError("DUPLICATE_POLICY_LIMIT")
                seen.add(key)
                for value in row[1:]: _units(value, positive=True)
                if ((category == "ENGINE" and row[1] > self.capital_budget_units)
                        or row[-2] > self.gross_limit_units or row[-1] > self.stop_risk_limit_units):
                    raise AdmissionError("PARTICIPANT_LIMIT_EXCEEDS_GLOBAL_POLICY")

    @property
    def fingerprint(self):
        return _hash(asdict(self))


@dataclass(frozen=True)
class Baseline:
    period: str
    started_at: float
    adjusted_equity_units: int
    evidence_id: str

    def __post_init__(self):
        _at(self.started_at); _units(self.adjusted_equity_units, signed=True); _id(self.evidence_id)
        if self.period not in {"DAY", "WEEK"} or _periods(self.started_at)[self.period] != self.started_at:
            raise AdmissionError("EXACT_UTC_BOUNDARY_BASELINE_REQUIRED")


@dataclass(frozen=True)
class PositionFact:
    exposure_id: str
    engine_id: str
    symbol: str
    direction: str
    gross_units: int
    inclusive_stop_risk_units: int
    leverage_milli: int
    correlation_group: str
    observed_at: float
    protection_verified: bool
    managed_ticket_id: str | None = None

    def __post_init__(self):
        for value in (self.exposure_id, self.engine_id, self.correlation_group): _id(value)
        if not isinstance(self.symbol, str) or not _SYMBOL.fullmatch(self.symbol) or self.direction not in {"LONG", "SHORT"}:
            raise AdmissionError("VALID_POSITION_TERMS_REQUIRED")
        _units(self.gross_units, positive=True); _units(self.inclusive_stop_risk_units, positive=True)
        _at(self.observed_at); _bool(self.protection_verified)
        if type(self.leverage_milli) is not int or not 1000 <= self.leverage_milli <= 125000:
            raise AdmissionError("EXPLICIT_LEVERAGE_REQUIRED")
        if self.managed_ticket_id is not None: _id(self.managed_ticket_id)


@dataclass(frozen=True)
class AdmissionFacts:
    """Complete account cut: positions includes pending entry exposures as well.

    Unknown ownership, pending risk, committed margin or stop evidence must make
    inventory_complete/orders_reconciled false; absence is never a zero estimate.
    exchange_committed_units includes all venue commitments, already removed from
    FREE. Extra commitment not attributable to a known position is conservatively
    charged to each strategy's capital test, never silently assigned or netted.
    """
    scope: Scope
    source_id: str
    evidence_id: str
    observed_at: float
    received_at: float
    equity_units: int
    cumulative_net_cashflow_units: int
    cashflow_anchor_id: str
    free_units: int
    exchange_committed_units: int
    identity_verified: bool
    inventory_complete: bool
    orders_reconciled: bool
    cashflows_complete: bool
    free_is_net_of_exchange_commitments: bool
    exchange_ready: bool
    correlation_verified: bool
    baselines: tuple[Baseline, ...]
    positions: tuple[PositionFact, ...]

    def __post_init__(self):
        if not isinstance(self.scope, Scope): raise AdmissionError("TYPED_SCOPE_REQUIRED")
        for value in (self.source_id, self.evidence_id, self.cashflow_anchor_id): _id(value)
        _at(self.observed_at); _at(self.received_at)
        _units(self.equity_units, signed=True); _units(self.cumulative_net_cashflow_units, signed=True)
        _units(self.free_units)
        _units(self.exchange_committed_units)
        for value in (self.identity_verified, self.inventory_complete, self.orders_reconciled,
                      self.cashflows_complete, self.free_is_net_of_exchange_commitments,
                      self.exchange_ready, self.correlation_verified): _bool(value)
        if (not isinstance(self.baselines, tuple) or len(self.baselines) > 2
                or any(not isinstance(x, Baseline) for x in self.baselines)
                or len({x.period for x in self.baselines}) != len(self.baselines)
                or not isinstance(self.positions, tuple) or len(self.positions) > 100
                or any(not isinstance(x, PositionFact) for x in self.positions)
                or len({x.exposure_id for x in self.positions}) != len(self.positions)
                or len([x.managed_ticket_id for x in self.positions if x.managed_ticket_id])
                   != len({x.managed_ticket_id for x in self.positions if x.managed_ticket_id})):
            raise AdmissionError("BOUNDED_UNIQUE_IMMUTABLE_FACTS_REQUIRED")


@dataclass(frozen=True)
class EntryProposal:
    proposal_id: str
    scope: Scope
    engine_id: str
    symbol: str
    direction: str
    gross_units: int
    principal_units: int
    cost_buffer_units: int
    inclusive_stop_risk_units: int
    leverage_milli: int
    correlation_group: str
    observed_at: float
    expires_at: float
    fee_bps: int
    slippage_bps: int
    spread_bps: int
    available_depth_units: int
    protection_plan_verified: bool
    quantitative_review_allowed: bool
    individual_ai_review_allowed: bool
    strategy_fingerprint: str
    execution_plan_fingerprint: str

    def __post_init__(self):
        for value in (self.proposal_id, self.engine_id, self.correlation_group, self.strategy_fingerprint): _id(value)
        if (not isinstance(self.execution_plan_fingerprint,str)
                or not re.fullmatch(r"[0-9a-f]{64}",self.execution_plan_fingerprint)):
            raise AdmissionError("EXACT_EXECUTION_PLAN_SHA256_REQUIRED")
        if not isinstance(self.scope, Scope): raise AdmissionError("TYPED_SCOPE_REQUIRED")
        # Shares exact side/leverage/asset validation with inventory evidence.
        PositionFact(self.proposal_id, self.engine_id, self.symbol, self.direction,
                     self.gross_units, self.inclusive_stop_risk_units, self.leverage_milli,
                     self.correlation_group, self.observed_at, self.protection_plan_verified)
        for value in (self.principal_units, self.cost_buffer_units, self.available_depth_units): _units(value)
        _units(self.principal_units, positive=True); _at(self.expires_at)
        for value in (self.protection_plan_verified, self.quantitative_review_allowed,
                      self.individual_ai_review_allowed): _bool(value)
        for value in (self.fee_bps, self.slippage_bps, self.spread_bps):
            if type(value) is not int or not 0 <= value <= 10000:
                raise AdmissionError("BOUNDED_EXECUTION_COST_REQUIRED")
        if (self.expires_at <= self.observed_at
                or self.principal_units != (self.gross_units*1000+self.leverage_milli-1)//self.leverage_milli):
            raise AdmissionError("PRINCIPAL_MUST_EQUAL_INTEGER_MARGIN_CEILING")
        floor = (self.gross_units*(2*self.fee_bps+2*self.slippage_bps)+9999)//10000
        if self.cost_buffer_units < floor or self.inclusive_stop_risk_units < floor:
            raise AdmissionError("ROUND_TRIP_COST_FLOOR_REQUIRED")
        if (self.engine_id == "SPOT" or self.scope.environment.startswith("SPOT_")) and (self.direction != "LONG" or self.leverage_milli != 1000):
            raise AdmissionError("SPOT_REQUIRES_UNLEVERED_LONG")

    @property
    def fingerprint(self):
        return _hash(asdict(self))


class _SimulationCapability:
    __slots__ = ("scope", "policy_fingerprint", "expires_at", "_secret")

    def __init__(self, scope, policy_fingerprint, expires_at, secret):
        if secret is not _CAPABILITY_SECRET: raise AdmissionError("CAPABILITY_ISSUER_REQUIRED")
        self.scope, self.policy_fingerprint, self.expires_at, self._secret = scope, policy_fingerprint, expires_at, secret


def simulation_capability(scope: Scope, policy: AdmissionPolicy, *, expires_at: float):
    """Explicit offline capability; cannot provision operational environments."""
    if not isinstance(scope, Scope) or scope.environment not in {"SHADOW", "PAPER"}:
        raise AdmissionError("OPERATING_CAPABILITY_NOT_PROVISIONED")
    if not isinstance(policy, AdmissionPolicy): raise AdmissionError("TYPED_POLICY_REQUIRED")
    return _SimulationCapability(scope, policy.fingerprint, _at(expires_at), _CAPABILITY_SECRET)


@dataclass(frozen=True)
class OperatingCapability:
    """Opaque proof presented to a separately authenticated authorization service.

    Construction alone confers no authority. The injected verifier must validate
    proof provenance/revocation and the approval ID against the owner-approved
    immutable policy. This module checks all bindings before calling it.
    """
    scope: Scope
    policy_fingerprint: str
    terms_fingerprint: str
    approval_id: str
    issued_at: float
    expires_at: float
    proof: str

    def __post_init__(self):
        if not isinstance(self.scope, Scope): raise AdmissionError("TYPED_SCOPE_REQUIRED")
        _id(self.approval_id); _at(self.issued_at); _at(self.expires_at)
        if (self.expires_at <= self.issued_at
                or not isinstance(self.policy_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}",self.policy_fingerprint)
                or not isinstance(self.terms_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}",self.terms_fingerprint)
                or not isinstance(self.proof,str) or not 1 <= len(self.proof) <= 8192):
            raise AdmissionError("BOUNDED_CAPABILITY_BINDINGS_REQUIRED")


@dataclass(frozen=True)
class Reconciliation:
    event_id: str
    ticket_id: str
    source_id: str
    evidence_id: str
    observed_at: float
    scope: Scope
    state: str
    cumulative_filled_principal_units: int
    execution_complete: bool
    position_closed: bool
    sibling_orders_clear: bool

    def __post_init__(self):
        for value in (self.event_id, self.ticket_id, self.source_id, self.evidence_id): _id(value)
        _at(self.observed_at); _units(self.cumulative_filled_principal_units)
        if not isinstance(self.scope, Scope) or self.state not in {"UNKNOWN", "PARTIAL", "OPEN", "CANCELLED", "CLOSED"}:
            raise AdmissionError("TYPED_RECONCILIATION_REQUIRED")
        for value in (self.execution_complete, self.position_closed, self.sibling_orders_clear): _bool(value)


class CentralAdmission:
    """Entry-only prepared authority. Operational callers use observe(), not veto."""

    def __init__(self, path, *, scope: Scope, policy: AdmissionPolicy, clock=time.time,
                 capability_verifier=None, fault_hook=None):
        if not isinstance(scope, Scope) or not isinstance(policy, AdmissionPolicy):
            raise AdmissionError("TYPED_EXPLICIT_IDENTITY_REQUIRED")
        self.path, self.scope, self.policy, self.clock = Path(path), scope, policy, clock
        if self.path.suffix != ".sqlite3" or not self.path.name.startswith("central-admission-"):
            raise AdmissionError("SEPARATE_CENTRAL_ADMISSION_STORE_REQUIRED")
        self._identity_data = _json({"app": APP, "scope": asdict(scope), "policy": asdict(policy)})
        self._fault_hook = fault_hook
        if capability_verifier is not None and not callable(capability_verifier):
            raise AdmissionError("CALLABLE_AUTHORIZATION_VERIFIER_REQUIRED")
        self.capability_verifier = capability_verifier

    @contextmanager
    def _connection(self, *, readonly=False, create=False):
        if not create and not self.path.is_file(): raise AdmissionError("CENTRAL_STORE_NOT_INITIALIZED")
        if readonly:
            db = sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)
            db.execute("PRAGMA query_only=ON")
        else:
            db = sqlite3.connect(self.path, timeout=5)
            db.execute("PRAGMA synchronous=FULL")
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
            if not create: self._identity(db)
            yield db
            if not readonly:
                if self._fault_hook: self._fault_hook("BEFORE_COMMIT")
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _identity(self, db):
        current = _json({"app": APP, "scope": asdict(self.scope), "policy": asdict(self.policy)})
        if current != self._identity_data:
            raise AdmissionError("IN_MEMORY_POLICY_IDENTITY_CHANGED")
        try: row = db.execute("SELECT data FROM identity WHERE id=1").fetchone()
        except sqlite3.Error: raise AdmissionError("FOREIGN_CENTRAL_STORE") from None
        if row is None or row[0] != self._identity_data:
            raise AdmissionError("SCOPE_OR_IMMUTABLE_POLICY_MISMATCH")

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(create=True) as db:
            tables = {x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                self._identity(db)
                return
            db.execute("CREATE TABLE identity(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)")
            db.execute("INSERT INTO identity VALUES(1,?)", (self._identity_data,))
            db.execute("CREATE TABLE events(id TEXT PRIMARY KEY,payload TEXT NOT NULL,result TEXT NOT NULL,at REAL NOT NULL)")
            db.execute("CREATE TABLE evidence(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            db.execute("CREATE TABLE baselines(period TEXT NOT NULL,start REAL NOT NULL,value INTEGER NOT NULL,evidence TEXT NOT NULL,PRIMARY KEY(period,start))")
            db.execute("CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)")
            db.execute("INSERT INTO state VALUES(1,?)", (_json({"last_at": 0, "last_observed": 0,
                "cashflow_anchor": None, "cashflow_total": None, "peak": None, "manual": False,
                "recovery": [], "day_latch": None, "week_latch": None, "drawdown_latch": False,
                "daily_loss": None, "weekly_loss": None, "drawdown": None}),))
            db.execute("CREATE TABLE tickets(id TEXT PRIMARY KEY,terms TEXT NOT NULL,terms_hash TEXT NOT NULL,state TEXT NOT NULL,created_at REAL NOT NULL,filled INTEGER NOT NULL,claim_id TEXT UNIQUE,claimed_at REAL,last_reconciled_at REAL)")
            db.execute("CREATE TABLE transport_grants(claim_id TEXT PRIMARY KEY,nonce TEXT UNIQUE NOT NULL,plan_hash TEXT NOT NULL,at REAL NOT NULL)")

    def _state(self, db):
        return json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])

    def _save_state(self, db, state):
        db.execute("UPDATE state SET data=? WHERE id=1", (_json(state),))

    def _event(self, db, event_id, payload, mutation):
        _id(event_id)
        encoded = _json(payload)
        old = db.execute("SELECT payload,result FROM events WHERE id=?", (event_id,)).fetchone()
        if old:
            if old[0] == encoded: return json.loads(old[1])
            state = self._state(db)
            state["recovery"] = sorted(set(state["recovery"]+["EVENT_ID_CONFLICT"]))
            self._save_state(db, state)
            return self._result(False, ["EVENT_ID_CONFLICT"], "RECOVERY_REQUIRED")
        result = mutation()
        db.execute("INSERT INTO events VALUES(?,?,?,?)", (event_id, encoded, _json(result), _at(self.clock())))
        return result

    def _result(self, accepted, reasons, state, **values):
        return {"accepted": accepted, "reasons": sorted(set(reasons)), "state": state,
                "scope": asdict(self.scope), "policy_fingerprint": self.policy.fingerprint,
                "execution_enabled": False, "can_veto_operating_engines": False,
                "operating_verifier_configured": self.capability_verifier is not None,
                "protective_exits_independent": True,
                **values}

    def _facts(self, db, facts, now):
        if not isinstance(facts, AdmissionFacts): raise AdmissionError("TYPED_ACCOUNT_FACTS_REQUIRED")
        state = self._state(db)
        reasons = []
        if facts.scope != self.scope: reasons.append("ACCOUNT_ENVIRONMENT_CURRENCY_MISMATCH")
        if now < state["last_at"]: reasons.append("CLOCK_REGRESSION")
        if (facts.observed_at > facts.received_at or facts.received_at > now
                or now-facts.observed_at > self.policy.max_data_age_seconds
                or facts.observed_at < state["last_observed"]): reasons.append("STALE_FUTURE_OR_REGRESSING_FACTS")
        for name in ("identity_verified", "inventory_complete", "orders_reconciled", "cashflows_complete",
                     "free_is_net_of_exchange_commitments", "exchange_ready", "correlation_verified"):
            if not getattr(facts, name): reasons.append(name.upper()+"_REQUIRED")
        if facts.equity_units < 0: reasons.append("NEGATIVE_ACCOUNT_EQUITY")
        if facts.free_units+facts.exchange_committed_units > facts.equity_units:
            reasons.append("ACCOUNT_CAPITAL_COMPONENTS_EXCEED_EQUITY")
        if self.policy.approved_at > now: reasons.append("POLICY_NOT_YET_AVAILABLE")
        encoded = _json(asdict(facts))
        old = db.execute("SELECT payload FROM evidence WHERE id=?", (facts.evidence_id,)).fetchone()
        if old and old[0] != encoded: reasons.append("EVIDENCE_ID_CONFLICT")
        if state["cashflow_anchor"] is not None and facts.cashflow_anchor_id != state["cashflow_anchor"]:
            reasons.append("CASHFLOW_ANCHOR_CHANGED")
        if (state["cashflow_total"] is not None and facts.observed_at == state["last_observed"]
                and facts.cumulative_net_cashflow_units != state["cashflow_total"]):
            reasons.append("CASHFLOW_CUT_CONTRADICTION")
        periods = _periods(now)
        for baseline in facts.baselines:
            if baseline.started_at != periods[baseline.period]:
                reasons.append("BASELINE_OUTSIDE_CURRENT_PERIOD")
                continue
            stored = db.execute("SELECT value,evidence FROM baselines WHERE period=? AND start=?", (baseline.period, baseline.started_at)).fetchone()
            if stored and tuple(stored) != (baseline.adjusted_equity_units, baseline.evidence_id):
                reasons.append("IMMUTABLE_BASELINE_CONFLICT")
        if not reasons:
            for baseline in facts.baselines:
                db.execute("INSERT OR IGNORE INTO baselines VALUES(?,?,?,?)", (baseline.period, baseline.started_at,
                    baseline.adjusted_equity_units, baseline.evidence_id))
            values = {}
            for kind in ("DAY", "WEEK"):
                row = db.execute("SELECT value FROM baselines WHERE period=? AND start=?", (kind, periods[kind])).fetchone()
                if row is None: reasons.append(kind+"_BASELINE_MISSING")
                else: values[kind] = row[0]
            if not reasons:
                adjusted = facts.equity_units-facts.cumulative_net_cashflow_units
                if abs(adjusted) > MAX_UNITS: reasons.append("ADJUSTED_EQUITY_RANGE_EXCEEDED")
                else:
                    state["cashflow_anchor"] = facts.cashflow_anchor_id
                    state["cashflow_total"] = facts.cumulative_net_cashflow_units
                    state["peak"] = adjusted if state["peak"] is None else max(state["peak"], adjusted)
                    state["daily_loss"] = max(0, values["DAY"]-adjusted)
                    state["weekly_loss"] = max(0, values["WEEK"]-adjusted)
                    state["drawdown"] = max(0, state["peak"]-adjusted)
                    # Calendar passage alone does not clear a latch: this branch
                    # requires fresh complete facts AND a registered new baseline.
                    if state["day_latch"] != periods["DAY"]: state["day_latch"] = None
                    if state["week_latch"] != periods["WEEK"]: state["week_latch"] = None
                    if state["daily_loss"] >= self.policy.daily_loss_limit_units: state["day_latch"] = periods["DAY"]
                    if state["weekly_loss"] >= self.policy.weekly_loss_limit_units: state["week_latch"] = periods["WEEK"]
                    if state["drawdown"] >= self.policy.drawdown_limit_units: state["drawdown_latch"] = True
                    state["last_observed"] = max(state["last_observed"], facts.observed_at)
                    if not old: db.execute("INSERT INTO evidence VALUES(?,?)", (facts.evidence_id, encoded))
        if reasons: state["recovery"] = sorted(set(state["recovery"]+reasons))
        state["last_at"] = max(state["last_at"], now)
        self._save_state(db, state)
        return state, reasons

    def _gate(self, state):
        reasons = list(state["recovery"])
        if reasons: return "RECOVERY_REQUIRED", reasons
        if state["manual"]: reasons.append("MANUAL_ENTRY_HALT")
        if state["day_latch"] is not None: reasons.append("DAILY_LOSS_LATCH")
        if state["week_latch"] is not None: reasons.append("WEEKLY_LOSS_LATCH")
        if state["drawdown_latch"]: reasons.append("DRAWDOWN_LATCH")
        if reasons: return "ENTRY_HALTED", reasons
        fraction = max((state[key] or 0)*1_000_000//limit for key,limit in (
            ("daily_loss",self.policy.daily_loss_limit_units), ("weekly_loss",self.policy.weekly_loss_limit_units),
            ("drawdown",self.policy.drawdown_limit_units)))
        if fraction >= self.policy.reduced_fraction_ppm: return "RISK_REDUCED", []
        if fraction >= self.policy.caution_fraction_ppm: return "CAUTION", []
        return "NORMAL", []

    def _active(self, db, exclude=None):
        return [(row, EntryProposal(**{**json.loads(row["terms"]), "scope": Scope(**json.loads(row["terms"])["scope"])}))
                for row in db.execute("SELECT * FROM tickets WHERE state NOT IN ('CANCELLED','CLOSED')") if row["id"] != exclude]

    def _assess(self, db, proposal, facts, now, *, exclude=None):
        if not isinstance(proposal, EntryProposal): raise AdmissionError("TYPED_ENTRY_PROPOSAL_REQUIRED")
        state, _ = self._facts(db, facts, now)
        risk_state, reasons = self._gate(state)
        if proposal.scope != self.scope: reasons.append("PROPOSAL_SCOPE_MISMATCH")
        if (proposal.observed_at > now or now-proposal.observed_at > self.policy.max_data_age_seconds
                or proposal.expires_at <= now): reasons.append("PROPOSAL_STALE_FUTURE_OR_EXPIRED")
        if not proposal.quantitative_review_allowed: reasons.append("QUANTITATIVE_REVIEW_REJECTED")
        if not proposal.individual_ai_review_allowed: reasons.append("INDIVIDUAL_AI_REVIEW_REJECTED")
        if not proposal.protection_plan_verified: reasons.append("PROTECTION_PLAN_UNVERIFIED")
        if proposal.fee_bps > self.policy.max_fee_bps or proposal.slippage_bps > self.policy.max_slippage_bps or proposal.spread_bps > self.policy.max_spread_bps:
            reasons.append("COST_OR_SPREAD_LIMIT")
        if proposal.available_depth_units < proposal.gross_units: reasons.append("INSUFFICIENT_VERIFIED_DEPTH")
        active = self._active(db, exclude)
        if any(row["state"] in {"UNKNOWN", "RECOVERY_REQUIRED"} for row, _ in active):
            reasons.append("UNRECONCILED_MANAGED_ORDER")
        # Full original terms stay in risk and capital totals through partial
        # fills and uncertain/cancel-pending states. External managed positions
        # can only replace duplicate counting after conservative exact linkage.
        rows = [(p.engine_id,p.symbol,p.gross_units,p.inclusive_stop_risk_units,p.leverage_milli,p.correlation_group) for _,p in active]
        active_by_id = {row["id"]:(row,p) for row,p in active}
        reflected_principal = 0
        reflected_tickets=set()
        for position in facts.positions:
            if (position.observed_at > now or now-position.observed_at > self.policy.max_data_age_seconds
                    or not position.protection_verified): reasons.append("EXISTING_POSITION_STALE_OR_UNPROTECTED")
            if position.managed_ticket_id:
                target = active_by_id.get(position.managed_ticket_id)
                if target is None:
                    reasons.append("UNKNOWN_MANAGED_POSITION_LINK")
                else:
                    ticket, terms = target
                    if ((position.engine_id,position.symbol,position.direction,position.leverage_milli,position.correlation_group)
                            != (terms.engine_id,terms.symbol,terms.direction,terms.leverage_milli,terms.correlation_group)
                            or position.gross_units > terms.gross_units
                            or position.inclusive_stop_risk_units > terms.inclusive_stop_risk_units
                            or ticket["filled"] < (position.gross_units*1000+position.leverage_milli-1)//position.leverage_milli):
                        reasons.append("MANAGED_POSITION_TERMS_CONTRADICTION")
                    else:
                        reflected_principal += (position.gross_units*1000+position.leverage_milli-1)//position.leverage_milli
                        reflected_tickets.add(position.managed_ticket_id)
                continue
            rows.append((position.engine_id,position.symbol,position.gross_units,position.inclusive_stop_risk_units,position.leverage_milli,position.correlation_group))
        if any(row["filled"] > 0 and row["id"] not in reflected_tickets for row,_ in active):
            reasons.append("MANAGED_FILL_MISSING_FROM_COMPLETE_INVENTORY")
        before_gross = sum(x[2] for x in rows)
        before_risk = sum(x[3] for x in rows)
        if any(x[1] == proposal.symbol for x in rows): reasons.append("ASSET_ALREADY_EXPOSED_OR_RESERVED")
        after = rows+[(proposal.engine_id,proposal.symbol,proposal.gross_units,proposal.inclusive_stop_risk_units,
                      proposal.leverage_milli,proposal.correlation_group)]
        capital = sum(p.principal_units+p.cost_buffer_units for _,p in active)
        requested = proposal.principal_units+proposal.cost_buffer_units
        known_exchange_principal=sum((x.gross_units*1000+x.leverage_milli-1)//x.leverage_milli for x in facts.positions)
        if known_exchange_principal > facts.exchange_committed_units:
            reasons.append("EXCHANGE_COMMITMENTS_BELOW_OBSERVED_POSITIONS")
        unassigned_exchange_capital=max(0,facts.exchange_committed_units-known_exchange_principal)
        # FREE already excludes exchange commitments. Credit only matched filled
        # principal; never credit costs, unknown orders or mere ticket assertions.
        if reflected_principal > facts.exchange_committed_units:
            reasons.append("REFLECTED_PRINCIPAL_EXCEEDS_EXCHANGE_COMMITMENTS")
        local_unreflected=capital-reflected_principal
        free = min(self.policy.capital_budget_units-facts.exchange_committed_units-local_unreflected,
                   facts.free_units-local_unreflected)
        if requested > max(0, free): reasons.append("INSUFFICIENT_UNRESERVED_CAPITAL")
        if len(after) > self.policy.max_positions: reasons.append("GLOBAL_POSITION_LIMIT")
        if any(x[4] > self.policy.max_leverage_milli for x in after): reasons.append("LEVERAGE_LIMIT")
        if sum(x[2] for x in after) > self.policy.gross_limit_units: reasons.append("GLOBAL_GROSS_LIMIT")
        if sum(x[3] for x in after) > self.policy.stop_risk_limit_units: reasons.append("GLOBAL_STOP_RISK_LIMIT")
        if proposal.inclusive_stop_risk_units > self.policy.per_trade_stop_risk_limit_units:
            reasons.append("PER_TRADE_STOP_RISK_LIMIT")
        for category, limits, index in (("ENGINE", self.policy.engine_limits, 0), ("ASSET", self.policy.asset_limits, 1),
                                        ("CORRELATION", self.policy.correlation_limits, 5)):
            mapping = {x[0]:x for x in limits}
            for key in {x[index] for x in after}:
                limit = mapping.get(key)
                if limit is None:
                    reasons.append(category+"_LIMIT_UNSPECIFIED")
                    continue
                matching = [x for x in after if x[index] == key]
                if sum(x[2] for x in matching) > limit[-2]: reasons.append(category+"_GROSS_LIMIT")
                if sum(x[3] for x in matching) > limit[-1]: reasons.append(category+"_STOP_RISK_LIMIT")
                if category == "ENGINE":
                    engine_capital = sum(p.principal_units+p.cost_buffer_units for _,p in active if p.engine_id == key)
                    # Unmanaged account positions consume this strategy's budget
                    # too. Unknown extra margin remains capped globally by the
                    # explicit complete-account exchange commitment above.
                    engine_capital += sum((x.gross_units*1000+x.leverage_milli-1)//x.leverage_milli
                        for x in facts.positions if x.engine_id == key and x.managed_ticket_id is None)
                    engine_capital += unassigned_exchange_capital
                    if key == proposal.engine_id: engine_capital += requested
                    if engine_capital > limit[1]: reasons.append("ENGINE_CAPITAL_LIMIT")
        if risk_state == "RISK_REDUCED" and proposal.inclusive_stop_risk_units > self.policy.reduced_candidate_risk_cap_units:
            reasons.append("REDUCED_CANDIDATE_STOP_RISK_LIMIT")
        if any(abs(x) > MAX_UNITS for x in (before_gross, before_risk, sum(x[2] for x in after), sum(x[3] for x in after), capital, requested)):
            reasons.append("AGGREGATE_MONEY_RANGE_EXCEEDED")
        return self._result(not reasons, reasons, risk_state if not reasons else (
            "RECOVERY_REQUIRED" if risk_state == "RECOVERY_REQUIRED" else "ENTRY_HALTED"),
            before={"gross_units":before_gross,"stop_risk_units":before_risk,"reserved_units":capital},
            after={"gross_units":sum(x[2] for x in after),"stop_risk_units":sum(x[3] for x in after),
                   "reserved_units":capital+requested}, available_units=max(0,free),
            data_evidence_id=facts.evidence_id, data_observed_at=facts.observed_at,
            proposal_fingerprint=proposal.fingerprint)

    def observe(self, proposal, facts, *, event_id):
        """Audit hypothetical admission. Never veto, reserve or create a claim."""
        now = _at(self.clock())
        with self._connection() as db:
            return self._event(db,event_id,{"kind":"OBSERVE","proposal":asdict(proposal),"facts":asdict(facts)},
                lambda: {**self._assess(db,proposal,facts,now),"mode":"SHADOW","reservation_created":False})

    def _capability(self, capability, now, terms_fingerprint):
        if type(capability) is _SimulationCapability:
            if (capability._secret is not _CAPABILITY_SECRET or self.scope.environment not in {"SHADOW","PAPER"}
                    or capability.scope != self.scope or capability.policy_fingerprint != self.policy.fingerprint
                    or capability.expires_at <= now):
                raise AdmissionError("SIMULATION_CAPABILITY_INVALID_OR_EXPIRED")
            return "SIMULATION"
        if (type(capability) is not OperatingCapability or self.capability_verifier is None
                or self.scope.environment in {"SHADOW","PAPER"}
                or capability.scope != self.scope or capability.policy_fingerprint != self.policy.fingerprint
                or capability.terms_fingerprint != terms_fingerprint
                or not capability.issued_at <= now < capability.expires_at):
            raise AdmissionError("OPERATING_CAPABILITY_NOT_PROVISIONED_OR_INVALID")
        try:
            verified=self.capability_verifier(capability, scope=self.scope,
                policy_fingerprint=self.policy.fingerprint, terms_fingerprint=terms_fingerprint, now=now)
        except Exception:
            raise AdmissionError("OPERATING_CAPABILITY_VERIFICATION_FAILED") from None
        if verified is not True: raise AdmissionError("OPERATING_CAPABILITY_VERIFICATION_FAILED")
        checked_at=_at(self.clock())
        if checked_at < now or not capability.issued_at <= checked_at < capability.expires_at:
            raise AdmissionError("OPERATING_CAPABILITY_EXPIRED_DURING_VERIFICATION")
        return "APPROVED_ADMISSION"

    @staticmethod
    def _provenance(capability):
        if type(capability) is OperatingCapability:
            return {"approval_id":capability.approval_id,"issued_at":capability.issued_at,
                    "expires_at":capability.expires_at,"proof_sha256":hashlib.sha256(capability.proof.encode()).hexdigest()}
        return {"approval_id":"EXPLICIT_SIMULATION_ONLY"}

    def assess_and_reserve(self, proposal, facts, *, event_id, capability=None):
        if not isinstance(proposal,EntryProposal): raise AdmissionError("TYPED_ENTRY_PROPOSAL_REQUIRED")
        with self._connection() as db:
            now = _at(self.clock()); mode=self._capability(capability,now,proposal.fingerprint)
            now = _at(self.clock())
            def reserve():
                old = db.execute("SELECT terms_hash FROM tickets WHERE id=?", (proposal.proposal_id,)).fetchone()
                if old:
                    state = self._state(db)
                    state["recovery"] = sorted(set(state["recovery"]+["PROPOSAL_ID_ALREADY_USED"]))
                    self._save_state(db,state)
                    return self._result(False,["PROPOSAL_ID_ALREADY_USED"],"RECOVERY_REQUIRED")
                result = self._assess(db,proposal,facts,now)
                if result["accepted"]:
                    db.execute("INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?)", (proposal.proposal_id,_json(asdict(proposal)),
                        proposal.fingerprint,"RESERVED",now,0,None,None,None))
                return {**result,"ticket_id":proposal.proposal_id if result["accepted"] else None,
                        "reservation_created":result["accepted"],"mode":mode}
            return self._event(db,event_id,{"kind":"RESERVE","proposal":asdict(proposal),"facts":asdict(facts),
                "authorization":self._provenance(capability)},reserve)

    def claim(self, ticket_id, facts, *, event_id, capability=None):
        _id(ticket_id)
        with self._connection() as db:
            now = _at(self.clock())
            ticket=db.execute("SELECT terms_hash FROM tickets WHERE id=?",(ticket_id,)).fetchone()
            if ticket is None: return self._result(False,["TICKET_UNKNOWN"],"RECOVERY_REQUIRED")
            mode=self._capability(capability,now,ticket[0])
            now = _at(self.clock())
            replay=db.execute("SELECT 1 FROM events WHERE id=?",(event_id,)).fetchone() is not None
            def claim_once():
                row = db.execute("SELECT * FROM tickets WHERE id=?",(ticket_id,)).fetchone()
                if row is None: return self._result(False,["TICKET_UNKNOWN"],"RECOVERY_REQUIRED")
                if row["state"] != "RESERVED" or row["claim_id"] is not None:
                    return self._result(False,["SUBMISSION_ALREADY_CLAIMED_OR_TERMINAL"],row["state"],
                                        new_claim_created=False,submission_permitted=False)
                value = json.loads(row["terms"]); proposal = EntryProposal(**{**value,"scope":Scope(**value["scope"])})
                result = self._assess(db,proposal,facts,now,exclude=ticket_id)
                if now-row["created_at"] > self.policy.max_reservation_age_seconds:
                    result = {**result,"accepted":False,"state":"ENTRY_HALTED", "reasons":sorted(set(result["reasons"]+["RESERVATION_EXPIRED_RECONCILIATION_REQUIRED"]))}
                if not result["accepted"]:
                    return {**result,"new_claim_created":False,"submission_permitted":False}
                claim_id = ("SIM-" if mode=="SIMULATION" else "CLAIM-")+hashlib.sha256((self._identity_data+"|"+ticket_id+"|"+row["terms_hash"]).encode()).hexdigest()[:48]
                db.execute("UPDATE tickets SET state='SUBMITTING',claim_id=?,claimed_at=? WHERE id=?",(claim_id,now,ticket_id))
                return {**result,"ticket_id":ticket_id,"claim_id":claim_id,"terms_fingerprint":row["terms_hash"],
                        "new_claim_created":True,"submission_permitted":False,
                        "claim_ready_for_transport":mode=="APPROVED_ADMISSION",
                        "execution_plan_fingerprint":proposal.execution_plan_fingerprint,
                        "claim_kind":"SIMULATED_SINGLE_INTENTION" if mode=="SIMULATION" else "ONE_DURABLE_SUBMISSION_INTENTION",
                        "mode":mode}
            payload={"kind":"CLAIM","ticket_id":ticket_id,"facts":asdict(facts),"authorization":self._provenance(capability)}
            result = self._event(db,event_id,payload,claim_once)
            # A replay is a durable receipt, never a second send permission.
            return {**result,"new_claim_created":False,"submission_permitted":False,"receipt_replayed":True} if replay else result

    def ticket_terms(self, ticket_id):
        """Read exact immutable planned terms; never returns authority or proof."""
        _id(ticket_id)
        with self._connection(readonly=True) as db:
            row=db.execute("SELECT terms,terms_hash,state,claim_id FROM tickets WHERE id=?",(ticket_id,)).fetchone()
            if row is None: raise AdmissionError("TICKET_UNKNOWN")
            return {"ticket_id":ticket_id,"terms":json.loads(row["terms"]),"terms_fingerprint":row["terms_hash"],
                    "state":row["state"],"claim_id":row["claim_id"],"submission_permitted":False}

    def get_claim(self, claim_id):
        """Read a durable receipt after restart, without renewing send permission."""
        _id(claim_id)
        with self._connection(readonly=True) as db:
            row=db.execute("SELECT * FROM tickets WHERE claim_id=?",(claim_id,)).fetchone()
            if row is None: raise AdmissionError("CLAIM_UNKNOWN")
            terms=json.loads(row["terms"])
            consumed=db.execute("SELECT 1 FROM transport_grants WHERE claim_id=?",(claim_id,)).fetchone() is not None
            return {"claim_id":claim_id,"ticket_id":row["id"],"state":row["state"],
                    "scope":asdict(self.scope),"policy_fingerprint":self.policy.fingerprint,
                    "terms_fingerprint":row["terms_hash"],"execution_plan_fingerprint":terms["execution_plan_fingerprint"],
                    "claimed_at":row["claimed_at"],"transport_consumed":consumed,"submission_permitted":False}

    def consume_transport_grant(self, claim_id, execution_plan_fingerprint, facts, *, event_id,
                                capability=None, transport_nonce=None):
        """Consume one handoff inside the authority transaction, before any HTTP.

        A returned nonce is an audit identity, not a reusable credential. Even an
        exact duplicate event returns transport_permitted=False. Once consumed,
        UNKNOWN retains all original capital/risk until reconciliation, including
        a crash before the caller manages to contact the venue. No resend here.
        """
        _id(claim_id)
        if transport_nonce is not None: _id(transport_nonce)
        with self._connection() as db:
            now=_at(self.clock())
            row=db.execute("SELECT * FROM tickets WHERE claim_id=?",(claim_id,)).fetchone()
            if row is None: return self._result(False,["CLAIM_UNKNOWN"],"RECOVERY_REQUIRED",transport_permitted=False)
            mode=self._capability(capability,now,row["terms_hash"])
            now = _at(self.clock())
            value=json.loads(row["terms"]); proposal=EntryProposal(**{**value,"scope":Scope(**value["scope"])})
            if execution_plan_fingerprint != proposal.execution_plan_fingerprint:
                raise AdmissionError("EXECUTION_PLAN_FINGERPRINT_MISMATCH")
            replay=db.execute("SELECT 1 FROM events WHERE id=?",(event_id,)).fetchone() is not None
            def consume():
                old=db.execute("SELECT nonce FROM transport_grants WHERE claim_id=?",(claim_id,)).fetchone()
                if old or row["state"] != "SUBMITTING":
                    return self._result(False,["TRANSPORT_GRANT_ALREADY_CONSUMED_OR_STATE_UNCERTAIN"],row["state"],
                        transport_permitted=False,new_grant_created=False)
                result=self._assess(db,proposal,facts,now,exclude=row["id"])
                if not result["accepted"]:
                    return {**result,"transport_permitted":False,"new_grant_created":False}
                nonce=transport_nonce or "HANDOFF-"+hashlib.sha256((claim_id+"|"+row["terms_hash"]+"|"+execution_plan_fingerprint).encode()).hexdigest()[:48]
                if db.execute("SELECT 1 FROM transport_grants WHERE nonce=?",(nonce,)).fetchone():
                    state=self._state(db)
                    state["recovery"]=sorted(set(state["recovery"]+["TRANSPORT_NONCE_ALREADY_USED"]))
                    self._save_state(db,state)
                    return self._result(False,["TRANSPORT_NONCE_ALREADY_USED"],"RECOVERY_REQUIRED",
                                        transport_permitted=False,new_grant_created=False)
                db.execute("INSERT INTO transport_grants VALUES(?,?,?,?)",(claim_id,nonce,execution_plan_fingerprint,now))
                db.execute("UPDATE tickets SET state='UNKNOWN' WHERE id=?",(row["id"],))
                return {**result,"claim_id":claim_id,"grant_nonce":nonce,"ticket_id":row["id"],
                        "terms_fingerprint":row["terms_hash"],"execution_plan_fingerprint":execution_plan_fingerprint,
                        "new_grant_created":True,"transport_permitted":mode=="APPROVED_ADMISSION",
                        "submission_permitted":mode=="APPROVED_ADMISSION","mode":mode,"state":"UNKNOWN"}
            result=self._event(db,event_id,{"kind":"TRANSPORT_HANDOFF","claim_id":claim_id,
                "execution_plan_fingerprint":execution_plan_fingerprint,"facts":asdict(facts),
                "transport_nonce":transport_nonce,
                "authorization":self._provenance(capability)},consume)
            return {**result,"new_grant_created":False,"transport_permitted":False,
                    "submission_permitted":False,"receipt_replayed":True} if replay else result

    def mark_recovery(self, ticket_id, reason, *, event_id):
        """Safety-only durable halt for e.g. an executed fill without native stop.

        Never releases capital or changes an order/position. No capability is
        required to make entry safety stricter. Caller must supply a closed code,
        not a provider error, credential or arbitrary free text.
        """
        _id(ticket_id)
        if not isinstance(reason,str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}",reason):
            raise AdmissionError("CLOSED_RECOVERY_REASON_CODE_REQUIRED")
        with self._connection() as db:
            row=db.execute("SELECT state FROM tickets WHERE id=?",(ticket_id,)).fetchone()
            if row is None: raise AdmissionError("TICKET_UNKNOWN")
            state=self._state(db)
            state["recovery"]=sorted(set(state["recovery"]+[reason]))
            self._save_state(db,state)
            if row[0] not in {"CANCELLED","CLOSED"}:
                db.execute("UPDATE tickets SET state='RECOVERY_REQUIRED' WHERE id=?",(ticket_id,))
            return self._event(db,event_id,{"kind":"MARK_RECOVERY","ticket_id":ticket_id,"reason":reason},
                lambda:self._result(False,[reason],"RECOVERY_REQUIRED",reservation_released=False))

    def reconcile(self, event: Reconciliation):
        if not isinstance(event,Reconciliation): raise AdmissionError("TYPED_RECONCILIATION_REQUIRED")
        now = _at(self.clock())
        with self._connection() as db:
            def apply():
                row=db.execute("SELECT * FROM tickets WHERE id=?",(event.ticket_id,)).fetchone()
                if row is None: return self._result(False,["TICKET_UNKNOWN"],"RECOVERY_REQUIRED")
                terms=json.loads(row["terms"])
                invalid=[]
                if event.scope != self.scope: invalid.append("RECONCILIATION_SCOPE_MISMATCH")
                if event.observed_at > now or now-event.observed_at > self.policy.max_data_age_seconds: invalid.append("RECONCILIATION_STALE_OR_FUTURE")
                if (event.observed_at < (row["claimed_at"] or row["created_at"])
                        or row["last_reconciled_at"] is not None and event.observed_at < row["last_reconciled_at"]):
                    invalid.append("RECONCILIATION_CUT_PRECEDES_CLAIM_OR_ACCEPTED_EVIDENCE")
                if (event.cumulative_filled_principal_units < row["filled"]
                        or event.cumulative_filled_principal_units > terms["principal_units"]): invalid.append("FILL_CUMULATIVE_CONTRADICTION")
                terminal=event.state in {"CANCELLED","CLOSED"}
                if terminal and (not event.execution_complete or not event.position_closed or not event.sibling_orders_clear):
                    invalid.append("TERMINAL_RECONCILIATION_INCOMPLETE")
                if event.state=="CANCELLED" and event.cumulative_filled_principal_units: invalid.append("FILLED_ORDER_CANNOT_RELEASE_AS_CANCELLED")
                if event.state in {"PARTIAL","OPEN","CLOSED"} and event.cumulative_filled_principal_units==0: invalid.append("POSITIVE_FILL_REQUIRED")
                if event.state=="OPEN" and not event.execution_complete: invalid.append("OPEN_EXECUTION_NOT_COMPLETE")
                if row["state"] in {"CANCELLED","CLOSED"} and (event.state != row["state"] or event.cumulative_filled_principal_units != row["filled"]):
                    invalid.append("TERMINAL_STATE_CONTRADICTION")
                if row["claim_id"] is None and event.state != "CANCELLED": invalid.append("FILL_WITHOUT_SUBMISSION_CLAIM")
                evidence_payload=_json(asdict(event))
                evidence=db.execute("SELECT payload FROM evidence WHERE id=?",(event.evidence_id,)).fetchone()
                if evidence and evidence[0] != evidence_payload: invalid.append("EVIDENCE_ID_CONFLICT")
                state=self._state(db)
                if now < state["last_at"]: invalid.append("CLOCK_REGRESSION")
                if invalid:
                    state["recovery"]=sorted(set(state["recovery"]+invalid)); self._save_state(db,state)
                    if row["state"] not in {"CANCELLED","CLOSED"}: db.execute("UPDATE tickets SET state='RECOVERY_REQUIRED' WHERE id=?",(event.ticket_id,))
                    return self._result(False,invalid,"RECOVERY_REQUIRED",reservation_released=False)
                if not evidence: db.execute("INSERT INTO evidence VALUES(?,?)",(event.evidence_id,evidence_payload))
                db.execute("UPDATE tickets SET state=?,filled=?,last_reconciled_at=? WHERE id=?",(event.state,event.cumulative_filled_principal_units,event.observed_at,event.ticket_id))
                state["last_at"]=max(state["last_at"],now); self._save_state(db,state)
                return self._result(True,[],event.state,reservation_released=terminal,
                                    ticket_id=event.ticket_id,retained_principal_units=0 if terminal else terms["principal_units"])
            return self._event(db,event.event_id,{"kind":"RECONCILE","event":asdict(event)},apply)

    def set_manual_halt(self, halted: bool, *, actor: str, event_id: str, capability=None):
        _bool(halted); _id(actor)
        with self._connection() as db:
            now=_at(self.clock())
            if not halted:
                action=_hash({"kind":"MANUAL_HALT","halted":False,"actor":actor})
                self._capability(capability,now,action)
            # Safety activation is durable even when the event ID conflicts or
            # the clock regresses. Clearing is separately checked and audited.
            if halted:
                state=self._state(db); state["manual"]=True; self._save_state(db,state)
            def apply():
                state=self._state(db)
                if now < state["last_at"]:
                    state["recovery"]=sorted(set(state["recovery"]+["CLOCK_REGRESSION"]))
                elif not halted: state["manual"]=False
                state["last_at"]=max(state["last_at"],now); self._save_state(db,state)
                risk,reasons=self._gate(state)
                return self._result(not state["recovery"],reasons,risk,manual_halt=state["manual"])
            return self._event(db,event_id,{"kind":"MANUAL_HALT","halted":halted,"actor":actor},apply)

    def acknowledge_recovery(self, facts, *, actor, event_id, capability=None):
        """Explicit SIM acknowledgement, requiring fresh complete evidence.

        Does not erase daily/weekly/drawdown latches, peaks or unresolved tickets.
        Production owner approval is not provisioned by this method.
        """
        _id(actor)
        with self._connection() as db:
            now=_at(self.clock())
            # Recovery control needs its own exact action fingerprint, never an
            # entry capability repurposed to clear a safety latch.
            action=_hash({"kind":"ACK_RECOVERY","actor":actor,"facts":asdict(facts)})
            self._capability(capability,now,action)
            def apply():
                state,reasons=self._facts(db,facts,now)
                if any(row["state"] in {"UNKNOWN","RECOVERY_REQUIRED"} for row,_ in self._active(db)):
                    reasons.append("UNRECONCILED_MANAGED_ORDER")
                if not reasons: state["recovery"]=[]
                self._save_state(db,state)
                risk,failures=self._gate(state)
                return self._result(not reasons,failures,risk)
            return self._event(db,event_id,{"kind":"ACK_RECOVERY","actor":actor,"facts":asdict(facts)},apply)

    def snapshot(self):
        """Read-only, bounded metadata; no collection, valuation or initialization."""
        with self._connection(readonly=True) as db:
            state=self._state(db); active=self._active(db); risk,reasons=self._gate(state)
            return self._result(not reasons,reasons,risk,losses={key:state[key] for key in
                ("daily_loss","weekly_loss","drawdown","day_latch","week_latch","drawdown_latch","manual","peak")},
                last_observed_at=state["last_observed"] or None,
                reserved_units=sum(p.principal_units+p.cost_buffer_units for _,p in active),
                gross_units=sum(p.gross_units for _,p in active),
                stop_risk_units=sum(p.inclusive_stop_risk_units for _,p in active),
                active_tickets=[{"ticket_id":row["id"],"state":row["state"],"terms_fingerprint":row["terms_hash"],
                                 "filled_principal_units":row["filled"]} for row,_ in active],
                event_count=db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                claim_count=db.execute("SELECT COUNT(*) FROM tickets WHERE claim_id IS NOT NULL").fetchone()[0],
                limitations=["CALLER_ATTESTED_FACTS_NOT_ACCOUNT_CERTIFICATION","DESIGNATED_SINGLE_STORE_REQUIRED",
                    "NO_OPERATING_CAPABILITY_ISSUER_OR_ENTRY_INTEGRATION","NO_EXCHANGE_TRANSPORT",
                    "NO_TIMEOUT_RELEASE_OR_LEG_ATOMICITY","OBSERVED_CASHFLOW_ADJUSTED_PEAK_ONLY"])
