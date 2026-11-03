"""Print private aggregate evidence; source ledgers are opened read only."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trader.evidence_review import review_retained_evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    result = review_retained_evidence(args.data_dir)
    print(json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2))
    return 0 if result['state'] == 'REVIEWED_WITH_EXPLICIT_GAPS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
