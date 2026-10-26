"""Prepared common entry protocol on private synthetic SQLite files only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from trader.central_admission import (
    AdmissionError, AdmissionFacts, AdmissionPolicy, Baseline, CentralAdmission,
    EntryProposal, OperatingCapability, PositionFact, Reconciliation, Scope,
    simulation_capability,
)


U=1_000_000
NOW=datetime(2026,10,24,12,tzinfo=UTC).timestamp()


class Clock:
    def __init__(self): self.value=NOW
    def __call__(self): return self.value


def policy():
    return AdmissionPolicy("EXPLICIT_POLICY","SYNTHETIC_APPROVAL",NOW-10,
        1000*U,900*U,30*U,30*U,10,2000,
        (("SPOT",900*U,900*U,30*U),("FUTURES",900*U,900*U,30*U)),
        (("BTCUSDT",900*U,30*U),("ETHUSDT",900*U,30*U)),
        (("CRYPTO_FACTOR",900*U,30*U),),100*U,200*U,150*U,
        500_000,750_000,2*U,30,60,20,20,15)


def baselines(at=NOW,value=1000*U):
    day=datetime.fromtimestamp(at,UTC).replace(hour=0,minute=0,second=0,microsecond=0)
    week=day-timedelta(days=day.weekday())
    return (Baseline("DAY",day.timestamp(),value,"DAY_"+day.strftime("%Y%m%d")),
            Baseline("WEEK",week.timestamp(),value,"WEEK_"+week.strftime("%Y%m%d")))


def facts(scope, *, at=NOW, evidence="ACCOUNT_CUT_1", equity=1000*U, cashflow=0,
          free=None, committed=0, positions=(), baseline=None):
    if free is None: free=max(0,equity-committed)
    return AdmissionFacts(scope,"SYNTHETIC_ACCOUNT_SOURCE",evidence,at,at,
        equity,cashflow,"CASHFLOW_ANCHOR",free,committed,True,True,True,True,True,True,True,
        baselines(at) if baseline is None else baseline,positions)


def proposal(scope, *, identifier="PROPOSAL_1",symbol="BTCUSDT",engine="SPOT",
             gross=100*U,risk=5*U,at=NOW,direction="LONG"):
    return EntryProposal(identifier,scope,engine,symbol,direction,gross,gross,2*U,
        risk,1000,"CRYPTO_FACTOR",at,at+60,10,10,5,1000*U,True,True,True,"STRATEGY_V1","a"*64)


class CentralAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"central-admission-synthetic.sqlite3"
        self.scope=Scope("SYNTHETIC_ACCOUNT","SHADOW","USDT")
        self.policy=policy(); self.clock=Clock()
        self.flow=self.make(); self.flow.initialize()

    def make(self, **kwargs):
        return CentralAdmission(self.path,scope=self.scope,policy=self.policy,clock=self.clock,**kwargs)

    def cap(self): return simulation_capability(self.scope,self.policy,expires_at=self.clock()+3600)

    def reserve(self, p=None, f=None, event="RESERVE_1"):
        return self.flow.assess_and_reserve(p or proposal(self.scope),f or facts(self.scope),
            event_id=event,capability=self.cap())

    def claim(self, event="CLAIM_1",f=None):
        return self.flow.claim("PROPOSAL_1",f or facts(self.scope),event_id=event,capability=self.cap())

    def reconcile(self, state, *, event="RECON_1",filled=100*U,complete=True,closed=False,siblings=False):
        return self.flow.reconcile(Reconciliation(event,"PROPOSAL_1","SYNTHETIC_RECONCILER",event+"_EVIDENCE",
            self.clock(),self.scope,state,filled,complete,closed,siblings))

    def test_observe_persists_no_reservations_or_claims_and_survives_restart(self):
        result=self.flow.observe(proposal(self.scope),facts(self.scope),event_id="OBS_1")
        self.assertTrue(result["accepted"])
        self.assertFalse(result["reservation_created"])
        self.assertEqual(result["mode"],"SHADOW")
        restarted=self.make(); restarted.initialize()
        snapshot=restarted.snapshot()
        self.assertEqual(snapshot["reserved_units"],0)
        self.assertEqual(snapshot["claim_count"],0)
        self.assertEqual(snapshot["event_count"],1)
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["can_veto_operating_engines"])
        self.assertTrue(result["protective_exits_independent"])

    def test_explicit_integer_immutable_policy_and_exact_principal_cost_binding(self):
        with self.assertRaises(FrozenInstanceError): self.policy.capital_budget_units=2000*U
        with self.assertRaises(AdmissionError): replace(self.policy,daily_loss_limit_units=True)
        with self.assertRaises(AdmissionError): replace(self.policy,engine_limits=(("SPOT",2000*U,900*U,30*U),))
        with self.assertRaises(AdmissionError): replace(proposal(self.scope),principal_units=101*U)
        with self.assertRaises(AdmissionError): replace(proposal(self.scope),cost_buffer_units=1)
        with self.assertRaises(AdmissionError): replace(proposal(self.scope),inclusive_stop_risk_units=1)
        with self.assertRaises(AdmissionError): replace(proposal(self.scope),direction="SHORT")

    def test_store_rejects_changed_policy_scope_or_foreign_schema_without_adoption(self):
        with self.assertRaises(AdmissionError): CentralAdmission(self.path,scope=self.scope,
            policy=replace(self.policy,daily_loss_limit_units=101*U)).initialize()
        with self.assertRaises(AdmissionError): CentralAdmission(self.path,scope=replace(self.scope,environment="PAPER"),policy=self.policy).initialize()
        foreign=Path(self.temp.name)/"central-admission-foreign.sqlite3"
        with closing(sqlite3.connect(foreign)) as db:
            db.execute("CREATE TABLE financial_history(value INTEGER)"); db.commit()
        with self.assertRaises(AdmissionError): CentralAdmission(foreign,scope=self.scope,policy=self.policy).initialize()
        with closing(sqlite3.connect(foreign)) as db: self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[("financial_history",)])

    def test_simulation_claim_single_replay_restart_never_grants_submission(self):
        self.assertTrue(self.reserve()["accepted"])
        first=self.claim()
        self.assertTrue(first["new_claim_created"])
        self.assertFalse(first["submission_permitted"])
        replay=self.claim()
        self.assertEqual(replay["claim_id"],first["claim_id"])
        self.assertFalse(replay["new_claim_created"])
        restarted=self.make(); restarted.initialize()
        repeated=restarted.claim("PROPOSAL_1",facts(self.scope),event_id="CLAIM_2",capability=self.cap())
        self.assertFalse(repeated["submission_permitted"])
        self.assertEqual(restarted.snapshot()["claim_count"],1)

    def test_absent_capability_never_reserves_even_valid_shadow_proposal(self):
        with self.assertRaises(AdmissionError): self.flow.assess_and_reserve(proposal(self.scope),facts(self.scope),event_id="R")
        self.assertEqual(self.flow.snapshot()["reserved_units"],0)

    def test_operating_capability_requires_external_verification_and_exact_terms(self):
        for environment in ("SPOT_TESTNET","FUTURES_DEMO","SPOT_LIVE","FUTURES_LIVE"):
            with self.subTest(environment=environment):
                scope=replace(self.scope,environment=environment)
                path=Path(self.temp.name)/("central-admission-"+environment+".sqlite3")
                p=proposal(scope); f=facts(scope)
                grant=OperatingCapability(scope,self.policy.fingerprint,p.fingerprint,"OWNER_APPROVAL",NOW-1,NOW+300,"TEST_PROOF_ONLY")
                absent=CentralAdmission(path,scope=scope,policy=self.policy,clock=self.clock); absent.initialize()
                with self.assertRaises(AdmissionError): absent.assess_and_reserve(p,f,event_id="R",capability=grant)
                calls=[]
                def verifier(capability, **bindings):
                    calls.append(bindings)
                    return capability.proof=="TEST_PROOF_ONLY" and capability.approval_id=="OWNER_APPROVAL"
                active=CentralAdmission(path,scope=scope,policy=self.policy,clock=self.clock,capability_verifier=verifier)
                self.assertTrue(active.assess_and_reserve(p,f,event_id="R",capability=grant)["accepted"])
                sent=active.claim(p.proposal_id,f,event_id="C",capability=grant)
                self.assertTrue(sent["new_claim_created"])
                self.assertFalse(sent["submission_permitted"])
                self.assertTrue(sent["claim_ready_for_transport"])
                handoff=active.consume_transport_grant(sent["claim_id"],p.execution_plan_fingerprint,f,event_id="H",capability=grant)
                self.assertTrue(handoff["transport_permitted"])
                self.assertFalse(active.consume_transport_grant(sent["claim_id"],p.execution_plan_fingerprint,f,event_id="H",capability=grant)["transport_permitted"])
                self.assertFalse(active.consume_transport_grant(sent["claim_id"],p.execution_plan_fingerprint,f,event_id="H2",capability=grant)["transport_permitted"])
                self.assertTrue(active.get_claim(sent["claim_id"])["transport_consumed"])
                replay=active.claim(p.proposal_id,f,event_id="C",capability=grant)
                self.assertFalse(replay["submission_permitted"])
                self.assertEqual(calls[-1]["terms_fingerprint"],p.fingerprint)
                with self.assertRaises(AdmissionError): active.claim(p.proposal_id,f,event_id="C2",capability=replace(grant,terms_fingerprint="a"*64))
                with self.assertRaises(AdmissionError): simulation_capability(scope,self.policy,expires_at=NOW+300)

    def test_operating_revocation_failure_or_exception_rechecked_at_claim(self):
        scope=replace(self.scope,environment="SPOT_LIVE")
        p=proposal(scope); f=facts(scope); enabled=[True]
        capability=OperatingCapability(scope,self.policy.fingerprint,p.fingerprint,"OWNER_APPROVAL",NOW-1,NOW+300,"OPAQUE")
        def verifier(*args,**kwargs): return enabled[0]
        flow=CentralAdmission(Path(self.temp.name)/"central-admission-live.sqlite3",scope=scope,
            policy=self.policy,clock=self.clock,capability_verifier=verifier); flow.initialize()
        flow.assess_and_reserve(p,f,event_id="R",capability=capability)
        enabled[0]=False
        with self.assertRaises(AdmissionError): flow.claim(p.proposal_id,f,event_id="C",capability=capability)
        self.assertEqual(flow.snapshot()["claim_count"],0)
        def broken(*args,**kwargs): raise RuntimeError("SECRET_MUST_NOT_PROPAGATE")
        flow.capability_verifier=broken
        with self.assertRaisesRegex(AdmissionError,"^OPERATING_CAPABILITY_VERIFICATION_FAILED$"):
            flow.claim(p.proposal_id,f,event_id="C",capability=capability)

    def race(self, p1,p2):
        barrier=threading.Barrier(2)
        def run(item):
            index,p=item
            peer=self.make(); peer.initialize(); barrier.wait(timeout=10)
            return peer.assess_and_reserve(p,facts(self.scope),event_id="RACE_"+str(index),capability=self.cap())
        with ThreadPoolExecutor(max_workers=2) as pool: return list(pool.map(run,enumerate((p1,p2))))

    def test_concurrent_engines_cannot_use_same_free_capital(self):
        self.policy=replace(self.policy,capital_budget_units=600*U,
            engine_limits=(("SPOT",600*U,900*U,30*U),("FUTURES",600*U,900*U,30*U)))
        self.path=Path(self.temp.name)/"central-admission-concurrent.sqlite3"
        self.flow=self.make(); self.flow.initialize()
        results=self.race(proposal(self.scope,gross=400*U),proposal(self.scope,identifier="PROPOSAL_2",engine="FUTURES",symbol="ETHUSDT",gross=400*U))
        self.assertEqual(sum(x["accepted"] for x in results),1)
        self.assertIn("INSUFFICIENT_UNRESERVED_CAPITAL",next(x["reasons"] for x in results if not x["accepted"]))
        self.assertEqual(self.flow.snapshot()["reserved_units"],402*U)

    def test_gross_and_stop_risk_checked_with_reservation_inside_same_transaction(self):
        results=self.race(proposal(self.scope,gross=100*U,risk=20*U),proposal(self.scope,identifier="PROPOSAL_2",engine="FUTURES",symbol="ETHUSDT",gross=100*U,risk=20*U))
        self.assertEqual(sum(x["accepted"] for x in results),1)
        self.assertIn("GLOBAL_STOP_RISK_LIMIT",next(x["reasons"] for x in results if not x["accepted"]))
        self.assertEqual(self.flow.snapshot()["stop_risk_units"],20*U)

    def test_claim_race_durable_one_intention(self):
        self.reserve(); barrier=threading.Barrier(2)
        def run(i):
            flow=self.make(); barrier.wait(timeout=10)
            return flow.claim("PROPOSAL_1",facts(self.scope),event_id="CLAIM_RACE_"+str(i),capability=self.cap())
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,range(2)))
        self.assertEqual(sum(x["new_claim_created"] for x in results),1)
        self.assertEqual(self.flow.snapshot()["claim_count"],1)

    def test_unknown_partial_and_expiry_never_release_original_risk_or_principal(self):
        self.reserve(); self.claim()
        self.reconcile("PARTIAL",filled=25*U,complete=False)
        self.assertEqual(self.flow.snapshot()["gross_units"],100*U)
        self.assertEqual(self.flow.snapshot()["stop_risk_units"],5*U)
        self.assertEqual(self.flow.snapshot()["reserved_units"],102*U)
        self.reconcile("UNKNOWN",event="RECON_UNKNOWN",filled=25*U,complete=False)
        other=proposal(self.scope,identifier="PROPOSAL_2",symbol="ETHUSDT")
        result=self.reserve(other,event="RESERVE_2")
        self.assertFalse(result["accepted"])
        self.assertIn("UNRECONCILED_MANAGED_ORDER",result["reasons"])
        self.clock.value+=3600
        self.assertEqual(self.make().snapshot()["reserved_units"],102*U)

    def test_complete_terminal_reconciliation_releases_only_after_closed_and_siblings_clear(self):
        self.reserve(); self.claim()
        self.reconcile("PARTIAL",filled=25*U,complete=False)
        rejected=self.reconcile("CLOSED",event="CLOSE_BAD",filled=25*U,closed=True,siblings=False)
        self.assertFalse(rejected["reservation_released"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],102*U)
        result=self.reconcile("CLOSED",event="CLOSE_CONFIRMED",filled=25*U,closed=True,siblings=True)
        self.assertTrue(result["reservation_released"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],0)
        # Resolution does not silently clear the earlier evidence dispute.
        self.assertEqual(self.flow.snapshot()["state"],"RECOVERY_REQUIRED")

    def test_filled_order_cannot_release_via_cancel_or_reopen_after_terminal(self):
        self.reserve(); self.claim()
        invalid=self.reconcile("CANCELLED",closed=True,siblings=True)
        self.assertIn("FILLED_ORDER_CANNOT_RELEASE_AS_CANCELLED",invalid["reasons"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],102*U)
        self.reconcile("CLOSED",event="VALID_CLOSE",closed=True,siblings=True)
        repeated=self.reconcile("OPEN",event="LATE_OPEN")
        self.assertIn("TERMINAL_STATE_CONTRADICTION",repeated["reasons"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],0)

    def test_never_submitted_reservation_requires_confirmed_cancel_not_timeout(self):
        self.reserve(); self.clock.value+=61
        fresh=facts(self.scope,at=self.clock(),evidence="FRESH")
        rejected=self.claim(f=fresh)
        self.assertFalse(rejected["accepted"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],102*U)
        result=self.reconcile("CANCELLED",filled=0,closed=True,siblings=True)
        self.assertTrue(result["reservation_released"])

    def test_losses_latch_atomically_even_when_proposal_rejected_and_survive_restart(self):
        loss=facts(self.scope,equity=890*U)
        result=self.reserve(f=loss)
        self.assertFalse(result["accepted"])
        self.assertIn("DAILY_LOSS_LATCH",result["reasons"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],0)
        restarted=self.make(); restarted.initialize()
        self.assertEqual(restarted.snapshot()["losses"]["daily_loss"],110*U)
        self.assertIsNotNone(restarted.snapshot()["losses"]["day_latch"])
        rebound=facts(self.scope,at=NOW+1,evidence="REBOUND",equity=1000*U)
        self.clock.value+=1
        self.assertFalse(self.reserve(f=rebound,event="AFTER_REBOUND")["accepted"])

    def test_weekly_and_drawdown_latches_preserve_peak_after_deposit(self):
        self.flow.observe(proposal(self.scope),facts(self.scope),event_id="OPEN")
        self.clock.value+=1
        deposit=facts(self.scope,at=self.clock(),evidence="DEPOSIT",equity=1300*U,cashflow=300*U)
        self.flow.observe(proposal(self.scope,at=self.clock()),deposit,event_id="DEPOSIT_OBS")
        self.assertEqual(self.flow.snapshot()["losses"]["peak"],1000*U)
        self.assertEqual(self.flow.snapshot()["losses"]["drawdown"],0)
        self.clock.value+=1
        loss=facts(self.scope,at=self.clock(),evidence="LOSS",equity=1050*U,cashflow=300*U)
        result=self.flow.observe(proposal(self.scope,at=self.clock()),loss,event_id="LOSS_OBS")
        self.assertIn("WEEKLY_LOSS_LATCH",result["reasons"])
        self.assertIn("DRAWDOWN_LATCH",result["reasons"])
        self.assertEqual(self.flow.snapshot()["losses"]["drawdown"],250*U)

    def test_period_change_needs_new_complete_baseline_not_calendar_only(self):
        self.reserve(f=facts(self.scope,equity=890*U))
        self.clock.value+=86400
        current=proposal(self.scope,at=self.clock())
        missing=facts(self.scope,at=self.clock(),evidence="NEXT_DAY",equity=890*U,baseline=())
        result=self.flow.observe(current,missing,event_id="MISSING_BASELINE")
        self.assertIn("DAY_BASELINE_MISSING",result["reasons"])
        self.assertIsNotNone(self.flow.snapshot()["losses"]["day_latch"])
        new=(baselines(self.clock(),890*U)[0],)
        complete=facts(self.scope,at=self.clock(),evidence="COMPLETE_NEXT_DAY",equity=890*U,baseline=new)
        self.flow.acknowledge_recovery(complete,actor="SIM_OWNER",event_id="ACK",capability=self.cap())
        self.assertIsNone(self.flow.snapshot()["losses"]["day_latch"])
        self.assertEqual(self.flow.snapshot()["losses"]["weekly_loss"],110*U)

    def test_duplicate_fact_does_not_refresh_cut_and_changed_fact_latches_recovery(self):
        p=proposal(self.scope); f=facts(self.scope)
        self.flow.observe(p,f,event_id="OBS1")
        self.clock.value+=31
        result=self.flow.observe(proposal(self.scope,at=self.clock()),f,event_id="OBS2")
        self.assertIn("STALE_FUTURE_OR_REGRESSING_FACTS",result["reasons"])
        self.assertEqual(self.flow.snapshot()["last_observed_at"],NOW)
        self.clock.value=NOW+32
        changed=replace(f,observed_at=self.clock(),received_at=self.clock(),free_units=999*U)
        invalid=self.flow.observe(proposal(self.scope,at=self.clock()),changed,event_id="OBS3")
        self.assertIn("EVIDENCE_ID_CONFLICT",invalid["reasons"])

    def test_manual_halt_activation_survives_clock_regression_and_event_conflict(self):
        self.flow.observe(proposal(self.scope),facts(self.scope),event_id="REUSED")
        self.clock.value-=5
        result=self.flow.set_manual_halt(True,actor="OWNER",event_id="REUSED")
        self.assertIn("EVENT_ID_CONFLICT",result["reasons"])
        self.assertTrue(self.make().snapshot()["losses"]["manual"])

    def test_policy_limits_and_required_individual_reviews_are_not_overridden(self):
        for field,value,reason in (("individual_ai_review_allowed",False,"INDIVIDUAL_AI_REVIEW_REJECTED"),
                ("quantitative_review_allowed",False,"QUANTITATIVE_REVIEW_REJECTED"),
                ("protection_plan_verified",False,"PROTECTION_PLAN_UNVERIFIED"),
                ("available_depth_units",1,"INSUFFICIENT_VERIFIED_DEPTH"),
                ("spread_bps",16,"COST_OR_SPREAD_LIMIT")):
            with self.subTest(field=field):
                p=replace(proposal(self.scope),**{field:value})
                result=self.flow.observe(p,facts(self.scope),event_id="BAD_"+field)
                self.assertFalse(result["accepted"])
                self.assertIn(reason,result["reasons"])

    def test_opposite_positions_receive_no_hedge_credit_or_duplicate_asset_entry(self):
        self.reserve()
        opposite=proposal(self.scope,identifier="PROPOSAL_2",engine="FUTURES",direction="SHORT")
        result=self.reserve(opposite,event="RESERVE_2")
        self.assertFalse(result["accepted"])
        self.assertIn("ASSET_ALREADY_EXPOSED_OR_RESERVED",result["reasons"])
        self.assertEqual(result["after"]["gross_units"],200*U)
        self.assertEqual(result["after"]["stop_risk_units"],10*U)

    def test_managed_external_fill_link_prevents_double_subtract_but_retains_full_risk(self):
        self.reserve(); self.claim()
        self.reconcile("PARTIAL",filled=25*U,complete=False)
        position=PositionFact("EXCHANGE_POSITION","SPOT","BTCUSDT","LONG",25*U,2*U,
            1000,"CRYPTO_FACTOR",NOW,True,"PROPOSAL_1")
        # Exchange FREE has already lost 25 principal; the same 25 is credited
        # only against its exact durable filled amount, never against costs.
        f=facts(self.scope,evidence="MATCHED_POSITION",free=975*U,committed=25*U,positions=(position,))
        p=proposal(self.scope,identifier="PROPOSAL_2",symbol="ETHUSDT")
        result=self.reserve(p,f,event="RESERVE_2")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["before"]["gross_units"],100*U)
        self.assertEqual(result["available_units"],898*U)
        changed=replace(position,gross_units=26*U)
        bad=facts(self.scope,evidence="BAD_LINK",free=975*U,positions=(changed,))
        rejected=self.flow.observe(p,bad,event_id="LINK_CONTRADICTION")
        self.assertIn("MANAGED_POSITION_TERMS_CONTRADICTION",rejected["reasons"])

    def test_unprotected_or_stale_inventory_and_incomplete_account_fail_closed(self):
        position=PositionFact("EXTERNAL","FUTURES","ETHUSDT","SHORT",100*U,5*U,1000,"CRYPTO_FACTOR",NOW,False)
        result=self.flow.observe(proposal(self.scope),facts(self.scope,positions=(position,)),event_id="UNPROTECTED")
        self.assertIn("EXISTING_POSITION_STALE_OR_UNPROTECTED",result["reasons"])
        f=replace(facts(self.scope),orders_reconciled=False)
        result=self.flow.observe(proposal(self.scope),f,event_id="UNCERTAIN_ORDER")
        self.assertIn("ORDERS_RECONCILED_REQUIRED",result["reasons"])
        self.assertEqual(self.flow.snapshot()["state"],"RECOVERY_REQUIRED")

    def test_crash_rolls_back_reservation_loss_state_and_claim_together(self):
        def crash(stage): raise RuntimeError("SYNTHETIC_POWER_LOSS")
        faulty=self.make(fault_hook=crash)
        with self.assertRaises(RuntimeError): faulty.assess_and_reserve(proposal(self.scope),facts(self.scope),event_id="R",capability=self.cap())
        self.assertEqual(self.flow.snapshot()["reserved_units"],0)
        self.assertIsNone(self.flow.snapshot()["last_observed_at"])
        self.reserve()
        with self.assertRaises(RuntimeError): faulty.claim("PROPOSAL_1",facts(self.scope),event_id="C",capability=self.cap())
        self.assertEqual(self.make().snapshot()["claim_count"],0)
        self.assertTrue(self.claim()["new_claim_created"])

    def test_reused_reserve_event_is_idempotent_and_changed_terms_persist_dispute(self):
        first=self.reserve(); self.assertEqual(self.reserve(),first)
        changed=proposal(self.scope,risk=6*U)
        result=self.reserve(changed)
        self.assertIn("EVENT_ID_CONFLICT",result["reasons"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],102*U)
        self.assertEqual(self.make().snapshot()["state"],"RECOVERY_REQUIRED")

    def test_scope_never_sums_wallets_and_changed_cashflow_anchor_fails_closed(self):
        p=proposal(replace(self.scope,environment="PAPER"))
        result=self.flow.observe(p,facts(self.scope),event_id="WRONG_ENV")
        self.assertIn("PROPOSAL_SCOPE_MISMATCH",result["reasons"])
        self.flow.observe(proposal(self.scope),facts(self.scope),event_id="VALID")
        changed=replace(facts(self.scope,evidence="NEW_ANCHOR"),cashflow_anchor_id="DIFFERENT")
        result=self.flow.observe(proposal(self.scope),changed,event_id="ANCHOR_CHANGED")
        self.assertIn("CASHFLOW_ANCHOR_CHANGED",result["reasons"])

    def test_per_trade_stop_risk_cap_and_existing_exchange_capital_cannot_be_bypassed(self):
        self.policy=replace(self.policy,per_trade_stop_risk_limit_units=4*U)
        self.path=Path(self.temp.name)/"central-admission-per-trade.sqlite3"
        self.flow=self.make(); self.flow.initialize()
        result=self.reserve()
        self.assertIn("PER_TRADE_STOP_RISK_LIMIT",result["reasons"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],0)
        p=proposal(self.scope,risk=4*U)
        committed=facts(self.scope,evidence="OLD_COMMITMENTS",free=50*U,committed=950*U)
        result=self.reserve(p,committed,event="OVER_CAPITAL_BUDGET")
        self.assertIn("INSUFFICIENT_UNRESERVED_CAPITAL",result["reasons"])
        self.assertEqual(result["available_units"],50*U)

    def test_handoff_is_unique_across_threads_restart_and_exact_plan(self):
        self.reserve(); claim=self.claim(); barrier=threading.Barrier(2)
        with self.assertRaises(AdmissionError): self.flow.consume_transport_grant(claim["claim_id"],"b"*64,
            facts(self.scope),event_id="BAD_PLAN",capability=self.cap())
        def run(i):
            flow=self.make(); barrier.wait(timeout=10)
            return flow.consume_transport_grant(claim["claim_id"],"a"*64,facts(self.scope),
                event_id="HANDOFF_"+str(i),capability=self.cap())
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,range(2)))
        self.assertEqual(sum(x["new_grant_created"] for x in results),1)
        self.assertTrue(self.make().get_claim(claim["claim_id"])["transport_consumed"])
        self.assertEqual(self.make().snapshot()["active_tickets"][0]["state"],"UNKNOWN")
        self.assertEqual(self.make().snapshot()["reserved_units"],102*U)
        replay=self.make().consume_transport_grant(claim["claim_id"],"a"*64,facts(self.scope),event_id="AFTER_RESTART",capability=self.cap())
        self.assertFalse(replay["transport_permitted"])
        self.assertFalse(replay["new_grant_created"])

    def test_loss_arriving_after_claim_prevents_handoff_and_keeps_capital(self):
        self.reserve(); receipt=self.claim()
        self.clock.value+=1
        f=facts(self.scope,at=self.clock(),evidence="LOSS_AFTER_CLAIM",equity=890*U)
        rejected=self.flow.consume_transport_grant(receipt["claim_id"],"a"*64,f,event_id="HANDOFF_LOSS",capability=self.cap())
        self.assertFalse(rejected["transport_permitted"])
        self.assertIn("DAILY_LOSS_LATCH",rejected["reasons"])
        self.assertFalse(self.flow.get_claim(receipt["claim_id"])["transport_consumed"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],102*U)

    def test_manual_halt_after_claim_prevents_handoff_and_clearing_requires_capability(self):
        self.reserve(); receipt=self.claim()
        self.flow.set_manual_halt(True,actor="OWNER",event_id="HALT")
        with self.assertRaises(AdmissionError): self.flow.set_manual_halt(False,actor="OWNER",event_id="CLEAR")
        rejected=self.flow.consume_transport_grant(receipt["claim_id"],"a"*64,facts(self.scope),event_id="HANDOFF_HALTED",capability=self.cap())
        self.assertFalse(rejected["transport_permitted"])
        self.assertIn("MANUAL_ENTRY_HALT",rejected["reasons"])
        self.flow.set_manual_halt(False,actor="OWNER",event_id="CLEAR",capability=self.cap())
        self.assertFalse(self.flow.snapshot()["losses"]["manual"])

    def test_reconciliation_before_claim_cut_cannot_release_reservation(self):
        self.reserve(); self.clock.value+=1
        self.claim(f=facts(self.scope,at=self.clock(),evidence="AT_CLAIM"))
        bad=Reconciliation("TOO_EARLY","PROPOSAL_1","SOURCE","OLD_EVIDENCE",NOW,self.scope,
            "CANCELLED",0,True,True,True)
        result=self.flow.reconcile(bad)
        self.assertIn("RECONCILIATION_CUT_PRECEDES_CLAIM_OR_ACCEPTED_EVIDENCE",result["reasons"])
        self.assertFalse(result["reservation_released"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],102*U)

    def test_loss_observation_and_reserve_race_share_latch_transaction(self):
        barrier=threading.Barrier(2)
        def reserve():
            barrier.wait(timeout=10)
            return self.make().assess_and_reserve(proposal(self.scope),facts(self.scope),event_id="RACE_RESERVE",capability=self.cap())
        def loss():
            barrier.wait(timeout=10)
            return self.make().observe(proposal(self.scope),facts(self.scope,evidence="RACE_LOSS",equity=890*U),event_id="RACE_OBSERVE")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(reserve); second=pool.submit(loss)
            result=first.result(); second.result()
        snapshot=self.make().snapshot()
        self.assertIsNotNone(snapshot["losses"]["day_latch"])
        self.assertEqual(snapshot["reserved_units"],102*U if result["accepted"] else 0)
        if result["accepted"]:
            claimed=self.claim()
            self.assertFalse(claimed["accepted"])
            self.assertEqual(self.flow.snapshot()["claim_count"],0)

    def test_transport_nonce_is_recorded_exactly_once_and_safety_recovery_retains_capital(self):
        self.reserve(); receipt=self.claim()
        result=self.flow.consume_transport_grant(receipt["claim_id"],"a"*64,facts(self.scope),
            event_id="HANDOFF_EXPLICIT",capability=self.cap(),transport_nonce="TRANSPORT_NONCE_1")
        self.assertEqual(result["grant_nonce"],"TRANSPORT_NONCE_1")
        halt=self.flow.mark_recovery("PROPOSAL_1","NATIVE_STOP_NOT_VERIFIED",event_id="RECOVERY")
        self.assertFalse(halt["reservation_released"])
        snapshot=self.make().snapshot()
        self.assertEqual(snapshot["state"],"RECOVERY_REQUIRED")
        self.assertEqual(snapshot["reserved_units"],102*U)
        self.assertEqual(snapshot["active_tickets"][0]["state"],"RECOVERY_REQUIRED")
        with self.assertRaises(AdmissionError): self.flow.mark_recovery("PROPOSAL_1","provider error with secret",event_id="BAD")

    def test_operating_capability_expiring_inside_verifier_cannot_admit(self):
        scope=replace(self.scope,environment="SPOT_LIVE"); p=proposal(scope)
        grant=OperatingCapability(scope,self.policy.fingerprint,p.fingerprint,"OWNER",NOW-1,NOW+1,"OPAQUE")
        def delayed(*args,**kwargs):
            self.clock.value+=2
            return True
        flow=CentralAdmission(Path(self.temp.name)/"central-admission-expiring.sqlite3",scope=scope,
            policy=self.policy,clock=self.clock,capability_verifier=delayed); flow.initialize()
        with self.assertRaisesRegex(AdmissionError,"EXPIRED_DURING_VERIFICATION"):
            flow.assess_and_reserve(p,facts(scope),event_id="EXPIRED",capability=grant)
        self.assertEqual(flow.snapshot()["reserved_units"],0)

    def test_contradictory_account_capital_components_do_not_become_free_funds(self):
        f=facts(self.scope,free=1000*U,committed=100*U)
        result=self.reserve(f=f)
        self.assertIn("ACCOUNT_CAPITAL_COMPONENTS_EXCEED_EQUITY",result["reasons"])
        self.assertEqual(self.flow.snapshot()["reserved_units"],0)
        self.assertEqual(self.flow.snapshot()["state"],"RECOVERY_REQUIRED")


if __name__=="__main__": unittest.main()
