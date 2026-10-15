import math
import unittest
from dataclasses import replace

from trader.config import load_config
from trader.domain import Candle
from trader.futures_strategy import evaluate_futures_signal
from trader.research_operating import operating_baselines, operating_signal_rows
from trader.strategy import SwingStrategy


def history(interval, count=700):
    result = []
    for i in range(count):
        price = 100+i*.04+math.sin(i/9)*3
        result.append(Candle(i*interval, price-.2, price+1, price-1, price,
                            1000+(i%13)*50, (i+1)*interval-1))
    return result


class OperatingReferenceTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.spot = history(14_400_000)
        self.futures = history(3_600_000)

    def test_reference_reuses_the_exact_operating_signal_context_and_functions(self):
        strategy = SwingStrategy(self.config.strategy, self.config.risk)
        spot = operating_signal_rows('SPOT', 'BTCUSDT', self.spot, self.spot, self.config)
        futures = operating_signal_rows('FUTURES', 'BTCUSDT', self.futures, [], self.config)
        for index in (249, 350, 699):
            spot_context = self.spot[index-249:index+1]
            expected = strategy.evaluate('BTCUSDT', spot_context, strategy.btc_regime(spot_context))
            actual = spot[index-249]
            self.assertEqual(actual['direction'], 'BUY' if expected.action == 'BUY' else None)
            for key in ('score','price','atr','rsi','ema_fast','ema_slow','volume_ratio','stop_price','take_profit'):
                self.assertEqual(actual[key], getattr(expected, key))
            expected_futures = evaluate_futures_signal(self.futures[index-249:index+1],
                self.config.strategy, self.config.futures_testnet)
            self.assertEqual({key: futures[index-249][key] for key in expected_futures}, expected_futures)

    def test_baselines_are_signal_references_with_current_limits_and_no_profitability_claim(self):
        references = operating_baselines({'BTCUSDT':self.spot}, {'BTCUSDT':self.futures}, self.config, 300, 100)
        self.assertEqual([r['market'] for r in references], ['SPOT','FUTURES'])
        for reference in references:
            self.assertEqual(reference['evidence'], 'SIGNAL_PARITY_ONLY')
            self.assertEqual(reference['selection'], 'CONFIGURED_OPERATING_RULES_NO_SELECTION')
            self.assertFalse(reference['automatic_promotion'])
            self.assertFalse(reference['profitability_evaluated'])
            self.assertIn('AI_not_replayed', reference['execution_gaps'])
            self.assertNotIn('champion_candidate', reference)
            self.assertNotIn('net_return_pct', reference)
            self.assertEqual([w['evaluated_symbol_bars'] for w in reference['windows'].values()], [51,300,100])
            for window in reference['windows'].values():
                self.assertEqual(window['eligible_signals']+window['hold_signals'], window['evaluated_symbol_bars'])
        self.assertEqual(references[0]['configuration']['limits']['max_positions'], self.config.risk.max_positions)
        future_limits = references[1]['configuration']['limits']
        self.assertEqual(future_limits['forward_max_positions'], self.config.futures_testnet.forward_max_positions)
        self.assertEqual(future_limits['forward_total_stop_loss_usdt'], self.config.futures_testnet.forward_total_stop_loss_usdt)
        self.assertEqual(future_limits['target_notional_before_filters_usdt'], 30.0)
        self.assertEqual(references[0]['timeframe'], '4h')
        self.assertEqual(references[1]['timeframe'], '1h')

    def test_final_prices_do_not_change_development_signals_or_configuration_identity(self):
        first = operating_baselines({'BTCUSDT':self.spot}, {'BTCUSDT':self.futures}, self.config, 300, 100)
        def alter(rows):
            return rows[:-100]+[replace(c,open=c.open*2,high=c.high*2,low=c.low*2,close=c.close*2) for c in rows[-100:]]
        second = operating_baselines({'BTCUSDT':alter(self.spot)}, {'BTCUSDT':alter(self.futures)}, self.config, 300, 100)
        for before, after in zip(first, second):
            self.assertEqual(before['configuration_fingerprint'], after['configuration_fingerprint'])
            self.assertEqual(before['windows']['training'], after['windows']['training'])
            self.assertEqual(before['windows']['development_oos'], after['windows']['development_oos'])
            self.assertNotEqual(before['latest_signals'], after['latest_signals'])

    def test_futures_configuration_changes_only_its_reference_fingerprint(self):
        first = operating_baselines({'BTCUSDT':self.spot}, {'BTCUSDT':self.futures}, self.config, 300, 100)
        modified = replace(self.config, futures_testnet=replace(self.config.futures_testnet,
            forward_timeframe='2h', forward_min_score=80))
        second = operating_baselines({'BTCUSDT':self.spot}, {'BTCUSDT':self.futures}, modified, 300, 100)
        self.assertEqual(first[0]['configuration_fingerprint'], second[0]['configuration_fingerprint'])
        self.assertNotEqual(first[1]['configuration_fingerprint'], second[1]['configuration_fingerprint'])
        self.assertEqual(second[1]['configuration']['minimum_score'], 80)

    def test_missing_market_has_an_explicit_empty_reference(self):
        references = operating_baselines({'BTCUSDT':self.spot}, {}, self.config, 300, 100)
        self.assertEqual(references[1]['status'], 'DATA_UNAVAILABLE')
        self.assertEqual(references[1]['windows'], {})
        self.assertFalse(references[1]['profitability_evaluated'])


if __name__ == '__main__':
    unittest.main()
