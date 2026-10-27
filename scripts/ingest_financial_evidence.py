"""Explicit offline financial packet ingestion; no exchange calls or orders."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from trader.financial_evidence import _iso, _time, canonical
from trader.financial_evidence_io import (MAX_ORIGINAL_BYTES, _public,
    ingest_financial_files, read_financial_overlay, read_retained_json)


class ClosedParser(argparse.ArgumentParser):
    def error(self,message):
        raise ValueError('FINANCIAL_INGEST_ARGUMENTS_INVALID')


def main(argv=None):
    coverage_mode=False
    parser=ClosedParser(description='Retain an explicit canonical packet locally; no Binance attestation or financial authorization.')
    parser.add_argument('--registration',type=Path,required=True)
    parser.add_argument('--journal',type=Path,required=True)
    parser.add_argument('--anchor',type=Path,required=True)
    parser.add_argument('--original',type=Path,help='Immutable operational receipt JSON, read only')
    parser.add_argument('--bundle',type=Path,help='Retained canonical financial bundle JSON, read only')
    parser.add_argument('--reconcile-anchor',action='store_true',help='Revalidate the exact single committed packet whose anchor is pending')
    parser.add_argument('--coverage',action='store_true',help='Read-only coverage overlay, never ingestion')
    parser.add_argument('--originals',type=Path,help='Bounded JSON list of retained original receipts for coverage')
    parser.add_argument('--cohort-digest')
    parser.add_argument('--account-ref')
    parser.add_argument('--unit-scale',type=int)
    parser.add_argument('--as-of',help='UTC Z time for read-only coverage; cannot be later than current time')
    try:
        args=parser.parse_args(argv)
        coverage_mode=args.coverage
        actual=_iso(datetime.now(UTC))
        if args.coverage:
            if (args.original is not None or args.bundle is not None or args.reconcile_anchor
                    or args.originals is None or args.cohort_digest is None or args.account_ref is None
                    or args.unit_scale is None):
                raise ValueError('COVERAGE_REFERENCES_REQUIRED')
            asof=args.as_of or actual
            if _time(asof)>_time(actual):raise ValueError('FUTURE_COVERAGE_UNAVAILABLE')
            result=read_financial_overlay(args.journal,args.anchor,
                read_retained_json(args.registration,max_bytes=32768),
                read_retained_json(args.originals,max_bytes=MAX_ORIGINAL_BYTES),now=asof,
                expected_cohort_digest=args.cohort_digest,expected_account_ref=args.account_ref,
                expected_unit_scale=args.unit_scale)
        else:
            if (args.original is None or args.bundle is None or args.originals is not None
                    or args.cohort_digest is not None or args.account_ref is not None
                    or args.unit_scale is not None or args.as_of is not None):
                raise ValueError('EXPLICIT_PACKET_FILES_REQUIRED')
            result=ingest_financial_files(args.registration,args.original,args.bundle,
                journal_path=args.journal,anchor_path=args.anchor,reconcile_anchor=args.reconcile_anchor)
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,OSError):
        result=_public('RETAINED_PACKET_REJECTED')
    print(canonical(result))
    return 0 if result.get('packet_received') or coverage_mode and result.get('journal_verified') else 2


if __name__=='__main__':raise SystemExit(main())
