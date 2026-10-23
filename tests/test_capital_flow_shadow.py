"""Synthetic SHADOW lifecycle; no engine, account, broker or network calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from trader.capital_manager_shadow import (
    AccountScope, CapitalManagerShadow, LegRequest, ReconciliationEvent,
    ReservationRequest, SimulationError, SimulationLimits,
)
from trader.capital_flow_shadow import Admission, CapitalFlowShadow
from trader.global_risk_shadow import Candidate, Exposure, Inventory, RiskPolicy


U = 1_000_000
NOW = 1_800_000_000.


def policies(scope):
    limits = SimulationLimits('SIM_CAPITAL_POLICY', 'SIM_RECIPE_AUTHOR', NOW,
        'EXPLICIT_NEW_SIMULATION_COHORT', 1000*U, 900*U, 900*U, 900*U, 30*U,
        (('SIM_SPOT', 900*U, 30*U), ('SIM_FUTURES', 900*U, 30*U)), 120, 10)
    risk = RiskPolicy('SIM_RISK_POLICY', scope, NOW, 900*U, 30*U, 10, 2000,
        (('SIM_SPOT', 900*U, 30*U), ('SIM_FUTURES', 900*U, 30*U)),
        (('BTCUSDT', 900*U, 30*U), ('ETHUSDT', 900*U, 30*U)),
        (('SIM_CRYPTO_FACTOR', 900*U, 30*U),), 100*U, 200*U, 150*U,
        500000, 750000, 2*U, 30, 20, 15)
    return limits, risk


def admission(scope, *, identifier='SIM_REQ_A', strategy='SIM_SPOT',
              symbol='BTCUSDT', direction='LONG', principal=100*U, risk=5*U,
              now=NOW, available=1000*U):
    leg_id = 'SIM_LEG_'+identifier[4:]
    leg = LegRequest(leg_id, symbol, direction,
        'SPOT_REFERENCE' if strategy == 'SIM_SPOT' else 'FUTURES_REFERENCE', principal, 2*U, risk)
    request = ReservationRequest(identifier, scope, strategy, 'SIM_CAPITAL_POLICY', (leg,), now+60)
    exposure = Exposure(leg_id, strategy, symbol, direction, principal, risk,
                        1000, 'SIM_CRYPTO_FACTOR', now, True)
    candidate = Candidate(identifier, scope, now, (exposure,), principal+2*U, 10, 10, 5, True)
    inventory = Inventory(scope, now, True, True, True, available, True,
        0, 0, 0, True, True, 'READY', False, (), ())
    return Admission(request, candidate, inventory)


class Clock:
    def __init__(self): self.value = NOW
    def __call__(self): return self.value


class CapitalFlowShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scope = AccountScope('SHADOW', 'SIM_ACCOUNT', 'USDT')
        self.limits, self.risk = policies(self.scope)
        self.clock = Clock()
        self.path = Path(self.temp.name)/'SIM_FLOW_CASE.simulation.sqlite3'
        self.flow = self.manager()
        self.flow.initialize()

    def manager(self, *, limits=None, risk=None, scope=None):
        return CapitalFlowShadow(self.path, wallet_name='SIM_FLOW_CASE',
            scope=scope or self.scope, limits=limits or self.limits,
            risk_policy=risk or self.risk, clock=self.clock)

    def event(self, identifier, *, state='FILLED', filled=100*U, entry=U,
              exit_fee=0, pnl=0, closed=False, complete=True):
        return ReconciliationEvent(identifier, self.scope, 'SIM_REQ_A', 'SIM_LEG_REQ_A',
            'SIM_RECONCILER', state, filled, entry, exit_fee, pnl, closed, self.clock(), complete)

    def start(self):
        self.assertTrue(self.flow.admit(admission(self.scope))['accepted'])
        return self.flow.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')

    def assert_conserved(self):
        result = self.flow.snapshot()
        self.assertEqual(result['book_equity_units'], 1000*U+result['realized_pnl_units']-result['fees_paid_units'])
        self.assertEqual(result['book_equity_units'], result['free_units_signed']+result['reserved_units']+result['committed_units'])
        return result

    def test_admission_claim_and_confirmed_close_are_auditable_without_authority(self):
        result = self.flow.admit(admission(self.scope))
        self.assertEqual(result['risk']['before']['gross_units'], 0)
        self.assertEqual(result['risk']['after']['gross_units'], 100*U)
        receipt = self.flow.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')
        self.assertEqual(receipt['claim_kind'], 'ONE_DURABLE_SYNTHETIC_INTENTION')
        self.assertFalse(receipt['submission_permitted'])
        self.flow.reconcile(self.event('SIM_FILL'))
        self.flow.reconcile(self.event('SIM_CLOSE', state='CLOSED', exit_fee=U, pnl=10*U, closed=True))
        value = self.assert_conserved()
        self.assertEqual(value['available_units'], 1008*U)
        self.assertEqual(value['admitted_request_count'], 1)
        self.assertEqual(value['synthetic_submission_claim_count'], 1)
        for record in (result, receipt, value):
            for flag in ('execution_enabled', 'controls_enabled', 'can_veto', 'reservations_enabled',
                         'promotion_allowed', 'live_implemented', 'real_account_adapter', 'atomic_hedge_claimed'):
                self.assertIs(record[flag], False)

    def test_repeated_proposals_and_claims_survive_restart_without_second_claim(self):
        proposal = admission(self.scope)
        first = self.flow.admit(proposal)
        self.assertEqual(self.flow.admit(proposal), first)
        receipt = self.flow.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')
        count = self.flow.snapshot()['event_count']
        restarted = self.manager(); restarted.initialize()
        self.assertEqual(restarted.admit(proposal), first)
        self.assertEqual(restarted.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT'), receipt)
        self.assertEqual(restarted.snapshot()['event_count'], count)
        self.assertEqual(restarted.snapshot()['synthetic_submission_claim_count'], 1)
        changed = replace(proposal, inventory=replace(proposal.inventory, available_margin_units=999*U))
        with self.assertRaises(SimulationError): restarted.admit(changed)
        with self.assertRaises(SimulationError): restarted.claim_submission('SIM_REQ_A', actor='SIM_DIFFERENT')

    def compete(self):
        gate = threading.Barrier(2)
        proposals = (admission(self.scope, principal=400*U),
                     admission(self.scope, identifier='SIM_REQ_B', strategy='SIM_FUTURES', symbol='ETHUSDT', principal=400*U))
        def race(proposal):
            peer = self.manager(); peer.initialize(); gate.wait(timeout=5)
            return peer.admit(proposal)
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(race, proposals))

    def test_concurrent_strategies_cannot_spend_same_account_money(self):
        self.limits = replace(self.limits, total_allocated_limit_units=600*U,
            reserved_limit_units=600*U, committed_limit_units=600*U,
            strategy_limits=(('SIM_SPOT', 600*U, 30*U), ('SIM_FUTURES', 600*U, 30*U)))
        # Identity path/name remain explicit and isolated for this separate recipe.
        self.path = Path(self.temp.name)/'new'/'SIM_FLOW_CASE.simulation.sqlite3'
        self.path.parent.mkdir()
        self.flow = self.manager(); self.flow.initialize()
        results = self.compete()
        self.assertEqual(sum(x['accepted'] for x in results), 1)
        self.assertIn('EXPLICIT_SIMULATION_BUDGET_EXCEEDED', [x.get('reason') for x in results])
        self.assertEqual(self.assert_conserved()['reserved_units'], 402*U)

    def test_global_gross_risk_and_reserve_share_transaction_not_racing_snapshots(self):
        self.risk = replace(self.risk, gross_limit_units=600*U,
            engine_limits=(('SIM_SPOT', 600*U, 30*U), ('SIM_FUTURES', 600*U, 30*U)),
            asset_limits=(('BTCUSDT', 600*U, 30*U), ('ETHUSDT', 600*U, 30*U)),
            correlation_limits=(('SIM_CRYPTO_FACTOR', 600*U, 30*U),))
        self.path = Path(self.temp.name)/'new'/'SIM_FLOW_CASE.simulation.sqlite3'; self.path.parent.mkdir()
        self.flow = self.manager(); self.flow.initialize()
        results = self.compete()
        self.assertEqual(sum(x['accepted'] for x in results), 1)
        rejected = next(x for x in results if not x['accepted'])
        self.assertEqual(rejected['reason'], 'SIMULATED_RISK_REJECTED')
        self.assertIn('GLOBAL_GROSS_LIMIT_EXCEEDED', rejected['risk']['reasons'])
        self.assertEqual(rejected['risk']['before']['gross_units'], 400*U)

    def test_opposite_directions_have_no_automatic_hedge_credit(self):
        first = admission(self.scope)
        self.flow.admit(first)
        opposite = admission(self.scope, identifier='SIM_REQ_B', strategy='SIM_FUTURES', direction='SHORT')
        result = self.flow.admit(opposite)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'ACCOUNT_ASSET_ALREADY_RESERVED')
        self.assertEqual(result['risk']['after']['gross_units'], 200*U)
        self.assertEqual(result['risk']['after']['inclusive_stop_risk_units'], 10*U)

    def test_crash_before_claim_commit_rolls_back_claim_and_state(self):
        self.flow.admit(admission(self.scope))
        def crash(stage):
            if stage == 'BEFORE_COMMIT': raise RuntimeError('SYNTHETIC_CRASH')
        self.flow._test_fault_hook = crash
        with self.assertRaisesRegex(RuntimeError, 'SYNTHETIC_CRASH'):
            self.flow.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')
        restart = self.manager(); restart.initialize()
        self.assertEqual(restart.snapshot()['requests'][0]['state'], 'RESERVED')
        self.assertEqual(restart.snapshot()['synthetic_submission_claim_count'], 0)
        restart.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')
        self.assertEqual(restart.snapshot()['synthetic_submission_claim_count'], 1)

    def test_crash_after_claim_commit_recovers_unknown_without_reclaim_or_ttl_release(self):
        self.flow.admit(admission(self.scope))
        def crash(stage):
            if stage == 'AFTER_COMMIT': raise RuntimeError('SYNTHETIC_CRASH')
        self.flow._test_fault_hook = crash
        with self.assertRaisesRegex(RuntimeError, 'SYNTHETIC_CRASH'):
            self.flow.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')
        restart = self.manager(); restart.initialize()
        self.clock.value += 3600
        restart.recover('SIM_RESTART', actor='SIM_RECOVERY')
        receipt = restart.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')
        self.assertFalse(receipt['submission_permitted'])
        value = restart.snapshot()
        self.assertEqual(value['requests'][0]['state'], 'UNKNOWN')
        self.assertEqual(value['reserved_units'], 102*U)
        self.assertEqual(value['synthetic_submission_claim_count'], 1)

    def test_cancel_failure_and_late_terminal_reconciliation_keep_funds_until_fact(self):
        self.start()
        self.flow.request_cancel('SIM_CANCEL', 'SIM_REQ_A', actor='SIM_CANCEL_ACTOR')
        self.flow.reconcile(self.event('SIM_CANCEL_UNKNOWN', state='UNKNOWN', filled=0, entry=0, complete=False))
        self.clock.value += 4000
        value = self.assert_conserved()
        self.assertEqual(value['reserved_units'], 102*U)
        self.assertEqual(value['requests'][0]['state'], 'UNKNOWN')
        result = self.flow.reconcile(self.event('SIM_CANCEL_CONFIRMED', state='CANCELLED', filled=0, entry=0))
        self.assertEqual(result['state'], 'CANCELLED')
        self.assertEqual(self.assert_conserved()['reserved_units'], 0)
        receipt = self.flow.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')
        self.assertFalse(receipt['submission_permitted'])
        self.assertEqual(self.flow.snapshot()['synthetic_submission_claim_count'], 1)

    def test_partial_fill_cancel_close_and_duplicate_terminal_are_conservative(self):
        self.start()
        self.flow.reconcile(self.event('SIM_PART', state='PARTIAL', filled=40*U, entry=400000))
        result = self.flow.reconcile(self.event('SIM_CANCEL_CONFIRMED', state='CANCELLED', filled=40*U, entry=400000))
        self.assertEqual(result['state'], 'RECOVERY_REQUIRED')
        value = self.assert_conserved()
        self.assertEqual(value['committed_units'], 40*U)
        self.assertEqual(value['reserved_units'], 1600000)
        close = self.event('SIM_CLOSE', state='CLOSED', filled=40*U, entry=400000,
                           exit_fee=400000, pnl=-2*U, closed=True)
        self.flow.reconcile(close)
        before = self.assert_conserved()
        self.flow.reconcile(close)
        self.flow.reconcile(replace(close, event_id='SIM_CLOSE_DUPLICATE_FACT'))
        after = self.assert_conserved()
        for key in ('book_equity_units', 'available_units', 'fees_paid_units', 'realized_pnl_units'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(after['available_units'], 997200000)

    def test_stale_data_unknown_identity_manual_halt_and_ai_absence_fail_closed(self):
        proposal = admission(self.scope)
        for field, value, reason in (
                ('observed_at', NOW-31, 'STALE_OR_FUTURE_DATA'),
                ('account_identity_verified', None, 'ACCOUNT_IDENTITY_UNVERIFIED'),
                ('inventory_complete', False, 'INVENTORY_INCOMPLETE_OR_UNKNOWN'),
                ('manual_entry_halt', True, 'MANUAL_ENTRY_HALT')):
            with self.subTest(field=field):
                request = replace(proposal.request, request_id='SIM_REQ_'+field)
                candidate = replace(proposal.candidate, candidate_id=request.request_id)
                result = self.flow.admit(Admission(request, candidate, replace(proposal.inventory, **{field: value})))
                self.assertFalse(result['accepted']); self.assertIn(reason, result['risk']['reasons'])
        self.assertEqual(self.assert_conserved()['reserved_units'], 0)

    def test_binding_and_fee_floor_cannot_swap_direction_risk_or_money(self):
        proposal = admission(self.scope)
        for candidate in (
                replace(proposal.candidate, candidate_id='SIM_OTHER'),
                replace(proposal.candidate, required_margin_units=U),
                replace(proposal.candidate, legs=(replace(proposal.candidate.legs[0], direction='SHORT'),)),
                replace(proposal.candidate, legs=(replace(proposal.candidate.legs[0], inclusive_stop_risk_units=U),)),
                replace(proposal.candidate, estimated_fee_bps=1000)):
            with self.subTest(candidate=candidate), self.assertRaises(SimulationError):
                Admission(proposal.request, candidate, proposal.inventory)
        future = admission(self.scope, strategy='SIM_FUTURES')
        fractional = replace(future.candidate, legs=(replace(future.candidate.legs[0], leverage_milli=1500),))
        with self.assertRaisesRegex(SimulationError, 'INTEGRAL_SIMULATED_FUTURES_LEVERAGE_REQUIRED'):
            Admission(future.request, fractional, future.inventory)

    def test_environments_policies_and_wallet_names_are_explicit(self):
        with self.assertRaises(SimulationError):
            self.manager(scope=AccountScope('FUTURES_DEMO', 'SIM_ACCOUNT', 'USDT'))
        with self.assertRaises(SimulationError):
            self.manager(risk=replace(self.risk, daily_loss_limit_units=99*U)).initialize()
        self.flow.risk_policy = replace(self.risk, daily_loss_limit_units=99*U)
        with self.assertRaises(SimulationError): self.flow.admit(admission(self.scope))

    def test_allocated_principal_cannot_understate_durable_authorized_gross(self):
        spot = admission(self.scope)
        understated = replace(spot.candidate, legs=(replace(spot.candidate.legs[0], gross_units=U),))
        with self.assertRaisesRegex(SimulationError, 'LEG_CAPITAL_NOT_BOUND_TO_AUTHORIZED_GROSS'):
            Admission(spot.request, understated, spot.inventory)
        future = admission(self.scope, strategy='SIM_FUTURES')
        for gross in (U, 199*U, 300*U):
            candidate = replace(future.candidate, legs=(replace(future.candidate.legs[0],
                gross_units=gross, leverage_milli=2000),))
            with self.subTest(gross=gross), self.assertRaisesRegex(SimulationError, 'LEG_CAPITAL_NOT_BOUND_TO_AUTHORIZED_GROSS'):
                Admission(future.request, candidate, future.inventory)
        candidate = replace(future.candidate, legs=(replace(future.candidate.legs[0],
            gross_units=200*U, leverage_milli=2000),))
        valid = Admission(future.request, candidate, future.inventory)
        result = self.flow.admit(valid)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['risk']['after']['gross_units'], 200*U)

    def test_parent_manager_bypass_is_detected_as_untracked_and_never_ignored(self):
        parent = CapitalManagerShadow(self.path, wallet_name='SIM_FLOW_CASE', scope=self.scope,
            limits=self.limits, clock=self.clock)
        parent.initialize()
        parent.reserve(admission(self.scope).request)
        result = self.flow.admit(admission(self.scope, identifier='SIM_REQ_B', symbol='ETHUSDT'))
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'UNTRACKED_SIMULATED_REQUEST')

    def test_duplicate_inventory_exposure_does_not_bypass_or_double_count(self):
        proposal = admission(self.scope); self.flow.admit(proposal)
        next_proposal = admission(self.scope, identifier='SIM_REQ_B', symbol='ETHUSDT')
        inventory = replace(next_proposal.inventory, positions=proposal.candidate.legs)
        result = self.flow.admit(replace(next_proposal, inventory=inventory))
        self.assertEqual(result['reason'], 'DUPLICATE_MANAGED_EXPOSURE')
        self.assertEqual(self.flow.snapshot()['admitted_request_count'], 1)

    def test_admission_crash_before_commit_rolls_back_risk_metadata_and_money(self):
        def crash(stage):
            if stage == 'BEFORE_COMMIT': raise RuntimeError('SYNTHETIC_CRASH')
        self.flow._test_fault_hook = crash
        with self.assertRaises(RuntimeError): self.flow.admit(admission(self.scope))
        restart = self.manager(); restart.initialize()
        self.assertEqual(restart.snapshot()['admitted_request_count'], 0)
        self.assertEqual(restart.snapshot()['reserved_units'], 0)
        self.assertTrue(restart.admit(admission(self.scope))['accepted'])

    def test_freshness_is_checked_again_before_first_synthetic_claim(self):
        self.flow.admit(admission(self.scope))
        self.clock.value += 31  # Capital observation and request remain within their own TTLs.
        result = self.flow.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'SIMULATED_RISK_REJECTED_AT_CLAIM')
        self.assertIn('STALE_OR_FUTURE_DATA', result['risk']['reasons'])
        self.assertEqual(self.flow.snapshot()['synthetic_submission_claim_count'], 0)
        self.assertEqual(self.flow.snapshot()['reserved_units'], 102*U)

    def test_simultaneous_repeated_claims_are_one_durable_intention(self):
        self.flow.admit(admission(self.scope))
        gate = threading.Barrier(2)
        def claim(_):
            peer = self.manager(); peer.initialize(); gate.wait(timeout=5)
            return peer.claim_submission('SIM_REQ_A', actor='SIM_CLAIMANT')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.flow.snapshot()['synthetic_submission_claim_count'], 1)
        self.assertTrue(all(x['submission_permitted'] is False for x in results))

    def test_terminal_contradiction_does_not_revive_spendable_capital(self):
        self.start()
        self.flow.reconcile(self.event('SIM_CANCELLED', state='CANCELLED', filled=0, entry=0))
        before = self.assert_conserved()
        result = self.flow.reconcile(self.event('SIM_IMPOSSIBLE_LATE_FILL'))
        self.assertEqual(result['reason'], 'TERMINAL_SIMULATION_FACT_DIVERGENCE')
        self.assertEqual(result['state'], 'RECOVERY_REQUIRED')
        self.assertEqual(self.assert_conserved()['book_equity_units'], before['book_equity_units'])
        proposal = admission(self.scope, identifier='SIM_REQ_B', symbol='ETHUSDT')
        self.assertFalse(self.flow.admit(proposal)['accepted'])

    def test_reading_and_reopening_preserve_existing_journal_and_additive_tables(self):
        self.start()
        def rows():
            with closing(sqlite3.connect(self.path)) as db:
                return db.execute('SELECT * FROM events ORDER BY sequence').fetchall()
        before = rows()
        for _ in range(3):
            self.manager().initialize()
            self.flow.snapshot()
        self.assertEqual(rows(), before)
        # A previous protocol reader still sees the wallet, with no new trading path.
        previous = CapitalManagerShadow(self.path, wallet_name='SIM_FLOW_CASE',
            scope=self.scope, limits=self.limits, clock=self.clock)
        value = previous.initialize()
        self.assertEqual(value['reserved_units'], 102*U)
        self.assertEqual(value['requests'][0]['state'], 'SUBMITTING')
        self.assertFalse(value['execution_enabled'])
        self.assertEqual(rows(), before)

    def test_cli_recipes_are_explicit_and_never_overwrite_existing_evidence(self):
        from scripts.run_capital_flow_shadow import run_recipes
        directory = Path(self.temp.name)/'fresh-recipe-run'
        report = run_recipes(directory)
        self.assertEqual(report['state'], 'PASSED')
        self.assertEqual(len(report['checks']), 16)
        self.assertTrue(all(x['passed'] for x in report['checks']))
        self.assertEqual(report['ai_calls'], 0)
        self.assertEqual(report['provider_calls'], 0)
        self.assertIs(report['owner_capital_used'], False)
        before = (directory/'report.json').read_bytes()
        with self.assertRaises(FileExistsError): run_recipes(directory)
        self.assertEqual((directory/'report.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
