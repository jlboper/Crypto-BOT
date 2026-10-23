"""Run fixed synthetic loss-latch recovery recipes in a NEW isolated directory.

No existing wallet is accepted, no operating data is read, no provider/AI client
is constructed. The numerical limits are fixture hypotheses, not owner policy.
This report is a software rehearsal, never account or LIVE-readiness evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trader.capital_manager_shadow import AccountScope
from trader.risk_latches_shadow import (
    CashflowObservation, EquityObservation, LossLatchPolicy, PeriodBaseline, RiskLatchesShadow,
)


_AT = datetime(2026, 10, 26, 12, tzinfo=UTC).timestamp()
_DAY = _AT-12*3600
_U = 1_000_000


def _check(condition, reason):
    if not condition:
        raise AssertionError(reason)


class _Scenario:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir()
        self.at = _AT
        self.scope = AccountScope("SHADOW", "SIM_REHEARSAL_ACCOUNT", "USDT")
        self.policy = LossLatchPolicy("SIM_REHEARSAL_POLICY", self.scope, "SIM_FIXTURE_ACTOR", _AT-1,
                                      50*_U, 100*_U, 150*_U, 120)
        self.manager = self.reopen()

    def reopen(self, *, fault_hook=None):
        manager = RiskLatchesShadow(self.directory/"SIM_RISK_REHEARSAL.simulation.sqlite3",
                                   wallet_name="SIM_RISK_REHEARSAL", policy=self.policy,
                                   clock=lambda: self.at, fault_hook=fault_hook)
        manager.initialize()
        return manager

    def base(self, period="DAY", *, start=_DAY, equity=1000*_U):
        return PeriodBaseline(period, start, equity, "SIM_BASE_"+period+str(int(start)), True)

    def observation(self, *, equity=1000*_U, flows=0, baselines=None, inventory=True):
        observation = EquityObservation(self.scope, "SIM_OBSERVER", "SIM_EQUITY_EVIDENCE", self.at,
                                 equity, flows, True, inventory, True, True,
                                 (self.base(), self.base("WEEK")) if baselines is None else baselines)
        return replace(observation, evidence_id="SIM_EQ_"+hashlib.sha256(repr(observation).encode()).hexdigest()[:50])

    def observe(self, event, **kwargs):
        return self.manager.observe(event, self.observation(**kwargs))

    def flow(self, amount, evidence="SIM_CASHFLOW_EVIDENCE"):
        return CashflowObservation(self.scope, "SIM_FLOW_OBSERVER", evidence, self.at, amount, True)

    def acknowledge(self, event="SIM_ACK", target="RECOVERY"):
        return self.manager.acknowledge(event, actor="SIM_REVIEWER", evidence_id="SIM_REVIEW_EVIDENCE", target=target)

    def require_clear(self, expected):
        _check(self.manager.snapshot()["loss_gate_clear"] is expected, "UNEXPECTED_LOSS_GATE")


def _daily_rollover(scenario):
    scenario.observe("SIM_DAILY_LIMIT", equity=950*_U)
    scenario.require_clear(False)
    scenario.at += 86400
    scenario.require_clear(False)
    scenario.observe("SIM_MISSING_BASELINE", equity=950*_U, baselines=())
    scenario.observe("SIM_NEW_DAY", equity=950*_U,
                     baselines=(scenario.base(start=_DAY+86400, equity=950*_U),))
    scenario.require_clear(False)
    _check(scenario.acknowledge()["recorded"], "RECOVERY_ACK_FAILED")
    scenario.require_clear(True)
    _check(scenario.manager.snapshot()["weekly_loss_units"] == 50*_U, "WEEKLY_HISTORY_LOST")


def _weekly_rollover(scenario):
    scenario.observe("SIM_WEEKLY_LIMIT", equity=900*_U)
    scenario.at += 86400
    scenario.observe("SIM_NEXT_DAY", equity=900*_U,
                     baselines=(scenario.base(start=_DAY+86400, equity=900*_U),))
    _check("WEEKLY_LOSS_LATCH" in scenario.manager.snapshot()["reasons"], "WEEKLY_LATCH_CLEARED_EARLY")
    scenario.at = _AT+7*86400
    scenario.require_clear(False)
    scenario.observe("SIM_NEXT_WEEK", equity=900*_U,
                     baselines=(scenario.base(start=_DAY+7*86400, equity=900*_U),
                                scenario.base("WEEK", start=_DAY+7*86400, equity=900*_U)))
    scenario.require_clear(True)


def _cashflow_neutrality(scenario):
    scenario.observe("SIM_INITIAL")
    scenario.at += 1
    scenario.manager.record_cashflow("SIM_DEPOSIT", scenario.flow(100*_U))
    scenario.observe("SIM_AFTER_DEPOSIT", equity=1100*_U, flows=100*_U)
    scenario.at += 1
    scenario.manager.record_cashflow("SIM_WITHDRAWAL", scenario.flow(-50*_U, "SIM_WITHDRAWAL_EVIDENCE"))
    scenario.observe("SIM_AFTER_WITHDRAWAL", equity=1050*_U, flows=50*_U)
    state = scenario.manager.snapshot()
    _check(state["cashflow_adjusted_equity_units"] == 1000*_U and state["drawdown_units"] == 0,
           "CASHFLOW_COUNTED_AS_PERFORMANCE")
    scenario.require_clear(True)


def _incomplete_recovery(scenario):
    scenario.observe("SIM_INITIAL")
    scenario.observe("SIM_INCOMPLETE", inventory=False)
    _check(not scenario.acknowledge("SIM_PREMATURE_ACK")["recorded"], "UNKNOWN_EVIDENCE_ACKNOWLEDGED")
    scenario.at += 1
    scenario.observe("SIM_VERIFIED_AGAIN")
    scenario.require_clear(False)
    _check(scenario.acknowledge()["recorded"], "EXPLICIT_RECOVERY_FAILED")
    scenario.require_clear(True)


def _drawdown_manual_restart(scenario):
    scenario.observe("SIM_DRAWDOWN", equity=800*_U)
    scenario.manager.set_manual_halt("SIM_OWNER_HALT", actor="SIM_OWNER", evidence_id="SIM_MANUAL_EVIDENCE")
    scenario.manager = scenario.reopen()
    _check("MANUAL_LATCH" in scenario.manager.snapshot()["reasons"], "MANUAL_HALT_LOST_AFTER_RESTART")
    scenario.at += 1
    scenario.manager.record_cashflow("SIM_NEW_DEPOSIT", scenario.flow(1000*_U))
    scenario.observe("SIM_EQUITY_WITH_DEPOSIT", equity=1800*_U, flows=1000*_U)
    _check(scenario.manager.snapshot()["drawdown_units"] == 200*_U, "DEPOSIT_ERASED_DRAWDOWN")
    _check(not scenario.acknowledge(target="DRAWDOWN")["recorded"], "ACTIVE_DRAWDOWN_RESET")
    scenario.require_clear(False)


def _lost_commit_acknowledgement(scenario):
    def fail(stage):
        if stage == "AFTER_COMMIT":
            raise RuntimeError("SYNTHETIC_LOST_ACKNOWLEDGEMENT")
    manager = scenario.reopen(fault_hook=fail)
    observation = scenario.observation(equity=950*_U)
    lost = False
    try:
        manager.observe("SIM_COMMITTED", observation)
    except RuntimeError:
        lost = True
    _check(lost, "FAULT_NOT_EXERCISED")
    scenario.manager = scenario.reopen()
    _check(scenario.manager.observe("SIM_COMMITTED", observation)["recorded"], "RETRY_FAILED")
    _check(scenario.manager.snapshot()["event_count"] == 1, "DUPLICATED_COMMIT")
    scenario.require_clear(False)


def _concurrent_deduplication(scenario):
    scenario.observe("SIM_INITIAL")
    scenario.at += 1
    managers = [scenario.reopen(), scenario.reopen()]
    barrier = threading.Barrier(3)
    results, errors = [], []
    flow = scenario.flow(100*_U)
    def worker(manager):
        try:
            barrier.wait(timeout=10)
            results.append(manager.record_cashflow("SIM_CONCURRENT_FLOW", flow))
        except BaseException as error:
            errors.append(type(error).__name__)
    threads = [threading.Thread(target=worker, args=(manager,)) for manager in managers]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=10)
    for thread in threads:
        thread.join(10)
    _check(not any(thread.is_alive() for thread in threads) and not errors, "CONCURRENT_REHEARSAL_FAILED")
    _check(len(results) == 2 and results[0] == results[1], "IDEMPOTENCY_RECEIPTS_DIFFER")
    _check(scenario.manager.snapshot()["cumulative_net_cashflow_units"] == 100*_U, "DOUBLE_BOOKED_CASHFLOW")


def _immutable_baseline(scenario):
    scenario.observe("SIM_LOSS", equity=940*_U)
    scenario.at += 1
    result = scenario.observe("SIM_CHANGED_BASELINE", equity=940*_U,
                              baselines=(scenario.base(equity=940*_U), scenario.base("WEEK")))
    _check(not result["recorded"], "BASELINE_REWRITE_ACCEPTED")
    scenario.observe("SIM_ORIGINAL_BASELINE", equity=940*_U)
    _check(not scenario.acknowledge()["recorded"], "DISPUTED_HISTORY_RESET")
    scenario.require_clear(False)


def _clock_regression(scenario):
    scenario.observe("SIM_INITIAL")
    scenario.at += 10
    scenario.observe("SIM_NEWER")
    scenario.at -= 5
    _check(not scenario.observe("SIM_REGRESSION")["recorded"], "CLOCK_REGRESSION_ACCEPTED")
    scenario.at += 6
    scenario.manager = scenario.reopen()
    scenario.require_clear(False)
    scenario.observe("SIM_CLOCK_RESTORED")
    _check(scenario.acknowledge()["recorded"], "CLOCK_RECOVERY_FAILED")
    scenario.require_clear(True)


_RECIPES = (
    ("DAILY_VERIFIED_ROLLOVER", _daily_rollover),
    ("WEEKLY_VERIFIED_ROLLOVER", _weekly_rollover),
    ("CASHFLOW_NEUTRALITY", _cashflow_neutrality),
    ("INCOMPLETE_EVIDENCE_RECOVERY", _incomplete_recovery),
    ("DRAWDOWN_MANUAL_RESTART", _drawdown_manual_restart),
    ("LOST_COMMIT_ACKNOWLEDGEMENT", _lost_commit_acknowledgement),
    ("CONCURRENT_CASHFLOW_DEDUPLICATION", _concurrent_deduplication),
    ("IMMUTABLE_BASELINE_DISPUTE", _immutable_baseline),
    ("CLOCK_REGRESSION_RECOVERY", _clock_regression),
)


def run_rehearsal(directory):
    """Create a fresh cohort tree and report; existing directories are rejected."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.parent.is_dir():
        raise ValueError("NEW_EXISTING_PARENT_SIMULATION_DIRECTORY_REQUIRED")
    directory.mkdir(exist_ok=False)
    cases = []
    for name, recipe in _RECIPES:
        error_code, state, integrity = None, "UNKNOWN", False
        try:
            scenario = _Scenario(directory/name.lower())
            recipe(scenario)
            state = scenario.manager.snapshot()["state"]
            path = scenario.manager.path
            db = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True)
            try:
                integrity = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            finally:
                db.close()
            _check(integrity, "SQLITE_INTEGRITY_FAILED")
        except Exception as error:
            # Only fixture assertion codes are exposed; no filesystem details.
            error_code = str(error) if isinstance(error, AssertionError) else type(error).__name__
        cases.append({"scenario": name, "passed": error_code is None, "final_state": state,
                      "sqlite_quick_check": integrity, "error_code": error_code})
    passed = sum(row["passed"] for row in cases)
    report = {"schema": 1, "engine": "RISK_LATCHES_REHEARSAL", "mode": "SYNTHETIC_ONLY",
              "recipe_version": "risk-latches-shadow-recipes-v1",
              "generated_at": datetime.now(UTC).isoformat(), "simulation_at": datetime.fromtimestamp(_AT, UTC).isoformat(),
              "state": "PASS" if passed == len(cases) else "FAIL", "scenario_count": len(cases),
              "passed_count": passed, "failed_count": len(cases)-passed, "scenarios": cases,
              "policy_source": "FIXED_SYNTHETIC_FIXTURES_NOT_OWNER_POLICY", "operational_evidence": False,
              "fixture_limits_micro_usdt": {"starting_equity": 1000*_U, "daily_loss": 50*_U,
                                             "weekly_loss": 100*_U, "drawdown": 150*_U},
              "owner_capital_used": False, "engine_started": False, "provider_calls": 0, "ai_calls": 0,
              "admission_authority": False, "execution_enabled": False, "live_implemented": False,
              "promotion_allowed": False, "protective_exits_intercepted": False,
              "limitations": ["SIMULATION_INPUT_ASSERTIONS_ONLY", "NOT_EXCHANGE_RECONCILIATION",
                              "NOT_FULL_RISK_ADMISSION", "NO_ENGINE_ADMISSION_INTEGRATION",
                              "NOT_WINDOWS_POWER_FAILURE_OR_ROLLBACK_CERTIFICATION",
                              "OBSERVED_HIGH_WATER_NOT_CONTINUOUS_EXCHANGE_VALUATION",
                              "SQLITE_TRANSACTIONS_NOT_TAMPER_PROOF_STATE"]}
    source_root = Path(__file__).resolve().parent.parent
    report["source_sha256"] = {
        "recipe": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "risk_latches": hashlib.sha256((source_root/"trader"/"risk_latches_shadow.py").read_bytes()).hexdigest(),
        "capital_scope_types": hashlib.sha256((source_root/"trader"/"capital_manager_shadow.py").read_bytes()).hexdigest(),
    }
    (directory/"report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True)+"\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path,
                        help="New directory under an existing writable parent; never an existing wallet directory")
    args = parser.parse_args()
    try:
        report = run_rehearsal(args.directory)
    except (OSError, ValueError):
        parser.exit(2, "New isolated simulation directory could not be created; no existing wallet is accepted.\n")
    print(json.dumps({"state": report["state"], "scenario_count": report["scenario_count"],
                      "passed_count": report["passed_count"], "failed_count": report["failed_count"],
                      "report": str(args.directory/"report.json"), "admission_authority": False,
                      "execution_enabled": False}, ensure_ascii=True))
    return 0 if report["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
