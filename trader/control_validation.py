"""Reproducible synthetic Risk + existing Capital protocol preparation lab.

No native engine hook or real account adapter exists. The capital portion reuses
the existing transactional protocol recipes in newly named SIM wallets. The risk
portion is pure arithmetic on explicit synthetic assertions. Passing this lab is
not permission to activate Guardian Control or certification of Binance behavior.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import time
import uuid

from . import capital_protocol_lab as capital_lab
from . import global_risk_shadow as risk
from .capital_manager_shadow import AccountScope


MAX_REPORT_BYTES = 80_000
RECIPE_VERSION = "control-preparation-simulation-v1"
VIRTUAL_AT = 1_800_000_000.
U = 1_000_000
AUTHORITY_FIELDS = ("execution_enabled", "controls_enabled", "can_veto", "reservations_enabled", "promotion_allowed")
LIMITATIONS = ["SYNTHETIC_SCENARIOS_NOT_BINANCE_ACCOUNT_OR_EXECUTION_VALIDATION",
    "NO_NATIVE_ENGINE_OR_PROTECTIVE_CLOSE_HOOK",
    "NO_NEW_CAPITAL_PROTOCOL_OR_SHARED_OPERATIONAL_WALLET",
    "PASS_DOES_NOT_CERTIFY_ALL_CONTROL_PRECONDITIONS",
    "SEPARATE_VALIDATION_AND_OWNER_AUTHORIZATION_REQUIRED_FOR_EACH_AUTONOMY_LEVEL",
    "READ_VALIDATES_REPORT_NOT_PERSISTED_WALLETS_OR_ACCOUNT_RECONCILIATION",
    "SNAPSHOT_ASSESSMENT_NOT_PERSISTENT_LOSS_LATCH_OR_PERIOD_RESET",
    "CONSERVATIVE_MARGIN_FLOOR_NOT_BINANCE_MARGIN_OR_LIQUIDATION_CALIBRATION"]


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _fixture():
    # Explicit frozen example policy, not a risk recommendation or owner budget.
    scope = AccountScope("SHADOW", "SIM_RISK_ACCOUNT", "USDT")
    policy = risk.RiskPolicy("SIM_RISK_POLICY", scope, VIRTUAL_AT-3600,
        1000*U, 50*U, 8, 2000,
        (("SIM_SPOT",600*U,40*U),("SIM_QUANT",600*U,40*U)),
        (("BTCUSDT",600*U,30*U),("ETHUSDT",600*U,30*U)),
        (("SIM_CRYPTO_FACTOR",900*U,45*U),), 100*U,200*U,150*U,
        500_000,750_000,2*U,30,20,15)
    existing = risk.Exposure("SIM_EXISTING","SIM_SPOT","BTCUSDT","LONG",100*U,4*U,
        1000,"SIM_CRYPTO_FACTOR",VIRTUAL_AT-1,True)
    inventory = risk.Inventory(scope,VIRTUAL_AT-1,True,True,True,800*U,True,
        0,0,0,True,True,"READY",False,(existing,),())
    leg = risk.Exposure("SIM_NEW","SIM_QUANT","ETHUSDT","SHORT",100*U,3*U,
        1000,"SIM_CRYPTO_FACTOR",VIRTUAL_AT-1,True)
    candidate = risk.Candidate("SIM_CANDIDATE",scope,VIRTUAL_AT-1,(leg,),101*U,10,10,5,True)
    return policy, inventory, candidate


def risk_scenarios():
    """Closed finite scenarios; no state, network, wallet or model dependency."""
    p,i,c = _fixture()
    def inventory(**values):
        return replace(i, **values)
    def candidate(**values):
        return replace(c, **values)
    cases = (
        ("SIM_NORMAL",p,i,c,"NORMAL",True,None),
        ("SIM_CAUTION",p,inventory(daily_pnl_units=-50*U),c,"CAUTION",True,None),
        ("SIM_REDUCED",p,inventory(daily_pnl_units=-75*U),candidate(legs=(replace(c.legs[0],inclusive_stop_risk_units=U),)),"RISK_REDUCED",True,None),
        ("SIM_REDUCED_CAP",p,inventory(daily_pnl_units=-75*U),c,"ENTRY_HALTED",False,"REDUCED_CANDIDATE_RISK_CAP_EXCEEDED"),
        ("SIM_DAILY_HALT",p,inventory(daily_pnl_units=-100*U),c,"ENTRY_HALTED",False,"DAILY_LOSS_LIMIT_REACHED"),
        ("SIM_WEEKLY_HALT",p,inventory(weekly_pnl_units=-200*U),c,"ENTRY_HALTED",False,"WEEKLY_LOSS_LIMIT_REACHED"),
        ("SIM_DRAWDOWN_HALT",p,inventory(drawdown_units=150*U),c,"ENTRY_HALTED",False,"DRAWDOWN_LIMIT_REACHED"),
        ("SIM_UNKNOWN_INVENTORY",p,inventory(inventory_complete=None),c,"RECOVERY_REQUIRED",False,"INVENTORY_INCOMPLETE_OR_UNKNOWN"),
        ("SIM_UNKNOWN_ORDERS",p,inventory(reconciliation_complete=None),c,"RECOVERY_REQUIRED",False,"ORDER_RECONCILIATION_INCOMPLETE_OR_UNKNOWN"),
        ("SIM_UNKNOWN_MARGIN",p,inventory(margin_is_net_of_commitments=None),c,"RECOVERY_REQUIRED",False,"AVAILABLE_MARGIN_UNKNOWN"),
        ("SIM_MISSING_PROTECTION",p,inventory(positions=(replace(i.positions[0],protection_verified=None),)),c,"RECOVERY_REQUIRED",False,"EXISTING_PROTECTION_MISSING_OR_UNKNOWN"),
        ("SIM_DIFFERENT_ENVIRONMENT",p,i,candidate(scope=AccountScope("FUTURES_DEMO","SIM_RISK_ACCOUNT","USDT")),"RECOVERY_REQUIRED",False,"ACCOUNT_OR_ENVIRONMENT_SCOPE_MISMATCH"),
        ("SIM_OPPOSITE_NO_HEDGE",p,i,candidate(legs=(replace(c.legs[0],symbol="BTCUSDT",gross_units=550*U,inclusive_stop_risk_units=28*U),)),"ENTRY_HALTED",False,"ASSET_GROSS_LIMIT_EXCEEDED"),
        ("SIM_PENDING_EXPOSURE",p,inventory(pending=(replace(i.positions[0],exposure_id="SIM_PENDING",gross_units=550*U),)),c,"ENTRY_HALTED",False,"ENGINE_GROSS_LIMIT_EXCEEDED"),
        ("SIM_STALE_DATA",p,inventory(observed_at=VIRTUAL_AT-31),c,"ENTRY_HALTED",False,"STALE_OR_FUTURE_DATA"),
        ("SIM_UNKNOWN_CORRELATION",p,inventory(correlation_evidence_verified=None),c,"RECOVERY_REQUIRED",False,"CORRELATION_GROUP_EVIDENCE_UNVERIFIED"),
        ("SIM_MANUAL_HALT",p,inventory(manual_entry_halt=True),c,"ENTRY_HALTED",False,"MANUAL_ENTRY_HALT"),
        ("SIM_EXECUTION_COSTS",p,i,candidate(estimated_slippage_bps=None),"ENTRY_HALTED",False,"EXECUTION_COSTS_UNKNOWN_OR_EXCESSIVE"),
    )
    results = []
    for identifier, policy, observed, proposal, state, allowed, reason in cases:
        result = risk.assess_risk(policy, observed, proposal, now=VIRTUAL_AT)
        matches = (result["state"] == state and result["hypothetical_admission"] is allowed
            and (reason is None or reason in result["reasons"])
            and all(result[field] is False for field in AUTHORITY_FIELDS))
        results.append({"id":identifier, "expected_state":state, "expected_hypothetical_admission":allowed,
            "required_reason":reason, "matches":matches,
            "input_digest":_digest({"policy":asdict(policy),"inventory":asdict(observed),"candidate":asdict(proposal)}),
            "result_digest":_digest(result), "result":result})
    return results


def _source():
    return {"recipe_version":RECIPE_VERSION,
        "risk_sha256":hashlib.sha256(Path(risk.__file__).read_bytes()).hexdigest(),
        "lab_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "capital_protocol_sha256":hashlib.sha256(Path(capital_lab.protocol.__file__).read_bytes()).hexdigest(),
        "capital_lab_sha256":hashlib.sha256(Path(capital_lab.__file__).read_bytes()).hexdigest()}


def _valid_at(value):
    try:
        if not isinstance(value,str) or not 1 <= len(value) <= 40:
            return False
        parsed = datetime.fromisoformat(value.replace("Z","+00:00"))
        return parsed.tzinfo is not None and 0 < parsed.timestamp() <= time.time()+5
    except (ValueError,OverflowError,OSError):
        return False


def run_control_validation(output_dir):
    root = capital_lab._root(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    run_id = "SIM_"+uuid.uuid4().hex
    run = root/run_id
    run.mkdir(exist_ok=False)
    capital = capital_lab.run_capital_protocol_lab(run/"capital-protocol")
    scenarios = risk_scenarios()
    report = {"schema":1, "engine":"GUARDIAN_CONTROL_PREPARATION", "mode":"SHADOW",
        "synthetic":True, "autonomy_level":0,
        **{field:False for field in AUTHORITY_FIELDS},
        "state":"PASSED" if capital["state"] == "PASSED" and all(row["matches"] for row in scenarios) else "FAILED",
        "report_id":run_id, "at":datetime.fromtimestamp(time.time(),UTC).isoformat(),
        "source_version":_source(), "risk_policy":asdict(_fixture()[0]),
        "risk_scenarios":scenarios, "capital_protocol":capital,
        "limitations":LIMITATIONS.copy(),
        "report_digest":None}
    report["report_digest"] = _digest({key:value for key,value in report.items() if key != "report_digest"})
    raw = _json(report)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("CONTROL_PREPARATION_REPORT_SIZE_LIMIT")
    with (run/"report.json").open("xb") as handle:
        handle.write(raw)
    return json.loads(raw)


def read_control_validation(path):
    """Read and reproduce the same closed risk recipes; never creates a wallet."""
    try:
        path = capital_lab._root(path)
        if not path.is_file():
            return {"schema":1,"state":"NOT_RUN","execution_enabled":False,"controls_enabled":False}
        if path.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError("CONTROL_REPORT_READ_BUDGET")
        raw = path.read_bytes()
        value = json.loads(raw)
        if (not isinstance(value,dict) or _json(value) != raw
                or set(value) != {'schema','engine','mode','synthetic','autonomy_level',*AUTHORITY_FIELDS,
                    'state','report_id','at','source_version','risk_policy','risk_scenarios',
                    'capital_protocol','limitations','report_digest'}
                or type(value.get('schema')) is not int or value['schema'] != 1
                or value.get('engine') != 'GUARDIAN_CONTROL_PREPARATION'
                or not isinstance(value.get('report_id'),str) or not capital_lab.RUN_ID.fullmatch(value['report_id'])
                or not _valid_at(value.get('at'))
                or value.get('limitations') != LIMITATIONS
                or value.get("report_digest") != _digest({key:item for key,item in value.items() if key != "report_digest"})
                or value.get("source_version") != _source()
                or value.get("risk_policy") != json.loads(_json(asdict(_fixture()[0])))
                or value.get("risk_scenarios") != risk_scenarios()
                or value.get("mode") != "SHADOW" or value.get("synthetic") is not True
                or type(value.get("autonomy_level")) is not int or value["autonomy_level"] != 0
                or any(value.get(field) is not False for field in AUTHORITY_FIELDS)
                or not capital_lab._valid_report(value.get("capital_protocol"))
                or value['capital_protocol']['source_version'] != capital_lab._source_version()):
            raise ValueError("CONTROL_REPORT_VERIFICATION_FAILED")
        expected = ("PASSED" if value["capital_protocol"]["state"] == "PASSED"
                    and all(row["matches"] for row in value["risk_scenarios"]) else "FAILED")
        if value.get("state") != expected:
            raise ValueError("CONTROL_REPORT_RESULT_MISMATCH")
        return value
    except Exception:
        return {"schema":1,"state":"UNAVAILABLE","execution_enabled":False,"controls_enabled":False}
