import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.refresh_independent_agent import MODULES, refresh


class AgentRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.agent = root / "paper", root / "agent"
        self.source.mkdir()
        self.agent.mkdir()
        (self.source / "config.toml").write_text('[bot]\nmode="paper"\n')
        (self.source / "pyproject.toml").write_text('[project]\nversion="0.6.16"\n')
        files = {}
        for name in MODULES:
            origin, target = self.source / name, self.agent / name
            origin.parent.mkdir(parents=True, exist_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            origin.write_bytes(b"signed " + name.encode())
            target.write_bytes(b"old " + name.encode())
            files[name] = hashlib.sha256(origin.read_bytes()).hexdigest()
        state = self.agent / "data/remote-updates"
        state.mkdir(parents=True)
        (self.agent / "data/trusted-update.pub").write_text("trusted")
        (state / "journal.json").write_text(json.dumps({"phase": "committed", "version": "0.6.16",
            "sequence": 17, "release_id": "a" * 64, "files": files}))
        (state / "sequence.json").write_text(json.dumps({"sequence": 17}))

    def test_preview_and_bounded_refresh_preserve_backup(self):
        before = refresh(self.source, self.agent)
        self.assertEqual(before["changes"], list(MODULES))
        with self.assertRaisesRegex(ValueError, "stop marker"):
            refresh(self.source, self.agent, apply=True)
        (self.agent / "data/REMOTE_STOP").write_text("stopped")
        result = refresh(self.source, self.agent, apply=True)
        self.assertEqual(result["status"], "refreshed")
        for name in MODULES:
            self.assertEqual((self.agent / name).read_bytes(), (self.source / name).read_bytes())
            self.assertTrue((Path(result["backup"]) / name).read_bytes().startswith(b"old "))
        self.assertEqual(refresh(self.source, self.agent, apply=True)["status"], "already_current")

    def test_testnet_mode_can_refresh_signed_supervisor_modules(self):
        (self.source / "config.toml").write_text('[bot]\nmode="testnet"\n')
        before = refresh(self.source, self.agent)
        self.assertEqual(before["changes"], list(MODULES))
        self.assertIn("trader/update_supervisor.py", MODULES)
        self.assertIn("trader/update_manager.py", MODULES)
        self.assertIn("scripts/remote_job.py", MODULES)

    def test_new_signed_module_is_added_without_requiring_an_old_copy(self):
        (self.agent / MODULES[-1]).unlink()
        (self.agent / 'data/REMOTE_STOP').write_text('stopped')
        result = refresh(self.source, self.agent, apply=True)
        self.assertEqual((self.agent / MODULES[-1]).read_bytes(), (self.source / MODULES[-1]).read_bytes())
        self.assertFalse((Path(result['backup']) / MODULES[-1]).exists())

    def test_changed_source_or_uncommitted_install_is_rejected(self):
        (self.source / MODULES[0]).write_text("tampered")
        with self.assertRaisesRegex(ValueError, "signed code"):
            refresh(self.source, self.agent)
        (self.source / MODULES[0]).write_bytes(b"signed " + MODULES[0].encode())
        journal = self.agent / "data/remote-updates/journal.json"
        record = json.loads(journal.read_text())
        record["phase"] = "pending_health"
        journal.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "not committed"):
            refresh(self.source, self.agent)

    def test_second_copy_failure_restores_first_module(self):
        (self.agent / "data/REMOTE_STOP").write_text("stopped")
        old = (self.agent / MODULES[0]).read_bytes()
        original_copy = __import__("shutil").copyfile
        def fail_second(source, destination, **kwargs):
            if Path(source).name == Path(MODULES[1]).name:
                raise OSError("copy failed")
            return original_copy(source, destination, **kwargs)
        with patch("scripts.refresh_independent_agent.shutil.copyfile", side_effect=fail_second):
            with self.assertRaises(OSError):
                refresh(self.source, self.agent, apply=True)
        self.assertEqual((self.agent / MODULES[0]).read_bytes(), old)
