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


def history(count=700):
    interval = 14400000
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
        public = Mock()
        public.historical_candles.side_effect = lambda symbol, interval, size: rows[-size:] if symbol == 'BTCUSDT' else []
        futures = Mock()
        futures.candles.side_effect = lambda symbol, interval, size, **kwargs: rows[-size:]
        events = [{'time':c.open_time, 'mark':c.open, 'rate':.0001} for c in rows[::2]]
        futures.funding.return_value = events
        with patch('trader.research_market.ResearchClient', return_value=public), patch(
                'trader.research_market.FuturesHistory', return_value=futures):
            result = execute_research(self.config, symbols=('BTCUSDT','ETHUSDT'),
                                      history_candles=700, train_bars=180, test_bars=100)
            self.assertEqual(result['coverage']['studied_spot'], ['BTCUSDT'])
            self.assertEqual(result['coverage']['unavailable'][0]['symbol'], 'ETHUSDT')
            self.assertEqual(len(result['futures_assets']),2)
            self.assertEqual(len(result['joint_portfolios']),18)
            self.assertFalse(result['auto_promotion'])
            self.assertTrue(all(not p['automatic_promotion'] for p in result['joint_portfolios']))
            projected = project_report(result)
            self.assertLess(len(json.dumps(projected).encode()),240000)
            self.assertTrue(all('trades' not in p for p in projected['joint_portfolios']))
            scaled = copy.deepcopy(result)
            scaled['assets'] = [copy.deepcopy(result['assets'][0]) for _ in range(30)]
            scaled['futures_assets'] = [copy.deepcopy(result['futures_assets'][0]) for _ in range(15)]
            scaled['history'] *= 12
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


if __name__ == '__main__':
    unittest.main()
