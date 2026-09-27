import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.database import Database
from trader.domain import Signal
from trader.engine import TradingEngine
from trader.testnet_broker import BinanceTestnetBroker
from trader.testnet_transport import TestnetExecutionError


class UnifiedTestnetBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = load_config()
        self.db = Database(Path(self.temp.name) / "testnet.db")
        self.broker = BinanceTestnetBroker(self.db, self.config.paper, self.config.risk)
        self.db.record_market_snapshot({"BTCUSDT": 100.0})
        self.signal = Signal(
            "BTCUSDT", "BUY", 80, 100.0, 95.0, 110.0, 2.0, 60.0,
            101.0, 99.0, 1.3, "unit", "now",
        )
        self.info = {
            "symbol": "BTCUSDT",
            "baseAsset": "BTC",
            "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "10", "stepSize": "0.001"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5", "applyToMarket": True},
            ],
        }

    def test_filled_testnet_buy_updates_local_accounting_from_exchange_fill(self):
        def signed(method, endpoint, fields):
            if endpoint == "/api/v3/account":
                return {"balances": [{"asset": "USDT", "free": "1000", "locked": "0"}]}
            self.assertEqual((method, endpoint), ("POST", "/api/v3/order"))
            return {
                "symbol": "BTCUSDT",
                "clientOrderId": fields["newClientOrderId"],
                "side": "BUY",
                "status": "FILLED",
                "executedQty": "0.1",
                "cummulativeQuoteQty": "10",
                "fills": [{"commission": "0.01", "commissionAsset": "USDT"}],
            }

        with patch("trader.exchange.BinanceClient") as client,              patch("trader.testnet_broker.signed_request", side_effect=signed):
            client.return_value.testnet_symbol_info.return_value = self.info
            client.return_value.testnet_reference_price.return_value = 100.0
            position = self.broker.buy(self.signal, 0.1, "automatic testnet")

        self.assertAlmostEqual(position.quantity, 0.1)
        self.assertAlmostEqual(position.entry_price, 100.0)
        self.assertAlmostEqual(self.db.cash(), 989.99)
        self.assertEqual(self.db.recent("trades", 1)[0]["reason"], "TESTNET automatic testnet")
        self.assertFalse(self.db.setting(self.broker.PENDING_KEY))

    def test_buy_blocks_when_testnet_price_moves_outside_signal_protection(self):
        with patch("trader.exchange.BinanceClient") as client, \
             patch("trader.testnet_broker.signed_request", side_effect=AssertionError("no signed write expected")):
            client.return_value.testnet_symbol_info.return_value = self.info
            client.return_value.testnet_reference_price.return_value = 120.0
            with self.assertRaisesRegex(TestnetExecutionError, "outside signal protection range"):
                self.broker.buy(self.signal, 0.1, "blocked")

    def test_terminal_reconciliation_reads_mytrades_before_accounting_fees(self):
        pending = {
            "client_order_id": "cait-auto-test",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "planned_qty": "0.1",
            "base_asset": "BTC",
            "reason": "reconciled",
            "signal": self.signal.to_dict(),
            "created_at": "2026-09-27T12:00:00+00:00",
            "status": "UNCERTAIN",
        }
        self.broker._save_pending(pending)
        def signed(method, endpoint, fields):
            if endpoint == "/api/v3/order":
                return {
                    "symbol": "BTCUSDT", "clientOrderId": "cait-auto-test",
                    "side": "BUY", "status": "FILLED", "executedQty": "0.1",
                    "cummulativeQuoteQty": "10", "orderId": 77,
                }
            if endpoint == "/api/v3/myTrades":
                self.assertEqual(fields["orderId"], 77)
                return [{"commission": "0.01", "commissionAsset": "USDT"}]
            raise AssertionError((method, endpoint, fields))
        with patch("trader.testnet_broker.signed_request", side_effect=signed):
            self.assertTrue(self.broker.reconcile_pending())
        self.assertFalse(self.db.setting(self.broker.PENDING_KEY))
        self.assertAlmostEqual(self.db.cash(), 989.99)
        self.assertAlmostEqual(self.db.position("BTCUSDT").entry_fee, 0.01)

    def test_filled_buy_anchors_protection_levels_to_actual_fill(self):
        def signed(method, endpoint, fields):
            if endpoint == "/api/v3/account":
                return {"balances": [{"asset": "USDT", "free": "1000", "locked": "0"}]}
            return {
                "symbol": "BTCUSDT", "clientOrderId": fields["newClientOrderId"],
                "side": "BUY", "status": "FILLED", "executedQty": "0.1",
                "cummulativeQuoteQty": "10.5", "fills": [],
                "orderId": 88,
            }
        with patch("trader.exchange.BinanceClient") as client, \
             patch("trader.testnet_broker.signed_request", side_effect=signed):
            client.return_value.testnet_symbol_info.return_value = self.info
            client.return_value.testnet_reference_price.return_value = 100.0
            position = self.broker.buy(self.signal, 0.1, "fill drift")
        self.assertAlmostEqual(position.entry_price, 105.0)
        self.assertAlmostEqual(position.stop_price, 99.75)
        self.assertAlmostEqual(position.take_profit, 115.5)

    def test_uncertain_post_is_never_retried_while_exchange_order_is_open(self):
        posts = 0

        def signed(method, endpoint, fields):
            nonlocal posts
            if endpoint == "/api/v3/account":
                return {"balances": [{"asset": "USDT", "free": "1000", "locked": "0"}]}
            if method == "POST":
                posts += 1
                raise TestnetExecutionError("uncertain")
            pending = json.loads(self.db.setting(self.broker.PENDING_KEY))
            return {
                "symbol": "BTCUSDT",
                "clientOrderId": pending["client_order_id"],
                "side": "BUY",
                "status": "NEW",
                "executedQty": "0",
                "cummulativeQuoteQty": "0",
            }

        with patch("trader.exchange.BinanceClient") as client,              patch("trader.testnet_broker.signed_request", side_effect=signed):
            client.return_value.testnet_symbol_info.return_value = self.info
            client.return_value.testnet_reference_price.return_value = 100.0
            with self.assertRaises(TestnetExecutionError):
                self.broker.buy(self.signal, 0.1, "first")
            with self.assertRaisesRegex(TestnetExecutionError, "still pending"):
                self.broker.buy(self.signal, 0.1, "second")
        self.assertEqual(posts, 1)

    def test_engine_selects_testnet_broker_only_for_explicit_testnet_mode(self):
        config = replace(
            self.config,
            bot=replace(
                self.config.bot,
                mode="testnet",
                database_path=Path(self.temp.name) / "engine.db",
                kill_switch_path=Path(self.temp.name) / "KILL",
            ),
        )
        engine = TradingEngine(config)
        self.assertIsInstance(engine.broker, BinanceTestnetBroker)

    def test_live_mode_is_rejected_by_configuration(self):
        with patch.dict("os.environ", {"EXECUTION_MODE": "live"}):
            with self.assertRaisesRegex(ValueError, "LIVE is not implemented"):
                load_config()


if __name__ == "__main__":
    unittest.main()
