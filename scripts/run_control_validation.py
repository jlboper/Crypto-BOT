"""Run explicit SIM risk/capital recipes, or verify a completed report read-only."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    sys.path.insert(0,str(ROOT))
    from trader.control_validation import read_control_validation, run_control_validation
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'data'/'research'/'control-validation')
    parser.add_argument('--read-report',type=Path,
                        help='Verify one existing report; do not create a directory or wallet')
    args = parser.parse_args(argv)
    value = read_control_validation(args.read_report) if args.read_report else run_control_validation(args.output_dir)
    # Full synthetic inputs/results are retained in the immutable run artifact.
    result = {key:value.get(key) for key in ('schema','engine','mode','synthetic','autonomy_level',
        'state','report_id','report_digest','execution_enabled','controls_enabled')}
    result.update(risk_scenarios=len(value.get('risk_scenarios',[])),
        risk_matches=sum(row['matches'] for row in value.get('risk_scenarios',[])),
        capital_scenarios=len(value.get('capital_protocol',{}).get('scenarios',[])),
        capital_state=value.get('capital_protocol',{}).get('state'))
    print(json.dumps(result,ensure_ascii=True,separators=(',',':'),allow_nan=False))
    return 0 if value['state'] in {'PASSED','NOT_RUN'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
