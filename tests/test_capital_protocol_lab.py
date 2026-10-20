"""Closed Capital Protocol Lab tests. Temporary synthetic wallets only."""
import ast
import copy
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trader import capital_protocol_lab as lab


def hashes(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob('*') if path.is_file()}


class CapitalProtocolLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'new-lab'

    def run_lab(self):
        return lab.run_capital_protocol_lab(self.root)

    def rewrite(self, report):
        report['report_digest'] = lab._digest({k: v for k, v in report.items() if k != 'report_digest'})
        raw = lab._json(report)
        (self.root/report['report_id']/'report.json').write_bytes(raw)
        (self.root/'latest.json').write_bytes(lab._json({'schema': 1, 'report_id': report['report_id'],
            'file_sha256': hashlib.sha256(raw).hexdigest()}))

    def test_seven_real_protocol_recipes_pass_with_exact_results_and_audit_ids(self):
        report = self.run_lab()
        self.assertEqual(report['state'], 'PASSED')
        self.assertEqual(len(report['scenarios']), 7)
        self.assertEqual([row['id'] for row in report['scenarios']], [row[0] for row in lab.RECIPES])
        self.assertLessEqual(len(lab._json(report)), 8000)
        self.assertEqual(report['mode'], 'RESEARCH_ONLY')
        self.assertIs(report['synthetic'], True)
        self.assertIs(report['execution_enabled'], False)
        self.assertIs(report['real_account_adapter'], False)
        self.assertIs(type(report['autonomy_level']), int)
        self.assertEqual(report['autonomy_level'], 0)
        for row in report['scenarios']:
            self.assertEqual(row['state'], 'PASSED', row['id'])
            self.assertEqual(row['scope'], {'scenario_environment':'SHADOW',
                'simulated_account_id':row['id'], 'currency':'USDT'})
            self.assertTrue(row['matches'])
            self.assertTrue(row['conservation_matches'])
            self.assertTrue(lab._conserved(row['book']))
            self.assertRegex(row['record_id'], r'^SIM_')
            self.assertRegex(row['record_digest'], r'^[a-f0-9]{64}$')
            self.assertTrue(all(type(value) is int for value in row['book'].values()))
        self.assertEqual(lab.capital_protocol_lab_snapshot(self.root), report)

    def test_no_run_projection_creates_no_directory_wallet_or_pointer(self):
        with patch.object(lab.protocol.CapitalManagerShadow, 'initialize', side_effect=AssertionError('reader initialized wallet')):
            result = lab.capital_protocol_lab_snapshot(self.root)
        self.assertEqual(result['state'], 'NOT_RUN')
        self.assertIsNone(result['report_id'])
        self.assertIsNone(result['policy'])
        self.assertEqual(result['scenarios'], [])
        self.assertFalse(self.root.exists())

    def test_second_run_uses_only_new_wallets_and_preserves_previous_run_and_other_files(self):
        first = self.run_lab()
        old = self.root/first['report_id']
        before = hashes(old)
        sentinel = self.root/'unrelated-existing.db'
        sentinel.write_bytes(b'financial sentinel never opened')
        second = self.run_lab()
        self.assertNotEqual(second['report_id'], first['report_id'])
        self.assertEqual(hashes(old), before)
        self.assertEqual(sentinel.read_bytes(), b'financial sentinel never opened')
        self.assertEqual(len(list((self.root/second['report_id']).glob('*.simulation.sqlite3'))), 7)
        self.assertEqual(lab.capital_protocol_lab_snapshot(self.root), second)

    def test_projection_is_json_read_only_and_never_opens_any_sqlite_wallet(self):
        expected = self.run_lab()
        before = hashes(self.root)
        with patch.object(lab.sqlite3, 'connect', side_effect=AssertionError('projection opened database')):
            self.assertEqual(lab.capital_protocol_lab_snapshot(self.root), expected)
        self.assertEqual(hashes(self.root), before)

    def test_changed_json_without_matching_digests_is_unavailable_not_zero_or_passed(self):
        report = self.run_lab()
        path = self.root/report['report_id']/'report.json'
        path.write_bytes(path.read_bytes().replace(b'RESEARCH_ONLY', b'RESEARCH_EVIL'))
        result = lab.capital_protocol_lab_snapshot(self.root)
        self.assertEqual(result['state'], 'UNAVAILABLE')
        self.assertEqual(result['scenarios'], [])
        self.assertIsNone(result['policy'])

    def test_rehashed_authority_policy_source_and_schema_mutations_are_rejected(self):
        original = self.run_lab()
        mutations = (
            lambda r: r.update(mode='LIVE'), lambda r: r.update(execution_enabled=True),
            lambda r: r.update(real_account_adapter=True), lambda r: r.update(synthetic=False),
            lambda r: r.update(autonomy_level=False), lambda r: r.update(autonomy_level=1),
            lambda r: r.update(controls_enabled=False), lambda r: r.update(api_key='sk-synthetic'),
            lambda r: r['policy'].update(initial_balance_units=2000*lab.U),
            lambda r: r['policy'].update(approved_actor='OWNER'),
            lambda r: r['source_version'].update(recipe_sha256='0'*64),
            lambda r: r['source_version'].update(secret='private'),
            lambda r: r.update(at='yesterday'), lambda r: r.update(at='2026-10-18T00:00:00'),
        )
        for mutate in mutations:
            report = copy.deepcopy(original); mutate(report); self.rewrite(report)
            with self.subTest(mutation=mutate):
                self.assertEqual(lab.capital_protocol_lab_snapshot(self.root)['state'], 'UNAVAILABLE')

    def test_rehashed_invented_checks_and_financial_results_cannot_claim_pass(self):
        original = self.run_lab()
        def change_conserved_book(report):
            report['scenarios'][0]['book'].update(book_equity_units=999*lab.U,
                fees_paid_units=lab.U, free_units_signed=795*lab.U, available_units=795*lab.U)
        mutations = (
            lambda r: r['scenarios'].pop(), lambda r: r['scenarios'].append(r['scenarios'][0]),
            lambda r: r['scenarios'][0].update(id='SIM_INVENTED_RECIPE'),
            lambda r: r['scenarios'][0]['scope'].update(simulated_account_id='REAL_ACCOUNT'),
            lambda r: r['scenarios'][0]['scope'].update(scenario_environment='LIVE'),
            lambda r: r['scenarios'][0]['scope'].update(currency='USDC'),
            lambda r: r['scenarios'][0].update(checks=[]),
            lambda r: r['scenarios'][0]['checks'][0].update(code='INVENTED_CHECK'),
            lambda r: r['scenarios'][0]['checks'][0].update(expected=0, actual=0),
            lambda r: r['scenarios'][0]['book'].update(reserved_units=True),
            lambda r: r['scenarios'][0]['book'].update(reserved_units=0),
            lambda r: r['scenarios'][0].update(record_id='REAL_ORDER_1'),
            lambda r: r['scenarios'][0].update(record_digest='bad'),
            change_conserved_book,
        )
        for mutate in mutations:
            report = copy.deepcopy(original); mutate(report); self.rewrite(report)
            with self.subTest(mutation=mutate):
                self.assertEqual(lab.capital_protocol_lab_snapshot(self.root)['state'], 'UNAVAILABLE')

    def test_missing_truncated_or_oversized_report_and_unsafe_pointer_stay_unknown(self):
        report = self.run_lab()
        pointer_path = self.root/'latest.json'
        original_pointer = pointer_path.read_bytes()
        for pointer in ({'schema':1,'report_id':'../../financial.db','file_sha256':'a'*64},
                        {'schema':True,'report_id':report['report_id'],'file_sha256':'a'*64},
                        {'schema':1,'report_id':report['report_id'],'file_sha256':'a'*64,'path':'private'}):
            pointer_path.write_bytes(lab._json(pointer))
            self.assertEqual(lab.capital_protocol_lab_snapshot(self.root)['state'], 'UNAVAILABLE')
        pointer_path.write_bytes(b'x'*513)
        self.assertEqual(lab.capital_protocol_lab_snapshot(self.root)['state'], 'UNAVAILABLE')
        pointer_path.write_bytes(original_pointer)
        path = self.root/report['report_id']/'report.json'
        path.write_bytes(b'x'*8001)
        self.assertEqual(lab.capital_protocol_lab_snapshot(self.root)['state'], 'UNAVAILABLE')
        path.unlink()
        self.assertEqual(lab.capital_protocol_lab_snapshot(self.root)['state'], 'UNAVAILABLE')

    def test_protocol_error_produces_honest_failed_report_without_private_error_body(self):
        with patch.object(lab.protocol.CapitalManagerShadow, 'reserve', side_effect=RuntimeError('private-token-body')):
            report = self.run_lab()
        self.assertEqual(report['state'], 'FAILED')
        self.assertTrue(all(row['state'] == 'FAILED' for row in report['scenarios']))
        self.assertNotIn('private-token', lab._json(report).decode())
        self.assertTrue(all(row['book'] is None for row in report['scenarios']))
        for row in report['scenarios']:
            self.assertEqual(len(row['checks']), len(lab.CHECKS[row['id']]))
            self.assertTrue(all(check['actual']=='NOT_EVALUATED' and check['matches'] is False
                                for check in row['checks']))
        self.assertEqual(lab.capital_protocol_lab_snapshot(self.root), report)

    def test_rehashed_failed_reports_reject_append_omit_reorder_and_unknown_checks(self):
        original = self.run_lab()
        def append(row):
            row['checks'].append({'unexpected_field':'synthetic-private-metadata'})
        def omit(row):
            row['checks'].pop()
        def reorder(row):
            row['checks'].reverse()
        def unknown(row):
            row['checks'][0]['unexpected_field'] = 'synthetic-private-metadata'
        for mutate in (append, omit, reorder, unknown):
            report = copy.deepcopy(original)
            report['state'] = 'FAILED'
            row = report['scenarios'][0]
            row['state'] = 'FAILED'; row['matches'] = False
            mutate(row)
            self.rewrite(report)  # Recompute both digests; validate semantics too.
            with self.subTest(mutation=mutate.__name__):
                actual = lab.capital_protocol_lab_snapshot(self.root)
                self.assertEqual(actual['state'], 'UNAVAILABLE')
                self.assertEqual(actual['scenarios'], [])
                self.assertNotIn('synthetic-private', lab._json(actual).decode())

    def test_valid_json_of_wrong_top_type_and_malformed_pointer_never_escape_reader(self):
        report = self.run_lab()
        pointer_path = self.root/'latest.json'
        path = self.root/report['report_id']/'report.json'
        original = pointer_path.read_bytes()
        for value in ([], None, 'UNKNOWN', True, 42):
            raw = lab._json(value)
            path.write_bytes(raw)
            pointer_path.write_bytes(lab._json({'schema':1,'report_id':report['report_id'],
                'file_sha256':hashlib.sha256(raw).hexdigest()}))
            self.assertEqual(lab.capital_protocol_lab_snapshot(self.root)['state'], 'UNAVAILABLE')
        for raw in (b'[]', b'null', b'"private"', b'{broken'):
            pointer_path.write_bytes(raw)
            result = lab.capital_protocol_lab_snapshot(self.root)
            self.assertEqual(result['state'], 'UNAVAILABLE')
            self.assertNotIn('private', lab._json(result).decode())
        pointer_path.write_bytes(original)

    def test_negative_shortfall_partial_cancel_and_concurrency_are_not_optimistic(self):
        rows = {row['id']: row for row in self.run_lab()['scenarios']}
        self.assertEqual(rows['SIM_LOSS_SHORTFALL']['book']['book_equity_units'], -204*lab.U)
        self.assertEqual(rows['SIM_LOSS_SHORTFALL']['book']['available_units'], 0)
        self.assertEqual(rows['SIM_LOSS_SHORTFALL']['book']['shortfall_units'], 204*lab.U)
        self.assertEqual(rows['SIM_PARTIAL_CANCEL']['book']['committed_units'], 40*lab.U)
        self.assertEqual(rows['SIM_PARTIAL_CANCEL']['book']['reserved_units'], 1600000)
        self.assertEqual(rows['SIM_CONCURRENT_BUDGET']['checks'][0]['actual'], 1)
        self.assertEqual(rows['SIM_RESTART_UNKNOWN_TTL']['actual_state'], 'UNKNOWN')

    def test_import_closure_contains_no_credentials_broker_engine_or_provider(self):
        tree = ast.parse(Path(lab.__file__).read_text(encoding='utf-8'))
        names = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        names += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        self.assertFalse(any(any(word in name for word in ('trader','openai','urllib','requests','socket','broker')) for name in names))
        self.assertTrue(any(isinstance(node, ast.ImportFrom) and node.level == 1
                            and node.module is None and [alias.name for alias in node.names] == ['capital_manager_shadow']
                            for node in ast.walk(tree)))

    def load_cli(self):
        path=Path(__file__).resolve().parent.parent/'scripts'/'run_capital_protocol_lab.py'
        spec=importlib.util.spec_from_file_location('capital_lab_cli_test',path)
        module=importlib.util.module_from_spec(spec)
        with patch.object(lab,'run_capital_protocol_lab',side_effect=AssertionError('CLI import ran scenario')):
            spec.loader.exec_module(module)
        return module

    def test_cli_import_and_read_only_default_never_initialize_a_wallet_or_create_directory(self):
        cli=self.load_cli()
        cli.ROOT=self.root/'synthetic-install'
        output=io.StringIO()
        with (patch.object(lab.sqlite3,'connect',side_effect=AssertionError('reader opened SQLite')),
              redirect_stdout(output)):
            result=cli.main(['--read-only'])
        self.assertEqual(result,0)
        self.assertEqual(json.loads(output.getvalue())['state'],'NOT_RUN')
        self.assertFalse(cli.ROOT.exists())

    def test_cli_creates_only_explicit_new_synthetic_run_and_then_reads_same_json(self):
        cli=self.load_cli()
        output=io.StringIO()
        with redirect_stdout(output):
            code=cli.main(['--output-dir',str(self.root)])
        report=json.loads(output.getvalue())
        self.assertEqual(code,0)
        self.assertEqual(report['state'],'PASSED')
        self.assertEqual(len(list((self.root/report['report_id']).glob('*.simulation.sqlite3'))),7)
        before=hashes(self.root)
        output=io.StringIO()
        with (patch.object(lab.sqlite3,'connect',side_effect=AssertionError('reader opened SQLite')),
              redirect_stdout(output)):
            code=cli.main(['--output-dir',str(self.root),'--read-only'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(output.getvalue()),report)
        self.assertEqual(hashes(self.root),before)

    def test_new_lab_sources_and_cli_are_accepted_by_existing_package_allowlist(self):
        from trader.update_manager import safe_name
        for path in ('trader/capital_manager_shadow.py','trader/capital_protocol_lab.py',
                     'scripts/run_capital_protocol_lab.py'):
            self.assertEqual(str(safe_name(path)),path)


if __name__ == '__main__':
    unittest.main()
