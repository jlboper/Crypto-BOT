"""Real Guardian capture/service/journal projection from four synthetic DBs.

The importable producer and CLI never load environment/config files or call APIs.
Each invocation creates and deletes its own temporary fixture, not a bot process.
"""
import argparse
import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_guardian_intelligence(*, now=None, variant="ready"):
    from tests.test_guardian_capture import make_fixture
    from tests.test_guardian_shadow import advisory
    from trader import guardian_capture
    from trader.guardian_shadow import GuardianShadowConfig, GuardianShadowService, guardian_shadow_snapshot

    if variant not in {"ready", "stale", "partial", "not-started", "no-ai"}:
        raise ValueError("Unknown synthetic Guardian fixture variant")
    # All fixture receipts use the same whole UTC second. ISO microsecond
    # rounding must not place a synthetic receipt after its frozen cutoff.
    instant = float(int(time.time() if now is None else now))
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        journal = root/"guardian"
        if variant == "not-started":
            result = guardian_shadow_snapshot(journal, now=instant)
            if journal.exists():
                raise AssertionError("Reading an absent Guardian journal created files")
            return result
        sources = root/"sources"
        sources.mkdir()
        config = make_fixture(sources, instant)
        if variant == "partial":
            config.futures_testnet.database_path.unlink()
        with patch.object(guardian_capture.time, "time", return_value=instant):
            captured = guardian_capture.capture_guardian(config, now=instant)
        with_ai = variant != "no-ai"
        service = GuardianShadowService(journal, app_config=config, clock=lambda: instant,
            config=replace(GuardianShadowConfig(), context_max_calls_per_day=1 if with_ai else 0),
            capture_fn=lambda _: copy.deepcopy(captured),
            context_hook=(lambda report: advisory(report, instant)) if with_ai else None)
        try:
            recorded = service.tick()
            if recorded.get("state") != "RECORDED":
                raise AssertionError("Real synthetic Guardian service did not record: "+str(recorded.get("state")))
            replay = service.replay(recorded["id"])
            if replay.get("state") != "MATCH":
                raise AssertionError("Synthetic Guardian causal replay did not match: "+str(replay))
            result = guardian_shadow_snapshot(journal, now=instant+180 if variant == "stale" else instant)
            if result.get("report") is None or with_ai and (result.get("ai") or {}).get("state") != "COMPLETED":
                raise AssertionError("Real Guardian producer returned incomplete evidence")
            return result
        finally:
            service.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("ready", "stale", "partial", "not-started", "no-ai"), default="ready")
    args = parser.parse_args()
    print(json.dumps(make_guardian_intelligence(variant=args.variant), ensure_ascii=True,
                     allow_nan=False, separators=(",", ":")))
