"""Synthetic policy drafts; no real approval, account, config or capital."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.central_admission import AdmissionPolicy
from trader.live_policy_review import (canonical,load_policy_review,prepare_live_policy_file,
    prepare_live_policy_review)


AT='2026-10-26T00:00:00Z'
FLAGS=('active','execution_enabled','capital_allocated','financial_authorization',
       'apply_to_current_testnet','automatic_activation','ready_for_live','materializable')


def draft():
    return {'schema':'policy-review-proposal/v1','state':'OWNER_REVIEWED_INACTIVE',
        'created_at':AT,'owner_reviewed_at':AT,'owner_approval_source':'SYNTHETIC_REVIEW_METADATA_ONLY',
        'owner_approval_received':True,'execution_enabled':False,'capital_allocated':False,
        'financial_authorization':False,'apply_to_current_testnet':False,'currency':'USDT',
        'capital_budget':120,'wallet_budgets':{'SPOT_LIVE':60,'FUTURES_LIVE':60},
        'per_trade_estimated_stop_risk_cap':0.4,'per_trade_risk_pct_of_each_wallet':1,
        'global_estimated_open_stop_risk_cap':1.6,'daily_loss_cap_utc':2.4,
        'weekly_loss_cap_utc':6.4,'cashflow_adjusted_drawdown_cap':12,
        'wallet_loss_caps':{scope:{'daily':1.2,'weekly':3.2,'drawdown':6,'open_stop_risk':0.8}
                            for scope in ('SPOT_LIVE','FUTURES_LIVE')},
        'max_positions_per_engine':1,'max_positions_total':2,'spot_leverage':1,'futures_max_leverage':2,
        'futures_margin_mode_required':'ISOLATED','futures_position_mode_required':'ONE_WAY',
        'gross_exposure_caps':{'SPOT_LIVE':30,'FUTURES_LIVE':60,'total_static_envelope':90,'per_asset':25},
        'risk_aggregation':'GROSS_NO_SHORT_HEDGE_CREDIT','initial_engines':['SPOT','FUTURES'],
        'pulse_quant':'SHADOW_ONLY_UNTIL_SEPARATE_PROMOTION','hypothesis_only':True,
        'statistically_optimal_claim':False,'usd_usdt_conversion_performed':False,
        'stop_risk_includes':['estimated_stop_distance','fees','adverse_slippage']}


class InactivePolicyTemplateTests(unittest.TestCase):
    def test_review_is_exact_micro_units_and_never_an_authorization(self):
        source=draft();before=deepcopy(source);result=prepare_live_policy_review(source,created_at=AT)
        self.assertEqual(result['state'],'INACTIVE_REVIEW_ONLY');self.assertTrue(all(result[k] is False for k in FLAGS))
        self.assertEqual(result['global_nominal_limits']['capital_budget_units'],120_000_000)
        self.assertEqual(result['global_nominal_limits']['per_trade_stop_risk_limit_units'],400_000)
        self.assertEqual(result['owner_review_metadata']['recorded_source'],source['owner_approval_source'])
        self.assertFalse(result['owner_review_metadata']['grants_financial_authority']);self.assertEqual(source,before)
        for scope in ('SPOT_LIVE','FUTURES_LIVE'):
            template=result['wallet_templates'][scope];fields=template['admission_policy_fields']
            self.assertFalse(template['materializable']);self.assertEqual(fields['capital_budget_units'],60_000_000)
            for key in ('policy_id','approval_reference','approved_at','asset_limits','correlation_limits',
                        'max_fee_bps','max_slippage_bps','max_spread_bps','caution_fraction_ppm','max_data_age_seconds'):
                self.assertIsNone(fields[key]);self.assertIn(key,template['unknown_fields'])
            with self.assertRaises(ValueError):AdmissionPolicy(**fields)
        source['stop_risk_includes'].append('mutated afterwards')
        self.assertNotIn('mutated afterwards',result['explicit_constraints']['stop_risk_includes'])

    def test_omitted_amounts_and_review_metadata_never_default_to_capital_or_approval(self):
        source={k:v for k,v in draft().items() if k in {'schema','state','execution_enabled',
            'capital_allocated','financial_authorization','apply_to_current_testnet'}}
        result=prepare_live_policy_review(source,created_at=AT)
        self.assertIsNone(result['currency']);self.assertIsNone(result['global_nominal_limits']['capital_budget_units'])
        self.assertIsNone(result['owner_review_metadata']['recorded_received'])
        self.assertIsNone(result['wallet_templates']['SPOT_LIVE']['admission_policy_fields']['capital_budget_units'])
        self.assertNotIn('100000000',canonical(result));self.assertFalse(result['materializable'])

    def test_every_known_wallet_envelope_must_fit_global_limit(self):
        changes=[('wallet_budgets','SPOT_LIVE',61),('gross_exposure_caps','SPOT_LIVE',31)]
        changes += [('wallet_loss_caps','SPOT_LIVE.'+key,value) for key,value in
                    (('daily',1.3),('weekly',3.3),('drawdown',6.1),('open_stop_risk',0.9))]
        for category,key,amount in changes:
            source=draft();target=source[category]
            parts=key.split('.')
            if len(parts)==2:target=target[parts[0]]
            target[parts[-1]]=amount
            with self.subTest(category=category,key=key),self.assertRaises(ValueError):
                prepare_live_policy_review(source,created_at=AT)
        source=draft();source['wallet_budgets']={'SPOT_LIVE':121}
        with self.assertRaises(ValueError):prepare_live_policy_review(source,created_at=AT)

    def test_position_leverage_currency_and_percentage_inconsistencies_fail(self):
        for key,value in (('max_positions_total',1),('spot_leverage',2),('futures_margin_mode_required','CROSSED'),
                          ('risk_aggregation','NET_LONG_MINUS_SHORT'),('per_trade_risk_pct_of_each_wallet',0.1),
                          ('currency','USD'),('per_trade_estimated_stop_risk_cap',2)):
            source=draft();source[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):prepare_live_policy_review(source,created_at=AT)
        source=draft();del source['currency']
        with self.assertRaises(ValueError):prepare_live_policy_review(source,created_at=AT)

    def test_nonfinite_bool_inexact_money_and_unknown_fields_fail(self):
        for value in (True,float('nan'),float('inf'),0,-1,'120',0.0000001):
            source=draft();source['capital_budget']=value
            with self.subTest(value=str(value)),self.assertRaises((ValueError,TypeError)):
                prepare_live_policy_review(source,created_at=AT)
        for key in ('approval_token','active_policy','api_key','unknown_budget'):
            source=draft();source[key]='SYNTHETIC'
            with self.assertRaises(ValueError):prepare_live_policy_review(source,created_at=AT)

    def test_active_source_claim_or_future_review_cannot_create_template(self):
        for flag in ('execution_enabled','capital_allocated','financial_authorization','apply_to_current_testnet',
                     'usd_usdt_conversion_performed','statistically_optimal_claim'):
            source=draft();source[flag]=True
            with self.assertRaises(ValueError):prepare_live_policy_review(source,created_at=AT)
        source=draft();source['owner_reviewed_at']='2026-10-27T00:00:00Z'
        with self.assertRaises(ValueError):prepare_live_policy_review(source,created_at=AT)


class PolicyReviewFileTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/'explicit-review.json';self.output=self.root/'inactive-template.json'
        self.source.write_text(canonical(draft()),encoding='utf-8')

    def test_functional_file_creation_is_canonical_new_and_preserves_source(self):
        original=self.source.read_bytes()
        result=prepare_live_policy_file(self.source,self.output,clock=lambda:AT)
        value=json.loads(self.output.read_text());self.assertEqual(self.output.read_bytes(),canonical(value).encode('ascii'))
        self.assertEqual(result['state'],'INACTIVE_REVIEW_FILE_CREATED');self.assertEqual(self.source.read_bytes(),original)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),['explicit-review.json','inactive-template.json'])
        before=self.output.read_bytes()
        with self.assertRaises(ValueError):prepare_live_policy_file(self.source,self.output,clock=lambda:AT)
        self.assertEqual(before,self.output.read_bytes())

    def test_alias_protected_formats_and_publish_race_never_overwrite(self):
        with self.assertRaises(ValueError):prepare_live_policy_file(self.source,self.source,clock=lambda:AT)
        for name in ('authorization.dpapi','readiness.dpapi','config.toml','.env'):
            with self.assertRaises(ValueError):prepare_live_policy_file(self.source,self.root/name,clock=lambda:AT)
            self.assertFalse((self.root/name).exists())
        from trader.live_policy_review import _write_new
        self.output.write_text('retain me')
        with self.assertRaises(OSError):_write_new(self.output,{'replacement':True})
        self.assertEqual(self.output.read_text(),'retain me')

    def test_json_limits_duplicate_keys_hardlinks_and_linked_paths_fail(self):
        for raw in ('{"schema":1,"schema":1}','{"risk":NaN}','x'*32769):
            self.source.write_text(raw)
            with self.assertRaises(ValueError):load_policy_review(self.source)
        self.source.write_text(canonical(draft()))
        linked=self.root/'linked.json';os.link(self.source,linked)
        with self.assertRaises(ValueError):load_policy_review(self.source)
        linked.unlink()
        with patch.object(Path,'is_symlink',lambda self:True),self.assertRaises(ValueError):load_policy_review(self.source)
        self.assertFalse(self.output.exists())

    def test_cli_creates_only_inactive_artifact_and_sanitizes_invalid_arguments(self):
        script=Path(__file__).resolve().parents[1]/'scripts'/'prepare_live_policy.py'
        process=subprocess.run([sys.executable,'-I','-B',str(script),'--review',str(self.source),'--output',str(self.output)],
            capture_output=True,timeout=15)
        self.assertEqual(process.returncode,0,process.stderr.decode(errors='replace'))
        status=json.loads(process.stdout);self.assertTrue(all(status[k] is False for k in FLAGS))
        value=json.loads(self.output.read_text());self.assertEqual(value['state'],'INACTIVE_REVIEW_ONLY')
        self.assertNotIn('SYNTHETIC_REVIEW_METADATA_ONLY',process.stdout.decode())
        self.assertFalse((self.root/'authorization.dpapi').exists());self.assertFalse((self.root/'readiness.dpapi').exists())
        rejected=subprocess.run([sys.executable,'-I','-B',str(script),'--unexpected','SECRET_SENTINEL'],capture_output=True,timeout=15)
        self.assertEqual(rejected.returncode,2);self.assertNotIn(b'SECRET_SENTINEL',rejected.stdout+rejected.stderr)


if __name__=='__main__':unittest.main()
