"""Atomic risk/capital lifecycle for explicitly funded SHADOW simulations only.

This is not an engine adapter. No broker, executor callback, credentials, HTTP or
AI is imported. A submission claim is a durable synthetic receipt, never an order
or permission to send one. Existing engines and protective exits do not use it.

Risk assessment, active simulated exposures and reservation share one SQLite
BEGIN IMMEDIATE transaction. Full original gross/stop risk is retained through
partial/unknown states until confirmed closure; LONG/SHORT are never netted.
Caller-supplied inventory/loss facts remain synthetic assertions. The snapshot
risk assessor has no durable daily/weekly loss latch: those require a separate
validated policy/store before any operational integration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import time

from .capital_manager_shadow import (
    AccountScope, CapitalManagerShadow, ReconciliationEvent, ReservationRequest,
    SimulationError, SimulationLimits, _connection, _id, _json,
)
from .global_risk_shadow import Candidate, Exposure, Inventory, RiskPolicy, assess_risk


APP = 'CAPITAL_FLOW_SHADOW_V1'
LIMITATIONS = (
    'EXPLICIT_SYNTHETIC_ASSERTIONS_NOT_BINANCE_ACCOUNT_CERTIFICATION',
    'NO_OPERATING_ENGINE_ADMISSION_OR_EXCHANGE_EXECUTOR',
    'NO_COMMON_CAPITAL_ACROSS_ACCOUNTS_OR_ENVIRONMENTS',
    'ATOMICITY_LIMITED_TO_ONE_NAMED_SIMULATION_FILE_NOT_CROSS_FILE_REGISTRATION',
    'ORIGINAL_GROSS_AND_STOP_RISK_RETAINED_UNTIL_CONFIRMED_CLOSE',
    'NO_ATOMIC_PERSISTENT_LOSS_GATE_OR_MARK_TO_MARKET_VALUATION_IN_THIS_FLOW',
    'EXTERNAL_INVENTORY_LOSS_AND_CORRELATION_FACTS_NOT_INDEPENDENTLY_VERIFIED',
    'NO_TTL_RELEASE_OR_ATOMIC_MULTI_LEG_EXECUTION',
)


def _authority():
    return {'simulation_only': True, 'mode': 'SHADOW',
            'execution_enabled': False, 'controls_enabled': False, 'can_veto': False,
            'reservations_enabled': False, 'promotion_allowed': False,
            'live_implemented': False, 'real_account_adapter': False,
            'atomic_hedge_claimed': False}


@dataclass(frozen=True)
class Admission:
    request: ReservationRequest
    candidate: Candidate
    inventory: Inventory

    def __post_init__(self):
        if (not isinstance(self.request, ReservationRequest)
                or not isinstance(self.candidate, Candidate)
                or not isinstance(self.inventory, Inventory)):
            raise SimulationError('TYPED_SHADOW_ADMISSION_REQUIRED')
        r, c = self.request, self.candidate
        if (r.scope != c.scope or r.scope != self.inventory.scope
                or r.request_id != c.candidate_id
                or c.required_margin_units != sum(x.principal_units+x.fee_buffer_units for x in r.legs)
                or len(r.legs) != len(c.legs)):
            raise SimulationError('CANDIDATE_RESERVATION_BINDING_MISMATCH')
        exposures = {x.exposure_id: x for x in c.legs}
        for leg in r.legs:
            row = exposures.get(leg.leg_id)
            if (row is None or row.engine_id != r.strategy_id or row.symbol != leg.symbol
                    or row.direction != leg.direction or row.inclusive_stop_risk_units != leg.stop_risk_units):
                raise SimulationError('CANDIDATE_LEG_BINDING_MISMATCH')
            if leg.venue == 'SPOT_REFERENCE' and (row.direction != 'LONG' or row.leverage_milli != 1000):
                raise SimulationError('SPOT_SIMULATION_REQUIRES_UNLEVERED_LONG')
            if leg.venue == 'FUTURES_REFERENCE' and row.leverage_milli % 1000:
                raise SimulationError('INTEGRAL_SIMULATED_FUTURES_LEVERAGE_REQUIRED')
            # The base protocol reconciles filled principal, not exchange
            # notional. Bind that principal to the authorized gross exactly at
            # the integer margin ceiling, so overfunding cannot later conceal a
            # larger fill behind a deliberately understated risk exposure.
            if leg.principal_units != (row.gross_units*1000+row.leverage_milli-1)//row.leverage_milli:
                raise SimulationError('LEG_CAPITAL_NOT_BOUND_TO_AUTHORIZED_GROSS')
            if c.estimated_fee_bps is not None and c.estimated_slippage_bps is not None:
                floor = (row.gross_units*(2*c.estimated_fee_bps+2*c.estimated_slippage_bps)+9999)//10000
                if leg.fee_buffer_units < floor:
                    raise SimulationError('LEG_COST_BUFFER_BELOW_CONSERVATIVE_FLOOR')


class _FlowManager(CapitalManagerShadow):
    """Bind one immutable call context; concurrent callers never share scratch state."""
    def __init__(self, *args, flow, admission=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.flow, self.admission = flow, admission

    def _identity(self, db):
        super()._identity(db)
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='flow_identity'").fetchone():
            self.flow._identity(db)
        elif self.flow._initialized:
            raise SimulationError('FLOW_RISK_IDENTITY_MISSING')

    def _apply(self, event_id, payload, mutation):
        kind = payload.get('kind')
        if kind == 'RESERVE':
            if self.admission is None:
                raise SimulationError('ATOMIC_RISK_ADMISSION_REQUIRED')
            payload = {**payload, 'risk_policy': asdict(self.flow.risk_policy),
                       'admission': asdict(self.admission)}

        def guarded(db):
            self.flow._identity(db)
            if kind == 'RESERVE':
                admission = self.admission
                active = db.execute("SELECT r.id,c.candidate FROM requests r LEFT JOIN flow_candidates c ON c.request_id=r.id WHERE r.state NOT IN ('CANCELLED','CLOSED')").fetchall()
                if any(row['candidate'] is None for row in active):
                    return {'accepted': False, 'reason': 'UNTRACKED_SIMULATED_REQUEST', **_authority()}
                durable = tuple(Exposure(**leg) for row in active
                                for leg in json.loads(row['candidate'])['legs'])
                supplied = admission.inventory.positions+admission.inventory.pending
                all_ids = [row.exposure_id for row in supplied+durable+admission.candidate.legs]
                if len(all_ids) != len(set(all_ids)):
                    return {'accepted': False, 'reason': 'DUPLICATE_MANAGED_EXPOSURE', **_authority()}
                for leg in admission.candidate.legs:
                    if db.execute('SELECT 1 FROM flow_exposures WHERE exposure_id=?', (leg.exposure_id,)).fetchone():
                        raise SimulationError('SIMULATED_EXPOSURE_ID_ALREADY_USED')
                totals = self._totals(db)
                margin = admission.inventory.available_margin_units
                # Both quantities are net available values; cap, never subtract
                # local reservations twice from a caller's already-net value.
                inventory = replace(admission.inventory,
                    pending=admission.inventory.pending+durable,
                    available_margin_units=None if margin is None else min(margin, totals['available_units']))
                risk = assess_risk(self.flow.risk_policy, inventory, admission.candidate, now=self.clock())
                if not risk['hypothetical_admission']:
                    return {'accepted': False, 'reason': 'SIMULATED_RISK_REJECTED', 'risk': risk, **_authority()}
                result = mutation(db)  # Existing atomic capital/risk/strategy/asset checks.
                if result['accepted']:
                    db.execute('INSERT INTO flow_candidates VALUES(?,?,?,?)',
                        (admission.request.request_id, _json(asdict(admission.candidate)),
                         _json(risk), _json(asdict(admission.inventory))))
                    db.executemany('INSERT INTO flow_exposures VALUES(?,?)',
                        [(leg.exposure_id, admission.request.request_id) for leg in admission.candidate.legs])
                return {**result, 'risk': risk, **_authority()}
            if kind == 'MARK_SUBMITTING':
                request_id = payload['request_id']
                stored = db.execute('SELECT candidate,inventory FROM flow_candidates WHERE request_id=?', (request_id,)).fetchone()
                if stored is None:
                    raise SimulationError('ATOMIC_ADMISSION_RECORD_REQUIRED')
                candidate_data, inventory_data = json.loads(stored[0]), json.loads(stored[1])
                candidate = Candidate(**{**candidate_data, 'legs': tuple(Exposure(**x) for x in candidate_data['legs']),
                    'scope': AccountScope(**candidate_data['scope'])})
                active = db.execute("SELECT r.id,c.candidate FROM requests r LEFT JOIN flow_candidates c ON c.request_id=r.id WHERE r.state NOT IN ('CANCELLED','CLOSED') AND r.id<>?", (request_id,)).fetchall()
                if any(row['candidate'] is None for row in active):
                    return {'accepted': False, 'reason': 'UNTRACKED_SIMULATED_REQUEST', **_authority()}
                durable = tuple(Exposure(**leg) for row in active for leg in json.loads(row['candidate'])['legs'])
                inventory = Inventory(**{**inventory_data, 'scope': AccountScope(**inventory_data['scope']),
                    'positions': tuple(Exposure(**x) for x in inventory_data['positions']),
                    'pending': tuple(Exposure(**x) for x in inventory_data['pending'])+durable})
                risk = assess_risk(self.flow.risk_policy, inventory, candidate, now=self.clock())
                if not risk['hypothetical_admission']:
                    return {'accepted': False, 'state': 'RESERVED',
                            'reason': 'SIMULATED_RISK_REJECTED_AT_CLAIM', 'risk': risk, **_authority()}
                result = mutation(db)
                if result['accepted']:
                    receipt = 'SIM_RECEIPT_'+hashlib.sha256((self.flow.wallet_name+'|'+request_id).encode()).hexdigest()[:48]
                    db.execute('INSERT INTO flow_claims VALUES(?,?,?)', (request_id, receipt, self.clock()))
                    return {**result, 'synthetic_receipt': receipt, 'submission_permitted': False,
                            'claim_kind': 'ONE_DURABLE_SYNTHETIC_INTENTION', **_authority()}
                return {**result, **_authority()}
            return {**mutation(db), **_authority()}

        return super()._apply(event_id, payload, guarded)


class CapitalFlowShadow:
    def __init__(self, path, *, wallet_name: str, scope: AccountScope,
                 limits: SimulationLimits, risk_policy: RiskPolicy, clock=time.time):
        if (not isinstance(risk_policy, RiskPolicy) or not isinstance(scope, AccountScope)
                or scope.environment != 'SHADOW' or risk_policy.scope != scope
                or not isinstance(limits, SimulationLimits)):
            raise SimulationError('EXPLICIT_MATCHING_SHADOW_POLICIES_REQUIRED')
        if not isinstance(wallet_name, str) or not wallet_name.startswith('SIM_FLOW_'):
            raise SimulationError('SEPARATE_FLOW_SIMULATION_WALLET_REQUIRED')
        _id(wallet_name)
        if {x[0] for x in limits.strategy_limits} != {x[0] for x in risk_policy.engine_limits}:
            raise SimulationError('RISK_AND_CAPITAL_PARTICIPANTS_MISMATCH')
        self.path, self.wallet_name, self.scope = Path(path), wallet_name, scope
        self.limits, self.risk_policy, self.clock = limits, risk_policy, clock
        self._frozen = _json({'app': APP, 'scope': asdict(scope), 'risk_policy': asdict(risk_policy)})
        self._initialized = False
        self._test_fault_hook = None  # Only offline fault injection; never an executor.

    def _manager(self, admission=None):
        manager = _FlowManager(self.path, wallet_name=self.wallet_name, scope=self.scope,
            limits=self.limits, clock=self.clock, flow=self, admission=admission,
            fault_hook=self._test_fault_hook)
        manager._initialized = self._initialized
        return manager

    def _identity(self, db):
        current = _json({'app': APP, 'scope': asdict(self.scope), 'risk_policy': asdict(self.risk_policy)})
        if current != self._frozen:
            raise SimulationError('FLOW_RISK_POLICY_MUTATED')
        row = db.execute('SELECT data FROM flow_identity WHERE singleton=1').fetchone()
        if row is None or row[0] != self._frozen:
            raise SimulationError('FLOW_RISK_POLICY_IDENTITY_MISMATCH')

    def initialize(self):
        manager = self._manager()
        # Existing strict identity prevents adopting an operational/foreign DB.
        manager.initialize()
        with _connection(self.path) as db:
            manager._identity(db)
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='flow_identity'").fetchone()
            if not exists:
                if db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]:
                    raise SimulationError('CANNOT_ADOPT_EXISTING_SIMULATED_REQUESTS')
                db.execute('CREATE TABLE flow_identity(singleton INTEGER PRIMARY KEY CHECK(singleton=1),data TEXT NOT NULL)')
                db.execute('INSERT INTO flow_identity VALUES(1,?)', (self._frozen,))
                db.execute('CREATE TABLE flow_candidates(request_id TEXT PRIMARY KEY,candidate TEXT NOT NULL,risk TEXT NOT NULL,inventory TEXT NOT NULL)')
                db.execute('CREATE TABLE flow_exposures(exposure_id TEXT PRIMARY KEY,request_id TEXT NOT NULL)')
                db.execute('CREATE TABLE flow_claims(request_id TEXT PRIMARY KEY,receipt TEXT UNIQUE NOT NULL,at REAL NOT NULL)')
            self._identity(db)
        self._initialized = True
        return self.snapshot()

    def admit(self, admission: Admission):
        if not isinstance(admission, Admission):
            raise SimulationError('TYPED_SHADOW_ADMISSION_REQUIRED')
        return self._manager(admission).reserve(admission.request)

    def claim_submission(self, request_id: str, *, actor: str):
        _id(request_id); _id(actor)
        with _connection(self.path, True) as db:
            self._identity(db)
            ids = [row[0] for row in db.execute('SELECT id FROM legs WHERE request_id=? ORDER BY id', (request_id,))]
        # Stable identities across restart/repeated messages. No receipt can be
        # interpreted as a broker invocation or permission to invoke one.
        digest = hashlib.sha256(request_id.encode()).hexdigest()[:40]
        order_ids = {leg: 'SIM_ORDER_'+hashlib.sha256((request_id+'|'+leg).encode()).hexdigest()[:48] for leg in ids}
        return self._manager().mark_submitting('SIM_FLOW_CLAIM_'+digest, request_id,
            actor=actor, client_order_ids=order_ids)

    def reconcile(self, event: ReconciliationEvent):
        return self._manager().reconcile(event)

    def request_cancel(self, event_id, request_id, *, actor):
        return self._manager().request_cancel(event_id, request_id, actor=actor)

    def recover(self, event_id, *, actor):
        return self._manager().recover(event_id, actor=actor)

    def observe_balance(self, event_id, **facts):
        return self._manager().observe_balance(event_id, **facts)

    def snapshot(self):
        manager = self._manager()
        value = manager.snapshot()
        with _connection(self.path, True) as db:
            self._identity(db)
            count = db.execute('SELECT COUNT(*) FROM flow_claims').fetchone()[0]
            admissions = db.execute('SELECT COUNT(*) FROM flow_candidates').fetchone()[0]
        return {**value, 'flow_app': APP, 'risk_policy_id': self.risk_policy.policy_id,
                'admitted_request_count': admissions, 'synthetic_submission_claim_count': count,
                'simulation_reservations_enabled': True, **_authority(),
                'limitations': list(LIMITATIONS), 'snapshot_globally_atomic': False}
