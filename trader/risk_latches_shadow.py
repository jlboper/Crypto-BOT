"""Durable loss-gate simulation, separate from financial ledgers and execution.

All identities are SIM_* and all money is integer micro-USDT. Inputs assert
synthetic, complete evidence; accepting them does not certify an exchange account.
Daily/weekly baselines are immutable UTC boundary observations. Calendar passage
alone never clears a latch. Cashflows require distinct, idempotent verified events
and cannot be backdated across an accepted equity observation. Drawdown uses the
cashflow-adjusted observed high-water mark and never resets that peak. Unobserved
intraperiod peaks are not reconstructed. SQLite transactions and append-only
evidence are not a tamper-proof store or continuous exchange valuation.

This is one loss gate, not a full admission decision. No order, real reservation,
protective exit, API client, environment credential or AI is imported or called.
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

from .capital_manager_shadow import AccountScope, MAX_INTEGER, SimulationError


APP = "RISK_LATCHES_SHADOW_SIMULATION_V1"
_ID = re.compile(r"^SIM_[A-Za-z0-9_-]{1,80}$")


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise SimulationError("EXPLICIT_SIMULATION_ID_REQUIRED")


def _units(value, *, signed=False, positive=False):
    if (type(value) is not int or abs(value) > MAX_INTEGER
            or not signed and value < 0 or positive and value <= 0):
        raise SimulationError("INTEGER_ATOMIC_MONEY_REQUIRED")
    return value


def _at(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 253402300799:
        raise SimulationError("INVALID_SIMULATION_TIME")
    return float(value)


def _fact(value):
    if type(value) is not bool:
        raise SimulationError("EXPLICIT_SIMULATION_FACT_REQUIRED")


def _json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True)
    if len(encoded) > 32768:
        raise SimulationError("SIMULATION_EVENT_SIZE_LIMIT")
    return encoded


def _periods(at):
    day = datetime.fromtimestamp(at, UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"DAY": day.timestamp(), "WEEK": (day-timedelta(days=day.weekday())).timestamp()}


@dataclass(frozen=True)
class LossLatchPolicy:
    policy_id: str
    scope: AccountScope
    approved_actor: str
    approved_at: float
    daily_loss_limit_units: int
    weekly_loss_limit_units: int
    drawdown_limit_units: int
    max_data_age_seconds: int

    def __post_init__(self):
        _id(self.policy_id); _id(self.approved_actor); _at(self.approved_at)
        if not isinstance(self.scope, AccountScope):
            raise SimulationError("EXPLICIT_SIMULATION_SCOPE_REQUIRED")
        for value in (self.daily_loss_limit_units, self.weekly_loss_limit_units, self.drawdown_limit_units):
            _units(value, positive=True)
        if type(self.max_data_age_seconds) is not int or not 1 <= self.max_data_age_seconds <= 3600:
            raise SimulationError("BOUNDED_EXPLICIT_POLICY_REQUIRED")


@dataclass(frozen=True)
class PeriodBaseline:
    period: str
    started_at: float
    adjusted_equity_units: int
    evidence_id: str
    verified_complete: bool

    def __post_init__(self):
        _at(self.started_at); _units(self.adjusted_equity_units, signed=True); _id(self.evidence_id)
        _fact(self.verified_complete)
        if self.period not in {"DAY", "WEEK"} or _periods(self.started_at)[self.period] != self.started_at:
            raise SimulationError("EXACT_UTC_BOUNDARY_BASELINE_REQUIRED")


@dataclass(frozen=True)
class EquityObservation:
    scope: AccountScope
    actor: str
    evidence_id: str
    observed_at: float
    equity_units: int
    cumulative_net_cashflow_units: int
    account_identity_verified: bool
    inventory_complete: bool
    orders_reconciled: bool
    cashflow_history_complete: bool
    baselines: tuple[PeriodBaseline, ...]

    def __post_init__(self):
        _id(self.actor); _id(self.evidence_id); _at(self.observed_at)
        _units(self.equity_units, signed=True); _units(self.cumulative_net_cashflow_units, signed=True)
        if not isinstance(self.scope, AccountScope):
            raise SimulationError("EXPLICIT_SIMULATION_SCOPE_REQUIRED")
        for value in (self.account_identity_verified, self.inventory_complete,
                      self.orders_reconciled, self.cashflow_history_complete):
            _fact(value)
        if (not isinstance(self.baselines, tuple) or len(self.baselines) > 2
                or any(not isinstance(row, PeriodBaseline) for row in self.baselines)
                or len({row.period for row in self.baselines}) != len(self.baselines)):
            raise SimulationError("BOUNDED_IMMUTABLE_BASELINES_REQUIRED")


@dataclass(frozen=True)
class CashflowObservation:
    scope: AccountScope
    actor: str
    evidence_id: str
    occurred_at: float
    amount_units: int
    verified_complete: bool

    def __post_init__(self):
        _id(self.actor); _id(self.evidence_id); _at(self.occurred_at)
        _units(self.amount_units, signed=True); _fact(self.verified_complete)
        if not isinstance(self.scope, AccountScope) or self.amount_units == 0:
            raise SimulationError("EXPLICIT_NONZERO_SIMULATED_CASHFLOW_REQUIRED")


@contextmanager
def _connection(path, *, readonly=False):
    if readonly:
        if not path.is_file():
            raise SimulationError("SIMULATION_NOT_INITIALIZED")
        with path.open("rb") as handle:
            header = handle.read(100)
        if not header.startswith(b"SQLite format 3\0") or header[18:20] != b"\x01\x01":
            raise SimulationError("FOREIGN_OR_UNSUPPORTED_SIMULATION_FILE")
        db = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)
        db.execute("PRAGMA query_only=ON")
    else:
        db = sqlite3.connect(path, timeout=5)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
        yield db
        if not readonly:
            db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


class RiskLatchesShadow:
    """A persistent scenario loss gate with no execution or admission authority."""

    def __init__(self, path, *, wallet_name, policy, clock=time.time, fault_hook=None):
        _id(wallet_name)
        if not isinstance(policy, LossLatchPolicy):
            raise SimulationError("EXPLICIT_SIMULATION_POLICY_REQUIRED")
        self.path = Path(path)
        if self.path.name != wallet_name+".simulation.sqlite3" or self.path.is_symlink():
            raise SimulationError("SEPARATE_NAMED_SIMULATION_WALLET_REQUIRED")
        self.wallet_name, self.policy, self.clock, self.fault_hook = wallet_name, policy, clock, fault_hook
        self._frozen_identity = _json({"app": APP, "wallet_name": wallet_name, "policy": asdict(policy)})
        self._initialized = False

    def _identity(self, db):
        current = _json({"app": APP, "wallet_name": self.wallet_name, "policy": asdict(self.policy)})
        if current != self._frozen_identity:
            raise SimulationError("SIMULATION_POLICY_MUTATED")
        try:
            row = db.execute("SELECT data FROM identity WHERE singleton=1").fetchone()
        except sqlite3.Error:
            raise SimulationError("FOREIGN_SIMULATION_WALLET") from None
        if row is None or row[0] != self._frozen_identity:
            raise SimulationError("SIMULATION_IDENTITY_OR_POLICY_MISMATCH")

    def initialize(self):
        now = _at(self.clock())
        if now < self.policy.approved_at:
            raise SimulationError("FUTURE_POLICY_NOT_APPROVED")
        if self.path.exists():
            with _connection(self.path, readonly=True) as db:
                self._identity(db)
            self._initialized = True
            return self.snapshot()
        if not self.path.parent.is_dir():
            raise SimulationError("SIMULATION_DIRECTORY_MUST_EXIST")
        with self.path.open("xb"):
            pass
        with _connection(self.path) as db:
            db.execute("CREATE TABLE identity(singleton INTEGER PRIMARY KEY CHECK(singleton=1),data TEXT NOT NULL)")
            db.execute("INSERT INTO identity VALUES(1,?)", (self._frozen_identity,))
            db.execute("CREATE TABLE state(singleton INTEGER PRIMARY KEY CHECK(singleton=1),last_clock REAL NOT NULL,last_observed REAL,adjusted INTEGER,peak INTEGER,cashflows INTEGER NOT NULL,day_start REAL,week_start REAL,daily_loss INTEGER,weekly_loss INTEGER,drawdown INTEGER,daily_halt INTEGER NOT NULL,weekly_halt INTEGER NOT NULL,drawdown_halt INTEGER NOT NULL,manual_halt INTEGER NOT NULL,recovery INTEGER NOT NULL,disputed INTEGER NOT NULL,latest_valid INTEGER NOT NULL,last_reason TEXT NOT NULL)")
            db.execute("INSERT INTO state VALUES(1,?,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,NULL,0,0,0,0,0,0,0,'BASELINE_REQUIRED')", (now,))
            db.execute("CREATE TABLE baselines(period TEXT NOT NULL,started_at REAL NOT NULL,adjusted INTEGER NOT NULL,evidence TEXT NOT NULL,PRIMARY KEY(period,started_at))")
            db.execute("CREATE TABLE cashflows(evidence TEXT PRIMARY KEY,occurred_at REAL NOT NULL,amount INTEGER NOT NULL)")
            db.execute("CREATE TABLE equity_evidence(evidence TEXT PRIMARY KEY,digest TEXT NOT NULL)")
            db.execute("CREATE TABLE conflicts(event_id TEXT NOT NULL,payload_digest TEXT NOT NULL,payload TEXT NOT NULL,at REAL NOT NULL,PRIMARY KEY(event_id,payload_digest))")
            db.execute("CREATE TABLE events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,payload_digest TEXT NOT NULL,payload TEXT NOT NULL,result TEXT NOT NULL,at REAL NOT NULL)")
            for table in ("events", "baselines", "cashflows", "equity_evidence", "conflicts"):
                for operation in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'simulation evidence is append-only'); END")
        self._initialized = True
        return self.snapshot()

    @staticmethod
    def _invalidate(db, reason, *, disputed=False):
        db.execute("UPDATE state SET recovery=1,latest_valid=0,disputed=MAX(disputed,?),last_reason=? WHERE singleton=1",
                   (int(disputed), reason))
        return {"recorded": False, "reason": reason}

    def _apply(self, event_id, payload, mutation):
        if not self._initialized:
            raise SimulationError("EXPLICIT_INITIALIZE_REQUIRED")
        _id(event_id)
        encoded = _json(payload)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        # A read-only identity check prevents opening a substituted financial DB
        # for writes. The same check is repeated inside the write transaction.
        with _connection(self.path, readonly=True) as db:
            self._identity(db)
        with _connection(self.path) as db:
            self._identity(db)
            prior = db.execute("SELECT payload_digest,result FROM events WHERE id=?", (event_id,)).fetchone()
            conflict = prior is not None and prior[0] != digest
            if prior and not conflict:
                return json.loads(prior[1])
            now = _at(self.clock())
            if conflict:
                if payload.get("kind") == "MANUAL_HALT":
                    # An explicit halt remains conservative even if the sender
                    # reused a message ID. Keep both the halt and the dispute;
                    # the original immutable receipt is never overwritten.
                    db.execute("UPDATE state SET manual_halt=1 WHERE singleton=1")
                result = self._invalidate(db, "IDEMPOTENCY_CONFLICT", disputed=True)
                if payload.get("kind") == "MANUAL_HALT":
                    result["manual_halt"] = True
                db.execute("INSERT OR IGNORE INTO conflicts VALUES(?,?,?,?)", (event_id, digest, encoded, now))
            else:
                state = db.execute("SELECT * FROM state WHERE singleton=1").fetchone()
                if now < state["last_clock"]:
                    result = self._invalidate(db, "CLOCK_REGRESSION")
                    if payload.get("kind") == "MANUAL_HALT":
                        # Applying a halt needs no trustworthy market clock.
                        # The independent clock-recovery latch remains active.
                        db.execute("UPDATE state SET manual_halt=1 WHERE singleton=1")
                        result.update(recorded=True, manual_halt=True)
                else:
                    db.execute("SAVEPOINT mutation")
                    try:
                        result = mutation(db, state, now)
                    except SimulationError as error:
                        # Even bounded individual integers can overflow a derived
                        # sum/difference. Preserve no partial evidence, but durably
                        # invalidate the last usable gate rather than leaving it green.
                        db.execute("ROLLBACK TO mutation")
                        result = self._invalidate(db, str(error))
                    finally:
                        db.execute("RELEASE mutation")
                    db.execute("UPDATE state SET last_clock=? WHERE singleton=1", (now,))
            result.update(simulation_only=True, execution_enabled=False, admission_authority=False)
            if not conflict:
                db.execute("INSERT INTO events(id,payload_digest,payload,result,at) VALUES(?,?,?,?,?)",
                           (event_id, digest, encoded, _json(result), now))
            if self.fault_hook:
                self.fault_hook("BEFORE_COMMIT")
        if self.fault_hook:
            self.fault_hook("AFTER_COMMIT")
        return result

    def record_cashflow(self, event_id, observation):
        if not isinstance(observation, CashflowObservation) or observation.scope != self.policy.scope:
            raise SimulationError("CASHFLOW_SCOPE_MISMATCH")

        def mutation(db, state, now):
            if not observation.verified_complete or not 0 <= now-observation.occurred_at <= self.policy.max_data_age_seconds:
                return self._invalidate(db, "CASHFLOW_UNVERIFIED_OR_STALE")
            existing = db.execute("SELECT occurred_at,amount FROM cashflows WHERE evidence=?", (observation.evidence_id,)).fetchone()
            if existing:
                if tuple(existing) != (observation.occurred_at, observation.amount_units):
                    return self._invalidate(db, "CASHFLOW_EVIDENCE_CONFLICT", disputed=True)
                return {"recorded": True, "duplicate_evidence": True}
            if state["last_observed"] is not None and observation.occurred_at <= state["last_observed"]:
                return self._invalidate(db, "CASHFLOW_WOULD_REWRITE_VERIFIED_HISTORY", disputed=True)
            amount = _units(state["cashflows"]+observation.amount_units, signed=True)
            db.execute("INSERT INTO cashflows VALUES(?,?,?)", (observation.evidence_id, observation.occurred_at, observation.amount_units))
            db.execute("UPDATE state SET cashflows=?,latest_valid=0,last_reason='EQUITY_AFTER_CASHFLOW_REQUIRED' WHERE singleton=1", (amount,))
            return {"recorded": True, "cumulative_net_cashflow_units": amount}

        return self._apply(event_id, {"kind": "CASHFLOW", "observation": asdict(observation)}, mutation)

    def observe(self, event_id, observation):
        if not isinstance(observation, EquityObservation) or observation.scope != self.policy.scope:
            raise SimulationError("OBSERVATION_SCOPE_MISMATCH")

        def mutation(db, state, now):
            evidence_digest = hashlib.sha256(_json(asdict(observation)).encode()).hexdigest()
            evidence = db.execute("SELECT digest FROM equity_evidence WHERE evidence=?", (observation.evidence_id,)).fetchone()
            if evidence:
                if evidence[0] != evidence_digest:
                    return self._invalidate(db, "EQUITY_EVIDENCE_ID_CONFLICT", disputed=True)
                return {"recorded": True, "duplicate_evidence": True}
            if not all((observation.account_identity_verified, observation.inventory_complete,
                        observation.orders_reconciled, observation.cashflow_history_complete)):
                return self._invalidate(db, "INCOMPLETE_OR_UNVERIFIED_ACCOUNT_EVIDENCE")
            if not 0 <= now-observation.observed_at <= self.policy.max_data_age_seconds:
                return self._invalidate(db, "STALE_OR_FUTURE_EQUITY")
            if state["last_observed"] is not None and observation.observed_at < state["last_observed"]:
                return self._invalidate(db, "OBSERVATION_TIME_REGRESSION")
            if observation.cumulative_net_cashflow_units != state["cashflows"]:
                return self._invalidate(db, "CASHFLOW_HISTORY_NOT_RECONCILED")
            newest_flow = db.execute("SELECT MAX(occurred_at) FROM cashflows").fetchone()[0]
            if newest_flow is not None and observation.observed_at < newest_flow:
                return self._invalidate(db, "EQUITY_PRECEDES_KNOWN_CASHFLOW")
            adjusted = _units(observation.equity_units-state["cashflows"], signed=True)
            if observation.observed_at == state["last_observed"] and adjusted != state["adjusted"]:
                return self._invalidate(db, "CONFLICTING_EQUITY_AT_SAME_TIME", disputed=True)
            periods = _periods(observation.observed_at)
            if periods != _periods(now):
                return self._invalidate(db, "CURRENT_UTC_PERIOD_BASELINE_REQUIRED")
            supplied = {row.period: row for row in observation.baselines}
            values = {}
            # Validate all proposed baselines before storing either one.
            for period, start in periods.items():
                row = supplied.get(period)
                saved = db.execute("SELECT adjusted FROM baselines WHERE period=? AND started_at=?", (period, start)).fetchone()
                if row is not None and (row.started_at != start or not row.verified_complete):
                    return self._invalidate(db, "CURRENT_VERIFIED_UTC_BASELINE_REQUIRED")
                if saved and row is not None and saved[0] != row.adjusted_equity_units:
                    return self._invalidate(db, "IMMUTABLE_BASELINE_CONFLICT", disputed=True)
                if not saved and row is None:
                    return self._invalidate(db, "CURRENT_VERIFIED_UTC_BASELINE_REQUIRED")
                values[period] = saved[0] if saved else row.adjusted_equity_units
            if periods["DAY"] == periods["WEEK"] and values["DAY"] != values["WEEK"]:
                return self._invalidate(db, "CONFLICTING_BASELINES_AT_SAME_BOUNDARY", disputed=True)
            if any(observation.observed_at == start and values[period] != adjusted
                   for period, start in periods.items()):
                return self._invalidate(db, "BASELINE_CONFLICTS_WITH_BOUNDARY_EQUITY", disputed=True)
            for period, start in periods.items():
                row = supplied.get(period)
                if row is not None:
                    db.execute("INSERT OR IGNORE INTO baselines VALUES(?,?,?,?)", (period, start, row.adjusted_equity_units, row.evidence_id))
            peak = max(adjusted, values["DAY"], values["WEEK"], state["peak"] if state["peak"] is not None else adjusted)
            daily = _units(max(0, values["DAY"]-adjusted))
            weekly = _units(max(0, values["WEEK"]-adjusted))
            drawdown = _units(max(0, peak-adjusted))
            daily_halt = (state["daily_halt"] if state["day_start"] == periods["DAY"] else False) or daily >= self.policy.daily_loss_limit_units
            weekly_halt = (state["weekly_halt"] if state["week_start"] == periods["WEEK"] else False) or weekly >= self.policy.weekly_loss_limit_units
            drawdown_halt = state["drawdown_halt"] or drawdown >= self.policy.drawdown_limit_units
            db.execute("UPDATE state SET last_observed=?,adjusted=?,peak=?,day_start=?,week_start=?,daily_loss=?,weekly_loss=?,drawdown=?,daily_halt=?,weekly_halt=?,drawdown_halt=?,latest_valid=1,last_reason='VERIFIED_SIMULATION_OBSERVATION' WHERE singleton=1",
                       (observation.observed_at, adjusted, peak, periods["DAY"], periods["WEEK"], daily, weekly, drawdown,
                        int(daily_halt), int(weekly_halt), int(drawdown_halt)))
            db.execute("INSERT INTO equity_evidence VALUES(?,?)", (observation.evidence_id, evidence_digest))
            return {"recorded": True, "daily_loss_units": daily, "weekly_loss_units": weekly, "drawdown_units": drawdown}

        return self._apply(event_id, {"kind": "EQUITY_OBSERVATION", "observation": asdict(observation)}, mutation)

    def set_manual_halt(self, event_id, *, actor, evidence_id):
        _id(actor); _id(evidence_id)

        def mutation(db, state, now):
            db.execute("UPDATE state SET manual_halt=1 WHERE singleton=1")
            return {"recorded": True, "manual_halt": True}

        return self._apply(event_id, {"kind": "MANUAL_HALT", "actor": actor, "evidence_id": evidence_id}, mutation)

    def acknowledge(self, event_id, *, actor, evidence_id, target):
        """Clear only a recovered SIM latch; never erase a peak or period loss.

        Recovery needs a newer accepted complete observation. Permanent baseline,
        equity or historical-flow contradictions cannot be acknowledged away.
        Manual and drawdown acknowledgements do not clear other latches.
        """
        _id(actor); _id(evidence_id)
        if target not in {"RECOVERY", "MANUAL", "DRAWDOWN"}:
            raise SimulationError("EXPLICIT_SIMULATION_RESET_TARGET_REQUIRED")

        def mutation(db, state, now):
            reasons = self._data_reasons(state, now)
            if reasons or state["disputed"]:
                return {"recorded": False, "reason": "FRESH_UNDISPUTED_BASELINE_REQUIRED"}
            if target == "RECOVERY":
                db.execute("UPDATE state SET recovery=0 WHERE singleton=1")
            elif target == "MANUAL":
                db.execute("UPDATE state SET manual_halt=0 WHERE singleton=1")
            elif state["drawdown"] >= self.policy.drawdown_limit_units:
                return {"recorded": False, "reason": "DRAWDOWN_THRESHOLD_STILL_EXCEEDED"}
            else:
                db.execute("UPDATE state SET drawdown_halt=0 WHERE singleton=1")
            return {"recorded": True, "acknowledged": target}

        return self._apply(event_id, {"kind": "ACKNOWLEDGEMENT", "actor": actor, "evidence_id": evidence_id, "target": target}, mutation)

    def _data_reasons(self, state, now):
        reasons = []
        if now < state["last_clock"]:
            reasons.append("CLOCK_REGRESSION")
        if not state["latest_valid"] or state["last_observed"] is None:
            reasons.append("COMPLETE_VERIFIED_OBSERVATION_REQUIRED")
        elif not 0 <= now-state["last_observed"] <= self.policy.max_data_age_seconds:
            reasons.append("STALE_OR_FUTURE_EQUITY")
        periods = _periods(now)
        if state["day_start"] != periods["DAY"] or state["week_start"] != periods["WEEK"]:
            reasons.append("CURRENT_UTC_PERIOD_BASELINE_REQUIRED")
        return reasons

    def snapshot(self):
        """Read-only current gate. Historical mutation receipts never admit entry."""
        if not self._initialized:
            raise SimulationError("EXPLICIT_INITIALIZE_REQUIRED")
        with _connection(self.path, readonly=True) as db:
            self._identity(db)
            state = db.execute("SELECT * FROM state WHERE singleton=1").fetchone()
            now = _at(self.clock())
            reasons = self._data_reasons(state, now)
            if state["recovery"]:
                reasons.append("PERSISTENT_RECOVERY_LATCH")
            if state["disputed"]:
                reasons.append("IMMUTABLE_EVIDENCE_DISPUTE")
            recovery = bool(reasons)
            for key, label in (("daily_halt", "DAILY_LOSS_LATCH"), ("weekly_halt", "WEEKLY_LOSS_LATCH"),
                               ("drawdown_halt", "DRAWDOWN_LATCH"), ("manual_halt", "MANUAL_LATCH")):
                if state[key]:
                    reasons.append(label)
            status = "RECOVERY_REQUIRED" if recovery else "ENTRY_HALTED" if reasons else "NORMAL"
            return {"schema": 1, "engine": "RISK_LATCHES_SHADOW", "mode": "SIMULATION", "state": status,
                    "scope": asdict(self.policy.scope), "policy_id": self.policy.policy_id,
                    "loss_gate_clear": not reasons, "reasons": reasons, "last_reason": state["last_reason"],
                    "last_observed_at": state["last_observed"], "day_start_at": state["day_start"], "week_start_at": state["week_start"],
                    "daily_loss_units": state["daily_loss"], "weekly_loss_units": state["weekly_loss"], "drawdown_units": state["drawdown"],
                    "cashflow_adjusted_equity_units": state["adjusted"], "high_water_mark_units": state["peak"],
                    "cumulative_net_cashflow_units": state["cashflows"], "event_count": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    "idempotency_conflict_count": db.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0],
                    "simulation_only": True, "admission_authority": False, "execution_enabled": False,
                    "full_risk_admission_verified": False, "protective_exits_intercepted": False}
