import tempfile
import unittest
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
