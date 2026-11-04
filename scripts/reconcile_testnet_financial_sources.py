"""Offline diagnostics of encrypted Testnet/Demo originals; no credentials or GETs."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trader.financial_evidence import AUTHORITY
from trader.testnet_financial_replay import replay_retained_windows


class ClosedParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'TESTNET_REPLAY_ARGUMENTS_INVALID\n')


def main(argv=None):
    parser = ClosedParser(description=__doc__)
    parser.add_argument('--source-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--max-windows', type=int, default=100)
    args = parser.parse_args(argv)
    try:
        result = replay_retained_windows(args.source_dir,args.output_dir,max_windows=args.max_windows)
    except (OSError, ValueError, TypeError, KeyError):
        result = {'state':'RETAINED_SOURCE_REPLAY_BLOCKED', 'reason_codes':['TESTNET_REPLAY_INPUT_INVALID'], **AUTHORITY}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 2 if result['state'] != 'RETAINED_SOURCE_DIAGNOSTICS_WRITTEN' else 0


if __name__ == '__main__':
    raise SystemExit(main())
