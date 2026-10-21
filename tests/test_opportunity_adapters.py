"""Synthetic parity/failure tests for observational entry adapters, never brokers online."""
from __future__ import annotations

import ast
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from trader.config import load_config
from trader.database import Database
from trader.domain import Signal
from trader.engine import TradingEngine
from trader.futures_testnet import FuturesTestnetLab
from trader.market_pulse import MarketPulseService, PulseConfig, _connect as pulse_connect
from trader.quant_shadow import QuantShadowService, _connect as quant_connect
from trader.testnet_broker import BinanceTestnetBroker


NOW = 1_800_000_000.


def pulse_market(symbol):
    return {"symbol": symbol, "price": 100., "change_1m_pct": .8, "change_5m_pct": 1.4,
        "relative_volume": 2.2, "anomaly_z": 3., "momentum": .8, "acceleration": .2,
        "volatility_pct": .15, "spread_bps": 4., "depth_quote": 100_000., "imbalance": .1,
        "liquidity_change_pct": 0., "fresh": True, "complete": True,
        "at": datetime.fromtimestamp(NOW, UTC).isoformat()}


def quant_source(now):
    markets = []
    for symbol, rate in (("BTCUSDT", .01), ("ETHUSDT", .0001), ("SOLUSDT", .0001)):
        spot = {"symbol": symbol, "bid": 99.99, "ask": 100.01,
            "bid_depth_usdt": 100000., "ask_depth_usdt": 100000., "at": now-1, "received_at": now}
        future = {**spot, "mark_price": 100., "observed_funding_rate": rate,
            "next_funding_at": now+3600, "funding_interval_seconds": 28800.}
        history = [{"at": now-25200-i*28800, "received_at": now-25200-i*28800+1,
                    "rate": rate, "mark_price": 100.} for i in range(8)]
        markets.append({"symbol": symbol, "spot": spot, "futures": future, "history": history})
    return {"markets": markets, "sources": [], "at": now}


class EntryAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = load_config()

    def spot(self, name):
        db = Database(self.root/(name+".db"))
        db.record_market_snapshot({"BTCUSDT": 100.})
        broker = BinanceTestnetBroker(db, self.config.paper, self.config.risk)
        signal = Signal("BTCUSDT", "BUY", 80, 100., 95., 110., 2., 60., 101., 99., 1.3,
                        "fixture", datetime.fromtimestamp(NOW-1, UTC).isoformat())
        info = {"symbol": "BTCUSDT", "baseAsset": "BTC", "ocoAllowed": True,
            "orderTypes": ["MARKET", "STOP_LOSS", "TAKE_PROFIT"], "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": ".01", "minPrice": ".01", "maxPrice": "1000000"},
                {"filterType": "LOT_SIZE", "minQty": ".001", "maxQty": "10", "stepSize": ".001"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5", "applyToMarket": True}]}
        return broker, signal, info

    def test_spot_identical_single_post_with_absent_full_and_failing_observation(self):
        payloads, balances = [], []
        for index, behavior in enumerate((False, True, RuntimeError("observer disk full"))):
            broker, signal, info = self.spot(str(index))
            posts, observed_pending = [], []
            def signed(method, endpoint, fields):
                if endpoint == "/api/v3/account":
                    return {"balances": [{"asset": "USDT", "free": "1000", "locked": "0"}]}
                self.assertEqual((method, endpoint), ("POST", "/api/v3/order"))
                posts.append(dict(fields))
                return {"symbol": "BTCUSDT", "clientOrderId": fields["newClientOrderId"], "side": "BUY",
                    "status": "FILLED", "executedQty": ".1", "cummulativeQuoteQty": "10",
                    "fills": [{"commission": ".01", "commissionAsset": "USDT"}]}
            def intent(**kwargs):
                observed_pending.append((broker._pending(), kwargs["origin_ref"]))
                # The copied adapter DTO cannot mutate the native pending/Signal.
                kwargs["legs"][0]["quantity"] = "99999"
                if isinstance(behavior, Exception):
                    raise behavior
                return behavior
            with patch("trader.exchange.BinanceClient") as client, \
                    patch("trader.native_protection.SpotNativeProtection.ensure"), \
                    patch("trader.testnet_broker.secrets.token_hex", return_value="fixed"), \
                    patch("trader.testnet_broker.signed_request", side_effect=signed), \
                    patch("trader.opportunity_observer.observe_entry_intent", side_effect=intent) as observe, \
                    patch("trader.opportunity_observer.observe_entry_outcome", side_effect=RuntimeError("stopped")):
                client.return_value.testnet_symbol_info.return_value = info
                client.return_value.testnet_reference_price.return_value = 100.
                position = broker.buy(signal, .1, "fixture")
            self.assertEqual(observe.call_count, 1)
            self.assertEqual(observed_pending[0][0]["client_order_id"], observed_pending[0][1])
            self.assertEqual(len(posts), 1)
            self.assertEqual(position.quantity, .1)
            self.assertEqual(signal.price, 100.)
            self.assertIsNone(broker._pending())
            payloads.append(posts[0]); balances.append(broker.db.cash())
        self.assertEqual(payloads, [payloads[0]]*3)
        self.assertEqual(balances, [989.99]*3)

    def test_spot_sell_does_not_emit_entry_and_buy_reconciliation_reports_outcome(self):
        broker, signal, _ = self.spot("sell")
        pending = {"symbol": "BTCUSDT", "side": "SELL", "client_order_id": "sell-id", "planned_qty": ".1"}
        response = {"symbol": "BTCUSDT", "side": "SELL", "clientOrderId": "sell-id",
            "status": "CANCELED", "executedQty": "0", "cummulativeQuoteQty": "0"}
        with patch("trader.opportunity_observer.observe_entry_intent") as intent, \
                patch("trader.opportunity_observer.observe_entry_outcome") as outcome, \
                patch("trader.testnet_broker.signed_request", return_value=response):
            broker._submit_market(pending, {"side": "SELL"})
            pending.update(side="BUY", signal=signal.to_dict())
            response.update(side="BUY")
            broker._save_pending(pending)
            self.assertTrue(broker.reconcile_pending())
        intent.assert_not_called()
        self.assertEqual(outcome.call_count,1)
        self.assertEqual(outcome.call_args.kwargs['state'],'CANCELLED')
        self.assertEqual(outcome.call_args.kwargs['evidence']['quantity'],'0')

    def filled_buy(self,broker,signal,identity='entry-id'):
        return {'symbol':'BTCUSDT','side':'BUY','client_order_id':identity,'planned_qty':'.1',
            'signal':signal.to_dict(),'status':'FILLED','executed_qty':'.1','cumulative_quote':'10',
            'commission_quote':'.01','commission_base':'0','commission_other':{},'reason':'fixture'}

    def test_spot_commit_observation_reads_committed_ledger_and_survives_receipt_replay(self):
        broker,signal,_=self.spot('ledger-commit')
        pending=self.filled_buy(broker,signal)
        observations=[]
        def committed(**fields):
            with closing(sqlite3.connect(broker.db.path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM positions').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM exchange_fill_receipts').fetchone()[0],1)
            observations.append(fields)
        with patch('trader.opportunity_observer.observe_entry_outcome',side_effect=committed):
            broker._apply_terminal_fill(pending)
            recovered=broker._pending()
            broker._apply_terminal_fill(recovered)
        self.assertEqual(len(observations),2)
        self.assertEqual(observations[0]['evidence'],observations[1]['evidence'])
        self.assertEqual(observations[0]['state'],'OPENED')
        self.assertEqual(broker.db.cash(),989.99)
        self.assertEqual(broker.db.position('BTCUSDT').quantity,.1)

    def test_spot_failed_commit_emits_no_open_and_preserves_balance(self):
        broker,signal,_=self.spot('ledger-rollback')
        with broker.db.connect() as db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON exchange_fill_receipts BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with patch('trader.opportunity_observer.observe_entry_outcome') as observed:
            with self.assertRaises(sqlite3.IntegrityError):broker._apply_terminal_fill(self.filled_buy(broker,signal))
        observed.assert_not_called()
        self.assertEqual(broker.db.cash(),1000.)
        self.assertIsNone(broker.db.position('BTCUSDT'))

    def test_spot_partial_and_native_full_close_emit_only_after_commit(self):
        broker,signal,_=self.spot('ledger-close')
        broker._apply_terminal_fill(self.filled_buy(broker,signal))
        opening=broker.db.position('BTCUSDT')
        calls=[]
        def closed(**fields):
            with closing(sqlite3.connect(broker.db.path)) as db:
                count=db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
                self.assertEqual(count,0 if fields['remaining_quantity']=='0' else 1)
                self.assertGreater(db.execute("SELECT COUNT(*) FROM trades WHERE side='SELL'").fetchone()[0],0)
            calls.append(fields)
        with patch('trader.opportunity_observer.observe_position_commit',side_effect=closed):
            for identity,quantity,quote in [('partial-id','.04','4'),('native-stop-id','.06','6')]:
                position=broker.db.position('BTCUSDT')
                pending={'symbol':'BTCUSDT','side':'SELL','client_order_id':identity,'status':'FILLED',
                    'executed_qty':quantity,'cumulative_quote':quote,'commission_quote':'0','commission_base':'0',
                    'commission_other':{},'position':position.to_dict(),'reason':'native stop'}
                broker._apply_terminal_fill(pending,native=identity=='native-stop-id')
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]['position_ref'],opening.symbol+'|'+opening.opened_at)
        self.assertEqual(calls[0]['position_ref'],calls[1]['position_ref'])
        self.assertGreater(float(calls[0]['remaining_quantity']),0)
        self.assertEqual(calls[1]['remaining_quantity'],'0')
        self.assertIsNone(broker.db.position('BTCUSDT'))

    def test_spot_native_rejection_preserves_zero_posts_and_zero_observation(self):
        broker, signal, _ = self.spot("reject")
        with patch("trader.opportunity_observer.observe_entry_intent") as intent, \
                patch("trader.testnet_broker.signed_request") as signed:
            with self.assertRaises(ValueError):
                broker.buy(signal, -1., "rejected")
        signed.assert_not_called(); intent.assert_not_called()

    def future(self, name):
        settings = replace(self.config.futures_testnet, database_path=self.root/(name+".db"))
        lab = FuturesTestnetLab(settings)
        lab.ledger.set_setting("forward_open_plan", {"symbol": "BTCUSDT", "direction": "LONG", "leverage": 1})
        return lab

    def forward_position(self):
        return {'symbol':'BTCUSDT','direction':'LONG','leverage':1,'quantity':.1,'entry_price':100.,
            'stop_price':95.,'take_profit':110.,'liquidation_price':None,'signal_score':80,
            'opened_at':datetime.fromtimestamp(NOW,UTC).isoformat()}

    def test_futures_ledger_open_close_observation_is_after_sqlite_commit(self):
        lab=self.future('forward-ledger')
        observations=[]
        def opened(**fields):
            with closing(sqlite3.connect(lab.ledger.path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM forward_position').fetchone()[0],1)
            observations.append(fields)
        def closed(**fields):
            with closing(sqlite3.connect(lab.ledger.path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM forward_position').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM forward_trades').fetchone()[0],1)
            observations.append(fields)
        with patch('trader.opportunity_observer.observe_entry_outcome',side_effect=opened), \
                patch('trader.opportunity_observer.observe_position_commit',side_effect=closed):
            lab.ledger.set_forward_position(self.forward_position(),observation_origin='exact-forward-entry')
            lab.ledger.close_forward_position(symbol='BTCUSDT',exit_price=101.,gross_pnl=.1,exit_reason='NATIVE_STOP')
        self.assertEqual(observations[0]['origin_ref'],'exact-forward-entry')
        self.assertEqual(observations[1]['position_ref'],'BTCUSDT|'+self.forward_position()['opened_at'])
        self.assertEqual(observations[1]['remaining_quantity'],'0')

    def test_futures_close_rollback_and_absent_identity_do_not_fabricate_open(self):
        lab=self.future('forward-rollback')
        with patch('trader.opportunity_observer.observe_entry_outcome') as opened:
            lab.ledger.set_forward_position(self.forward_position())
        opened.assert_not_called()
        with lab.ledger._connect() as db:
            db.execute("CREATE TRIGGER reject_close BEFORE INSERT ON forward_trades BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with patch('trader.opportunity_observer.observe_position_commit') as closed:
            with self.assertRaises(sqlite3.IntegrityError):
                lab.ledger.close_forward_position(symbol='BTCUSDT',exit_price=101.,gross_pnl=.1,exit_reason='STOP')
        closed.assert_not_called()
        self.assertIsNotNone(lab.ledger.forward_position('BTCUSDT'))

    def test_futures_readonly_reconciliation_reports_partial_without_second_post(self):
        lab=self.future('forward-partial')
        pending={'symbol':'BTCUSDT','client_order_id':'pending-entry','reduce_only':False}
        lab.ledger.set_setting('forward_pending_order',pending)
        response={'clientOrderId':'pending-entry','status':'PARTIALLY_FILLED','executedQty':'.04'}
        with patch('trader.futures_testnet.signed_request',return_value=response) as request, \
                patch('trader.opportunity_observer.observe_entry_outcome') as observed:
            result=lab.reconcile_forward_pending()
        self.assertFalse(result['resolved'])
        self.assertEqual(request.call_args.args[0],'GET')
        self.assertEqual(request.call_count,1)
        self.assertEqual(observed.call_args.kwargs['state'],'PARTIAL')
        self.assertFalse(observed.call_args.kwargs['complete'])
        self.assertEqual(lab.ledger.setting('forward_pending_order'),pending)

    def test_futures_identical_post_with_observation_full_or_failed(self):
        posts = []
        for index, behavior in enumerate((False, True, RuntimeError("broken"))):
            lab = self.future("f"+str(index))
            observed_pending = []
            def signed(method, endpoint, fields):
                self.assertEqual((method, endpoint), ("POST", "/fapi/v1/order"))
                posts.append(dict(fields))
                return {"clientOrderId": fields["newClientOrderId"], "status": "FILLED", "executedQty": ".1"}
            def intent(**kwargs):
                observed_pending.append((lab.ledger.setting("forward_pending_order"), kwargs["origin_ref"]))
                kwargs["legs"][0]["quantity"] = "99999"
                if isinstance(behavior, Exception):
                    raise behavior
                return behavior
            with patch.object(lab, "ensure_flat_forward_configuration"), \
                    patch("trader.futures_testnet.secrets.token_hex", return_value="fixed"), \
                    patch("trader.futures_testnet.signed_request", side_effect=signed), \
                    patch("trader.opportunity_observer.observe_entry_intent", side_effect=intent) as observe, \
                    patch("trader.opportunity_observer.observe_entry_outcome", side_effect=RuntimeError("full")):
                result = lab.forward_submit(symbol="BTCUSDT", side="BUY", quantity=Decimal(".1"), reduce_only=False)
            self.assertEqual(result["status"], "FILLED")
            self.assertEqual(observe.call_count, 1)
            self.assertEqual(observed_pending[0][0]["client_order_id"], observed_pending[0][1])
            self.assertIsNotNone(lab.ledger.setting("forward_pending_order"))
        self.assertEqual(posts, [posts[0]]*3)
        self.assertNotIn("reduceOnly", posts[0])

    def test_futures_reduce_only_and_native_configuration_rejection_have_no_entry_hook(self):
        lab = self.future("close")
        def signed(method, endpoint, fields):
            self.assertEqual(fields["reduceOnly"], "true")
            return {"clientOrderId": fields["newClientOrderId"], "status": "FILLED"}
        with patch("trader.opportunity_observer.observe_entry_intent") as intent, \
                patch("trader.opportunity_observer.observe_entry_outcome") as outcome, \
                patch("trader.futures_testnet.signed_request", side_effect=signed):
            lab.forward_submit(symbol="BTCUSDT", side="SELL", quantity=Decimal(".1"), reduce_only=True)
        intent.assert_not_called(); outcome.assert_not_called()
        lab.ledger.set_setting("forward_pending_order", None)
        with patch.object(lab, "ensure_flat_forward_configuration", side_effect=RuntimeError("native gate")), \
                patch("trader.opportunity_observer.observe_entry_intent") as intent, \
                patch("trader.futures_testnet.signed_request") as signed:
            with self.assertRaisesRegex(RuntimeError, "native gate"):
                lab.forward_submit(symbol="BTCUSDT", side="BUY", quantity=Decimal(".1"), reduce_only=False)
        intent.assert_not_called(); signed.assert_not_called()

    def test_futures_context_preserves_native_reference_and_original_review(self):
        from copy import deepcopy
        from types import SimpleNamespace
        from trader.futures_forward import FuturesForwardEngine
        engine = FuturesForwardEngine.__new__(FuturesForwardEngine)
        engine.settings = self.config.futures_testnet
        engine.lab = SimpleNamespace()
        signal = {"direction": "LONG", "candle_close_utc": datetime.fromtimestamp(NOW-60, UTC).isoformat()}
        review = {"model": "existing", "verdict": "ALLOW", "confidence": .8, "direction": "LONG", "score": 80,
                  "at": datetime.fromtimestamp(NOW-1, UTC).isoformat(), "reason": "free text never projected"}
        portfolio = {"notional_limit_usdt": 300., "stop_loss_limit_usdt": 7.5}
        account = {"available_balance": 1000., "wallet_balance": 1000., "unrealized_pnl": 0.}
        originals = deepcopy((signal, review, portfolio, account))
        reference = Decimal("100.123456789123456789")
        engine._set_opportunity_context(signal, review, reference, 2., account, portfolio)
        context = engine.lab._opportunity_context
        self.assertIsNotNone(context)
        self.assertEqual(context["reference_price"], reference)
        self.assertNotIn("market_at", context["evidence"])  # Candle time is not the final REST quote timestamp.
        self.assertNotIn("decision_at", context["evidence"])  # The final durable pending hook sets this later.
        self.assertEqual(len(context["evidence"]["source_digest"]), 64)
        self.assertEqual(len(context["evidence"]["policy_digest"]), 64)
        self.assertNotIn("at", context["capital"])  # The prior account read has no captured source timestamp.
        self.assertEqual(len(context["evidence"]["review_digest"]), 64)
        self.assertNotIn("free text", repr(context))
        self.assertEqual((signal, review, portfolio, account), originals)

    def test_final_decision_cutoff_follows_original_signal_review_and_balance(self):
        from trader.domain import AIReview
        from trader.opportunity_contract import build_intent
        from trader.opportunity_shadow import evaluate_intent
        from trader.futures_forward import FuturesForwardEngine
        broker, signal, _ = self.spot("final-cutoff")
        signal = replace(signal, created_at=datetime.fromtimestamp(NOW-60, UTC).isoformat())
        broker._opportunity_review = (AIReview("ALLOW", .8, 1., "fixture"), "existing-model", NOW-30)
        pending = {"symbol": "BTCUSDT", "side": "BUY", "client_order_id": "cutoff-spot",
                   "planned_qty": ".1", "signal": signal.to_dict()}
        capital = {"available": "1000", "at": NOW-1}
        with patch("trader.testnet_broker.time.time", return_value=NOW), \
                patch("trader.opportunity_observer.observe_entry_intent") as observe:
            broker._observe_entry(pending, {"capital": capital, "limits": {"gross_limit": 9999}})
        spot = observe.call_args.kwargs
        self.assertEqual(spot["evidence"]["decision_at"], NOW)
        self.assertEqual(spot["evidence"]["known_at"], NOW)
        self.assertGreater(spot["evidence"]["decision_at"], capital["at"])
        self.assertNotIn("market_at", spot["evidence"])
        self.assertNotIn("received_at", spot["evidence"])
        self.assertIsNone(spot["limits"])  # No starting account inventory is frozen.
        self.assertEqual(len(spot["evidence"]["source_digest"]), 64)
        self.assertEqual(len(spot["evidence"]["review_digest"]), 64)
        self.assertNotEqual(evaluate_intent(build_intent(**spot).payload())["reason"], "EVIDENCE_AFTER_DECISION")
        engine = FuturesForwardEngine.__new__(FuturesForwardEngine)
        engine.settings = self.config.futures_testnet
        engine.lab = self.future("cutoff-future")
        original_signal = {"direction": "LONG", "candle_close_utc": datetime.fromtimestamp(NOW-60, UTC).isoformat()}
        review = {"model": "existing", "verdict": "ALLOW", "confidence": .8, "direction": "LONG", "score": 80,
                  "at": datetime.fromtimestamp(NOW-30, UTC).isoformat()}
        engine._set_opportunity_context(original_signal, review, Decimal("100"), 2.,
            {"available_balance": 1000., "wallet_balance": 1000., "unrealized_pnl": 0.},
            {"notional_limit_usdt": 300., "stop_loss_limit_usdt": 7.5})
        forward = {"symbol": "BTCUSDT", "side": "BUY", "quantity": ".1", "client_order_id": "cutoff-futures"}
        with patch("trader.futures_testnet.time.time", return_value=NOW), \
                patch("trader.opportunity_observer.observe_entry_intent") as observe:
            engine.lab._observe_forward_entry(forward, {})
        futures = observe.call_args.kwargs
        self.assertEqual(futures["evidence"]["decision_at"], NOW)
        self.assertEqual(futures["evidence"]["known_at"], NOW)
        self.assertNotIn("market_at", futures["evidence"])
        self.assertNotIn("received_at", futures["evidence"])
        self.assertIsNone(futures["limits"])
        self.assertNotEqual(evaluate_intent(build_intent(**futures).payload())["reason"], "EVIDENCE_AFTER_DECISION")

    def test_spot_uncertain_post_keeps_pending_once_and_only_reports_unknown(self):
        broker, signal, _ = self.spot("uncertain")
        pending = {"symbol": "BTCUSDT", "side": "BUY", "client_order_id": "uncertain-id",
            "planned_qty": ".1", "signal": signal.to_dict(), "status": "UNCERTAIN"}
        with patch("trader.opportunity_observer.observe_entry_intent") as intent, \
                patch("trader.opportunity_observer.observe_entry_outcome") as outcome, \
                patch("trader.testnet_broker.signed_request", side_effect=TimeoutError("uncertain")) as post:
            with self.assertRaises(TimeoutError):
                broker._submit_market(pending, {"side": "BUY"})
            with self.assertRaises(Exception):
                broker._submit_market(pending, {"side": "BUY"})
        self.assertEqual(post.call_count, 1); self.assertEqual(intent.call_count, 1)
        self.assertEqual(outcome.call_args.kwargs["state"], "UNKNOWN")
        self.assertFalse(outcome.call_args.kwargs["complete"])

    def test_real_full_queue_and_stopped_consumer_preserve_both_native_posts(self):
        from trader.opportunity_observer import OpportunityObserverService, register_observer, unregister_observer
        observer = OpportunityObserverService(self.root/"never-initialized-observer")
        while not observer._queue.full():
            observer._queue.put_nowait(None)
        self.assertTrue(register_observer(observer))
        self.addCleanup(unregister_observer, observer)
        broker, signal, _ = self.spot("full-real")
        pending = {"symbol": "BTCUSDT", "side": "BUY", "client_order_id": "full-spot",
            "planned_qty": ".1", "signal": signal.to_dict(), "status": "UNCERTAIN"}
        fields = {"symbol": "BTCUSDT", "side": "BUY", "quantity": ".1", "newClientOrderId": "full-spot"}
        response = {"symbol": "BTCUSDT", "side": "BUY", "clientOrderId": "full-spot",
                    "status": "NEW", "executedQty": "0", "cummulativeQuoteQty": "0"}
        with patch("trader.testnet_broker.signed_request", return_value=response) as post:
            broker._submit_market(pending, fields)
        post.assert_called_once_with("POST", "/api/v3/order", fields)
        self.assertEqual(broker._pending()["planned_qty"], ".1")
        lab = self.future("full-real-future")
        with patch.object(lab, "ensure_flat_forward_configuration"), \
                patch("trader.futures_testnet.secrets.token_hex", return_value="fixed"), \
                patch("trader.futures_testnet.signed_request", return_value={"clientOrderId": "cait-fwd-fixed", "status": "FILLED"}) as post:
            lab.forward_submit(symbol="BTCUSDT", side="BUY", quantity=Decimal(".1"), reduce_only=False)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[2]["quantity"], "0.1")
        self.assertEqual(observer._queue.qsize(), observer._queue.maxsize)
        self.assertFalse(observer.path.parent.exists())  # Producer never initialized SQL or waits for a worker.
        self.assertIsNotNone(broker._pending())

    def test_futures_uncertain_post_keeps_pending_once_and_only_reports_unknown(self):
        lab = self.future("uncertain-future")
        with patch.object(lab, "ensure_flat_forward_configuration"), \
                patch("trader.opportunity_observer.observe_entry_intent") as intent, \
                patch("trader.opportunity_observer.observe_entry_outcome") as outcome, \
                patch("trader.futures_testnet.signed_request", side_effect=TimeoutError("uncertain")) as post:
            with self.assertRaises(TimeoutError):
                lab.forward_submit(symbol="BTCUSDT", side="BUY", quantity=Decimal(".1"), reduce_only=False)
            with self.assertRaises(Exception):
                lab.forward_submit(symbol="BTCUSDT", side="BUY", quantity=Decimal(".1"), reduce_only=False)
        self.assertEqual(post.call_count, 1); self.assertEqual(intent.call_count, 1)
        self.assertEqual(outcome.call_args.kwargs["state"], "UNKNOWN")
        self.assertFalse(outcome.call_args.kwargs["complete"])

    def pulse(self, name):
        service = MarketPulseService(self.root/name, config=PulseConfig(symbols=("BTCUSDT",)), clock=lambda: NOW)
        service._initialize()
        window = service.windows["BTCUSDT"]
        window.metrics = Mock(return_value=pulse_market("BTCUSDT"))
        window.bid, window.ask, window.book_at = 99.98, 100.02, NOW
        window.bid_quote, window.ask_quote = 50000., 50000.
        window.last_trade_at = window.last_received_at = NOW
        return service

    def test_pulse_observes_before_insert_and_confirms_only_after_commit(self):
        service = self.pulse("pulse")
        events = []
        def intent(**kwargs):
            with pulse_connect(service.path, readonly=True) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM pulse_positions").fetchone()[0], 0)
            events.append(("intent", kwargs))
        def committed(**kwargs):
            with pulse_connect(service.path, readonly=True) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM pulse_positions").fetchone()[0], 1)
            events.append(("commit", kwargs))
        with patch("trader.opportunity_observer.observe_entry_intent", side_effect=intent), \
                patch("trader.opportunity_observer.observe_entry_outcome", side_effect=committed):
            service.evaluate(NOW, project=False)
        self.assertEqual([row[0] for row in events], ["intent", "commit"])
        self.assertEqual(events[1][1]["stage"], "LEDGER_COMMIT")
        self.assertEqual(events[0][1]["origin_ref"], events[1][1]["origin_ref"])

    def test_pulse_observer_failure_does_not_change_wallet_and_pause_preserves_zero_intents(self):
        values = []
        for name, failing in (("pa", False), ("pb", True)):
            service = self.pulse(name)
            with patch("trader.opportunity_observer.observe_entry_intent", side_effect=RuntimeError("observer") if failing else None), \
                    patch("trader.opportunity_observer.observe_entry_outcome", side_effect=RuntimeError("observer") if failing else None):
                service.evaluate(NOW, project=False)
            with pulse_connect(service.path, readonly=True) as db:
                values.append((db.execute("SELECT data FROM pulse_positions").fetchone()[0],
                    db.execute("SELECT value FROM pulse_meta WHERE key='cash'").fetchone()[0]))
        self.assertEqual(values[0], values[1])
        service = self.pulse("paused")
        service.kill_switch_path.write_text("owner pause\n", encoding="utf-8")
        with patch("trader.opportunity_observer.observe_entry_intent") as intent:
            service.evaluate(NOW, project=False)
        intent.assert_not_called()

    def test_pulse_rollback_never_claims_ledger_commit(self):
        service = self.pulse("rollback")
        with pulse_connect(service.path) as db:
            db.execute("CREATE TRIGGER fail_decision BEFORE INSERT ON pulse_decisions BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        with patch("trader.opportunity_observer.observe_entry_intent") as intent, \
                patch("trader.opportunity_observer.observe_entry_outcome") as outcome:
            with self.assertRaises(sqlite3.IntegrityError):
                service.evaluate(NOW, project=False)
        self.assertEqual(intent.call_count, 1); outcome.assert_not_called()

    def test_pulse_protective_close_observes_committed_trade_and_failure_is_isolated(self):
        service=self.pulse('pulse-close');service.evaluate(NOW,project=False)
        identity=service._positions['BTCUSDT']['id']
        def closed(**fields):
            with pulse_connect(service.path,readonly=True) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM pulse_positions').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM pulse_trades').fetchone()[0],1)
            self.assertEqual(fields['position_ref'],identity)
            raise RuntimeError('observer failure never cancels the committed protective close')
        with patch('trader.opportunity_observer.observe_position_commit',side_effect=closed) as observe:
            service._close_position('BTCUSDT',99.,NOW,'STOP')
        self.assertEqual(observe.call_count,1)
        self.assertNotIn('BTCUSDT',service._positions)

    def test_pulse_close_rollback_never_claims_closed(self):
        service=self.pulse('pulse-close-rollback');service.evaluate(NOW,project=False)
        with pulse_connect(service.path) as db:
            db.execute("CREATE TRIGGER reject_close BEFORE INSERT ON pulse_trades BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with patch('trader.opportunity_observer.observe_position_commit') as observe:
            with self.assertRaises(sqlite3.IntegrityError):service._close_position('BTCUSDT',99.,NOW,'STOP')
        observe.assert_not_called()
        self.assertIn('BTCUSDT',service._positions)

    def test_quant_protective_close_observes_only_committed_pair(self):
        service=QuantShadowService(self.root/'quant-close',source=quant_source,clock=lambda:NOW)
        self.addCleanup(service.stop);self.assertTrue(service.tick())
        service.kill_switch_path.write_text('owner pause',encoding='utf-8')
        def closed(**fields):
            with quant_connect(service.path,readonly=True) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM quant_positions').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM quant_trades').fetchone()[0],1)
            self.assertEqual(fields['remaining_quantity'],'0')
        with patch('trader.opportunity_observer.observe_position_commit',side_effect=closed) as observe:
            self.assertTrue(service.tick())
        self.assertEqual(observe.call_count,1)

    def test_quant_protective_close_rollback_has_no_false_terminal(self):
        service=QuantShadowService(self.root/'quant-close-rollback',source=quant_source,clock=lambda:NOW)
        self.addCleanup(service.stop);self.assertTrue(service.tick())
        service.kill_switch_path.write_text('owner pause',encoding='utf-8')
        with quant_connect(service.path) as db:
            db.execute("CREATE TRIGGER reject_close BEFORE INSERT ON quant_trades BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with patch('trader.opportunity_observer.observe_position_commit') as observe:
            with self.assertRaises(sqlite3.IntegrityError):service.tick()
        observe.assert_not_called()
        with quant_connect(service.path,readonly=True) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM quant_positions').fetchone()[0],1)

    def test_quant_two_legs_before_insert_and_commit_after_native_transaction(self):
        service = QuantShadowService(self.root/"quant", source=quant_source, clock=lambda: NOW)
        self.addCleanup(service.stop)
        events = []
        def intent(**kwargs):
            with quant_connect(service.path, readonly=True) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM quant_positions").fetchone()[0], 0)
            self.assertEqual(len(kwargs["legs"]), 2)
            self.assertEqual(kwargs["legs"][0]["quantity"], kwargs["legs"][1]["quantity"])
            events.append(("intent", kwargs))
        def committed(**kwargs):
            with quant_connect(service.path, readonly=True) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM quant_positions").fetchone()[0], 1)
            events.append(("commit", kwargs))
        with patch("trader.opportunity_observer.observe_entry_intent", side_effect=intent), \
                patch("trader.opportunity_observer.observe_entry_outcome", side_effect=committed):
            self.assertTrue(service.tick())
        self.assertEqual([row[0] for row in events], ["intent", "commit"])
        self.assertEqual(events[0][1]["origin_ref"], events[1][1]["origin_ref"])

    def test_quant_failure_and_pause_keep_native_shadow_gates(self):
        results = []
        for name, failing in (("qa", False), ("qb", True)):
            service = QuantShadowService(self.root/name, source=quant_source, clock=lambda: NOW)
            self.addCleanup(service.stop)
            with patch("trader.opportunity_observer.observe_entry_intent", side_effect=RuntimeError("observer") if failing else None), \
                    patch("trader.opportunity_observer.observe_entry_outcome", side_effect=RuntimeError("observer") if failing else None):
                self.assertTrue(service.tick())
            with quant_connect(service.path, readonly=True) as db:
                results.append((db.execute("SELECT data FROM quant_positions").fetchone()[0],
                    db.execute("SELECT value FROM quant_meta WHERE key='wallet_balance'").fetchone()[0]))
        self.assertEqual(results[0], results[1])
        service = QuantShadowService(self.root/"qpaused", source=quant_source, clock=lambda: NOW)
        self.addCleanup(service.stop); service.initialize()
        service.kill_switch_path.write_text("owner pause\n", encoding="utf-8")
        with patch("trader.opportunity_observer.observe_entry_intent") as intent:
            self.assertTrue(service.tick())
        intent.assert_not_called()

    def test_quant_rollback_never_claims_commit(self):
        service = QuantShadowService(self.root/"qrollback", source=quant_source, clock=lambda: NOW)
        self.addCleanup(service.stop); service.initialize()
        with quant_connect(service.path) as db:
            db.execute("CREATE TRIGGER fail_decision BEFORE INSERT ON quant_decisions BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        with patch("trader.opportunity_observer.observe_entry_intent") as intent, \
                patch("trader.opportunity_observer.observe_entry_outcome") as outcome:
            with self.assertRaises(sqlite3.IntegrityError):
                service.tick()
        self.assertEqual(intent.call_count, 1); outcome.assert_not_called()

    def engine(self):
        config = replace(self.config, bot=replace(self.config.bot, mode="paper", database_path=self.root/"engine.db"),
            market_pulse=replace(self.config.market_pulse, enabled=False),
            quant_arbitrage=replace(self.config.quant_arbitrage, enabled=False))
        return TradingEngine(config)

    def test_observer_lifecycle_failure_and_shutdown_do_not_interrupt_engine_loop(self):
        engine = self.engine()
        observer = Mock()
        observer.start.side_effect = RuntimeError("private observer detail")
        with patch.object(engine, "_create_opportunity_observer", return_value=observer), \
                patch.object(engine, "_create_guardian_shadow", return_value=Mock()), \
                patch.object(engine, "_run_supervised_loop") as loop:
            engine.run_forever()
        observer.stop.assert_called_once(); loop.assert_called_once()
        self.assertNotIn("private observer detail", json.dumps(engine.db.recent("events", 10)))

    def test_disabled_or_stopped_host_does_not_start_observation(self):
        engine = self.engine()
        with patch.object(engine, "_create_opportunity_observer") as factory, \
                patch.object(engine, "_run_supervised_loop"):
            engine.run_forever(lambda: True)
            engine.config = replace(engine.config, guardian_intelligence=replace(engine.config.guardian_intelligence, enabled=False))
            engine.run_forever()
        factory.assert_not_called()

    def test_four_adapters_reach_real_closed_contract_and_separate_journal(self):
        from trader.domain import AIReview
        from trader.opportunity_observer import OpportunityObserverService, register_observer, unregister_observer
        observer = OpportunityObserverService(self.root/"observer", clock=lambda: NOW+1)
        observer.initialize()
        self.assertTrue(register_observer(observer))
        self.addCleanup(unregister_observer, observer)
        broker, signal, _ = self.spot("contract")
        broker._opportunity_review = (AIReview("ALLOW", .8, 1., "untrusted free reason"), "existing-model", NOW-1)
        pending = {"symbol": "BTCUSDT", "side": "BUY", "client_order_id": "native-spot",
            "planned_qty": ".1", "signal": signal.to_dict(), "status": "FILLED",
            "executed_qty": ".1", "commission_quote": ".01", "commission_base": "0"}
        lab = self.future("contract-futures")
        forward = {"symbol": "BTCUSDT", "side": "BUY", "quantity": ".1", "client_order_id": "native-futures"}
        pulse = self.pulse("contract-pulse")
        quant = QuantShadowService(self.root/"contract-quant", clock=lambda: NOW)
        position = {"id": "native-pulse", "symbol": "BTCUSDT", "quantity": .1, "stop": 95., "target": 110.}
        books = [quant_source(NOW)["markets"][0][venue] for venue in ("spot", "futures")]
        pair = {"id": "native-quant", "strategy": "FUNDING_CARRY", "legs": [
            {"symbol": "BTCUSDT", "venue": venue, "direction": direction, "quantity": .1,
             "entry_price": 100., "entry_reference": 100.}
            for venue, direction in (("SPOT_REFERENCE", "LONG"), ("FUTURES_REFERENCE", "SHORT"))]}
        with patch("trader.testnet_broker.time.time", return_value=NOW):
            broker._observe_entry(pending, {"capital": {"available": "1000", "at": NOW}, "limits": {"max_positions": 10}})
            broker._observe_response(pending)
            lab._observe_forward_entry(forward, {})
            lab._observe_forward_response(forward, {"status": "FILLED", "executedQty": ".1"})
            pulse._observe_entry(position, pulse.windows["BTCUSDT"], pulse_market("BTCUSDT"), None, 1000., 1000., NOW)
            pulse._observe_entry_commit(position["id"], NOW)
            quant._observe_entry(pair, books, 1000., NOW)
            quant._observe_entry_commit(pair["id"], NOW)
        self.assertEqual(observer._queue.qsize(), 8)
        payloads = []
        while not observer._queue.empty():
            event = observer._queue.get_nowait()
            payloads.append(event.payload())
            observer._consume(event)
        self.assertEqual({event["engine"] for event in payloads}, {"SPOT", "FUTURES", "AI_MARKET_PULSE", "QUANT_ARBITRAGE"})
        self.assertTrue(all(event["account_identity"] == "UNKNOWN" for event in payloads))
        from trader.opportunity_shadow import evaluate_intent
        intents = [event for event in payloads if event["kind"] == "ENTRY_INTENT"]
        self.assertTrue(all(event["limits"] == {"gross_limit": None, "capital_limit": None,
            "stop_risk_limit": None, "max_positions": None} for event in intents))
        self.assertTrue(all(evaluate_intent(event)["hypothetical_state"] == "UNKNOWN" for event in intents))
        snapshot = observer.snapshot(now=NOW+1)
        self.assertEqual(snapshot["health"]["records"], 8)
        self.assertFalse(snapshot["execution_enabled"])
        self.assertFalse(snapshot["reservations_enabled"])
        self.assertNotIn("untrusted free reason", observer.path.read_bytes().decode("latin1"))

    def test_all_adapter_producers_call_only_fixed_ingress_without_io(self):
        methods = (BinanceTestnetBroker._observe_entry, FuturesTestnetLab._observe_forward_entry,
                   MarketPulseService._observe_entry, QuantShadowService._observe_entry)
        import inspect
        import textwrap
        for method in methods:
            source = textwrap.dedent(inspect.getsource(method))
            tree = ast.parse(source)
            calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
            forbidden = {"execute", "commit", "connect", "signed_request", "public_request", "review", "join", "sleep", "put"}
            self.assertFalse(any((isinstance(func, ast.Attribute) and func.attr in forbidden)
                or (isinstance(func, ast.Name) and func.id in forbidden) for func in calls), method.__qualname__)
            self.assertIn("observe_entry_intent(", source)
