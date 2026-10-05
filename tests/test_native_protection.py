"""Exchange lifecycle tests with durable temporary ledgers, no credentials."""
import json
import hashlib
import hmac
import importlib
import tempfile
import unittest
from urllib.parse import urlsplit, parse_qs
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.database import Database
from trader.domain import Position, Signal
from trader.futures_forward import FuturesForwardEngine
from trader.native_protection import FUTURES_KEY, SPOT_KEY, FuturesNativeProtection, price_tick, projection
from trader.testnet_broker import BinanceTestnetBroker
from trader.testnet_transport import TestnetExecutionError


INFO = {"symbol": "BTCUSDT", "baseAsset": "BTC", "ocoAllowed": True,
    "orderTypes": ["MARKET", "STOP_LOSS", "TAKE_PROFIT"], "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01", "minPrice": "0.01", "maxPrice": "1000000"},
        {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "10", "stepSize": "0.001"},
        {"filterType": "MIN_NOTIONAL", "minNotional": "5", "applyToMarket": True}]}


class FuturesExchange:
    def __init__(self, engine):
        self.engine = engine; self.orders = {}; self.fills = {}; self.calls = []
        self.rows = [{"symbol": "BTCUSDT", "positionAmt": "0.1", "entryPrice": "100",
            "leverage": 1, "marginType": "isolated", "positionSide": "BOTH", "markPrice": "100"}]
        self.timeout_post = False; self.timeout_delete = False; self.race = False

    def request(self, method, endpoint, fields):
        self.calls.append((method, endpoint, dict(fields)))
        if endpoint == "/fapi/v1/order": return dict(self.fills[str(fields["orderId"])])
        identity = fields["clientAlgoId"]
        if method == "POST":
            self.orders[identity] = {"algoId": len(self.orders) + 1, "clientAlgoId": identity,
                "symbol": fields["symbol"], "orderType": fields["type"], "side": fields["side"],
                "workingType": fields["workingType"], "positionSide": fields["positionSide"],
                "closePosition": True, "triggerPrice": fields["triggerPrice"], "algoStatus": "NEW", "actualOrderId": ""}
            if self.timeout_post: raise TimeoutError("response lost")
        if method == "DELETE":
            if self.race:
                self.race = False; self.trigger(identity)
            else: self.orders[identity]["algoStatus"] = "CANCELED"
            if self.timeout_delete: raise TimeoutError("cancel response lost")
        if identity not in self.orders: raise ValueError("unknown algo id")
        return dict(self.orders[identity])

    def trigger(self, identity=None, *, partial=False):
        identity = identity or next(iter(self.orders))
        order = self.orders[identity]; order_id = str(order["algoId"] + 100)
        order.update(algoStatus="FINISHED" if not partial else "TRIGGERED", actualOrderId=order_id)
        self.fills[order_id] = {"symbol": order["symbol"], "orderId": int(order_id), "side": order["side"],
            "positionSide": "BOTH", "status": "PARTIALLY_FILLED" if partial else "FILLED",
            "executedQty": "0.05" if partial else "0.1", "avgPrice": order["triggerPrice"]}
        self.rows = [] if not partial else [{**self.rows[0], "positionAmt": "0.05"}]


class FuturesNativeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        config = load_config(); config = replace(config, futures_testnet=replace(config.futures_testnet,
            database_path=Path(temp.name) / "f.db", kill_switch_path=Path(temp.name) / "KILL"))
        self.engine = FuturesForwardEngine(config, None)
        self.position = {"symbol": "BTCUSDT", "direction": "LONG", "leverage": 1, "quantity": 0.1,
            "entry_price": 100.0, "stop_price": 95.0, "take_profit": 110.0, "liquidation_price": None,
            "signal_score": 80, "opened_at": "2026-10-03T12:00:00Z"}
        self.engine.ledger.set_forward_position(self.position)
        self.exchange = FuturesExchange(self.engine)
        for target, value in (("trader.native_protection.futures_request", self.exchange.request),):
            patcher = patch(target, side_effect=value); patcher.start(); self.addCleanup(patcher.stop)
        for obj, name, kwargs in ((self.engine, "_actual_rows", {"side_effect": lambda symbol: self.exchange.rows}),
            (self.engine, "_validated_rows", {"side_effect": lambda symbol, local: self.exchange.rows}),
            (self.engine.lab, "_symbol_info", {"return_value": INFO})):
            patcher = patch.object(obj, name, **kwargs); patcher.start(); self.addCleanup(patcher.stop)

    def arm(self): self.engine.native.ensure(self.position)

    def test_pair_is_close_only_and_uses_mark_price(self):
        self.arm()
        writes = [fields for method, _, fields in self.exchange.calls if method == "POST"]
        self.assertEqual(len(writes), 2)
        self.assertEqual({row["type"] for row in writes}, {"STOP_MARKET", "TAKE_PROFIT_MARKET"})
        for row in writes:
            self.assertEqual(row["workingType"], "MARK_PRICE"); self.assertEqual(row["closePosition"], "true")
            self.assertNotIn("quantity", row); self.assertNotIn("reduceOnly", row)
        self.assertEqual(self.engine.native.records()["BTCUSDT"]["status"], "ARMED")

    def test_short_has_buy_closes_and_correct_trigger_rounding(self):
        self.position.update(direction="SHORT", stop_price=105.009, take_profit=90.009)
        self.engine.ledger.set_forward_position(self.position)
        self.exchange.rows[0]["positionAmt"] = "-0.1"
        self.arm()
        self.assertEqual({row["side"] for row in self.exchange.orders.values()}, {"BUY"})
        self.assertEqual({row["triggerPrice"] for row in self.exchange.orders.values()}, {"105.00", "90.00"})
        self.exchange.trigger(); self.engine.native.reconcile_all()
        self.assertAlmostEqual(self.engine.ledger.forward_snapshot()["gross_pnl"], -0.5)

    def test_offline_native_fill_records_once_and_cancels_only_owned_sibling(self):
        self.arm(); self.exchange.trigger()
        self.exchange.orders["external"] = {"algoStatus": "NEW"}
        self.engine.native.reconcile_all(); self.engine.native.reconcile_all()
        snap = self.engine.ledger.forward_snapshot()
        self.assertEqual(snap["closed_trades"], 1); self.assertEqual(snap["trades"][0]["exit_reason"], "STOP")
        self.assertAlmostEqual(snap["gross_pnl"], -0.5)
        self.assertFalse(self.engine.native.records()); self.assertEqual(self.exchange.orders["external"]["algoStatus"], "NEW")

    def test_uncertain_post_recovered_by_id_without_resubmission(self):
        self.exchange.timeout_post = True
        with self.assertRaises(TimeoutError): self.arm()
        self.exchange.timeout_post = False
        self.engine.native = FuturesNativeProtection(self.engine); self.arm()
        self.assertEqual(sum(method == "POST" for method, _, _ in self.exchange.calls), 2)
        self.assertEqual(self.engine.native.records()["BTCUSDT"]["status"], "ARMED")

    def test_missing_uncertain_lookup_blocks_new_post(self):
        self.exchange.timeout_post = True
        with self.assertRaises(TimeoutError): self.arm()
        self.exchange.orders.clear(); self.exchange.timeout_post = False
        with self.assertRaisesRegex(ValueError, "unknown algo"): self.arm()
        self.assertEqual(sum(method == "POST" for method, _, _ in self.exchange.calls), 1)

    def test_accounting_commit_then_cleanup_crash_does_not_duplicate_trade(self):
        self.arm(); self.exchange.trigger(); self.exchange.timeout_delete = True
        with self.assertRaises(TimeoutError): self.engine.native.reconcile_all()
        self.assertIsNone(self.engine.ledger.forward_position("BTCUSDT"))
        self.exchange.timeout_delete = False; self.engine.native.reconcile_all()
        self.assertEqual(self.engine.ledger.forward_snapshot()["closed_trades"], 1)
        self.assertFalse(self.engine.native.records())

    def test_stop_during_manual_cancel_never_sends_second_market_close(self):
        self.arm(); self.exchange.race = True
        with patch.object(self.engine.lab, "forward_submit") as submit:
            result = self.engine._close(self.position, "OPPOSITE_SIGNAL")
            submit.assert_not_called()
        self.assertEqual(result["exit_reason"], "STOP")

    def test_partial_trigger_blocks_accounting_and_additional_writes(self):
        self.arm(); self.exchange.trigger(partial=True)
        before = len(self.exchange.calls)
        with self.assertRaisesRegex(ValueError, "unresolved or partial"): self.engine.native.reconcile_all()
        self.assertEqual(self.engine.ledger.forward_snapshot()["closed_trades"], 0)
        self.assertFalse(any(method in {"POST", "DELETE"} for method, _, _ in self.exchange.calls[before:]))

    def test_wrong_exchange_identity_blocks_cancellation(self):
        self.arm(); next(iter(self.exchange.orders.values()))["side"] = "BUY"
        with self.assertRaisesRegex(ValueError, "identity/status"): self.engine.native.reconcile("BTCUSDT", cancel=True)
        self.assertFalse(any(method == "DELETE" for method, _, _ in self.exchange.calls))

    def test_native_close_clears_stale_open_journal_without_evidence_gap(self):
        self.arm(); self.engine.ledger.set_setting("forward_pending_order", {"symbol": "BTCUSDT", "reduce_only": False})
        self.exchange.trigger(); self.assertIsNone(self.engine._recover_journal())
        self.assertIsNone(self.engine.ledger.setting("forward_pending_order"))
        self.assertIsNone(self.engine.ledger.setting("forward_evidence_gap"))

    def test_killed_engine_reconciles_fill_on_protection_tick(self):
        self.arm(); self.engine._halt("owner pause"); self.exchange.trigger()
        self.engine.protection_tick()
        self.assertTrue(self.engine.killed()); self.assertEqual(self.engine.ledger.forward_snapshot()["closed_trades"], 1)

    def test_flat_without_fill_evidence_never_fabricates_trade(self):
        self.arm(); self.exchange.rows = []
        # No native fill; existing engine identity guard must fail closed.
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            self.engine.native.reconcile_all()
        self.assertEqual(self.engine.ledger.forward_snapshot()["closed_trades"], 0)

    def test_definite_rejection_preserves_local_protective_close(self):
        from trader.futures_testnet_transport import FuturesTestnetExecutionError
        with patch("trader.native_protection.futures_request", side_effect=FuturesTestnetExecutionError("invalid filter", code=-1013)):
            with self.assertRaises(FuturesTestnetExecutionError): self.arm()
        record = self.engine.native.records()["BTCUSDT"]
        self.assertEqual(record["legs"][0]["state"], "REJECTED")
        self.engine.native.reconcile_all()  # no query of an explicitly rejected id
        with patch.object(self.engine.lab, "forward_submit", return_value={"avgPrice": "94"}) as submit, \
             patch.object(self.engine, "_actual_rows", side_effect=[self.exchange.rows, []]):
            trade = self.engine._close(self.position, "STOP")
        submit.assert_called_once(); self.assertEqual(trade["exit_reason"], "STOP")


