"""Synthetic isolated accounting/ownership/source failures; no trading or API calls."""
import copy
import importlib
import json
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


from trader.quant_shadow import QuantConfig, QuantShadowService, DB_NAME, pause_quant, quant_snapshot, replay_quant_decision
from trader.quant_public import QuantPublicFeed, ReferenceRateLimit, reference_json


NOW = 1_800_000_000.


class Clock:
    def __init__(self):
        self.now = NOW
    def __call__(self):
        return self.now


class Source:
    def __init__(self, clock):
        self.clock = clock
        self.rates = {"BTCUSDT": .01, "ETHUSDT": .0001, "SOLUSDT": .0001}
        self.spot = self.future = 100.
        self.stale = False
        self.history_extra = []
        self.missing_futures = False
    def __call__(self, now):
        markets = []
        for symbol in self.rates:
            old = now-100 if self.stale else now-1
            spot = {"symbol": symbol, "bid": self.spot-.01, "ask": self.spot+.01,
                    "bid_depth_usdt": 100000., "ask_depth_usdt": 100000., "at": old, "received_at": now}
            future = {**spot, "bid": self.future-.01, "ask": self.future+.01,
                      "mark_price": self.future, "observed_funding_rate": self.rates[symbol],
                      "next_funding_at": NOW+3600 if now < NOW+3600 else NOW+3600+28800,
                      "funding_interval_seconds": 28800.}
            history = [{"at": NOW-25200-i*28800, "received_at": NOW-25200-i*28800+1,
                        "rate": self.rates[symbol] if self.rates[symbol]>0 else .01, "mark_price": 100.} for i in range(8)]
            if symbol == "BTCUSDT":
                history += copy.deepcopy(self.history_extra)
            markets.append({"symbol": symbol, "spot": spot,
                            "futures": None if self.missing_futures else future, "history": history})
        return {"markets": markets, "sources": [{"id": "FIXTURE", "state": "READY", "at": now, "error": None}], "at": now}


class QuantLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.source = Source(self.clock)
        self.service = QuantShadowService(self.root, source=self.source, clock=self.clock)
        self.addCleanup(self.service.stop)
    def snapshot(self):
        return self.service.snapshot(now=self.clock())
    def database(self):
        db = sqlite3.connect(self.root/DB_NAME)
        self.addCleanup(db.close)
        return db
    def test_uninitialized_projection_never_creates_wallet(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["state"], "NOT_STARTED")
        self.assertIsNone(snapshot["performance"]["initial_capital"])
        self.assertFalse((self.root/DB_NAME).exists())
    def test_config_rejects_every_execution_mode_and_risk_raise(self):
        for settings in ({"mode": "LIVE"}, {"mode": "TESTNET"}, {"mode": "PAPER"},
                         {"risk_per_trade": .0026}, {"max_exposure_fraction": .16},
                         {"max_positions": 3}, {"fee_bps": 0}, {"slippage_bps": 0},
                         {"daily_loss_limit": .011}, {"weekly_loss_limit": .021},
                         {"virtual_margin_stress_fraction": .81},
                         {"initial_capital": float("nan")}, {"max_positions": True}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                QuantConfig(**settings)
    def test_shadow_opens_equal_quantity_two_legs_costs_and_full_collateral(self):
        self.assertTrue(self.service.tick())
        snapshot = self.snapshot()
        self.assertEqual(snapshot["state"], "SHADOW")
        self.assertFalse(snapshot["execution_enabled"])
        self.assertFalse(snapshot["promotion_allowed"])
        self.assertEqual(len(snapshot["positions"]), 1)
        pair = snapshot["positions"][0]
        self.assertEqual([leg["direction"] for leg in pair["legs"]], ["LONG", "SHORT"])
        self.assertEqual(pair["legs"][0]["quantity"], pair["legs"][1]["quantity"])
        self.assertTrue(all(leg["leverage"] == 1 for leg in pair["legs"]))
        self.assertFalse(pair["hedge_atomic"])
        self.assertGreater(snapshot["performance"]["collateral_usdt"], 50)
        self.assertGreater(snapshot["performance"]["costs_usdt"], 0)
        self.assertLess(snapshot["performance"]["equity"], 1000)
        self.assertEqual(snapshot["performance"]["simulated_funding_usdt"], 0)
        self.assertLessEqual(pair["risk_budget_usdt"], 2.5)
        self.assertLessEqual(snapshot["performance"]["gross_exposure_usdt"], 150)
    def test_duplicate_ticks_do_not_duplicate_positions_or_fees(self):
        self.service.tick()
        previous = self.snapshot()
        self.service.tick()
        following = self.snapshot()
        self.assertEqual(len(following["positions"]), 1)
        self.assertEqual(following["performance"], previous["performance"])
        self.assertEqual(self.database().execute("SELECT COUNT(*) FROM quant_decisions").fetchone()[0], 6)
    def test_restart_preserves_capital_positions_and_journal(self):
        self.service.tick()
        previous = self.snapshot()
        self.clock.now += 121
        successor = QuantShadowService(self.root, source=self.source, clock=self.clock)
        self.addCleanup(successor.stop)
        successor.initialize()
        self.assertTrue(successor.tick())
        following = successor.snapshot(now=self.clock())
        self.assertEqual(previous["positions"][0]["id"], following["positions"][0]["id"])
        self.assertEqual(previous["performance"]["costs_usdt"], following["performance"]["costs_usdt"])
        self.assertEqual(self.database().execute("SELECT COUNT(*) FROM quant_journal WHERE kind='COHORT_STARTED'").fetchone()[0], 1)
    def test_financial_hypothesis_change_rejected_without_reset(self):
        self.service.tick()
        successor = QuantShadowService(self.root, source=self.source, clock=self.clock,
                                      config=QuantConfig(initial_capital=2000))
        with self.assertRaisesRegex(ValueError, "cohort"):
            successor.initialize()
        self.assertEqual(self.snapshot()["performance"]["initial_capital"], 1000)
        self.assertEqual(len(self.snapshot()["positions"]), 1)
    def test_second_owner_cannot_mutate_ledger(self):
        self.service.tick()
        successor = QuantShadowService(self.root, source=self.source, clock=self.clock)
        successor.initialize()
        self.assertFalse(successor.tick())
        self.assertEqual(len(self.snapshot()["positions"]), 1)
    def test_concurrent_owners_acquire_one_atomic_shadow_lease(self):
        self.service.initialize()
        successor = QuantShadowService(self.root, source=self.source, clock=self.clock)
        successor.initialize()
        barrier = threading.Barrier(2)
        results = []
        def acquire(service):
            barrier.wait(timeout=2)
            results.append(service._lease(self.clock()))
        workers = [threading.Thread(target=acquire, args=(service,)) for service in (self.service,successor)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(3)
        self.assertEqual(sorted(results), [False, True])
    def test_same_process_start_does_not_create_duplicate_shadow_thread(self):
        self.assertTrue(self.service.start())
        successor = QuantShadowService(self.root, source=self.source, clock=self.clock)
        self.addCleanup(successor.stop)
        self.assertFalse(successor.start())
        deadline = time.monotonic()+3
        while time.monotonic() < deadline and self.snapshot()["state"] == "NOT_STARTED":
            time.sleep(.01)
        self.service.stop()
        self.assertFalse(self.service._thread.is_alive())
    def test_interrupted_open_rolls_back_wallet_pair_and_journal_together(self):
        module = sys.modules[QuantShadowService.__module__]
        original = module._journal
        def interrupted(db, now, kind, data, identity=None):
            if kind == "PAIR_OPENED_SIMULATION":
                raise RuntimeError("synthetic power interruption before atomic commit")
            return original(db, now, kind, data, identity)
        with patch.object(module, "_journal", interrupted), self.assertRaisesRegex(RuntimeError, "interruption"):
            self.service.tick()
        db = self.database()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM quant_positions").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT value FROM quant_meta WHERE key='wallet_balance'").fetchone()[0], "1000.0")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM quant_journal WHERE kind='PAIR_OPENED_SIMULATION'").fetchone()[0], 0)
        self.clock.now += 60
        self.service.tick()
        self.assertEqual(len(self.snapshot()["positions"]), 1)
    def test_expired_lease_after_source_cannot_commit_any_evidence_or_fill(self):
        self.service.initialize()
        def slow_source(now):
            result = self.source(now)
            self.clock.now += 121
            return result
        self.service.source = slow_source
        self.assertFalse(self.service.tick())
        self.assertEqual(self.database().execute("SELECT COUNT(*) FROM quant_sources").fetchone()[0], 0)
        self.assertEqual(self.snapshot()["performance"]["initial_capital"], 1000)
        self.assertEqual(len(self.snapshot()["positions"]), 0)
    def test_model_delay_expiring_lease_rolls_back_financial_transaction(self):
        def slow_model(*args):
            self.clock.now += 121
            return {"decision": "REJECT", "reason": "FIXTURE", "metrics": {}, "evidence": {}, "legs": []}
        self.service.model_funding = slow_model
        self.assertFalse(self.service.tick())
        db = self.database()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM quant_sources").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM quant_positions").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT value FROM quant_meta WHERE key='wallet_balance'").fetchone()[0], '1000.0')
    def test_stale_quotes_reject_and_hide_current_financial_values(self):
        self.service.tick()
        self.clock.now += 100
        self.source.stale = True
        self.service.tick()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["state"], "DEGRADED")
        self.assertIsNone(snapshot["performance"]["equity"])
        self.assertIsNone(snapshot["positions"][0]["legs"][0]["mark_price"])
        self.assertEqual(snapshot["performance"]["simulated_funding_usdt"], 0)
    def test_missing_one_leg_does_not_fabricate_hedge(self):
        self.source.missing_futures = True
        self.service.tick()
        self.assertEqual(self.snapshot()["positions"], [])
        self.assertEqual(self.snapshot()["state"], "DEGRADED")
    def test_pause_blocks_entries_and_protective_exit_continues(self):
        self.service.initialize()
        self.assertTrue(pause_quant(self.root, True))
        self.service.tick()
        self.assertEqual(self.snapshot()["positions"], [])
        self.assertEqual(self.snapshot()["state"], "PAUSED")
        pause_quant(self.root, False)
        self.clock.now += 60
        self.service.tick()
        self.assertEqual(len(self.snapshot()["positions"]), 1)
        pause_quant(self.root, True)
        self.source.rates["BTCUSDT"] = -.001
        self.clock.now += 60
        self.service.tick()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["positions"], [])
        self.assertEqual(snapshot["performance"]["closed_trades"], 1)
        self.assertLess(snapshot["performance"]["net_pnl"], 0)
    def test_kill_requests_hypothetical_exit_but_waits_for_fresh_prices(self):
        self.service.tick()
        self.service.kill_switch_path.write_text("stop", encoding="utf-8")
        self.clock.now += 60
        self.source.stale = True
        self.service.tick()
        self.assertEqual(len(self.snapshot()["positions"]), 1)
        self.source.stale = False
        self.clock.now += 60
        self.service.tick()
        self.assertEqual(self.snapshot()["positions"], [])
        self.assertEqual(self.snapshot()["state"], "PAUSED")
    def test_pair_stop_accounts_both_leg_costs_without_leverage_multiplier(self):
        self.service.tick()
        self.source.future = 120
        self.clock.now += 60
        self.service.tick()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["positions"], [])
        self.assertEqual(snapshot["performance"]["closed_trades"], 1)
        self.assertLess(snapshot["performance"]["net_pnl"], -2.5)
        self.assertGreater(snapshot["performance"]["drawdown_pct"], 0)
        # A gap can exceed the estimate; never claim a guaranteed maximum loss.
        record = json.loads(self.database().execute("SELECT data FROM quant_trades").fetchone()[0])
        self.assertEqual(record["reason"], "ESTIMATED_PAIR_STOP")
    def test_short_margin_stress_closes_even_when_spot_profit_offsets_pair_loss(self):
        self.service.tick()
        pause_quant(self.root,True)
        self.source.future = self.source.spot = 200.
        self.clock.now += 60
        self.service.tick()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["positions"],[])
        self.assertEqual(snapshot["performance"]["closed_trades"],1)
        record = json.loads(self.database().execute("SELECT data FROM quant_trades").fetchone()[0])
        self.assertEqual(record["reason"],"VIRTUAL_MARGIN_STRESS_EXIT")
        self.assertGreater(snapshot["performance"]["stress_costs_usdt"],0)
        self.assertAlmostEqual(record["stress_costs_usdt"],snapshot["performance"]["stress_costs_usdt"])
        self.assertAlmostEqual(snapshot["performance"]["net_pnl"],record["net_pnl_usdt"])
        self.assertGreater(snapshot["performance"]["costs_usdt"],snapshot["performance"]["stress_costs_usdt"])
        costs = snapshot["performance"]["stress_costs_usdt"]
        self.service.tick()
        self.assertEqual(self.snapshot()["performance"]["stress_costs_usdt"],costs)
        self.assertFalse(record["hedge_atomic"])
        self.assertIn("VIRTUAL_MARGIN_STRESS_PROXY_NOT_EXCHANGE_LIQUIDATION_MODEL",snapshot["limitations"])
    def test_margin_gap_stress_can_exceed_initial_risk_estimate(self):
        self.service.tick()
        self.source.future = self.source.spot = 1000.
        self.clock.now += 60
        self.service.tick()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["positions"],[])
        self.assertLess(snapshot["performance"]["net_pnl"],-2.5)
        self.assertGreater(snapshot["performance"]["stress_costs_usdt"],2.5)
    def test_margin_stress_exit_does_not_immediately_reopen_same_asset(self):
        self.service.tick()
        self.source.future = self.source.spot = 200.
        self.clock.now += 60
        self.service.tick()
        self.assertEqual(self.snapshot()["positions"],[])
        self.assertTrue(any(row["reason"] == "PROTECTIVE_EXIT_COOLDOWN" for row in self.snapshot()["decisions"]))
    def test_initialized_before_first_tick_risk_is_honestly_unknown(self):
        self.service.initialize()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["risk_halt"]["state"],"UNKNOWN")
        self.assertIsNone(snapshot["risk_halt"]["daily"]["baseline_at"])
        self.assertIsNone(snapshot["risk_halt"]["weekly"]["baseline_equity"])
    def test_projected_funding_never_booked_and_actual_held_event_exactly_once(self):
        self.service.tick()
        quantity = self.snapshot()["positions"][0]["legs"][0]["quantity"]
        self.assertEqual(self.snapshot()["performance"]["simulated_funding_usdt"], 0)
        self.clock.now = NOW+3601
        self.source.history_extra = [{"at": NOW+3600, "received_at": self.clock(), "rate": .01, "mark_price": 100.}]
        self.service.tick()
        once = self.snapshot()
        self.service.tick()
        twice = self.snapshot()
        self.assertAlmostEqual(once["performance"]["simulated_funding_usdt"], quantity*100*.01)
        self.assertEqual(once["performance"]["simulated_funding_usdt"], twice["performance"]["simulated_funding_usdt"])
        self.assertEqual(self.database().execute("SELECT COUNT(*) FROM quant_funding").fetchone()[0], 1)
        self.assertEqual(twice["funding"][0]["state"], "SETTLED_SIMULATION")
    def test_due_funding_without_authoritative_history_is_unknown_not_zero_net(self):
        self.service.tick()
        self.clock.now = NOW+3601
        self.service.tick()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["data_quality"]["funding"], "PENDING_AUTHORITATIVE_EVENTS")
        self.assertIsNone(snapshot["performance"]["net_pnl"])
    def test_authoritative_funding_received_after_close_updates_closed_simulation(self):
        self.service.tick()
        self.clock.now = NOW+3601
        self.source.rates["BTCUSDT"] = -.001
        self.service.tick()
        self.assertEqual(self.snapshot()["positions"], [])
        self.assertIsNone(self.snapshot()["performance"]["net_pnl"])
        self.clock.now += 60
        self.source.history_extra = [{"at": NOW+3600, "received_at": self.clock(), "rate": .01, "mark_price": 100.}]
        self.service.tick()
        snapshot = self.snapshot()
        self.assertIsNotNone(snapshot["performance"]["net_pnl"])
        self.assertGreater(snapshot["performance"]["simulated_funding_usdt"], 0)
        self.assertEqual(snapshot["performance"]["closed_trades"], 1)
    def test_historical_event_before_entry_is_never_retroactive_income(self):
        self.service.tick()
        self.clock.now += 60
        self.service.tick()
        self.assertEqual(self.snapshot()["performance"]["simulated_funding_usdt"], 0)
    def test_adverse_authoritative_funding_is_simulated_debit_not_projected_credit(self):
        self.service.tick()
        quantity = self.snapshot()["positions"][0]["legs"][0]["quantity"]
        self.clock.now = NOW+3601
        self.source.history_extra = [{"at": NOW+3600, "received_at": self.clock(), "rate": -.01, "mark_price": 100.}]
        self.service.tick()
        self.assertAlmostEqual(self.snapshot()["performance"]["simulated_funding_usdt"], -quantity)
    def test_conflicting_funding_history_rolls_back_without_double_cashflow(self):
        self.service.tick()
        self.clock.now = NOW+3601
        event = {"at": NOW+3600, "received_at": self.clock(), "rate": .01, "mark_price": 100.}
        self.source.history_extra = [event, {**event, "rate": -.01}]
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.service.tick()
        self.assertEqual(self.snapshot()["performance"]["simulated_funding_usdt"], 0)
    def test_core_quote_clock_skew_requires_real_receipt_before_decision(self):
        module = sys.modules[QuantShadowService.__module__]
        quote = self.source(self.clock())["markets"][0]["spot"]
        quote.update(at=self.clock()+2, received_at=self.clock())
        self.assertTrue(module._fresh_book(quote,self.clock()))
        quote["at"] = self.clock()+6
        self.assertFalse(module._fresh_book(quote,self.clock()))
        quote.update(at=self.clock(),received_at=self.clock()+1)
        self.assertFalse(module._fresh_book(quote,self.clock()))
    def test_daily_loss_halt_blocks_new_entries_and_keeps_protective_closes(self):
        self.service.tick()
        with closing(sqlite3.connect(self.root/DB_NAME)) as db, db:
            db.execute("UPDATE quant_meta SET value=CAST(value AS REAL)-20 WHERE key='wallet_balance'")
        self.source.future = 120
        self.clock.now += 60
        self.service.tick()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["risk_halt"]["state"], "HALTED")
        self.assertTrue(snapshot["risk_halt"]["daily"]["halted"])
        self.assertEqual(snapshot["positions"], [])
        self.assertEqual(snapshot["performance"]["closed_trades"], 1)
        self.source.future = 100
        self.clock.now += 60
        self.service.tick()
        self.assertEqual(self.snapshot()["positions"], [])
        self.assertTrue(any(row["reason"] == "DAILY_OR_WEEKLY_ENTRY_HALT" for row in self.snapshot()["decisions"]))
    def test_first_valid_midperiod_baseline_is_explicit_and_halt_latches(self):
        self.service.tick()
        risk = self.snapshot()["risk_halt"]
        self.assertEqual(risk["method"], "FIRST_VALID_LEDGER_EQUITY_WITHIN_UTC_PERIOD")
        self.assertNotEqual(risk["daily"]["baseline_at"],risk["daily"]["period_start"])
        with closing(sqlite3.connect(self.root/DB_NAME)) as db, db:
            db.execute("UPDATE quant_meta SET value=CAST(value AS REAL)-15 WHERE key='wallet_balance'")
        self.clock.now += 60
        self.service.tick()
        self.assertTrue(self.snapshot()["risk_halt"]["daily"]["halted"])
        with closing(sqlite3.connect(self.root/DB_NAME)) as db, db:
            db.execute("UPDATE quant_meta SET value=CAST(value AS REAL)+30 WHERE key='wallet_balance'")
        self.clock.now += 60
        self.service.tick()
        self.assertTrue(self.snapshot()["risk_halt"]["daily"]["halted"])
    def test_daily_period_reset_preserves_weekly_halt_and_unknown_marks_block(self):
        self.service.tick()
        with closing(sqlite3.connect(self.root/DB_NAME)) as db, db:
            db.execute("UPDATE quant_meta SET value=CAST(value AS REAL)-25 WHERE key='wallet_balance'")
        self.clock.now += 60
        self.service.tick()
        previous = self.snapshot()["risk_halt"]
        self.clock.now = datetime.fromisoformat(previous["daily"]["resets_at"].replace('Z','+00:00')).timestamp()+1
        self.source.stale = True
        self.service.tick()
        current = self.snapshot()["risk_halt"]
        self.assertIsNone(current["daily"]["baseline_equity"])
        self.assertTrue(current["weekly"]["halted"])
        self.assertNotEqual(current["state"], "READY")
    def test_one_leg_failure_records_conservative_unwind_loss_without_pair(self):
        self.service.fill_checker = lambda leg, index: index == 0
        self.service.tick()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["positions"], [])
        self.assertLess(snapshot["performance"]["net_pnl"], 0)
        self.assertGreater(snapshot["performance"]["costs_usdt"], 0)
        self.assertEqual(self.database().execute("SELECT COUNT(*) FROM quant_journal WHERE kind='LEG_FAILURE_UNWIND_SIMULATION'").fetchone()[0], 1)
        self.service.tick()
        self.assertEqual(self.database().execute("SELECT COUNT(*) FROM quant_journal WHERE kind='LEG_FAILURE_UNWIND_SIMULATION'").fetchone()[0], 1)
    def test_model_error_is_isolated_and_protection_still_closes(self):
        self.service.tick()
        def broken(*args):
            raise RuntimeError("synthetic classifier failure")
        self.service.model_funding = broken
        self.source.future = 120
        self.clock.now += 60
        self.service.tick()
        self.assertEqual(self.snapshot()["positions"], [])
        self.assertEqual(self.snapshot()["performance"]["closed_trades"], 1)
        self.assertTrue(any(row["reason"] == "MODEL_ERROR" for row in self.snapshot()["decisions"]))
    def test_decision_evidence_links_immutable_quotes_and_no_future_observations(self):
        self.service.tick()
        db = self.database()
        decision = json.loads(db.execute("SELECT data FROM quant_decisions WHERE action='OPEN_SHADOW'").fetchone()[0])
        digest = decision["available_at_decision"]["source_digest"]
        source = json.loads(db.execute("SELECT data FROM quant_sources WHERE id=?", (digest,)).fetchone()[0])
        self.assertLessEqual(source["at"], self.clock())
        self.assertTrue(all(row["spot"]["received_at"] <= self.clock() for row in source["markets"]))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM quant_observations WHERE received>?", (self.clock(),)).fetchone()[0], 0)
    def test_replay_uses_only_frozen_quotes_funding_and_assumptions(self):
        self.service.tick()
        identity = self.database().execute("SELECT id FROM quant_decisions WHERE action='OPEN_SHADOW'").fetchone()[0]
        original = replay_quant_decision(self.root, identity)
        self.assertTrue(original["model_matches"])
        self.source.spot = 200
        self.source.future = 220
        self.clock.now += 60
        self.service.tick()
        later = replay_quant_decision(self.root, identity)
        self.assertTrue(later["model_matches"])
        self.assertEqual(original["replayed_model"], later["replayed_model"])
        self.assertFalse(later["execution_enabled"])
    def test_statistical_replay_excludes_later_minute_observations(self):
        self.service.tick()
        identity = self.database().execute("SELECT id FROM quant_decisions WHERE strategy='STATISTICAL_ARBITRAGE' LIMIT 1").fetchone()[0]
        original = replay_quant_decision(self.root, identity)
        self.clock.now += 60
        self.service.tick()
        self.assertTrue(original["model_matches"])
        self.assertTrue(replay_quant_decision(self.root, identity)["model_matches"])
    def test_snapshot_is_bounded_and_contains_every_live_leg(self):
        self.source.rates["ETHUSDT"] = .01
        self.service.tick()
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot["positions"]), 2)
        self.assertEqual(sum(len(position["legs"]) for position in snapshot["positions"]), 4)
        self.assertLess(len(json.dumps(snapshot,separators=(",", ":")).encode()), 20000)
        self.assertEqual(len(snapshot["market"]), 3)
        self.assertEqual(len(snapshot["strategies"]), 2)
    def test_read_only_projection_database_failure_never_invents_cash(self):
        (self.root/DB_NAME).write_text("invalid sqlite", encoding="utf-8")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["state"], "DEGRADED")
        self.assertIsNone(snapshot["performance"]["equity"])
        self.assertIsNone(snapshot["performance"]["initial_capital"])


class ReferenceTransportTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.calls = []
    def request(self, venue, path, params):
        self.calls.append((venue,path,params))
        if path.endswith("fundingInfo"):
            return []
        if path.endswith("depth"):
            return {"bids": [["99.99", "1000"]], "asks": [["100.01", "1000"]], "E": self.clock()*1000}
        if path.endswith("premiumIndex"):
            return {"symbol": params["symbol"], "markPrice": "100", "lastFundingRate": ".0001",
                    "nextFundingTime": (self.clock()+3600)*1000, "time": self.clock()*1000}
        return [{"symbol": params["symbol"], "fundingTime": (self.clock()-25200-i*28800)*1000,
                 "fundingRate": ".0001", "markPrice": "100"} for i in range(8)]
    def test_fixed_public_feed_caches_history_and_stays_inside_call_budget(self):
        feed = QuantPublicFeed(request=self.request, clock=self.clock)
        first = feed()
        self.assertEqual(len(self.calls), 13)
        self.assertEqual(len(first["markets"]), 3)
        self.assertTrue(all(row["futures"]["funding_interval_seconds"] == 28800 for row in first["markets"]))
        feed()
        self.assertEqual(len(self.calls), 13)
        self.clock.now += 60
        feed()
        self.assertEqual(len(self.calls), 22)
        self.assertEqual(sum(path.endswith("fundingRate") for _,path,_ in self.calls), 3)
    def test_rate_limit_stops_subsequent_calls_and_retries_after_bound(self):
        def limited(*args):
            self.calls.append(args)
            raise ReferenceRateLimit(120)
        feed = QuantPublicFeed(request=limited, clock=self.clock)
        feed()
        self.assertEqual(len(self.calls), 1)
        self.clock.now += 60
        result = feed()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["sources"][0]["state"], "BACKOFF")
    def test_provider_errors_return_partial_diagnostics_without_quotes(self):
        def failed(*args):
            raise OSError("provider offline")
        feed = QuantPublicFeed(request=failed, clock=self.clock)
        result = feed()
        self.assertEqual(len(result["markets"]), 3)
        self.assertTrue(all(row["spot"] is None and row["futures"] is None for row in result["markets"]))
        self.assertGreater(feed.health["errors"], 0)
    def test_no_account_order_arbitrary_host_or_credentials_endpoint(self):
        for venue, path, params in (("FUTURES_REFERENCE", "/fapi/v1/order", {"symbol":"BTCUSDT"}),
                                     ("SPOT_REFERENCE", "/api/v3/account", {}),
                                     ("LIVE", "/fapi/v1/premiumIndex", {"symbol":"BTCUSDT"}),
                                     ("FUTURES_REFERENCE", "/fapi/v1/premiumIndex", {"symbol":"BTCUSDT","signature":"fake"}),
                                     ("SPOT_REFERENCE", "/api/v3/depth", {"symbol":"DOGEUSDT","limit":5})):
            with self.subTest(path=path), self.assertRaises(ValueError):
                reference_json(venue,path,params)
    def test_source_stop_prevents_any_new_http_request(self):
        feed = QuantPublicFeed(request=self.request, clock=self.clock)
        feed.close()
        feed()
        self.assertEqual(self.calls, [])
    def test_partial_far_depth_does_not_become_available_slippage_liquidity(self):
        original = self.request
        def request(venue, path, params):
            if path.endswith("depth"):
                return {"bids": [["99.99","1"],["90","10000"]], "asks": [["100.01","1"],["110","10000"]], "E": self.clock()*1000}
            return original(venue,path,params)
        result = QuantPublicFeed(request=request, clock=self.clock)()
        self.assertAlmostEqual(result["markets"][0]["spot"]["bid_depth_usdt"], 99.99)
        self.assertAlmostEqual(result["markets"][0]["spot"]["ask_depth_usdt"], 100.01)


if __name__ == "__main__":
    unittest.main(verbosity=2)
