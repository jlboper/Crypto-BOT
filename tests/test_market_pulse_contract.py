import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import time
from unittest.mock import patch

from trader.config import load_config
from trader.operational_controls import execute
from trader.portal_snapshot import bounded_market_pulse_projection, market_pulse_projection, _pulse_source_url


class MarketPulseContractTests(unittest.TestCase):
    def _pulse(self):
        from trader.market_pulse import _empty_snapshot
        return _empty_snapshot(time.time())

    def test_ten_assets_and_optional_public_provider_metadata_are_bounded_and_allowlisted(self):
        raw = self._pulse()
        symbols = ('BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'SOLUSDT',
                   'TRXUSDT', 'ZECUSDT', 'HYPEUSDT', 'DOGEUSDT', 'LINKUSDT')
        raw['market'] = [dict(symbol=symbol, price=100, at=raw['at']) for symbol in symbols]
        raw['performance']['benchmark_buy_hold'] = {symbol: 1.25 for symbol in symbols}
        raw['news_providers'] = [dict(id='official-source', name='Official source',
            url='https://example.com/feed?api_key=private#fragment', kind='official', state='STANDBY',
            last_update=None, last_error=None, api_key='private')]
        raw['universe'] = dict(selection='OWNER_APPROVED_LIQUID_TOP10', selected_at=raw['at'],
            source='Binance public exchangeInfo and 24h quote volume', secret='private')
        with patch('trader.market_pulse.market_pulse_snapshot', return_value=raw):
            projected = market_pulse_projection(load_config())
        self.assertEqual([row['symbol'] for row in projected['market']], list(symbols))
        self.assertEqual(len(projected['performance']['benchmark_buy_hold']), 10)
        self.assertEqual(projected['news_providers'][0]['url'], 'https://example.com/feed')
        self.assertNotIn('api_key', projected['news_providers'][0])
        self.assertNotIn('private', json.dumps(projected))
        self.assertNotIn('secret', projected['universe'])
        self.assertLess(len(json.dumps(projected, ensure_ascii=True, separators=(',', ':'))), 20000)
        raw['universe']['source'] = 'https://www.coingecko.com/?api_key=private#fragment'
        with patch('trader.market_pulse.market_pulse_snapshot', return_value=raw):
            projected = market_pulse_projection(load_config())
        self.assertEqual(projected['universe']['source'], 'https://www.coingecko.com/')

    def test_malformed_optional_metadata_and_over_limit_universes_fail_safely(self):
        base = self._pulse()
        provider = dict(id='public-source', name='Public source', url='https://example.com/feed',
            kind='editorial', state='STANDBY', last_update=None, last_error=None)
        updates = [dict(news_providers=[dict(provider, kind='ai-instructions')]),
            dict(news_providers=[dict(provider, state='EXECUTE')]),
            dict(news_providers=[dict(provider, last_update='old')]),
            dict(news_providers=[dict(provider, last_error='api_key=private')]),
            dict(news_providers=[provider] * 6), dict(news_providers=[provider] * 2),
            dict(universe={'selection': {'instructions': 'trade'}, 'source': 'private'}),
            dict(market=[{'symbol': 'BTCUSDT'}] * 11),
            dict(positions=[{'symbol': 'BTCUSDT'}] * 4),
            dict(performance={**base['performance'], 'benchmark_buy_hold': {f'COIN{i}USDT': 0 for i in range(11)}})]
        for update in updates:
            with self.subTest(update=update):
                with patch('trader.market_pulse.market_pulse_snapshot', return_value={**base, **update}):
                    projected = market_pulse_projection(load_config())
                self.assertEqual(projected['state'], 'DEGRADED')
                self.assertEqual(projected['health']['last_error'], 'PULSE_PROJECTION_UNAVAILABLE')
                self.assertNotIn('private', json.dumps(projected))

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

    def test_actual_legacy_journal_and_protective_sell_omit_absent_optional_ranking(self):
        from tests.emit_market_pulse_fixture import legacy_sell_projection
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = load_config()
            config = replace(base, bot=replace(base.bot, database_path=root / 'spot.db'),
                market_pulse=replace(base.market_pulse, kill_switch_path=root / 'pulse-kill'))
            projected = legacy_sell_projection(root, config)
        self.assertEqual(projected['state'], 'PAUSED')
        self.assertEqual(projected['performance']['closed_trades'], 1)
        self.assertEqual(len(projected['positions']), 2)
        legacy = [row for row in projected['decisions'] if row['action'] == 'BUY']
        protective = [row for row in projected['decisions'] if row['action'] == 'SELL']
        self.assertEqual(len(legacy), 3)
        self.assertEqual(len(protective), 1)
        for row in legacy + protective:
            for key in ('selection_rank', 'selection_pool', 'selection_rule'):
                self.assertNotIn(key, row['evidence'])

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
