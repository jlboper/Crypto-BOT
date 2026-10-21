import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.evidence_backup import backup_evidence


class EvidenceBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.path = self.source / 'opportunity-shadow.db'

    def database(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY, evidence TEXT)')
        db.executemany('INSERT INTO events VALUES(?,?)', [(i, 'evidence-' + str(i)) for i in range(100)])
        db.commit()
        return db

    def test_wal_copy_restores_all_committed_rows_and_preserves_source(self):
        db = self.database()
        self.addCleanup(db.close)
        before = db.execute('SELECT * FROM events ORDER BY id').fetchall()
        result = backup_evidence(self.source, self.root / 'copy', names=['opportunity-shadow.db'])
        self.assertEqual(result['state'], 'VERIFIED_COPIES')
        self.assertFalse(result['globally_atomic'])
        self.assertFalse(result['account_baseline_certified'])
        with closing(sqlite3.connect(self.root / 'copy' / self.path.name)) as restored:
            self.assertEqual(restored.execute('SELECT * FROM events ORDER BY id').fetchall(), before)
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone(), ('ok',))
        self.assertEqual(db.execute('SELECT * FROM events ORDER BY id').fetchall(), before)
        copied = self.root / 'copy' / self.path.name
        self.assertEqual(result['files'][0]['sha256'], hashlib.sha256(copied.read_bytes()).hexdigest())
        manifest = json.loads((self.root / 'copy' / 'manifest.json').read_text())
        self.assertEqual(manifest, result)
        self.assertNotIn('evidence-1', json.dumps(manifest))

    def test_uncommitted_write_is_absent_and_writer_remains_usable(self):
        db = self.database()
        self.addCleanup(db.close)
        db.execute("INSERT INTO events VALUES(100,'not committed')")
        result = backup_evidence(self.source, self.root / 'copy', names=['opportunity-shadow.db'])
        self.assertEqual(result['state'], 'VERIFIED_COPIES')
        with closing(sqlite3.connect(self.root / 'copy' / self.path.name)) as restored:
            self.assertEqual(restored.execute('SELECT count(*) FROM events').fetchone()[0], 100)
        db.commit()
        self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 101)

    def test_missing_sources_are_not_recreated_or_reported_verified(self):
        report = backup_evidence(self.source, self.root / 'copy', names=['guardian-shadow.db'])
        self.assertEqual(report['state'], 'INCOMPLETE')
        self.assertEqual(report['files'][0]['state'], 'NOT_FOUND')
        self.assertFalse((self.source / 'guardian-shadow.db').exists())
        self.assertFalse((self.root / 'copy' / 'guardian-shadow.db').exists())

    def test_existing_output_is_never_overwritten(self):
        output = self.root / 'copy'
        output.mkdir()
        marker = output / 'manifest.json'
        marker.write_text('keep')
        with self.assertRaises(FileExistsError):
            backup_evidence(self.source, output, names=['guardian-shadow.db'])
        self.assertEqual(marker.read_text(), 'keep')

    def test_bad_requests_and_source_dest_overlap_fail_before_creation(self):
        for names in [[], ['.env.local'], ['../opportunity-shadow.db'], ['guardian-shadow.db'] * 2]:
            with self.assertRaises(ValueError):
                backup_evidence(self.source, self.root / 'copy', names=names)
        for target in [self.source, self.source / 'child']:
            with self.assertRaises(ValueError):
                backup_evidence(self.source, target)
        for timeout in [float('nan'), float('inf'), 0, -1, 121, True]:
            with self.assertRaises(ValueError):
                backup_evidence(self.source, self.root / 'copy', timeout_seconds=timeout)
        self.assertFalse((self.root / 'copy').exists())

    def test_corruption_is_retained_as_incomplete_with_safe_error(self):
        self.path.write_bytes(b'not a database / private text')
        result = backup_evidence(self.source, self.root / 'copy', names=[self.path.name])
        self.assertEqual(result['state'], 'INCOMPLETE')
        self.assertEqual(result['files'][0]['error'], 'COPY_OR_INTEGRITY_FAILED')
        self.assertNotIn('private text', json.dumps(result))
        self.assertEqual(self.path.read_bytes(), b'not a database / private text')

    def test_failed_copy_does_not_prevent_independent_source_backup(self):
        db = self.database()
        db.close()
        (self.source / 'guardian-shadow.db').write_bytes(b'corrupt')
        report = backup_evidence(self.source, self.root / 'copy', names=['guardian-shadow.db', self.path.name])
        self.assertEqual([row['state'] for row in report['files']], ['INCOMPLETE', 'VERIFIED_COPY'])

    def test_abrupt_interruption_leaves_incomplete_manifest_without_touching_source(self):
        db = self.database()
        db.close()
        before = self.path.read_bytes()
        with patch('trader.evidence_backup.sqlite3.connect', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                backup_evidence(self.source, self.root / 'copy', names=[self.path.name])
        manifest = json.loads((self.root / 'copy' / 'manifest.json').read_text())
        self.assertEqual(manifest['state'], 'INCOMPLETE')
        self.assertIsNone(manifest['completed_at'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_copy_deadline_retains_incomplete_evidence_and_source_remains_readable(self):
        db = self.database()
        db.close()
        with patch('trader.evidence_backup.time.monotonic', side_effect=[0, 100]):
            result = backup_evidence(self.source, self.root / 'copy', names=[self.path.name])
        self.assertEqual(result['state'], 'INCOMPLETE')
        with closing(sqlite3.connect(self.path)) as source:
            self.assertEqual(source.execute('SELECT count(*) FROM events').fetchone()[0], 100)


if __name__ == '__main__':
    unittest.main()
