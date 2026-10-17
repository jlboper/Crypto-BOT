"""Synthetic pure-model tests. These establish mechanics, never profitability."""
import copy
import json
import math
import random
import unittest

from trader.quant_models import MAX_HISTORY, funding_signal, statarb_signal


NOW = 1_800_000_000.0


def funding_fixture(rate=.01):
    spot = {'symbol': 'BTCUSDT', 'bid': 99.99, 'ask': 100.01,
            'bid_depth_usdt': 100000, 'ask_depth_usdt': 100000,
            'at': NOW-1, 'received_at': NOW}
    futures = dict(spot, mark_price=100.0, observed_funding_rate=rate,
                   next_funding_at=NOW+3600, funding_interval_seconds=28800)
    history = [{'at': NOW-3600-i*28800, 'received_at': NOW-3600-i*28800+5,
                'rate': rate, 'mark_price': 100.0} for i in range(8)]
    assumptions = {'available_virtual_usdt': 1000.0, 'risk_budget_usdt': 2.5}
    return spot, futures, history, assumptions


def pair_fixture(count=420, *, break_shift=0.0, random_spread=False, current_sigma=None):
    randomizer = random.Random(419)
    common, residual = 7.0, 0.0
    rows = []
    for i in range(count):
        common += randomizer.gauss(0, .005)
        residual = ((residual if random_spread else .55*residual)
                    + randomizer.gauss(0, .001))
        spread = residual+(break_shift if i >= count*2//3 else 0)
        rows.append({'at': NOW-(count-1-i)*60, 'received_at': NOW-(count-1-i)*60,
                     'prices': {'BTCUSDT': math.exp(2+.9*common+spread), 'ETHUSDT': math.exp(common)}})
    if current_sigma is not None:
        initial = statarb_signal(rows, NOW)
        metrics = initial['metrics']
        if metrics.get('train_spread_sigma'):
            log_b = math.log(rows[-1]['prices']['ETHUSDT'])
            # Reconstruct intercept from any training row plus actual residual.
            train = rows[:len(rows)*2//3]
            alpha = sum(math.log(row['prices']['BTCUSDT'])-metrics['hedge_ratio']*math.log(row['prices']['ETHUSDT'])
                        for row in train)/len(train)
            rows[-1]['prices']['BTCUSDT'] = math.exp(alpha+metrics['hedge_ratio']*log_b
                                                   +current_sigma*metrics['train_spread_sigma'])
    return rows


class FundingModelTests(unittest.TestCase):
    def evaluate(self, *, rate=.01, changes=None):
        spot, futures, history, assumptions = funding_fixture(rate)
        if changes:
            changes(spot, futures, history, assumptions)
        return funding_signal(spot, futures, history, NOW, assumptions)

    def test_favorable_conditional_carry_is_only_shadow_and_equal_quantity(self):
        result = self.evaluate()
        self.assertEqual(result['decision'], 'OPEN_SHADOW')
        self.assertFalse(result['execution_enabled'])
        self.assertEqual(result['mode'], 'SHADOW')
        self.assertEqual([leg['direction'] for leg in result['legs']], ['LONG', 'SHORT'])
        self.assertEqual([leg['venue'] for leg in result['legs']], ['SPOT_REFERENCE', 'FUTURES_REFERENCE'])
        self.assertEqual(result['evidence']['funding_income_kind'], 'CONDITIONAL_PROJECTION_NOT_SETTLED')
        self.assertIsNone(result['metrics']['settled_funding_usdt'])
        self.assertGreater(result['metrics']['conditional_net_estimate_usdt'], 0)
        metrics = result['metrics']
        self.assertAlmostEqual(metrics['spot_notional_usdt']/metrics['spot_mid'],
                               metrics['futures_notional_usdt']/metrics['futures_mid'])

    def test_normal_low_funding_is_rejected_after_both_legs_roundtrip_costs(self):
        result = self.evaluate(rate=.0001)
        self.assertEqual(result['reason'], 'PROJECTED_CARRY_BELOW_ALL_COSTS')
        # Fees and slip alone cost .8% of one leg; quoted spreads add .04%.
        self.assertAlmostEqual(result['metrics']['roundtrip_cost_usdt'], 28.4*.0084)

    def test_missing_virtual_capital_cannot_default_to_an_account_balance(self):
        spot, futures, history, _ = funding_fixture()
        result = funding_signal(spot, futures, history, NOW)
        self.assertEqual(result['reason'], 'VIRTUAL_CAPITAL_OR_RISK_UNKNOWN')
        self.assertEqual(result['decision'], 'WAIT')

    def test_margin_is_fully_collateralized_and_not_synthetic_cross_account_net(self):
        result = self.evaluate(changes=lambda s, f, h, a: a.update(available_virtual_usdt=50))
        self.assertEqual(result['reason'], 'INSUFFICIENT_VIRTUAL_COLLATERAL')
        self.assertGreater(result['metrics']['required_virtual_cash_usdt'],
                           result['metrics']['gross_notional_usdt'])

    def test_quantitative_risk_budget_overrides_an_attractive_projection(self):
        result = self.evaluate(changes=lambda s, f, h, a: a.update(risk_budget_usdt=.1))
        self.assertEqual(result['reason'], 'ESTIMATED_STRESS_EXCEEDS_BUDGET')

    def test_negative_current_or_historical_funding_rejected(self):
        self.assertEqual(self.evaluate(rate=-.0001)['reason'], 'NONPOSITIVE_OR_EXTREME_FUNDING')
        result = self.evaluate(changes=lambda s, f, h, a: h[0].update(rate=-.0001))
        self.assertEqual(result['reason'], 'ADVERSE_FUNDING_IN_HISTORY')

    def test_future_history_or_future_receipt_cannot_change_a_past_signal(self):
        spot, futures, history, assumptions = funding_fixture()
        baseline = funding_signal(spot, futures, history, NOW, assumptions)
        future = [{'at': NOW+1, 'received_at': NOW+1, 'rate': -.01, 'mark_price': 100},
                  {'at': NOW-1, 'received_at': NOW+1, 'rate': -.01, 'mark_price': 100}]
        result = funding_signal(spot, futures, history+future, NOW, assumptions)
        self.assertEqual(result, baseline)

    def test_duplicates_do_not_inflate_history_and_conflicts_reject(self):
        spot, futures, history, assumptions = funding_fixture()
        baseline = funding_signal(spot, futures, history, NOW, assumptions)
        self.assertEqual(baseline, funding_signal(spot, futures, history+[dict(history[0])], NOW, assumptions))
        conflicting = dict(history[0], rate=.009)
        self.assertEqual(funding_signal(spot, futures, history+[conflicting], NOW, assumptions)['reason'],
                         'CONFLICTING_FUNDING_EVENT')
        self.assertEqual(funding_signal(spot, futures, history[:7], NOW, assumptions)['reason'],
                         'COLLECTING_FUNDING_HISTORY')

    def test_history_gaps_or_changed_interval_are_not_zero_filled(self):
        result = self.evaluate(changes=lambda s, f, h, a: h[-1].update(at=h[-1]['at']-28800))
        self.assertEqual(result['reason'], 'FUNDING_HISTORY_GAPPED_OR_INTERVAL_CHANGED')
        result = self.evaluate(changes=lambda s, f, h, a: f.update(funding_interval_seconds=3600))
        self.assertEqual(result['reason'], 'FUNDING_HISTORY_GAPPED_OR_INTERVAL_CHANGED')

    def test_stale_future_incomplete_unaligned_and_wrong_symbols(self):
        cases = [
            (lambda s, f, h, a: s.update(at=NOW-100), 'STALE_QUOTE'),
            (lambda s, f, h, a: s.update(received_at=NOW+1), 'QUOTE_NOT_AVAILABLE_AT_DECISION'),
            (lambda s, f, h, a: f.update(at=NOW-10), 'UNALIGNED_LEG_TIMES'),
            (lambda s, f, h, a: f.update(symbol='ETHUSDT'), 'SYMBOL_MISMATCH'),
            (lambda s, f, h, a: s.pop('bid_depth_usdt'), 'INCOMPLETE_QUOTE'),
            (lambda s, f, h, a: f.update(funding_interval_seconds=5000), 'FUNDING_INTERVAL_UNVERIFIED'),
        ]
        for change, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.evaluate(changes=change)['reason'], expected)

    def test_bounded_provider_clock_lead_requires_real_receipt_before_decision(self):
        def lead(spot,futures,history,assumptions):
            spot.update(at=NOW+2,received_at=NOW)
            futures.update(at=NOW+2,received_at=NOW)
        accepted = self.evaluate(changes=lead)
        self.assertEqual(accepted['decision'],'OPEN_SHADOW')
        for updates in ({'at':NOW+6,'received_at':NOW},
                        {'at':NOW,'received_at':NOW+1},
                        {'at':NOW,'received_at':NOW-6}):
            with self.subTest(updates=updates):
                result = self.evaluate(changes=lambda s,f,h,a:s.update(**updates))
                self.assertEqual(result['reason'],'QUOTE_NOT_AVAILABLE_AT_DECISION')

    def test_spread_basis_mark_divergence_and_liquidity_fail_closed(self):
        cases = [
            (lambda s, f, h, a: s.update(ask=102), 'WIDE_SPREAD'),
            (lambda s, f, h, a: f.update(bid=102, ask=102.01), 'EXCESSIVE_BASIS'),
            (lambda s, f, h, a: f.update(mark_price=110), 'MARK_BOOK_DIVERGENCE'),
            (lambda s, f, h, a: s.update(ask_depth_usdt=0), 'INSUFFICIENT_TWO_SIDED_LIQUIDITY'),
            (lambda s, f, h, a: f.update(next_funding_at=NOW+10), 'FUNDING_TIME_NOT_CAPTUREABLE'),
        ]
        for change, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.evaluate(changes=change)['reason'], expected)

    def test_nan_booleans_overflow_and_invalid_costs_never_generate_a_signal(self):
        for value in (float('nan'), float('inf'), True, 1 << 10000, 1e308):
            with self.subTest(value_type=type(value).__name__):
                result = self.evaluate(changes=lambda s, f, h, a: s.update(bid=value))
                self.assertEqual(result['decision'], 'REJECT')
                json.dumps(result, allow_nan=False)
        for invalid in (-.001, .5, float('nan'), True):
            result = self.evaluate(changes=lambda s, f, h, a: a.update(slippage_rate=invalid))
            self.assertEqual(result['reason'], 'INVALID_ASSUMPTIONS')

    def test_model_does_not_mutate_frozen_evidence_or_capital(self):
        arguments = funding_fixture()
        before = copy.deepcopy(arguments)
        spot, futures, history, assumptions = arguments
        first = funding_signal(spot, futures, history, NOW, assumptions)
        second = funding_signal(spot, futures, history, NOW, assumptions)
        self.assertEqual(first, second)
        self.assertEqual(arguments, before)


