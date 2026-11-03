"""Retain production GET originals encrypted; inspect gaps without activation.

Use an explicit installation source containing the existing protected vault and
an output parent outside Git. This never provisions authorization/readiness,
changes configuration, constructs a write transport or places an order.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trader.live_account import EncryptedAuditStore, audit_directory
from trader.live_credentials import LiveCredentialVault
from trader.live_supervisor import ReadOnlyAdmissionFactsSource
from trader.live_transport import LiveError, LiveHTTPError, LiveReadOnlyTransport, SYMBOL
from trader.live_venue import LiveVenueReader


def safe_diagnostic(error):
    """Return transport-owned codes only; never arbitrary exception text."""
    if type(error) is LiveHTTPError:
        return error.diagnostics()
    if type(error) is LiveError:
        code = str(error)
        if re.fullmatch(r'(?:LIVE|VENUE)_[A-Z0-9_]{1,88}',code):
            return {'code':code}
    return {'code':'RETAINED_GET_DIAGNOSTIC_UNAVAILABLE'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--raw-parent', type=Path, required=True)
    parser.add_argument('--scope', choices=('SPOT_LIVE', 'FUTURES_LIVE'), action='append', required=True)
    parser.add_argument('--symbol', action='append', required=True)
    args = parser.parse_args(argv)
    if (len(args.scope) != len(set(args.scope)) or not 1 <= len(args.symbol) <= 10
            or len(args.symbol) != len(set(args.symbol)) or any(not SYMBOL.fullmatch(s) for s in args.symbol)):
        parser.error('Choose distinct scopes and one to ten distinct USDT symbols')
    result = {'schema':1, 'mode':'READ_ONLY_COMMISSIONING_DIAGNOSTIC', 'execution_enabled':False,
        'automatic_activation':False, 'commissioned':False, 'account_facts_certified':False,
        'state':'UNAVAILABLE', 'accounts':[], 'venues':[]}
    try:
        pairs = LiveCredentialVault(args.source.resolve() / 'data/live-preproduction/credentials.dpapi').read()
        if not set(args.scope) <= pairs.keys():
            raise ValueError()
        store = EncryptedAuditStore(audit_directory(args.raw_parent.resolve()))
        transport = LiveReadOnlyTransport({scope:pairs[scope] for scope in args.scope}, max_calls=200)
        facts = ReadOnlyAdmissionFactsSource(transport, retain=store.retain)
        venue = LiveVenueReader(transport, retain=store.retain)
        failed = False
        for scope in args.scope:
            try:
                result['accounts'].append(facts.observe(scope))
            except Exception as error:
                failed = True
                result['accounts'].append({'environment':scope, 'state':'UNAVAILABLE',
                    'diagnostic':safe_diagnostic(error),
                    'reasons':['LIVE_ACCOUNT_GET_OR_ENCRYPTED_RETENTION_UNAVAILABLE']})
            for symbol in args.symbol:
                try:
                    result['venues'].append(venue.summary(venue.capture(scope, symbol)))
                except Exception as error:
                    failed = True
                    result['venues'].append({'environment':scope, 'symbol':symbol, 'state':'UNAVAILABLE',
                        'diagnostic':safe_diagnostic(error),
                        'reasons':['LIVE_VENUE_GET_OR_ENCRYPTED_RETENTION_UNAVAILABLE']})
        result['state'] = 'INCOMPLETE_DIAGNOSTIC' if failed else 'READ_ONLY_DIAGNOSTIC_COMPLETE_WITH_GAPS'
        store.report(result)
    except Exception:
        result['state'] = 'UNAVAILABLE'
        result['reasons'] = ['PROTECTED_CREDENTIALS_OR_PRIVATE_ENCRYPTED_OUTPUT_UNAVAILABLE']
    print(json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2))
    return 0 if result['state'] == 'READ_ONLY_DIAGNOSTIC_COMPLETE_WITH_GAPS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
