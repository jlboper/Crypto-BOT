"""Publish local technical-test evidence, never a financial readiness permit.

Requires a successful full offline run against the exact current sources. The
output cannot create authorization.dpapi/readiness.dpapi or alter configuration.
"""
from __future__ import annotations
import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trader.preproduction_status import PACKAGE_IDS, SOURCE_REQUIREMENTS


def technical_report(test_report, *, source=ROOT):
    source = Path(source).resolve()
    if (type(test_report) is not dict or test_report.get("passed") is not True
            or test_report.get("source_unchanged") is not True
            or test_report.get("external_network") != "blocked" or test_report.get("fixtures") != "synthetic"
            or test_report.get("bot_started") is not False or test_report.get("failures") != 0
            or test_report.get("errors") != 0 or type(test_report.get("tests")) is not int or test_report["tests"] < 1200
            or type(test_report.get("source_hashes")) is not dict):
        raise ValueError("EXACT_FULL_OFFLINE_TEST_REPORT_REQUIRED")
    tested = test_report["source_hashes"]
    required = {"trader/" + name for files in SOURCE_REQUIREMENTS.values() for name in files}
    required.update({"trader/engine.py", "trader/preproduction_runtime.py", "trader/live_authorization.py",
                     "tests/test_central_admission.py", "tests/test_live_execution_runtime.py",
                     "tests/test_preproduction_runtime.py", "tests/test_preproduction_status.py"})
    for name in required:
        digest = hashlib.sha256((source/name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if tested.get(name) != digest:
            raise ValueError("TESTED_SOURCE_CHANGED_OR_OMITTED")
    version = tomllib.loads((source/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    return {"schema": 1, "at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "source_version": version, "packages": [{"id": name,
                "state": "IMPLEMENTED_NOT_VALIDATED" if name == "EXECUTION" else "TESTED_PREPARED"} for name in PACKAGE_IDS],
            "source_hashes": {key: tested[key] for key in sorted(required)
                               if key in {"trader/"+name for files in SOURCE_REQUIREMENTS.values() for name in files}}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-report', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--ack-local-write', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        if args.test_report.stat().st_size > 1_048_576:
            raise ValueError()
        report = technical_report(json.loads(args.test_report.read_text(encoding='utf-8')))
        target = args.data_dir.resolve()/"live-preproduction/technical-status.json"
        if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in (target, *target.parents)):
            raise ValueError()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        with temporary.open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(report, ensure_ascii=True, allow_nan=False))
        temporary.replace(target)
        print(json.dumps({"state": "TECHNICAL_TESTS_RECORDED", "execution_enabled": False,
                          "financial_readiness_certified": False}))
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        print('TECHNICAL_EVIDENCE_UNAVAILABLE', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
