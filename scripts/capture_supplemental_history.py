"""Explicit existing-Spot-key collateral/dividend GETs; no trading or authority."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from trader.financial_capture import SupplementalHistoryCapture,COLLATERAL_HISTORY,DIVIDEND_HISTORY
from trader.live_credentials import LiveCredentialVault
from trader.live_transport import LiveError,LiveReadOnlyTransport


class ClosedParser(argparse.ArgumentParser):
    def error(self,message):
        self.exit(2,'SUPPLEMENTAL_CAPTURE_ARGUMENTS_INVALID\n')


def main(argv=None):
    parser=ClosedParser(description=__doc__)
    parser.add_argument('--ack-read-only',required=True,action='store_true')
    parser.add_argument('--vault',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--start-utc-ms',required=True,type=int)
    parser.add_argument('--end-utc-ms',required=True,type=int)
    parser.add_argument('--source',choices=('collateral','dividend'),action='append')
    parser.add_argument('--asset')
    parser.add_argument('--product-id')
    parser.add_argument('--max-calls',type=int,choices=range(1,5),default=4)
    args=parser.parse_args(argv)
    try:
        sources=args.source or ['collateral','dividend']
        if len(sources)!=len(set(sources)):
            raise LiveError('EXPLICIT_SUPPLEMENTAL_SOURCES_REQUIRED')
        credentials=LiveCredentialVault(args.vault).read()
        if 'SPOT_LIVE' not in credentials:
            raise LiveError('LIVE_REQUESTED_SCOPE_NOT_CONFIGURED')
        transport=LiveReadOnlyTransport({'SPOT_LIVE':credentials['SPOT_LIVE']},max_calls=args.max_calls+4)
        endpoints=tuple({'collateral':COLLATERAL_HISTORY,'dividend':DIVIDEND_HISTORY}[source] for source in sources)
        result=SupplementalHistoryCapture(transport,args.output_dir,
            start_utc_ms=args.start_utc_ms,end_utc_ms=args.end_utc_ms,endpoints=endpoints,
            asset=args.asset,product_id=args.product_id).run(max_calls=args.max_calls)
        print(json.dumps(result,ensure_ascii=True,allow_nan=False))
        return 0 if result['state']=='SUPPLEMENTAL_SOURCES_CAPTURED' else 2
    except (ValueError,OSError,TypeError,KeyError) as error:
        code=str(error)
        if not isinstance(error,LiveError) or not re.fullmatch('(?:LIVE|SUPPLEMENTAL|CAPTURE)_[A-Z0-9_]{1,70}',code):
            code='SUPPLEMENTAL_CAPTURE_LOCAL_INPUT_ERROR'
        print(json.dumps({'state':'SUPPLEMENTAL_CAPTURE_BLOCKED','reason_codes':[code],
            'execution_enabled':False,'financial_authorization':False,'ready_for_live':False,'automatic_activation':False}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
