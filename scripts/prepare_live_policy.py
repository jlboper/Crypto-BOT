"""Prepare a new inactive review JSON; cannot grant trading authority."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from trader.live_policy_review import _FALSE,canonical,prepare_live_policy_file


class ClosedParser(argparse.ArgumentParser):
    def error(self,message):raise ValueError('LIVE_POLICY_REVIEW_ARGUMENTS_INVALID')


def main(argv=None):
    parser=ClosedParser(description='Create only a new inactive numerical review template; no activation or active configuration.')
    parser.add_argument('--review',type=Path,required=True,help='Explicit reviewed JSON source, read only')
    parser.add_argument('--output',type=Path,required=True,help='New separate JSON review artifact; never overwrite')
    try:
        args=parser.parse_args(argv)
        result=prepare_live_policy_file(args.review,args.output)
        code=0
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,OSError):
        result={'state':'INACTIVE_REVIEW_NOT_CREATED',**{key:False for key in _FALSE}}
        code=2
    print(canonical(result))
    return code


if __name__=='__main__':raise SystemExit(main())
