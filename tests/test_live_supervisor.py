"""Single synchronous owner, synthetic HTTPS only; no financial activation."""
from dataclasses import replace
import hashlib
import json
import unittest
from unittest.mock import Mock, patch

from trader.live_supervisor import (LiveSupervisedExecutor, LiveWalletRuntime,
    LiveSupervisionService, ReadOnlyAdmissionFactsSource)
from trader.central_admission import CentralAdmission
from trader.live_strategy_adapter import LiveStrategyPlanStore
from trader.live_transport import LiveError, LiveReadOnlyTransport, LiveOrderTransport, LiveSubmissionJournal
from tests.test_central_admission import facts
from tests import test_live_strategy_adapter as fixtures
from tests.test_live_preproduction import pair
from tests.test_live_execution_runtime import FakeSpotVenue


class LiveSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeStrategyAdapterTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.bundle = self.fixture.prepare()
        self.coordinator, self.venue = self.fixture.coordinator(self.bundle)
        self.coordinator.transport.authority = None
        self.wallet = LiveWalletRuntime(self.coordinator.admission, self.coordinator.transport,
            self.fixture.store, self.coordinator.provider)
        self.facts = Mock(side_effect=lambda *args: facts(self.bundle.proposal.scope))
        self.proposals = Mock(return_value=(self.bundle,))
        self.validate = Mock(return_value=True)
        self.halt = Mock(return_value=False)
        self.runtime = self.make_runtime()

    def make_runtime(self):
        return LiveSupervisedExecutor((self.wallet,), facts_source=self.facts, proposal_source=self.proposals,
            venue_validator=self.validate, entry_halted=self.halt, clock=self.fixture.clock)

    def writes(self):
        return sum(method != 'GET' for method, _, _ in self.venue.requests)

    def test_execute_retains_plan_and_rechecks_facts_before_transport(self):
        result = self.runtime.cycle()
        self.assertEqual(result['wallets'][0]['entries'][0]['state'], 'OPEN')
        self.assertEqual(self.facts.call_count, 2)
        self.assertEqual(self.fixture.store.load(self.bundle.proposal.proposal_id).payload(), self.bundle.payload())

    def test_restart_recovers_before_halt_without_ai_or_new_writes(self):
        self.runtime.cycle()
        writes = self.writes()
        self.facts.reset_mock()
        self.proposals.reset_mock()
        self.halt.return_value = True
        self.fixture.clock.value += 1
        result = self.make_runtime().cycle()
        self.assertEqual(result['wallets'][0]['recoveries'][0]['state'], 'OPEN')
        self.assertEqual(self.writes(), writes)
        self.facts.assert_not_called()
        self.proposals.assert_not_called()

    def test_recovery_tick_does_not_consult_entry_halt_facts_or_ai(self):
        self.runtime.cycle()
        self.halt.reset_mock()
        self.facts.reset_mock()
        self.proposals.reset_mock()
        self.fixture.clock.value += 1
        result = self.make_runtime().cycle(recover_only=True)
        self.assertEqual(result['wallets'][0]['recoveries'][0]['state'], 'OPEN')
        self.halt.assert_not_called()
        self.facts.assert_not_called()
        self.proposals.assert_not_called()

    def test_unknown_entry_is_queried_after_restart_without_resubmission(self):
        self.venue.fail_entry = True
        self.assertEqual(self.runtime.cycle()['wallets'][0]['entries'][0]['state'], 'UNKNOWN')
        self.venue.fail_entry = False
        self.fixture.clock.value += 1
        self.halt.return_value = True
        result = self.make_runtime().cycle()
        self.assertEqual(result['wallets'][0]['recoveries'][0]['state'], 'OPEN')
        self.assertEqual(sum(m == 'POST' and p == '/fapi/v1/order' for m, p, _ in self.venue.requests), 1)

    def test_missing_retained_plan_blocks_new_proposals_and_retains_reservation(self):
        self.runtime.cycle()
        self.fixture.store.path.unlink()
        self.proposals.reset_mock()
        result = self.make_runtime().cycle()
        self.assertIn('PENDING_RECOVERY_BLOCKS_ENTRIES', result['wallets'][0]['reasons'])
        self.proposals.assert_not_called()
        self.assertGreater(self.coordinator.admission.snapshot()['reserved_units'], 0)

    def test_reservation_without_claim_is_not_submitted_after_restart(self):
        self.fixture.store.save(self.bundle)
        cap = self.wallet.provider.capability(self.bundle.proposal.scope, self.bundle.policy.fingerprint,
            self.bundle.proposal.fingerprint, self.fixture.clock())
        self.wallet.admission.assess_and_reserve(self.bundle.proposal, facts(self.bundle.proposal.scope),
            event_id='SYNTHETIC_CRASH_AFTER_RESERVE', capability=cap)
        result = self.runtime.cycle()
        self.assertIn('UNSENT_RESERVATION_REQUIRES_REVIEW', result['wallets'][0]['recoveries'][0]['reasons'])
        self.assertEqual(self.writes(), 0)
        self.proposals.assert_not_called()

    def test_failed_or_incomplete_facts_do_not_query_ai_or_admit(self):
        for source in (LiveError('SYNTHETIC_UNAVAILABLE'),
                       lambda *args: replace(facts(self.bundle.proposal.scope), cashflows_complete=False),
                       lambda *args: facts(self.bundle.proposal.scope, baseline=())):
            self.facts.side_effect = source
            result = self.runtime.cycle()
            self.assertEqual(result['state'], 'BLOCKED')
            self.proposals.assert_not_called()
            self.assertEqual(self.writes(), 0)

    def test_one_failed_wallet_does_not_starve_other_wallet_protection(self):
        self.runtime.cycle()
        spot_plan = self.fixture.prepare(self.fixture.spot_decision())
        spot_admission = CentralAdmission(self.fixture.root / 'central-admission-spot.sqlite3',
            scope=spot_plan.proposal.scope, policy=spot_plan.policy, clock=self.fixture.clock,
            capability_verifier=self.wallet.provider.verifier)
        spot_admission.initialize()
        spot_store = LiveStrategyPlanStore(self.fixture.root / 'live-strategy-plans-spot.sqlite3')
        spot_store.initialize()
        spot_transport = LiveOrderTransport({'SPOT_LIVE':pair()},
            journal=LiveSubmissionJournal(self.fixture.root / 'LIVE_SUBMISSION_spot.sqlite3'),
            clock=self.fixture.clock, monotonic=lambda:0)
        spot_wallet = LiveWalletRuntime(spot_admission, spot_transport, spot_store, self.wallet.provider)
        spot_venue = FakeSpotVenue(spot_admission)
        accounts = Mock(side_effect=lambda scope, *args: facts(scope))
        proposals = Mock(side_effect=lambda scope, *args: (spot_plan,) if scope.environment == 'SPOT_LIVE' else ())
        runtime = LiveSupervisedExecutor((self.wallet, spot_wallet), facts_source=accounts, proposal_source=proposals,
            venue_validator=lambda *args:True, entry_halted=lambda *args:False, clock=self.fixture.clock)
        with patch.object(spot_transport, '_opener', return_value=spot_venue):
            first = runtime.cycle()
            self.assertEqual(first['wallets'][1]['entries'][0]['state'], 'OPEN')
            accounts.reset_mock()
            proposals.reset_mock()
            self.fixture.clock.value += 1
            with patch.object(self.wallet.admission, 'snapshot', side_effect=OSError('Synthetic failed wallet')):
                result = runtime.cycle(recover_only=True)
            self.assertIn('PENDING_RECOVERY_BLOCKS_ENTRIES', result['wallets'][0]['reasons'])
            self.assertEqual(result['wallets'][1]['recoveries'][0]['state'], 'OPEN')
            accounts.assert_not_called()
            proposals.assert_not_called()

    def test_facts_change_before_send_and_venue_failure_block_entry(self):
        self.validate.return_value = False
        self.assertEqual(self.runtime.cycle()['state'], 'BLOCKED')
        self.assertEqual(self.writes(), 0)
        self.validate.return_value = True
        self.facts.side_effect = [facts(self.bundle.proposal.scope), replace(facts(self.bundle.proposal.scope), inventory_complete=False)]
        self.assertEqual(self.runtime.cycle()['state'], 'BLOCKED')
        self.assertEqual(self.writes(), 0)

    def test_cycle_cannot_overlap_or_activate_from_testnet(self):
        self.runtime._lock.acquire()
        try:
            with self.assertRaisesRegex(LiveError, 'SINGLE_SUPERVISOR'):
                self.runtime.cycle()
        finally:
            self.runtime._lock.release()
        cfg = Mock()
        cfg.bot.mode = 'testnet'
        self.assertFalse(LiveSupervisionService(cfg).cycle()['execution_enabled'])
        with self.assertRaises(LiveError):
            LiveSupervisionService(cfg, runtime=self.runtime)

    def test_read_only_fact_cut_retains_originals_but_does_not_certify(self):
        transport = LiveReadOnlyTransport({'SPOT_LIVE':pair()})
        captured = []
        def retain(value):
            captured.append(value)
            return {'sha256':hashlib.sha256(json.dumps(value).encode()).hexdigest()}
        source = ReadOnlyAdmissionFactsSource(transport, retain=retain)
        with patch.object(transport, 'get', return_value={}):
            result = source.observe('SPOT_LIVE')
            self.assertEqual(result['response_count'], 3)
            self.assertEqual(len(captured), 3)
            self.assertFalse(result['execution_enabled'])
            with self.assertRaisesRegex(LiveError, 'FACTS_NOT_CERTIFIED'):
                source(self.fixture.spot_decision().scope, self.bundle.policy, self.fixture.clock())


if __name__ == '__main__':
    unittest.main()