class PairModelTests(unittest.TestCase):
    def test_collecting_history_is_unknown_not_an_invented_backtest(self):
        result = statarb_signal([], NOW)
        self.assertEqual(result['reason'], 'COLLECTING_ALIGNED_PAIR_HISTORY')
        self.assertEqual(result['metrics'], {})
        self.assertIsNone(result['evidence']['p_value'])
        self.assertEqual(result['evidence']['observation_count'], 0)

    def test_fixed_training_and_holdout_diagnostics_are_bounded_and_exploratory(self):
        result = statarb_signal(pair_fixture(), NOW)
        self.assertNotEqual(result['decision'], 'OPEN_SHADOW')
        self.assertIsNone(result['evidence']['p_value'])
        self.assertEqual(result['evidence']['cointegration_status'], 'NOT_FORMALLY_VALIDATED')
        self.assertLess(result['evidence']['train_end_at'], result['evidence']['holdout_start_at'])
        self.assertGreater(result['metrics']['train_return_correlation'], .8)
        self.assertIsNotNone(result['metrics']['residual_adf_lag1_t'])
        self.assertGreater(result['metrics']['approximate_half_life_observations'], 0)
        self.assertLess(len(json.dumps(result, allow_nan=False)), 8000)

    def test_even_promising_cost_free_fixture_requires_independent_validation(self):
        rows = pair_fixture(current_sigma=2.5)
        result = statarb_signal(rows, NOW, {'futures_fee_rate': 0, 'slippage_rate': 0})
        self.assertEqual(result['reason'], 'COINTEGRATION_NOT_INDEPENDENTLY_VALIDATED')
        self.assertEqual(result['decision'], 'WAIT')
        self.assertEqual(result['legs'], [])

    def test_two_leg_costs_reject_a_spread_that_looks_large_in_z_units(self):
        result = statarb_signal(pair_fixture(current_sigma=2.5), NOW)
        self.assertEqual(result['reason'], 'CONVERGENCE_SCENARIO_BELOW_COSTS')
        self.assertLess(result['metrics']['net_convergence_scenario_rate'], 0)
        self.assertAlmostEqual(result['metrics']['roundtrip_fee_slippage_rate'], .004)

    def test_holdout_structural_break_rejected_without_refitting(self):
        result = statarb_signal(pair_fixture(break_shift=.02), NOW)
        self.assertIn('HOLDOUT_STRUCTURAL_BREAK', result['reasons'])
        self.assertGreater(result['metrics']['holdout_mean_shift_sigma'], 1.5)

    def test_correlated_random_walk_spread_is_not_cointegration(self):
        result = statarb_signal(pair_fixture(random_spread=True), NOW)
        self.assertEqual(result['decision'], 'REJECT')
        self.assertIn('RESIDUAL_UNIT_ROOT_SCREEN_FAILED', result['reasons'])
        self.assertIsNone(result['evidence']['p_value'])

    def test_future_prices_and_late_receipts_do_not_influence_a_decision(self):
        rows = pair_fixture()
        baseline = statarb_signal(rows, NOW)
        future = [{'at': NOW+60, 'received_at': NOW+60,
                   'prices': {'BTCUSDT': 1, 'ETHUSDT': 1000000}},
                  {'at': NOW-30, 'received_at': NOW+1,
                   'prices': {'BTCUSDT': 1, 'ETHUSDT': 1000000}}]
        self.assertEqual(baseline, statarb_signal(rows+future, NOW))

    def test_holdout_does_not_change_training_parameters(self):
        rows = pair_fixture()
        original = statarb_signal(rows, NOW)
        changed = copy.deepcopy(rows)
        for row in changed[len(rows)*2//3:]:
            row['prices']['BTCUSDT'] *= 1.01
        result = statarb_signal(changed, NOW)
        for key in ('hedge_ratio', 'train_spread_mean', 'train_spread_sigma',
                    'residual_adf_lag1_t', 'ar1_phi'):
            self.assertEqual(original['metrics'][key], result['metrics'][key])

    def test_gaps_conflicts_missing_prices_and_staleness_reject(self):
        rows = pair_fixture()
        gapped = rows[:100]+rows[101:]
        self.assertEqual(statarb_signal(gapped, NOW)['reason'], 'GAPPED_OR_IRREGULAR_PAIR_HISTORY')
        conflict = copy.deepcopy(rows[-1])
        conflict['prices']['BTCUSDT'] *= 2
        self.assertEqual(statarb_signal(rows+[conflict], NOW)['reason'], 'CONFLICTING_PAIR_OBSERVATION')
        incomplete = copy.deepcopy(rows)
        incomplete[1]['prices'].pop('ETHUSDT')
        self.assertEqual(statarb_signal(incomplete, NOW)['reason'], 'INVALID_PAIR_OBSERVATION')
        self.assertEqual(statarb_signal(rows, NOW+100)['reason'], 'STALE_PAIR_HISTORY')

    def test_constant_or_duplicate_assets_and_oversized_input_do_not_claim_evidence(self):
        rows = pair_fixture()
        for row in rows:
            row['prices']['ETHUSDT'] = 1000
        self.assertEqual(statarb_signal(rows, NOW)['reason'], 'DEGENERATE_TRAINING_PRICES')
        self.assertEqual(statarb_signal(rows, NOW, {'symbol_a': 'BTCUSDT', 'symbol_b': 'BTCUSDT'})['reason'],
                         'IDENTICAL_ASSETS')
        self.assertEqual(statarb_signal([{}]*(MAX_HISTORY+1), NOW)['reason'], 'INVALID_OR_UNBOUNDED_PAIR_HISTORY')

    def test_pair_model_is_reproducible_and_preserves_original_observations(self):
        rows = pair_fixture()
        before = copy.deepcopy(rows)
        self.assertEqual(statarb_signal(rows, NOW), statarb_signal(rows, NOW))
        self.assertEqual(rows, before)

    def test_unsupported_pair_cannot_be_selected_through_assumptions(self):
        self.assertEqual(statarb_signal(pair_fixture(), NOW, {'symbol_b': 'USDTUSDT'})['reason'],
                         'INVALID_ASSUMPTIONS')


if __name__ == '__main__':
    unittest.main()
