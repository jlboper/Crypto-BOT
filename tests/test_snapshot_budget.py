import json
import unittest
from copy import deepcopy
from trader.portal_snapshot import bounded_futures_projection
from scripts.export_paper_snapshot import compatible_remote_projection


class FuturesProjectionBudgetTests(unittest.TestCase):
    def test_long_history_is_thinned_without_hiding_safety_or_totals(self):
        futures={'positions':[{'symbol':f'COIN{i}USDT','quantity':1} for i in range(10)],
                 'native_protection':{'supported':True,'positions':{'GNSUSDT':{'status':'BLOCKED'}}},
                 'pause_diagnostics':{'active':True,'detail':'safety pause'},
                 'closed_trades':500,'gross_pnl':-31.25,'scorecard':{'closed_trades':500},
                 'signals':[{'id':i,'text':'ñ'*250} for i in range(50)],
                 'equity':[{'id':i,'text':'x'*250} for i in range(120)],
                 'trades':[{'id':i,'text':'x'*250} for i in range(50)],
                 'shadow_scorecard':[{'id':i,'text':'x'*250} for i in range(27)]}
        before=deepcopy(futures)
        bounded_futures_projection(futures)
        self.assertLess(len(json.dumps(futures,ensure_ascii=False,separators=(',',':')).encode()),72000)
        for key in ('positions','native_protection','pause_diagnostics','closed_trades','gross_pnl','scorecard'):
            self.assertEqual(futures[key],before[key])
        self.assertEqual(futures['equity'][-1],before['equity'][-1])
        self.assertEqual(futures['trades'][0],before['trades'][0])

    def test_optional_history_cannot_replace_or_truncate_safety_evidence(self):
        futures={'positions':[{'symbol':'BTCUSDT','unexpected':'x'*80000}],'signals':[]}
        with self.assertRaises(ValueError):bounded_futures_projection(futures)
        self.assertEqual(len(futures['positions'][0]['unexpected']),80000)

    def test_actual_export_path_applies_budget_and_small_snapshots_stay_compatible(self):
        d={'paper_scorecard':{'financial':{}},'futures_forward':{'positions':[],
            'signals':[{'i':i,'text':'x'*2000} for i in range(50)]}}
        self.assertGreater(len(json.dumps(d['futures_forward'])),80000)
        result=compatible_remote_projection(d)
        self.assertLess(len(json.dumps(result['futures_forward'],separators=(',',':'))),72000)
        small={'positions':[],'equity':[],'gross_pnl':0,'closed_trades':0}
        self.assertEqual(bounded_futures_projection(deepcopy(small)),small)
