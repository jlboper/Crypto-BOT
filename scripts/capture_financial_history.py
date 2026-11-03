"""Explicit original financial GET capture; resumable, encrypted, no orders."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trader.financial_capture import FinancialHistoryCapture, FinancialCaptureService, EarnSourceCapture
from trader.live_credentials import LiveCredentialVault
from trader.live_transport import LiveError, LiveReadOnlyTransport


class ClosedParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'FINANCIAL_CAPTURE_ARGUMENTS_INVALID\n')


def main(argv=None):
    parser = ClosedParser(description=__doc__)
    parser.add_argument('--ack-read-only', required=True, action='store_true')
    parser.add_argument('--vault', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--scope', choices=('SPOT_LIVE', 'FUTURES_LIVE'))
    parser.add_argument('--spot-symbols', default='BTCUSDT,ETHUSDT')
    parser.add_argument('--futures-symbols', default='BTCUSDT,ETHUSDT')
    parser.add_argument('--start-utc-ms', type=int)
    parser.add_argument('--end-utc-ms', type=int)
    parser.add_argument('--max-calls', type=int, default=80)
    parser.add_argument('--daily-snapshots', action='store_true',
                        help='Explicit high-weight daily original cuts; 2400 IP weight per scope, one scope per invocation')
    parser.add_argument('--prospective-tick', action='store_true',
                        help='Capture/resume one bounded prospective step without daily-snapshot calls')
    parser.add_argument('--earn-history', action='store_true',
                        help='Explicit supplemental Earn sources, Spot scope only, at most four high-weight GETs')
    args = parser.parse_args(argv)
    try:
        if args.prospective_tick and (args.earn_history or args.daily_snapshots or args.start_utc_ms is not None or args.end_utc_ms is not None):
            raise LiveError('SEPARATE_PROSPECTIVE_AND_BACKFILL_CAPTURE_REQUIRED')
        if args.earn_history and (args.daily_snapshots or args.scope != 'SPOT_LIVE'):
            raise LiveError('EXPLICIT_SEPARATE_SPOT_EARN_CAPTURE_REQUIRED')
        vault = LiveCredentialVault(args.vault)
        def source():
            credentials = vault.read()
            if args.scope:
                if args.scope not in credentials:
                    raise LiveError('LIVE_REQUESTED_SCOPE_NOT_CONFIGURED')
                credentials = {args.scope: credentials[args.scope]}
            return credentials
        credentials = source()
        symbols = {scope: (args.spot_symbols if scope == 'SPOT_LIVE' else args.futures_symbols).split(',')
                   for scope in credentials}
        if args.prospective_tick:
            report = FinancialCaptureService(source, args.output_dir, symbols=symbols).tick(max_calls=args.max_calls)
        else:
            if args.start_utc_ms is None or args.end_utc_ms is None:
                raise LiveError('EXPLICIT_FIXED_HISTORY_WINDOW_REQUIRED')
            transport = LiveReadOnlyTransport(credentials, max_calls=min(200, args.max_calls))
            if args.earn_history:
                report = EarnSourceCapture(transport, args.output_dir,
                    start_utc_ms=args.start_utc_ms, end_utc_ms=args.end_utc_ms).run(max_calls=min(4,args.max_calls))
            else:
                report = FinancialHistoryCapture(transport, args.output_dir, symbols=symbols,
                    start_utc_ms=args.start_utc_ms, end_utc_ms=args.end_utc_ms).run(
                    max_calls=args.max_calls, daily_snapshot_scopes=1 if args.daily_snapshots else 0)
        print(json.dumps(report, ensure_ascii=True, allow_nan=False))
        return 2 if report['state'] == 'CAPTURE_BLOCKED' else 0
    except (ValueError, OSError, TypeError, KeyError) as error:
        code = str(error)
        import re
        if not isinstance(error, LiveError) or not re.fullmatch('[A-Z0-9_]{1,80}', code):
            code = 'FINANCIAL_CAPTURE_LOCAL_INPUT_ERROR'
        print(json.dumps({'state': 'CAPTURE_BLOCKED', 'reason_codes': [code],
                          'execution_enabled': False, 'financial_authorization': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
