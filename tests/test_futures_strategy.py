import hashlib
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from trader.config import StrategySettings
from trader.domain import Candle
from trader.futures_forward import FuturesForwardEngine
from trader.futures_strategy import evaluate_futures_signal


class FuturesStrategyTests(unittest.TestCase):
    @staticmethod
    def cases():
        patterns = {
            'flat': [100.0]*160,
            'up': [100+index*.5+(4 if index==159 else 0) for index in range(160)],
            'down': [200-index*.5-(4 if index==159 else 0) for index in range(160)],
            'wave': [100+(index%11-5)*.7+index*.01 for index in range(160)],
            'reversal': [100+index*.5 if index<140 else 170-(index-140)*2 for index in range(160)],
            'volatile': [100.0 if index%2==0 else 150.0 for index in range(160)],
            'zero_volume': [100+index*.5 for index in range(160)],
        }
        for name, prices in patterns.items():
            rows = [Candle(index*3600000, price-.2,
                           price+(40 if name=='volatile' else .5),
                           price-(40 if name=='volatile' else .5),price,
                           0.0 if name=='zero_volume' else (120.0 if index==159 else 100.0),
                           (index+1)*3600000-1) for index,price in enumerate(prices)]
            yield name,rows

    def test_operating_outputs_match_pre_extraction_golden_cases_exactly(self):
        # Frozen from 0.10.29 before extraction, rather than a second scoring formula.
        base = StrategySettings(70,20,50,14,14,20,20)
        profiles = (base,replace(base,ema_fast=12,ema_slow=36,breakout_period=12,volume_period=12))
        outputs = []
        for profile in profiles:
            for threshold in (0,70,85,101):
                for name,rows in self.cases():
                    original = list(rows)
                    outputs.append({'name':name,'threshold':threshold,'ema_fast':profile.ema_fast,
                                    'signal':evaluate_futures_signal(rows,profile,
                                        SimpleNamespace(forward_min_score=threshold))})
                    self.assertEqual(rows,original)
        serialized = json.dumps(outputs,sort_keys=True,separators=(',',':'),allow_nan=False)
        self.assertEqual(len(outputs),56)
        self.assertEqual(hashlib.sha256(serialized.encode()).hexdigest(),
                         'bbe7f2475766d923c39a271a1de6ced036fb3f52ed584f5a22564f6cdf962fc0')

    def test_short_history_retains_operating_error(self):
        strategy = StrategySettings(70,20,50,14,14,20,20)
        with self.assertRaisesRegex(ValueError,'^Futures forward history unavailable$'):
            evaluate_futures_signal([],strategy,SimpleNamespace(forward_min_score=70))

    def test_forward_adapter_delegates_with_exact_operating_settings(self):
        strategy = StrategySettings(70,20,50,14,14,20,20)
        engine = FuturesForwardEngine.__new__(FuturesForwardEngine)
        engine.config = SimpleNamespace(strategy=strategy)
        engine.settings = SimpleNamespace(forward_min_score=75)
        rows = next(self.cases())[1]
        sentinel = {'direction':'SHORT','score':75}
        with patch('trader.futures_forward.evaluate_futures_signal',return_value=sentinel) as pure:
            self.assertIs(engine._signal(rows),sentinel)
        pure.assert_called_once_with(rows,strategy,engine.settings)


if __name__ == '__main__':
    unittest.main()
