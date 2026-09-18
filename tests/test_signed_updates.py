import base64
import hashlib
import io
import json
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.exceptions import InvalidSignature
from trader.update_manager import UpdateManager, canonical, verify, safe_name, release_id
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

    def test_stage_identifies_client_and_verifies_without_installing(self):
        manifest = json.loads(self.envelope.read_text())["manifest"]
        manifest["package_url"] = "https://portal.example/package.zip"
        envelope = json.dumps({"manifest": manifest, "signature": base64.b64encode(self.key.sign(canonical(manifest))).decode()}).encode()
        urls = []
        def opened(request, timeout):
            self.assertEqual(request.get_header("User-agent"), "CryptoAITraderUpdateManager/1")
            self.assertFalse(request.has_header("Authorization"))
            urls.append(request.full_url)
            return io.BytesIO(envelope if len(urls) == 1 else self.package.read_bytes())
        with patch("trader.update_manager.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = opened
            result = self.manager.stage("https://portal.example/latest")
        self.assertEqual(urls, ["https://portal.example/latest", manifest["package_url"]])
        self.assertEqual(result["status"], "staged_verified")
        self.assertEqual((self.root/"trader/__main__.py").read_text(), "OLD = True\n")
        self.assertFalse(self.manager.journal.exists())

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

    def approved_release(self):
        return release_id(json.loads(self.envelope.read_text())["manifest"])

    def test_changed_approval_does_not_modify_installation(self):
        with self.assertRaisesRegex(ValueError, "approved release changed"):
            self.manager.apply(self.package, self.envelope, expected_release="0"*64, defer_commit=True)
        self.assertEqual((self.root/"trader/__main__.py").read_text(), "OLD = True\n")
        self.assertFalse(self.manager.journal.exists())

    def test_supervised_commit_requires_health_and_exact_release(self):
        approved = self.approved_release()
        result = self.manager.apply(self.package, self.envelope, expected_release=approved, defer_commit=True)
        self.assertEqual(result["status"], "pending_health")
        self.assertFalse(self.manager.sequence.exists())
        with self.assertRaises(ValueError):
            self.manager.commit_pending("0"*64, lambda: True)
        with self.assertRaises(RuntimeError):
            self.manager.commit_pending(approved, lambda: False)
        self.assertFalse(self.manager.sequence.exists())
        # Commit must work while the candidate owns the engine lock.
        with single_instance(self.root/"data/engine.lock"):
            result = self.manager.commit_pending(approved, lambda: True)
        self.assertEqual(result["status"], "committed")
        self.assertEqual(json.loads(self.manager.sequence.read_text())["sequence"], 1)

    def test_crash_before_health_rolls_back_on_recovery(self):
        self.manager.apply(self.package, self.envelope, expected_release=self.approved_release(), defer_commit=True)
        with single_instance(self.root/"data/engine.lock"):
            with self.assertRaises(RuntimeError):
                self.manager.recover()
        self.assertTrue(UpdateManager(self.root, self.public).recover())
        self.assertEqual((self.root/"trader/__main__.py").read_text(), "OLD = True\n")
        self.assertFalse((self.root/"trader/new_module.py").exists())
        self.assertFalse(self.manager.sequence.exists())

    def test_mutation_before_health_cannot_commit(self):
        approved = self.approved_release()
        self.manager.apply(self.package, self.envelope, expected_release=approved, defer_commit=True)
        (self.root/"trader/new_module.py").write_text("UNEXPECTED = True\n")
        with self.assertRaisesRegex(ValueError, "installed file changed"):
            self.manager.commit_pending(approved, lambda: True)
        self.assertFalse(self.manager.sequence.exists())
        self.assertTrue(self.manager.recover())

    def test_other_installer_state_directory_cannot_bypass_transaction_lock(self):
        other = UpdateManager(self.root, self.public, self.root/"other-state")
        with single_instance(self.manager.transaction_lock):
            with self.assertRaises(RuntimeError):
                other.apply(self.package, self.envelope)

    def test_supervised_install_rejects_missing_approval(self):
        with self.assertRaises(ValueError):
            self.manager.apply(self.package, self.envelope, defer_commit=True)

    def test_failed_candidate_restores_database_schema_and_wal_content(self):
        database = self.root/'data/bot.db'
        # Keep the connection open so committed data remains in its WAL.
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE balance (amount INTEGER)')
        connection.execute('INSERT INTO balance VALUES (1000)')
        connection.commit()
        self.manager.apply(self.package, self.envelope, expected_release=self.approved_release(), defer_commit=True)
        connection.execute('UPDATE balance SET amount=1')
        connection.execute('CREATE TABLE candidate_only (value TEXT)')
        connection.commit()
        self.assertTrue(self.manager.recover())
        self.assertEqual(connection.execute('SELECT amount FROM balance').fetchone()[0], 1000)
        self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='candidate_only'").fetchone())

    def test_failed_candidate_removes_database_created_during_startup(self):
        self.manager.apply(self.package, self.envelope, expected_release=self.approved_release(), defer_commit=True)
        database = self.root/'data/bot.db'
        connection = sqlite3.connect(database)
        connection.execute('CREATE TABLE candidate_only (value TEXT)')
        connection.commit()
        connection.close()
        self.assertTrue(self.manager.recover())
        self.assertFalse(database.exists())

    def test_install_and_rollback_remove_stale_python_bytecode(self):
        cache = self.root/'trader/__pycache__'
        cache.mkdir()
        compiled = cache/'__main__.cpython-312.pyc'
        unrelated = cache/'untouched.cpython-312.pyc'
        compiled.write_bytes(b'old cached code')
        unrelated.write_bytes(b'unrelated')
        self.manager.apply(self.package, self.envelope, expected_release=self.approved_release(), defer_commit=True)
        self.assertFalse(compiled.exists())
        self.assertTrue(unrelated.exists())
        compiled.write_bytes(b'candidate cached code')
        self.manager.recover()
        self.assertFalse(compiled.exists())
        self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
