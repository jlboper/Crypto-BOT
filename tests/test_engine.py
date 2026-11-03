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
            config = replace(config, bot=replace(config.bot, mode='paper', database_path=Path(folder)/'risk.db',
                                                kill_switch_path=Path(folder)/'kill'))
            engine = TradingEngine(config)
            signal = Signal('BTCUSDT','BUY',80,100,95,110,2,60,101,99,1.3,'synthetic','now')
            sizes = []
            for profile in ('minimo','leve','prudente','moderado','alto','normal'):
                engine.db.set_setting('paper_risk_profile',profile)
                sizes.append(engine._position_size(signal,1000,1000,0,1))
            self.assertEqual(sizes,sorted(sizes))
            self.assertEqual(len(set(sizes)),6)
            self.assertLessEqual(sizes[-1]*signal.price, 150)  # Existing 15% cap.
            engine.db.set_setting('paper_risk_profile','unexpected')
            self.assertEqual(engine._position_size(signal,1000,1000,0,1),0)

    def test_diagnostic_cleanup_keeps_financial_records_and_positions(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(config, bot=replace(config.bot, mode='paper', database_path=Path(folder)/'test.db',
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
            config = replace(config, bot=replace(config.bot, mode='paper', database_path=Path(folder)/'test.db',
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
            config = replace(config, bot=replace(config.bot, mode='paper', database_path=Path(folder)/'test.db',
                                                kill_switch_path=Path(folder)/'KILL_SWITCH'))
            engine = TradingEngine(config)
            engine.db.upsert_position(Position('TESTUSDT', 1, 100, 95, 120, 100, 2, 0.1, 'now'))
            with patch.object(engine.exchange, 'latest_prices', return_value={}), \
                 patch.object(engine.exchange, 'top_usdt_symbols') as universe:
                with self.assertRaises(RuntimeError):
                    engine.cycle()
                universe.assert_not_called()
            self.assertEqual(engine.db.recent('trades'), [])

    def test_spot_testnet_protection_uses_testnet_execution_price(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(config, bot=replace(config.bot, mode='testnet',
                                                database_path=Path(folder)/'testnet.db',
                                                kill_switch_path=Path(folder)/'KILL_SWITCH'))
            engine = TradingEngine(config)
            engine.db.upsert_position(Position('BTCUSDT', 0.1, 100, 95, 110, 100, 2, 0.0, 'now'))
            with patch.object(engine, '_run_futures_forward_protection'), \
                 patch.object(engine.broker, 'execution_price', return_value=94.0) as venue, \
                 patch.object(engine, '_manage_positions') as manage:
                engine.protection_tick()
            venue.assert_called_once_with('BTCUSDT')
            self.assertEqual(manage.call_args.args[1], {'BTCUSDT': 94.0})

    def test_live_price_can_trigger_protective_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(
                config,
                bot=replace(
                    config.bot,
                    mode='paper',
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


    def test_expected_spot_guardrail_is_skipped_without_cycle_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(config, bot=replace(config.bot, mode='testnet',
                                                database_path=Path(folder)/'testnet.db',
                                                kill_switch_path=Path(folder)/'KILL_SWITCH'))
            engine = TradingEngine(config)
            signal = Signal('BTCUSDT','BUY',80,100,95,110,2,60,101,99,1.3,'synthetic','now')
            with patch.object(engine.broker, 'buy', side_effect=ValueError('per-trade risk limit')):
                self.assertFalse(engine._buy_or_skip_guardrail(signal, 0.1, 'test'))
            events = engine.db.recent('events', 5)
            self.assertTrue(any('PER_TRADE_RISK_LIMIT' in row['message'] for row in events))
            self.assertFalse(any(row['level'] == 'ERROR' for row in events))

    def test_unknown_value_error_remains_fatal_but_is_safely_classified(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(config, bot=replace(config.bot, mode='paper',
                                                database_path=Path(folder)/'test.db',
                                                kill_switch_path=Path(folder)/'KILL_SWITCH'))
            engine = TradingEngine(config)
            signal = Signal('BTCUSDT','BUY',80,100,95,110,2,60,101,99,1.3,'synthetic','now')
            with patch.object(engine.broker, 'buy', side_effect=ValueError('secret raw detail')):
                with self.assertRaisesRegex(ValueError, 'secret raw detail'):
                    engine._buy_or_skip_guardrail(signal, 0.1, 'test')
            projection = engine._spot_failure_projection(ValueError('secret raw detail'))
            self.assertEqual(projection['code'], 'UNEXPECTED_VALUE_ERROR')
            self.assertNotIn('secret raw detail', projection['label'])

    def test_filter_failure_after_filled_buy_is_not_misreported_as_skipped(self):
        from trader.testnet_transport import TestnetExecutionError
        with tempfile.TemporaryDirectory() as folder:
            config=load_config()
            config=replace(config,bot=replace(config.bot,mode='testnet',database_path=Path(folder)/'s.db',
                                             kill_switch_path=Path(folder)/'KILL'))
            engine=TradingEngine(config)
            signal=Signal('BTCUSDT','BUY',80,100,95,110,2,60,101,99,1.3,'synthetic','now')
            error=TestnetExecutionError('Spot native protection outside percent price filter')
            with patch.object(engine.broker,'buy',side_effect=error):
                self.assertFalse(engine._buy_or_skip_guardrail(signal,.1,'pre-write filter'))
                engine.db.upsert_position(Position('BTCUSDT',.1,100,95,110,100,2,0,'now'))
                with self.assertRaises(TestnetExecutionError):
                    engine._buy_or_skip_guardrail(signal,.1,'post-fill protection failure')

    def test_spot_exchange_incident_retains_safe_code_in_state_and_event(self):
        import json
        from trader.testnet_transport import TestnetExecutionError
        with tempfile.TemporaryDirectory() as folder:
            config = load_config()
            config = replace(config, bot=replace(config.bot, mode='paper',
                database_path=Path(folder)/'incident.db', kill_switch_path=Path(folder)/'KILL'))
            engine = TradingEngine(config)
            error = TestnetExecutionError('secret response and signed URL', code=-1021,
                api_message='secret exchange body', uncertain=False)
            with patch.object(engine.exchange, 'top_usdt_symbols', side_effect=error):
                with self.assertRaises(TestnetExecutionError):
                    engine.cycle()
            retained = json.loads(engine.db.setting('spot_last_error'))
            self.assertEqual(retained['exchange_code'], -1021)
            self.assertEqual(retained['reason_code'], 'EXCHANGE_TIMESTAMP_REJECTION')
            self.assertFalse(retained['uncertain'])
            events = [row['message'] for row in engine.db.recent('events')]
            self.assertTrue(any('EXCHANGE_TIMESTAMP_REJECTION' in row and 'Binance -1021' in row for row in events))
            self.assertNotIn('secret', json.dumps([retained, events]))

    def test_spot_uncertain_or_malformed_exchange_code_never_retains_raw_detail(self):
        import json
        from trader.testnet_transport import TestnetExecutionError
        for code in (None, True, 'secret code', -(10**12)):
            with self.subTest(code=code):
                projection = TradingEngine._spot_failure_projection(TestnetExecutionError(
                    'secret response', code=code, api_message='secret body', uncertain=True))
                self.assertIsNone(projection['exchange_code'])
                self.assertEqual(projection['reason_code'], 'TESTNET_RESPONSE_UNCERTAIN')
                self.assertTrue(projection['uncertain'])
                self.assertNotIn('secret', json.dumps(projection))



if __name__ == "__main__":
    unittest.main()
