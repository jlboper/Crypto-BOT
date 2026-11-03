from contextlib import closing
from pathlib import Path
import sqlite3
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.evidence_review import review_retained_evidence, read_verified_cohort_snapshot
from trader.operational_cohort import FLAGS, OperationalCohortStore, iso
from trader.migration_evidence import FINGERPRINT_KEYS

NOW = 1793100000.0


class EvidenceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, script in (
            ('testnet-trader.db', 'CREATE TABLE trades(id INTEGER,side TEXT,realized_pnl REAL,fee REAL,created_at TEXT);'
             'CREATE TABLE equity(id INTEGER,equity REAL,created_at TEXT);'),
            ('futures-testnet.db', 'CREATE TABLE forward_trades(id INTEGER,direction TEXT,gross_pnl REAL,closed_at TEXT);'
             'CREATE TABLE forward_equity(id INTEGER,wallet_balance REAL,unrealized_pnl REAL,created_at TEXT);')):
            with closing(sqlite3.connect(self.root/name)) as db, db:
                db.executescript(script)
        with closing(sqlite3.connect(self.root/'testnet-trader.db')) as db, db:
            db.executemany('INSERT INTO trades VALUES(?,?,?,?,?)', [
                (1, 'BUY', 0, .1, iso(NOW-40*86400)), (2, 'SELL', 2, .2, iso(NOW-100))])
            db.executemany('INSERT INTO equity VALUES(?,?,?)', [
                (1, 100, iso(NOW-40*86400)), (2, 80, iso(NOW-100)), (3, 90, iso(NOW-10))])
        with closing(sqlite3.connect(self.root/'futures-testnet.db')) as db, db:
            db.execute('INSERT INTO forward_trades VALUES(?,?,?,?)', (1, 'SHORT', -1, iso(NOW-10)))
            db.execute('INSERT INTO forward_equity VALUES(?,?,?,?)', (1, 100, 1, iso(NOW-10)))

    def test_forty_days_preserved_without_authority_or_net_claim(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        value = review_retained_evidence(self.root, now=NOW)
        spot, futures = value['engines']
        self.assertEqual(spot['recorded_exit_rows'], 1)
        self.assertEqual(spot['recorded_realized_pnl'], '2.0')
        self.assertEqual(spot['sampled_max_drawdown_pct'], '20.0')
        self.assertGreater(spot['legacy']['local_span_days'], 39)
        self.assertIsNone(spot['fully_reconciled_net_pnl'])
        self.assertEqual(futures['pnl_basis'], 'GROSS')
        self.assertIsNone(futures['recorded_fees'])
        self.assertFalse(value['execution_enabled'])
        self.assertFalse(value['history_reset'])
        self.assertIn('FINANCIALLY_QUALIFIED_FORWARD_INCOMPLETE', value['blockers'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_future_rows_are_rejected(self):
        with closing(sqlite3.connect(self.root/'testnet-trader.db')) as db, db:
            db.execute('UPDATE trades SET created_at=? WHERE id=2', (iso(NOW+1),))
        value = review_retained_evidence(self.root, now=NOW)
        self.assertEqual(value['engines'][0]['state'], 'INVALID_OR_UNAVAILABLE_SOURCE')
        self.assertIsNone(value['engines'][0]['recorded_realized_pnl'])
        self.assertEqual(value['state'], 'REVIEW_INCOMPLETE')

    def test_missing_sources_are_not_created(self):
        missing = self.root/'absent'
        value = review_retained_evidence(missing, now=NOW)
        self.assertFalse(missing.exists())
        self.assertEqual(value['state'], 'REVIEW_INCOMPLETE')

    def test_row_budget_does_not_report_a_partial_sample_as_whole_history(self):
        with patch('trader.evidence_review.MAX_ROWS', 1):
            value = review_retained_evidence(self.root, now=NOW)
        self.assertTrue(value['engines'][0]['truncated'])
        self.assertEqual(value['engines'][0]['state'], 'ROW_LIMIT_REACHED')
        self.assertIsNone(value['engines'][0]['recorded_realized_pnl'])

    def test_corrupt_prospective_chain_is_not_used_for_qualification(self):
        store = OperationalCohortStore(self.root/'operational-cohorts.sqlite3')
        store.initialize()
        store.register('SPOT', 'SPOT_TESTNET', {key: 'a'*64 for key in FINGERPRINT_KEYS}, now=NOW-1000)
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute('DROP TRIGGER observations_no_update')
            db.execute('UPDATE observations SET at=at+1')
        value = review_retained_evidence(self.root, now=NOW)
        self.assertEqual(value['cohort_chain']['state'], 'INVALID')
        self.assertEqual(value['cohorts'], [])
        self.assertIn('COHORT_CHAIN_INVALID', value['blockers'])

    def test_nonfinite_result_is_not_reported_as_profit(self):
        with closing(sqlite3.connect(self.root/'testnet-trader.db')) as db, db:
            db.execute('UPDATE trades SET realized_pnl=? WHERE id=2', ('Infinity',))
        value = review_retained_evidence(self.root, now=NOW)
        self.assertIsNone(value['engines'][0]['recorded_realized_pnl'])
        self.assertEqual(value['engines'][0]['state'], 'INVALID_OR_UNAVAILABLE_SOURCE')

    def test_thirty_one_supplied_qualified_days_never_grant_activation(self):
        store = OperationalCohortStore(self.root/'operational-cohorts.sqlite3')
        store.initialize()
        start = int(NOW//86400)*86400-31*86400
        registrations = [store.register(engine, environment, {key: 'b'*64 for key in FINGERPRINT_KEYS},
                          cadence_seconds=86400, max_receipt_delay_seconds=60, now=start)
                         for engine, environment in (('SPOT', 'SPOT_TESTNET'), ('FUTURES', 'FUTURES_DEMO'))]
        for day in range(32):
            for reg in registrations:
                store.observe(reg, {key: True for key in FLAGS}, now=start+day*86400)
        value = review_retained_evidence(self.root, now=NOW)
        self.assertTrue(all(row['qualified_days'] == 31 for row in value['cohorts']))
        # Chained caller flags retain their historical meaning; they are not
        # original account/fill/fee/protection sources for outcome qualification.
        self.assertIn('FINANCIALLY_QUALIFIED_FORWARD_INCOMPLETE', value['blockers'])
        self.assertTrue(all(row['financial_qualified_days'] is None for row in value['cohorts']))
        self.assertIn('OWNER_ACTIVATION_REQUIRED', value['blockers'])
        self.assertIn('INDEPENDENT_OOS_EVIDENCE_UNPROVEN', value['blockers'])
        self.assertFalse(value['execution_enabled'])
        self.assertFalse(value['financial_authorization'])

    def _one_incomplete_receipt(self):
        store = OperationalCohortStore(self.root/'operational-cohorts.sqlite3')
        store.initialize()
        start = int(NOW//300)*300-600
        reg = store.register('SPOT', 'SPOT_TESTNET', {key: 'c'*64 for key in FINGERPRINT_KEYS}, now=start)
        for at in (start, start+300):
            store.observe(reg, {key: False for key in FLAGS}, now=at)
        return store

    def test_qualification_cache_tampering_is_detected_with_intact_observation_chain(self):
        store = self._one_incomplete_receipt()
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute('DROP TRIGGER receipts_no_update')
            db.execute('UPDATE receipts SET financial=1')
        self.assertEqual(store.verify_chain()['state'], 'VALID_LOCAL_CHAIN')
        value = review_retained_evidence(self.root, now=NOW)
        self.assertEqual(value['cohorts'], [])
        self.assertIn('COHORT_AUDIT_UNAVAILABLE', value['blockers'])

    def test_edited_receipt_flags_cannot_override_chained_original_capture(self):
        store = self._one_incomplete_receipt()
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute('DROP TRIGGER receipts_no_update')
            receipt = json.loads(db.execute('SELECT payload FROM receipts').fetchone()[0])
            receipt.update({flag: True for flag in FLAGS})
            db.execute('UPDATE receipts SET payload=?,operational=1,financial=1', (json.dumps(receipt),))
        value = review_retained_evidence(self.root, now=NOW)
        self.assertEqual(value['cohorts'], [])
        self.assertIn('COHORT_AUDIT_UNAVAILABLE', value['blockers'])

    def test_cohort_scope_and_ordering_metadata_are_bound_to_registered_event(self):
        store = self._one_incomplete_receipt()
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute('DROP TRIGGER cohorts_no_update')
            db.execute("UPDATE cohorts SET engine='FUTURES',environment='FUTURES_DEMO',registered=registered+1")
        self.assertEqual(store.verify_chain()['state'], 'VALID_LOCAL_CHAIN')
        value = review_retained_evidence(self.root, now=NOW)
        self.assertEqual(value['cohorts'], [])
        self.assertIn('COHORT_AUDIT_UNAVAILABLE', value['blockers'])

    def test_exit_row_count_does_not_claim_fully_closed_episodes(self):
        value = review_retained_evidence(self.root, now=NOW)
        self.assertEqual(value['engines'][0]['recorded_exit_rows'], 1)
        self.assertNotIn('observed_closes', value['engines'][0])
        self.assertIn('CLOSED_EPISODE_LINKAGE', value['engines'][0]['unproven'])

    def test_original_fractional_registration_keeps_canonical_microsecond_precision(self):
        store = OperationalCohortStore(self.root/'operational-cohorts.sqlite3')
        store.initialize()
        store.register('SPOT', 'SPOT_TESTNET', {key: 'd'*64 for key in FINGERPRINT_KEYS}, now=NOW-1000+.1234567)
        value = review_retained_evidence(self.root, now=NOW)
        self.assertNotIn('COHORT_AUDIT_UNAVAILABLE', value['blockers'])
        self.assertEqual(len(value['cohorts']), 1)

    def financial_scope(self, engine='SPOT', days=1):
        """Real chained operational receipts plus synthetic complete packets."""
        from copy import deepcopy
        from trader.financial_evidence import AUTHORITY as FINANCIAL_AUTHORITY
        from trader.financial_evidence_io import ingest_financial_files
        from tests.test_financial_evidence import ACCOUNT, fixture, reseal
        store = OperationalCohortStore(self.root/'operational-cohorts.sqlite3')
        if not store.path.exists():
            store.initialize()
        start = int(NOW//86400)*86400-days*86400
        environment = 'SPOT_TESTNET' if engine == 'SPOT' else 'FUTURES_DEMO'
        registrations = {name: store.register(name, scope, {key: 'e'*64 for key in FINGERPRINT_KEYS},
            cadence_seconds=86400, max_receipt_delay_seconds=60, now=start)
            for name, scope in (('SPOT', 'SPOT_TESTNET'), ('FUTURES', 'FUTURES_DEMO'))}
        reg = registrations[engine]
        for day in range(days+1):
            at = start+day*86400
            for registered in registrations.values():
                store.observe(registered, {**{key: key == 'source_complete' for key in FLAGS},
                    'source_at':iso(at), 'state':'OBSERVED_LOCAL'}, now=at)
        directory = self.root/'testnet-financial-capture'/environment
        directory.mkdir(parents=True, exist_ok=True)
        with closing(store.connect(True)) as db:
            originals = [json.loads(row[0]) for row in db.execute('SELECT payload FROM receipts WHERE cohort=? ORDER BY slot',
                (digest_registration(reg),))]
        for original in originals:
            bundle = deepcopy(fixture(engine=engine)[2])
            bundle.update(environment=environment, unit_scale=8, window_start=original['interval_start'], window_end=original['interval_end'])
            for name in ('ledger', 'exchange'):
                cut = bundle[name]
                cut['environment'] = environment
                cut['coverage'].update(start=original['interval_start'], end=original['interval_end'], received_at=iso(NOW))
            bundle['protection_coverage'].update(start=original['interval_start'], end=original['interval_end'], received_at=iso(NOW))
            reseal(bundle)
            for name, body in (('registration.json', reg), ('original.json', original), ('bundle.json', bundle)):
                (directory/name).write_text(json.dumps(body), encoding='utf-8')
            saved = ingest_financial_files(directory/'registration.json', directory/'original.json', directory/'bundle.json',
                journal_path=directory/'financial-evidence.sqlite3', anchor_path=directory/'financial-evidence.anchor.json', clock=lambda:iso(NOW))
            self.assertTrue(saved['supplied_window_complete'], saved)
        binding = {'schema':1, 'environment':environment, 'cohort_digest':digest_registration(reg), 'account_ref':ACCOUNT,
            'unit_scale':8, 'identity_state':'REPORTED', **FINANCIAL_AUTHORITY}
        (directory/'binding.json').write_text(json.dumps(binding), encoding='utf-8')
        return store, reg, directory

    def test_reconciled_outcome_overlay_qualifies_today_without_rewriting_original_inputs(self):
        store, _, _ = self.financial_scope(days=1)
        before = {path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        value = review_retained_evidence(self.root, now=NOW)
        row = value['cohorts'][0]
        self.assertEqual(row['operational_coverage_days'], 1)
        self.assertIsNone(row['qualified_days'])
        self.assertEqual(row['financial_continuous_qualified_days'], 1)
        self.assertTrue(row['financial_overlay']['coverage_verified'])
        self.assertEqual(row['financial_overlay']['late_reconciled_windows'], 1)
        self.assertEqual(before, {path:path.read_bytes() for path in before})
        self.assertEqual(store.snapshot(now=NOW)['scopes'][0]['valid_receipts'], 0)
        self.assertFalse(value['execution_enabled'])

    def test_thirty_financial_days_in_both_current_scopes_remove_only_the_forward_blocker(self):
        self.financial_scope('SPOT', days=30)
        self.financial_scope('FUTURES', days=30)
        value = review_retained_evidence(self.root, now=NOW)
        self.assertTrue(all(row['financial_continuous_qualified_days'] == 30 for row in value['cohorts']))
        self.assertNotIn('FINANCIALLY_QUALIFIED_FORWARD_INCOMPLETE', value['blockers'])
        self.assertIn('OWNER_ACTIVATION_REQUIRED', value['blockers'])
        self.assertIn('INDEPENDENT_OOS_EVIDENCE_UNPROVEN', value['blockers'])
        self.assertFalse(value['financial_authorization'])

    def test_overlay_requires_original_binding_and_current_cohort_not_cached_flags(self):
        store, reg, directory = self.financial_scope()
        binding_path = directory/'binding.json'
        original = json.loads(binding_path.read_text())
        changes = ({'identity_state':'UNKNOWN'}, {'account_ref':'b'*64}, {'unit_scale':6}, {'execution_enabled':True},
                   {'cohort_digest':'b'*64}, {'environment':'FUTURES_DEMO'}, {'manual_qualified_days':30})
        for change in changes:
            binding_path.write_text(json.dumps({**original, **change}), encoding='utf-8')
            value = read_verified_cohort_snapshot(self.root, now=NOW)
            self.assertIsNone(value['scopes'][0]['financial_continuous_qualified_days'], change)
        binding_path.write_text(json.dumps(original), encoding='utf-8')
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute('DROP TRIGGER receipts_no_update')
            db.execute('UPDATE receipts SET financial=1')
        self.assertEqual(read_verified_cohort_snapshot(self.root, now=NOW)['scopes'], [])

    def test_unknown_anchor_future_outcome_and_changed_registration_cannot_rescue_qualification(self):
        store, reg, directory = self.financial_scope()
        value = read_verified_cohort_snapshot(self.root, now=NOW-1)
        self.assertIsNone(value['scopes'][0]['financial_continuous_qualified_days'])
        anchor = directory/'financial-evidence.anchor.json'
        retained = anchor.read_text()
        changed = json.loads(retained); changed['tail']='f'*64
        anchor.write_text(json.dumps(changed), encoding='utf-8')
        self.assertIsNone(read_verified_cohort_snapshot(self.root, now=NOW)['scopes'][0]['financial_qualified_days'])
        anchor.write_text(retained, encoding='utf-8')
        store.register('SPOT', 'SPOT_TESTNET', {key:'f'*64 for key in FINGERPRINT_KEYS}, cadence_seconds=86400, now=NOW-1)
        active = [row for row in read_verified_cohort_snapshot(self.root, now=NOW)['scopes'] if row['active'] and row['engine'] == 'SPOT']
        self.assertEqual(len(active), 1)
        self.assertIsNone(active[0]['financial_qualified_days'])

    def test_expired_read_budget_returns_unknown_without_creating_evidence(self):
        self.financial_scope()
        with patch('trader.evidence_review.time.monotonic', side_effect=[0, 4]):
            value = read_verified_cohort_snapshot(self.root, now=NOW)
        self.assertEqual(value['state'], 'UNAVAILABLE')
        self.assertEqual(value['scopes'], [])


def digest_registration(registration):
    from trader.migration_evidence import register_forward_cohort
    return register_forward_cohort(registration).digest
