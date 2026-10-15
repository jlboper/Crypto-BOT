import json
import copy
import math
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from trader.config import load_config
from trader.domain import Candle
from trader.exchange import ExchangeError
from trader.research import execute_research
from trader.research_campaign import forward_observation, futures_research
from trader.research_market import FuturesHistory, ResearchClient
from trader.research_runtime import atomic, cancellation, check_cancel, project_report
from trader.runtime import single_instance


def history(count=700, interval=14400000):
    end = int(time.time()*1000)//interval*interval
    rows = []
    for i in range(count):
        close = 100+i*.035+math.sin(i/8)*2.5
        start = end-(count-i)*interval
        rows.append(Candle(start,close-.2,close+1,close-1,close,1000+(i%13)*20,start+interval-1))
    return rows


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        config = load_config()
        self.config = replace(config, bot=replace(config.bot, database_path=root/'spot.db'),
            research=replace(config.research, report_path=root/'research/latest.json'),
            futures_testnet=replace(config.futures_testnet, forward_symbols=('BTCUSDT','ETHUSDT')))

    def test_complete_campaign_partial_coverage_caches_and_keeps_evidence(self):
        rows = history()
        futures_rows = history(interval=3600000)
        public = Mock()
        public.historical_candles.side_effect = lambda symbol, interval, size: rows[-size:] if symbol == 'BTCUSDT' else []
        futures = Mock()
        futures.candles.side_effect = lambda symbol, interval, size, **kwargs: futures_rows[-size:]
        events = [{'time':c.open_time, 'mark':c.open, 'rate':.0001} for c in futures_rows[::2]]
        futures.funding.return_value = events
        # A prior 4h study must survive, and even a mislabelled 1h cache must
        # not mix its otherwise valid 4h candles into the new hourly study.
        from dataclasses import asdict
        cache = self.config.research.report_path.parent/'cache'
        legacy_cache = {'candles': [asdict(c) for c in rows]}
        for market in ('futures', 'mark'):
            atomic(cache/f'{market}-BTCUSDT-4h.json', legacy_cache)
            atomic(cache/f'{market}-BTCUSDT-1h.json', legacy_cache)
        with patch('trader.research_market.ResearchClient', return_value=public), patch(
                'trader.research_market.FuturesHistory', return_value=futures):
            result = execute_research(self.config, symbols=('BTCUSDT','ETHUSDT'),
                                      history_candles=700, train_bars=180, test_bars=100)
            self.assertEqual(result['coverage']['studied_spot'], ['BTCUSDT'])
            self.assertEqual(result['coverage']['unavailable'][0]['symbol'], 'ETHUSDT')
            self.assertEqual(len(result['futures_assets']),2)
            self.assertEqual(len(result['joint_portfolios']),18)
            self.assertEqual({call.args[1] for call in public.historical_candles.call_args_list}, {'4h'})
            self.assertEqual({call.args[1] for call in futures.candles.call_args_list}, {'1h'})
            self.assertTrue(all(call.args[2] == 700 for call in futures.candles.call_args_list))
            self.assertEqual(result['experiment']['spot_timeframe'], '4h')
            self.assertEqual(result['experiment']['futures_timeframe'], '1h')
            self.assertTrue(all(a['timeframe'] == '1h' for a in result['futures_assets']))
            self.assertTrue(all(p['timeframe'] == ('4h' if p['market'] == 'SPOT' else '1h')
                                for p in result['joint_portfolios']))
            for market in ('futures', 'mark'):
                self.assertEqual(json.loads((cache/f'{market}-BTCUSDT-4h.json').read_text()), legacy_cache)
                hourly = json.loads((cache/f'{market}-BTCUSDT-1h.json').read_text())['candles']
                self.assertEqual(len(hourly), 700)
                self.assertTrue(all(c['close_time']-c['open_time']+1 == 3600000 for c in hourly))
            self.assertFalse(result['auto_promotion'])
            self.assertTrue(all(not p['automatic_promotion'] for p in result['joint_portfolios']))
            self.assertEqual([b['market'] for b in result['operating_baselines']], ['SPOT','FUTURES'])
            self.assertTrue(all(b['evidence'] == 'SIGNAL_PARITY_ONLY' and not b['profitability_evaluated']
                                for b in result['operating_baselines']))
            projected = project_report(result)
            self.assertLess(len(json.dumps(projected).encode()),240000)
            self.assertTrue(all('trades' not in p for p in projected['joint_portfolios']))
            scaled = copy.deepcopy(result)
            scaled['assets'] = [copy.deepcopy(result['assets'][0]) for _ in range(30)]
            scaled['futures_assets'] = [copy.deepcopy(result['futures_assets'][0]) for _ in range(15)]
            scaled['history'] *= 12
            scaled['operating_baselines'][0]['latest_signals'] *= 30
            scaled['operating_baselines'][1]['latest_signals'] = scaled['operating_baselines'][1]['latest_signals'][:1]*15
            self.assertLess(len(json.dumps(project_report(scaled)).encode()),240000)
            self.assertTrue(all(f['status'] == 'WAITING_NEW_DATA' for f in result['forward_observation']))
            self.assertEqual(len(list((self.config.research.report_path.parent/'runs').glob('*.json'))),1)
            before = self.config.research.report_path.read_bytes()
            public.historical_candles.return_value = []
            public.historical_candles.side_effect = None
            with self.assertRaisesRegex(ValueError, 'previous report retained'):
                execute_research(self.config, symbols=('BTCUSDT',),history_candles=700, train_bars=180, test_bars=100)
            self.assertEqual(self.config.research.report_path.read_bytes(),before)
            self.assertEqual(public.historical_candles.call_args.args[-1],250)

    def test_futures_final_window_does_not_change_initial_model_or_oos(self):
        rows = history()
        events = {'BTCUSDT':[{'time':c.open_time,'mark':c.open,'rate':.0001} for c in rows[::2]]}
        first, runs, _ = futures_research({'BTCUSDT':rows},{'BTCUSDT':rows},events,self.config,180,100)
        changed = rows[:-100]+[replace(c,open=c.open*2,high=c.high*2,low=c.low*2,close=c.close*2) for c in rows[-100:]]
        second, altered_runs, _ = futures_research({'BTCUSDT':changed},{'BTCUSDT':changed},events,self.config,180,100)
        self.assertEqual(first[0]['champion_candidate'],second[0]['champion_candidate'])
        self.assertEqual(first[0]['folds'],second[0]['folds'])
        self.assertEqual([r['net_return_pct'] for r in runs],[r['net_return_pct'] for r in altered_runs])
        self.assertTrue(all('contract_liquidation_calibration' in a['discarded_reasons'] for a in second))

    def test_fresh_futures_history_with_wrong_interval_is_excluded(self):
        rows = history()
        irregular = history(interval=3600000)
        irregular[200] = replace(irregular[200], open_time=irregular[200].open_time+1800000,
                                 close_time=irregular[200].close_time+1800000)
        # The second sample has the correct duration and median cadence, but one
        # overlapping bar. Inferring a median interval alone would accept it.
        for sample in (rows, irregular):
            with self.subTest(wrong_interval=sample is rows):
                public, futures = Mock(), Mock()
                public.historical_candles.return_value = rows
                futures.candles.return_value = sample
                spot_report = {'assets': [], 'summary': {'assets': 0}, 'auto_promotion': False}
                with patch('trader.research_market.ResearchClient', return_value=public), patch(
                        'trader.research_market.FuturesHistory', return_value=futures), patch(
                        'trader.research.build_research_report', return_value=spot_report), patch(
                        'trader.research_campaign.spot_portfolios', return_value=[]), patch(
                        'trader.research_campaign.forward_observation', return_value=[]):
                    report = execute_research(self.config, symbols=('BTCUSDT',),
                                              history_candles=700, train_bars=180, test_bars=100)
                self.assertEqual(report['coverage']['studied_futures'], [])
                self.assertEqual(len(report['coverage']['unavailable']), 2)
                self.assertTrue(all(failure['market'] == 'FUTURES' for failure in report['coverage']['unavailable']))
                futures.funding.assert_not_called()
                self.assertFalse((self.config.research.report_path.parent/'cache/futures-BTCUSDT-1h.json').exists())

    def test_public_transport_rejects_signed_and_write_requests(self):
        client = ResearchClient()
        with self.assertRaises(ExchangeError):
            client._request('GET','/fapi/v1/account', signed=True)
        with self.assertRaises(ExchangeError):
            client._request('POST','/fapi/v1/order')

    def test_missing_funding_not_substituted_by_zero(self):
        history_client = FuturesHistory()
        with patch.object(history_client.client,'_request',return_value=[]):
            with self.assertRaisesRegex(ExchangeError,'unavailable'):
                history_client.funding('BTCUSDT',0,86400000)

    def test_cancel_on_update_releases_the_research_lock(self):
        lock = self.config.research.report_path.parent/'research.lock'
        with self.assertRaisesRegex(RuntimeError,'maintenance'):
            with single_instance(lock), cancellation(self.config):
                atomic(self.config.bot.database_path.parent/'UPDATE_MAINTENANCE.json',{'phase':'stopping'})
                check_cancel()
        with single_instance(lock):
            pass  # Updater can now acquire the exact same lock.

    def test_forward_cohort_does_not_use_registration_history_or_reselect(self):
        rows = history()
        report = {'assets':[{'symbol':'BTCUSDT','champion_candidate':'baseline_trend'}], 'futures_assets':[]}
        first = forward_observation(report,{'BTCUSDT':rows},{},{},{},{},self.config)
        self.assertEqual(first[0]['status'],'WAITING_NEW_DATA')
        path = self.config.research.report_path.parent/'forward-baseline.json'
        baseline = json.loads(path.read_text())
        baseline['start_after']['SPOT'] = rows[-20].open_time-1
        atomic(path,baseline)
        report['assets'][0]['champion_candidate'] = 'fast_momentum'
        second = forward_observation(report,{'BTCUSDT':rows},{},{},{},{},self.config)
        self.assertEqual(second[0]['status'],'OBSERVING')
        self.assertEqual(json.loads(path.read_text())['spot']['BTCUSDT'],'baseline_trend')
        self.assertLessEqual(second[0]['observed_days'],20*4/24)
        self.assertFalse(second[0]['automatic_promotion'])

    def test_legacy_futures_cohort_is_archived_on_interval_change_without_resetting_spot(self):
        rows = history()
        hourly = history(interval=3600000)
        report = {'assets':[{'symbol':'BTCUSDT','champion_candidate':'baseline_trend'}],
                  'futures_assets':[{'symbol':'BTCUSDT','champion_candidate':'trend'}]}
        models = {'BTCUSDT': {'trend': {}, 'breakout': {}}}
        forward_observation(report, {'BTCUSDT':rows}, {'BTCUSDT':hourly},
                            {'BTCUSDT':hourly}, {'BTCUSDT':[]}, models, self.config)
        path = self.config.research.report_path.parent/'forward-baseline.json'
        legacy = json.loads(path.read_text())
        for key in ('timeframes', 'market_fingerprints', 'registered_at_by_market'):
            legacy.pop(key)
        legacy['registered_at'] = '2026-01-01T00:00:00+00:00'
        legacy['start_after'] = {market: rows[-20].open_time-1 for market in ('SPOT','FUTURES')}
        atomic(path, legacy)
        report['assets'][0]['champion_candidate'] = 'fast_momentum'
        report['futures_assets'][0]['champion_candidate'] = 'breakout'

        result = forward_observation(report, {'BTCUSDT':rows}, {'BTCUSDT':hourly},
                                     {'BTCUSDT':hourly}, {'BTCUSDT':[]}, models, self.config)
        current = json.loads(path.read_text())
        self.assertEqual(current['spot'], legacy['spot'])
        self.assertEqual(current['start_after']['SPOT'], legacy['start_after']['SPOT'])
        self.assertEqual(current['registered_at_by_market']['SPOT'], legacy['registered_at'])
        self.assertEqual(result[0]['status'], 'OBSERVING')
        self.assertEqual(current['futures'], {'BTCUSDT':'breakout'})
        self.assertGreater(current['start_after']['FUTURES'], legacy['start_after']['FUTURES'])
        self.assertEqual(result[1]['status'], 'WAITING_NEW_DATA')
        self.assertEqual(result[1]['observed_days'], 0)
        self.assertEqual(result[1]['timeframe'], '1h')
        archives = list((path.parent/'forward-cohorts').glob('*.json'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(json.loads(archives[0].read_text()), legacy)

        changed = replace(self.config, futures_testnet=replace(self.config.futures_testnet, forward_timeframe='2h'))
        two_hourly = history(interval=7200000)
        next_result = forward_observation(report, {'BTCUSDT':rows}, {'BTCUSDT':two_hourly},
            {'BTCUSDT':two_hourly}, {'BTCUSDT':[]}, models, changed)
        self.assertEqual(next_result[0]['model_fingerprint'], result[0]['model_fingerprint'])
        self.assertNotEqual(next_result[1]['model_fingerprint'], result[1]['model_fingerprint'])
        self.assertEqual(next_result[1]['status'], 'WAITING_NEW_DATA')
        archives = list((path.parent/'forward-cohorts').glob('*.json'))
        self.assertEqual(len(archives), 2)
        self.assertIn(current, [json.loads(p.read_text()) for p in archives])


if __name__ == '__main__':
    unittest.main()
