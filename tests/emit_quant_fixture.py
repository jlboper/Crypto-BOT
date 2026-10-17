"""Actual isolated Quant ledger -> public projection -> Worker fixture. No API calls."""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.export_paper_snapshot import compatible_remote_projection
from tests.emit_guardian_fixture import make_dashboard
from tests.test_quant_shadow import Clock, Source
from trader.portfolio_guardian import build_guardian, engine_catalog
from trader.portal_snapshot import public_quant_projection
from trader.quant_shadow import QuantShadowService


def make_quant_dashboard(root, *, stale=False, paused=False, pending=False, settled=False, not_ready=False):
    clock = Clock()
    clock.now = time.time()
    with patch('tests.test_quant_shadow.NOW', clock.now):
        source = Source(clock)
        service = QuantShadowService(root, source=source, clock=clock)
        try:
            if not_ready:
                service.initialize()
            else:
                service.tick()
            if paused:
                from trader.quant_shadow import pause_quant
                pause_quant(root, True)
            if pending or settled:
                if settled:
                    source.history_extra.append({'at': clock.now + 3600,
                        'received_at': clock.now + 3601, 'rate': .01, 'mark_price': 100.})
                clock.now += 3601
                service.tick()
            if stale:
                clock.now += 91
            quant = public_quant_projection(service.snapshot(now=clock()))
            payload = make_dashboard(root)
            payload['quant'] = quant
            payload['portfolio_guardian'] = build_guardian(payload, now=clock())
            payload['engine_catalog'] = engine_catalog(payload)
            return compatible_remote_projection(payload)
        finally:
            service.stop()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        payload = make_quant_dashboard(Path(directory), stale='--stale' in sys.argv,
            paused='--paused' in sys.argv, pending='--pending' in sys.argv,
            settled='--settled' in sys.argv, not_ready='--not-ready' in sys.argv)
        print(json.dumps(payload, allow_nan=False, ensure_ascii=True, separators=(',', ':')))
