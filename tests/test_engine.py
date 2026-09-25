import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.domain import Candle, Position, Signal
from trader.engine import TradingEngine


class EngineTests(unittest.TestCase):
    def test_paper_profile_reduces_risk_and_cannot_raise_base_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(config, bot=replace(config.bot, database_path=Path(folder)/'risk.db',
                                                kill_switch_path=Path(folder)/'kill'))
            engine = TradingEngine(config)
            signal = Signal('BTCUSDT','BUY',80,100,95,110,2,60,101,99,1.3,'synthetic','now')
            normal = engine._position_size(signal,1000,1000,0,1)
            engine.db.set_setting('paper_risk_profile','prudente')
            cautious = engine._position_size(signal,1000,1000,0,1)
            engine.db.set_setting('paper_risk_profile','minimo')
            minimum = engine._position_size(signal,1000,1000,0,1)
            self.assertLess(minimum,cautious)
            self.assertLess(cautious,normal)
            engine.db.set_setting('paper_risk_profile','unexpected')
            self.assertEqual(engine._position_size(signal,1000,1000,0,1),0)

    def test_diagnostic_cleanup_keeps_financial_records_and_positions(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(config, bot=replace(config.bot, database_path=Path(folder)/'test.db',
                                                kill_switch_path=Path(folder)/'KILL_SWITCH'))
            engine = TradingEngine(config)
            engine.db.initialize_cash(1000)
            engine.db.record_equity(1000, 1000, 0, 100)
            engine.db.record_trade('BTCUSDT','BUY',0.1,100,0.01,0,'paper')
            engine.db.upsert_position(Position('BTCUSDT',0.1,100,90,120,100,2,0.01,'now'))
            engine.db.event('INFO','obsolete diagnostic')
            engine.db.record_order_preflight('BTCUSDT','incompatible',['LOT_SIZE_STEP'])
            with engine.db.connect() as db:
                db.execute("UPDATE events SET created_at='2020-01-01T00:00:00+00:00'")
                db.execute("UPDATE order_preflight SET created_at='2020-01-01T00:00:00+00:00'")
            engine._prune_diagnostics_if_due()
            self.assertFalse(engine.db.recent('events'))
            with engine.db.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM order_preflight').fetchone()[0],0)
            self.assertEqual(len(engine.db.recent('equity')),1)
            self.assertEqual(len(engine.db.recent('trades')),1)
            self.assertEqual(len(engine.db.positions()),1)
            engine._prune_diagnostics_if_due()
            self.assertEqual(len(engine.db.recent('trades')),1)

    def test_missing_or_invalid_spot_never_closes_held_position_at_candle_price(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(config, bot=replace(config.bot, database_path=Path(folder)/'test.db',
                                                kill_switch_path=Path(folder)/'KILL_SWITCH'))
            engine = TradingEngine(config)
            engine.db.upsert_position(Position('TESTUSDT', 1, 100, 95, 120, 100, 2, 0.1, 'now'))
            candles = [Candle(i*1000, 90, 92, 88, 90, 1000, i*1000+999) for i in range(80)]
            for prices in ({}, {'TESTUSDT': float('nan')}, {'TESTUSDT': 0}):
                with self.assertRaises(RuntimeError):
                    engine._manage_positions({'TESTUSDT': candles}, prices)
                self.assertIsNotNone(engine.db.position('TESTUSDT'))
                self.assertEqual(engine.db.recent('trades'), [])

    def test_missing_held_quote_blocks_cycle_before_universe_and_buy(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(config, bot=replace(config.bot, database_path=Path(folder)/'test.db',
                                                kill_switch_path=Path(folder)/'KILL_SWITCH'))
            engine = TradingEngine(config)
            engine.db.upsert_position(Position('TESTUSDT', 1, 100, 95, 120, 100, 2, 0.1, 'now'))
            with patch.object(engine.exchange, 'latest_prices', return_value={}), \
                 patch.object(engine.exchange, 'top_usdt_symbols') as universe:
                with self.assertRaises(RuntimeError):
                    engine.cycle()
                universe.assert_not_called()
            self.assertEqual(engine.db.recent('trades'), [])

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
