import unittest
from dataclasses import replace

from trader.domain import Candle
from trader.research_portfolio import Intent, Scenario, futures_intents, scenarios, simulate


def bars(prices):
    return [Candle(i*1000, p, p+1, p-1, p, 100, (i+1)*1000-1) for i,p in enumerate(prices)]


class JointPortfolioTests(unittest.TestCase):
    def run_sim(self, data, signals, scenario=None, **kwargs):
        defaults = dict(initial_cash=1000, fee=.001, slippage=.001, start=0, end=100000)
        defaults.update(kwargs)
        return simulate(data, signals, scenario or Scenario('base', .005, .2, .8), **defaults)

    def test_shared_wallet_position_and_gross_caps_and_next_open(self):
        data = {f'A{i}USDT': bars([100,110,110]) for i in range(8)}
        signals = {s: {999: Intent(1, 50)} for s in data}
        result = self.run_sim(data, signals, Scenario('agresivo', .05, 1, .8))
        self.assertEqual(result['max_open_positions'], 5)
        self.assertLessEqual(result['max_entry_gross_equity_ratio'], .8+1e-6)
        self.assertGreater(result['blocked_entries']['positions'], 0)
        self.assertTrue(all(t['opened_at'] == 1000 for t in result['trades']))
        # A jump before execution is not awarded to the simulated strategy.
        self.assertLess(result['net_return_pct'], 0)
        self.assertGreater(result['ending_equity'], 0)

    def test_stop_first_when_both_touched_and_open_gap(self):
        data = {'AUSDT': [Candle(0,100,101,99,100,1,999), Candle(1000,100,115,90,100,1,1999)]}
        result = self.run_sim(data, {'AUSDT': {999: Intent(1, 5, 2)}}, fee=0, slippage=0)
        self.assertEqual(result['trades'][0]['reason'], 'STOP')
        self.assertLess(result['net_return_pct'], 0)
        data['AUSDT'] = bars([100,100,80])
        result = self.run_sim(data, {'AUSDT': {999: Intent(1, 5)}}, fee=0, slippage=0)
        self.assertEqual(result['trades'][0]['reason'], 'STOP_GAP')

    def test_no_entry_across_missing_bar(self):
        data = {'AUSDT': bars([100,100,120])}
        data['AUSDT'].pop(1)
        result = self.run_sim(data, {'AUSDT': {999: Intent(1, 5)}})
        self.assertEqual(result['closed_trades'], 0)

    def test_short_profit_and_funding_direction(self):
        data = {'AUSDT': bars([100,100,90])}
        funding = {'AUSDT': [{'time': 0, 'rate': .5, 'mark': 100}, {'time':1000,'rate':.001,'mark':100}]}
        result = self.run_sim(data, {'AUSDT': {999: Intent(-1,20)}}, market='FUTURES',
                              marks=data, funding=funding, fee=0, slippage=0)
        self.assertGreater(result['net_return_pct'], 0)
        self.assertLess(result['funding_cost'], 0)
        self.assertAlmostEqual(result['funding_cost'], -.025)
        self.assertEqual(result['trades'][0]['side'], 'SHORT')

    def test_leverage_does_not_multiply_position_notional(self):
        data = {'AUSDT': bars([100,100,102])}
        signals = {'AUSDT': {999: Intent(1,20)}}
        returns = [self.run_sim(data, signals, Scenario('base', .005, .2, .8, leverage),
                               market='FUTURES', marks=data, funding={'AUSDT':[]}, fee=0, slippage=0)
                   for leverage in (1,2,3,5,10)]
        self.assertEqual(len({r['net_return_pct'] for r in returns}), 1)

    def test_mark_liquidation_limits_loss_to_isolated_margin(self):
        data = {'AUSDT': bars([100,100,100])}
        marks = {'AUSDT': bars([100,100,70])}
        marks['AUSDT'][1] = Candle(1000,100,101,70,100,0,1999)
        result = self.run_sim(data, {'AUSDT': {999: Intent(1,50)}}, Scenario('agresivo', .05, .3, 1.5, 10),
                              market='FUTURES', marks=marks, funding={'AUSDT':[]}, fee=0, slippage=0)
        self.assertEqual(result['liquidations'], 1)
        self.assertGreaterEqual(result['ending_equity'], 990)

    def test_missing_mark_or_funding_rejected(self):
        data = {'AUSDT': bars([100,100])}
        with self.assertRaisesRegex(ValueError, 'aligned mark'):
            self.run_sim(data, {}, market='FUTURES')

    def test_higher_costs_reduce_net_result_on_identical_fills(self):
        data = {'AUSDT': bars([100,100,102])}
        signals = {'AUSDT': {999:Intent(1,1)}}
        base = self.run_sim(data, signals, fee=.001, slippage=.001)
        stress = self.run_sim(data, signals, fee=.002, slippage=.002)
        self.assertLess(stress['net_return_pct'], base['net_return_pct'])

    def test_curves_bounded_and_final_mark_is_realized_cash(self):
        data = {'AUSDT': bars([100+i*.01 for i in range(1000)])}
        result = self.run_sim(data, {'AUSDT': {999:Intent(1,30)}}, end=1000000)
        self.assertLessEqual(len(result['curve']), 120)
        self.assertEqual(result['curve'][-1]['equity'], result['ending_equity'])

    def test_futures_signals_do_not_change_when_future_prices_change(self):
        original = bars([100+i*.05 for i in range(220)])
        modified = original[:180]+[replace(c,open=10+i,close=10+i,high=11+i,low=9+i) for i,c in enumerate(original[180:])]
        a,b = futures_intents(original), futures_intents(modified)
        for name in a:
            self.assertEqual({t:s for t,s in a[name].items() if t <=179999},
                             {t:s for t,s in b[name].items() if t <=179999})
        self.assertEqual(len(scenarios('SPOT')), 3)
        self.assertEqual(len(scenarios('FUTURES')), 15)


if __name__ == '__main__':
    unittest.main()
