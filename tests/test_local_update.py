import base64
import hashlib
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts.local_update import run
from trader.update_manager import canonical, release_id


class LocalUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.agent = root / 'agent'
        self.source = root / 'paper'
        (self.agent / 'data/remote-updates').mkdir(parents=True)
        self.source.mkdir()
        (self.source / 'config.toml').write_text('[bot]\nmode="paper"\n', encoding='utf-8')
        (self.source / 'pyproject.toml').write_text('[project]\nversion="0.6.11"\n', encoding='utf-8')
        (self.agent / 'data/trusted-release.json').write_text(
            json.dumps({'supervised_install_enabled': True, 'manifest_url': 'https://example.invalid/latest'}))
        self.key = Ed25519PrivateKey.generate()
        (self.agent / 'data/trusted-update.pub').write_bytes(
            self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
        self.package = self.agent / 'data/remote-updates/staged.zip'
        self.envelope = self.agent / 'data/remote-updates/staged.zip.manifest.json'
        self.files = {'pyproject.toml': b'[project]\nversion="0.6.12"\n',
                      'trader/__main__.py': b'pass\n',
                      'trader/runtime_control.py': b'pass\n'}
        with zipfile.ZipFile(self.package, 'w') as archive:
            for name, content in self.files.items():
                archive.writestr(name, content)
        self.manifest = {'app': 'crypto-ai-trading-bot', 'mode': 'paper', 'version': '0.6.12',
                         'runtime_protocol': 1, 'sequence': 15, 'expires': time.time() + 3600,
                         'size': self.package.stat().st_size,
                         'sha256': hashlib.sha256(self.package.read_bytes()).hexdigest(),
                         'files': {name: hashlib.sha256(content).hexdigest()
                                   for name, content in self.files.items()}}
        self.envelope.write_text(json.dumps({'manifest': self.manifest,
            'signature': base64.b64encode(self.key.sign(canonical(self.manifest))).decode()}))

    def test_offline_check_verifies_signature_without_network_or_installation(self):
        with patch('trader.update_manager.urllib.request.build_opener') as network:
            result = run(self.source, 'check-offline', agent_root=self.agent)
        network.assert_not_called()
        self.assertEqual(result['release_id'], release_id(self.manifest))
        self.assertFalse(result['order_submission_enabled'])
        self.assertEqual((self.source/'pyproject.toml').read_text(), '[project]\nversion="0.6.11"\n')

    def test_exact_release_is_required_and_supervisor_is_the_only_installer(self):
        with patch('trader.update_supervisor.UpdateSupervisor') as supervisor:
            with self.assertRaisesRegex(ValueError, 'Exact signed release'):
                run(self.source, 'install', '0'*64, agent_root=self.agent)
            supervisor.assert_not_called()
            supervisor.return_value.install.return_value = {
                'status': 'installed_healthy', 'version': '0.6.12', 'release_id': release_id(self.manifest)}
            result = run(self.source, 'install', release_id(self.manifest), agent_root=self.agent)
            self.assertEqual(result['status'], 'installed_healthy')
            supervisor.return_value.install.assert_called_once()

    def test_tampering_paper_mode_and_missing_independent_supervisor_fail_closed(self):
        with self.assertRaises(ValueError):
            run(self.agent, 'check-offline', agent_root=self.agent)
        self.package.write_bytes(self.package.read_bytes() + b'tamper')
        with self.assertRaises(ValueError):
            run(self.source, 'check-offline', agent_root=self.agent)
        (self.source / 'config.toml').write_text('[bot]\nmode="live"\n')
        with self.assertRaises(ValueError):
            run(self.source, 'check-offline', agent_root=self.agent)


if __name__ == '__main__':
    unittest.main()
