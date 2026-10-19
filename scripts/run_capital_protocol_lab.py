"""Run closed synthetic capital scenarios; never connect a trading account."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    # Importing this CLI never initializes a wallet, starts a server or reads keys.
    sys.path.insert(0, str(ROOT))
    from trader.capital_protocol_lab import (
        _json, capital_protocol_lab_snapshot, run_capital_protocol_lab,
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT/'data'/'research'/'capital-lab',
                        help='Separate synthetic run/report directory (default: data/research/capital-lab)')
    parser.add_argument('--read-only', action='store_true',
                        help='Read the last completed JSON report without opening or creating any wallet')
    args = parser.parse_args(argv)
    value = (capital_protocol_lab_snapshot(args.output_dir) if args.read_only
             else run_capital_protocol_lab(args.output_dir))
    print(_json(value).decode('ascii'))
    return 0 if value['state'] in {'PASSED', 'NOT_RUN'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
