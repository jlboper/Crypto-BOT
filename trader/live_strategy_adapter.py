"""Prepared native strategy adapter. No keys, network, defaults or activation.

Only a caller already operating on an explicitly identified LIVE source may
construct an executable plan. Testnet/Shadow observations cannot be relabelled.
The engine commissioning guard and local owner authority remain independent.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat

from .central_admission import AdmissionFacts, AdmissionPolicy, CentralAdmission, EntryProposal, Scope
from .domain import AIReview, Signal
from .live_execution_runtime import ConfirmedPosition, LiveExecutionCoordinator, NativeProtectionPlan
from .live_transport import LiveError, LiveOrderIntent

MICRO = Decimal(1_000_000)
MAX_PLAN_BYTES = 32768
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z', re.ASCII)
_HEX = re.compile(r'[a-f0-9]{64}\Z', re.ASCII)


def _canonical(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
    if len(raw) > MAX_PLAN_BYTES:
        raise LiveError('BOUNDED_STRATEGY_PLAN_REQUIRED')
    return raw


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decimal(value):
    if type(value) not in (str, int) or len(str(value)) > 64:
        raise LiveError('EXACT_STRATEGY_DECIMAL_REQUIRED')
    try:
        number = Decimal(value)
        if not number.is_finite() or not 0 < number < Decimal('1e15') or number.as_tuple().exponent < -18:
            raise ValueError()
        return number
    except (ValueError, InvalidOperation):
        raise LiveError('EXACT_STRATEGY_DECIMAL_REQUIRED') from None


def _native_decimal(value):
    if type(value) not in (int, float, str, Decimal) or type(value) is float and not math.isfinite(value):
        raise LiveError('FINITE_NATIVE_STRATEGY_NUMBER_REQUIRED')
    text = format(Decimal(str(value)), 'f')
    _decimal(text)
    return text


def _time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 253402300799:
        raise LiveError('STRATEGY_UTC_TIME_REQUIRED')
    return float(value)


def _identifier(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise LiveError('STRATEGY_IDENTIFIER_REQUIRED')


def _ceil(value):
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _on_grid(value, step):
    with localcontext() as context:
        context.prec = 80
        return value % step == 0


def _single_file_identity(path, error):
    """Read-only descriptor/name comparison before SQLite may touch metadata."""
    try:
        named=path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(named.st_mode) or named.st_nlink!=1:
        raise LiveError(error)
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)
    descriptor=os.open(path,flags)
    try:
        opened=os.fstat(descriptor);current=path.lstat()
        identity=(opened.st_dev,opened.st_ino)
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode)
                or opened.st_nlink!=1 or current.st_nlink!=1
                or identity!=(named.st_dev,named.st_ino) or identity!=(current.st_dev,current.st_ino)):
            raise LiveError(error)
        return identity
    finally:os.close(descriptor)


@dataclass(frozen=True)
class NativeStrategyDecision:
    decision_id: str
    scope: Scope
    source_environment: str
    engine_id: str
    symbol: str
    direction: str
    quantity: str
    reference_price: str
    stop_price: str
    take_profit: str
    stop_limit_price: str | None
    leverage_milli: int
    correlation_group: str
    source_observed_at: float
    reviewed_at: float
    decision_at: float
    expires_at: float
    strategy_fingerprint: str
    source_digest: str
    review: AIReview
    review_model: str
    quantitative_checks_passed: bool

    def __post_init__(self):
        for value in (self.decision_id, self.correlation_group, self.strategy_fingerprint, self.review_model):
            _identifier(value)
        if (type(self.scope) is not Scope or self.scope.environment not in {'SPOT_LIVE', 'FUTURES_LIVE'}
                or self.source_environment != self.scope.environment
                or self.engine_id != ('SPOT' if self.scope.environment == 'SPOT_LIVE' else 'FUTURES')):
            raise LiveError('LIVE_SOURCE_SCOPE_REQUIRED_NOT_A_TESTNET_PROMOTION')
        if type(self.source_digest) is not str or not _HEX.fullmatch(self.source_digest):
            raise LiveError('NATIVE_STRATEGY_EVIDENCE_SHA256_REQUIRED')
        if type(self.symbol) is not str or not re.fullmatch(r'[A-Z0-9]{2,24}USDT', self.symbol, re.ASCII):
            raise LiveError('NATIVE_STRATEGY_SYMBOL_REQUIRED')
        if self.direction not in {'LONG', 'SHORT'}:
            raise LiveError('NATIVE_STRATEGY_DIRECTION_REQUIRED')
        quantity, reference, stop, target = map(_decimal, (self.quantity, self.reference_price, self.stop_price, self.take_profit))
        if not (stop < reference < target if self.direction == 'LONG' else target < reference < stop):
            raise LiveError('NATIVE_STRATEGY_PROTECTION_DIRECTION_REQUIRED')
        if (type(self.leverage_milli) is not int or not 1000 <= self.leverage_milli <= 125000
                or type(self.quantitative_checks_passed) is not bool):
            raise LiveError('EXPLICIT_NATIVE_QUANTITATIVE_TERMS_REQUIRED')
        if self.engine_id == 'SPOT':
            if self.direction != 'LONG' or self.leverage_milli != 1000 or self.stop_limit_price is None or _decimal(self.stop_limit_price) > stop:
                raise LiveError('NATIVE_SPOT_UNLEVERED_OCO_REQUIRED')
        elif self.stop_limit_price is not None:
            raise LiveError('FUTURES_STOP_LIMIT_NOT_SUPPORTED')
        times = tuple(map(_time, (self.source_observed_at, self.reviewed_at, self.decision_at, self.expires_at)))
        if not times[0] <= times[1] <= times[2] < times[3] or not 0 < times[3] - times[2] <= 30:
            raise LiveError('NATIVE_DECISION_CAUSALITY_OR_EXPIRY_REQUIRED')
        if (type(self.review) is not AIReview or self.review.verdict not in {'ALLOW', 'REDUCE', 'REJECT'}
                or type(self.review.reason) is not str or len(self.review.reason) > 240):
            raise LiveError('NATIVE_INDIVIDUAL_AI_REVIEW_REQUIRED')
        for number in (self.review.confidence, self.review.risk_multiplier):
            if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 1:
                raise LiveError('NATIVE_INDIVIDUAL_AI_REVIEW_REQUIRED')

    @classmethod
    def from_spot(cls, signal, review, *, quantity, stop_limit_price, **context):
        """Use the final native Signal after quantitative price/size checks."""
        if type(signal) is not Signal or signal.action != 'BUY':
            raise LiveError('NATIVE_SPOT_BUY_SIGNAL_REQUIRED')
        return cls(engine_id='SPOT', symbol=signal.symbol, direction='LONG', quantity=_native_decimal(quantity),
                   reference_price=_native_decimal(signal.price), stop_price=_native_decimal(signal.stop_price),
                   take_profit=_native_decimal(signal.take_profit), stop_limit_price=_native_decimal(stop_limit_price),
                   review=review, **context)

    @classmethod
    def from_futures(cls, signal, review, *, quantity, reference_price, stop_price, take_profit, **context):
        """Preserve native LONG/SHORT; never let AI choose or invert direction."""
        if type(signal) is not dict or signal.get('direction') not in {'LONG', 'SHORT'}:
            raise LiveError('NATIVE_FUTURES_SIGNAL_REQUIRED')
        return cls(engine_id='FUTURES', symbol=signal.get('symbol'), direction=signal['direction'],
                   quantity=_native_decimal(quantity), reference_price=_native_decimal(reference_price),
                   stop_price=_native_decimal(stop_price), take_profit=_native_decimal(take_profit),
                   stop_limit_price=None, review=review, **context)


@dataclass(frozen=True)
class VenueExecutionEvidence:
    scope: Scope
    evidence_digest: str
    observed_at: float
    received_at: float
    reference_price: str
    quantity_step: str
    minimum_quantity: str
    maximum_quantity: str
    price_tick: str
    minimum_notional_units: int
    maximum_notional_units: int | None
    fee_bps: int
    slippage_bps: int
    spread_bps: int
    available_depth_units: int
    configured_leverage_milli: int
    filters_complete: bool
    protection_filters_verified: bool
    isolated_margin_verified: bool
    one_way_mode_verified: bool

    def __post_init__(self):
        if type(self.scope) is not Scope or self.scope.environment not in {'SPOT_LIVE', 'FUTURES_LIVE'}:
            raise LiveError('VENUE_SCOPE_REQUIRED')
        if type(self.evidence_digest) is not str or not _HEX.fullmatch(self.evidence_digest):
            raise LiveError('VENUE_EVIDENCE_SHA256_REQUIRED')
        if _time(self.observed_at) > _time(self.received_at):
            raise LiveError('VENUE_EVIDENCE_CAUSALITY_REQUIRED')
        for value in (self.reference_price, self.quantity_step, self.minimum_quantity, self.maximum_quantity, self.price_tick):
            _decimal(value)
        if _decimal(self.minimum_quantity) > _decimal(self.maximum_quantity):
            raise LiveError('VENUE_QUANTITY_RANGE_REQUIRED')
        for value in (self.minimum_notional_units, self.available_depth_units):
            if type(value) is not int or not 0 <= value <= 10**18:
                raise LiveError('VENUE_INTEGER_UNITS_REQUIRED')
        if self.maximum_notional_units is not None and (type(self.maximum_notional_units) is not int or self.maximum_notional_units < self.minimum_notional_units or self.maximum_notional_units > 10**18):
            raise LiveError('VENUE_INTEGER_UNITS_REQUIRED')
        for value in (self.fee_bps, self.slippage_bps, self.spread_bps):
            if type(value) is not int or not 0 <= value <= 10000:
                raise LiveError('VENUE_COST_EVIDENCE_REQUIRED')
        if type(self.configured_leverage_milli) is not int or not 1000 <= self.configured_leverage_milli <= 125000:
            raise LiveError('VENUE_LEVERAGE_EVIDENCE_REQUIRED')
        for value in (self.filters_complete, self.protection_filters_verified, self.isolated_margin_verified, self.one_way_mode_verified):
            if type(value) is not bool:
                raise LiveError('VENUE_EXPLICIT_FLAGS_REQUIRED')


def _native_plan(decision, venue, policy_fingerprint, quantity, now, ttl_ms):
    amount = _decimal(quantity)
    if not _on_grid(amount, _decimal(venue.quantity_step)) or amount < _decimal(venue.minimum_quantity) or amount > _decimal(venue.maximum_quantity):
        # A net base fill outside LOT_SIZE is UNKNOWN, never claimed protected.
        raise LiveError('CONFIRMED_PROTECTION_QUANTITY_OUTSIDE_VENUE_GRID')
    with localcontext() as context:
        context.prec = 80
        for price in (decision.stop_price, decision.take_profit, decision.stop_limit_price):
            if price is None:
                continue
            notional = amount * _decimal(price) * MICRO
            if (notional < venue.minimum_notional_units
                    or venue.maximum_notional_units is not None and notional > venue.maximum_notional_units):
                raise LiveError('NATIVE_PROTECTION_NOTIONAL_OUTSIDE_VENUE_FILTERS')
    def client(role):
        return 'CB-' + _hash([asdict(decision.scope), decision.engine_id, decision.decision_id, role])[:32]
    expiry = int(_time(now) * 1000) + ttl_ms
    side = 'SELL' if decision.direction == 'LONG' else 'BUY'
    if decision.engine_id == 'SPOT':
        fields = {'symbol':decision.symbol, 'side':side, 'quantity':quantity, 'listClientOrderId':client('OCO'),
                  'aboveClientOrderId':client('TAKE_PROFIT'), 'belowClientOrderId':client('STOP'),
                  'aboveType':'LIMIT_MAKER', 'abovePrice':decision.take_profit, 'belowType':'STOP_LOSS_LIMIT',
                  'belowStopPrice':decision.stop_price, 'belowPrice':decision.stop_limit_price, 'belowTimeInForce':'GTC'}
        return NativeProtectionPlan((LiveOrderIntent(decision.scope.environment, 'PROTECT', 'POST', '/api/v3/orderList/oco',
            tuple(fields.items()), client('OCO'), policy_fingerprint, expiry),))
    intents = []
    for role, kind, price in (('STOP','STOP_MARKET',decision.stop_price),('TAKE_PROFIT','TAKE_PROFIT_MARKET',decision.take_profit)):
        fields = {'symbol':decision.symbol, 'side':side, 'quantity':quantity, 'type':kind, 'clientAlgoId':client(role),
                  'algoType':'CONDITIONAL', 'triggerPrice':price, 'workingType':'MARK_PRICE', 'priceProtect':'TRUE',
                  'positionSide':'BOTH', 'reduceOnly':'true'}
        intents.append(LiveOrderIntent(decision.scope.environment, 'PROTECT', 'POST', '/fapi/v1/algoOrder',
            tuple(fields.items()), client(role), policy_fingerprint, expiry))
    return NativeProtectionPlan(tuple(intents))


@dataclass(frozen=True)
class PreparedStrategyEntry:
    decision: NativeStrategyDecision
    venue: VenueExecutionEvidence
    policy: AdmissionPolicy
    proposal: EntryProposal
    intent: LiveOrderIntent
    protection_ttl_ms: int

    def protection_factory(self, proposal, intent, position, now):
        if type(proposal) is not EntryProposal or proposal.fingerprint != self.proposal.fingerprint or intent.digest() != self.intent.digest():
            raise LiveError('EXACT_STORED_STRATEGY_PLAN_REQUIRED')
        if position is not None and (type(position) is not ConfirmedPosition or position.scope != self.decision.scope
                or position.ticket_id != self.proposal.proposal_id or position.symbol != self.decision.symbol
                or position.direction != self.decision.direction or _decimal(position.quantity) > _decimal(self.decision.quantity)):
            raise LiveError('CONFIRMED_OWNED_STRATEGY_POSITION_REQUIRED')
        return _native_plan(self.decision,self.venue,self.policy.fingerprint,
                            position.quantity if position is not None else self.decision.quantity,now,self.protection_ttl_ms)

    def _retained(self, store):
        if type(store) is not LiveStrategyPlanStore or store.load(self.proposal.proposal_id).payload() != self.payload():
            raise LiveError('EXACT_RETAINED_STRATEGY_PLAN_REQUIRED')

    def observe(self, admission, facts, *, plan_store, event_id):
        self._retained(plan_store)
        if type(admission) is not CentralAdmission or admission.scope != self.proposal.scope or admission.policy.fingerprint != self.policy.fingerprint:
            raise LiveError('EXACT_STRATEGY_ADMISSION_REQUIRED')
        self._facts(facts)
        return admission.observe(self.proposal, facts, event_id=event_id)

    def _facts(self, facts):
        if type(facts) is not AdmissionFacts or facts.scope != self.proposal.scope:
            raise LiveError('EXACT_SCOPED_STRATEGY_ACCOUNT_FACTS_REQUIRED')

    def _coordinator(self, coordinator):
        if type(coordinator) is not LiveExecutionCoordinator or coordinator.admission.scope != self.proposal.scope or coordinator.admission.policy.fingerprint != self.policy.fingerprint:
            raise LiveError('EXACT_STRATEGY_COORDINATOR_REQUIRED')
        factory = coordinator.protection_factory
        bound = getattr(factory, '__self__', None)
        if (type(bound) is not PreparedStrategyEntry or getattr(factory, '__func__', None) is not PreparedStrategyEntry.protection_factory
                or bound.payload() != self.payload()):
            raise LiveError('EXACT_STRATEGY_PROTECTION_FACTORY_REQUIRED')

    def execute(self, coordinator, facts, *, plan_store, event_id):
        self._retained(plan_store)
        self._coordinator(coordinator)
        self._facts(facts)
        # The coordinator still requires its own authenticated owner provider.
        # This method creates no approval, mode flag, marker or default transport.
        return coordinator.execute_entry(self.proposal,facts,self.intent,event_id=event_id)

    def recover(self, coordinator, *, plan_store, event_id):
        self._retained(plan_store)
        self._coordinator(coordinator)
        return coordinator.reconcile_by_client_id(self.proposal.proposal_id,self.intent,event_id=event_id)

    def payload(self):
        return {'schema':1,'decision':asdict(self.decision),'venue':asdict(self.venue),
                'policy':asdict(self.policy),'protection_ttl_ms':self.protection_ttl_ms,
                'proposal_fingerprint':self.proposal.fingerprint,'intent_digest':self.intent.digest()}


def prepare_strategy_entry(decision, venue, policy, *, now, protection_ttl_ms):
    if type(decision) is not NativeStrategyDecision or type(venue) is not VenueExecutionEvidence or type(policy) is not AdmissionPolicy:
        raise LiveError('TYPED_NATIVE_STRATEGY_INPUT_REQUIRED')
    stamp = _time(now)
    if type(protection_ttl_ms) is not int or not 1 <= protection_ttl_ms <= 30000:
        raise LiveError('EXPLICIT_PROTECTION_REQUEST_TTL_REQUIRED')
    if (decision.scope != venue.scope or not decision.quantitative_checks_passed or not venue.filters_complete
            or not venue.protection_filters_verified or decision.reference_price != venue.reference_price):
        raise LiveError('COMPLETE_MATCHING_NATIVE_VENUE_EVIDENCE_REQUIRED')
    if (not venue.observed_at <= venue.received_at <= decision.decision_at <= stamp < decision.expires_at
            or not decision.source_observed_at <= venue.received_at
            or stamp-decision.source_observed_at > policy.max_data_age_seconds
            or stamp-venue.observed_at > policy.max_data_age_seconds
            or decision.expires_at-stamp > 30):
        raise LiveError('FRESH_CAUSAL_STRATEGY_EVIDENCE_REQUIRED')
    review = decision.review
    if review.verdict == 'REJECT' or review.risk_multiplier <= 0 or decision.engine_id == 'FUTURES' and (review.verdict != 'ALLOW' or review.risk_multiplier != 1):
        raise LiveError('INDIVIDUAL_AI_REVIEW_REJECTS_ENTRY')
    if decision.leverage_milli != venue.configured_leverage_milli or decision.leverage_milli > policy.max_leverage_milli:
        raise LiveError('EXISTING_VENUE_LEVERAGE_MUST_MATCH_POLICY')
    if decision.engine_id == 'FUTURES' and (not venue.isolated_margin_verified or not venue.one_way_mode_verified):
        raise LiveError('EXISTING_ISOLATED_ONE_WAY_CONFIGURATION_REQUIRED')
    quantity, reference, stop = map(_decimal,(decision.quantity,decision.reference_price,decision.stop_price))
    if not _on_grid(quantity, _decimal(venue.quantity_step)) or not _decimal(venue.minimum_quantity) <= quantity <= _decimal(venue.maximum_quantity):
        raise LiveError('NATIVE_QUANTITY_OUTSIDE_VENUE_FILTERS')
    for price in (decision.reference_price,decision.stop_price,decision.take_profit,decision.stop_limit_price):
        if price is not None and not _on_grid(_decimal(price), _decimal(venue.price_tick)):
            raise LiveError('NATIVE_PRICE_OUTSIDE_VENUE_FILTERS')
    with localcontext() as context:
        context.prec=80
        gross=_ceil(quantity*reference*MICRO)
        costs=(gross*(2*venue.fee_bps+2*venue.slippage_bps+venue.spread_bps)+9999)//10000
        risk=_ceil(quantity*abs(reference-stop)*MICRO)+costs
        ai_risk_cap=int((Decimal(policy.per_trade_stop_risk_limit_units)*Decimal(str(review.risk_multiplier))).to_integral_value(rounding=ROUND_FLOOR))
    if gross < venue.minimum_notional_units or venue.maximum_notional_units is not None and gross > venue.maximum_notional_units:
        raise LiveError('NATIVE_NOTIONAL_OUTSIDE_VENUE_FILTERS')
    if risk > ai_risk_cap:
        raise LiveError('INDIVIDUAL_AI_REDUCED_RISK_CAP_EXCEEDED')
    plan_key=_hash([asdict(decision.scope),decision.engine_id,decision.decision_id])
    client='CB-'+_hash([plan_key,'ENTRY'])[:32]
    fields={'symbol':decision.symbol,'side':'BUY' if decision.direction=='LONG' else 'SELL','type':'MARKET',
            'quantity':decision.quantity,'newClientOrderId':client}
    if decision.engine_id=='FUTURES':fields.update(positionSide='BOTH',reduceOnly='false')
    preliminary=LiveOrderIntent(decision.scope.environment,'ENTRY','POST',
        '/api/v3/order' if decision.engine_id=='SPOT' else '/fapi/v1/order',tuple(fields.items()),client,
        policy.fingerprint,int(decision.expires_at*1000))
    native=_native_plan(decision,venue,policy.fingerprint,decision.quantity,stamp,protection_ttl_ms)
    terms={'quantity':decision.quantity,'reference_price':decision.reference_price,'stop_price':decision.stop_price,
           'reference_utc_ms':str(int(venue.observed_at*1000)),'protection_plan_fingerprint':native.terms_fingerprint}
    intent=replace(preliminary,risk_terms=tuple(terms.items()))
    proposal=EntryProposal('LIVEPLAN-'+plan_key,decision.scope,decision.engine_id,decision.symbol,decision.direction,
        gross,(gross*1000+decision.leverage_milli-1)//decision.leverage_milli,costs,risk,decision.leverage_milli,
        decision.correlation_group,decision.decision_at,decision.expires_at,venue.fee_bps,venue.slippage_bps,
        venue.spread_bps,venue.available_depth_units,True,True,True,decision.strategy_fingerprint,intent.digest())
    return PreparedStrategyEntry(decision,venue,policy,proposal,intent,protection_ttl_ms)


def _restore(payload):
    if type(payload) is not dict or set(payload)!={'schema','decision','venue','policy','protection_ttl_ms','proposal_fingerprint','intent_digest'} or type(payload['schema']) is not int or payload['schema']!=1:
        raise LiveError('STORED_STRATEGY_PLAN_SCHEMA_REQUIRED')
    decision=dict(payload['decision']);decision['scope']=Scope(**decision['scope']);decision['review']=AIReview(**decision['review'])
    venue=dict(payload['venue']);venue['scope']=Scope(**venue['scope'])
    policy=dict(payload['policy'])
    for key in ('engine_limits','asset_limits','correlation_limits'):policy[key]=tuple(tuple(row) for row in policy[key])
    d=NativeStrategyDecision(**decision)
    result=prepare_strategy_entry(d,VenueExecutionEvidence(**venue),AdmissionPolicy(**policy),now=d.decision_at,
                                  protection_ttl_ms=payload['protection_ttl_ms'])
    if result.proposal.fingerprint!=payload['proposal_fingerprint'] or result.intent.digest()!=payload['intent_digest']:
        raise LiveError('STORED_STRATEGY_PLAN_CHANGED')
    return result


class LiveStrategyPlanStore:
    """Explicitly initialized immutable plan receipts; never a wallet or authority."""
    def __init__(self,path):
        self.path=Path(path)
        if self.path.suffix!='.sqlite3' or not self.path.name.startswith('live-strategy-plans-'):
            raise LiveError('SEPARATE_STRATEGY_PLAN_STORE_REQUIRED')

    def _safe(self):
        if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in (self.path,*self.path.parents)):
            raise LiveError('LINKED_STRATEGY_PLAN_STORE_BLOCKED')
        return _single_file_identity(self.path,'NONPRIVATE_STRATEGY_PLAN_STORE_BLOCKED')

    def _same_file(self,identity):
        if identity is None or self._safe()!=identity:
            raise LiveError('STRATEGY_PLAN_STORE_IDENTITY_CHANGED')

    @staticmethod
    def _identity(db):
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if (tables!={'strategy_plan_meta','strategy_plans'}
                or db.execute('SELECT schema FROM strategy_plan_meta').fetchall()!=[(1,)]):
            raise LiveError('FOREIGN_STRATEGY_PLAN_STORE')

    def initialize(self):
        identity=self._safe();self.path.parent.mkdir(parents=True,exist_ok=True)
        if identity is None:
            descriptor=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_BINARY',0),0o600)
            os.close(descriptor);identity=self._safe()
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw',uri=True,timeout=5)) as db,db:
            self._same_file(identity)
            db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA synchronous=FULL')
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and tables!={'strategy_plan_meta','strategy_plans'}:raise LiveError('FOREIGN_STRATEGY_PLAN_STORE')
            db.execute('CREATE TABLE IF NOT EXISTS strategy_plan_meta(schema INTEGER NOT NULL)')
            if not tables:db.execute('INSERT INTO strategy_plan_meta VALUES(1)')
            if db.execute('SELECT schema FROM strategy_plan_meta').fetchall()!=[(1,)]:raise LiveError('FOREIGN_STRATEGY_PLAN_STORE')
            db.execute('CREATE TABLE IF NOT EXISTS strategy_plans(id TEXT PRIMARY KEY,digest TEXT NOT NULL,payload BLOB NOT NULL)')
            db.executescript("CREATE TRIGGER IF NOT EXISTS strategy_plans_no_update BEFORE UPDATE ON strategy_plans BEGIN SELECT RAISE(ABORT,'immutable plan'); END; CREATE TRIGGER IF NOT EXISTS strategy_plans_no_delete BEFORE DELETE ON strategy_plans BEGIN SELECT RAISE(ABORT,'immutable plan'); END;")

    def save(self,plan):
        if type(plan) is not PreparedStrategyEntry:raise LiveError('TYPED_PREPARED_STRATEGY_PLAN_REQUIRED')
        identity=self._safe();raw=_canonical(plan.payload());digest=hashlib.sha256(raw).hexdigest()
        if _canonical(_restore(json.loads(raw)).payload()) != raw:
            raise LiveError('EXACT_PREPARED_STRATEGY_PLAN_REQUIRED')
        if not self.path.is_file():raise LiveError('STRATEGY_PLAN_STORE_NOT_INITIALIZED')
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw',uri=True,timeout=5)) as db,db:
            self._same_file(identity)
            db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            self._identity(db)
            old=db.execute('SELECT digest,payload FROM strategy_plans WHERE id=?',(plan.proposal.proposal_id,)).fetchone()
            if old is not None:
                if old!=(digest,raw):raise LiveError('STRATEGY_DECISION_ID_CONFLICT')
                return False
            db.execute('INSERT INTO strategy_plans VALUES(?,?,?)',(plan.proposal.proposal_id,digest,raw));return True

    def load(self,proposal_id):
        _identifier(proposal_id);identity=self._safe()
        if not self.path.is_file():raise LiveError('STRATEGY_PLAN_STORE_NOT_INITIALIZED')
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            self._same_file(identity)
            db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
            self._identity(db)
            row=db.execute('SELECT digest,payload FROM strategy_plans WHERE id=?',(proposal_id,)).fetchone()
        if row is None:raise LiveError('STORED_STRATEGY_PLAN_UNKNOWN')
        digest,raw=row
        if type(raw) is not bytes or len(raw)>MAX_PLAN_BYTES or hashlib.sha256(raw).hexdigest()!=digest:
            raise LiveError('STORED_STRATEGY_PLAN_CHANGED')
        try:
            result = _restore(json.loads(raw))
            if result.proposal.proposal_id != proposal_id or _canonical(result.payload()) != raw:
                raise LiveError('STORED_STRATEGY_PLAN_CHANGED')
            return result
        except (ValueError,TypeError,KeyError,RecursionError):raise LiveError('STORED_STRATEGY_PLAN_INVALID') from None
