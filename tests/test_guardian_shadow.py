"""Synthetic lifecycle/journal tests; no operating database or network access."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zlib

from tests.test_guardian_capture import make_fixture, fixture_db, fingerprint, iso, NOW
from trader import guardian_capture
from trader.guardian_intelligence import build_intelligence
from trader import guardian_shadow as shadow


class Clock:
    def __init__(self):
        self.value=NOW
    def __call__(self):
        return self.value
    def advance(self,seconds):
        self.value+=seconds


def advisory(report,at=NOW):
    return {"state":"COMPLETED","at":iso(at),"assessment_id":report["assessment_id"],"model":"gpt-6-luna",
            "advisory_only":True,"execution_enabled":False,"controls_enabled":False,
            "commentary":{"summary":"Observación sintética sin autoridad.","posture":"OBSERVE","cautions":[],"evidence_ids":[report["assessment_id"]]},
            "usage":{"input_tokens":100,"output_tokens":50,"cached_tokens":0,"estimated_cost_usd":.000035,"pricing_verified_at":"2026-10-18"}}


def emit_fixture(at=None):
    """Real service/projection, temporary synthetic DBs and fake AI only."""
    instant=time.time() if at is None else at
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        sources=root/"sources"
        sources.mkdir()
        config=make_fixture(sources,instant)
        with patch.object(guardian_capture.time,"time",return_value=instant):
            captured=guardian_capture.capture_guardian(config,now=instant)
        observer=shadow.GuardianShadowService(root/"guardian",app_config=config,clock=lambda:instant,
            config=replace(shadow.GuardianShadowConfig(),context_max_calls_per_day=1),
            capture_fn=lambda _:copy.deepcopy(captured),context_hook=lambda report:advisory(report,instant))
        try:
            if observer.tick().get("state")!="RECORDED":
                raise AssertionError("Synthetic Guardian fixture was not recorded")
            result=shadow.guardian_shadow_snapshot(root/"guardian",now=instant)
            if result.get("report") is None or result.get("ai",{}).get("state")!="COMPLETED":
                raise AssertionError("Synthetic Guardian fixture is incomplete")
            return result
        finally:
            observer.stop()


class GuardianShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.source=self.root/"sources"
        self.source.mkdir()
        self.config=make_fixture(self.source)
        self.journal=self.root/"guardian"
        self.clock=Clock()
        self.capture=self.make_capture()
        self.service=self.make_service()

    def tearDown(self):
        for value in list(shadow._OWNERS.values()):
            if value.path.parent==self.journal:
                value.stop()
        self.service.stop()
        self.temp.cleanup()

    def make_capture(self):
        with patch.object(guardian_capture.time,"time",return_value=self.clock()):
            return guardian_capture.capture_guardian(self.config,now=self.clock())

    def make_service(self,**kwargs):
        return shadow.GuardianShadowService(self.journal,app_config=self.config,clock=self.clock,
            capture_fn=kwargs.pop("capture_fn",lambda _:copy.deepcopy(self.capture)),**kwargs)

    def next_capture(self,seconds=60):
        self.clock.advance(seconds)
        self.capture=self.make_capture()

    def record_count(self):
        with fixture_db(self.service.path) as db:
            return db.execute("SELECT COUNT(*) FROM guardian_records").fetchone()[0]

    def test_default_level_zero_cannot_enable_authority(self):
        for kwargs in ({"mode":"LIVE"},{"mode":"TESTNET"},{"autonomy_level":1},{"autonomy_level":False},
                       {"evaluation_interval":1},{"lease_seconds":60},{"context_max_calls_per_day":5},
                       {"max_records":129601},{"max_corpus_bytes":513*1024*1024}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                shadow.GuardianShadowConfig(**kwargs)
        self.assertEqual(shadow.GuardianShadowConfig().context_max_calls_per_day,0)

    def test_real_clock_precision_survives_capture_sqlite_and_replay(self):
        # datetime ISO rounds to microseconds; SQLite REAL coerces int clocks.
        # Both representations must preserve causality and the frozen digest.
        for index, instant in enumerate((int(NOW), NOW+.1234567)):
            with self.subTest(instant=instant):
                with patch.object(guardian_capture.time, 'time', return_value=instant):
                    frozen = guardian_capture.capture_guardian(self.config, now=instant)
                self.assertTrue(all(source['available_at'] is None or
                    shadow._time(source['available_at']) <= instant
                    for source in frozen['source_metadata'].values()))
                service = shadow.GuardianShadowService(self.journal/str(index),
                    app_config=self.config, clock=lambda:instant,
                    capture_fn=lambda _:copy.deepcopy(frozen))
                try:
                    result = service.tick()
                    self.assertEqual(result['state'], 'RECORDED')
                    self.assertEqual(service.replay(result['id'])['state'], 'MATCH')
                    snapshot = shadow.guardian_shadow_snapshot(service.data_dir, now=instant)
                    self.assertIsNotNone(snapshot['health']['heartbeat_at'])
                    self.assertAlmostEqual(shadow._time(snapshot['health']['heartbeat_at']), instant, places=5)
                finally:
                    service.stop()

    def test_missing_snapshot_and_replay_do_not_create_directory_or_database(self):
        result=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertFalse(self.journal.exists())
        self.assertEqual(result["state"],"NOT_STARTED")
        self.assertIsNone(result["report"])
        self.assertIsNone(result["health"]["records"])
        replay=shadow.replay_guardian(self.journal,"0"*64)
        self.assertEqual(replay["state"],"UNAVAILABLE")
        self.assertFalse(self.journal.exists())

    def test_record_is_compressed_append_only_idempotent_and_replayable(self):
        before=fingerprint(self.source)
        first=self.service.tick()
        self.assertEqual(first["state"],"RECORDED")
        self.assertEqual(self.service.tick(),{"state":"ALREADY_RECORDED","id":first["id"]})
        self.assertEqual(self.record_count(),1)
        with fixture_db(self.service.path) as db:
            row=db.execute("SELECT capture_codec,capture,capture_bytes,report_codec,report,report_bytes FROM guardian_records").fetchone()
            self.assertEqual(row[0],"ZLIB")
            self.assertLess(len(row[1]),row[2])
            self.assertLess(len(row[4]),row[5])
            for statement in ("UPDATE guardian_records SET report_digest='broken'","DELETE FROM guardian_records"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)
        replay=self.service.replay(first["id"])
        self.assertEqual(replay["state"],"MATCH")
        self.assertTrue(replay["causal_cutoff_valid"])
        self.assertFalse(replay["annotation_replayed"])
        self.assertEqual(fingerprint(self.source),before)

    def test_new_captures_chain_without_rewriting_first_evidence(self):
        first=self.service.tick()
        with fixture_db(self.service.path) as db:
            original=tuple(db.execute("SELECT * FROM guardian_records WHERE id=?",(first["id"],)).fetchone())
        self.next_capture()
        second=self.service.tick()
        self.assertEqual(second["state"],"RECORDED")
        with fixture_db(self.service.path) as db:
            self.assertEqual(original,tuple(db.execute("SELECT * FROM guardian_records WHERE id=?",(first["id"],)).fetchone()))
            chain=db.execute("SELECT previous_digest,record_digest FROM guardian_records ORDER BY sequence").fetchall()
        self.assertEqual(chain[0][0],"0"*64)
        self.assertEqual(chain[1][0],chain[0][1])
        self.assertEqual(self.service.replay(first["id"])["state"],"MATCH")
        self.assertEqual(self.service.replay(second["id"])["state"],"MATCH")

    def test_causal_cutoff_cannot_be_backdated_or_use_later_source_receipts(self):
        for change in ("capture_after_cutoff","source_receipt","future_bar","future_cutoff"):
            with self.subTest(change=change):
                value=copy.deepcopy(self.capture)
                if change=="capture_after_cutoff":
                    value["captured_at"]=iso(self.clock()+1)
                elif change=="source_receipt":
                    value["source_metadata"]["spot"]["available_at"]=iso(self.clock()+1)
                elif change=="future_bar":
                    value["btc_closed_bars"][-1]["known_at"]=self.clock()+1
                else:
                    value["captured_at"]=iso(self.clock()+1)
                    value["cutoff_at"]=self.clock()+1
                observer=self.make_service(capture_fn=lambda _,v=value:v)
                self.assertEqual(observer.tick()["state"],"CAPTURE_CAUSALITY_ERROR")
                observer.stop()
        self.assertEqual(self.record_count(),0)

    def test_source_failure_is_frozen_as_partial_without_stopping_other_engines(self):
        self.config.futures_testnet.database_path.unlink()
        self.capture=self.make_capture()
        self.assertEqual(self.service.tick()["state"],"RECORDED")
        result=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertEqual(result["state"],"PARTIAL")
        scopes={row["id"]:row for row in result["report"]["scopes"]}
        self.assertEqual(scopes["SPOT"]["observed_gross_usdt"],100.)
        self.assertIsNone(scopes["FUTURES"]["observed_gross_usdt"])
        self.assertFalse(result["execution_enabled"])

    def test_restart_uses_existing_wallet_free_journal_and_recovers_only_after_lease(self):
        first=self.service.tick()
        successor=self.make_service()
        self.assertEqual(successor.tick()["state"],"LEASE_HELD_BY_ANOTHER_OBSERVER")
        self.next_capture(161)
        self.assertEqual(successor.tick()["state"],"RECORDED")
        self.assertEqual(self.record_count(),2)
        self.assertEqual(successor.replay(first["id"])["state"],"MATCH")
        successor.stop()

    def test_stale_owner_cannot_append_after_blocking_capture_and_successor_claim(self):
        entered,release=threading.Event(),threading.Event()
        frozen=copy.deepcopy(self.capture)
        def blocked(_):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("synthetic timeout")
            return frozen
        predecessor=self.make_service(capture_fn=blocked)
        outcomes=[]
        thread=threading.Thread(target=lambda:outcomes.append(predecessor.tick()))
        thread.start()
        self.assertTrue(entered.wait(2))
        try:
            self.next_capture(161)
            self.assertEqual(self.service.tick()["state"],"RECORDED")
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes,[{"state":"LEASE_LOST"}])
        self.assertEqual(self.record_count(),1)
        predecessor.stop()

    def test_two_observers_concurrently_cannot_call_capture_twice(self):
        gate=threading.Barrier(3)
        calls=[]
        lock=threading.Lock()
        def capture(_):
            with lock:
                calls.append(1)
            return copy.deepcopy(self.capture)
        first,second=self.make_service(capture_fn=capture),self.make_service(capture_fn=capture)
        first.initialize()
        second.initialize()
        results=[]
        def run(observer):
            gate.wait()
            results.append(observer.tick())
        threads=[threading.Thread(target=run,args=(observer,)) for observer in (first,second)]
        for thread in threads: thread.start()
        gate.wait()
        for thread in threads: thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(calls),1)
        self.assertEqual(sorted(row["state"] for row in results),["LEASE_HELD_BY_ANOTHER_OBSERVER","RECORDED"])
        self.assertEqual(self.record_count(),1)
        first.stop()
        second.stop()

    def test_same_service_tick_is_nonblocking_and_stop_rejects_late_append(self):
        entered,release=threading.Event(),threading.Event()
        def capture(_):
            entered.set()
            release.wait(3)
            return copy.deepcopy(self.capture)
        observer=self.make_service(capture_fn=capture)
        outcomes=[]
        thread=threading.Thread(target=lambda:outcomes.append(observer.tick()))
        thread.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(observer.tick()["state"],"TICK_ALREADY_RUNNING")
        started=time.monotonic()
        self.assertFalse(observer.stop(timeout=.01))
        self.assertLess(time.monotonic()-started,.5)
        release.set()
        thread.join(3)
        self.assertEqual(outcomes,[{"state":"LEASE_LOST"}])
        self.assertEqual(self.record_count(),0)
        observer.stop()

    def test_lease_is_rechecked_after_blocking_analysis(self):
        def analyzer(capture,now):
            self.clock.advance(161)
            return build_intelligence(capture,now=now)
        observer=self.make_service(analyze_fn=analyzer)
        self.assertEqual(observer.tick()["state"],"LEASE_LOST")
        self.assertEqual(self.record_count(),0)
        observer.stop()

    def test_heartbeat_extends_only_current_owner_lease(self):
        self.service.initialize()
        self.assertTrue(self.service._lease())
        self.clock.advance(150)
        self.assertTrue(self.service._lease())
        self.clock.advance(20)
        successor=self.make_service()
        successor.initialize()
        self.assertFalse(successor._lease())
        self.service.stop()
        self.assertTrue(successor._lease())
        successor.stop()

    def test_scheduler_waits_sixty_seconds_after_tick_completion_without_sleep(self):
        observer=self.make_service()
        observer.monotonic=self.clock
        starts=[]
        class FakeStop:
            stopped=False
            def is_set(inner): return inner.stopped
            def wait(inner,seconds): self.clock.advance(seconds)
        stopper=FakeStop()
        observer._stop=stopper
        def tick():
            starts.append(self.clock())
            self.clock.advance(7)
            if len(starts)==2: stopper.stopped=True
        observer.tick=tick
        observer._run()
        self.assertEqual(starts,[NOW,NOW+67])

    def test_backward_windows_clock_jump_does_not_freeze_monotonic_cadence(self):
        observer=self.make_service()
        elapsed=[0.]
        observer.monotonic=lambda:elapsed[0]
        starts=[]
        class FakeStop:
            stopped=False
            jumped=False
            def is_set(inner): return inner.stopped
            def wait(inner,seconds):
                elapsed[0]+=seconds
                self.clock.advance(seconds)
                if not inner.jumped:
                    self.clock.advance(-3600)
                    inner.jumped=True
        stopper=FakeStop()
        observer._stop=stopper
        def tick():
            starts.append((elapsed[0],self.clock()))
            elapsed[0]+=7
            self.clock.advance(7)
            if len(starts)==2: stopper.stopped=True
        observer.tick=tick
        observer._run()
        self.assertEqual([row[0] for row in starts],[0.,67.])
        self.assertLess(starts[1][1],starts[0][1])

    def test_capacity_warning_and_full_preserve_prior_evidence(self):
        config=replace(shadow.GuardianShadowConfig(),max_records=5)
        observer=self.make_service(config=config)
        for i in range(4):
            if i: self.next_capture()
            self.assertEqual(observer.tick()["state"],"RECORDED")
        snapshot=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertEqual(snapshot["health"]["capacity_state"],"WARNING")
        self.next_capture()
        self.assertEqual(observer.tick()["state"],"RECORDED")
        with fixture_db(observer.path) as db:
            records=db.execute("SELECT id,record_digest FROM guardian_records ORDER BY sequence").fetchall()
        self.next_capture()
        self.assertEqual(observer.tick()["state"],"RETENTION_FULL")
        self.assertEqual(self.record_count(),5)
        with fixture_db(observer.path) as db:
            self.assertEqual(records,db.execute("SELECT id,record_digest FROM guardian_records ORDER BY sequence").fetchall())
        snapshot=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertEqual(snapshot["health"]["capacity_state"],"FULL")
        self.assertEqual(snapshot["health"]["last_error"],"RETENTION_FULL")
        observer.stop()

    def test_changed_frozen_configuration_never_resets_past_corpus(self):
        self.assertEqual(self.service.tick()["state"],"RECORDED")
        first=fingerprint(self.journal)
        other=self.make_service(config=replace(shadow.GuardianShadowConfig(),max_records=100))
        self.assertEqual(other.tick()["state"],"GUARDIAN_COHORT_CONFIG_MISMATCH")
        self.assertEqual(first,fingerprint(self.journal))
        self.assertEqual(self.record_count(),1)

    def test_snapshot_read_only_preserves_stale_original_report(self):
        result=self.service.tick()
        before=fingerprint(self.journal)
        current=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        later=shadow.guardian_shadow_snapshot(self.journal,now=self.clock()+100)
        self.assertEqual(current["report"],later["report"])
        self.assertEqual(current["updated_at"],later["updated_at"])
        self.assertEqual(later["freshness"]["state"],"STALE")
        self.assertEqual(later["state"],"STALE")
        self.assertEqual(fingerprint(self.journal),before)
        self.assertLessEqual(len(shadow._dump(current).encode()),shadow.MAX_SNAPSHOT)
        self.assertEqual(current["engine"],"GUARDIAN_INTELLIGENCE")
        self.assertEqual(current["journal"][0]["id"],result["id"])

    def test_snapshot_locked_corrupt_and_missing_are_unknown_no_create(self):
        self.service.tick()
        with fixture_db(self.service.path) as db:
            db.execute("BEGIN EXCLUSIVE")
            started=time.monotonic()
            snapshot=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
            self.assertLess(time.monotonic()-started,1.)
            self.assertEqual(snapshot["state"],"DEGRADED")
            self.assertIsNone(snapshot["report"])
        self.service.stop()
        self.service.path.write_bytes(b"not a db with private token")
        snapshot=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertNotIn("private token",json.dumps(snapshot))
        self.assertEqual(snapshot["health"]["last_error"],"GUARDIAN_JOURNAL_UNAVAILABLE")

    def test_context_disabled_by_default_even_when_injected(self):
        calls=[]
        observer=self.make_service(context_hook=lambda payload:calls.append(payload))
        self.assertEqual(observer.tick()["state"],"RECORDED")
        self.assertEqual(calls,[])
        snapshot=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertEqual(snapshot["ai"]["state"],"UNAVAILABLE")
        self.assertEqual(snapshot["ai"]["reason"],"AI_DISABLED_OR_UNAVAILABLE")
        self.assertEqual(snapshot["health"]["ai_calls_today"],0)
        observer.stop()

    def test_no_model_call_or_budget_claim_without_verified_context(self):
        capture = copy.deepcopy(self.capture)
        capture.update(dashboard={}, btc_closed_bars=[])
        for source in capture['source_metadata'].values():
            source.update(state='UNKNOWN', inventory_complete=False,
                positions_seen=None, positions_returned=0, available_at=None)
        calls = []
        observer = self.make_service(
            config=replace(shadow.GuardianShadowConfig(), context_max_calls_per_day=2),
            capture_fn=lambda _:copy.deepcopy(capture),
            context_hook=lambda payload:calls.append(payload))
        try:
            self.assertEqual(observer.tick()['state'], 'RECORDED')
            self.assertEqual(calls, [])
            value = shadow.guardian_shadow_snapshot(self.journal, now=self.clock())
            self.assertEqual(value['ai']['reason'], 'INSUFFICIENT_VERIFIED_CONTEXT')
            self.assertEqual(value['health']['ai_calls_today'], 0)
            self.assertEqual(value['report']['state'], 'PARTIAL')
        finally:
            observer.stop()

    def test_optional_context_budget_frozen_separately_never_changes_assessment(self):
        calls=[]
        def hook(payload):
            calls.append(payload)
            return advisory(payload,self.clock())
        observer=self.make_service(config=replace(shadow.GuardianShadowConfig(),context_max_calls_per_day=1),context_hook=hook)
        first=observer.tick()
        expected=build_intelligence(self.capture,now=self.clock())
        self.assertEqual(first["report_digest"],shadow._digest(expected))
        self.assertEqual(len(calls),1)
        self.assertLessEqual(len(json.dumps(calls[0]).encode()),shadow.MAX_REPORT)
        self.assertEqual(observer.tick()["state"],"ALREADY_RECORDED")
        self.assertEqual(len(calls),1)
        self.next_capture()
        self.assertEqual(observer.tick()["state"],"RECORDED")
        snapshot=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertEqual(snapshot["ai"]["reason"],"AI_BUDGET_OR_INTERVAL")
        self.assertEqual(len(calls),1)
        self.assertEqual(observer.replay(first["id"])["state"],"MATCH")
        self.assertEqual(len(calls),1)
        observer.stop()

    def test_context_timeout_and_invalid_output_are_bounded_and_cannot_create_orders(self):
        release=threading.Event()
        def hook(_):
            release.wait(2)
            return {"order":"BUY","api_key":"never persist me"}
        observer=self.make_service(config=replace(shadow.GuardianShadowConfig(),context_max_calls_per_day=2,context_timeout_seconds=.05),context_hook=hook)
        try:
            started=time.monotonic()
            self.assertEqual(observer.tick()["state"],"RECORDED")
            self.assertLess(time.monotonic()-started,1.)
            snapshot=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
            self.assertEqual(snapshot["ai"]["reason"],"AI_CONTEXT_TIMEOUT")
            self.next_capture()
            self.assertEqual(observer.tick()["state"],"RECORDED")
            snapshot=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
            self.assertEqual(snapshot["ai"]["reason"],"AI_PRIOR_CONTEXT_RUNNING")
            self.assertNotIn("never persist me",json.dumps(snapshot))
            self.assertEqual(snapshot["health"]["ai_calls_today"],1)
        finally:
            release.set()
            observer._context_thread.join(2)
            observer.stop()

    def test_reviewer_health_counts_api_attempts_not_cached_hook_invocations(self):
        clock=self.clock
        class Hook:
            calls=0
            used=0
            old=None
            def health(inner):
                return {"daily_cap":1,"used_today":inner.used,"available":True}
            def __call__(inner,report):
                inner.calls+=1
                if inner.old is None:
                    inner.used+=1
                    inner.old=advisory(report,clock())
                    return copy.deepcopy(inner.old)
                return {**copy.deepcopy(inner.old),"state":"CACHED_HISTORICAL","cache_age_seconds":clock()-NOW}
        hook=Hook()
        observer=self.make_service(config=replace(shadow.GuardianShadowConfig(),context_max_calls_per_day=1),context_hook=hook)
        first=observer.tick()
        self.next_capture()
        self.assertEqual(observer.tick()["state"],"RECORDED")
        snapshot=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertEqual(hook.calls,2)
        self.assertEqual(snapshot["health"]["ai_calls_today"],1)
        self.assertEqual(snapshot["health"]["ai_daily_limit"],1)
        self.assertEqual(snapshot["ai"]["state"],"CACHED_HISTORICAL")
        self.assertNotEqual(snapshot["ai"]["assessment_id"],snapshot["report"]["assessment_id"])
        self.assertEqual(snapshot["ai"]["assessment_id"],hook.old["assessment_id"])
        self.assertEqual(observer.replay(first["id"])["state"],"MATCH")
        self.assertEqual(hook.calls,2)
        observer.stop()

    def test_invalid_review_or_budget_cannot_smuggle_authority_or_arbitrary_text(self):
        def malicious(report):
            result=advisory(report,self.clock())
            result["execution_enabled"]=True
            result["orders"]=["BUY"]
            return result
        observer=self.make_service(config=replace(shadow.GuardianShadowConfig(),context_max_calls_per_day=1),context_hook=malicious)
        self.assertEqual(observer.tick()["state"],"RECORDED")
        result=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertEqual(result["ai"]["reason"],"AI_CONTEXT_INVALID")
        self.assertNotIn("orders",json.dumps(result))
        observer.stop()

    def test_explicit_hook_health_budget_must_be_at_or_below_wrapper_cap(self):
        class Hook:
            called=False
            def health(inner): return {"daily_cap":2,"used_today":0,"available":True}
            def __call__(inner,report): inner.called=True
        hook=Hook()
        observer=self.make_service(config=replace(shadow.GuardianShadowConfig(),context_max_calls_per_day=1),context_hook=hook)
        self.assertEqual(observer.tick()["state"],"RECORDED")
        self.assertFalse(hook.called)
        result=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertEqual(result["ai"]["reason"],"AI_BUDGET_CONFIGURATION")
        observer.stop()

    def test_errors_are_fixed_codes_never_well_formed_private_strings(self):
        def bad(_): raise shadow.ShadowError("private_bearer_token")
        observer=self.make_service(capture_fn=bad)
        self.assertEqual(observer.tick()["state"],"GUARDIAN_OBSERVATION_FAILED")
        result=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertNotIn("private_bearer_token",json.dumps(result))
        observer.stop()

    def test_full_retention_stops_capture_and_context_without_deleting_evidence(self):
        calls=[]
        observer=self.make_service(config=replace(shadow.GuardianShadowConfig(),max_records=1),capture_fn=lambda _:(calls.append(1),copy.deepcopy(self.capture))[1])
        self.assertEqual(observer.tick()["state"],"RECORDED")
        self.next_capture()
        self.assertEqual(observer.tick()["state"],"RETENTION_FULL")
        self.assertEqual(calls,[1])
        self.assertEqual(self.record_count(),1)
        observer.stop()

    def test_start_registry_prevents_duplicate_thread_and_stop_allows_clean_successor(self):
        finished=threading.Event()
        first=self.make_service()
        original=first.tick
        def observed_tick():
            value=original()
            finished.set()
            return value
        first.tick=observed_tick
        second=self.make_service()
        self.assertTrue(first.start())
        self.assertTrue(finished.wait(2))
        self.assertFalse(second.start())
        self.assertTrue(first.stop())
        released=shadow.guardian_shadow_snapshot(self.journal,now=self.clock())
        self.assertEqual(released["health"]["lease_state"],"RELEASED")
        self.assertTrue(second.start())
        self.assertTrue(second.stop())

    def test_disabled_service_does_not_initialize_any_database(self):
        observer=self.make_service(config=replace(shadow.GuardianShadowConfig(),enabled=False))
        self.assertFalse(observer.start())
        self.assertEqual(observer.tick()["state"],"STOPPED")
        self.assertFalse(self.journal.exists())

    def test_capture_size_limit_is_checked_before_analysis_and_hook(self):
        value=copy.deepcopy(self.capture)
        value["oversized"]="x"*shadow.MAX_CAPTURE
        called=[]
        observer=self.make_service(capture_fn=lambda _:value,analyze_fn=lambda *args,**kwargs:called.append(1))
        self.assertEqual(observer.tick()["state"],"FROZEN_VALUE_TOO_LARGE")
        self.assertEqual(called,[])
        self.assertEqual(self.record_count(),0)
        observer.stop()

    def test_every_writer_reapplies_physical_page_ceiling_from_frozen_cohort(self):
        maximum=1024*1024
        observer=self.make_service(config=replace(shadow.GuardianShadowConfig(),max_corpus_bytes=maximum))
        observer.initialize()
        for _ in range(2):
            with shadow._writer(observer.path) as db:
                pages=db.execute("PRAGMA max_page_count").fetchone()[0]
                page_size=db.execute("PRAGMA page_size").fetchone()[0]
                self.assertLessEqual(pages*page_size,maximum)
                self.assertGreaterEqual(pages,8)
        observer.stop()

    def test_malformed_assessment_authority_is_rejected_before_append(self):
        def analyze(capture,now):
            report=build_intelligence(capture,now=now)
            report["execution_enabled"]=True
            return report
        observer=self.make_service(analyze_fn=analyze)
        self.assertEqual(observer.tick()["state"],"INVALID_ASSESSMENT_IDENTITY")
        self.assertEqual(self.record_count(),0)
        observer.stop()

    def test_replay_detects_changed_analyzer_without_new_data_or_network(self):
        record=self.service.tick()
        before=fingerprint(self.journal)
        def changed(capture,now):
            report=build_intelligence(capture,now=now)
            report["policy"]["id"]="changed-policy"
            return report
        replay=shadow.replay_guardian(self.journal,record["id"],analyze_fn=changed)
        self.assertEqual(replay["state"],"MISMATCH")
        self.assertEqual(before,fingerprint(self.journal))

    def test_bounded_decompression_rejects_bombs_and_noncanonical_json(self):
        for codec,payload in (("ZLIB",zlib.compress(b"x"*100000)),("RAW",b'{"not": "canonical"}'),("OTHER",b"{}")):
            with self.subTest(codec=codec),self.assertRaises(shadow.ShadowError):
                shadow._unpack(codec,payload,1000)

    def test_digest_tampering_is_detected_and_never_repaired_by_reader(self):
        record=self.service.tick()
        with fixture_db(self.service.path) as db:
            db.execute("DROP TRIGGER guardian_records_no_update")
            db.execute("UPDATE guardian_records SET report_digest=?",("0"*64,))
        before=fingerprint(self.journal)
        self.assertEqual(self.service.replay(record["id"])["state"],"UNAVAILABLE")
        self.assertEqual(shadow.guardian_shadow_snapshot(self.journal,now=self.clock())["state"],"DEGRADED")
        self.assertEqual(fingerprint(self.journal),before)


if __name__=="__main__":
    unittest.main(verbosity=2)
