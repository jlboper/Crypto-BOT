"""Control preparation is a reproducible simulation, never an activation gate."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from trader.control_validation import (
    AUTHORITY_FIELDS, MAX_REPORT_BYTES, _digest, _json,
    read_control_validation, risk_scenarios, run_control_validation,
)


class ControlValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_risk_and_existing_capital_recipes_pass_without_financial_authority(self):
        report = run_control_validation(self.root)
        self.assertEqual(report['state'], 'PASSED')
        self.assertTrue(report['synthetic'])
        self.assertEqual(report['autonomy_level'], 0)
        self.assertEqual(len(report['risk_scenarios']), 18)
        self.assertTrue(all(row['matches'] for row in report['risk_scenarios']))
        self.assertEqual(len(report['capital_protocol']['scenarios']), 7)
        self.assertEqual(report['capital_protocol']['state'], 'PASSED')
        self.assertTrue(all(report[field] is False for field in AUTHORITY_FIELDS))
        files = list(self.root.rglob('*.sqlite3'))
        self.assertEqual(len(files), 7)
        self.assertTrue(all(p.name.startswith('SIM_') and p.name.endswith('.simulation.sqlite3') for p in files))
        self.assertLessEqual(len(_json(report)), MAX_REPORT_BYTES)
        self.assertEqual({row['result']['state'] for row in report['risk_scenarios']},
                         {'NORMAL','CAUTION','RISK_REDUCED','ENTRY_HALTED','RECOVERY_REQUIRED'})

    def test_read_reproduces_risk_without_recreating_wallets_or_rewriting_evidence(self):
        report = run_control_validation(self.root)
        path = self.root / report['report_id'] / 'report.json'
        before = {p.relative_to(self.root):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob('*') if p.is_file()}
        with patch('trader.capital_protocol_lab.run_capital_protocol_lab', side_effect=AssertionError('read executed lab')):
            current = read_control_validation(path)
        self.assertEqual(current, json.loads(_json(report)))
        after = {p.relative_to(self.root):hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_forged_authority_or_claims_fail_even_if_attacker_rehashes_report(self):
        report = run_control_validation(self.root)
        path = self.root / report['report_id'] / 'report.json'
        for change in (lambda x:x.update(controls_enabled=True),lambda x:x.update(state='APPROVED'),
                       lambda x:x.update(autonomy_level=1),lambda x:x.update(extra='untrusted'),
                       lambda x:x['risk_scenarios'][0]['result'].update(hypothetical_admission=False),
                       lambda x:x['source_version'].update(risk_sha256='0'*64)):
            changed = copy.deepcopy(report)
            change(changed)
            changed['report_digest'] = _digest({k:v for k,v in changed.items() if k!='report_digest'})
            path.write_bytes(_json(changed))
            self.assertEqual(read_control_validation(path)['state'], 'UNAVAILABLE')

    def test_missing_and_invalid_reports_never_create_directories(self):
        path = self.root / 'absent' / 'report.json'
        self.assertEqual(read_control_validation(path)['state'], 'NOT_RUN')
        self.assertFalse(path.parent.exists())
        path = self.root / 'report.json'
        path.write_text('private invalid content')
        result = read_control_validation(path)
        self.assertEqual(result['state'], 'UNAVAILABLE')
        self.assertNotIn('private invalid content', json.dumps(result))

    def test_repeated_runs_retain_independent_simulation_cohorts_and_stable_risk_recipes(self):
        first = run_control_validation(self.root)
        second = run_control_validation(self.root)
        self.assertNotEqual(first['report_id'], second['report_id'])
        self.assertEqual(first['risk_scenarios'], risk_scenarios())
        self.assertEqual(first['risk_scenarios'], second['risk_scenarios'])
        self.assertEqual(len(list(self.root.rglob('*.simulation.sqlite3'))), 14)
        self.assertEqual(read_control_validation(self.root/first['report_id']/'report.json')['state'], 'PASSED')

    def test_current_capital_core_and_lab_hashes_are_required_even_after_nested_redigests(self):
        report = run_control_validation(self.root)
        path = self.root/report['report_id']/'report.json'
        from trader import capital_protocol_lab as capital_lab
        self.assertEqual(report['source_version']['capital_protocol_sha256'],
                         hashlib.sha256(Path(capital_lab.protocol.__file__).read_bytes()).hexdigest())
        self.assertEqual(report['source_version']['capital_lab_sha256'],
                         hashlib.sha256(Path(capital_lab.__file__).read_bytes()).hexdigest())
        for field in ('protocol_sha256','lab_sha256'):
            changed = copy.deepcopy(report)
            nested = changed['capital_protocol']
            nested['source_version'][field] = '0'*64
            nested['report_digest'] = _digest({k:v for k,v in nested.items() if k!='report_digest'})
            changed['report_digest'] = _digest({k:v for k,v in changed.items() if k!='report_digest'})
            path.write_bytes(_json(changed))
            self.assertEqual(read_control_validation(path)['state'],'UNAVAILABLE')

    def test_strict_metadata_limitations_and_snapshot_scope_cannot_be_rewritten(self):
        report = run_control_validation(self.root)
        path = self.root/report['report_id']/'report.json'
        self.assertIn('SNAPSHOT_ASSESSMENT_NOT_PERSISTENT_LOSS_LATCH_OR_PERIOD_RESET',report['limitations'])
        self.assertIn('READ_VALIDATES_REPORT_NOT_PERSISTED_WALLETS_OR_ACCOUNT_RECONCILIATION',report['limitations'])
        for change in (lambda x:x.update(autonomy_level=False),lambda x:x.update(report_id='../real-account'),
                       lambda x:x.update(at='2026-10-01'),lambda x:x.update(at='2099-01-01T00:00:00Z'),
                       lambda x:x.update(limitations=[]),lambda x:x.update(schema=True)):
            changed = copy.deepcopy(report)
            change(changed)
            changed['report_digest'] = _digest({k:v for k,v in changed.items() if k!='report_digest'})
            path.write_bytes(_json(changed))
            self.assertEqual(read_control_validation(path)['state'],'UNAVAILABLE')

    def test_read_validates_completed_report_and_does_not_claim_to_inspect_capital_wallets(self):
        report = run_control_validation(self.root)
        path = self.root/report['report_id']/'report.json'
        # This is deliberately a report verifier. It does not silently label its
        # own arithmetic reproduction a persisted-wallet/account reconciliation.
        with patch('sqlite3.connect',side_effect=AssertionError('read opened wallet')):
            current = read_control_validation(path)
        self.assertEqual(current['state'],'PASSED')
        self.assertIn('READ_VALIDATES_REPORT_NOT_PERSISTED_WALLETS_OR_ACCOUNT_RECONCILIATION',current['limitations'])

    def test_bad_path_and_size_budget_return_unavailable_without_arbitrary_error_text(self):
        with patch('trader.capital_protocol_lab._root',side_effect=ValueError('PRIVATE_PATH_CONTENT')):
            current = read_control_validation(self.root/'report.json')
        self.assertEqual(current['state'],'UNAVAILABLE')
        self.assertNotIn('PRIVATE_PATH_CONTENT',json.dumps(current))
        report = run_control_validation(self.root)
        with patch('trader.control_validation.MAX_REPORT_BYTES',1):
            self.assertEqual(read_control_validation(self.root/report['report_id']/'report.json')['state'],'UNAVAILABLE')

    def test_cli_full_run_read_missing_and_corrupt_are_bounded_and_keep_authority_false(self):
        spec = importlib.util.spec_from_file_location('run_control_validation',
            Path(__file__).resolve().parents[1]/'scripts'/'run_control_validation.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = self.root/'cli-runs'
        with redirect_stdout(io.StringIO()) as out:
            code = module.main(['--output-dir',str(output)])
        self.assertEqual(code,0)
        value = json.loads(out.getvalue())
        self.assertEqual(value['state'],'PASSED')
        self.assertEqual((value['risk_scenarios'],value['risk_matches'],value['capital_scenarios']), (18,18,7))
        self.assertIs(value['controls_enabled'],False)
        path = output/value['report_id']/'report.json'
        before = path.read_bytes()
        unused = self.root/'must-not-be-created'
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(module.main(['--output-dir',str(unused),'--read-report',str(path)]),0)
        self.assertEqual(json.loads(out.getvalue())['state'],'PASSED')
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse(unused.exists())
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(module.main(['--read-report',str(unused/'report.json')]),0)
        self.assertEqual(json.loads(out.getvalue())['state'],'NOT_RUN')
        path.write_text('PRIVATE_CORRUPT_REPORT',encoding='utf-8')
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(module.main(['--read-report',str(path)]),1)
        self.assertEqual(json.loads(out.getvalue())['state'],'UNAVAILABLE')
        self.assertNotIn('PRIVATE_CORRUPT_REPORT',out.getvalue())


if __name__ == '__main__':
    unittest.main()
