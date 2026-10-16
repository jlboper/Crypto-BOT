import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.operational_controls import execute
from trader.portal_snapshot import bounded_market_pulse_projection, market_pulse_projection, _pulse_source_url


class MarketPulseContractTests(unittest.TestCase):
    def test_remote_budget_preserves_positions_totals_and_latest_decisions(self):
        pulse = {'positions': [{'symbol': 'BTCUSDT', 'stop': 95}],
            'performance': {'closed_trades': 30, 'net_pnl': -2},
            'decisions': [{'id': str(i), 'reason': 'ñ' * 300} for i in range(80)],
            'events': [], 'opportunities': []}
        before = deepcopy(pulse)
        bounded_market_pulse_projection(pulse)
        self.assertLess(len(json.dumps(pulse, ensure_ascii=True, separators=(',', ':'))), 20000)
        self.assertEqual(pulse['positions'], before['positions'])
        self.assertEqual(pulse['performance'], before['performance'])
        self.assertEqual(pulse['decisions'][0], before['decisions'][0])
        with self.assertRaises(ValueError):
            bounded_market_pulse_projection({'positions': [{'raw': 'x' * 21000}]})

    def test_missing_pulse_ledger_is_read_only_and_does_not_invent_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = load_config()
            config = replace(base, bot=replace(base.bot, database_path=root / 'spot.db'),
                market_pulse=replace(base.market_pulse, kill_switch_path=root / 'pulse-kill'))
            projected = market_pulse_projection(config)
            self.assertEqual(projected['mode'], 'SHADOW')
            self.assertFalse(projected['execution_enabled'])
            self.assertEqual(list(root.iterdir()), [])
            self.assertIn(projected['state'], {'NOT_STARTED', 'DEGRADED'})
            self.assertIsNone(projected.get('performance', {}).get('return_pct'))

    def test_optional_pulse_failure_keeps_a_safe_diagnostic_and_no_exception_secret(self):
        base = load_config()
        with patch('trader.market_pulse.market_pulse_snapshot', side_effect=ValueError('api_key=private')):
            projected = market_pulse_projection(base)
        self.assertEqual(projected['state'], 'DEGRADED')
        self.assertFalse(projected['controls_available'])
        self.assertNotIn('private', json.dumps(projected))

    def test_source_urls_drop_queries_userinfo_and_credential_paths(self):
        self.assertEqual(_pulse_source_url('https://example.com/news/123?api_key=private#fragment'),
                         'https://example.com/news/123')
        for url in ('http://example.com/news', 'https://user:secret@example.com/news',
                    'https://localhost/news', 'https://example.com/token/private'):
            self.assertIsNone(_pulse_source_url(url))

    def test_controls_are_shadow_only_and_do_not_restart_other_engines(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            data = source / 'data'
            data.mkdir()
            base = load_config()
            config = replace(base, bot=replace(base.bot, database_path=data / 'spot.db'),
                market_pulse=replace(base.market_pulse, kill_switch_path=data / 'pulse-kill'))
            with patch('trader.operational_controls.load_config', return_value=config), \
                 patch('trader.operational_controls.ProcessRuntime') as runtime, \
                 patch('trader.market_pulse.market_pulse_control', return_value={'state': 'PAUSED'}) as control:
                self.assertTrue(execute(source, 'market_pulse_pause', {})['ok'])
                control.assert_called_once_with(data, 'pause', kill_switch_path=data / 'pulse-kill')
                runtime.assert_not_called()
                with self.assertRaises(ValueError):
                    execute(source, 'market_pulse_resume', {'mode': 'testnet'})
                disabled = replace(config, market_pulse=replace(config.market_pulse, enabled=False))
                with patch('trader.operational_controls.load_config', return_value=disabled):
                    with self.assertRaisesRegex(ValueError, 'SHADOW'):
                        execute(source, 'market_pulse_resume', {})
                (data / 'UPDATE_MAINTENANCE.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'Maintenance'):
                    execute(source, 'market_pulse_resume', {})


if __name__ == '__main__':
    unittest.main()
