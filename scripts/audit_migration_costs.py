"""Read explicit independent sizing scenarios; no account, credentials or API."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
MAX_FILE_BYTES = 16_384


def _unique(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _number(value):
    if len(value) > 80:
        raise ValueError("JSON_NUMBER_BOUNDS")
    return Decimal(value)


def _integer(value):
    if len(value) > 80:
        raise ValueError("JSON_NUMBER_BOUNDS")
    return int(value)


def _invalid_constant(_value):
    raise ValueError("NONSTANDARD_JSON_NUMBER")


def main(argv=None):
    sys.path.insert(0,str(ROOT))
    from trader.migration_costs import OrderCostScenario, SCENARIO_KEYS, evaluate_order_costs
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',type=Path,required=True,
        help='Existing JSON: schema=1, mode=INDEPENDENT_SIMULATIONS, items=1..4 complete scenarios')
    args = parser.parse_args(argv)
    report = {"schema":1,"mode":"READ_ONLY_MATHEMATICAL_AUDIT","state":"INVALID_INPUT",
        "execution_enabled":False,"financial_authorization":False,"promotion_allowed":False,
        "independent_scenarios":True,"simultaneous_funding_evaluated":False,"items":[],"error":None}
    try:
        if not args.scenario.is_file() or args.scenario.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("SCENARIO_FILE_BOUNDS")
        with args.scenario.open('rb') as handle:
            raw=handle.read(MAX_FILE_BYTES+1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("SCENARIO_FILE_BOUNDS")
        value=json.loads(raw,object_pairs_hook=_unique,parse_float=_number,
                         parse_int=_integer,parse_constant=_invalid_constant)
        if (not isinstance(value,dict) or set(value) != {'schema','mode','items'}
                or type(value['schema']) is not int or value['schema'] != 1
                or value['mode'] != 'INDEPENDENT_SIMULATIONS'
                or not isinstance(value['items'],list) or not 1 <= len(value['items']) <= 4
                or any(not isinstance(item,dict) or set(item) != set(SCENARIO_KEYS) for item in value['items'])):
            raise ValueError("CLOSED_SCENARIO_SCHEMA_REQUIRED")
        report['items']=[evaluate_order_costs(OrderCostScenario(**item)) for item in value['items']]
        report['state']='HYPOTHESES_EVALUATED'
    except Exception:
        report['error']='SCENARIO_INPUT_UNAVAILABLE_OR_INVALID'
        print(json.dumps(report,ensure_ascii=True,separators=(',',':'),allow_nan=False))
        return 2
    print(json.dumps(report,ensure_ascii=True,separators=(',',':'),allow_nan=False))
    return 0 if all(item['feasible_hypothesis'] for item in report['items']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
