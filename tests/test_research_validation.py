"""Evidence presence cannot certify causal gains or authorize financial control."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from trader.quant_research import quant_research_evidence
from trader.research_runtime import project_report
from trader.research_validation import build_validation_summary, MAX_BYTES


NOW = 1_800_000_000.
AT = '2027-01-15T08:00:00Z'


def fixture():
    return {'mode':'RESEARCH_ONLY', 'auto_promotion':False, 'generated_at':AT,
        'assets':[{'symbol':'BTCUSDT','holdout':{'double_costs':{'return_pct':1000}}}],
        'futures_assets':[{'symbol':'ETHUSDT','holdout':{},'double_cost_holdout':{}}],
        'methodology':{'validation':'walk_forward_reserved_holdout'},
        'operating_baselines':[{'market':market,'evidence':'SIGNAL_PARITY_ONLY',
            'profitability_evaluated':False} for market in ('SPOT','FUTURES')],
        'forward_observation':[{'market':'SPOT','status':'OBSERVING'},
                               {'market':'FUTURES','status':'WAITING_NEW_DATA'}],
        'market_pulse_observation':{'engine':'AI_MARKET_PULSE','mode':'SHADOW',
            'captured_at':AT,'automatic_promotion':False,'decisions':100,
            'replay':{'checked':100,'mismatches':0,'invalid_timestamps':0}},
        'quant_observation':{'schema':1,'engine':'QUANT_ARBITRAGE','mode':'SHADOW',
            'captured_at':AT,'execution_enabled':False,'automatic_promotion':False,
            'state':'AVAILABLE','counts':{'decisions':100},
            'replay':{'checked':16,'matches':16,'mismatches':0,'unavailable':0,'sampled':16}}}


class ResearchValidationTests(unittest.TestCase):
    def test_four_environments_are_separate_and_methodology_is_not_execution_validation(self):
        report = fixture()
        before = copy.deepcopy(report)
        summary = build_validation_summary(report, now=NOW)
        self.assertEqual(report, before)
        self.assertEqual([row['engine'] for row in summary['engines']],
                         ['SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE'])
        self.assertEqual([row['evidence_environment'] for row in summary['engines']],
                         ['PUBLIC_MARKET_RESEARCH','PUBLIC_MARKET_RESEARCH','SHADOW','SHADOW'])
        self.assertEqual(summary['engines'][0]['cost_stress'], 'METHODOLOGY_PRESENT_NOT_EXECUTION_VALIDATED')
        self.assertTrue(all(not row['execution_validated'] for row in summary['engines']))
        self.assertEqual(summary['engines'][0]['operating_signal_reference'], 'SIGNAL_PARITY_ONLY')
        self.assertEqual(summary['engines'][1]['forward_state'], 'WAITING_NEW_DATA')
        self.assertIsNone(summary['comparison']['aggregate_capital'])
        self.assertIsNone(summary['comparison']['best_strategy'])
        self.assertEqual(summary['comparison']['state'], 'NOT_COMPARABLE_NO_MATCHED_EXECUTION_COHORT')

    def test_positive_returns_and_forged_approval_cannot_promote_or_create_avoided_losses(self):
        report = fixture()
        report.update(approved=True, guardian_control=True, testnet_eligible=True,
                      losses_avoided=100000, pnl_without_ai=999999)
        for row in report['assets']+report['futures_assets']:
            row.update(return_pct=999999, profit_factor=999, approved=True)
        summary = build_validation_summary(report, now=NOW)
        for field in ('execution_enabled','controls_enabled','reservations_enabled','promotion_allowed'):
            self.assertIs(summary[field], False)
        self.assertEqual(summary['autonomy_level'], 0)
        for row in summary['engines']:
            self.assertIsNone(row['attribution']['estimated_pnl_without_ai'])
            self.assertIsNone(row['attribution']['estimated_losses_avoided'])
            self.assertFalse(row['attribution']['causal_claim_allowed'])
        self.assertTrue(all(row['state'] in {'NOT_CERTIFIED_BY_THIS_REPORT','SEPARATE_AUTHORIZATION_REQUIRED'}
                            for row in summary['control_preconditions']))

    def test_absent_or_future_or_unauthorized_source_does_not_become_verified_evidence(self):
        for report in ({}, dict(fixture(),generated_at='2099-01-01T00:00:00Z'),
                       dict(fixture(),mode='LIVE'), dict(fixture(),auto_promotion=True),
                       dict(fixture(),generated_at='2027-01-15T08:00:00')):
            with self.subTest(report_at=report.get('generated_at')):
                summary = build_validation_summary(report, now=NOW)
                self.assertEqual(summary['state'], 'NOT_REPORTED')
                self.assertIsNone(summary['source_generated_at'])
                self.assertIsNone(summary['engines'][0]['strategies_or_assets'])
                self.assertTrue(all(row['replay'] is None for row in summary['engines']))

    def test_raw_provider_model_or_unknown_status_text_is_not_projected(self):
        report = fixture()
        secret = 'UNTRUSTED_PROVIDER_INSTRUCTION_123'
        report['forward_observation'][0]['status'] = secret
        report['quant_observation']['state'] = secret
        report['market_pulse_observation']['replay']['checked'] = True
        report['quant_observation']['replay']['checked'] = 100000
        report['assets'][0].update(reason=secret, source=secret)
        summary = build_validation_summary(report, now=NOW)
        self.assertNotIn(secret, json.dumps(summary))
        self.assertEqual(summary['engines'][0]['forward_state'], 'NOT_REPORTED')
        self.assertEqual(summary['engines'][3]['state'], 'NOT_REPORTED')
        self.assertIsNone(summary['engines'][2]['replay'])
        self.assertIsNone(summary['engines'][3]['replay'])

    def test_missing_quant_remains_unstarted_without_wallet_or_capital(self):
        with tempfile.TemporaryDirectory() as folder:
            report = fixture()
            report['quant_observation'] = quant_research_evidence(folder, now=NOW)
            summary = build_validation_summary(report, now=NOW)
            self.assertEqual(summary['engines'][3]['state'], 'NOT_STARTED')
            self.assertFalse(list(Path(folder).iterdir()))
            self.assertIsNone(summary['comparison']['aggregate_capital'])

    def test_summary_is_bounded_and_survives_shared_report_projection(self):
        report = fixture()
        report['assets'] *= 10000
        report['futures_assets'] *= 10000
        report['forward_observation'] *= 10000
        summary = build_validation_summary(report, now=NOW)
        self.assertLess(len(json.dumps(summary,separators=(',',':')).encode()), MAX_BYTES)
        minimal = {'validation_summary':summary,'history':[]}
        self.assertEqual(project_report(minimal)['validation_summary'], summary)
        self.assertEqual(summary['engines'][0]['strategies_or_assets'], 30)
        self.assertEqual(summary['engines'][1]['strategies_or_assets'], 15)

    def test_observer_evidence_received_after_archived_run_is_not_inserted_into_its_past(self):
        report = fixture()
        report['generated_at'] = '2027-01-15T07:59:00Z'
        summary = build_validation_summary(report,now=NOW)
        for row in summary['engines'][2:]:
            self.assertEqual(row['state'],'NOT_REPORTED')
            self.assertIsNone(row['replay'])
            self.assertIsNone(row['evidence_at'])
        report['generated_at'] = '2027-01-15T07:59:59.999900Z'
        report['market_pulse_observation']['captured_at'] = '2027-01-15T07:59:59.999800Z'
        summary = build_validation_summary(report,now=NOW)
        self.assertEqual(summary['engines'][2]['state'],'FORWARD_SHADOW_ONLY')

    def test_pulse_error_counters_are_independent_bounded_and_never_hidden_as_success(self):
        report = fixture()
        report['market_pulse_observation']['replay'] = {'checked':0,'mismatches':1000,'invalid_timestamps':1000}
        summary = build_validation_summary(report,now=NOW)
        self.assertEqual(summary['engines'][2]['replay'],{'checked':0,'mismatches':1000,'invalid_timestamps':1000})
        report['market_pulse_observation']['replay']['mismatches'] = 1001
        self.assertIsNone(build_validation_summary(report,now=NOW)['engines'][2]['replay'])

    def test_cli_is_read_only_and_does_not_rewrite_archived_evidence_with_current_quant(self):
        spec = importlib.util.spec_from_file_location('audit_research_validation',
            Path(__file__).resolve().parents[1]/'scripts'/'audit_research_validation.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)/'missing-data'
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = module.main(['--data-dir',str(data)])
            self.assertEqual(code,0)
            value = json.loads(buffer.getvalue())
            self.assertEqual(value['research_read_state'],'NOT_STARTED')
            self.assertEqual(value['current_quant_audit']['state'],'NOT_STARTED')
            self.assertFalse(data.exists())
            report = Path(folder)/'archived.json'
            report.write_text(json.dumps(fixture()),encoding='utf-8')
            before = report.read_bytes()
            with patch('trader.research_validation.time.time',return_value=NOW), redirect_stdout(io.StringIO()) as out:
                self.assertEqual(module.main(['--data-dir',str(data),'--research-report',str(report)]),0)
            value = json.loads(out.getvalue())
            self.assertEqual(value['validation_summary']['engines'][3]['state'],'AVAILABLE')
            self.assertEqual(value['current_quant_audit']['state'],'NOT_STARTED')
            self.assertEqual(report.read_bytes(),before)

    def test_cli_rejects_corrupt_report_without_exposing_contents(self):
        spec = importlib.util.spec_from_file_location('audit_research_validation',
            Path(__file__).resolve().parents[1]/'scripts'/'audit_research_validation.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'report.json'
            path.write_text('PRIVATE_INVALID_JSON',encoding='utf-8')
            with redirect_stdout(io.StringIO()) as out:
                code = module.main(['--data-dir',folder,'--research-report',str(path)])
            self.assertEqual(code,1)
            self.assertNotIn('PRIVATE_INVALID_JSON',out.getvalue())
            self.assertEqual(json.loads(out.getvalue())['research_read_state'],'UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
