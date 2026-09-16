import unittest

from trader.indicators import atr, ema, max_drawdown, rsi, sma


class IndicatorTests(unittest.TestCase):
    def test_sma_and_ema(self):
        values = [float(i) for i in range(1, 31)]
        self.assertAlmostEqual(sma(values, 10), 25.5)
        self.assertGreater(ema(values, 10), 24)

    def test_rsi_uptrend(self):
        self.assertGreater(rsi([float(i) for i in range(1, 40)], 14), 99)

    def test_atr(self):
        closes = [100 + i for i in range(20)]
        highs = [value + 2 for value in closes]
        lows = [value - 2 for value in closes]
        self.assertAlmostEqual(atr(highs, lows, closes, 14), 4.0)

    def test_drawdown(self):
        self.assertAlmostEqual(max_drawdown([100, 120, 90, 110]), -0.25)


if __name__ == "__main__":
    unittest.main()

