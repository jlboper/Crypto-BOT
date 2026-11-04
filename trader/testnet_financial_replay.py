"""Read retained originals and produce separate encrypted diagnostics, no GETs."""
from __future__ import annotations

from pathlib import Path
import hashlib
import re

from .account_inventory import HOSTS
from .financial_capture import _directory, _load_cipher, _save_cipher, dpapi_unprotect
from .financial_evidence import AUTHORITY, digest
from .financial_evidence_io import _path
from .live_account import dpapi_protect
from .testnet_financial_materializer import reconcile_testnet_sources


def verify_retained_packet(path, *, unprotect=dpapi_unprotect):
    """Check every original reference, without trusting the packet's copy."""
    path = _path(path, existing=True)
    if (path.name != 'sources.dpapi' or path.parent.parent.name != 'windows'
            or not re.fullmatch('[a-f0-9]{64}', path.parent.name)):
        raise ValueError('TESTNET_RETAINED_WINDOW_PATH_REQUIRED')
    scope_dir = path.parent.parent.parent
    scope = scope_dir.name
    if scope not in HOSTS:
        raise ValueError('TESTNET_RETAINED_SCOPE_REQUIRED')
    packet = _load_cipher(path, unprotect)
    if (type(packet) is not dict or type(packet.get('schema')) is not int or packet['schema'] != 1
            or packet.get('environment') != scope or packet.get('source_scope') != 'BOUNDED_SYMBOLS'
            or digest(packet.get('original')) != path.parent.name
            or any(packet.get(name) is not False for name in AUTHORITY)):
        raise ValueError('TESTNET_RETAINED_PACKET_INVALID')
    refs, sources = packet.get('source_refs'), packet.get('sources')
    if (type(refs) is not list or type(sources) is not list or not 1 <= len(refs) <= 1024
            or len(refs) != len(sources)):
        raise ValueError('TESTNET_RETAINED_SOURCE_LIMIT')
    seen = set()
    for ref, source in zip(refs, sources):
        if (type(ref) is not dict or set(ref) != {'file', 'sha256', 'encrypted_sha256'}
                or type(ref['file']) is not str
                or not re.fullmatch(r'responses/[0-9]{12}\.dpapi', ref['file'])
                or ref['file'] in seen):
            raise ValueError('TESTNET_SOURCE_REFERENCE_INVALID')
        seen.add(ref['file'])
        retained = _path(scope_dir/ref['file'], existing=True)
        # _load_cipher has its own size/link checks before decryption.
        original = _load_cipher(retained, unprotect)
        if (hashlib.sha256(retained.read_bytes()).hexdigest() != ref['encrypted_sha256']
                or digest(original) != ref['sha256'] or original != source
                or original.get('environment') != scope or original.get('host') != HOSTS[scope]):
            raise ValueError('TESTNET_SOURCE_SCOPE_OR_CONTENT_CHANGED')
    return packet


def replay_retained_windows(source_dir, output_dir, *, max_windows=100,
                            protect=dpapi_protect, unprotect=dpapi_unprotect):
    """Bounded offline replay. Never alter a source window, ledger or cohort."""
    if type(max_windows) is not int or not 1 <= max_windows <= 1000:
        raise ValueError('TESTNET_REPLAY_WINDOW_LIMIT_REQUIRED')
    source = Path(source_dir).absolute()
    if source.name not in HOSTS or not source.is_dir():
        raise ValueError('TESTNET_RETAINED_SCOPE_REQUIRED')
    output = Path(output_dir).absolute().resolve()
    if source.resolve() == output or source.resolve() in output.parents or output in source.resolve().parents:
        raise ValueError('SEPARATE_TESTNET_REPLAY_OUTPUT_REQUIRED')
    output = _directory(output_dir)
    summary = {'schema':1, 'state':'RETAINED_SOURCE_DIAGNOSTICS_WRITTEN',
               'windows_examined':0, 'diagnostics_written':0, 'windows_blocked':0,
               'source_scope':'BOUNDED_SYMBOLS', 'financial_window_complete':False,
               'source_files_modified':False, 'network_calls':0, 'reason_codes':[], **AUTHORITY}
    reasons = set()
    for path in (source/'windows').glob('*/sources.dpapi'):
        if summary['windows_examined'] >= max_windows:
            reasons.add('TESTNET_REPLAY_LIMIT_REACHED'); break
        summary['windows_examined'] += 1
        try:
            packet = verify_retained_packet(path, unprotect=unprotect)
            result = reconcile_testnet_sources(packet)
            target = output/(path.parent.name+'.dpapi')
            if target.exists():
                if _load_cipher(target, unprotect) != result:
                    raise ValueError('TESTNET_REPLAY_DIAGNOSTIC_CHANGED')
            else:
                _save_cipher(target, result, protect)
            summary['diagnostics_written'] += 1
            reasons.update(result['summary']['reason_codes'])
        except (OSError, ValueError, TypeError, KeyError):
            summary['windows_blocked'] += 1
            reasons.add('TESTNET_RETAINED_SOURCE_VERIFICATION_FAILED')
    if summary['windows_blocked']:
        summary['state'] = 'RETAINED_SOURCE_REPLAY_PARTIAL'
    elif not summary['windows_examined']:
        summary['state'] = 'NO_RETAINED_SOURCE_WINDOW'
    summary['reason_codes'] = sorted(reasons)
    return summary
