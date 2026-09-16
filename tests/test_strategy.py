import math
import unittest

from trader.config import load_config
from trader.domain import Candle
from trader.strategy import SwingStrategy


def trending_candles(count=100):
    rows=[]
    for i in range(count):
        base=100+i*0.8+math.sin(i/3)
        high=base+1.8
        if i==count-1:
            high=base+8
            close=base+7
            volume=3000
        else:
            close=base+0.6
            volume=1000+i
        rows.append(Candle(i*1000,base,high,base-1,close,volume,i*1000+999))
    return rows


class StrategyTests(unittest.TestCase):
    def test_strong_trend_can_create_buy(self):
        config=load_config()
        strategy=SwingStrategy(config.strategy,config.risk)
        signal=strategy.evaluate("TESTUSDT",trending_candles(),True)
        self.assertEqual(signal.action,"BUY")
        self.assertGreaterEqual(signal.score,config.strategy.minimum_score)
        self.assertLess(signal.stop_price,signal.price)
        self.assertGreater(signal.take_profit,signal.price)

    def test_bearish_btc_reduces_score(self):
        config=load_config()
        strategy=SwingStrategy(config.strategy,config.risk)
        bullish=strategy.evaluate("TESTUSDT",trending_candles(),True)
        bearish=strategy.evaluate("TESTUSDT",trending_candles(),False)
        self.assertEqual(bullish.score-bearish.score,20)


if __name__ == "__main__":
    unittest.main()

