"""Deterministic SIM inputs exercise admission hypotheses, never actual orders."""
from dataclasses import FrozenInstanceError, replace
import json
import unittest

from trader.capital_manager_shadow import AccountScope, MAX_INTEGER, SimulationError
from trader.global_risk_shadow import Candidate, Exposure, Inventory, RiskPolicy, assess_risk


U = 1_000_000
NOW = 1_800_000_000.


def fixture():
    scope = AccountScope('SHADOW','SIM_RISK_ACCOUNT','USDT')
    policy = RiskPolicy('SIM_RISK_POLICY',scope,NOW-3600,1000*U,50*U,8,2000,
        (('SIM_SPOT',600*U,40*U),('SIM_QUANT',600*U,40*U)),
        (('BTCUSDT',600*U,30*U),('ETHUSDT',600*U,30*U)),
        (('SIM_CRYPTO_FACTOR',900*U,45*U),),100*U,200*U,150*U,
        500_000,750_000,2*U,30,20,15)
    existing = Exposure('SIM_EXISTING','SIM_SPOT','BTCUSDT','LONG',100*U,4*U,
                        1000,'SIM_CRYPTO_FACTOR',NOW-1,True)
    inventory = Inventory(scope,NOW-1,True,True,True,800*U,True,
                          0,0,0,True,True,'READY',False,(existing,),())
    proposed = Exposure('SIM_NEW','SIM_QUANT','ETHUSDT','SHORT',100*U,3*U,
                        1000,'SIM_CRYPTO_FACTOR',NOW-1,True)
    candidate = Candidate('SIM_CANDIDATE',scope,NOW-1,(proposed,),101*U,10,10,5,True)
    return policy, inventory, candidate


