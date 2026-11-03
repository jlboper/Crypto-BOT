"""Owned-process LIVE supervision; financial approval remains separate.

This explicit synchronous component is exercised through synthetic transports.
It does not commission the default engine, discover authority, start a daemon,
provision financial facts or create an activation record.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import threading
import time

from .central_admission import AdmissionError, AdmissionFacts, CentralAdmission
from .live_execution_runtime import LiveExecutionCoordinator
from .live_strategy_adapter import LiveStrategyPlanStore, PreparedStrategyEntry
from .live_transport import LiveError, LiveOrderTransport, LiveReadOnlyTransport

LIVE_SUPERVISOR_PROTOCOL = 1


def _event(ticket, action):
    return 'SUP-' + hashlib.sha256((ticket + ':' + action).encode('ascii')).hexdigest()


@dataclass(frozen=True)
class LiveWalletRuntime:
    admission: CentralAdmission
    transport: LiveOrderTransport
    plans: LiveStrategyPlanStore
    provider: object

    def __post_init__(self):
        if (type(self.admission) is not CentralAdmission or type(self.transport) is not LiveOrderTransport
                or type(self.plans) is not LiveStrategyPlanStore or self.provider is None
                or set(self.transport._credentials) != {self.admission.scope.environment}
                or self.transport.authority is not None):
            raise LiveError('EXACT_DEDICATED_SUPERVISED_WALLET_REQUIRED')


class LiveSupervisedExecutor:
    """Recover all wallets before consulting entry facts or any proposal/AI.

    The existing installation-wide process lock must own calls. This local lock
    additionally rejects overlapping callbacks. Transport budgets remain bounded;
    exhaustion never resets counters or renews a submission permission.
    """
    def __init__(self, wallets, *, facts_source, proposal_source, venue_validator,
                 entry_halted, reduction_validator=None, clock=time.time):
        if (type(wallets) is not tuple or not 1 <= len(wallets) <= 2
                or any(type(wallet) is not LiveWalletRuntime for wallet in wallets)
                or len({w.admission.scope.environment for w in wallets}) != len(wallets)
                or any(not callable(value) for value in (facts_source, proposal_source, venue_validator, entry_halted))):
            raise LiveError('EXPLICIT_SUPERVISOR_DEPENDENCIES_REQUIRED')
        self.wallets = wallets
        self.facts_source, self.proposal_source = facts_source, proposal_source
        self.venue_validator, self.entry_halted, self.clock = venue_validator, entry_halted, clock
        if reduction_validator is not None and not callable(reduction_validator):
            raise LiveError('EXPLICIT_REDUCTION_VALIDATOR_REQUIRED')
        self.reduction_validator = reduction_validator
        self._lock = threading.Lock()

    def _coordinator(self, wallet, plan):
        # Synchronous ownership prevents pending callbacks during rebinding.
        # The new Python object has no old grant nonce after a restart.
        wallet.transport.authority = None
        return LiveExecutionCoordinator(wallet.admission, wallet.transport,
            provider=wallet.provider, protection_factory=plan.protection_factory,
            reduction_validator=self.reduction_validator, clock=wallet.admission.clock)

    def _recover(self, wallet):
        results, blocked = [], False
        for row in wallet.admission.snapshot()['active_tickets']:
            ticket = row['ticket_id']
            try:
                plan = wallet.plans.load(ticket)
                terms = wallet.admission.ticket_terms(ticket)
                if plan.proposal.scope != wallet.admission.scope or plan.policy.fingerprint != wallet.admission.policy.fingerprint:
                    raise LiveError('RECOVERY_PLAN_WALLET_MISMATCH')
                if terms['claim_id'] is None:
                    result = {'state':'RECOVERY_REQUIRED', 'reasons':['UNSENT_RESERVATION_REQUIRES_REVIEW']}
                else:
                    coordinator = self._coordinator(wallet, plan)
                    cut = str(int(wallet.admission.clock() * 1_000_000))
                    result = plan.recover(coordinator, plan_store=wallet.plans, event_id=_event(ticket, 'recover:' + cut))
                    if result['state'] == 'RECOVERY_REQUIRED':
                        closed = coordinator.reconcile_native_exit_by_client_id(ticket, plan.intent,
                            event_id=_event(ticket, 'native-exit:' + cut))
                        if closed['state'] == 'CLOSED':
                            result = closed
                        elif self.reduction_validator is not None:
                            result = coordinator.mitigate_residual_by_client_id(ticket, plan.intent,
                                event_id=_event(ticket, 'residual:' + cut))
                results.append({'ticket_id':ticket, 'state':result['state'], 'reasons':result.get('reasons', [])})
                if result['state'] not in {'OPEN', 'CLOSED', 'CANCELLED'}:
                    blocked = True
            except Exception:
                # One corrupt wallet/adapter must not starve another wallet's
                # recovery. Closed diagnostics reveal no provider text or data.
                blocked = True
                results.append({'ticket_id':ticket, 'state':'RECOVERY_REQUIRED',
                    'reasons':['RETAINED_PLAN_OR_RECONCILIATION_UNAVAILABLE']})
        return results, blocked

    @staticmethod
    def _fresh(facts, scope, policy, now):
        if (type(facts) is not AdmissionFacts or facts.scope != scope
                or not all((facts.identity_verified, facts.inventory_complete, facts.orders_reconciled,
                    facts.cashflows_complete, facts.free_is_net_of_exchange_commitments,
                    facts.exchange_ready, facts.correlation_verified))
                or not facts.observed_at <= facts.received_at <= now
                or now - facts.observed_at > policy.max_data_age_seconds
                or {b.period for b in facts.baselines} != {'DAY', 'WEEK'}
                or any(not p.protection_verified or not 0 <= now - p.observed_at <= policy.max_data_age_seconds
                       for p in facts.positions)):
            raise LiveError('LIVE_FINANCIAL_FACTS_NOT_CERTIFIED')

    def cycle(self, *, recover_only=False):
        if type(recover_only) is not bool:
            raise LiveError('EXPLICIT_SUPERVISOR_PHASE_REQUIRED')
        if not self._lock.acquire(blocking=False):
            raise LiveError('SINGLE_SUPERVISOR_CYCLE_REQUIRED')
        out = {'state':'OBSERVING', 'automatic_activation':False, 'wallets':[]}
        try:
            recovered = []
            for wallet in self.wallets:
                try:
                    rows, blocked = self._recover(wallet)
                except Exception:
                    rows, blocked = [], True
                recovered.append((wallet, rows, blocked))
            for wallet, rows, blocked in recovered:
                scope, policy = wallet.admission.scope, wallet.admission.policy
                item = {'environment':scope.environment, 'recoveries':rows, 'entries':[], 'reasons':[]}
                out['wallets'].append(item)
                if blocked:
                    item['reasons'].append('PENDING_RECOVERY_BLOCKS_ENTRIES')
                    continue
                if recover_only:
                    continue
                try:
                    if self.entry_halted(scope):
                        item['reasons'].append('ENTRY_HALT_ACTIVE')
                        continue
                    facts = self.facts_source(scope, policy, self.clock())
                    self._fresh(facts, scope, policy, self.clock())
                    plans = self.proposal_source(scope, policy, facts)
                    if type(plans) is not tuple or len(plans) > 64 or any(type(p) is not PreparedStrategyEntry for p in plans):
                        raise LiveError('BOUNDED_TYPED_SUPERVISED_PLANS_REQUIRED')
                    for plan in plans:
                        if plan.proposal.scope != scope or plan.policy.fingerprint != policy.fingerprint:
                            raise LiveError('EXACT_SUPERVISED_PLAN_SCOPE_POLICY_REQUIRED')
                        if self.entry_halted(scope):
                            break
                        current = self.facts_source(scope, policy, self.clock())
                        self._fresh(current, scope, policy, self.clock())
                        if self.venue_validator(plan, self.clock()) is not True:
                            raise LiveError('LIVE_VENUE_FILTERS_NOT_VERIFIED')
                        wallet.plans.save(plan)
                        result = plan.execute(self._coordinator(wallet, plan), current,
                            plan_store=wallet.plans, event_id=_event(plan.proposal.proposal_id, 'entry'))
                        item['entries'].append({'ticket_id':plan.proposal.proposal_id,
                            'state':result['state'], 'reasons':result.get('reasons', [])})
                        if result['state'] not in {'OPEN', 'CANCELLED', 'BLOCKED'}:
                            break
                except Exception:
                    item['reasons'].append('LIVE_ENTRY_DEPENDENCY_UNAVAILABLE')
            if any(w['reasons'] or any(e['state'] not in {'OPEN','CANCELLED'} for e in w['entries']) for w in out['wallets']):
                out['state'] = 'BLOCKED'
            return out
        finally:
            self._lock.release()


class ReadOnlyAdmissionFactsSource:
    """Retain actual GET cuts; incomplete history never becomes complete facts."""
    def __init__(self, transport, *, retain, clock=time.time):
        if type(transport) is not LiveReadOnlyTransport or not callable(retain):
            raise LiveError('READ_ONLY_RETAINED_ACCOUNT_SOURCE_REQUIRED')
        self.transport, self.retain, self.clock = transport, retain, clock

    def observe(self, environment):
        if environment not in {'SPOT_LIVE', 'FUTURES_LIVE'}:
            raise LiveError('EXPLICIT_SUPERVISOR_ACCOUNT_SCOPE_REQUIRED')
        endpoints = ('/api/v3/account', '/api/v3/openOrders', '/api/v3/openOrderList') if environment == 'SPOT_LIVE' else (
            '/fapi/v3/account', '/fapi/v3/positionRisk', '/fapi/v1/openOrders', '/fapi/v1/openAlgoOrders')
        digests = []
        for endpoint in endpoints:
            began = self.clock()
            raw = self.transport.get(environment, endpoint)
            receipt = self.retain({'environment':environment, 'endpoint':endpoint, 'params':{},
                'request_started_at':began, 'received_at':self.clock(), 'response':raw})
            if (type(receipt) is not dict or type(receipt.get('sha256')) is not str
                    or not re.fullmatch('[0-9a-f]{64}', receipt['sha256'])):
                raise LiveError('RETAINED_SUPERVISOR_ACCOUNT_CUT_REQUIRED')
            digests.append(receipt['sha256'])
        return {'environment':environment, 'state':'BLOCKED', 'execution_enabled':False,
            'account_get_responses_retained':True, 'response_count':len(digests),
            'evidence_digest':hashlib.sha256(repr(digests).encode('ascii')).hexdigest(),
            'reasons':['LIVE_FINANCIAL_FACTS_NOT_CERTIFIED', 'CASHFLOW_BASELINES_NOT_CERTIFIED',
                'HISTORICAL_PROTECTION_COVERAGE_NOT_CERTIFIED']}

    def __call__(self, scope, policy, now):
        self.observe(scope.environment)
        raise LiveError('LIVE_FINANCIAL_FACTS_NOT_CERTIFIED')


class LiveSupervisionService:
    """Owned-process lifecycle hook, inactive by default and without a worker."""
    def __init__(self, config, *, runtime=None):
        self.config, self.runtime = config, runtime
        if runtime is not None and (config.bot.mode != 'live' or type(runtime) is not LiveSupervisedExecutor):
            raise LiveError('EXPLICIT_LIVE_MODE_FOR_SUPERVISED_EXECUTION_REQUIRED')

    def cycle(self):
        if self.config.bot.mode != 'live' or self.runtime is None:
            return {'state':'BLOCKED', 'reasons':['LIVE_OWNER_ACTIVATION_AND_CERTIFIED_FACTS_REQUIRED'],
                'execution_enabled':False, 'automatic_activation':False, 'supervisor_protocol':LIVE_SUPERVISOR_PROTOCOL}
        return self.runtime.cycle()
