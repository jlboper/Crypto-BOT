"""Dedicated LIVE credential vault. Possession never authorizes orders."""
from contextlib import contextmanager
import errno
import os
import stat
import time

from .live_transport import LiveCredentials, LiveError
from .local_protection import ProtectedStore, UserProtection, ProtectionError, PURPOSES

SCOPES = frozenset({'SPOT_LIVE', 'FUTURES_LIVE'})
CREDENTIAL_LOCK_WAIT_SECONDS = 5.0


class LiveCredentialVault:
    def __init__(self, path, *, protection=None):
        self.store = ProtectedStore(path, PURPOSES[0], protection=protection)

    def read(self):
        try:
            value = self.store.read()
        except ProtectionError:
            raise LiveError('USER_PROTECTED_RECORD_UNAVAILABLE') from None
        if (type(value) is not dict or set(value) != {'schema', 'orders_enabled', 'credentials'}
                or type(value['schema']) is not int or value['schema'] != 1 or value['orders_enabled'] is not False
                or type(value['credentials']) is not dict or not value['credentials']
                or set(value['credentials']) - {'SPOT_LIVE', 'FUTURES_LIVE'}):
            raise LiveError('INVALID_LIVE_CREDENTIAL_VAULT')
        result = {}
        for scope, pair in value['credentials'].items():
            if type(pair) is not dict or set(pair) != {'api_key', 'api_secret'}:
                raise LiveError('INVALID_LIVE_CREDENTIAL_VAULT')
            result[scope] = LiveCredentials(pair['api_key'], pair['api_secret'])
        return result

    def configure(self, credentials, *, replace=False):
        if (type(credentials) is not dict or not credentials
                or set(credentials) - SCOPES
                or any(type(pair) is not LiveCredentials for pair in credentials.values())
                or type(replace) is not bool):
            raise LiveError('EXPLICIT_LIVE_CREDENTIALS_REQUIRED')
        credentials = dict(credentials)
        with self._write_lock():
            self._write(credentials, replace=replace)

    def configure_scope(self, scope, pair, *, replace=False):
        """Merge one owner-entered scope against the current locked record.

        Collect hidden input before calling this method. A console opened before
        another scope was configured must never save its old snapshot over it.
        """
        if type(scope) is not str or scope not in SCOPES or type(pair) is not LiveCredentials or type(replace) is not bool:
            raise LiveError('EXPLICIT_LIVE_CREDENTIALS_REQUIRED')
        with self._write_lock():
            current = self.read() if self.store.path.exists() else {}
            if scope in current and not replace:
                raise LiveError('EXPLICIT_CREDENTIAL_REPLACEMENT_REQUIRED')
            current[scope] = pair
            self._write(current, replace=self.store.path.exists())

    def _write(self, credentials, *, replace):
        try:
            self.store.write({'schema': 1, 'orders_enabled': False,
            'credentials': {scope: {'api_key': pair.api_key, 'api_secret': pair.api_secret}
                            for scope, pair in credentials.items()}}, replace=replace)
        except (ProtectionError, OSError):
            raise LiveError('USER_PROTECTED_RECORD_UNAVAILABLE') from None

    @contextmanager
    def _write_lock(self):
        """A cooperative vault-only OS lock; never the trading process lock.

        The persistent empty marker contains no secret; legacy one-byte markers
        are also accepted. Windows can lock a range beyond EOF, so never write
        that byte before locking: another process may already own its range.
        OS ownership ends
        after process termination, so a crashed writer cannot strand a lock.
        """
        handle, acquired = None, False
        path = self.store.path.with_name(self.store.path.name + '.lock')
        try:
            self.store._safe()
            ProtectedStore(path, PURPOSES[0])._safe()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.store._safe()
            ProtectedStore(path, PURPOSES[0])._safe()
            flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
            descriptor = os.open(path, flags, 0o600)
            handle = os.fdopen(descriptor, 'r+b')
            opened, named = os.fstat(handle.fileno()), os.stat(path, follow_symlinks=False)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size > 1
                    or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                    or getattr(named, 'st_file_attributes', 0) & 0x400):
                raise LiveError('CREDENTIAL_LOCK_PATH_BLOCKED')
            deadline = time.monotonic() + CREDENTIAL_LOCK_WAIT_SECONDS
            while True:
                try:
                    handle.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    if time.monotonic() >= deadline:
                        raise LiveError('CREDENTIAL_STORE_BUSY') from None
                    time.sleep(0.025)
            self.store._safe()
            ProtectedStore(path, PURPOSES[0])._safe()
            current = os.stat(path, follow_symlinks=False)
            if ((opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
                    or current.st_nlink != 1 or not stat.S_ISREG(current.st_mode)
                    or current.st_size not in {0, 1} or getattr(current, 'st_file_attributes', 0) & 0x400):
                raise LiveError('CREDENTIAL_LOCK_PATH_BLOCKED')
        except (ProtectionError, OSError):
            if handle is not None:
                handle.close()
            raise LiveError('USER_PROTECTED_RECORD_UNAVAILABLE') from None
        except BaseException:
            if handle is not None:
                handle.close()
            raise
        try:
            yield
        finally:
            if handle is not None:
                try:
                    if acquired:
                        handle.seek(0)
                        if os.name == 'nt':
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    # Closing the handle also releases OS ownership. An unlock
                    # diagnostic must not misreport a completed atomic write.
                    pass
                finally:
                    handle.close()

    def status(self):
        try:
            scopes = sorted(self.read())
            return {'state': 'CONFIGURED_READ_ONLY', 'scopes': scopes, 'orders_enabled': False}
        except LiveError:
            return {'state': 'NOT_CONFIGURED_OR_UNAVAILABLE', 'scopes': [], 'orders_enabled': False}