class GlobalRiskShadowTests(unittest.TestCase):
    def assess(self, policy=None, inventory=None, candidate=None):
        p,i,c = fixture()
        return assess_risk(policy or p,inventory or i,candidate or c,now=NOW)

    def assert_blocked(self, report, reason, state=None):
        self.assertFalse(report['hypothetical_admission'])
        self.assertIn(reason,report['reasons'])
        if state:
            self.assertEqual(report['state'],state)

    def test_normal_before_after_are_immutable_and_authority_is_always_false(self):
        p,i,c = fixture()
        before = repr((p,i,c))
        report = assess_risk(p,i,c,now=NOW)
        self.assertEqual(report['state'],'NORMAL')
        self.assertTrue(report['hypothetical_admission'])
        self.assertEqual(report['before'],{'gross_units':100*U,'inclusive_stop_risk_units':4*U,'positions':1})
        self.assertEqual(report['after'],{'gross_units':200*U,'inclusive_stop_risk_units':7*U,'positions':2})
        for key in ('execution_enabled','controls_enabled','can_veto','reservations_enabled','promotion_allowed'):
            self.assertIs(report[key],False)
        self.assertEqual(repr((p,i,c)),before)
        with self.assertRaises(FrozenInstanceError):
            p.gross_limit_units = 900000*U

    def test_loss_states_have_objective_thresholds_and_reduced_cap_is_additional(self):
        p,i,c = fixture()
        for loss,state in ((49,'NORMAL'),(50,'CAUTION'),(74,'CAUTION')):
            report = self.assess(inventory=replace(i,daily_pnl_units=-loss*U))
            self.assertEqual(report['state'],state)
            self.assertTrue(report['hypothetical_admission'])
        small = replace(c,legs=(replace(c.legs[0],inclusive_stop_risk_units=U),))
        report = self.assess(inventory=replace(i,daily_pnl_units=-75*U),candidate=small)
        self.assertEqual(report['state'],'RISK_REDUCED')
        self.assertTrue(report['hypothetical_admission'])
        self.assertEqual(report['reduced_candidate_risk_cap_units'],2*U)
        report = self.assess(inventory=replace(i,daily_pnl_units=-75*U))
        self.assert_blocked(report,'REDUCED_CANDIDATE_RISK_CAP_EXCEEDED','ENTRY_HALTED')
        self.assert_blocked(self.assess(inventory=replace(i,daily_pnl_units=-100*U)),
                            'DAILY_LOSS_LIMIT_REACHED','ENTRY_HALTED')

    def test_weekly_loss_and_drawdown_are_not_derived_from_missing_or_daily_only_data(self):
        p,i,c = fixture()
        self.assert_blocked(self.assess(inventory=replace(i,weekly_pnl_units=-200*U)),
                            'WEEKLY_LOSS_LIMIT_REACHED','ENTRY_HALTED')
        self.assert_blocked(self.assess(inventory=replace(i,drawdown_units=150*U)),
                            'DRAWDOWN_LIMIT_REACHED','ENTRY_HALTED')
        for key in ('daily_pnl_units','weekly_pnl_units','drawdown_units','loss_baselines_verified'):
            with self.subTest(key=key):
                self.assert_blocked(self.assess(inventory=replace(i,**{key:None})),
                                    'LOSS_BASELINES_OR_METRICS_UNKNOWN','RECOVERY_REQUIRED')

    def test_accounts_and_environments_never_form_a_joint_wallet(self):
        p,i,c = fixture()
        for scope in (AccountScope('SHADOW','SIM_OTHER_ACCOUNT','USDT'),
                      AccountScope('FUTURES_DEMO','SIM_RISK_ACCOUNT','USDT')):
            report = self.assess(candidate=replace(c,scope=scope))
            self.assert_blocked(report,
                                'ACCOUNT_OR_ENVIRONMENT_SCOPE_MISMATCH','RECOVERY_REQUIRED')
            self.assertEqual(report['before']['gross_units'],100*U)
            self.assertTrue(all(value is None for value in report['after'].values()))
            self.assertIsNone(report['candidate_inclusive_stop_risk_units'])
            self.assertIsNone(report['conservative_margin_floor_units'])
            report = self.assess(inventory=replace(i,scope=scope))
            self.assertTrue(all(value is None for value in report['before'].values()))
            self.assertTrue(all(value is None for value in report['after'].values()))
        with self.assertRaises(SimulationError):
            AccountScope('LIVE','SIM_RISK_ACCOUNT','USDT')
        with self.assertRaises(SimulationError):
            AccountScope('SHADOW','REAL_ACCOUNT_ID','USDT')

    def test_unknown_inventory_orders_or_margin_and_missing_protection_require_recovery(self):
        p,i,c = fixture()
        cases = (('account_identity_verified',None,'ACCOUNT_IDENTITY_UNVERIFIED'),
                 ('inventory_complete',False,'INVENTORY_INCOMPLETE_OR_UNKNOWN'),
                 ('reconciliation_complete',None,'ORDER_RECONCILIATION_INCOMPLETE_OR_UNKNOWN'),
                 ('available_margin_units',None,'AVAILABLE_MARGIN_UNKNOWN'),
                 ('margin_is_net_of_commitments',None,'AVAILABLE_MARGIN_UNKNOWN'))
        for key,value,reason in cases:
            self.assert_blocked(self.assess(inventory=replace(i,**{key:value})),reason,'RECOVERY_REQUIRED')
        existing = replace(i.positions[0],protection_verified=False)
        self.assert_blocked(self.assess(inventory=replace(i,positions=(existing,))),
                            'EXISTING_PROTECTION_MISSING_OR_UNKNOWN','RECOVERY_REQUIRED')

    def test_opposite_directions_and_pending_entries_get_no_hedge_credit(self):
        p,i,c = fixture()
        opposite = replace(c.legs[0],symbol='BTCUSDT',gross_units=550*U,
                           inclusive_stop_risk_units=28*U)
        report = self.assess(candidate=replace(c,legs=(opposite,)))
        self.assertEqual(report['after']['gross_units'],650*U)
        self.assertEqual(report['after']['inclusive_stop_risk_units'],32*U)
        self.assert_blocked(report,'ASSET_GROSS_LIMIT_EXCEEDED')
        self.assertIn('ASSET_STOP_RISK_LIMIT_EXCEEDED',report['reasons'])
        pending = replace(i.positions[0],exposure_id='SIM_PENDING',gross_units=550*U)
        self.assert_blocked(self.assess(inventory=replace(i,pending=(pending,))),
                            'ENGINE_GROSS_LIMIT_EXCEEDED')

    def test_global_limits_and_all_correlation_legs_are_checked_before_and_after(self):
        p,i,c = fixture()
        huge = replace(c.legs[0],gross_units=950*U,inclusive_stop_risk_units=49*U)
        report = self.assess(candidate=replace(c,legs=(huge,)))
        self.assert_blocked(report,'GLOBAL_GROSS_LIMIT_EXCEEDED')
        self.assertIn('GLOBAL_STOP_RISK_LIMIT_EXCEEDED',report['reasons'])
        self.assertIn('CORRELATION_GROSS_LIMIT_EXCEEDED',report['reasons'])
        self.assertIn('CORRELATION_STOP_RISK_LIMIT_EXCEEDED',report['reasons'])
        self.assert_blocked(self.assess(inventory=replace(i,correlation_evidence_verified=None)),
                            'CORRELATION_GROUP_EVIDENCE_UNVERIFIED','RECOVERY_REQUIRED')
        unknown = replace(c.legs[0],correlation_group='SIM_UNCLASSIFIED')
        self.assert_blocked(self.assess(candidate=replace(c,legs=(unknown,))),
                            'CORRELATION_BUDGET_UNKNOWN','RECOVERY_REQUIRED')

    def test_stale_future_or_unavailable_exchange_manual_halt_and_costs_block_only_simulation(self):
        p,i,c = fixture()
        for at in (NOW-31,NOW+1):
            self.assert_blocked(self.assess(inventory=replace(i,observed_at=at)),
                                'STALE_OR_FUTURE_DATA','ENTRY_HALTED')
            self.assert_blocked(self.assess(candidate=replace(c,legs=(replace(c.legs[0],market_at=at),))),
                                'STALE_OR_FUTURE_DATA','ENTRY_HALTED')
        self.assert_blocked(self.assess(inventory=replace(i,exchange_state='UNKNOWN')),'EXCHANGE_NOT_READY')
        self.assert_blocked(self.assess(inventory=replace(i,manual_entry_halt=True)),'MANUAL_ENTRY_HALT')
        for key,value in (('estimated_slippage_bps',None),('estimated_slippage_bps',21),('spread_bps',16)):
            self.assert_blocked(self.assess(candidate=replace(c,**{key:value})),
                                'EXECUTION_COSTS_UNKNOWN_OR_EXCESSIVE')
        self.assert_blocked(self.assess(candidate=replace(c,liquidity_verified=None)),'LIQUIDITY_UNVERIFIED')

    def test_positions_leverage_margin_and_candidate_protection_plan_are_explicit(self):
        p,i,c = fixture()
        self.assert_blocked(self.assess(policy=replace(p,max_positions=1)),'POSITION_LIMIT_EXCEEDED')
        self.assert_blocked(self.assess(candidate=replace(c,required_margin_units=801*U)),
                            'INSUFFICIENT_AVAILABLE_MARGIN')
        self.assert_blocked(self.assess(candidate=replace(c,legs=(replace(c.legs[0],leverage_milli=3000),))),
                            'LEVERAGE_LIMIT_EXCEEDED')
        self.assert_blocked(self.assess(candidate=replace(c,legs=(replace(c.legs[0],protection_verified=None),))),
                            'CANDIDATE_PROTECTION_PLAN_UNVERIFIED')

    def test_missing_stop_risk_is_unknown_and_does_not_erase_known_existing_risk(self):
        p,i,c = fixture()
        report = self.assess(candidate=replace(c,legs=(replace(c.legs[0],inclusive_stop_risk_units=None),)))
        self.assert_blocked(report,'INCLUSIVE_STOP_RISK_UNKNOWN','RECOVERY_REQUIRED')
        self.assertEqual(report['before']['inclusive_stop_risk_units'],4*U)
        self.assertIsNone(report['after']['inclusive_stop_risk_units'])

    def test_atomic_integer_overflow_is_unknown_not_a_float_or_optimistic_balance(self):
        p,i,c = fixture()
        existing = replace(i.positions[0],gross_units=MAX_INTEGER)
        report = self.assess(inventory=replace(i,positions=(existing,)))
        self.assert_blocked(report,'AGGREGATE_ATOMIC_MONEY_RANGE_EXCEEDED','RECOVERY_REQUIRED')
        self.assertIsNone(report['after']['gross_units'])
        self.assertEqual(report['before']['gross_units'],MAX_INTEGER)

    def test_policies_have_no_implicit_financial_defaults_or_mutable_budget_rows(self):
        p,i,c = fixture()
        with self.assertRaises(TypeError):
            RiskPolicy('SIM_POLICY')
        for settings in ({'engine_limits':list(p.engine_limits)},
                         {'asset_limits':(('BTCUSDT',1001*U,U),)},
                         {'caution_fraction_ppm':800000,'reduced_fraction_ppm':750000},
                         {'gross_limit_units':True},{'reduced_candidate_risk_cap_units':51*U}):
            with self.subTest(settings=settings), self.assertRaises(SimulationError):
                replace(p,**settings)
        with self.assertRaises(SimulationError):
            replace(c.legs[0],gross_units=1.5)
        with self.assertRaises(SimulationError):
            assess_risk({},i,c,now=NOW)

    def test_margin_floor_prevents_a_microunit_request_funding_a_large_leg(self):
        p,i,c = fixture()
        report = self.assess(inventory=replace(i,available_margin_units=1),
                            candidate=replace(c,required_margin_units=1))
        self.assert_blocked(report,'REQUIRED_MARGIN_BELOW_CONSERVATIVE_FLOOR','ENTRY_HALTED')
        self.assertEqual(report['conservative_margin_floor_units'],100_400_000)
        self.assertEqual(report['roundtrip_cost_floor_units'],400_000)
        self.assert_blocked(self.assess(candidate=replace(c,estimated_fee_bps=None)),
                            'EXECUTION_FEES_UNKNOWN','ENTRY_HALTED')
        self.assert_blocked(self.assess(candidate=replace(c,legs=(replace(c.legs[0],inclusive_stop_risk_units=1),))),
                            'INCLUSIVE_STOP_RISK_BELOW_COST_FLOOR','ENTRY_HALTED')

    def test_margin_and_cost_floors_round_up_each_leg_without_netting_or_leverage_quantity(self):
        p,i,c = fixture()
        legs = (replace(c.legs[0],gross_units=1001,leverage_milli=2000),
                replace(c.legs[0],exposure_id='SIM_SECOND_LEG',direction='LONG',gross_units=1001,leverage_milli=2000))
        report = self.assess(candidate=replace(c,legs=legs,required_margin_units=1012))
        self.assertTrue(report['hypothetical_admission'])
        # Each principal ceil(1001/2)=501; roundtrip fee/slip ceil(4.004)=5.
        self.assertEqual(report['conservative_margin_floor_units'],1012)
        self.assertEqual(report['roundtrip_cost_floor_units'],10)
        self.assertEqual(report['after']['gross_units'],100*U+2002)
        self.assert_blocked(self.assess(candidate=replace(c,legs=legs,required_margin_units=1011)),
                            'REQUIRED_MARGIN_BELOW_CONSERVATIVE_FLOOR')

    def test_loss_assessment_has_no_persistent_latch_and_does_not_claim_one(self):
        p,i,c = fixture()
        halted = self.assess(inventory=replace(i,daily_pnl_units=-100*U))
        recovered = self.assess(inventory=replace(i,daily_pnl_units=0))
        self.assertFalse(halted['hypothetical_admission'])
        self.assertEqual(recovered['state'],'NORMAL')
        self.assertFalse(recovered['controls_enabled'])


if __name__ == '__main__':
    unittest.main()
