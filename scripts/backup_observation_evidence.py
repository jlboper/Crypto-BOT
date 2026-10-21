"""Create explicit local evidence copies; never restore or restart a trading bot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-data-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path,
                        help='New directory outside the source; parent must exist')
    parser.add_argument('--database', action='append', dest='names',
                        help='Select an allowlisted DB; default is all eight ledgers/journals')
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from trader.evidence_backup import DATABASES, backup_evidence
    result = backup_evidence(args.source_data_dir, args.output_dir,
                             names=args.names if args.names is not None else DATABASES)
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0 if result['state'] == 'VERIFIED_COPIES' else 1


if __name__ == '__main__':
    raise SystemExit(main())
