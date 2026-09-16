import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from trader.config import load_config
from trader.domain import Candle, Position
from trader.engine import TradingEngine


class EngineTests(unittest.TestCase):
    def test_live_price_can_trigger_protective_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(
                config,
                bot=replace(
                    config.bot,
                    database_path=Path(folder) / "test.db",
                    kill_switch_path=Path(folder) / "KILL_SWITCH",
                ),
            )
            engine = TradingEngine(config)
            engine.db.initialize_cash(config.paper.initial_cash_usdt)
            engine.db.upsert_position(
                Position("TESTUSDT", 1.0, 100.0, 95.0, 120.0, 100.0, 2.0, 0.1, "now")
            )
            candles = [
                Candle(i * 1000, 99.0, 102.0, 98.0, 100.0, 1000.0, i * 1000 + 999)
                for i in range(80)
            ]

            engine._manage_positions({"TESTUSDT": candles}, {"TESTUSDT": 94.0})

            self.assertEqual(engine.db.positions(), [])
            trade = engine.db.recent("trades", 1)[0]
            self.assertEqual(trade["side"], "SELL")
            self.assertEqual(trade["reason"], "protective stop")


if __name__ == "__main__":
    unittest.main()
