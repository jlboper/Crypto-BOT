"""Local Windows-user protected LIVE records; never a trading permission.

No environment export, logs, web endpoint or provider call. DPAPI uses the current
Windows user, never LOCAL_MACHINE. Possession of credentials cannot enable orders.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path
import secrets
from ctypes import wintypes

class ProtectionError(ValueError):
    """Closed local protection error; never contains protected contents."""



MAX_BYTES = 32768
PURPOSES = ('BINANCE_LIVE_CREDENTIALS_V1', 'BINANCE_LOCAL_APPROVAL_V1', 'BINANCE_READINESS_V1')


class UserProtection:
    def _transform(self, raw, purpose, decrypt=False):
        if os.name != 'nt':
            raise ProtectionError('WINDOWS_USER_PROTECTION_REQUIRED')
        if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES or purpose not in PURPOSES:
            raise ProtectionError('INVALID_PROTECTED_RECORD')
        class Blob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
        source_buffer = ctypes.create_string_buffer(raw, len(raw))
        entropy_buffer = ctypes.create_string_buffer(purpose.encode('ascii'))
        source = Blob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        entropy = Blob(len(purpose), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        result = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p if decrypt else wintypes.LPCWSTR,
                              ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                              wintypes.DWORD, ctypes.POINTER(Blob)]
        operation.restype = wintypes.BOOL
        try:
            if not operation(ctypes.byref(source), None if decrypt else 'Crypto-BOT LIVE local record',
                             ctypes.byref(entropy), None, None, 1, ctypes.byref(result)):
                raise ProtectionError('USER_PROTECTED_RECORD_UNAVAILABLE')
            if not 1 <= result.cbData <= MAX_BYTES:
                raise ProtectionError('INVALID_PROTECTED_RECORD')
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            ctypes.memset(source_buffer, 0, len(raw))
            if result.pbData:
                ctypes.memset(result.pbData, 0, result.cbData)
                kernel.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))

    def protect(self, raw, purpose):
        return self._transform(raw, purpose)

    def unprotect(self, raw, purpose):
        return self._transform(raw, purpose, True)


def _json(raw):
    def pairs(values):
        out = {}
        for key, value in values:
            if key in out:
                raise ValueError()
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, RecursionError):
        raise ProtectionError('INVALID_PROTECTED_RECORD') from None


class ProtectedStore:
    """Purpose-bound local records. Injected protection is for isolated tests."""
    def __init__(self, path, purpose, *, protection=None):
        self.path = Path(path)
        if purpose not in PURPOSES:
            raise ProtectionError('INVALID_PROTECTED_PURPOSE')
        self.purpose, self.protection = purpose, protection or UserProtection()

    def _safe(self):
        if self.path.is_symlink() or any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)()
                                         for p in self.path.parents):
            raise ProtectionError('LINKED_PROTECTED_RECORD_BLOCKED')

    def read(self):
        self._safe()
        try:
            with self.path.open('rb') as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError()
            envelope = _json(raw)
            if (type(envelope) is not dict or set(envelope) != {'schema', 'purpose', 'cipher', 'data'}
                    or envelope['schema'] != 1 or type(envelope['schema']) is not int
                    or envelope['purpose'] != self.purpose or envelope['cipher'] != 'DPAPI_CURRENT_USER'):
                raise ValueError()
            protected = base64.b64decode(envelope['data'], validate=True)
            result = self.protection.unprotect(protected, self.purpose)
            if not 1 <= len(result) <= MAX_BYTES:
                raise ValueError()
            return _json(result)
        except (OSError, ValueError, TypeError, KeyError):
            raise ProtectionError('USER_PROTECTED_RECORD_UNAVAILABLE') from None

    def write(self, value, *, replace=False):
        self._safe()
        if self.path.exists() and not replace:
            raise ProtectionError('EXISTING_PROTECTED_RECORD_REQUIRES_EXPLICIT_REPLACEMENT')
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
        if len(raw) > MAX_BYTES//2:
            raise ProtectionError('PROTECTED_RECORD_TOO_LARGE')
        protected = self.protection.protect(raw, self.purpose)
        out = json.dumps({'schema': 1, 'purpose': self.purpose, 'cipher': 'DPAPI_CURRENT_USER',
                          'data': base64.b64encode(protected).decode('ascii')}, separators=(',', ':')).encode()
        if len(out) > MAX_BYTES:
            raise ProtectionError('PROTECTED_RECORD_TOO_LARGE')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name('.protected-' + secrets.token_hex(16))
        try:
            with temporary.open('xb') as handle:
                os.chmod(temporary, 0o600)
                handle.write(out); handle.flush(); os.fsync(handle.fileno())
            self._safe()
            if replace:
                os.replace(temporary, self.path)
            else:
                # Hard-link creation is exclusive, never silently overwrite a
                # concurrently configured record. Both names contain ciphertext.
                os.link(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