class SpotExchange:
    def __init__(self, broker):
        self.broker = broker; self.orders = {}; self.lists = {}; self.calls = []
        self.timeout_post = False; self.timeout_delete = False; self.race = False
        self.free = Decimal("10")

    def request(self, method, endpoint, fields):
        self.calls.append((method, endpoint, dict(fields)))
        if endpoint == "/api/v3/account":
            return {"balances": [{"asset": "BTC", "free": str(self.free), "locked": "0"},
                {"asset": "USDT", "free": "1000", "locked": "0"}]}
        if endpoint == "/api/v3/orderList/oco":
            list_id = len(self.lists) + 1; members = []
            for prefix in ("above", "below"):
                identity = fields[prefix + "ClientOrderId"]; oid = len(self.orders) + 1
                self.orders[identity] = {"symbol": fields["symbol"], "clientOrderId": identity, "orderId": oid,
                    "orderListId": list_id, "side": "SELL", "status": "NEW", "type": fields[prefix + "Type"],
                    "stopPrice": fields[prefix + "StopPrice"], "origQty": fields["quantity"], "executedQty": "0", "cummulativeQuoteQty": "0"}
                members.append({"symbol": fields["symbol"], "clientOrderId": identity, "orderId": oid})
            self.lists[fields["listClientOrderId"]] = {"symbol": fields["symbol"], "listClientOrderId": fields["listClientOrderId"],
                "orderListId": list_id, "contingencyType": "OCO", "listOrderStatus": "EXECUTING", "orders": members}
            self.free = Decimal("0")
            if self.timeout_post: raise TimeoutError("OCO response lost")
            return dict(self.lists[fields["listClientOrderId"]])
        if endpoint == "/api/v3/orderList":
            identity = fields.get("origClientOrderId", fields.get("listClientOrderId"))
            if method == "DELETE":
                if self.race: self.race = False; self.trigger(identity)
                else:
                    for member in self.lists[identity]["orders"]:
                        self.orders[member["clientOrderId"]]["status"] = "CANCELED"
                    self.lists[identity]["listOrderStatus"] = "ALL_DONE"; self.free = Decimal("10")
                if self.timeout_delete: raise TimeoutError("cancel response lost")
            if identity not in self.lists: raise TestnetExecutionError("OCO not found")
            return dict(self.lists[identity])
        if endpoint == "/api/v3/order":
            if method == "GET": return dict(self.orders[fields["origClientOrderId"]])
            quantity = fields["quantity"]; price = Decimal("100")
            return {"symbol": fields["symbol"], "clientOrderId": fields["newClientOrderId"], "side": fields["side"],
                "status": "FILLED", "executedQty": quantity, "cummulativeQuoteQty": str(Decimal(quantity) * price),
                "fills": [{"commission": "0", "commissionAsset": "USDT"}]}
        if endpoint == "/api/v3/myTrades": return [{"commission": "0.01", "commissionAsset": "USDT"}]
        raise AssertionError((method, endpoint, fields))

    def trigger(self, identity=None, *, partial=False):
        identity = identity or next(iter(self.lists)); order_list = self.lists[identity]
        for member in order_list["orders"]:
            order = self.orders[member["clientOrderId"]]
            if order["type"] == "STOP_LOSS":
                quantity = Decimal(order["origQty"]) / (2 if partial else 1)
                order.update(status="PARTIALLY_FILLED" if partial else "FILLED", executedQty=str(quantity),
                    cummulativeQuoteQty=str(quantity * Decimal(order["stopPrice"])))
            else: order["status"] = "CANCELED"
        order_list["listOrderStatus"] = "EXECUTING" if partial else "ALL_DONE"


class SpotNativeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.config = load_config(); self.db = Database(Path(temp.name) / "s.db")
        self.broker = BinanceTestnetBroker(self.db, self.config.paper, self.config.risk)
        self.position = Position("BTCUSDT", 0.1, 100, 95, 110, 100, 2, 0.01, "2026-10-03T12:00:00Z")
        self.db.upsert_position(self.position)
        self.exchange = SpotExchange(self.broker)
        patcher = patch("trader.testnet_broker.signed_request", side_effect=self.exchange.request)
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch("trader.exchange.BinanceClient"); self.client = patcher.start().return_value; self.addCleanup(patcher.stop)
        self.client.testnet_symbol_info.return_value = INFO; self.client.testnet_reference_price.return_value = 100.0

    def arm(self): self.broker.native.ensure(self.position)

    def test_oco_pair_and_durable_intent_precede_post(self):
        original = self.exchange.request
        def request(method, endpoint, fields):
            if method == "POST":
                record = json.loads(self.db.setting(SPOT_KEY))["BTCUSDT"]
                self.assertEqual(record["state"], "SENDING"); self.assertEqual(record["id"], fields["listClientOrderId"])
            return original(method, endpoint, fields)
        with patch("trader.testnet_broker.signed_request", side_effect=request): self.arm()
        record = self.broker.native.records()["BTCUSDT"]
        self.assertEqual(record["status"], "ARMED")
        self.assertEqual({order["type"] for order in self.exchange.orders.values()}, {"STOP_LOSS", "TAKE_PROFIT"})

    def test_native_fill_after_restart_accounts_fees_once(self):
        self.arm(); self.exchange.trigger(); before = self.db.cash()
        self.broker = BinanceTestnetBroker(self.db, self.config.paper, self.config.risk)
        self.broker.reconcile_pending(); self.broker.reconcile_pending()
        self.assertIsNone(self.db.position("BTCUSDT")); self.assertAlmostEqual(self.db.cash() - before, 9.49)
        trade = self.db.recent("trades", 1)[0]
        self.assertAlmostEqual(trade["realized_pnl"], -0.52)
        self.assertEqual(trade["reason"], "TESTNET protective stop"); self.assertFalse(self.broker.native.records())
        self.assertFalse(self.db.setting(self.broker.PENDING_KEY))

    def test_uncertain_oco_post_recovers_without_second_post(self):
        self.exchange.timeout_post = True
        with self.assertRaises(TimeoutError): self.arm()
        self.exchange.timeout_post = False; self.arm()
        self.assertEqual(sum(method == "POST" for method, _, _ in self.exchange.calls), 1)

    def test_uncertain_missing_oco_lookup_blocks_new_orders(self):
        self.exchange.timeout_post = True
        with self.assertRaises(TimeoutError): self.arm()
        self.exchange.lists.clear(); self.exchange.timeout_post = False
        with self.assertRaisesRegex(TestnetExecutionError, "OCO not found"): self.arm()
        self.assertEqual(sum(method == "POST" for method, _, _ in self.exchange.calls), 1)

    def test_manual_close_cancels_locked_oco_before_balance_and_market_order(self):
        self.arm(); before = len(self.exchange.calls)
        self.broker.sell(self.position, 100, "trend exit")
        calls = self.exchange.calls[before:]; methods = [(m, e) for m, e, _ in calls]
        self.assertLess(methods.index(("DELETE", "/api/v3/orderList")), methods.index(("GET", "/api/v3/account")))
        self.assertEqual(methods[-1], ("POST", "/api/v3/order")); self.assertIsNone(self.db.position("BTCUSDT"))

    def test_cancel_fill_race_avoids_duplicate_market_sell(self):
        self.arm(); self.exchange.race = True
        pnl = self.broker.sell(self.position, 100, "trend exit")
        self.assertAlmostEqual(pnl, -0.52)
        self.assertFalse(any(method == "POST" and endpoint == "/api/v3/order" for method, endpoint, _ in self.exchange.calls))

    def test_cancel_timeout_followed_by_read_confirmation(self):
        self.arm(); self.exchange.timeout_delete = True
        with self.assertRaises(TimeoutError): self.broker.sell(self.position, 100, "trend exit")
        self.exchange.timeout_delete = False; self.broker.sell(self.position, 100, "trend exit")
        self.assertEqual(sum(method == "DELETE" for method, _, _ in self.exchange.calls), 1)

    def test_partial_fill_stays_unaccounted_and_blocks_local_sell(self):
        self.arm(); self.exchange.trigger(partial=True)
        with self.assertRaisesRegex(TestnetExecutionError, "awaits reconciliation"): self.broker.sell(self.position, 94, "protective stop")
        self.assertEqual(self.db.position("BTCUSDT").quantity, 0.1)
        self.assertFalse(self.db.recent("trades", 10))

    def test_trailing_replaces_only_after_old_pair_is_terminal(self):
        self.arm(); self.client.testnet_reference_price.return_value = 107.0
        updated, _ = self.broker.protect(self.position, 107.0, 2.0)
        self.assertGreater(updated.stop_price, self.position.stop_price)
        methods = [(m, e) for m, e, _ in self.exchange.calls]
        self.assertEqual(methods.count(("POST", "/api/v3/orderList/oco")), 2)
        self.assertEqual(methods.count(("DELETE", "/api/v3/orderList")), 1)
        self.assertEqual(self.broker.native.records()["BTCUSDT"]["stop_price"], price_tick(INFO, updated.stop_price))

    def test_wrong_member_quantity_blocks_accounting_and_cancel(self):
        self.arm(); next(iter(self.exchange.orders.values()))["origQty"] = "1"
        with self.assertRaisesRegex(TestnetExecutionError, "quantity/trigger"): self.broker.native.reconcile("BTCUSDT", cancel=True)
        self.assertFalse(any(method == "DELETE" for method, _, _ in self.exchange.calls))

    def test_receipt_replay_after_native_accounting_crash_is_idempotent(self):
        self.arm(); self.exchange.trigger()
        from trader.native_protection import SpotNativeProtection
        real_save = SpotNativeProtection.save
        def crash_after_fill(manager, records):
            if not records: raise RuntimeError("crash before journal cleanup")
            real_save(manager, records)
        with patch.object(SpotNativeProtection, "save", crash_after_fill):
            with self.assertRaisesRegex(RuntimeError, "crash before"): self.broker.native.reconcile_all()
        cash = self.db.cash(); self.broker.native.reconcile_all()
        self.assertEqual(self.db.cash(), cash); self.assertEqual(len(self.db.recent("trades", 10)), 1)

    def test_unsupported_native_market_orders_block_buy_before_post(self):
        self.db.delete_position("BTCUSDT"); self.client.testnet_symbol_info.return_value = {**INFO, "ocoAllowed": False}
        signal = Signal("BTCUSDT", "BUY", 80, 100, 95, 110, 2, 60, 101, 99, 1.3, "unit", "now")
        with self.assertRaisesRegex(TestnetExecutionError, "unavailable"): self.broker.buy(signal, 0.1, "test")
        self.assertFalse(any(method == "POST" for method, _, _ in self.exchange.calls))

    def test_actual_buy_installs_pair_before_returning_success(self):
        self.db.delete_position("BTCUSDT")
        signal = Signal("BTCUSDT", "BUY", 80, 100, 95, 110, 2, 60, 101, 99, 1.3, "unit", "now")
        self.broker.buy(signal, 0.1, "test")
        self.assertEqual(self.broker.native.records()["BTCUSDT"]["status"], "ARMED")

    def test_dust_is_never_reported_as_armed(self):
        dust = replace(self.position, quantity=0.00001); self.db.upsert_position(dust)
        with self.assertRaisesRegex(TestnetExecutionError, "dust"): self.broker.native.ensure(dust)
        self.assertFalse(self.broker.native.records())

    def test_definite_oco_rejection_keeps_local_stop_available(self):
        original = self.exchange.request
        def reject_oco(method, endpoint, fields):
            if endpoint == "/api/v3/orderList/oco":
                raise TestnetExecutionError("Testnet HTTP 400 · Binance -1013: Filter failure: NOTIONAL", code=-1013)
            return original(method, endpoint, fields)
        with patch("trader.testnet_broker.signed_request", side_effect=reject_oco):
            with self.assertRaises(TestnetExecutionError): self.arm()
        self.assertEqual(self.broker.native.records()["BTCUSDT"]["state"], "REJECTED")
        calls_before = len(self.exchange.calls)
        with self.assertRaises(TestnetExecutionError) as caught:
            self.broker.native.ensure(self.position)
        self.assertEqual(caught.exception.code, -1013)
        self.assertEqual(caught.exception.api_message, 'Filter failure: NOTIONAL')
        self.assertEqual(len(self.exchange.calls), calls_before)
        self.broker.sell(self.position, 94, "protective stop")
        self.assertIsNone(self.db.position("BTCUSDT"))

    def test_native_receipt_does_not_overwrite_unrelated_pending_market_order(self):
        self.arm(); self.exchange.trigger()
        self.broker._save_pending({"client_order_id": "other", "symbol": "ETHUSDT"})
        self.broker.native.reconcile_all()
        self.assertEqual(self.broker._pending()["client_order_id"], "other")


