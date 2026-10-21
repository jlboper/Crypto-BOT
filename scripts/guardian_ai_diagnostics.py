"""Read Guardian AI attempt metadata; never call the API or change its journal."""
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',required=True,type=Path)
    parser.add_argument('--limit',type=int,default=8)
    args=parser.parse_args(argv)
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from trader.guardian_ai import guardian_ai_diagnostics
    result=guardian_ai_diagnostics(args.data_dir,limit=args.limit)
    print(json.dumps(result,ensure_ascii=True,allow_nan=False,separators=(',',':')))
    return 1 if result['state']=='UNAVAILABLE' else 0


if __name__=='__main__':
    raise SystemExit(main())
