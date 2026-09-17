"""Supervised PAPER activation. Run from the stable agent, outside the target.

Never kills a discovered PID: only a child created by this supervisor may be
terminated. An existing engine must implement the cooperative maintenance gate.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import tomllib
import urllib.request

from .runtime import single_instance
from .runtime_control import RuntimeControl
from .update_manager import atomic_json, release_id, verify


class ProcessRuntime:
    def __init__(self, root, python=None):
        self.root = root
        self.python = python or sys.executable

    def start(self, token=None):
        environment = dict(os.environ)
        environment.pop("CRYPTO_UPDATE_TOKEN", None)
        if token is not None:
            environment["CRYPTO_UPDATE_TOKEN"] = token
        return subprocess.Popen(
            [self.python, "-m", "trader", "--config", str(self.root/'config.toml'), "run"],
            cwd=self.root, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    @staticmethod
    def stop_owned(child):
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=20)

    def health(self, child, token):
        from .remote_agent import NoRedirect
        config = tomllib.loads((self.root/'config.toml').read_text())
        dashboard = config.get('dashboard', {})
        host, port = dashboard.get('host'), dashboard.get('port')
        if host not in {'127.0.0.1', 'localhost', '::1'} or type(port) is not int or not 1 <= port <= 65535:
            return False
        address = '[::1]' if host == '::1' else '127.0.0.1'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(f'http://{address}:{port}/health/runtime', timeout=2) as response:
                payload = json.loads(response.read(4097))
            return payload == {'pid': child.pid, 'token': token, 'mode': 'paper'} and child.poll() is None
        except (OSError, ValueError):
            return False


class UpdateSupervisor:
    def __init__(self, manager, runtime=None, timeout=120):
        self.manager = manager
        self.runtime = runtime or ProcessRuntime(manager.root)
        self.control = RuntimeControl(manager.database_path().parent)
        self.record = manager.state/'supervisor.json'
        self.lock = manager.root/'data/update-supervisor.lock'
        self.timeout = timeout

    def wait_stopped(self):
        deadline = time.monotonic()+self.timeout
        while True:
            try:
                with self.manager.locks():
                    return
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Engine or another writer did not stop cooperatively")
                time.sleep(0.1)

    def ready(self, child, token, version, phase):
        if child.poll() is not None:
            return False
        try:
            status = json.loads(self.control.status.read_text())
        except (OSError, ValueError):
            return False
        return (status.get('pid') == child.pid and status.get('token') == token
                and status.get('version') == version and status.get('phase') == phase
                and status.get('mode') == 'paper' and status.get('protocol') == 1
                and status.get('dashboard_ready') is True and self.runtime.health(child, token))

    def wait_ready(self, child, token, version, phase):
        deadline = time.monotonic()+self.timeout
        while not self.ready(child, token, version, phase):
            if child.poll() is not None:
                raise RuntimeError("Owned engine exited before readiness")
            if time.monotonic() >= deadline:
                raise TimeoutError("Engine readiness deadline exceeded")
            time.sleep(0.1)

    def phase(self, token, phase):
        atomic_json(self.control.maintenance, {'token': token, 'phase': phase})

    def restart_previous(self, version):
        self.control.maintenance.unlink(missing_ok=True)
        child = None
        try:
            child = self.runtime.start()
            self.wait_ready(child, None, version, 'running')
        except BaseException:
            self.phase(secrets.token_hex(32), 'recovery_failed')
            self.runtime.stop_owned(child)
            raise

    def install(self, package, envelope, approved, *, job_id=None):
        if job_id is not None and (type(job_id) is not int or job_id <= 0):
            raise ValueError("Invalid update job identifier")
        with single_instance(self.lock):
            if self.control.maintenance.exists():
                raise RuntimeError("Recover previous maintenance before installing")
            minimum = json.loads(self.manager.sequence.read_text())['sequence'] if self.manager.sequence.exists() else 0
            manifest = verify(package, envelope, self.manager.public_key, minimum)
            if release_id(manifest) != approved:
                raise ValueError("Approved release changed")
            if manifest.get('runtime_protocol') != 1 or 'trader/runtime_control.py' not in manifest['files']:
                raise ValueError("Candidate lacks supervised runtime protocol")
            if not (self.manager.root/'trader/runtime_control.py').is_file():
                raise RuntimeError("Existing installation requires one-time supervised bootstrap")
            original = json.loads(self.control.status.read_text())
            if original.get('protocol') != 1 or original.get('phase') != 'running' or original.get('mode') != 'paper':
                raise RuntimeError("Existing engine has no cooperative runtime status")
            # Do not turn a stopped installation into an active trading process.
            try:
                with single_instance(self.control.directory/'engine.lock'):
                    pass
            except RuntimeError:
                pass
            else:
                raise RuntimeError("Existing engine is stopped; supervised installation requires a running engine")
            token = secrets.token_hex(32)
            state = {'token': token, 'release_id': approved, 'old_version': original['version'],
                     'version': manifest['version'], 'phase': 'stopping', 'job_id': job_id}
            atomic_json(self.record, state)
            self.phase(token, 'stopping')
            child = None
            applied = False
            try:
                self.wait_stopped()
                self.manager.apply(package, envelope, expected_release=approved, defer_commit=True)
                applied = True
                self.phase(token, 'candidate')
                child = self.runtime.start(token)
                self.wait_ready(child, token, manifest['version'], 'candidate')
                self.manager.commit_pending(approved, lambda: self.ready(child, token, manifest['version'], 'candidate'))
                # The durable commit precedes permission to execute financial cycles.
                atomic_json(self.control.activation, {'token': token, 'release_id': approved})
                self.control.maintenance.unlink()
                self.wait_ready(child, token, manifest['version'], 'running')
                atomic_json(self.record, {**state, 'phase': 'completed'})
                return {'status': 'installed_healthy', 'version': manifest['version'], 'release_id': approved}
            except BaseException:
                journal = json.loads(self.manager.journal.read_text()) if self.manager.journal.exists() else {}
                if journal.get('phase') == 'committed' and journal.get('release_id') == approved:
                    # Financial cycles may already have executed. Never restore an old balance.
                    atomic_json(self.record, {**state, 'phase': 'committed_restart_required'})
                    raise
                self.phase(token, 'cancelled')
                self.runtime.stop_owned(child)
                self.wait_stopped()
                if applied or journal.get('phase') in {'applying', 'pending_health'}:
                    self.manager.recover()
                self.restart_previous(original['version'])
                atomic_json(self.record, {**state, 'phase': 'rolled_back'})
                raise

    def recover(self):
        """After supervisor/PC failure: cooperative stop, then journal recovery.

        A committed release keeps its data. A pending candidate restores code
        and database together. No process is killed by a PID read from disk.
        """
        with single_instance(self.lock):
            state = json.loads(self.record.read_text())
            if state['phase'] in {'completed', 'rolled_back'}:
                return {'status': state['phase']}
            self.phase(state['token'], 'cancelled')
            self.wait_stopped()
            journal = json.loads(self.manager.journal.read_text()) if self.manager.journal.exists() else {}
            committed = journal.get('phase') == 'committed' and journal.get('release_id') == state['release_id']
            self.manager.recover()
            version = state['version'] if committed else state['old_version']
            self.restart_previous(version)
            status = 'completed' if committed else 'rolled_back'
            atomic_json(self.record, {**state, 'phase': status})
            return {'status': status, 'version': version}
