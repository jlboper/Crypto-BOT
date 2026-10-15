import math
import unittest
from dataclasses import replace

from trader.domain import Signal


class EntryPricePlanTests(unittest.TestCase):
    def setUp(self):
        self.signal = Signal('BTCUSDT', 'BUY', 80, 100., 95., 110., 2., 60., 101., 99., 1.3, 'unit', 'now')

    def test_repeated_price_changes_preserve_risk_reward_and_observation(self):
        signal = self.signal
        for price in (103., 97., 102., 105.):
            signal = signal.at_entry_price(price)
            self.assertAlmostEqual((signal.price-signal.stop_price)/signal.price, .05)
            self.assertAlmostEqual((signal.take_profit-signal.price)/(signal.price-signal.stop_price), 2.)
            self.assertAlmostEqual(signal.atr/signal.price, .02)
            self.assertEqual((signal.observed_price, signal.observed_stop_price, signal.observed_take_profit), (100.,95.,110.))
            self.assertEqual((signal.ema_fast,signal.ema_slow,signal.rsi,signal.created_at), (101.,99.,60.,'now'))
        self.assertEqual(self.signal.price,100.)
        self.assertIsNone(self.signal.observed_price)
        self.assertNotIn('observed_price',self.signal.to_dict())
        self.assertEqual(Signal(**signal.to_dict()),signal)

    def test_invalid_prices_or_partial_observation_cannot_make_an_entry_plan(self):
        for price in (0.,-1.,float('nan'),float('inf'),True):
            with self.subTest(price=price), self.assertRaises(ValueError):
                self.signal.at_entry_price(price)
        for signal in (replace(self.signal, action='HOLD'), replace(self.signal, stop_price=None),
                       replace(self.signal, observed_price=100.), replace(self.signal, atr=math.inf)):
            with self.assertRaises(ValueError):
                signal.at_entry_price(101.)
