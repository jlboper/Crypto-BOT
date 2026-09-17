import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from trader.runtime_control import RuntimeControl
from trader.update_manager import UpdateManager, atomic_json, canonical, release_id
from trader.update_supervisor import ProcessRuntime, UpdateSupervisor

SOURCE = Path(__file__).resolve().parent.parent


class FixtureRuntime(ProcessRuntime):
    def health(self, child, token):
        # The synthetic engine never opens sockets; production HTTP is tested separately.
        return child.poll() is None

    def __init__(self, root):
        super().__init__(root)
        self.children = []
        self.behavior = 'normal'

    def start(self, token=None):
        env = dict(os.environ)
        env.pop('CRYPTO_UPDATE_TOKEN', None)
        if token:
            env['CRYPTO_UPDATE_TOKEN'] = token
        log_path = self.root/f'fixture-{len(self.children)}.log'
        with log_path.open('w') as log:
            child = subprocess.Popen([sys.executable, str(SOURCE/'tests/fixtures/runtime_child.py'),
                                  str(SOURCE), str(self.root), self.behavior], env=env,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.children.append(child)
        return child

    def close(self):
        for child in self.children:
            self.stop_owned(child)
        for path in self.root.glob('fixture-*.log'):
            content = path.read_text()
            if content and 'PermissionError' in content:
                print(content)


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'trader').mkdir()
        (self.root/'data').mkdir()
        (self.root/'trader/runtime_control.py').write_text('# original protocol fixture\n')
        (self.root/'trader/__main__.py').write_text('# original fixture\n')
        (self.root/'pyproject.toml').write_text('[project]\nversion="0.6.2"\n')
        (self.root/'config.toml').write_text('[bot]\nmode="paper"\ndatabase_path="data/bot.db"\n')
        with closing(sqlite3.connect(self.root/'data/bot.db')) as connection:
            connection.execute('CREATE TABLE balance (amount INTEGER)')
            connection.execute('INSERT INTO balance VALUES (1000)')
            connection.commit()
        key = Ed25519PrivateKey.generate()
        public = self.root/'trusted.pub'
        public.write_bytes(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
        self.package = self.root/'package.zip'
        self.envelope = self.root/'manifest.json'
        files = {'trader/__main__.py': b'# candidate fixture\n',
                 'trader/runtime_control.py': b'# candidate protocol fixture\n',
                 'pyproject.toml': b'[project]\nversion="0.6.3"\n'}
        with zipfile.ZipFile(self.package, 'w') as archive:
            for name, payload in files.items():
                archive.writestr(name, payload)
        manifest = {'app': 'crypto-ai-trading-bot', 'mode': 'paper', 'version': '0.6.3',
                    'runtime_protocol': 1, 'sequence': 1, 'expires': time.time()+3600,
                    'size': self.package.stat().st_size, 'sha256': hashlib.sha256(self.package.read_bytes()).hexdigest(),
                    'files': {name: hashlib.sha256(payload).hexdigest() for name, payload in files.items()}}
        atomic_json(self.envelope, {'manifest': manifest, 'signature': base64.b64encode(key.sign(canonical(manifest))).decode()})
        self.approved = release_id(manifest)
        self.manager = UpdateManager(self.root, public)
        self.runtime = FixtureRuntime(self.root)
        self.addCleanup(self.runtime.close)
        self.supervisor = UpdateSupervisor(self.manager, self.runtime, timeout=3)
        original = self.runtime.start()
        self.supervisor.wait_ready(original, None, '0.6.2', 'running')
        self.original = original

    def assert_restored(self):
        self.assertEqual((self.root/'trader/__main__.py').read_text(), '# original fixture\n')
        with closing(sqlite3.connect(self.root/'data/bot.db')) as connection:
            self.assertEqual(connection.execute('SELECT amount FROM balance').fetchone()[0], 1000)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='candidate_schema'").fetchone())
        self.assertEqual(json.loads(self.supervisor.control.status.read_text())['version'], '0.6.2')

    def test_success_commits_before_candidate_can_execute_cycle(self):
        result = self.supervisor.install(self.package, self.envelope, self.approved, job_id=41)
        self.assertEqual(result['status'], 'installed_healthy')
        self.assertEqual(json.loads(self.supervisor.record.read_text())['job_id'], 41)
        self.assertIsNotNone(self.original.poll())
        deadline = time.monotonic()+3
        while not (self.root/'candidate-cycle').exists() and time.monotonic()<deadline:
            time.sleep(0.02)
        self.assertTrue((self.root/'candidate-cycle').exists())
        self.assertFalse((self.root/'UNSAFE_CYCLE').exists())
        self.assertFalse(self.supervisor.control.maintenance.exists())

    def test_failed_start_restores_database_code_and_previous_engine(self):
        self.runtime.behavior = 'exit'
        with self.assertRaisesRegex(RuntimeError, 'exited'):
            self.supervisor.install(self.package, self.envelope, self.approved)
        self.assert_restored()
        self.assertEqual(json.loads(self.supervisor.record.read_text())['phase'], 'rolled_back')

    def test_wrong_candidate_handshake_cannot_commit(self):
        self.runtime.behavior = 'wrong-token'
        with self.assertRaises(TimeoutError):
            self.supervisor.install(self.package, self.envelope, self.approved)
        self.assert_restored()
        self.assertFalse(self.manager.sequence.exists())

    def test_wrong_approval_does_not_stop_existing_process(self):
        with self.assertRaises(ValueError):
            self.supervisor.install(self.package, self.envelope, '0'*64)
        self.assertIsNone(self.original.poll())
        self.assertFalse(self.supervisor.control.maintenance.exists())

    def test_legacy_runtime_is_not_stopped(self):
        (self.root/'trader/runtime_control.py').unlink()
        with self.assertRaisesRegex(RuntimeError, 'bootstrap'):
            self.supervisor.install(self.package, self.envelope, self.approved)
        self.assertIsNone(self.original.poll())

    def test_recovery_of_interrupted_pending_candidate_restores_previous(self):
        token = 'a'*64
        state = {'token': token, 'release_id': self.approved, 'old_version': '0.6.2', 'version': '0.6.3', 'phase': 'stopping'}
        atomic_json(self.supervisor.record, state)
        self.supervisor.phase(token, 'stopping')
        self.supervisor.wait_stopped()
        self.manager.apply(self.package, self.envelope, expected_release=self.approved, defer_commit=True)
        self.supervisor.phase(token, 'candidate')
        child = self.runtime.start(token)
        self.supervisor.wait_ready(child, token, '0.6.3', 'candidate')
        result = UpdateSupervisor(self.manager, self.runtime, timeout=3).recover()
        self.assertEqual(result['status'], 'rolled_back')
        self.assert_restored()

    def test_recovery_after_commit_preserves_new_database(self):
        token = 'b'*64
        atomic_json(self.supervisor.record, {'token': token, 'release_id': self.approved,
                    'old_version': '0.6.2', 'version': '0.6.3', 'phase': 'stopping'})
        self.supervisor.phase(token, 'stopping')
        self.supervisor.wait_stopped()
        self.manager.apply(self.package, self.envelope, expected_release=self.approved, defer_commit=True)
        self.supervisor.phase(token, 'candidate')
        child = self.runtime.start(token)
        self.supervisor.wait_ready(child, token, '0.6.3', 'candidate')
        self.manager.commit_pending(self.approved, lambda: True)
        result = self.supervisor.recover()
        self.assertEqual(result['status'], 'completed')
        with closing(sqlite3.connect(self.root/'data/bot.db')) as connection:
            self.assertEqual(connection.execute('SELECT amount FROM balance').fetchone()[0], 123)


class RuntimeGateTests(unittest.TestCase):
    def test_agent_reconciles_completed_job_without_restarting(self):
        from scripts.windows_agent import recover_updates
        from trader.remote_jobs import RemoteJobs
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'target'
            (root/'data/remote-updates').mkdir(parents=True)
            atomic_json(root/'data/trusted-release.json', {'supervised_install_enabled': True})
            atomic_json(root/'data/remote-updates/supervisor.json', {'phase': 'completed', 'job_id': 5})
            with patch('trader.remote_jobs.subprocess.Popen'), patch('scripts.windows_agent.ROOT', root), patch('trader.update_supervisor.UpdateSupervisor') as supervisor:
                jobs = RemoteJobs(root, source)
                jobs.accept({'id': 5, 'action': 'update_install', 'release_id': 'a'*64, 'expires': time.time()+100})
                recover_updates(source)
                self.assertEqual(jobs.results()[0]['status'], 'completed')
                supervisor.assert_not_called()

    def test_agent_does_not_recover_without_explicit_local_enable(self):
        from scripts.windows_agent import recover_updates
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'data/remote-updates').mkdir(parents=True)
            atomic_json(root/'data/trusted-release.json', {'supervised_install_enabled': 'true'})
            atomic_json(root/'data/remote-updates/supervisor.json', {'phase': 'stopping'})
            with patch('scripts.windows_agent.ROOT', root), patch('trader.update_supervisor.UpdateSupervisor') as supervisor:
                recover_updates(root/'target')
                supervisor.assert_not_called()

    def test_maintenance_blocks_normal_start_and_requires_exact_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            control = RuntimeControl(Path(directory))
            control.guard_start()
            atomic_json(control.maintenance, {'token': 'a'*64, 'phase': 'candidate'})
            with self.assertRaises(RuntimeError):
                control.guard_start()
            with self.assertRaises(RuntimeError):
                RuntimeControl(Path(directory), 'b'*64).guard_start()
            RuntimeControl(Path(directory), 'a'*64).guard_start()

    def test_candidate_cannot_proceed_without_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            control = RuntimeControl(Path(directory), 'a'*64)
            atomic_json(control.maintenance, {'token': 'a'*64, 'phase': 'candidate'})
            with self.assertRaises(TimeoutError):
                control.await_activation(timeout=0)
            atomic_json(control.maintenance, {'token': 'a'*64, 'phase': 'cancelled'})
            with self.assertRaises(RuntimeError):
                control.await_activation()
