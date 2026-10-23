"""Run closed, synthetic risk/reserve/recovery recipes in a NEW output directory.

Recipe funding is 1000 fictitious USDT, unrelated to the owner's 100 USD proposal.
No configuration, account, credentials, engine, broker or model is accessed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trader.capital_manager_shadow import AccountScope, LegRequest, ReconciliationEvent, ReservationRequest, SimulationLimits
from trader.capital_flow_shadow import APP, Admission, CapitalFlowShadow, LIMITATIONS, _authority
from trader.global_risk_shadow import Candidate, Exposure, Inventory, RiskPolicy


U = 1_000_000
VIRTUAL_AT = 1_800_000_000.
RECIPE_VERSION = 'capital-flow-shadow-recipes-v1'


class _Clock:
    def __init__(self): self.value = VIRTUAL_AT
    def __call__(self): return self.value


def run_recipes(output_dir):
    directory = Path(output_dir)
    if directory.is_symlink() or not directory.parent.is_dir():
        raise ValueError('NEW_OUTPUT_DIRECTORY_WITH_EXISTING_PARENT_REQUIRED')
    directory.mkdir(exist_ok=False)  # Never reopen or overwrite a previous run.
    checks, cases = [], []
    for name in ('SIM_FLOW_CONCURRENT', 'SIM_FLOW_RECOVERY', 'SIM_FLOW_PARTIAL'):
        clock = _Clock()
        scope = AccountScope('SHADOW', name, 'USDT')
        capital = SimulationLimits('SIM_CAPITAL_RECIPE_V1', 'SIM_RECIPE_AUTHOR', VIRTUAL_AT,
            'EXPLICIT_NEW_SIMULATION_COHORT', 1000*U, 900*U, 900*U, 900*U, 30*U,
            (('SIM_SPOT', 900*U, 30*U), ('SIM_FUTURES', 900*U, 30*U)), 120, 10)
        risk = RiskPolicy('SIM_RISK_RECIPE_V1', scope, VIRTUAL_AT, 600*U, 30*U, 10, 2000,
            (('SIM_SPOT', 600*U, 30*U), ('SIM_FUTURES', 600*U, 30*U)),
            (('BTCUSDT', 600*U, 30*U), ('ETHUSDT', 600*U, 30*U)),
            (('SIM_CRYPTO_FACTOR', 600*U, 30*U),), 100*U, 200*U, 150*U,
            500000, 750000, 2*U, 30, 20, 15)
        def new_manager():
            return CapitalFlowShadow(directory/(name+'.simulation.sqlite3'), wallet_name=name,
                scope=scope, limits=capital, risk_policy=risk, clock=clock)
        def proposal(identifier='SIM_REQUEST_A', strategy='SIM_SPOT', symbol='BTCUSDT', principal=100*U):
            leg_id = 'SIM_LEG_'+identifier[4:]
            leg = LegRequest(leg_id, symbol, 'LONG',
                'SPOT_REFERENCE' if strategy == 'SIM_SPOT' else 'FUTURES_REFERENCE', principal, 2*U, 5*U)
            request = ReservationRequest(identifier, scope, strategy, capital.policy_id, (leg,), clock()+60)
            exposure = Exposure(leg_id, strategy, symbol, 'LONG', principal, 5*U, 1000,
                'SIM_CRYPTO_FACTOR', clock(), True)
            candidate = Candidate(identifier, scope, clock(), (exposure,), principal+2*U, 10, 10, 5, True)
            inventory = Inventory(scope, clock(), True, True, True, 1000*U, True,
                0, 0, 0, True, True, 'READY', False, (), ())
            return Admission(request, candidate, inventory)
        def event(identifier, state, filled, entry, *, exit_fee=0, pnl=0, closed=False):
            return ReconciliationEvent(identifier, scope, 'SIM_REQUEST_A', 'SIM_LEG_REQUEST_A',
                'SIM_RECONCILER', state, filled, entry, exit_fee, pnl, closed, clock(), True)
        def check(code, actual, expected):
            checks.append({'case': name, 'code': code, 'actual': actual, 'expected': expected,
                           'passed': type(actual) is type(expected) and actual == expected})
        flow = new_manager(); flow.initialize()
        if name == 'SIM_FLOW_CONCURRENT':
            gate = threading.Barrier(2)
            proposals = (proposal(principal=400*U),
                proposal('SIM_REQUEST_B', 'SIM_FUTURES', 'ETHUSDT', 400*U))
            def compete(item):
                peer = new_manager(); peer.initialize(); gate.wait(timeout=5)
                return peer.admit(item)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(compete, proposals))
            check('ONE_ATOMIC_RISK_RESERVATION', sum(x['accepted'] for x in results), 1)
            check('NO_DOUBLE_CAPITAL', flow.snapshot()['reserved_units'], 402*U)
            rejected = next(x for x in results if not x['accepted'])
            check('DURABLE_PREVIOUS_GROSS_INCLUDED', rejected['risk']['before']['gross_units'], 400*U)
        else:
            flow.admit(proposal())
            first_receipt = flow.claim_submission('SIM_REQUEST_A', actor='SIM_CLAIMANT')
            if name == 'SIM_FLOW_RECOVERY':
                clock.value += 3600
                flow = new_manager(); flow.initialize()
                flow.recover('SIM_RECOVERY', actor='SIM_RECOVERY_ACTOR')
                replay = flow.claim_submission('SIM_REQUEST_A', actor='SIM_CLAIMANT')
                check('STABLE_RECEIPT_AFTER_RESTART', replay['synthetic_receipt'], first_receipt['synthetic_receipt'])
                check('UNKNOWN_NOT_RELEASED_BY_TTL', flow.snapshot()['reserved_units'], 102*U)
                check('UNKNOWN_STATE', flow.snapshot()['requests'][0]['state'], 'UNKNOWN')
                flow.reconcile(event('SIM_LATE_CANCEL', 'CANCELLED', 0, 0))
                check('RELEASE_ONLY_AFTER_CONFIRMED_CANCEL', flow.snapshot()['reserved_units'], 0)
            else:
                flow.reconcile(event('SIM_PARTIAL', 'PARTIAL', 40*U, 400000))
                flow.request_cancel('SIM_CANCEL', 'SIM_REQUEST_A', actor='SIM_CANCEL_ACTOR')
                flow.reconcile(event('SIM_PARTIAL_CANCEL', 'CANCELLED', 40*U, 400000))
                check('PARTIAL_CAPITAL_RETAINED', flow.snapshot()['committed_units'], 40*U)
                check('EXIT_COST_RETAINED', flow.snapshot()['reserved_units'], 1600000)
                close = event('SIM_CLOSE', 'CLOSED', 40*U, 400000, exit_fee=400000, pnl=-2*U, closed=True)
                flow.reconcile(close); flow.reconcile(close)
                check('NET_BOOK_INCLUDES_LOSS_AND_BOTH_FEES', flow.snapshot()['book_equity_units'], 997200000)
                check('DUPLICATE_TERMINAL_NOT_DOUBLE_CHARGED', flow.snapshot()['fees_paid_units'], 800000)
            check('SINGLE_DURABLE_CLAIM', flow.snapshot()['synthetic_submission_claim_count'], 1)
        snapshot = flow.snapshot()
        check('EXACT_BOOK_CONSERVATION', snapshot['book_equity_units'],
            snapshot['free_units_signed']+snapshot['reserved_units']+snapshot['committed_units'])
        cases.append({'id': name, 'capital_policy': asdict(capital), 'risk_policy': asdict(risk),
                      'final': snapshot})
    report = {'schema': 1, 'app': APP, 'recipe_version': RECIPE_VERSION,
        'recipe_time_utc_seconds': VIRTUAL_AT, 'state': 'PASSED' if all(x['passed'] for x in checks) else 'FAILED',
        'fictitious_funding_units_per_case': 1000*U, 'unit': 'MICRO_USDT',
        'owner_capital_used': False, 'engine_started': False, 'provider_calls': 0, 'ai_calls': 0,
        'checks': checks, 'cases': cases, 'limitations': list(LIMITATIONS), **_authority()}
    report['source_sha256'] = {
        'recipe': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'flow': hashlib.sha256((ROOT/'trader'/'capital_flow_shadow.py').read_bytes()).hexdigest(),
        'capital': hashlib.sha256((ROOT/'trader'/'capital_manager_shadow.py').read_bytes()).hexdigest(),
        'risk': hashlib.sha256((ROOT/'trader'/'global_risk_shadow.py').read_bytes()).hexdigest()}
    encoded = json.dumps(report, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    with (directory/'report.json').open('x', encoding='utf-8') as handle:
        handle.write(encoded+'\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path,
                        help='New, nonexisting directory under an existing parent; never an operating data folder')
    args = parser.parse_args(argv)
    try:
        report = run_recipes(args.output_dir)
    except (ValueError, OSError) as exc:
        print(json.dumps({'state': 'NOT_COMPLETED', 'error_type': type(exc).__name__, **_authority()}))
        return 2
    print(json.dumps({'state': report['state'], 'checks': len(report['checks']),
                      'passed': sum(x['passed'] for x in report['checks']), **_authority()}))
    return 0 if report['state'] == 'PASSED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
