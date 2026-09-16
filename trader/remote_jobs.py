"""Allowlisted, persisted background jobs. No arbitrary command or URL input."""
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


ACTIONS = frozenset({'research', 'update_check', 'update_install'})
TERMINAL = frozenset({'completed', 'failed'})
MAX_MESSAGE = 300
MAX_RUNTIME_SECONDS = 7200


@contextmanager
def _exclusive(path):
    """Serialize state transitions across the agent and its child process."""
    handle = path.open('a+b')
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class RemoteJobs:
    def __init__(self, root, source):
        self.root, self.source = Path(root).resolve(), Path(source).resolve()
        self.directory = self.root / 'data/portal-jobs'
        self.directory.mkdir(parents=True, exist_ok=True)

    def _read(self, path):
        data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or type(data.get('id')) is not int or data['id'] <= 0
                or data.get('action') not in ACTIONS or data.get('status') not in {'running', *TERMINAL}
                or type(data.get('at')) not in (int, float) or not isinstance(data.get('message'), str)
                or len(data['message']) > MAX_MESSAGE):
            raise ValueError('Invalid persisted job')
        return data

    def _replace(self, path, data):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.directory,
                                             prefix=f'.{path.stem}-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, separators=(',', ':'))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def accept(self, job):
        now = time.time()
        if type(job.get('id')) is not int or job['id'] <= 0 or job.get('action') not in ACTIONS:
            raise ValueError('Invalid job')
        if type(job.get('expires')) not in (int, float) or not now < job['expires'] <= now + 305:
            raise ValueError('Expired job')
        path = self.directory / (str(job['id'])+'.json')
        try:
            with path.open('x', encoding='utf-8') as file:
                json.dump({'id': job['id'], 'action': job['action'], 'status': 'running',
                           'message': 'Trabajo recibido en Windows', 'at': now}, file, separators=(',', ':'))
                file.flush()
                os.fsync(file.fileno())
        except FileExistsError:
            existing = self._read(path)
            if existing['id'] != job['id'] or existing['action'] != job['action']:
                raise ValueError('Job identifier conflict')
            return
        try:
            subprocess.Popen([sys.executable,str(self.root/'scripts/remote_job.py'),'--source',str(self.source),'--id',str(job['id'])],
                             cwd=self.root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except Exception:
            self.finish(job['id'],'failed','No se pudo iniciar el trabajo')

    def finish(self, identifier, status, message):
        if type(identifier) is not int or identifier <= 0 or status not in TERMINAL:
            raise ValueError('Invalid job result')
        path = self.directory / (str(identifier)+'.json')
        with _exclusive(path.with_suffix('.lock')):
            data = self._read(path)
            # A timeout or other terminal state is final. A late child cannot reverse it.
            if data['status'] != 'running':
                return False
            data.update(status=status, message=str(message)[:MAX_MESSAGE], at=time.time())
            self._replace(path, data)
            return True

    def results(self):
        paths = sorted((path for path in self.directory.glob('*.json') if path.stem.isdecimal()),
                       key=lambda path: int(path.stem))[-20:]
        result = []
        for path in paths:
            try:
                data = self._read(path)
                if data['status'] == 'running' and time.time()-data['at'] > MAX_RUNTIME_SECONDS:
                    self.finish(data['id'], 'failed', 'Tiempo de trabajo excedido; revisar en Windows antes de repetir')
                    data = self._read(path)
            except (OSError, ValueError, json.JSONDecodeError):
                # One damaged local record must not stop heartbeats or other results.
                continue
            result.append({key: data[key] for key in ('id', 'action', 'status', 'message')})
        return result
