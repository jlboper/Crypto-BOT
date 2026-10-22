"""Explicit synthetic budgets only; no account, model, provider or configuration."""
from dataclasses import asdict, FrozenInstanceError, replace
from decimal import Decimal, getcontext, localcontext
import importlib.util
import io
import json
from pathlib import Path
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.migration_costs import OrderCostScenario, evaluate_order_costs


def fixture(**changes):
    # 100 is an explicit synthetic scenario, not a balance or approved allocation.
    scenario = OrderCostScenario(
        venue='SPOT_SIMULATION',quote_asset='USDT',direction='LONG',
        available_capital='100',risk_budget='2',max_notional='100',
        reference_price='10',stop_price='9.5',leverage='1',approved_max_leverage='1',
        entry_fee_rate='0.001',exit_fee_rate='0.001',
        entry_slippage_rate='0.001',exit_slippage_rate='0.001',
        lot_step='0.001',min_qty='0.001',min_notional='5',max_qty=None,tick_size='0.01')
    return replace(scenario,**changes)


def d(value):
    return Decimal(value)


class MigrationCostTests(unittest.TestCase):
    def test_100_is_an_explicit_hypothesis_and_both_sides_of_fees_and_slippage_count(self):
        scenario=fixture()
        result=evaluate_order_costs(scenario)
        self.assertEqual(result['state'],'FEASIBLE_HYPOTHESIS')
        self.assertTrue(result['feasible_hypothesis'])
        quantity=d(result['quantity'])
        self.assertEqual(d(result['entry_scenario_price']),d('10.01'))
        self.assertEqual(d(result['stop_scenario_price']),d('9.49'))
        self.assertEqual(d(result['estimated_entry_fee']),quantity*d('10.01')*d('0.001'))
        self.assertEqual(d(result['estimated_exit_fee_at_stop']),quantity*d('9.49')*d('0.001'))
        self.assertEqual(d(result['stop_risk_per_unit']),d('0.5395'))
        self.assertLessEqual(d(result['estimated_stop_risk']),d(scenario.risk_budget))
        self.assertLessEqual(d(result['conservative_capital_required']),d(scenario.available_capital))
        self.assertLessEqual(d(result['conservative_notional']),d(scenario.max_notional))
        self.assertIsInstance(result['quantity'],str)
        for key in ('execution_enabled','promotion_allowed','financial_authorization','risk_change_allowed','live_implemented'):
            self.assertIs(result[key],False)
        with self.assertRaises(FrozenInstanceError):
            scenario.risk_budget='999'
        with self.assertRaises(TypeError):
            OrderCostScenario()

    def test_incompatible_minimum_never_raises_size_capital_or_risk_to_force_a_trade(self):
        scenario=fixture(risk_budget='0.01',min_notional='100')
        result=evaluate_order_costs(scenario)
        self.assertFalse(result['feasible_hypothesis'])
        self.assertIn('MIN_NOTIONAL_EXCEEDS_SAFE_SIZE',result['reason_codes'])
        self.assertLessEqual(d(result['estimated_stop_risk']),d('0.01'))
        self.assertLess(d(result['quantity']),d('0.02'))
        self.assertEqual(scenario.risk_budget,'0.01')

    def test_quantity_rounds_down_on_non_power_of_ten_steps_and_never_rounds_up_to_min_qty(self):
        scenario=fixture(reference_price='10',stop_price='9',entry_fee_rate='0',exit_fee_rate='0',
            entry_slippage_rate='0',exit_slippage_rate='0',risk_budget='1.24',
            lot_step='0.25',min_qty='1.01',min_notional='0')
        result=evaluate_order_costs(scenario)
        self.assertEqual(result['quantity'],'1')
        self.assertIn('MIN_QUANTITY_EXCEEDS_SAFE_SIZE',result['reason_codes'])
        self.assertEqual(result['estimated_stop_risk'],'1')

    def test_short_and_long_ticks_are_adverse_and_notional_budgets_include_raw_reference(self):
        common=dict(venue='LINEAR_FUTURES_SIMULATION',reference_price='100.001',
                    entry_fee_rate='0',exit_fee_rate='0',entry_slippage_rate='0',exit_slippage_rate='0',
                    tick_size='0.01',leverage='2',approved_max_leverage='2',risk_budget='100',
                    max_notional='100.001',min_notional='0',lot_step='0.001',min_qty='0')
        long=evaluate_order_costs(fixture(direction='LONG',stop_price='99.999',**common))
        short=evaluate_order_costs(fixture(direction='SHORT',stop_price='100.009',**common))
        self.assertEqual(long['entry_scenario_price'],'100.01')
        self.assertEqual(long['stop_scenario_price'],'99.99')
        self.assertEqual(short['entry_scenario_price'],'100')
        self.assertEqual(short['stop_scenario_price'],'100.01')
        self.assertEqual(short['notional_budget_basis_price'],'100.001')
        self.assertEqual(short['quantity'],'1')
        self.assertLessEqual(d(short['conservative_notional']),d(common['max_notional']))

    def test_adverse_tick_or_slippage_never_manufactures_minimum_notional_eligibility(self):
        result=evaluate_order_costs(fixture(reference_price='100.001',stop_price='99',
            available_capital='200',risk_budget='10',max_notional='200',lot_step='1',max_qty='1',
            entry_fee_rate='0',exit_fee_rate='0',entry_slippage_rate='0',exit_slippage_rate='0',
            tick_size='0.01',min_notional='100.005'))
        self.assertEqual(result['quantity'],'1')
        self.assertEqual(result['estimated_entry_notional'],'100.01')
        self.assertEqual(result['filter_min_notional_value'],'100.001')
        self.assertIn('MIN_NOTIONAL_EXCEEDS_SAFE_SIZE',result['reason_codes'])
        self.assertLessEqual(d(result['estimated_stop_risk']),d('10'))
        slipped=evaluate_order_costs(fixture(reference_price='100',stop_price='99',
            available_capital='200',risk_budget='10',max_notional='200',lot_step='1',max_qty='1',
            entry_fee_rate='0',exit_fee_rate='0',entry_slippage_rate='0.01',exit_slippage_rate='0',
            tick_size='0.01',min_notional='100.5'))
        self.assertEqual(slipped['filter_min_notional_value'],'100')
        self.assertFalse(slipped['feasible_hypothesis'])

    def test_linear_futures_margin_is_a_limited_proxy_and_leverage_does_not_multiply_notional(self):
        base=fixture(venue='LINEAR_FUTURES_SIMULATION',risk_budget='100',max_qty='1',
            entry_fee_rate='0',exit_fee_rate='0',entry_slippage_rate='0',exit_slippage_rate='0',
            reference_price='10',stop_price='9')
        one=evaluate_order_costs(base)
        two=evaluate_order_costs(replace(base,leverage='2',approved_max_leverage='2'))
        self.assertEqual(one['quantity'],two['quantity'])
        self.assertEqual(one['estimated_entry_notional'],two['estimated_entry_notional'])
        self.assertEqual(one['estimated_stop_risk'],two['estimated_stop_risk'])
        self.assertEqual(d(one['conservative_capital_required']),2*d(two['conservative_capital_required']))
        self.assertEqual(two['capital_model'],'SIM_NOT_CONTRACT_CALIBRATED')
        self.assertIn('FUNDING_NOT_MODELED',two['limitations'])
        self.assertIn('LIQUIDATION_AND_MAINTENANCE_MARGIN_NOT_CALIBRATED',two['limitations'])

    def test_exchange_max_quantity_and_capital_fee_reserves_are_applied_before_minimum_checks(self):
        capped=evaluate_order_costs(fixture(max_qty='0.5',min_notional='0'))
        self.assertEqual(capped['quantity'],'0.5')
        scenario=fixture(risk_budget='100',available_capital='10',max_notional='100',
            entry_slippage_rate='0',exit_slippage_rate='0',lot_step='0.001',min_notional='0')
        result=evaluate_order_costs(scenario)
        self.assertLess(d(result['quantity']),d('1'))
        self.assertLessEqual(d(result['conservative_capital_required']),d('10'))
        qty=d(result['quantity'])
        self.assertGreater((qty+d('0.001'))*d('10.0195'),d('10'))

    def test_futures_leverage_and_approved_maximum_require_integral_values_without_rounding(self):
        for leverage,approved in (('1.5','2'),('1','2.5'),('1.0001','2'),('1','2.0001')):
            with self.subTest(leverage=leverage,approved=approved):
                result=evaluate_order_costs(fixture(venue='LINEAR_FUTURES_SIMULATION',
                    leverage=leverage,approved_max_leverage=approved))
                self.assertEqual(result['state'],'REJECTED_HYPOTHESIS')
                self.assertEqual(result['reason_codes'],['INTEGER_FUTURES_LEVERAGE_REQUIRED'])
                self.assertFalse(result['execution_enabled'])
                self.assertIsNone(result['quantity'])
        normalized=evaluate_order_costs(fixture(venue='LINEAR_FUTURES_SIMULATION',
            leverage='1.000',approved_max_leverage='2.000'))
        canonical=evaluate_order_costs(fixture(venue='LINEAR_FUTURES_SIMULATION',
            leverage='1',approved_max_leverage='2'))
        self.assertEqual(normalized,canonical)
        self.assertTrue(normalized['feasible_hypothesis'])

    def test_missing_required_filters_prices_rates_or_budgets_are_unknown(self):
        for field in ('min_notional','min_qty','lot_step','tick_size','entry_fee_rate','exit_fee_rate',
                      'entry_slippage_rate','exit_slippage_rate','available_capital','risk_budget','reference_price'):
            with self.subTest(field=field):
                result=evaluate_order_costs(fixture(**{field:None}))
                self.assertEqual(result['state'],'UNKNOWN')
                self.assertFalse(result['feasible_hypothesis'])
                self.assertIsNone(result['quantity'])

    def test_non_finite_negative_boolean_float_massive_or_extreme_decimals_are_rejected(self):
        for invalid in ('NaN','sNaN','Infinity','-Infinity','-1','-0',True,1.5,float('nan'),
                        Decimal('1e-1000000000'),Decimal('1e1000000000'),'1'*81,10**1000,
                        '1e19','0.0000000000000000000000000000001',' 1','1 '):
            with self.subTest(kind=type(invalid).__name__):
                result=evaluate_order_costs(fixture(available_capital=invalid))
                self.assertEqual(result['state'],'REJECTED_HYPOTHESIS')
                self.assertFalse(result['feasible_hypothesis'])
                self.assertIsNone(result['quantity'])
        result=evaluate_order_costs(fixture(available_capital='PRIVATE_UNTRUSTED_VALUE'))
        self.assertNotIn('PRIVATE_UNTRUSTED_VALUE',json.dumps(result))

    def test_zero_budgets_zero_increments_and_invalid_rates_or_stops_cannot_become_an_order(self):
        for settings in ({'available_capital':'0'},{'risk_budget':'0'},{'max_notional':'0'},
                         {'lot_step':'0'},{'tick_size':'0'},{'reference_price':'0'},
                         {'entry_fee_rate':'1'},{'exit_fee_rate':'1'},{'entry_slippage_rate':'1'},
                         {'stop_price':'10'},{'stop_price':'11'},
                         {'max_qty':'0'},{'max_qty':'0.0001','min_qty':'1'}):
            with self.subTest(settings=settings):
                result=evaluate_order_costs(fixture(**settings))
                self.assertEqual(result['state'],'REJECTED_HYPOTHESIS')
                self.assertFalse(result['execution_enabled'])

    def test_scope_spot_short_and_leverage_policy_never_gain_authority(self):
        for settings in ({'venue':'LIVE'},{'venue':'FUTURES_DEMO'},{'quote_asset':'USD'},
                         {'direction':[]},{'direction':{}},{'venue':[]},{'quote_asset':{}},
                         {'direction':'SELL'},{'direction':'SHORT','stop_price':'11'},
                         {'leverage':'2','approved_max_leverage':'2'},
                         {'venue':'LINEAR_FUTURES_SIMULATION','leverage':'3','approved_max_leverage':'2'}):
            with self.subTest(settings=settings):
                result=evaluate_order_costs(fixture(**settings))
                self.assertFalse(result['feasible_hypothesis'])
                self.assertIs(result['financial_authorization'],False)
        self.assertEqual(evaluate_order_costs({})['reason_codes'],['TYPED_SCENARIO_REQUIRED'])

    def test_reproducible_exact_decimal_results_ignore_ambient_precision_and_rounding(self):
        scenario=fixture(reference_price='0.000000000000000001',stop_price='0.0000000000000000005',
            tick_size='0.000000000000000000000000000001',lot_step='0.000000000000000000000000000001',
            available_capital='1000000000000000000',max_notional='1000000000000000000',
            min_notional='0',risk_budget='0.000000000000000001')
        baseline=evaluate_order_costs(scenario)
        self.assertTrue(baseline['feasible_hypothesis'])
        with localcontext() as context:
            context.prec=2
            context.Emax=2
            context.Emin=-2
            self.assertEqual(evaluate_order_costs(scenario),baseline)
        self.assertLessEqual(d(baseline['estimated_stop_risk']),d(scenario.risk_budget))

    def test_sizing_does_not_modify_inputs_configuration_or_make_io_calls(self):
        scenario=fixture()
        before=asdict(scenario)
        with (patch('socket.socket.connect',side_effect=AssertionError('network')),
              patch('builtins.open',side_effect=AssertionError('file'))):
            result=evaluate_order_costs(scenario)
        self.assertTrue(result['feasible_hypothesis'])
        self.assertEqual(asdict(scenario),before)


class MigrationCostCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('audit_migration_costs',
            Path(__file__).resolve().parents[1]/'scripts'/'audit_migration_costs.py')
        cls.cli=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    def run_cli(self,text):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'scenario.json'
            path.write_text(text,encoding='utf-8')
            before=path.read_bytes()
            with redirect_stdout(io.StringIO()) as output:
                code=self.cli.main(['--scenario',str(path)])
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(list(Path(folder).iterdir()),[path])
            return code,json.loads(output.getvalue())

    def test_cli_complete_explicit_scenarios_are_independent_not_simultaneously_funded(self):
        value={'schema':1,'mode':'INDEPENDENT_SIMULATIONS','items':[asdict(fixture())]*4}
        code,result=self.run_cli(json.dumps(value))
        self.assertEqual(code,0)
        self.assertEqual(len(result['items']),4)
        self.assertTrue(result['independent_scenarios'])
        self.assertFalse(result['simultaneous_funding_evaluated'])
        self.assertFalse(result['execution_enabled'])
        self.assertFalse(result['financial_authorization'])

    def test_cli_missing_filters_and_impossible_minimum_are_not_promoted(self):
        for scenario,state in ((fixture(min_notional=None),'UNKNOWN'),
                               (fixture(min_notional='1000'),'REJECTED_HYPOTHESIS')):
            code,result=self.run_cli(json.dumps({'schema':1,'mode':'INDEPENDENT_SIMULATIONS','items':[asdict(scenario)]}))
            self.assertEqual(code,1)
            self.assertEqual(result['items'][0]['state'],state)

    def test_cli_strict_schema_duplicates_constants_and_untrusted_text_fail_without_echo(self):
        good={'schema':1,'mode':'INDEPENDENT_SIMULATIONS','items':[asdict(fixture())]}
        invalids=['PRIVATE_INVALID_JSON','{"schema":1,"schema":1,"mode":"INDEPENDENT_SIMULATIONS","items":[]}',
                  json.dumps(dict(good,secret='PRIVATE_SECRET')),
                  json.dumps(dict(good,schema=True)),json.dumps(dict(good,items=[])),
                  json.dumps(dict(good,items=[asdict(fixture())]*5)),
                  json.dumps(dict(good,items=[dict(asdict(fixture()),extra='PRIVATE_SECRET')])),
                  json.dumps(good).replace('"100"','NaN',1),
                  json.dumps(good).replace('"100"','Infinity',1)]
        for text in invalids:
            with self.subTest(length=len(text)):
                code,result=self.run_cli(text)
                self.assertEqual(code,2)
                self.assertEqual(result['state'],'INVALID_INPUT')
                self.assertNotIn('PRIVATE_',json.dumps(result))
                self.assertEqual(result['items'],[])

    def test_cli_bounded_json_numbers_and_file_size_are_rejected_before_expensive_math(self):
        good=json.dumps({'schema':1,'mode':'INDEPENDENT_SIMULATIONS','items':[asdict(fixture())]})
        for text in (good.replace('"100"','1'*81,1),good.replace('"100"','1e'+('1'*81),1),' '*16385):
            code,result=self.run_cli(text)
            self.assertEqual(code,2)
            self.assertFalse(result['execution_enabled'])


if __name__ == '__main__':
    unittest.main()