class NativeFilterTests(unittest.TestCase):
    def test_rounding_is_conservative_for_long_and_short(self):
        self.assertEqual(price_tick(INFO, 95.001), "95.01")
        self.assertEqual(price_tick(INFO, 105.009, up=False), "105.00")
        for value in ("NaN", "Infinity", 0, -1):
            with self.assertRaises(ValueError): price_tick(INFO, value)

    def test_projection_exposes_evidence_without_client_ids(self):
        value = projection({"BTCUSDT": {"status": "UNCONFIRMED", "id": "private-id", "error": "uncertain"}})
        self.assertEqual(value["positions"]["BTCUSDT"]["status"], "UNCONFIRMED")
        self.assertNotIn("private-id", json.dumps(value))


class NativeCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.target = self.root / "previous"; self.target.mkdir()
        (self.root / "config.toml").write_text('[bot]\nmode="testnet"\ntestnet_database_path="s.db"\nfutures_testnet_database_path="f.db"\n')
        self.db = Database(self.root / "s.db")

    def test_old_code_blocked_until_owned_orders_are_terminal(self):
        from trader.native_protection_compat import require_native_compatible
        self.db.set_setting(SPOT_KEY, '{"BTCUSDT":{"state":"SENDING"}}')
        with self.assertRaisesRegex(RuntimeError, "cannot resume"): require_native_compatible(self.root, self.target)
        self.db.set_setting(SPOT_KEY, '{}'); require_native_compatible(self.root, self.target)

    def test_native_capable_previous_code_can_resume_with_existing_journal(self):
        from trader.native_protection_compat import require_native_compatible
        self.db.set_setting(SPOT_KEY, '{"BTCUSDT":{"state":"SENDING"}}')
        (self.target / "trader").mkdir(); (self.target / "trader/native_protection.py").write_text('NATIVE_PROTECTION_PROTOCOL = 1\n')
        require_native_compatible(self.root, self.target)

    def test_unreadable_ledger_blocks_downgrade(self):
        from trader.native_protection_compat import require_native_compatible
        (self.root / "f.db").write_bytes(b'broken sqlite')
        with self.assertRaisesRegex(RuntimeError, "could not be verified"): require_native_compatible(self.root, self.target)


