import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

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

    def test_default_forward_test_is_btc_only_and_one_x(self):
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

    def test_legacy_forward_environment_override_does_not_disable_configured_pilot(self):
        import os
        with patch.dict(os.environ, {"FUTURES_FORWARD_ENABLED": "false"}):
            configured = load_config()
        self.assertTrue(configured.futures_testnet.forward_enabled)

    def test_futures_daily_loss_limit_halts_only_futures_entries(self):
        ledger = self.engine.ledger
        today = __import__("datetime").datetime.now(__import__("datetime").UTC).date().isoformat()
        week_start = (__import__("datetime").datetime.now(__import__("datetime").UTC).date()
                      - __import__("datetime").timedelta(
                          days=__import__("datetime").datetime.now(__import__("datetime").UTC).weekday()
                      )).isoformat()
        ledger.set_setting("forward_daily_baseline", {"key": today, "wallet": 5000.0})
        ledger.set_setting("forward_weekly_baseline", {"key": week_start, "wallet": 5000.0})
        state = self.engine._loss_circuit_breaker(4890.0)
        self.assertTrue(state["halted"])
        self.assertEqual(state["reason"], "DAILY_LOSS_LIMIT")
        self.assertTrue(self.config.futures_testnet.kill_switch_path.exists())
        self.assertFalse(self.config.bot.kill_switch_path.exists())

    def test_future_live_policy_is_hard_disabled_and_bounded(self):
        self.assertFalse(self.config.live_safety.enabled)
        self.assertEqual(self.config.live_safety.capital_cap_usdt, 250.0)
        self.assertEqual(self.config.live_safety.spot_symbol_whitelist, ("BTCUSDT", "ETHUSDT"))
        self.assertFalse(self.config.live_safety.withdrawals_enabled)
        self.assertFalse(self.config.live_safety.margin_enabled)
        self.assertFalse(self.config.live_safety.futures_enabled)

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
