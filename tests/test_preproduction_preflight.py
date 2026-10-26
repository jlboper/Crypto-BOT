import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.preproduction_preflight import technical_report
from trader.preproduction_status import SOURCE_REQUIREMENTS


class TechnicalEvidenceTests(unittest.TestCase):
    def fixture(self, root):
        names = {"trader/"+name for group in SOURCE_REQUIREMENTS.values() for name in group}
        names.update({'trader/engine.py', 'trader/preproduction_runtime.py', 'trader/live_authorization.py',
                      'tests/test_central_admission.py', 'tests/test_live_execution_runtime.py',
                      'tests/test_preproduction_runtime.py', 'tests/test_preproduction_status.py'})
        hashes = {}
        for name in names:
            path = root/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'# synthetic source\r\n')
            hashes[name] = hashlib.sha256(b'# synthetic source\n').hexdigest()
        (root/'pyproject.toml').write_text('[project]\nversion="0.10.54"\n')
        return {'passed': True, 'source_unchanged': True, 'external_network': 'blocked',
                'fixtures': 'synthetic', 'bot_started': False, 'failures': 0, 'errors': 0,
                'tests': 1300, 'source_hashes': hashes}

    def test_technical_evidence_never_commissions_live_or_creates_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); fixture = self.fixture(root)
            report = technical_report(fixture, source=root)
            self.assertEqual(report['packages'][-1]['state'], 'IMPLEMENTED_NOT_VALIDATED')
            self.assertNotIn('orders_enabled', report)
            self.assertFalse((root/'data').exists())

    def test_modified_or_omitted_source_withdraws_all_test_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); fixture = self.fixture(root)
            fixture['source_hashes'].pop('trader/central_admission.py')
            with self.assertRaisesRegex(ValueError, 'TESTED_SOURCE_CHANGED_OR_OMITTED'):
                technical_report(fixture, source=root)
            fixture = self.fixture(root)
            (root/'trader/central_admission.py').write_text('changed')
            with self.assertRaises(ValueError): technical_report(fixture, source=root)

    def test_failed_partial_changed_or_network_run_cannot_publish_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); fixture = self.fixture(root)
            for key, value in [('passed', False), ('tests', 5), ('source_unchanged', False),
                               ('external_network', 'allowed'), ('bot_started', True)]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    technical_report({**fixture, key: value}, source=root)