class NativeTransportTests(unittest.TestCase):
    def test_delete_signatures_and_hosts_for_both_test_environments(self):
        from unittest.mock import MagicMock
        for name, endpoint, fields, key_name, secret_name, opener_name in (
            ("futures_testnet_transport", "/fapi/v1/algoOrder", {"clientAlgoId": "owned"},
             "BINANCE_FUTURES_TESTNET_API_KEY", "BINANCE_FUTURES_TESTNET_API_SECRET", "_signed_opener"),
            ("testnet_transport", "/api/v3/orderList", {"symbol": "BTCUSDT", "listClientOrderId": "owned"},
             "BINANCE_API_KEY", "BINANCE_API_SECRET", None)):
            module = importlib.import_module("trader." + name)
            opener = MagicMock(); opener.open.return_value.__enter__.return_value.read.return_value = b'{}'
            target = "trader." + name + ("." + opener_name if opener_name else ".urllib.request.build_opener")
            with self.subTest(name=name), patch.dict("os.environ", {key_name: "synthetic-key", secret_name: "synthetic-secret"}), \
                 patch(target, return_value=opener):
                module.signed_request("DELETE", endpoint, fields)
            request = opener.open.call_args.args[0]
            parsed = urlsplit(request.full_url); query, signature = parsed.query.rsplit("&signature=", 1)
            self.assertEqual(parsed.scheme + "://" + parsed.netloc, module.HOST)
            self.assertEqual(request.method, "DELETE"); self.assertIsNone(request.data)
            self.assertEqual(signature, hmac.new(b'synthetic-secret', query.encode(), hashlib.sha256).hexdigest())
            self.assertIn("timestamp", parse_qs(query)); self.assertEqual(parsed.path, endpoint)

    def test_cancel_all_and_production_routes_stay_blocked(self):
        from trader.futures_testnet_transport import signed_request as futures
        from trader.testnet_transport import signed_request as spot
        for request, endpoint in ((futures, "/fapi/v1/allOpenOrders"), (spot, "/api/v3/openOrders"),
                                  (futures, "https://fapi.binance.com/fapi/v1/algoOrder")):
            with self.assertRaisesRegex(ValueError, "endpoint blocked"): request("DELETE", endpoint, {})
