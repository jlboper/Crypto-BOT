"""Durable loss-latch scenarios; temporary explicit SIM cohorts only."""
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from trader.capital_manager_shadow import AccountScope, MAX_INTEGER, SimulationError
from trader.risk_latches_shadow import (
    CashflowObservation, EquityObservation, LossLatchPolicy, PeriodBaseline, RiskLatchesShadow,
)


NOW = datetime(2026, 10, 26, 12, tzinfo=UTC).timestamp()  # Monday, synthetic time.
DAY = NOW-12*3600
U = 1_000_000


class Clock:
    value = NOW

    def __call__(self):
        return self.value


class RiskLatchShadowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.path = self.directory/"SIM_LOSS_GATE.simulation.sqlite3"
        self.clock = Clock()
        self.scope = AccountScope("SHADOW", "SIM_ACCOUNT", "USDT")
        # These are explicit synthetic test budgets, not an owner risk profile.
        self.policy = LossLatchPolicy("SIM_POLICY", self.scope, "SIM_APPROVER", NOW-60,
                                      50*U, 100*U, 150*U, 120)
        self.manager = self.new_manager()
        self.manager.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def new_manager(self, **kwargs):
        return RiskLatchesShadow(self.path, wallet_name="SIM_LOSS_GATE",
                                 policy=kwargs.pop("policy", self.policy), clock=self.clock, **kwargs)

    def baseline(self, period="DAY", *, start=DAY, equity=1000*U, verified=True):
        return PeriodBaseline(period, start, equity, "SIM_BASE_"+period+str(int(start)), verified)

    def observation(self, *, equity=1000*U, flows=0, at=None, baselines=None, **kwargs):
        observation = EquityObservation(self.scope, "SIM_OBSERVER", "SIM_EVIDENCE",
                                 self.clock() if at is None else at, equity, flows,
                                 kwargs.pop("identity", True), kwargs.pop("inventory", True),
                                 kwargs.pop("reconciled", True), kwargs.pop("cashflows", True),
                                 (self.baseline(), self.baseline("WEEK")) if baselines is None else baselines)
        return replace(observation, evidence_id="SIM_EQ_"+hashlib.sha256(repr(observation).encode()).hexdigest()[:50])

    def observe(self, event_id="SIM_OBSERVE", **kwargs):
        return self.manager.observe(event_id, self.observation(**kwargs))

    def acknowledge(self, target="RECOVERY", event_id="SIM_ACK"):
        return self.manager.acknowledge(event_id, actor="SIM_REVIEWER", evidence_id="SIM_REVIEW", target=target)

    def flow(self, *, amount=100*U, at=None, evidence="SIM_FLOW_EVIDENCE", verified=True):
        return CashflowObservation(self.scope, "SIM_CASHFLOW_OBSERVER", evidence,
                                   self.clock() if at is None else at, amount, verified)

    def advance(self, seconds=1):
        self.clock.value += seconds

    def test_unknown_initial_state_has_no_admission_or_execution_authority(self):
        state = self.manager.snapshot()
        self.assertEqual(state["state"], "RECOVERY_REQUIRED")
        self.assertFalse(state["loss_gate_clear"])
        for key in ("execution_enabled", "admission_authority", "full_risk_admission_verified", "protective_exits_intercepted"):
            self.assertIs(state[key], False)
        self.assertIsNone(state["daily_loss_units"])

    def test_complete_baseline_produces_exact_integer_loss_metrics(self):
        self.assertTrue(self.observe()["recorded"])
        self.advance()
        self.assertTrue(self.observe("SIM_DOWN", equity=990*U)["recorded"])
        state = self.manager.snapshot()
        self.assertEqual(state["state"], "NORMAL")
        for key in ("daily_loss_units", "weekly_loss_units", "drawdown_units"):
            self.assertEqual(state[key], 10*U)
            self.assertIs(type(state[key]), int)
        self.assertTrue(state["loss_gate_clear"])

    def test_daily_limit_is_inclusive_and_latched_after_rebound_and_restart(self):
        self.observe(equity=950*U)
        self.assertIn("DAILY_LOSS_LATCH", self.manager.snapshot()["reasons"])
        self.advance()
        self.observe("SIM_REBOUND", equity=1000*U)
        restarted = self.new_manager()
        state = restarted.initialize()
        self.assertEqual(state["daily_loss_units"], 0)
        self.assertEqual(state["state"], "ENTRY_HALTED")
        with self.assertRaises(SimulationError):
            restarted.acknowledge("SIM_NO_DAY_RESET", actor="SIM_A", evidence_id="SIM_E", target="DAY")

    def test_clock_passage_never_clears_daily_and_missing_baseline_requires_recovery(self):
        self.observe(equity=950*U)
        self.advance(86400)
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        state = self.manager.snapshot()
        self.assertEqual(state["state"], "RECOVERY_REQUIRED")
        self.assertIn("DAILY_LOSS_LATCH", state["reasons"])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertFalse(self.observe("SIM_NO_NEW_BASELINE", equity=950*U, baselines=())["recorded"])
        baseline = self.baseline(start=DAY+86400, equity=950*U)
        self.assertTrue(self.observe("SIM_NEW_DAY", equity=950*U, baselines=(baseline,))["recorded"])
        self.assertIn("PERSISTENT_RECOVERY_LATCH", self.manager.snapshot()["reasons"])
        self.assertTrue(self.acknowledge()["recorded"])
        state = self.manager.snapshot()
        self.assertEqual(state["state"], "NORMAL")
        self.assertEqual(state["daily_loss_units"], 0)
        self.assertEqual(state["weekly_loss_units"], 50*U)

    def test_next_day_baseline_does_not_clear_weekly_loss_latch(self):
        self.observe(equity=900*U)
        self.advance(86400)
        self.observe("SIM_NEW_DAY", equity=900*U, baselines=(self.baseline(start=DAY+86400, equity=900*U),))
        state = self.manager.snapshot()
        self.assertNotIn("DAILY_LOSS_LATCH", state["reasons"])
        self.assertIn("WEEKLY_LOSS_LATCH", state["reasons"])
        self.assertEqual(state["state"], "ENTRY_HALTED")

    def test_verified_new_monday_is_required_for_weekly_reset(self):
        self.observe(equity=900*U)
        self.advance(7*86400)
        self.assertIn("WEEKLY_LOSS_LATCH", self.manager.snapshot()["reasons"])
        baselines = (self.baseline(start=DAY+7*86400, equity=900*U),
                     self.baseline("WEEK", start=DAY+7*86400, equity=900*U))
        self.assertTrue(self.observe("SIM_NEW_WEEK", equity=900*U, baselines=baselines)["recorded"])
        self.assertEqual(self.manager.snapshot()["state"], "NORMAL")
        self.assertEqual(self.manager.snapshot()["high_water_mark_units"], 1000*U)

    def test_drawdown_manual_and_daily_latches_are_independent(self):
        self.observe(equity=850*U)
        self.manager.set_manual_halt("SIM_HALT", actor="SIM_OWNER", evidence_id="SIM_MANUAL_EVIDENCE")
        self.assertFalse(self.acknowledge("DRAWDOWN", "SIM_DD_BAD")["recorded"])
        self.advance()
        self.observe("SIM_RECOVERED_PRICE", equity=990*U)
        self.assertIn("DRAWDOWN_LATCH", self.manager.snapshot()["reasons"])
        self.assertTrue(self.acknowledge("DRAWDOWN", "SIM_DD_GOOD")["recorded"])
        self.assertTrue(self.acknowledge("MANUAL", "SIM_MANUAL_ACK")["recorded"])
        state = self.new_manager().initialize()
        self.assertEqual(state["high_water_mark_units"], 1000*U)
        self.assertIn("DAILY_LOSS_LATCH", state["reasons"])
        self.assertIn("WEEKLY_LOSS_LATCH", state["reasons"])
        self.assertNotIn("DRAWDOWN_LATCH", state["reasons"])
        self.assertNotIn("MANUAL_LATCH", state["reasons"])

    def test_profits_raise_observed_high_water_and_never_create_negative_loss(self):
        self.observe(equity=1100*U)
        self.assertEqual(self.manager.snapshot()["high_water_mark_units"], 1100*U)
        self.advance()
        self.observe("SIM_RETURN_TO_BASELINE", equity=1000*U)
        state = self.manager.snapshot()
        self.assertEqual(state["daily_loss_units"], 0)
        self.assertEqual(state["weekly_loss_units"], 0)
        self.assertEqual(state["drawdown_units"], 100*U)

    def test_deposits_and_withdrawals_are_not_performance(self):
        self.observe()
        self.advance()
        self.manager.record_cashflow("SIM_DEPOSIT", self.flow())
        self.assertFalse(self.manager.snapshot()["loss_gate_clear"])
        self.observe("SIM_EQUITY_AFTER_DEPOSIT", equity=1100*U, flows=100*U)
        self.advance()
        self.manager.record_cashflow("SIM_WITHDRAWAL", self.flow(amount=-50*U, evidence="SIM_WITHDRAW_EVIDENCE"))
        self.observe("SIM_EQUITY_AFTER_WITHDRAWAL", equity=1050*U, flows=50*U)
        state = self.manager.snapshot()
        self.assertEqual(state["state"], "NORMAL")
        self.assertEqual(state["cashflow_adjusted_equity_units"], 1000*U)
        self.assertEqual(state["drawdown_units"], 0)

    def test_deposit_cannot_erase_drawdown_or_loss_latches(self):
        self.observe(equity=800*U)
        self.advance()
        self.manager.record_cashflow("SIM_LARGE_DEPOSIT", self.flow(amount=1000*U))
        self.observe("SIM_DEPOSIT_ADJUSTED", equity=1800*U, flows=1000*U)
        self.assertEqual(self.manager.snapshot()["drawdown_units"], 200*U)
        self.assertFalse(self.acknowledge("DRAWDOWN")["recorded"])

    def test_unrecognized_cashflows_require_reconciliation_and_explicit_acknowledgement(self):
        self.observe()
        self.advance()
        self.assertFalse(self.observe("SIM_UNKNOWN_FLOW", equity=1100*U, flows=100*U)["recorded"])
        self.assertFalse(self.acknowledge(event_id="SIM_PREMATURE_ACK")["recorded"])
        self.manager.record_cashflow("SIM_KNOWN_DEPOSIT", self.flow())
        self.observe("SIM_COMPLETE_EQUITY", equity=1100*U, flows=100*U)
        self.assertFalse(self.manager.snapshot()["loss_gate_clear"])
        self.assertTrue(self.acknowledge()["recorded"])
        self.assertTrue(self.manager.snapshot()["loss_gate_clear"])

    def test_unverified_cashflow_is_not_booked(self):
        self.observe()
        self.advance()
        result = self.manager.record_cashflow("SIM_RUMORED_DEPOSIT", self.flow(verified=False))
        self.assertFalse(result["recorded"])
        self.assertEqual(self.manager.snapshot()["cumulative_net_cashflow_units"], 0)
        self.assertFalse(self.manager.snapshot()["loss_gate_clear"])

    def test_backdated_cashflow_cannot_rewrite_history_or_be_acknowledged_away(self):
        self.observe()
        self.advance()
        result = self.manager.record_cashflow("SIM_LATE_FLOW", self.flow(at=NOW))
        self.assertFalse(result["recorded"])
        self.assertEqual(result["reason"], "CASHFLOW_WOULD_REWRITE_VERIFIED_HISTORY")
        self.observe("SIM_NEW_EQUITY")
        self.assertFalse(self.acknowledge()["recorded"])
        self.assertIn("IMMUTABLE_EVIDENCE_DISPUTE", self.manager.snapshot()["reasons"])

    def test_idempotency_and_evidence_deduplication_survive_restart(self):
        observation = self.observation()
        first = self.manager.observe("SIM_IDEMPOTENT", observation)
        restarted = self.new_manager()
        restarted.initialize()
        self.assertEqual(first, restarted.observe("SIM_IDEMPOTENT", observation))
        self.assertEqual(restarted.snapshot()["event_count"], 1)
        conflict = restarted.observe("SIM_IDEMPOTENT", replace(observation, equity_units=990*U))
        self.assertEqual(conflict["reason"], "IDEMPOTENCY_CONFLICT")
        self.assertFalse(restarted.snapshot()["loss_gate_clear"])
        self.assertEqual(restarted.snapshot()["idempotency_conflict_count"], 1)
        self.advance()
        flow = self.flow()
        restarted.record_cashflow("SIM_FLOW_1", flow)
        self.assertTrue(restarted.record_cashflow("SIM_FLOW_2", flow)["duplicate_evidence"])
        self.assertEqual(restarted.snapshot()["cumulative_net_cashflow_units"], 100*U)

    def test_reused_equity_evidence_is_immutable_and_duplicate_does_not_refresh_freshness(self):
        observation = self.observation()
        self.manager.observe("SIM_ORIGINAL", observation)
        self.advance(10)
        duplicate = self.manager.observe("SIM_DUPLICATE_MESSAGE", observation)
        self.assertTrue(duplicate["duplicate_evidence"])
        self.assertEqual(self.manager.snapshot()["last_observed_at"], NOW)
        conflict = self.manager.observe("SIM_CONFLICTING_EVIDENCE", replace(observation, observed_at=self.clock(), equity_units=990*U))
        self.assertEqual(conflict["reason"], "EQUITY_EVIDENCE_ID_CONFLICT")
        self.observe("SIM_NEW_VALID_SOURCE")
        self.assertFalse(self.acknowledge()["recorded"])
        self.assertIn("IMMUTABLE_EVIDENCE_DISPUTE", self.manager.snapshot()["reasons"])

    def test_conflicting_cashflow_evidence_latches_dispute(self):
        self.manager.record_cashflow("SIM_FLOW_1", self.flow())
        result = self.manager.record_cashflow("SIM_FLOW_2", self.flow(amount=200*U))
        self.assertFalse(result["recorded"])
        self.assertEqual(self.manager.snapshot()["cumulative_net_cashflow_units"], 100*U)
        self.assertIn("IMMUTABLE_EVIDENCE_DISPUTE", self.manager.snapshot()["reasons"])

    def test_baseline_conflict_cannot_reset_recorded_losses(self):
        self.observe(equity=940*U)
        self.advance()
        result = self.observe("SIM_REVISED_OPEN", equity=940*U,
                              baselines=(self.baseline(equity=940*U), self.baseline("WEEK")))
        self.assertFalse(result["recorded"])
        self.assertEqual(self.manager.snapshot()["daily_loss_units"], 60*U)
        self.observe("SIM_BACK_TO_ORIGINAL", equity=940*U)
        self.assertFalse(self.acknowledge()["recorded"])
        self.assertIn("IMMUTABLE_EVIDENCE_DISPUTE", self.new_manager().initialize()["reasons"])

    def test_day_and_week_baselines_at_same_boundary_must_agree(self):
        result = self.observe(baselines=(self.baseline(equity=990*U), self.baseline("WEEK")))
        self.assertFalse(result["recorded"])
        self.assertEqual(result["reason"], "CONFLICTING_BASELINES_AT_SAME_BOUNDARY")
        self.assertIn("IMMUTABLE_EVIDENCE_DISPUTE", self.manager.snapshot()["reasons"])

    def test_boundary_equity_cannot_disagree_with_the_boundary_baseline(self):
        self.clock.value = DAY
        policy = replace(self.policy, approved_at=DAY-1)
        path = self.directory/"SIM_BOUNDARY.simulation.sqlite3"
        manager = RiskLatchesShadow(path, wallet_name="SIM_BOUNDARY", policy=policy, clock=self.clock)
        manager.initialize()
        result = manager.observe("SIM_BOUNDARY_OBSERVATION", self.observation(equity=990*U))
        self.assertEqual(result["reason"], "BASELINE_CONFLICTS_WITH_BOUNDARY_EQUITY")
        self.assertFalse(manager.snapshot()["loss_gate_clear"])

    def test_derived_integer_overflow_invalidates_gate_and_rolls_back_partial_evidence(self):
        self.observe()
        self.advance()
        result = self.observe("SIM_EXTREME_EQUITY", equity=-MAX_INTEGER)
        self.assertFalse(result["recorded"])
        state = self.new_manager().initialize()
        self.assertEqual(result["reason"], "INTEGER_ATOMIC_MONEY_REQUIRED")
        self.assertEqual(state["cashflow_adjusted_equity_units"], 1000*U)
        self.assertFalse(state["loss_gate_clear"])

    def test_cashflow_sum_overflow_is_not_partially_booked(self):
        self.manager.record_cashflow("SIM_MAX_FLOW", self.flow(amount=MAX_INTEGER))
        result = self.manager.record_cashflow("SIM_EXCESS_FLOW", self.flow(amount=1, evidence="SIM_EXCESS_EVIDENCE"))
        self.assertFalse(result["recorded"])
        self.assertEqual(self.manager.snapshot()["cumulative_net_cashflow_units"], MAX_INTEGER)
        self.assertFalse(self.manager.snapshot()["loss_gate_clear"])

    def test_stale_future_unknown_and_partial_data_never_clear_the_gate(self):
        cases = ({"at": NOW-121}, {"at": NOW+1}, {"identity": False}, {"inventory": False},
                 {"reconciled": False}, {"cashflows": False},
                 {"baselines": (self.baseline(verified=False), self.baseline("WEEK"))})
        for index, kwargs in enumerate(cases):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.observe("SIM_INVALID_"+str(index), **kwargs)["recorded"])
                self.assertFalse(self.manager.snapshot()["loss_gate_clear"])
        self.observe("SIM_VALID_AGAIN")
        self.assertFalse(self.manager.snapshot()["loss_gate_clear"])
        self.acknowledge()
        self.assertTrue(self.manager.snapshot()["loss_gate_clear"])
        self.advance(121)
        self.assertFalse(self.manager.snapshot()["loss_gate_clear"])
        self.assertFalse(self.acknowledge("MANUAL", "SIM_STALE_ACK")["recorded"])

    def test_timestamp_regression_and_same_time_conflicts_are_distinct(self):
        self.observe()
        self.advance(2)
        self.observe("SIM_NEXT_OBSERVATION", equity=990*U)
        self.assertFalse(self.observe("SIM_LATE_TICK", at=NOW+1)["recorded"])
        self.advance()
        self.observe("SIM_FRESH_AFTER_LATE", equity=990*U)
        self.assertTrue(self.acknowledge()["recorded"])
        result = self.observe("SIM_REVISED_SAME_TICK", equity=980*U)
        self.assertEqual(result["reason"], "CONFLICTING_EQUITY_AT_SAME_TIME")
        self.assertFalse(self.manager.snapshot()["loss_gate_clear"])

    def test_clock_regression_latches_across_restart_and_requires_new_evidence(self):
        self.observe()
        self.advance(10)
        self.observe("SIM_AFTER_10")
        self.clock.value = NOW+5
        self.assertIn("CLOCK_REGRESSION", self.manager.snapshot()["reasons"])
        self.assertFalse(self.observe("SIM_REGRESSED_CLOCK")["recorded"])
        self.clock.value = NOW+11
        self.assertFalse(self.new_manager().initialize()["loss_gate_clear"])
        self.assertFalse(self.acknowledge(event_id="SIM_NO_NEW_EVIDENCE")["recorded"])
        self.observe("SIM_CLOCK_RESTORED")
        self.assertTrue(self.acknowledge()["recorded"])
        self.assertTrue(self.manager.snapshot()["loss_gate_clear"])

    def test_manual_halt_during_clock_regression_survives_clock_recovery_and_restart(self):
        self.observe()
        self.advance(10)
        self.observe("SIM_LATEST_CLOCK")
        self.clock.value = NOW+5
        receipt = self.manager.set_manual_halt("SIM_OWNER_HALT", actor="SIM_OWNER", evidence_id="SIM_HALT_EVIDENCE")
        self.assertTrue(receipt["recorded"])
        self.assertTrue(receipt["manual_halt"])
        self.assertEqual(receipt["reason"], "CLOCK_REGRESSION")
        self.clock.value = NOW+11
        restarted = self.new_manager()
        self.assertIn("MANUAL_LATCH", restarted.initialize()["reasons"])
        self.observe("SIM_NEW_CLOCK_EVIDENCE")
        self.assertTrue(self.acknowledge()["recorded"])
        self.assertEqual(self.manager.snapshot()["state"], "ENTRY_HALTED")
        self.assertIn("MANUAL_LATCH", self.manager.snapshot()["reasons"])
        self.assertEqual(restarted.set_manual_halt("SIM_OWNER_HALT", actor="SIM_OWNER", evidence_id="SIM_HALT_EVIDENCE"), receipt)
        self.assertTrue(self.acknowledge("MANUAL", "SIM_OWNER_MANUAL_RESET")["recorded"])
        self.assertTrue(self.manager.snapshot()["loss_gate_clear"])

    def test_manual_halt_with_conflicting_message_id_keeps_halt_dispute_and_original_receipt(self):
        observation = self.observation()
        original = self.manager.observe("SIM_DUPLICATE_ID", observation)
        receipt = self.manager.set_manual_halt("SIM_DUPLICATE_ID", actor="SIM_OWNER", evidence_id="SIM_HALT_EVIDENCE")
        self.assertFalse(receipt["recorded"])
        self.assertTrue(receipt["manual_halt"])
        self.assertEqual(receipt["reason"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.manager.observe("SIM_DUPLICATE_ID", observation), original)
        restarted = self.new_manager()
        state = restarted.initialize()
        self.assertIn("MANUAL_LATCH", state["reasons"])
        self.assertIn("IMMUTABLE_EVIDENCE_DISPUTE", state["reasons"])
        self.assertEqual(state["event_count"], 1)
        self.assertEqual(state["idempotency_conflict_count"], 1)
        self.assertFalse(self.acknowledge("MANUAL")["recorded"])

    def test_foreign_wallet_wrong_identity_and_policy_are_never_migrated(self):
        with self.assertRaises(SimulationError):
            RiskLatchesShadow(self.directory/"spot.db", wallet_name="SIM_LOSS_GATE", policy=self.policy)
        foreign = self.directory/"SIM_FOREIGN.simulation.sqlite3"
        db = sqlite3.connect(foreign)
        try:
            db.execute("CREATE TABLE positions(id)")
            db.commit()
        finally:
            db.close()
        before = hashlib.sha256(foreign.read_bytes()).hexdigest()
        manager = RiskLatchesShadow(foreign, wallet_name="SIM_FOREIGN", policy=self.policy, clock=self.clock)
        with self.assertRaises(SimulationError):
            manager.initialize()
        self.assertEqual(hashlib.sha256(foreign.read_bytes()).hexdigest(), before)
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        changed = replace(self.policy, daily_loss_limit_units=100*U)
        with self.assertRaises(SimulationError):
            self.new_manager(policy=changed).initialize()
        changed_scope = replace(self.policy, scope=AccountScope("FUTURES_DEMO", "SIM_ACCOUNT", "USDT"))
        with self.assertRaises(SimulationError):
            self.new_manager(policy=changed_scope).initialize()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_invalid_scalar_values_cannot_enter_a_policy_or_fact(self):
        for value in (True, "100", 1.5, 0, -1, MAX_INTEGER+1):
            with self.subTest(value=value), self.assertRaises(SimulationError):
                replace(self.policy, daily_loss_limit_units=value)
        for value in (True, float("nan"), float("inf"), -1):
            with self.subTest(value=value), self.assertRaises(SimulationError):
                replace(self.policy, approved_at=value)
        with self.assertRaises(SimulationError):
            replace(self.observation(), inventory_complete=1)
        with self.assertRaises(SimulationError):
            replace(self.baseline(), started_at=DAY+1)
        with self.assertRaises(SimulationError):
            replace(self.baseline("WEEK"), started_at=DAY+86400)
        with self.assertRaises(SimulationError):
            AccountScope("LIVE", "SIM_A", "USDT")
        with self.assertRaises(SimulationError):
            replace(self.policy, approved_actor="OWNER")

    def test_uninitialized_calls_do_not_create_a_database(self):
        path = self.directory/"SIM_UNINITIALIZED.simulation.sqlite3"
        manager = RiskLatchesShadow(path, wallet_name="SIM_UNINITIALIZED", policy=self.policy, clock=self.clock)
        with self.assertRaises(SimulationError):
            manager.snapshot()
        with self.assertRaises(SimulationError):
            manager.observe("SIM_EVENT", self.observation())
        self.assertFalse(path.exists())

    def test_before_commit_failure_rolls_back_evidence_and_latch_atomically(self):
        self.observe()
        self.advance()
        def fail(stage):
            if stage == "BEFORE_COMMIT":
                raise RuntimeError("synthetic power loss")
        manager = self.new_manager(fault_hook=fail)
        manager.initialize()
        observation = self.observation(equity=800*U)
        before = self.manager.snapshot()
        with self.assertRaises(RuntimeError):
            manager.observe("SIM_CRASH", observation)
        after = self.new_manager().initialize()
        self.assertEqual(after["event_count"], before["event_count"])
        self.assertEqual(after["daily_loss_units"], 0)
        self.assertTrue(self.manager.observe("SIM_CRASH", observation)["recorded"])
        self.assertIn("DRAWDOWN_LATCH", self.manager.snapshot()["reasons"])

    def test_after_commit_failure_retries_exactly_once_after_restart(self):
        self.observe()
        self.advance()
        def fail(stage):
            if stage == "AFTER_COMMIT":
                raise RuntimeError("synthetic lost acknowledgement")
        manager = self.new_manager(fault_hook=fail)
        manager.initialize()
        observation = self.observation(equity=800*U)
        with self.assertRaises(RuntimeError):
            manager.observe("SIM_ACK_LOST", observation)
        restarted = self.new_manager()
        state = restarted.initialize()
        self.assertEqual(state["event_count"], 2)
        self.assertIn("DRAWDOWN_LATCH", state["reasons"])
        self.assertTrue(restarted.observe("SIM_ACK_LOST", observation)["recorded"])
        self.assertEqual(restarted.snapshot()["event_count"], 2)

    def test_concurrent_duplicate_events_do_not_double_book_cashflow(self):
        self.observe()
        self.advance()
        managers = [self.new_manager(), self.new_manager()]
        for manager in managers:
            manager.initialize()
        barrier = threading.Barrier(3)
        results, errors = [], []
        flow = self.flow()
        def run(manager):
            try:
                barrier.wait()
                results.append(manager.record_cashflow("SIM_SAME_FLOW", flow))
            except BaseException as exc:
                errors.append(type(exc).__name__)
        threads = [threading.Thread(target=run, args=(manager,)) for manager in managers]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        state = self.manager.snapshot()
        self.assertEqual(state["cumulative_net_cashflow_units"], 100*U)
        self.assertEqual(state["event_count"], 2)

    def test_concurrent_distinct_cashflows_serialize_without_lost_updates(self):
        self.observe()
        self.advance()
        managers = [self.new_manager(), self.new_manager()]
        for manager in managers:
            manager.initialize()
        barrier = threading.Barrier(3)
        errors = []
        def run(index):
            try:
                barrier.wait()
                managers[index].record_cashflow("SIM_FLOW_"+str(index), self.flow(evidence="SIM_EVIDENCE_"+str(index)))
            except BaseException as exc:
                errors.append(type(exc).__name__)
        threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(self.manager.snapshot()["cumulative_net_cashflow_units"], 200*U)

    def test_journal_and_baselines_are_append_only(self):
        self.observe()
        before = self.manager.snapshot()
        db = sqlite3.connect(self.path)
        try:
            for query in ("UPDATE events SET result='{}'", "DELETE FROM events", "UPDATE baselines SET adjusted=0", "DELETE FROM baselines"):
                with self.subTest(query=query), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(query)
                db.rollback()
        finally:
            db.close()
        self.assertEqual(self.manager.snapshot(), before)

    def test_rehearsal_recipes_are_reproducible_and_reject_existing_directories(self):
        from scripts.audit_risk_latches_shadow import run_rehearsal
        directory = self.directory/"new-rehearsal"
        report = run_rehearsal(directory)
        self.assertEqual(report["state"], "PASS")
        self.assertEqual(report["scenario_count"], 9)
        self.assertEqual(report["passed_count"], 9)
        self.assertEqual(report["failed_count"], 0)
        for key in ("operational_evidence", "admission_authority", "execution_enabled", "live_implemented", "promotion_allowed"):
            self.assertIs(report[key], False)
        report_hash = hashlib.sha256((directory/"report.json").read_bytes()).hexdigest()
        with self.assertRaises(FileExistsError):
            run_rehearsal(directory)
        self.assertEqual(hashlib.sha256((directory/"report.json").read_bytes()).hexdigest(), report_hash)


if __name__ == "__main__":
    unittest.main()
