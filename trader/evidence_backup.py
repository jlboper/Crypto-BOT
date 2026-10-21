"""Explicit, local SQLite evidence copies; no engine, credentials or recovery action.

Each database is a separate SQLite-consistent snapshot. These copies do not
certify a cross-database transaction, exchange account balance or capital baseline.
The existing signed updater and its rollback protocol are deliberately unchanged.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time


DATABASES = (
    'testnet-trader.db', 'futures-testnet.db', 'market-pulse.db',
    'market-pulse-ai.db', 'quant-shadow.db', 'guardian-shadow.db',
    'guardian-ai.db', 'opportunity-shadow.db',
)


def _iso():
    return datetime.now(UTC).isoformat()


def _digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def _checked_directory(path):
    path = Path(path).absolute()
    # A junction or symlink must not redirect a financial evidence operation.
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError('LINKED_EVIDENCE_PATH')
    return path.resolve()


def backup_evidence(source, output, *, names=DATABASES, timeout_seconds=30):
    """Create new private copies; never initialize/migrate or replace a source.

    Partial copies are retained with an INCOMPLETE manifest for diagnosis. A
    failed copy must not be used for recovery. Missing selected sources are
    explicit, and are not recreated as empty wallets. This is an explicit tool,
    never invoked by dashboard reads or the trading cycle.
    """
    if (type(names) not in (tuple, list) or not names or len(set(names)) != len(names)
            or any(type(name) is not str or name not in DATABASES for name in names)
            or type(timeout_seconds) not in (int, float)
            or not 0 < timeout_seconds <= 120):
        raise ValueError('INVALID_EVIDENCE_BACKUP_REQUEST')
    source, output = _checked_directory(source), _checked_directory(output)
    if not source.is_dir() or output == source or output.is_relative_to(source):
        raise ValueError('SEPARATE_EXISTING_SOURCE_REQUIRED')
    if not output.parent.is_dir():
        raise ValueError('OUTPUT_PARENT_MUST_EXIST')
    for name in names:
        path = source / name
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('LINKED_EVIDENCE_DATABASE')
    output.mkdir(exist_ok=False)
    report = {
        'schema': 1, 'kind': 'LOCAL_SQLITE_EVIDENCE_BACKUP',
        'started_at': _iso(), 'completed_at': None, 'state': 'INCOMPLETE',
        'globally_atomic': False, 'restores_operating_data': False,
        'account_baseline_certified': False, 'files': [],
    }
    # A process interruption must leave an explicitly incomplete directory.
    # This path was created exclusively by this invocation, never reused.
    with (output / 'manifest.json').open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=True, allow_nan=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    for name in names:
        path, target = source / name, output / name
        row = {'name': name, 'state': 'NOT_FOUND', 'started_at': _iso(),
               'completed_at': None, 'sha256': None, 'bytes': None,
               'quick_check': None, 'error': None}
        report['files'].append(row)
        if not path.is_file():
            row['completed_at'] = _iso()
            continue
        deadline = time.monotonic() + timeout_seconds

        def progress(_status, _remaining, _total):
            if time.monotonic() > deadline:
                raise TimeoutError('EVIDENCE_BACKUP_DEADLINE')

        reader = writer = None
        try:
            reader = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.25)
            reader.execute('PRAGMA query_only=ON')
            # Exclusive creation makes accidental replacement impossible.
            with target.open('xb'):
                pass
            writer = sqlite3.connect(target, timeout=.25)
            reader.backup(writer, pages=64, progress=progress, sleep=.01)
            writer.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            check = writer.execute('PRAGMA quick_check(1)').fetchone()
            if check != ('ok',):
                raise sqlite3.DatabaseError('EVIDENCE_BACKUP_INTEGRITY')
            writer.close()
            writer = None
            row.update(state='VERIFIED_COPY', quick_check='ok',
                       sha256=_digest(target), bytes=target.stat().st_size)
        except (OSError, sqlite3.Error, TimeoutError):
            row.update(state='INCOMPLETE', error='COPY_OR_INTEGRITY_FAILED')
        finally:
            if writer is not None:
                writer.close()
            if reader is not None:
                reader.close()
            row['completed_at'] = _iso()
    report['completed_at'] = _iso()
    if all(row['state'] == 'VERIFIED_COPY' for row in report['files']):
        report['state'] = 'VERIFIED_COPIES'
    # Manifest contains only metadata, never financial rows or source paths.
    temporary = output / '.manifest.tmp'
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=True, allow_nan=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(output / 'manifest.json')
    return report
