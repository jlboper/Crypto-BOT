import base64
import hashlib
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.exceptions import InvalidSignature
from trader.update_manager import UpdateManager, canonical, verify, safe_name
from trader.runtime import single_instance


class SignedUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.public = self.root / "trusted.pub"
        self.public.write_bytes(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
        (self.root/"trader").mkdir()
        (self.root/"trader/__main__.py").write_text("OLD = True\n")
        (self.root/"pyproject.toml").write_text('[project]\nversion="0.6.2"\n')
        (self.root/"config.toml").write_text('[bot]\nmode="paper"\ndatabase_path="data/bot.db"\n')
        (self.root/".env.local").write_text("TEST_SENTINEL=preserve\n")
        self.package = self.root/"release.zip"
        self.envelope = self.root/"release.json"
        self.manager = UpdateManager(self.root, self.public)
        self.make_package()

    def make_package(self):
        self.files = {"trader/__main__.py": b"NEW = True\n", "trader/new_module.py": b"VALUE = 1\n", "pyproject.toml": b'[project]\nversion="0.6.3"\n'}
        with zipfile.ZipFile(self.package, "w") as archive:
            for name, payload in self.files.items():
                archive.writestr(name, payload)
        manifest = {"app": "crypto-ai-trading-bot", "mode": "paper", "version": "0.6.3", "sequence": 1,
            "expires": time.time()+3600, "size": self.package.stat().st_size,
            "sha256": hashlib.sha256(self.package.read_bytes()).hexdigest(),
            "files": {name: hashlib.sha256(payload).hexdigest() for name,payload in self.files.items()}}
        self.envelope.write_text(json.dumps({"manifest": manifest, "signature": base64.b64encode(self.key.sign(canonical(manifest))).decode()}))

    def test_valid_install_preserves_config_and_secrets_rejects_replay(self):
        result = self.manager.apply(self.package, self.envelope)
        self.assertEqual(result["status"], "installed_offline")
        self.assertEqual((self.root/".env.local").read_text(), "TEST_SENTINEL=preserve\n")
        self.assertIn('mode="paper"', (self.root/"config.toml").read_text())
        with self.assertRaises(ValueError):
            self.manager.apply(self.package, self.envelope)

    def test_health_failure_restores_and_removes_new_files(self):
        with self.assertRaises(RuntimeError):
            self.manager.apply(self.package, self.envelope, health_check=lambda: False)
        self.assertEqual((self.root/"trader/__main__.py").read_text(), "OLD = True\n")
        self.assertFalse((self.root/"trader/new_module.py").exists())
        self.assertEqual(json.loads(self.manager.journal.read_text())["phase"], "rolled_back")

    def test_tampering_and_traversal_fail(self):
        data = json.loads(self.envelope.read_text())
        data["manifest"]["version"] = "9.0.0"
        self.envelope.write_text(json.dumps(data))
        with self.assertRaises(InvalidSignature):
            verify(self.package, self.envelope, self.public)
        for name in ("../x", "trader/../../x", "trader/CON.py", "trader/a:stream", ".env.local", "config.toml", "trader/.env", "trader/a."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_name(name)

    def test_running_engine_prevents_install(self):
        with single_instance(self.root/"data/engine.lock"):
            with self.assertRaises(RuntimeError):
                self.manager.apply(self.package, self.envelope)

    def test_recovery_after_interrupted_commit(self):
        self.manager.apply(self.package, self.envelope)
        record = json.loads(self.manager.journal.read_text())
        record["phase"] = "applying"
        self.manager.journal.write_text(json.dumps(record))
        self.manager.sequence.unlink()
        self.assertTrue(UpdateManager(self.root, self.public).recover())
        self.assertEqual((self.root/"trader/__main__.py").read_text(), "OLD = True\n")
        self.assertFalse((self.root/"trader/new_module.py").exists())

    def test_expired_signature_and_changed_package_fail(self):
        with self.assertRaises(ValueError):
            verify(self.package, self.envelope, self.public, now=time.time()+4000)
        self.package.write_bytes(self.package.read_bytes()+b"tampered")
        with self.assertRaises(ValueError):
            verify(self.package, self.envelope, self.public)


if __name__ == "__main__":
    unittest.main()
