"""Pure protocol scenarios using only fresh named simulation wallets in temp."""
import ast
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from trader.capital_manager_shadow import AccountScope,SimulationLimits,LegRequest,ReservationRequest,ReconciliationEvent,CapitalManagerShadow,SimulationError,MAX_INTEGER

NOW=1800000010.
U=1_000_000


class Clock:
    value=NOW
    def __call__(self):return self.value
    def advance(self,seconds):self.value+=seconds


def policy():
    # Explicit synthetic actor budgets, not proposed production risk settings.
    return SimulationLimits("SIM_POLICY_1","SIM_APPROVER",NOW,"EXPLICIT_NEW_SIMULATION_COHORT",
        1000*U,600*U,600*U,600*U,20*U,(("SIM_SPOT",600*U,20*U),("SIM_PULSE",600*U,20*U)),120,10)


@contextmanager
def db_open(path):
    db=sqlite3.connect(path)
    try:
        with db:yield db
    finally:db.close()


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CapitalShadowTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.directory=Path(self.temporary.name)
        self.clock=Clock()
        self.scope=AccountScope("SHADOW","SIM_SHARED_SCENARIO","USDT")
        self.limits=policy()
        self.path=self.directory/"SIM_WALLET.simulation.sqlite3"
        self.manager=self.new_manager()
        self.manager.initialize()

    def tearDown(self):self.temporary.cleanup()

    def new_manager(self,**kwargs):
        return CapitalManagerShadow(self.path,wallet_name="SIM_WALLET",scope=kwargs.pop("scope",self.scope),limits=kwargs.pop("limits",self.limits),clock=self.clock,**kwargs)

    def request(self,request_id="SIM_REQ_1",*,strategy="SIM_SPOT",symbol="BTCUSDT",principal=100*U,fee=2*U,risk=5*U,legs=None,expires=None):
        return ReservationRequest(request_id,self.scope,strategy,self.limits.policy_id,
            legs or (LegRequest("SIM_LEG_1",symbol,"LONG","SPOT_REFERENCE",principal,fee,risk),),
            self.clock()+60 if expires is None else expires)

    def submit(self,request_id="SIM_REQ_1",*,leg_ids=("SIM_LEG_1",)):
        return self.manager.mark_submitting("SIM_SUBMIT_"+request_id,request_id,actor="SIM_EXECUTOR",client_order_ids={v:"SIM_ORDER_"+request_id+v for v in leg_ids})

    def event(self,event_id="SIM_EVENT_1",*,request_id="SIM_REQ_1",leg_id="SIM_LEG_1",state="FILLED",filled=100*U,entry=U,exit_fee=0,pnl=0,closed=False,complete=True,at=None):
        return ReconciliationEvent(event_id,self.scope,request_id,leg_id,"SIM_RECONCILER",state,filled,entry,exit_fee,pnl,closed,self.clock() if at is None else at,complete)

    def observe(self,event_id="SIM_BALANCE",*,known=True,pending=True,at=None,units=None):
        return self.manager.observe_balance(event_id,actor="SIM_ACCOUNT_OBSERVER",balance_units=self.manager.snapshot()["book_equity_units"] if units is None else units,
            observed_at=self.clock() if at is None else at,known=known,pending_orders_complete=pending)

    def assertConserved(self,manager=None):
        snapshot=(manager or self.manager).snapshot()
        self.assertEqual(snapshot["book_equity_units"],1000*U+snapshot["realized_pnl_units"]-snapshot["fees_paid_units"])
        self.assertEqual(snapshot["book_equity_units"],snapshot["free_units_signed"]+snapshot["reserved_units"]+snapshot["committed_units"])
        for key in ("book_equity_units","free_units_signed","reserved_units","committed_units","fees_paid_units","realized_pnl_units"):
            self.assertIs(type(snapshot[key]),int)
        self.assertGreaterEqual(snapshot["reserved_units"],0)
        self.assertGreaterEqual(snapshot["committed_units"],0)
        return snapshot

    def test_new_explicit_simulation_funding_is_not_an_existing_balance(self):
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["free_units_signed"],1000*U)
        self.assertEqual(snapshot["entry_gate"],None)
        self.assertEqual(snapshot["event_count"],1)
        self.assertTrue(snapshot["simulation_only"])
        self.assertFalse(snapshot["execution_enabled"])
        self.assertFalse(snapshot["real_account_adapter"])

    def test_foreign_and_wrongly_named_files_are_never_migrated(self):
        with self.assertRaises(SimulationError):
            CapitalManagerShadow(self.directory/"spot-trader.db",wallet_name="SIM_WALLET",scope=self.scope,limits=self.limits)
        foreign=self.directory/"SIM_FOREIGN.simulation.sqlite3"
        with db_open(foreign) as db:db.execute("CREATE TABLE financial_positions(id)")
        before=fingerprint(foreign)
        manager=CapitalManagerShadow(foreign,wallet_name="SIM_FOREIGN",scope=self.scope,limits=self.limits)
        with self.assertRaises(SimulationError):manager.initialize()
        self.assertEqual(fingerprint(foreign),before)

    def test_reads_and_mutations_before_initialize_do_not_create_files(self):
        path=self.directory/"SIM_EMPTY.simulation.sqlite3"
        manager=CapitalManagerShadow(path,wallet_name="SIM_EMPTY",scope=self.scope,limits=self.limits)
        with self.assertRaises(SimulationError):manager.snapshot()
        with self.assertRaises(SimulationError):manager.reserve(self.request())
        self.assertFalse(path.exists())

    def test_integer_money_and_explicit_policy_scope_are_required(self):
        for value in (1.1,True,"100",-1,MAX_INTEGER+1):
            with self.subTest(value=value),self.assertRaises(SimulationError):
                LegRequest("SIM_L","BTCUSDT","LONG","SPOT_REFERENCE",value,1,1)
        for env in ("LIVE","TESTNET","unknown"):
            with self.assertRaises(SimulationError):AccountScope(env,"SIM_ACCOUNT","USDT")
        with self.assertRaises(SimulationError):AccountScope("SHADOW","actual-account","USDT")
        with self.assertRaises(SimulationError):replace(self.limits,total_allocated_limit_units=1001*U)
        with self.assertRaises(SimulationError):replace(self.limits,funding_source="SUM_EXISTING_WALLETS")

    def test_environment_and_account_isolation_never_consolidates_wallets(self):
        before=fingerprint(self.path)
        for scope in (AccountScope("PAPER",self.scope.account_id,"USDT"),AccountScope("SPOT_TESTNET",self.scope.account_id,"USDT"),
                      AccountScope("FUTURES_DEMO",self.scope.account_id,"USDT"),AccountScope("SHADOW","SIM_OTHER","USDT")):
            with self.subTest(scope=scope),self.assertRaises(SimulationError):self.new_manager(scope=scope).initialize()
        self.assertEqual(fingerprint(self.path),before)
        wrong=replace(self.request(),scope=AccountScope("PAPER",self.scope.account_id,"USDT"))
        with self.assertRaises(SimulationError):self.manager.reserve(wrong)

    def test_reserve_is_exactly_idempotent_across_restart_and_scope_strategy(self):
        request=self.request()
        first=self.manager.reserve(request)
        count=self.manager.snapshot()["event_count"]
        manager=self.new_manager();manager.initialize()
        self.assertEqual(first,manager.reserve(request))
        self.assertEqual(manager.snapshot()["event_count"],count)
        self.assertEqual(manager.snapshot()["reserved_units"],102*U)
        with self.assertRaises(SimulationError):manager.reserve(replace(request,strategy_id="SIM_PULSE"))
        self.assertEqual(manager.snapshot()["reserved_units"],102*U)

    def test_account_asset_conflict_is_not_hidden_by_strategy_key(self):
        self.assertTrue(self.manager.reserve(self.request())["accepted"])
        second=self.manager.reserve(self.request("SIM_REQ_2",strategy="SIM_PULSE"))
        self.assertFalse(second["accepted"])
        self.assertEqual(second["reason"],"ACCOUNT_ASSET_ALREADY_RESERVED")
        self.assertEqual(self.assertConserved()["reserved_units"],102*U)

    def test_concurrent_competing_strategies_obey_one_parent_account_budget(self):
        managers=[self.new_manager(),self.new_manager()]
        for manager in managers:manager.initialize()
        requests=[self.request("SIM_REQ_A",principal=400*U,strategy="SIM_SPOT"),self.request("SIM_REQ_B",principal=400*U,strategy="SIM_PULSE",symbol="ETHUSDT")]
        gate=threading.Barrier(3)
        results=[]
        def run(manager,request):
            gate.wait()
            results.append(manager.reserve(request))
        threads=[threading.Thread(target=run,args=pair) for pair in zip(managers,requests)]
        for thread in threads:thread.start()
        gate.wait()
        for thread in threads:thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sum(result["accepted"] for result in results),1)
        self.assertEqual(self.assertConserved()["reserved_units"],402*U)

    def test_explicit_child_strategy_and_inclusive_risk_caps_apply(self):
        request=self.request(risk=21*U)
        self.assertEqual(self.manager.reserve(request)["reason"],"EXPLICIT_SIMULATION_BUDGET_EXCEEDED")
        self.assertFalse(self.manager.reserve(self.request("SIM_REQ_2",strategy="SIM_UNKNOWN"))["accepted"])
        self.assertEqual(self.assertConserved()["reserved_units"],0)

    def test_atomic_pair_reserves_both_legs_and_both_cost_buffers(self):
        legs=(LegRequest("SIM_SPOT_LEG","BTCUSDT","LONG","SPOT_REFERENCE",50*U,U,2*U),
              LegRequest("SIM_FUT_LEG","BTCUSDT","SHORT","FUTURES_REFERENCE",50*U,U,2*U))
        self.assertTrue(self.manager.reserve(self.request(legs=legs))["accepted"])
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["reserved_units"],102*U)
        self.assertEqual(len(snapshot["requests"][0]["legs"]),2)
        self.assertFalse(snapshot["atomic_hedge_claimed"])

    def test_partial_fill_costs_final_fill_and_close_conserve_every_atomic_unit(self):
        self.manager.reserve(self.request());self.submit()
        partial=self.manager.reconcile(self.event("SIM_PART",state="PARTIAL",filled=40*U,entry=400000))
        self.assertEqual(partial["state"],"PARTIAL")
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["reserved_units"],61_600_000)
        self.assertEqual(snapshot["committed_units"],40*U)
        self.assertEqual(snapshot["fees_paid_units"],400000)
        final=self.manager.reconcile(self.event("SIM_FILL"))
        self.assertEqual(final["state"],"FILLED")
        self.assertEqual(final["released_units"],0)
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["committed_units"],100*U)
        self.assertEqual(snapshot["reserved_units"],U)
        self.assertEqual(snapshot["free_units_signed"],898*U)
        close=self.manager.reconcile(self.event("SIM_CLOSE",state="CLOSED",exit_fee=U,pnl=10*U,closed=True))
        self.assertEqual(close["state"],"CLOSED")
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["free_units_signed"],1008*U)
        self.assertEqual(snapshot["fees_paid_units"],2*U)

    def test_duplicate_and_reordered_reconciliation_cannot_double_charge_fees(self):
        self.manager.reserve(self.request());self.submit()
        event=self.event("SIM_FILL")
        first=self.manager.reconcile(event)
        self.assertEqual(self.manager.reconcile(event),first)
        self.assertEqual(self.assertConserved()["fees_paid_units"],U)
        changed=replace(event,cumulative_entry_fees_units=2*U)
        with self.assertRaises(SimulationError):self.manager.reconcile(changed)
        old=self.manager.reconcile(self.event("SIM_LATE_PART",state="PARTIAL",filled=50*U,entry=500000))
        self.assertEqual(old["state"],"RECOVERY_REQUIRED")
        self.assertEqual(self.assertConserved()["committed_units"],100*U)

    def test_ttl_cancel_request_unknown_and_restart_never_release_pending_funds(self):
        self.manager.reserve(self.request(expires=self.clock()+1));self.submit()
        self.clock.advance(3600)
        before=self.assertConserved()["reserved_units"]
        self.assertTrue(self.manager.snapshot()["requests"][0]["expired_diagnostic_only"])
        self.assertEqual(self.manager.request_cancel("SIM_CANCEL","SIM_REQ_1",actor="SIM_ACTOR")["released_units"],0)
        restarted=self.new_manager();restarted.initialize()
        self.assertEqual(restarted.recover("SIM_RECOVER",actor="SIM_ACTOR")["released_units"],0)
        self.assertEqual(restarted.snapshot()["requests"][0]["state"],"UNKNOWN")
        self.assertEqual(restarted.snapshot()["reserved_units"],before)
        event=self.event("SIM_CANCELLED",state="CANCELLED",filled=0,entry=0)
        self.assertEqual(restarted.reconcile(event)["state"],"CANCELLED")
        self.assertEqual(self.assertConserved()["reserved_units"],0)

    def test_partial_cancel_releases_only_unused_and_keeps_open_commitment(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_PART",state="PARTIAL",filled=40*U,entry=400000))
        self.manager.request_cancel("SIM_CANCEL","SIM_REQ_1",actor="SIM_ACTOR")
        result=self.manager.reconcile(self.event("SIM_CANCELLED",state="CANCELLED",filled=40*U,entry=400000))
        self.assertEqual(result["state"],"RECOVERY_REQUIRED")
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["reserved_units"],1_600_000)
        self.assertEqual(snapshot["committed_units"],40*U)
        self.assertEqual(snapshot["free_units_signed"],958*U)
        self.assertEqual(result["released_units"],60*U)

    def test_single_leg_failure_keeps_other_leg_until_explicit_simulated_unwind(self):
        legs=(LegRequest("SIM_A","BTCUSDT","LONG","SPOT_REFERENCE",50*U,U,2*U),LegRequest("SIM_B","BTCUSDT","SHORT","FUTURES_REFERENCE",50*U,U,2*U))
        self.manager.reserve(self.request(legs=legs));self.submit(leg_ids=("SIM_A","SIM_B"))
        self.manager.reconcile(self.event("SIM_FILL_A",leg_id="SIM_A",filled=50*U,entry=500000))
        self.manager.reconcile(self.event("SIM_REJECT_B",leg_id="SIM_B",state="CANCELLED",filled=0,entry=0))
        self.assertEqual(self.assertConserved()["committed_units"],50*U)
        result=self.manager.reconcile(self.event("SIM_UNWIND_A",leg_id="SIM_A",state="CLOSED",filled=50*U,entry=500000,exit_fee=500000,pnl=-2*U,closed=True))
        self.assertEqual(result["state"],"CLOSED")
        self.assertEqual(self.assertConserved()["free_units_signed"],997*U)

    def test_stale_unknown_mismatched_and_pending_balance_halt_new_reservations(self):
        self.clock.advance(121)
        self.assertEqual(self.manager.reserve(self.request())["reason"],"BALANCE_STALE_OR_FUTURE")
        self.observe("SIM_UNKNOWN",known=False)
        self.assertEqual(self.manager.reserve(self.request("SIM_REQ_2"))["reason"],"BALANCE_UNKNOWN_OR_CHANGED")
        self.observe("SIM_MISMATCH",units=999*U)
        self.assertFalse(self.manager.observe_balance("SIM_UNKNOWN_DUP",actor="SIM_ACTOR",balance_units=999*U,observed_at=self.clock(),known=True,pending_orders_complete=True)["accepted"])
        self.observe("SIM_PENDING",pending=False)
        self.assertEqual(self.manager.reserve(self.request("SIM_REQ_3"))["reason"],"PENDING_ORDER_RECONCILIATION_REQUIRED")
        self.observe("SIM_GOOD")
        self.assertTrue(self.manager.reserve(self.request("SIM_REQ_4"))["accepted"])

    def test_new_submission_and_financial_events_require_fresh_complete_reconciliation(self):
        self.manager.reserve(self.request());self.submit()
        self.assertEqual(self.manager.reserve(self.request("SIM_REQ_2",symbol="ETHUSDT"))["reason"],"PENDING_ORDER_RECONCILIATION_REQUIRED")
        self.manager.reconcile(self.event("SIM_FILL"))
        self.assertEqual(self.manager.reserve(self.request("SIM_REQ_3",symbol="ETHUSDT"))["reason"],"BALANCE_UNKNOWN_OR_CHANGED")
        self.observe("SIM_RECONCILED")
        self.assertTrue(self.manager.reserve(self.request("SIM_REQ_4",symbol="ETHUSDT"))["accepted"])

    def test_fees_over_buffer_are_booked_without_hiding_cash_overrun(self):
        self.manager.reserve(self.request());self.submit()
        result=self.manager.reconcile(self.event("SIM_OVERRUN",entry=3*U))
        self.assertEqual(result["state"],"RECOVERY_REQUIRED")
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["fees_paid_units"],3*U)
        self.assertEqual(snapshot["book_equity_units"],997*U)
        self.assertEqual(snapshot["free_units_signed"],897*U)

    def test_confirmed_gap_loss_is_not_capped_or_relabelled_as_zero_equity(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_FILL"))
        self.manager.reconcile(self.event("SIM_GAP",state="CLOSED",exit_fee=U,pnl=-1200*U,closed=True))
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["book_equity_units"],-202*U)
        self.assertEqual(snapshot["free_units_signed"],-202*U)
        self.assertEqual(snapshot["available_units"],0)
        self.assertEqual(snapshot["shortfall_units"],202*U)
        self.assertIsNotNone(snapshot["entry_gate"])

    def test_closed_position_cannot_be_reopened_by_an_out_of_order_message(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_FILL"))
        self.manager.reconcile(self.event("SIM_CLOSE",state="CLOSED",closed=True))
        before=self.assertConserved()
        result=self.manager.reconcile(self.event("SIM_OLD_FILL"))
        self.assertEqual(result["state"],"RECOVERY_REQUIRED")
        after=self.assertConserved()
        self.assertEqual(before["committed_units"],after["committed_units"])
        self.assertEqual(after["committed_units"],0)

    def test_crash_before_commit_rolls_back_and_retry_after_commit_is_idempotent(self):
        point=["BEFORE_COMMIT"]
        def fail(stage):
            if stage==point[0]:raise RuntimeError("synthetic interruption")
        manager=self.new_manager(fault_hook=fail);manager.initialize()
        request=self.request()
        with self.assertRaises(RuntimeError):manager.reserve(request)
        self.assertEqual(self.assertConserved()["reserved_units"],0)
        point[0]="AFTER_COMMIT"
        with self.assertRaises(RuntimeError):manager.reserve(request)
        self.assertEqual(self.assertConserved()["reserved_units"],102*U)
        point[0]="NONE"
        self.assertTrue(manager.reserve(request)["accepted"])
        self.assertEqual(self.assertConserved()["reserved_units"],102*U)

    def test_events_are_append_only_and_snapshot_never_changes_the_wallet(self):
        self.manager.reserve(self.request())
        before=fingerprint(self.path)
        self.manager.snapshot()
        self.assertEqual(before,fingerprint(self.path))
        with db_open(self.path) as db:
            for command in ("UPDATE events SET result='{}'","DELETE FROM events"):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(command)

    def test_policy_cannot_silently_increase_or_reset_funded_scenario(self):
        self.manager.reserve(self.request())
        before=fingerprint(self.path)
        with self.assertRaises(SimulationError):self.new_manager(limits=replace(self.limits,policy_id="SIM_NEW_POLICY")).initialize()
        self.assertEqual(before,fingerprint(self.path))
        self.assertEqual(self.assertConserved()["reserved_units"],102*U)

    def test_mutable_child_policy_or_replaced_runtime_policy_cannot_raise_caps(self):
        with self.assertRaises(SimulationError):replace(self.limits,strategy_limits=(["SIM_SPOT",600*U,20*U],))
        before=fingerprint(self.path)
        self.manager.limits=replace(self.limits,total_allocated_limit_units=700*U,reserved_limit_units=700*U)
        with self.assertRaises(SimulationError):self.manager.reserve(self.request())
        self.assertEqual(fingerprint(self.path),before)

    def test_terminal_filled_order_cannot_regress_and_re_reserve_released_buffer(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_FILLED"))
        before=self.assertConserved()
        result=self.manager.reconcile(self.event("SIM_OLD_PARTIAL",state="PARTIAL"))
        after=self.assertConserved()
        self.assertEqual(result["state"],"RECOVERY_REQUIRED")
        self.assertEqual(before["reserved_units"],after["reserved_units"])
        self.assertEqual(before["committed_units"],after["committed_units"])

    def test_read_summary_reports_omitted_inventory_instead_of_silently_truncating(self):
        other=self.directory/"SIM_BIG.simulation.sqlite3"
        limits=replace(self.limits,max_active_requests=30)
        manager=CapitalManagerShadow(other,wallet_name="SIM_BIG",scope=self.scope,limits=limits,clock=self.clock)
        manager.initialize()
        for i in range(21):
            self.assertTrue(manager.reserve(self.request("SIM_R_"+str(i),symbol=f"AAA{i}USDT",principal=U,fee=10000,risk=10000))["accepted"])
        snapshot=manager.snapshot()
        self.assertEqual(snapshot["request_count"],21)
        self.assertEqual(snapshot["requests_omitted"],1)
        self.assertFalse(snapshot["inventory_complete"])
        self.assertEqual(snapshot["reserved_units"],21_210_000)

    def test_unknown_stale_or_partial_observation_never_releases_committed_principal(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_PART",state="PARTIAL",filled=40*U,entry=400000))
        before=self.assertConserved()
        result=self.manager.reconcile(self.event("SIM_OLD_CANCEL",state="CANCELLED",filled=0,entry=0,at=self.clock()-121))
        after=self.assertConserved()
        self.assertEqual(result["state"],"UNKNOWN")
        self.assertEqual(before["reserved_units"],after["reserved_units"])
        self.assertEqual(before["committed_units"],after["committed_units"])

    def test_exit_cost_buffer_is_not_available_to_another_strategy_after_entry_fills(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_FILL"))
        self.observe()
        denied=self.manager.reserve(self.request("SIM_SPEND_EXIT_BUFFER",symbol="ETHUSDT",principal=500*U,fee=0,risk=U))
        self.assertEqual(denied["reason"],"EXPLICIT_SIMULATION_BUDGET_EXCEEDED")
        self.assertEqual(self.assertConserved()["reserved_units"],U)
        accepted=self.manager.reserve(self.request("SIM_USE_ONLY_FREE",symbol="ETHUSDT",principal=499*U,fee=0,risk=U))
        self.assertTrue(accepted["accepted"])

    def test_smaller_final_fill_releases_unused_principal_but_keeps_exit_buffer(self):
        self.manager.reserve(self.request());self.submit()
        result=self.manager.reconcile(self.event("SIM_SMALL_FINAL",filled=40*U,entry=400000))
        self.assertEqual(result["released_units"],60*U)
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["reserved_units"],1_600_000)
        self.assertEqual(snapshot["committed_units"],40*U)
        self.observe()
        # Future occupied capital is 40, not the original entry maximum 100.
        accepted=self.manager.reserve(self.request("SIM_SECOND",symbol="ETHUSDT",principal=558*U,fee=0,risk=U))
        self.assertTrue(accepted["accepted"])
        self.assertEqual(self.assertConserved()["reserved_units"],559_600_000)

    def test_partial_fee_overrun_cannot_be_hidden_inside_unfilled_principal(self):
        self.manager.reserve(self.request());self.submit()
        result=self.manager.reconcile(self.event("SIM_PART_FEE_OVERRUN",state="PARTIAL",filled=40*U,entry=3*U))
        self.assertEqual(result["state"],"RECOVERY_REQUIRED")
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["reserved_units"],60*U)
        self.assertEqual(snapshot["committed_units"],40*U)
        self.assertEqual(snapshot["book_equity_units"],997*U)
        self.observe()
        self.assertEqual(self.manager.snapshot()["entry_gate"],"PENDING_ORDER_RECONCILIATION_REQUIRED")

    def test_residual_cancelled_partial_position_blocks_even_after_fresh_balance(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_PART",state="PARTIAL",filled=40*U,entry=400000))
        self.manager.reconcile(self.event("SIM_CANCELLED",state="CANCELLED",filled=40*U,entry=400000))
        self.observe()
        self.assertEqual(self.assertConserved()["requests"][0]["state"],"RECOVERY_REQUIRED")
        denied=self.manager.reserve(self.request("SIM_OTHER",symbol="ETHUSDT"))
        self.assertEqual(denied["reason"],"PENDING_ORDER_RECONCILIATION_REQUIRED")
        closed=self.manager.reconcile(self.event("SIM_RESIDUAL_CLOSED",state="CLOSED",filled=40*U,entry=400000,exit_fee=400000,pnl=-2*U,closed=True))
        self.assertEqual(closed["state"],"CLOSED")
        self.observe("SIM_BALANCE_CLOSED")
        self.assertTrue(self.manager.reserve(self.request("SIM_RETRY_OTHER",symbol="ETHUSDT"))["accepted"])

    def test_submission_rechecks_expiry_and_never_releases_reserved_capital(self):
        self.manager.reserve(self.request(expires=self.clock()+1))
        self.clock.advance(2)
        denied=self.submit()
        self.assertFalse(denied["accepted"])
        self.assertEqual(denied["reason"],"PROPOSAL_EXPIRED")
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["reserved_units"],102*U)
        self.assertEqual(snapshot["requests"][0]["state"],"RESERVED")
        self.assertIsNone(snapshot["requests"][0]["legs"][0]["client_id"])

    def test_submission_requires_fresh_balance_and_new_id_after_frozen_denial(self):
        self.manager.reserve(self.request(expires=self.clock()+1000))
        self.clock.advance(121)
        denied=self.submit()
        self.assertEqual(denied["reason"],"BALANCE_STALE_OR_FUTURE")
        self.observe()
        self.assertEqual(self.submit(),denied)  # Event IDs acknowledge frozen history.
        accepted=self.manager.mark_submitting("SIM_NEW_SUBMIT","SIM_REQ_1",actor="SIM_EXECUTOR",client_order_ids={"SIM_LEG_1":"SIM_ORDER_NEW"})
        self.assertTrue(accepted["accepted"])
        self.assertEqual(self.assertConserved()["reserved_units"],102*U)

    def test_separate_pending_submission_blocks_an_already_reserved_intent(self):
        self.manager.reserve(self.request())
        self.manager.reserve(self.request("SIM_REQ_2",symbol="ETHUSDT"))
        self.submit()
        denied=self.submit("SIM_REQ_2")
        self.assertEqual(denied["reason"],"PENDING_ORDER_RECONCILIATION_REQUIRED")
        self.assertEqual(self.assertConserved()["reserved_units"],204*U)

    def test_late_terminal_fee_fact_books_once_and_pnl_correction_requires_recovery(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_FILL",entry=500000))
        self.manager.reconcile(self.event("SIM_CLOSE",state="CLOSED",entry=500000,exit_fee=500000,pnl=-3*U,closed=True))
        late=self.event("SIM_LATE_FEE",state="CLOSED",entry=500000,exit_fee=1_250_000,pnl=-3*U,closed=True)
        result=self.manager.reconcile(late)
        self.assertEqual(result["fees_delta_units"],750000)
        self.assertEqual(result["pnl_delta_units"],0)
        self.assertEqual(self.manager.reconcile(late),result)
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["free_units_signed"],995_250_000)
        self.assertEqual(snapshot["reserved_units"]+snapshot["committed_units"],0)
        self.assertEqual(snapshot["realized_pnl_units"],-3*U)
        changed=self.manager.reconcile(replace(late,event_id="SIM_CONTRADICTORY_PNL",cumulative_realized_pnl_units=-4*U))
        self.assertEqual(changed["state"],"RECOVERY_REQUIRED")
        self.assertEqual(self.assertConserved()["free_units_signed"],995_250_000)
        self.assertIsNotNone(self.manager.snapshot()["entry_gate"])

    def test_two_leg_terminal_losses_and_fees_reconcile_without_netting_cost_buffers(self):
        legs=(LegRequest("SIM_A","BTCUSDT","LONG","SPOT_REFERENCE",50*U,U,2*U),LegRequest("SIM_B","BTCUSDT","SHORT","FUTURES_REFERENCE",50*U,U,2*U))
        self.manager.reserve(self.request(legs=legs));self.submit(leg_ids=("SIM_A","SIM_B"))
        self.manager.reconcile(self.event("SIM_FILL_A",leg_id="SIM_A",filled=50*U,entry=500000))
        self.manager.reconcile(self.event("SIM_FILL_B",leg_id="SIM_B",filled=50*U,entry=500000))
        self.assertEqual(self.assertConserved()["reserved_units"],U)
        self.manager.reconcile(self.event("SIM_CLOSE_B",leg_id="SIM_B",state="CLOSED",filled=50*U,entry=500000,exit_fee=500000,pnl=10*U,closed=True))
        halfway=self.assertConserved()
        self.assertEqual(halfway["reserved_units"],500000)
        self.assertEqual(halfway["committed_units"],50*U)
        self.assertEqual(halfway["requests"][0]["state"],"PARTIAL")
        self.manager.reconcile(self.event("SIM_CLOSE_A",leg_id="SIM_A",state="CLOSED",filled=50*U,entry=500000,exit_fee=500000,pnl=-15*U,closed=True))
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["free_units_signed"],993*U)
        self.assertEqual(snapshot["fees_paid_units"],2*U)
        self.assertEqual(snapshot["realized_pnl_units"],-5*U)
        self.assertEqual(snapshot["requests"][0]["state"],"CLOSED")

    def test_initial_funding_journal_uses_the_frozen_policy_not_public_mutable_metadata(self):
        manager=CapitalManagerShadow(self.directory/"SIM_FROZEN.simulation.sqlite3",wallet_name="SIM_FROZEN",scope=self.scope,limits=self.limits,clock=self.clock)
        manager.identity["policy"]["initial_balance_units"]=5000*U
        manager.initialize()
        with db_open(manager.path) as db:
            evidence=json.loads(db.execute("SELECT payload FROM events WHERE id='SIM_INITIAL_FUNDING'").fetchone()[0])
        self.assertEqual(evidence["identity"]["policy"]["initial_balance_units"],1000*U)
        self.assertEqual(self.assertConserved(manager)["book_equity_units"],1000*U)

    def test_cancel_before_submission_cannot_authorize_a_fill_fact(self):
        self.manager.reserve(self.request())
        self.manager.request_cancel("SIM_CANCEL_INTENT","SIM_REQ_1",actor="SIM_ACTOR")
        before=self.assertConserved()
        result=self.manager.reconcile(self.event("SIM_FILL_WITHOUT_INTENT"))
        self.assertEqual(result["reason"],"CONTRADICTORY_SIMULATED_RECONCILIATION")
        after=self.assertConserved()
        self.assertEqual(after["reserved_units"],before["reserved_units"])
        self.assertEqual(after["committed_units"],0)
        self.assertEqual(after["fees_paid_units"],0)

    def test_fill_observed_before_the_durable_submission_cannot_change_money(self):
        self.manager.reserve(self.request())
        self.clock.advance(10)
        self.submit()
        result=self.manager.reconcile(self.event("SIM_PRE_INTENT_FILL",at=self.clock()-1))
        self.assertEqual(result["state"],"RECOVERY_REQUIRED")
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["reserved_units"],102*U)
        self.assertEqual(snapshot["committed_units"],0)

    def test_unfilled_cancelled_leg_cannot_mint_positive_or_negative_realized_pnl(self):
        self.manager.reserve(self.request());self.submit()
        for event_id,pnl in (("SIM_FAKE_PROFIT",10*U),("SIM_FAKE_LOSS",-10*U)):
            result=self.manager.reconcile(self.event(event_id,state="CLOSED",filled=0,entry=0,pnl=pnl,closed=True))
            self.assertEqual(result["state"],"RECOVERY_REQUIRED")
            snapshot=self.assertConserved()
            self.assertEqual(snapshot["book_equity_units"],1000*U)
            self.assertEqual(snapshot["reserved_units"],102*U)
            self.assertEqual(snapshot["realized_pnl_units"],0)

    def test_unique_client_intent_failure_rolls_back_all_legs_and_journal(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_FILLED"))
        self.observe()
        legs=(LegRequest("SIM_C","ETHUSDT","LONG","SPOT_REFERENCE",U,1,1),LegRequest("SIM_D","ETHUSDT","SHORT","FUTURES_REFERENCE",U,1,1))
        self.manager.reserve(self.request("SIM_SECOND",legs=legs))
        before=fingerprint(self.path)
        with self.assertRaises(sqlite3.IntegrityError):
            self.manager.mark_submitting("SIM_ATOMIC_SUBMIT","SIM_SECOND",actor="SIM_EXECUTOR",client_order_ids={"SIM_C":"SIM_NEW_ID","SIM_D":"SIM_ORDER_SIM_REQ_1SIM_LEG_1"})
        self.assertEqual(fingerprint(self.path),before)
        request=next(row for row in self.assertConserved()["requests"] if row["id"]=="SIM_SECOND")
        self.assertEqual(request["state"],"RESERVED")
        self.assertTrue(all(leg["client_id"] is None for leg in request["legs"]))

    def test_cancelled_then_unknown_cannot_revive_capital_or_steal_successor_asset_lock(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_CANCEL_FINAL",state="CANCELLED",filled=0,entry=0))
        self.assertTrue(self.manager.reserve(self.request("SIM_REQ_2",strategy="SIM_PULSE",principal=598*U))["accepted"])
        self.submit("SIM_REQ_2")
        self.manager.reconcile(self.event("SIM_SECOND_FILL",request_id="SIM_REQ_2",filled=598*U))
        before=self.assertConserved()
        unknown=self.manager.reconcile(self.event("SIM_OLD_UNKNOWN",state="UNKNOWN",filled=0,entry=0))
        self.assertEqual(unknown["state"],"RECOVERY_REQUIRED")
        late=self.manager.reconcile(self.event("SIM_OLD_LATE_FILL"))
        self.assertEqual(late["reason"],"TERMINAL_SIMULATION_FACT_DIVERGENCE")
        after=self.assertConserved()
        for key in ("book_equity_units","committed_units","reserved_units","fees_paid_units"):
            self.assertEqual(before[key],after[key])
        self.assertLessEqual(after["committed_units"]+after["reserved_units"],600*U)
        self.observe()
        self.assertEqual(self.manager.snapshot()["entry_gate"],"PENDING_ORDER_RECONCILIATION_REQUIRED")
        with db_open(self.path) as db:
            self.assertEqual(db.execute("SELECT request_id FROM asset_locks WHERE symbol='BTCUSDT'").fetchone()[0],"SIM_REQ_2")
            self.assertEqual(db.execute("SELECT terminal_state,terminal_filled FROM legs WHERE request_id='SIM_REQ_1'").fetchone(),("CANCELLED",0))

    def test_final_partial_quantity_survives_unknown_restart_and_cannot_increase(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_FINAL_SMALL",filled=40*U,entry=400000))
        self.manager.reconcile(self.event("SIM_OLD_UNKNOWN",state="UNKNOWN",filled=40*U,entry=400000))
        restarted=self.new_manager();restarted.initialize()
        restarted.recover("SIM_RESTART",actor="SIM_RECOVERY")
        before=self.assertConserved(restarted)
        late=restarted.reconcile(self.event("SIM_MORE_THAN_FINAL",filled=60*U,entry=600000))
        self.assertEqual(late["state"],"RECOVERY_REQUIRED")
        after=self.assertConserved(restarted)
        self.assertEqual(after["committed_units"],40*U)
        self.assertEqual(after["reserved_units"],1_600_000)
        self.assertEqual(after["fees_paid_units"],before["fees_paid_units"])
        with db_open(self.path) as db:
            self.assertEqual(db.execute("SELECT terminal_state,terminal_filled FROM legs").fetchone(),("FILLED",40*U))

    def test_closed_pnl_cannot_change_through_unknown_even_while_other_leg_is_open(self):
        legs=(LegRequest("SIM_A","BTCUSDT","LONG","SPOT_REFERENCE",50*U,U,2*U),LegRequest("SIM_B","ETHUSDT","SHORT","FUTURES_REFERENCE",50*U,U,2*U))
        self.manager.reserve(self.request(legs=legs));self.submit(leg_ids=("SIM_A","SIM_B"))
        for leg_id in ("SIM_A","SIM_B"):
            self.manager.reconcile(self.event("SIM_FILL_"+leg_id,leg_id=leg_id,filled=50*U,entry=500000))
        self.manager.reconcile(self.event("SIM_CLOSE_A",leg_id="SIM_A",state="CLOSED",filled=50*U,entry=500000,exit_fee=500000,pnl=-2*U,closed=True))
        before=self.assertConserved()
        self.manager.reconcile(self.event("SIM_UNKNOWN_A",leg_id="SIM_A",state="UNKNOWN",filled=50*U,entry=500000,exit_fee=500000,pnl=-2*U,closed=True))
        changed=self.manager.reconcile(self.event("SIM_CORRECTED_A",leg_id="SIM_A",state="CLOSED",filled=50*U,entry=500000,exit_fee=500000,pnl=3*U,closed=True))
        self.assertEqual(changed["state"],"RECOVERY_REQUIRED")
        after=self.assertConserved()
        self.assertEqual(after["realized_pnl_units"],-2*U)
        self.assertEqual(after["book_equity_units"],before["book_equity_units"])
        self.assertEqual(after["committed_units"],50*U)

    def test_unknown_terminal_divergence_does_not_prevent_correct_hypothetical_close(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_FILLED"))
        self.manager.reconcile(self.event("SIM_UNKNOWN",state="UNKNOWN"))
        result=self.manager.reconcile(self.event("SIM_SAFE_CLOSE",state="CLOSED",closed=True,exit_fee=U,pnl=-5*U))
        self.assertEqual(result["state"],"CLOSED")
        snapshot=self.assertConserved()
        self.assertEqual(snapshot["committed_units"]+snapshot["reserved_units"],0)
        self.assertEqual(snapshot["free_units_signed"],993*U)

    def test_balance_before_current_financial_epoch_cannot_certify_a_zero_fee_fill(self):
        self.manager.reserve(self.request())
        self.clock.advance(10)
        self.submit()
        self.manager.reconcile(self.event("SIM_ZERO_FEE_FILL",entry=0))
        old=self.observe("SIM_PRE_FILL_BALANCE",at=NOW,units=1000*U)
        self.assertFalse(old["accepted"])
        self.assertEqual(self.assertConserved()["entry_gate"],"BALANCE_UNKNOWN_OR_CHANGED")
        self.assertFalse(self.manager.reserve(self.request("SIM_OLD_BALANCE_ENTRY",symbol="ETHUSDT"))["accepted"])
        self.assertTrue(self.observe("SIM_CURRENT_BALANCE")["accepted"])
        self.assertTrue(self.manager.reserve(self.request("SIM_FRESH_ENTRY",symbol="ETHUSDT"))["accepted"])

    def test_financial_epoch_timestamp_survives_restart_and_late_fee(self):
        self.manager.reserve(self.request());self.submit()
        self.manager.reconcile(self.event("SIM_FILLED"))
        old_at=self.clock()
        self.clock.advance(5)
        self.manager.reconcile(self.event("SIM_LATE_FEE",entry=1_500_000))
        restarted=self.new_manager();restarted.initialize()
        result=restarted.observe_balance("SIM_BEFORE_FEE",actor="SIM_OBSERVER",balance_units=998_500_000,observed_at=old_at,known=True,pending_orders_complete=True)
        self.assertFalse(result["accepted"])
        snapshot=self.assertConserved(restarted)
        self.assertEqual(snapshot["entry_gate"],"BALANCE_UNKNOWN_OR_CHANGED")
        self.assertEqual(snapshot["balance_evidence"]["epoch_at"],old_at+5)

    def test_no_broker_ai_network_or_existing_ledger_imports(self):
        from trader import capital_manager_shadow as module
        tree=ast.parse(Path(module.__file__).read_text())
        imports=[node.module or "" for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
        self.assertFalse(any(any(part in name for part in ("trader","openai","urllib","socket","requests")) for name in imports))


if __name__=="__main__":unittest.main(verbosity=2)
