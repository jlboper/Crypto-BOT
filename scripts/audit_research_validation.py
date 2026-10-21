"""Read existing research/Quant evidence without starting services or providers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
MAX_REPORT_BYTES = 16 * 1024 * 1024


def main(argv=None):
    sys.path.insert(0, str(ROOT))
    from trader.quant_research import quant_research_evidence
    from trader.research_validation import build_validation_summary
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data')
    parser.add_argument('--research-report', type=Path,
                        help='Existing archived/latest report (default: data-dir/research/latest.json)')
    args = parser.parse_args(argv)
    path = args.research_report or args.data_dir/'research'/'latest.json'
    report = {}
    unavailable = False
    if path.is_file():
        try:
            if path.stat().st_size > MAX_REPORT_BYTES:
                raise ValueError('Research read budget exceeded')
            report = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(report, dict):
                raise ValueError('Invalid research report')
        except Exception:
            report, unavailable = {}, True
    # A current Quant audit is reported separately; an archived run's attached
    # evidence is never rewritten to pretend that new information existed then.
    result = {'validation_summary': build_validation_summary(report),
              'current_quant_audit': quant_research_evidence(args.data_dir),
              'research_read_state': 'UNAVAILABLE' if unavailable else 'READ' if report else 'NOT_STARTED'}
    print(json.dumps(result, ensure_ascii=True, separators=(',', ':'), allow_nan=False))
    return 1 if unavailable or result['current_quant_audit']['state'] == 'UNAVAILABLE' else 0


if __name__ == '__main__':
    raise SystemExit(main())
