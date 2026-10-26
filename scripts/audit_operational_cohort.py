"""Read-only audit of retained cohorts and explicitly supplied legacy sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trader.operational_cohort import OperationalCohortStore
from trader.preproduction_observer import SourceSpec, audit_legacy_source


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-database", required=True, type=Path)
    parser.add_argument("--source", action="append", default=[], help="ENGINE,ENVIRONMENT,explicit-sqlite-path")
    parser.add_argument("--retained-anchor", default=None)
    args = parser.parse_args(argv)
    if len(args.source) > 4:
        parser.error("at most four explicit sources")
    now = time.time()
    try:
        sources = []
        for entry in args.source:
            parts = entry.split(",", 2)
            if len(parts) != 3:
                raise ValueError()
            sources.append(SourceSpec(parts[0], parts[1], Path(parts[2])))
        store = OperationalCohortStore(args.cohort_database)
        result = store.snapshot(now=now)
        result["integrity"] = store.verify_chain(expected_anchor=args.retained_anchor)
        result["legacy"] = [audit_legacy_source(source, now=now) for source in sources]
    except Exception:
        print(json.dumps({"state": "UNAVAILABLE", "reason": "INVALID_OR_UNAVAILABLE_AUDIT_INPUT"}))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["integrity"]["state"] == "VALID_LOCAL_CHAIN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
