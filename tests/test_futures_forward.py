import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.domain import Candle
from trader.futures_forward import FuturesForwardEngine
from trader.futures_testnet_ledger import FuturesTestnetLedger


class FuturesForwardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = load_config()
        futures = replace(
            base.futures_testnet,
            database_path=Path(self.temp.name) / "futures-forward.db",
            kill_switch_path=Path(self.temp.name) / "FUTURES_KILL_SWITCH",
        )
        self.config = replace(base, futures_testnet=futures)
        self.engine = FuturesForwardEngine(self.config, exchange=None)

    @staticmethod
    def candles(up=True):
        rows = []
        base = 100.0
        for index in range(90):
            price = base + index if up else base + (90 - index)
            if index == 89:
                price += 5 if up else -5
            rows.append(Candle(
                open_time=index * 1000,
                open=price - 0.2,
                high=price + 0.5,
                low=price - 0.5,
                close=price,
                volume=200.0 if index == 89 else 100.0,
                close_time=index * 1000 + 999,
            ))
        return rows

    def test_stale_env_cannot_disable_signed_forward_test(self):
        with patch.dict("os.environ", {"FUTURES_FORWARD_ENABLED": "false"}):
            config = load_config()
        self.assertTrue(config.futures_testnet.forward_enabled)

    def test_stale_env_cannot_disable_signed_forward_test(self):
        with patch.dict("os.environ", {"FUTURES_FORWARD_ENABLED": "false"}):
            config = load_config()
        self.assertTrue(config.futures_testnet.forward_enabled)

    def test_default_forward_test_is_btc_only_and_one_x(self):
        self.assertEqual(self.config.bot.mode, "testnet")
        self.assertTrue(self.config.futures_testnet.forward_enabled)
        self.assertEqual(self.config.futures_testnet.forward_symbol, "BTCUSDT")
        self.assertEqual(self.config.futures_testnet.forward_leverage, 1)
        self.assertEqual(self.config.futures_testnet.forward_margin_usdt, 100.0)

    def test_signal_supports_long_and_short_symmetrically(self):
        long_signal = self.engine._signal(self.candles(True))
        short_signal = self.engine._signal(self.candles(False))
        self.assertEqual(long_signal["direction"], "LONG")
        self.assertGreaterEqual(long_signal["score"], self.config.futures_testnet.forward_min_score)
        self.assertEqual(short_signal["direction"], "SHORT")
        self.assertGreaterEqual(short_signal["score"], self.config.futures_testnet.forward_min_score)

    def test_forward_scorecard_tracks_return_drawdown_direction_and_errors(self):
        ledger = FuturesTestnetLedger(self.config.futures_testnet.database_path)
        with ledger._connect() as db:
            db.execute("INSERT INTO forward_equity(wallet_balance,available_balance,unrealized_pnl,created_at) VALUES(?,?,?,?)",
                       (5000.0, 5000.0, 0.0, "2026-09-01T00:00:00+00:00"))
            db.execute("INSERT INTO forward_equity(wallet_balance,available_balance,unrealized_pnl,created_at) VALUES(?,?,?,?)",
                       (4900.0, 4900.0, 0.0, "2026-09-15T00:00:00+00:00"))
            db.execute("INSERT INTO forward_equity(wallet_balance,available_balance,unrealized_pnl,created_at) VALUES(?,?,?,?)",
                       (5100.0, 5100.0, 0.0, "2026-10-02T00:00:00+00:00"))
            db.execute("""INSERT INTO forward_trades(symbol,direction,leverage,quantity,entry_price,exit_price,gross_pnl,exit_reason,opened_at,closed_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       ("BTCUSDT","LONG",1,0.001,100000.0,101000.0,1.0,"TAKE_PROFIT","2026-09-02T00:00:00+00:00","2026-09-03T00:00:00+00:00"))
            db.execute("""INSERT INTO forward_trades(symbol,direction,leverage,quantity,entry_price,exit_price,gross_pnl,exit_reason,opened_at,closed_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       ("BTCUSDT","SHORT",1,0.001,100000.0,100500.0,-0.5,"STOP","2026-09-04T00:00:00+00:00","2026-09-05T00:00:00+00:00"))
        ledger.set_setting("forward_cycle_total", 100)
        ledger.set_setting("forward_error_total", 2)
        score = ledger.forward_scorecard()
        self.assertGreaterEqual(score["observed_days"], 30)
        self.assertEqual(score["closed_trades"], 2)
        self.assertEqual(score["long_closed_trades"], 1)
        self.assertEqual(score["short_closed_trades"], 1)
        self.assertAlmostEqual(score["gross_realized_pnl_usdt"], 0.5)
        self.assertAlmostEqual(score["account_return_pct"], 2.0)
        self.assertAlmostEqual(score["sampled_max_drawdown_pct"], 2.0)
        self.assertAlmostEqual(score["profit_factor"], 2.0)
        self.assertEqual(score["error_total"], 2)
        self.assertEqual(score["cycle_total"], 100)
        self.assertEqual(score["status"], "INSUFFICIENT_EVIDENCE")


    def test_restart_reconstructs_confirmed_open_from_durable_plan(self):
        pending = {
            "symbol": "BTCUSDT", "side": "BUY", "quantity": "0.001",
            "reduce_only": False, "client_order_id": "cait-fwd-test",
        }
        plan = {"direction": "LONG", "score": 82, "atr": 2000.0,
                "opened_at": "2026-09-26T12:00:00+00:00"}
        self.engine.ledger.set_setting("forward_pending_order", pending)
        self.engine.ledger.set_setting("forward_open_plan", plan)
        outcome = {"resolved": True, "status": "FILLED", "pending": pending,
                   "order": {"clientOrderId": "cait-fwd-test", "avgPrice": "100000",
                             "executedQty": "0.001"}}
        row = {"positionAmt": "0.001", "entryPrice": "100000",
               "liquidationPrice": "1000", "leverage": "1", "marginType": "isolated"}
        with patch.object(self.engine.lab, "reconcile_forward_pending", return_value=outcome), \
             patch.object(self.engine, "_actual_rows", return_value=[row]):
            result = self.engine._recover_journal()
        self.assertEqual(result["status"], "RECOVERED_OPEN")
        self.assertEqual(self.engine.ledger.forward_position()["direction"], "LONG")
        self.assertIsNone(self.engine.ledger.setting("forward_pending_order"))
        self.assertIsNone(self.engine.ledger.setting("forward_open_plan"))

    def test_forward_ledger_is_separate_and_persistent(self):
        ledger = FuturesTestnetLedger(self.config.futures_testnet.database_path)
        position = {
            "symbol": "BTCUSDT", "direction": "LONG", "leverage": 1,
            "quantity": 0.001, "entry_price": 100000.0, "stop_price": 97500.0,
            "take_profit": 105000.0, "liquidation_price": 100.0,
            "signal_score": 80, "opened_at": "2026-09-26T00:00:00+00:00",
        }
        ledger.set_forward_position(position)
        self.assertEqual(ledger.forward_position()["direction"], "LONG")
        ledger.record_forward_equity(5000.0, 4900.0, 2.0)
        trade = ledger.close_forward_position(exit_price=101000.0, gross_pnl=1.0, exit_reason="TAKE_PROFIT")
        self.assertEqual(trade["gross_pnl"], 1.0)
        snapshot = ledger.forward_snapshot()
        self.assertIsNone(snapshot["position"])
        self.assertEqual(snapshot["closed_trades"], 1)
        self.assertEqual(snapshot["gross_pnl"], 1.0)


if __name__ == "__main__":
    unittest.main()
