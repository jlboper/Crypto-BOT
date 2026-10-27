"""Explicit local packet ingestion and read-only financial coverage projection.

This is not an automatic producer of exchange sources. Imported canonical cuts
are retained claims whose internal consistency is checked; no Binance origin or
financial authorization is asserted. Operating databases and original receipts
are never initialized, migrated, replaced or edited by these functions.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from .financial_evidence import (AUTHORITY, MAX_BYTES, FinancialEvidenceStore,
    _hash, _iso, _time, build_financial_receipt, canonical, digest)


MAX_ORIGINAL_BYTES = 16*1024*1024
_ANCHOR_KEYS = {'schema','kind','journal_ref','tail','records','updated_at'}
_OBJECTS = {'financial_receipts','sqlite_sequence','financial_cohort',
            'sqlite_autoindex_financial_receipts_1','sqlite_autoindex_financial_receipts_2',
            'financial_no_update','financial_no_delete'}


def _clock():
    return _iso(datetime.now(UTC))


def _path(value, *, existing=False):
    path = Path(value).absolute()
    if (len(str(path)) > 4096 or '\x00' in str(path) or path.drive.startswith('\\\\')
            or any(p.is_symlink() or getattr(p,'is_junction',lambda:False)()
                   for p in (path,*path.parents))):
        raise ValueError('REGULAR_LOCAL_EVIDENCE_PATH_REQUIRED')
    if os.name == 'nt' and any(':' in part or Path(part).is_reserved() for part in path.parts[1:]):
        raise ValueError('REGULAR_LOCAL_EVIDENCE_PATH_REQUIRED')
    # Check the supplied components for links before normalizing. absolute()
    # retains '..', which otherwise lets an output alias a retained input.
    path = path.resolve()
    if path.exists():
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('REGULAR_SINGLE_LINK_EVIDENCE_FILE_REQUIRED')
    elif existing:
        raise ValueError('RETAINED_EVIDENCE_FILE_REQUIRED')
    if not path.parent.is_dir():
        raise ValueError('EXISTING_EVIDENCE_PARENT_REQUIRED')
    return path


def read_retained_json(path, *, max_bytes=MAX_BYTES):
    """Bounded, strict JSON from an existing regular local file; no writes."""
    path=_path(path,existing=True)
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_ORIGINAL_BYTES:
        raise ValueError('BOUNDED_RETAINED_JSON_REQUIRED')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:
                raise ValueError('DUPLICATE_RETAINED_JSON_KEY')
            result[key]=value
        return result
    before=path.stat()
    with path.open('rb') as handle:
        opened=os.fstat(handle.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino)
                or opened.st_size > max_bytes):
            raise ValueError('BOUNDED_REGULAR_RETAINED_JSON_REQUIRED')
        raw=handle.read(max_bytes+1)
        after=os.fstat(handle.fileno())
    if len(raw)>max_bytes or (after.st_size,after.st_mtime_ns)!=(opened.st_size,opened.st_mtime_ns):
        raise ValueError('RETAINED_JSON_CHANGED_OR_TOO_LARGE')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('NONFINITE_RETAINED_JSON')))


def _paths(journal, anchor, inputs=()):
    journal,anchor=_path(journal),_path(anchor)
    lock=_path(str(journal)+'.ingest.lock')
    used={os.path.normcase(str(p)) for p in (journal,anchor,lock)}
    reserved={os.path.normcase(str(journal)+suffix) for suffix in ('-journal','-wal','-shm')}
    if len(used)!=3 or os.path.normcase(str(anchor)) in reserved:
        raise ValueError('SEPARATE_FINANCIAL_JOURNAL_AND_ANCHOR_REQUIRED')
    for source in inputs:
        if os.path.normcase(str(_path(source,existing=True))) in used|reserved:
            raise ValueError('RETAINED_INPUT_CANNOT_BE_OUTPUT')
    return journal,anchor,lock


def _journal_state(path):
    if not path.exists():
        return {'state':'VALID_LOCAL_CHAIN','anchor':'0'*64,'records':0,'external_attestation':False}
    _path(path,existing=True)
    if path.stat().st_size>256*1024*1024:
        raise ValueError('BOUNDED_FINANCIAL_JOURNAL_REQUIRED')
    # Refuse to initialize our tables inside a ledger or any other SQLite file.
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        entries=list(db.execute('SELECT name,type FROM sqlite_master LIMIT 20'))
        objects={row[0] for row in entries}
        if not objects or not {'financial_receipts','financial_no_update','financial_no_delete'} <= objects or not objects <= _OBJECTS:
            raise ValueError('DEDICATED_FINANCIAL_JOURNAL_REQUIRED')
        if any(kind!=('trigger' if name.startswith('financial_no_') else 'table' if name in {'financial_receipts','sqlite_sequence'} else 'index')
               for name,kind in entries):
            raise ValueError('DEDICATED_FINANCIAL_TABLES_REQUIRED')
        if db.execute('SELECT COUNT(*) FROM financial_receipts').fetchone()[0]>100000:
            raise ValueError('BOUNDED_FINANCIAL_JOURNAL_REQUIRED')
        largest=db.execute('SELECT MAX(length(receipt)),MAX(length(bundle)) FROM financial_receipts').fetchone()
        if (largest[0] or 0)>32768 or (largest[1] or 0)>MAX_BYTES:
            raise ValueError('BOUNDED_FINANCIAL_JOURNAL_RECORDS_REQUIRED')
    result=FinancialEvidenceStore(path).verify_chain()
    if result['state']!='VALID_LOCAL_CHAIN':
        raise ValueError('FINANCIAL_JOURNAL_CHAIN_INVALID')
    return result


def _journal_ref(path):
    return digest({'local_journal':os.path.normcase(str(path.resolve()))})


def _anchor(path, journal, *, now):
    value=read_retained_json(path,max_bytes=4096)
    if (type(value) is not dict or set(value)!=_ANCHOR_KEYS or value['schema']!=1
            or type(value['schema']) is not int or value['kind']!='FINANCIAL_JOURNAL_ANCHOR_V1'
            or value['journal_ref']!=_journal_ref(journal) or type(value['records']) is not int
            or not 0 <= value['records'] <= 100000 or _time(value['updated_at'])>_time(now)):
        raise ValueError('RETAINED_FINANCIAL_ANCHOR_INVALID')
    _hash(value['tail'])
    return value


@contextmanager
def _writer_lock(path):
    path=_path(path)
    flags=os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)
    with os.fdopen(os.open(path,flags,0o600),'r+b') as handle:
        opened,named=os.fstat(handle.fileno()),os.stat(path,follow_symlinks=False)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink!=1 or opened.st_size not in {0,1}
                or (opened.st_dev,opened.st_ino)!=(named.st_dev,named.st_ino)
                or getattr(named,'st_file_attributes',0)&0x400):
            raise ValueError('REGULAR_FINANCIAL_LOCK_REQUIRED')
        # Windows can lock beyond EOF. Never write an initialization byte before
        # acquiring ownership; another process may already own that byte range.
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            _path(path,existing=True)
            named=os.stat(path,follow_symlinks=False)
            if ((opened.st_dev,opened.st_ino)!=(named.st_dev,named.st_ino)
                    or named.st_nlink!=1 or named.st_size not in {0,1}):
                raise ValueError('FINANCIAL_LOCK_IDENTITY_CHANGED')
            yield
        finally:
            try:
                handle.seek(0)
                if os.name=='nt':
                    msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
            except OSError:
                pass  # close releases ownership; do not misreport a commit.


def _atomic_anchor(path, value):
    """Flush content, then atomically publish metadata; no partial JSON anchor."""
    fd,temporary=tempfile.mkstemp(prefix='.financial-anchor-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(canonical(value).encode('ascii'));handle.flush();os.fsync(handle.fileno())
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            move=ctypes.WinDLL('kernel32',use_last_error=True).MoveFileExW
            move.argtypes=(wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD)
            move.restype=wintypes.BOOL
            if not move(temporary,str(path),0x1|0x8):  # REPLACE_EXISTING | WRITE_THROUGH
                raise OSError('ATOMIC_FINANCIAL_ANCHOR_FAILED')
        else:
            os.replace(temporary,path)
            directory=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(directory)
            finally:os.close(directory)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def _public(state, *, received=False, complete=False, duplicate=False):
    return {'schema':1,'mode':'EXPLICIT_RETAINED_PACKET','state':state,
        'packet_received':received,'supplied_window_complete':complete,'duplicate':duplicate,
        'coverage_verified':False,'external_attestation':False,'automatic_source_producer':False,**AUTHORITY}


def ingest_financial_files(registration_path, original_path, bundle_path, *, journal_path,
                           anchor_path, reconcile_anchor=False, clock=_clock):
    """Append one explicit retained packet; print no amounts, raw rows or IDs.

    Rerunning normally is idempotent. A committed append with a missing/stale
    anchor blocks reads and new appends. Explicit reconciliation accepts only
    that same single unanchored tail packet and preserves its original timestamp.
    The clock argument is for offline synthetic tests; the CLI never backdates.
    """
    committed=False
    try:
        now=clock();_time(now)
        journal,anchor,lock=_paths(journal_path,anchor_path,(registration_path,original_path,bundle_path))
        registration=read_retained_json(registration_path,max_bytes=32768)
        original=read_retained_json(original_path,max_bytes=32768)
        bundle=read_retained_json(bundle_path)
        checked=build_financial_receipt(registration,original,bundle,now=now)
        if checked['cohort_digest'] is None:
            raise ValueError('VALID_RETAINED_FINANCIAL_PACKET_REQUIRED')
        with _writer_lock(lock):
            state=_journal_state(journal)
            previous=_anchor(anchor,journal,now=now) if anchor.exists() else None
            aligned=(previous is None and state['records']==0 or previous is not None
                     and (previous['tail'],previous['records'])==(state['anchor'],state['records']))
            if reconcile_anchor:
                if aligned:
                    return _public('ANCHOR_ALREADY_CURRENT')
                count=previous['records'] if previous else 0
                tail=previous['tail'] if previous else '0'*64
                if state['records']!=count+1:
                    raise ValueError('SINGLE_UNANCHORED_PACKET_REQUIRED')
                with closing(sqlite3.connect(journal.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
                    row=db.execute('SELECT id,receipt,bundle,previous,hash FROM financial_receipts ORDER BY sequence DESC LIMIT 1').fetchone()
                retained=json.loads(row[1])
                if _time(retained['available_at'])>_time(now):
                    raise ValueError('FINANCIAL_CLOCK_REGRESSION')
                rebuilt=build_financial_receipt(registration,original,bundle,now=retained['available_at'])
                identity=digest({'method':rebuilt['method'],'original':rebuilt['original_receipt_digest'],'bundle':rebuilt['bundle_digest']})
                if (row[0]!=identity or retained!=rebuilt or digest(json.loads(row[2]))!=digest(bundle)
                        or row[3]!=tail or row[4]!=state['anchor']):
                    raise ValueError('EXACT_UNANCHORED_PACKET_REQUIRED')
                result=_public('ANCHOR_RECONCILED',received=True,complete=retained['financial_window_complete'],duplicate=True)
            else:
                if not aligned:
                    return _public('ANCHOR_RECONCILIATION_REQUIRED')
                store=FinancialEvidenceStore(journal)
                if not journal.exists():store.initialize()
                saved=store.record(registration,original,bundle,now=now)
                if saved['duplicate']:
                    return _public('PACKET_ALREADY_RETAINED',received=True,
                        complete=saved['receipt']['financial_window_complete'],duplicate=True)
                committed=True
                state=_journal_state(journal)
                if state['anchor']!=saved['hash']:
                    raise ValueError('FINANCIAL_APPEND_RACE')
                result=_public('PACKET_RETAINED',received=True,complete=saved['receipt']['financial_window_complete'])
            _atomic_anchor(anchor,{'schema':1,'kind':'FINANCIAL_JOURNAL_ANCHOR_V1',
                'journal_ref':_journal_ref(journal),'tail':state['anchor'],'records':state['records'],'updated_at':now})
            result['anchor_current']=True
            return result
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,OSError,sqlite3.Error):
        return _public('JOURNAL_COMMITTED_ANCHOR_PENDING' if committed else 'RETAINED_PACKET_REJECTED',received=committed)


def read_financial_overlay(journal_path, anchor_path, registration, originals, *, now,
                           expected_cohort_digest, expected_account_ref, expected_unit_scale):
    """Read-only status helper. Missing/dirty/old anchors qualify no windows.

    Returns only bounded coverage counts and timestamps, never source rows,
    balances, trade IDs, account fingerprints or paths. It changes no old cohort
    receipt, decision or original performance metric. Call this with the actual
    status snapshot time and retain it as a separate as-of-today outcome overlay.
    """
    closed={'schema':1,'mode':'EXPLICIT_RETAINED_PACKET_COVERAGE','state':'UNKNOWN','at':None,
        'journal_verified':False,'coverage_verified':False,'valid_windows':0,'covered_seconds':0,
        'qualified_days':None,'continuous_qualified_days':None,'late_reconciled_windows':0,
        'missing_windows':None,'conflicting_windows':0,'external_attestation':False,
        'automatic_source_producer':False,'reason_codes':['FINANCIAL_JOURNAL_VERIFICATION_REQUIRED'],**AUTHORITY}
    try:
        closed['at']=_iso(_time(now))
        journal,anchor,_=_paths(journal_path,anchor_path)
        if not journal.exists() or not anchor.exists():return closed
        state=_journal_state(journal);retained=_anchor(anchor,journal,now=now)
        if (retained['tail'],retained['records'])!=(state['anchor'],state['records']):return closed
        result=FinancialEvidenceStore(journal).coverage(registration,originals,now=now,
            expected_cohort_digest=expected_cohort_digest,expected_account_ref=expected_account_ref,
            expected_unit_scale=expected_unit_scale,expected_anchor=retained['tail'])
        if _anchor(anchor,journal,now=now)!=retained:return closed
        allowed=('state','journal_verified','valid_windows','covered_seconds','qualified_days',
            'continuous_qualified_days','late_reconciled_windows','missing_windows','conflicting_windows','reason_codes')
        closed.update({key:result[key] for key in allowed})
        closed['coverage_verified']=result['journal_verified'] and result['valid_windows']>0
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,OSError,sqlite3.Error):
        pass
    return closed
