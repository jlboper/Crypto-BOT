"""Guardian host integration against isolated synthetic data; no API calls."""
from contextlib import nullcontext
from dataclasses import replace
import io
import json
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from trader.config import GuardianIntelligenceSettings, load_config
from trader.engine import TradingEngine
from tests.emit_guardian_intelligence_fixture import make_guardian_intelligence


class GuardianIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # No .env or operating config/credential reads in this test suite.
        with patch('trader.config.load_environment'):
            config = load_config()
        self.config = replace(config,
            bot=replace(config.bot, mode='paper', database_path=self.root/'data/spot.db',
                        kill_switch_path=self.root/'data/KILL'),
            ai=replace(config.ai, enabled=False),
            market_pulse=replace(config.market_pulse, enabled=False),
            quant_arbitrage=replace(config.quant_arbitrage, enabled=False),
            guardian_intelligence=GuardianIntelligenceSettings(enabled=True))

    def test_factory_keeps_immutable_service_ceiling_when_ai_master_or_budget_changes(self):
        for enabled in (False, True):
            for cap in (0, 1, 2):
                with self.subTest(enabled=enabled, cap=cap):
                    config = replace(self.config, ai=replace(self.config.ai, enabled=enabled),
                        guardian_intelligence=GuardianIntelligenceSettings(ai_max_reviews_per_day=cap))
                    engine = TradingEngine(config)
                    with patch('trader.guardian_ai.GuardianAIReviewer') as reviewer, \
                            patch('trader.guardian_shadow.GuardianShadowService') as service:
                        self.assertIs(engine._create_guardian_shadow(), service.return_value)
                    self.assertEqual(reviewer.call_args.kwargs['daily_cap'], cap if enabled else 0)
                    self.assertEqual(reviewer.call_args.kwargs['model'], self.config.ai.model)
                    self.assertEqual(service.call_args.kwargs['config'].context_max_calls_per_day, 2)
                    self.assertEqual(service.call_args.kwargs['config'].context_timeout_seconds, 10.)
                    self.assertIs(service.call_args.kwargs['context_hook'], reviewer.return_value)
                    self.assertFalse((self.root/'data/guardian-shadow.db').exists())

    def test_settings_refuse_authority_modes_bool_levels_and_budget_expansion(self):
        invalid = [{'mode': mode} for mode in ('LIVE', 'TESTNET', 'CONTROL', 'PAPER')]
        invalid += [{'autonomy_level': value} for value in (False, True, 1, 2, -1, '0')]
        invalid += [{'ai_max_reviews_per_day': value} for value in (False, True, -1, 3, '2', 1.5)]
        invalid += [{'enabled': value} for value in (0, 1, 'true')]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GuardianIntelligenceSettings(**kwargs)

    def test_toml_refuses_unknown_control_risk_and_reservation_settings(self):
        original = (Path(__file__).resolve().parents[1]/'config.toml').read_text(encoding='utf-8')
        original = re.sub(r'(?ms)^\[guardian_intelligence\].*?(?=^\[|\Z)', '', original)
        for setting in ('execution_enabled = true', 'can_veto = true', 'risk_per_trade = 0.01',
                        'reservations_enabled = true', 'autonomy_level = 1', 'mode = "LIVE"',
                        'ai_max_reviews_per_day = true', 'ai_max_reviews_per_day = 3'):
            path = self.root/'config.toml'
            path.write_text(original+'\n[guardian_intelligence]\n'+setting+'\n', encoding='utf-8')
            with self.subTest(setting=setting), patch('trader.config.load_environment'), self.assertRaises(ValueError):
                load_config(path)

    def test_observer_start_failure_does_not_stop_existing_supervised_loop(self):
        engine = TradingEngine(self.config)
        observer = Mock()
        observer.start.side_effect = RuntimeError('private detail must not be journaled')
        with patch.object(engine, '_create_guardian_shadow', return_value=observer), \
                patch.object(engine, '_run_supervised_loop') as loop:
            engine.run_forever()
        loop.assert_called_once()
        observer.stop.assert_called_once()
        self.assertFalse((self.root/'data/guardian-shadow.db').exists())
        self.assertNotIn('private detail', json.dumps(engine.db.recent('events', 10)))

    def test_observer_shutdown_failure_still_stops_quant_and_pulse(self):
        config = replace(self.config, market_pulse=replace(self.config.market_pulse, enabled=True),
                         quant_arbitrage=replace(self.config.quant_arbitrage, enabled=True))
        engine = TradingEngine(config)
        observer, quant, pulse = Mock(), Mock(), Mock()
        observer.stop.side_effect = RuntimeError('synthetic shutdown failure')
        with patch.object(engine, '_create_guardian_shadow', return_value=observer), \
                patch.object(engine, '_create_quant_shadow', return_value=quant), \
                patch.object(engine, '_create_market_pulse', return_value=pulse), \
                patch.object(engine, '_run_supervised_loop') as loop:
            engine.run_forever()
        loop.assert_called_once()
        for service in (observer, quant, pulse):
            service.start.assert_called_once()
            service.stop.assert_called_once()

    def test_disabled_or_stopped_host_never_initializes_guardian_journal(self):
        for disabled, stopped in ((True, False), (False, True)):
            with self.subTest(disabled=disabled, stopped=stopped):
                config = replace(self.config, guardian_intelligence=GuardianIntelligenceSettings(enabled=not disabled))
                engine = TradingEngine(config)
                with patch.object(engine, '_create_guardian_shadow') as factory, \
                        patch.object(engine, '_run_supervised_loop'):
                    engine.run_forever(lambda: stopped)
                factory.assert_not_called()
                self.assertFalse((self.root/'data/guardian-shadow.db').exists())

    def test_cli_activation_barrier_precedes_optional_observer_start(self):
        from trader import cli
        engine = TradingEngine(self.config)
        observer = Mock()
        control = Mock(token='synthetic-candidate-token')
        control.should_stop.return_value = False
        args = SimpleNamespace(command='run', config=None)
        dashboard = Mock()
        dashboard.start_thread.return_value.is_alive.return_value = True
        activated = []
        def start():
            self.assertEqual(activated, [True])
        observer.start.side_effect = start
        with patch.object(cli, 'parser') as parser, patch.object(cli, 'load_config', return_value=self.config), \
                patch.object(cli, 'RuntimeControl', return_value=control), \
                patch.object(cli, 'TradingEngine', return_value=engine), \
                patch.object(cli, 'DashboardServer', return_value=dashboard), \
                patch.object(cli, 'single_instance', return_value=nullcontext()), \
                patch.object(cli, '_start_windows_agent_self_heal') as heal, \
                patch.object(engine, '_create_guardian_shadow', return_value=observer) as factory, \
                patch.object(engine, '_run_supervised_loop') as loop, \
                patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
            parser.return_value.parse_args.return_value = args
            control.await_activation.side_effect = RuntimeError('candidate not committed')
            with self.assertRaises(SystemExit) as denied:
                cli.main()
            self.assertEqual(denied.exception.code, 2)
            factory.assert_not_called()
            loop.assert_not_called()
            heal.assert_not_called()
            control.await_activation.side_effect = lambda: activated.append(True)
            cli.main()
            factory.assert_called_once()
            observer.start.assert_called_once()
            observer.stop.assert_called_once()
            loop.assert_called_once()
            heal.assert_called_once()

    def test_protective_spot_and_futures_paths_have_no_guardian_dependency(self):
        engine = TradingEngine(self.config)
        position = SimpleNamespace(symbol='BTCUSDT')
        with patch.object(engine.db, 'positions', return_value=[position]), \
                patch.object(engine, '_run_futures_forward_protection') as futures, \
                patch.object(engine, '_position_execution_prices', return_value={'BTCUSDT': 100.}) as prices, \
                patch.object(engine, '_require_spot_prices') as validate, \
                patch.object(engine, '_manage_positions') as protect, \
                patch.object(engine.db, 'record_market_snapshot') as record, \
                patch.object(engine, '_create_guardian_shadow', side_effect=AssertionError('protectors called observer')) as factory, \
                patch.dict('sys.modules', {'trader.guardian_shadow': None, 'trader.guardian_intelligence': None}):
            engine.protection_tick()
        futures.assert_called_once()
        prices.assert_called_once_with({'BTCUSDT'})
        validate.assert_called_once()
        protect.assert_called_once_with({}, {'BTCUSDT': 100.})
        record.assert_called_once_with({'BTCUSDT': 100.})
        factory.assert_not_called()

    def test_real_producer_variants_keep_observation_and_no_counterfactual_claims(self):
        for variant, state in (('ready', 'OBSERVING'), ('partial', 'PARTIAL'), ('stale', 'STALE'), ('no-ai', 'OBSERVING')):
            with self.subTest(variant=variant):
                wrapper = make_guardian_intelligence(now=1792339200.1234567, variant=variant)
                self.assertEqual(wrapper['state'], state)
                self.assertLessEqual(len(json.dumps(wrapper, ensure_ascii=True).encode()), 12000)
                self.assertEqual(len(wrapper['report']['scopes']), 4)
                self.assertIsNone(wrapper['report']['counterfactual']['losses_avoided'])
                self.assertIsNone(wrapper['report']['counterfactual']['without_ai_pnl'])
                self.assertNotIn('dashboard', wrapper)
                self.assertNotIn('btc_closed_bars', wrapper)
                for flag in ('execution_enabled','can_veto','controls_enabled','reservations_enabled','promotion_allowed'):
                    self.assertIs(wrapper[flag], False)
                    self.assertIs(wrapper['report'][flag], False)

    def test_absent_journal_has_explicit_empty_state_and_no_fabricated_finances(self):
        wrapper = make_guardian_intelligence(variant='not-started')
        self.assertEqual(wrapper['state'], 'NOT_STARTED')
        self.assertIsNone(wrapper['report'])
        self.assertIsNone(wrapper['ai'])
        self.assertEqual(wrapper['journal'], [])
        self.assertIsNone(wrapper['health']['records'])


if __name__ == '__main__':
    unittest.main()
