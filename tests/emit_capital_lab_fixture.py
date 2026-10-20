"""Real closed Lab recipes in new temporary synthetic wallets; no config/env/API."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_capital_lab(*, variant='ready'):
    from trader.capital_protocol_lab import run_capital_protocol_lab, capital_protocol_lab_snapshot
    from trader.capital_manager_shadow import CapitalManagerShadow
    if variant not in {'ready', 'failed', 'not-run', 'corrupt'}:
        raise ValueError('Unknown synthetic capital lab fixture')
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary)/'research'/'capital-lab'
        if variant == 'not-run':
            result = capital_protocol_lab_snapshot(output)
            if output.exists():
                raise AssertionError('Absent lab projection created files')
            return result
        if variant == 'failed':
            with patch.object(CapitalManagerShadow, 'reserve', side_effect=RuntimeError('synthetic protocol interruption')):
                recorded = run_capital_protocol_lab(output)
        else:
            recorded = run_capital_protocol_lab(output)
        if variant == 'corrupt':
            (output/recorded['report_id']/'report.json').write_text('{broken', encoding='utf-8')
        result = capital_protocol_lab_snapshot(output)
        expected = {'ready':'PASSED', 'failed':'FAILED', 'corrupt':'UNAVAILABLE'}[variant]
        if result['state'] != expected:
            raise AssertionError('Real synthetic Lab producer returned unexpected state')
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=('ready','failed','not-run','corrupt'), default='ready')
    args = parser.parse_args()
    print(json.dumps(make_capital_lab(variant=args.variant), ensure_ascii=True, allow_nan=False, separators=(',',':')))
