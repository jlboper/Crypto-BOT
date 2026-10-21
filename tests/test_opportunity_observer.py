from contextlib import closing
import hashlib
import json
from pathlib import Path
import queue
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from trader import opportunity_observer as module
from trader.opportunity_contract import OpportunityEvent, build_intent, build_outcome, canonical, position_digest
from trader.opportunity_observer import (OpportunityObserverService, opportunity_snapshot,
    observe_entry_intent, observe_entry_outcome, register_observer, unregister_observer)
from tests.test_opportunity_contract import NOW,intent_fields,outcome_fields


class OpportunityObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        self.clock=[NOW];self.services=[];module._DROPPED=0

    def tearDown(self):
        for service in self.services:service.stop()
        module._DROPPED=0;self.temp.cleanup()

    def service(self,**kwargs):
        service=OpportunityObserverService(self.path,clock=lambda:self.clock[0],**kwargs)
        self.services.append(service);return service

    def initialized(self,**kwargs):
        service=self.service(**kwargs);service.initialize();service._flush_health(heartbeat=True);return service

    def consume(self,service,**kwargs):return service._consume(build_intent(**intent_fields(**kwargs)))

    def wait(self,predicate):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.01)
        self.fail('worker did not reach bounded expected state')

    def test_readonly_missing_snapshot_creates_no_path(self):
        missing=self.path/'missing'/'nested';value=opportunity_snapshot(missing,now=NOW)
        self.assertEqual(value['state'],'NOT_STARTED');self.assertFalse(missing.exists())
        self.assertIsNone(value['health']['records']);self.assertEqual(value['scopes'],[])

    def test_initialized_without_heartbeat_is_stale_not_activity_failure(self):
        service=self.service();service.initialize();value=service.snapshot()
        self.assertEqual(value['state'],'STALE');self.assertEqual(value['health']['errors'],0)

    def test_heartbeat_separates_liveness_from_last_event(self):
        service=self.initialized();self.assertEqual(service.snapshot()['state'],'IDLE')
        self.consume(service);first=service.snapshot()['updated_at']
        self.clock[0]+=3600;service._flush_health(heartbeat=True);value=service.snapshot()
        self.assertEqual(value['state'],'OBSERVING');self.assertEqual(value['freshness']['state'],'FRESH')
        self.assertEqual(value['updated_at'],first);self.assertNotEqual(value['health']['heartbeat_at'],first)
        self.clock[0]+=16;self.assertEqual(service.snapshot()['state'],'STALE')

    def test_worker_heartbeat_runs_without_events_and_uses_monotonic(self):
        service=self.service();self.assertTrue(service.start())
        self.wait(lambda:service._last_heartbeat==NOW)
        self.clock[0]-=100;service._heartbeat_monotonic-=6
        self.wait(lambda:service._last_heartbeat==NOW-100)
        value=service.snapshot();self.assertEqual(value['state'],'IDLE')
        self.assertEqual(value['health']['records'],0);self.assertEqual(value['health']['errors'],0)

    def test_clock_regression_has_no_negative_freshness(self):
        service=self.initialized();self.clock[0]-=1;value=service.snapshot()
        self.assertEqual(value['state'],'PARTIAL');self.assertIsNone(value['freshness']['age_seconds'])
        self.assertEqual(value['health']['last_error'],'CLOCK_REGRESSION')

    def test_new_heartbeat_after_utc_rollback_does_not_freshen_future_history(self):
        service=self.initialized();self.assertTrue(register_observer(service))
        self.consume(service);before=service.snapshot()
        self.clock[0]-=100;service._flush_health(heartbeat=True)
        value=service.snapshot()
        self.assertEqual(value['state'],'PARTIAL')
        self.assertEqual(value['health']['last_error'],'CLOCK_REGRESSION')
        self.assertEqual(value['freshness'],{'state':'UNAVAILABLE','age_seconds':None})
        self.assertEqual(value['updated_at'],before['updated_at'])
        self.assertEqual(value['recent_records'],before['recent_records'])
        self.assertNotEqual(value['health']['heartbeat_at'],value['updated_at'])

    def test_idempotence_and_restart_preserve_exact_journal(self):
        service=self.initialized();event=build_intent(**intent_fields())
        self.assertEqual(service._consume(event),'INTENT_OBSERVED');self.assertEqual(service._consume(event),'IDEMPOTENT')
        restarted=self.initialized();self.assertEqual(restarted._consume(event),'IDEMPOTENT')
        value=restarted.snapshot();self.assertEqual(value['health']['records'],1)
        self.assertEqual(value['recent_records'][0]['payload_digest'],event.id)
        self.assertEqual(value['scopes'][0]['hypothetical_reserved'],'100.4')

    def test_revision_conflict_stays_latched_and_blocks_new_scenario(self):
        service=self.initialized();self.consume(service)
        changed=intent_fields();changed['legs'][0]['quantity']='2'
        self.assertEqual(service._consume(build_intent(**changed)),'ORIGIN_CONFLICT')
        self.assertEqual(service._consume(build_outcome(**outcome_fields(stage='LEDGER_COMMIT',state='CLOSED'))),'ORIGIN_CONFLICT')
        self.consume(service,origin_ref='different',legs=[dict(symbol='ETHUSDT',venue='SPOT_TESTNET',direction='LONG',quantity='1',reference_price='100',stop_price='99',fee_rate='.001',slippage_rate='.001')])
        value=service.snapshot();self.assertIsNone(value['scopes'][0]['hypothetical_reserved'])
        self.assertEqual(value['recent_records'][0]['assessment']['hypothetical_state'],'UNKNOWN')

    def test_filled_response_and_open_commit_never_release_or_claim_protection(self):
        service=self.initialized();self.consume(service)
        self.assertEqual(service._consume(build_outcome(**outcome_fields())),'EXCHANGE_FILLED_UNCOMMITTED')
        value=service.snapshot();self.assertEqual(value['scopes'][0]['hypothetical_reserved'],'100.4')
        self.assertEqual(value['recent_records'][0]['stage'],'EXCHANGE_RESPONSE')
        self.assertEqual(service._consume(build_outcome(**outcome_fields(stage='LEDGER_COMMIT',state='OPENED'))),'COMMITTED_PROTECTION_UNVERIFIED')
        self.assertEqual(service.snapshot()['scopes'][0]['hypothetical_reserved'],'100.4')
        self.clock[0]+=86400
        self.assertEqual(service.snapshot()['scopes'][0]['hypothetical_reserved'],'100.4')

    def test_complete_close_and_late_divergence_preserve_terminal_history(self):
        service=self.initialized();self.consume(service)
        service._consume(build_outcome(**outcome_fields(stage='LEDGER_COMMIT',state='CLOSED')))
        self.assertEqual(service.snapshot()['scopes'][0]['hypothetical_reserved'],'0')
        self.assertEqual(service._consume(build_outcome(**outcome_fields(state='UNKNOWN',complete=False))),'TERMINAL_CONFLICT')
        with closing(sqlite3.connect(service.path)) as db:
            self.assertEqual(db.execute('SELECT terminal,closed FROM opportunity_origins').fetchone(),('CLOSED',1))
        self.assertIsNone(service.snapshot()['scopes'][0]['hypothetical_reserved'])
        self.assertEqual(service._consume(build_outcome(**outcome_fields())),'TERMINAL_CONFLICT')

    def position_event(self,reference,*,state='CLOSED',remaining='0',proof='c'*64,at=NOW):
        digest=position_digest('SPOT','SPOT_TESTNET',reference)
        return build_outcome(**outcome_fields(origin_ref='POSITION:'+digest,at=at,stage='LEDGER_COMMIT',
            state=state,complete=state=='CLOSED',by_position=True,
            evidence={'position_digest':digest,'remaining_quantity':remaining,'decision_digest':proof}))

    def link(self,service,reference,origin='private-client-order',proof='b'*64):
        event=build_outcome(**outcome_fields(origin_ref=origin,stage='LEDGER_COMMIT',state='OPENED',
            evidence={'position_digest':position_digest('SPOT','SPOT_TESTNET',reference),'decision_digest':proof}))
        self.assertEqual(service._consume(event),'COMMITTED_PROTECTION_UNVERIFIED')
        return event

    def test_exact_position_link_survives_restart_and_closes_only_its_origin(self):
        service=self.initialized();self.consume(service)
        reference='BTCUSDT|2026-10-20T12:00:00+00:00'
        self.link(service,reference)
        restarted=self.initialized()
        unrelated=self.position_event('BTCUSDT|2026-10-20T12:00:01+00:00')
        self.assertEqual(restarted._consume(unrelated),'UNKNOWN')
        self.assertEqual(restarted.snapshot()['scopes'][0]['hypothetical_reserved'],'100.4')
        self.assertEqual(restarted._consume(self.position_event(reference)),'CLOSED_OBSERVED')
        self.assertEqual(restarted.snapshot()['scopes'][0]['hypothetical_reserved'],'0')
        with closing(sqlite3.connect(service.path)) as db:
            raw,origin=db.execute('SELECT data,origin FROM opportunity_records ORDER BY sequence DESC LIMIT 1').fetchone()
        self.assertNotEqual(json.loads(raw)['origin_digest'],origin)
        self.assertEqual(origin,build_intent(**intent_fields()).payload()['origin_digest'])

    def test_partial_close_retains_reservation_until_exact_closed_commit(self):
        service=self.initialized();self.consume(service);self.link(service,'position-1')
        service._consume(self.position_event('position-1',state='PARTIAL',remaining='.4'))
        self.assertEqual(service.snapshot()['scopes'][0]['hypothetical_reserved'],'100.4')
        self.assertEqual(service._consume(self.position_event('position-1')),'CLOSED_OBSERVED')
        self.assertEqual(service.snapshot()['scopes'][0]['hypothetical_reserved'],'0')

    def test_unlinked_position_namespace_cannot_match_an_order_origin(self):
        service=self.initialized()
        digest=position_digest('SPOT','SPOT_TESTNET','position-1')
        self.consume(service,origin_ref='POSITION:'+digest)
        self.assertEqual(service._consume(self.position_event('position-1')),'UNKNOWN')
        self.assertEqual(service.snapshot()['scopes'][0]['hypothetical_reserved'],'100.4')

    def test_duplicate_closed_proof_and_open_receipt_replay_do_not_revive(self):
        service=self.initialized();self.consume(service);opening=self.link(service,'position-1')
        service._consume(self.position_event('position-1'))
        self.clock[0]+=1
        self.assertEqual(service._consume(self.position_event('position-1',at=NOW+1)),'CLOSED_OBSERVED')
        payload=opening.payload();payload['at']=NOW+1
        self.assertEqual(service._consume(build_outcome(**outcome_fields(at=NOW+1,stage='LEDGER_COMMIT',state='OPENED',
            evidence=payload['evidence']|{'position_digest':payload['position_digest']}))),'CLOSED_OBSERVED')
        self.assertEqual(service.snapshot()['scopes'][0]['hypothetical_reserved'],'0')
        self.assertEqual(service._consume(self.position_event('position-1',proof='d'*64,at=NOW+1)),'TERMINAL_CONFLICT')
        self.assertIsNone(service.snapshot()['scopes'][0]['hypothetical_reserved'])

    def test_position_link_collision_latches_both_origins_without_reassignment(self):
        service=self.initialized();self.consume(service);self.link(service,'position-1')
        self.consume(service,origin_ref='another-entry')
        collision=build_outcome(**outcome_fields(origin_ref='another-entry',stage='LEDGER_COMMIT',state='OPENED',
            evidence={'position_digest':position_digest('SPOT','SPOT_TESTNET','position-1'),'decision_digest':'e'*64}))
        self.assertEqual(service._consume(collision),'ORIGIN_CONFLICT')
        self.assertEqual(service._consume(self.position_event('position-1')),'ORIGIN_CONFLICT')
        self.assertIsNone(service.snapshot()['scopes'][0]['hypothetical_reserved'])

    def test_public_outcome_schema_does_not_leak_internal_position_link(self):
        service=self.initialized();self.consume(service);self.link(service,'private-position-reference')
        value=service.snapshot()['recent_records'][0]
        self.assertEqual(set(value['evidence']),{'response_digest','decision_digest','quantity','fees'})
        self.assertNotIn('private-position-reference',json.dumps(service.snapshot()))
        # Version46 projects payload['evidence'] unchanged. The durable format
        # must therefore keep the old closed shape, not just filter it in47.
        with closing(sqlite3.connect(service.path)) as db:
            payload=json.loads(db.execute('SELECT data FROM opportunity_records ORDER BY sequence DESC LIMIT 1').fetchone()[0])
        self.assertEqual(set(payload['evidence']),{'response_digest','decision_digest','quantity','fees'})
        self.assertIn('position_digest',payload)

    def test_exact_release46_reader_and_writer_preserve47_closed_origin(self):
        from tests.legacy_opportunity import load_observer46
        legacy=load_observer46()
        service=self.initialized();self.consume(service);self.link(service,'position-1')
        service._consume(self.position_event('position-1'))
        before=service.snapshot();old=legacy.opportunity_snapshot(self.path,now=NOW)
        self.assertEqual(old,before)
        rolled_back=legacy.OpportunityObserverService(self.path,clock=lambda:NOW)
        rolled_back.initialize()
        self.assertEqual(rolled_back._consume(build_intent(**intent_fields(origin_ref='new-after-rollback'))),'INTENT_OBSERVED')
        origin=build_intent(**intent_fields()).payload()['origin_digest']
        with closing(sqlite3.connect(service.path)) as db:
            self.assertEqual(db.execute('SELECT closed,terminal FROM opportunity_origins WHERE origin=?',(origin,)).fetchone(),(1,'CLOSED'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM opportunity_positions').fetchone()[0],1)
        self.assertEqual(legacy.opportunity_snapshot(self.path,now=NOW),service.snapshot())

    def test_filled_then_unknown_cannot_release_on_zero_cancel(self):
        service=self.initialized();self.consume(service)
        for changes in [{},dict(state='UNKNOWN',complete=False),dict(state='CANCELLED',evidence={'quantity':'0'})]:
            service._consume(build_outcome(**outcome_fields(**changes)))
        self.assertEqual(service.snapshot()['scopes'][0]['hypothetical_reserved'],'100.4')

    def test_orphan_and_pre_intent_outcome_do_not_infer_execution(self):
        service=self.initialized();service._consume(build_outcome(**outcome_fields()))
        value=service.snapshot();self.assertEqual(value['scopes'],[])
        self.assertEqual(value['recent_records'][0]['assessment']['reason'],'MISSING_INTENT')
        self.consume(service);service._consume(build_outcome(**outcome_fields(at=NOW-1)))
        self.assertEqual(service.snapshot()['recent_records'][0]['assessment']['reason'],'OUTCOME_BEFORE_INTENT')

    def test_five_scopes_preserve_environment_separation(self):
        service=self.initialized()
        for engine,env in [('SPOT','SPOT_TESTNET'),('SPOT','PAPER'),('FUTURES','FUTURES_DEMO'),('AI_MARKET_PULSE','SHADOW'),('QUANT_ARBITRAGE','SHADOW')]:
            self.consume(service,engine=engine,environment=env)
        value=service.snapshot();self.assertEqual(len(value['scopes']),5)
        self.assertEqual(value['coverage'][0]['environment'],'UNKNOWN')
        self.assertTrue(all(scope['account_identity']=='UNKNOWN' for scope in value['scopes']))
        self.assertTrue(all(value[key] is False for key in module.FLAGS))

    def test_capacity_keeps_past_evidence_and_reports_full(self):
        service=self.initialized(max_records=1);self.consume(service)
        self.assertEqual(self.consume(service,origin_ref='second'),'RETENTION_FULL');service._flush_health()
        value=service.snapshot();self.assertEqual(value['health']['records'],1)
        self.assertEqual(value['health']['capacity_state'],'FULL');self.assertEqual(value['state'],'PARTIAL')
        with closing(sqlite3.connect(service.path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM opportunity_records')
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE opportunity_records SET state='fake'")

    def test_producer_queue_full_and_slow_worker_do_not_wait_or_touch_sql(self):
        service=self.service();self.assertTrue(register_observer(service))
        with patch.object(module,'_connect',side_effect=AssertionError('producer attempted SQL')):
            for i in range(module.QUEUE_CAPACITY):self.assertTrue(observe_entry_intent(**intent_fields(origin_ref=str(i))))
            self.assertFalse(observe_entry_intent(**intent_fields(origin_ref='overflow')))
            self.assertFalse(observe_entry_outcome(**outcome_fields()))
        self.assertFalse(service.path.exists());self.assertEqual(service._queue.qsize(),module.QUEUE_CAPACITY)
        self.assertEqual(module._DROPPED,2)

    def test_registry_rejects_arbitrary_classes_and_second_service(self):
        class Callback:
            def __getattr__(self,name):raise AssertionError('callback')
        self.assertFalse(register_observer(Callback()))
        first=self.service();second=self.service()
        self.assertTrue(register_observer(first));self.assertFalse(register_observer(second))
        unregister_observer(second);self.assertIs(module._SERVICE,first)
        unregister_observer(first);self.assertFalse(observe_entry_intent(**intent_fields()))

    def test_concurrent_consume_same_event_commits_once(self):
        service=self.initialized();event=build_intent(**intent_fields());results=[]
        threads=[threading.Thread(target=lambda:results.append(service._consume(event))) for _ in range(6)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(2)
        self.assertEqual(results.count('INTENT_OBSERVED'),1);self.assertEqual(results.count('IDEMPOTENT'),5)
        self.assertEqual(service.snapshot()['health']['records'],1)

    def test_start_concurrency_creates_one_worker_and_stop_unregisters(self):
        service=self.service();results=[]
        threads=[threading.Thread(target=lambda:results.append(service.start())) for _ in range(4)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(2)
        self.assertEqual(results,[True]*4);self.assertEqual(sum(t.name=='opportunity-shadow' for t in threading.enumerate()),1)
        self.assertTrue(observe_entry_intent(**intent_fields()));self.wait(lambda:service._queue.unfinished_tasks==0)
        service.stop();self.assertFalse(observe_entry_intent(**intent_fields()))
        self.assertFalse(service.snapshot()['health']['worker_alive'])

    def test_worker_disk_failure_isolated_bounded_and_sanitized(self):
        service=self.service();self.assertTrue(service.start());self.wait(lambda:service._last_heartbeat==NOW)
        with patch.object(service,'_consume',side_effect=sqlite3.OperationalError('private_bearer_secret')):
            self.assertTrue(observe_entry_intent(**intent_fields()));self.wait(lambda:service._queue.unfinished_tasks==0)
        value=service.snapshot();self.assertEqual(value['health']['last_error'],'OBSERVATION_FAILED')
        self.assertNotIn('private_bearer',json.dumps(value));self.assertEqual(value['health']['records'],0)
        self.assertTrue(service._thread.is_alive())

    def test_invalid_or_future_event_never_appends(self):
        service=self.initialized()
        with self.assertRaises(ValueError):service._consume(build_intent(**intent_fields(at=NOW+1)))
        event=build_intent(**intent_fields())
        with self.assertRaises(ValueError):service._consume(OpportunityEvent(event.encoded,'a'*64))
        self.assertEqual(service.snapshot()['health']['records'],0)

    def test_corrupt_snapshot_is_safe_unknown_and_does_not_create_schema(self):
        path=self.path/'opportunity-shadow.db';path.write_bytes(b'bad sqlite private token')
        before=path.read_bytes();value=opportunity_snapshot(self.path,now=NOW)
        self.assertEqual(value['state'],'UNAVAILABLE');self.assertEqual(value['scopes'],[])
        self.assertEqual(path.read_bytes(),before);self.assertNotIn('private token',json.dumps(value))

    def test_readonly_snapshot_leaves_all_database_bytes_and_schema_unchanged(self):
        service=self.initialized();self.consume(service)
        before=hashlib.sha256(service.path.read_bytes()).hexdigest()
        with closing(sqlite3.connect(service.path)) as db:
            schema=db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall()
        for _ in range(3):self.assertEqual(opportunity_snapshot(self.path,now=NOW)['health']['records'],1)
        self.assertEqual(hashlib.sha256(service.path.read_bytes()).hexdigest(),before)
        with closing(sqlite3.connect(service.path)) as db:
            self.assertEqual(db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY name').fetchall(),schema)

    def test_actual_sqlite_size_limit_stops_only_observation(self):
        service=self.initialized(max_bytes=65536)
        # Filling a real SQLite file is a finite storage test, not a throughput
        # benchmark for 45 fsync-heavy transactions on a shared Windows runner.
        for i in range(45):
            fields=intent_fields(origin_ref='limited-'+str(i))
            try:
                if service._consume(build_intent(**fields))=='RETENTION_FULL':break
            except sqlite3.Error as error:
                self.assertEqual(getattr(error,'sqlite_errorcode',None),sqlite3.SQLITE_FULL)
                break
        else:self.fail('bounded fixture did not reach the real SQLite capacity limit')
        with closing(sqlite3.connect(service.path)) as db:
            preserved=db.execute('SELECT id,data,assessment FROM opportunity_records ORDER BY sequence').fetchall()

        entered=threading.Event();release=threading.Event();attempted=threading.Event();finished=threading.Event()
        consume=service._consume;flush=service._flush_health
        def blocked_consume(event):
            entered.set()
            if not release.wait(3):raise AssertionError('test did not release the observer consumer')
            try:return consume(event)
            finally:attempted.set()
        def flushed_health(**kwargs):
            flush(**kwargs)
            # Completion includes task_done AND persisted health, rather than
            # racing the worker's finally block after unfinished_tasks hits 0.
            if attempted.is_set() and service._queue.unfinished_tasks==0:finished.set()
        with patch.object(service,'_consume',side_effect=blocked_consume), \
                patch.object(service,'_flush_health',side_effect=flushed_health):
            try:
                self.assertTrue(service.start())
                self.assertTrue(observe_entry_intent(**fields))
                self.assertTrue(entered.wait(3),'observer did not start the bounded handoff')
                # A separate engine returns from ingress while the consumer is
                # deliberately blocked. No financial path waits for this disk.
                self.assertTrue(observe_entry_intent(**intent_fields(engine='FUTURES',
                    environment='FUTURES_DEMO',origin_ref='other-engine-at-capacity')))
                self.assertFalse(release.is_set());self.assertFalse(finished.is_set())
                release.set()
                self.assertTrue(finished.wait(3),'observer did not finish the two bounded handoffs')
            finally:release.set()
        value=service.snapshot();self.assertEqual(value['health']['capacity_state'],'FULL')
        self.assertIn(value['health']['last_error'],('RETENTION_FULL','JOURNAL_FULL'))
        self.assertGreater(value['health']['errors']+value['health']['dropped'],0)
        self.assertEqual(value['state'],'PARTIAL');self.assertGreater(value['health']['records'],0)
        self.assertLess(value['health']['records'],45);self.assertLessEqual(service.path.stat().st_size,65536)
        self.assertTrue(service._thread.is_alive())
        with closing(sqlite3.connect(service.path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT id,data,assessment FROM opportunity_records ORDER BY sequence LIMIT ?',
                (len(preserved),)).fetchall(),preserved)

    def test_held_scenario_totals_keep_exact_decimal_precision(self):
        service=self.initialized();fields=intent_fields()
        fields['legs'][0].update(quantity='0.12345678901234567890123456789',
            reference_price='100.12345678901234567890123456789',stop_price='99',fee_rate='0.000000000000000000000000000001',slippage_rate='0')
        event=build_intent(**fields);service._consume(event)
        with closing(sqlite3.connect(service.path)) as db:
            metrics=json.loads(db.execute('SELECT metrics FROM opportunity_origins').fetchone()[0])
        from decimal import Context,Decimal,localcontext
        with localcontext(Context(prec=256)):
            expected=format(Decimal(metrics['committed_capital'])+Decimal(metrics['estimated_costs']),'f')
        self.assertEqual(service.snapshot()['scopes'][0]['hypothetical_reserved'],expected)

    def test_public_snapshot_is_bounded_retains_totals_and_native_stages(self):
        service=self.initialized()
        for i in range(9):self.consume(service,origin_ref=str(i))
        value=service.snapshot();self.assertLessEqual(len(canonical(value)),12000)
        self.assertLessEqual(len(value['recent_records']),6);self.assertEqual(value['health']['records'],9)
        self.assertEqual(value['coverage'][0]['intents'],9)
        self.assertTrue(all(record['stage']=='FINAL_ENTRY_INTENT' for record in value['recent_records']))
        self.assertNotIn('private-client-order',json.dumps(value))


if __name__=='__main__':unittest.main()
