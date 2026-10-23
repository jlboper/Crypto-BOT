"""Explicitly select existing audit evidence for the cached read-only portal.

Does not run an audit, recipe, model, engine or exchange client. Each report is
preserved in a new directory; only its compact, closed latest.json is replaced.
This cache is not financial history, a wallet, permission or strategy promotion.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trader.migration_audit import build_migration_audit, _encode, _unique


def read(path):
    if path is None:
        return None, None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_194_304:
        raise ValueError("BOUNDED_EXISTING_REPORT_REQUIRED")
    with path.open("rb") as handle:
        raw = handle.read(4_194_305)
    if len(raw) > 4_194_304:
        raise ValueError("REPORT_TOO_LARGE")
    return json.loads(raw, object_pairs_hook=_unique), hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--capital", type=Path)
    parser.add_argument("--risk", type=Path)
    parser.add_argument("--evidence", type=Path, help="Closed {joint_reports:[...],cohort:null|existing result}")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Explicit report cache; never a wallet/ledger directory")
    args = parser.parse_args(argv)
    try:
        supplied = {name: read(path) for name, path in (("inventory", args.inventory), ("capital", args.capital),
                                                      ("risk", args.risk), ("evidence", args.evidence))}
        evidence = {"joint_reports": [], "cohort": None} if args.evidence is None else supplied["evidence"][0]
        if type(evidence) is not dict or set(evidence) != {"joint_reports", "cohort"}:
            raise ValueError("CLOSED_EVIDENCE_BUNDLE_REQUIRED")
        version = tomllib.loads((ROOT/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        report = build_migration_audit(version=version, inventory=supplied["inventory"][0],
            capital=supplied["capital"][0], risk=supplied["risk"][0], **evidence)
        root = args.output_dir.resolve()
        if root.name != "migration-audit" or args.output_dir.is_symlink():
            raise ValueError("SEPARATE_MIGRATION_AUDIT_DIRECTORY_REQUIRED")
        root.mkdir(parents=True, exist_ok=True)
        run = root/(datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex)
        run.mkdir(exist_ok=False)
        raw = _encode(report)
        (run/"report.json").write_bytes(raw)
        # Metadata contains only digests, not source paths or financial content.
        provenance = {name: value[1] for name, value in supplied.items() if value[1] is not None}
        (run/"provenance.json").write_bytes(_encode({"schema": 1, "report_sha256": hashlib.sha256(raw).hexdigest(),
                                                    "supplied_file_sha256": provenance}))
        pending = root/(".pending-"+uuid.uuid4().hex+".json")
        with pending.open("xb") as handle:
            handle.write(raw)
        os.replace(pending, root/"latest.json")
        print(json.dumps({"state": "CACHED_READ_ONLY_REPORT", "bytes": len(raw), "at": report["at"],
                          "source_version": version, "execution_enabled": False, "financial_authorization": False}))
        return 0
    except Exception:
        print(json.dumps({"state": "UNAVAILABLE", "error": "REPORT_NOT_PUBLISHED", "execution_enabled": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
