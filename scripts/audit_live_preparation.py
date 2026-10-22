"""Read a supplied dashboard JSON; never query an engine or exchange."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trader.live_preparation import evaluate_live_preparation, read_proposal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Existing sanitized dashboard JSON")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--proposal-file", help='Optional closed JSON: {"schema":1,"amount_usd":"100"}')
    group.add_argument("--proposed-capital-usd", help="Unfunded proposal only, decimal USD amount")
    parser.add_argument("--now", help="Explicit UTC evaluation time for reproducible inspection")
    args = parser.parse_args()
    try:
        with Path(args.snapshot).open("rb") as stream:
            raw = stream.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Input size limit")
        payload = json.loads(raw)
        if type(payload) is not dict:
            raise ValueError("Dashboard object required")
        proposal = read_proposal(args.proposal_file) if args.proposal_file else (
            {"schema": 1, "amount_usd": args.proposed_capital_usd} if args.proposed_capital_usd is not None else None)
        report = evaluate_live_preparation(payload, proposal, now=args.now)
        if (args.proposal_file or args.proposed_capital_usd is not None) and report["capital_proposal"]["status"] == "NOT_PROVIDED":
            raise ValueError("Invalid explicit proposal")
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        parser.exit(2, "Preparation input unavailable or invalid.\n")
    print(json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
