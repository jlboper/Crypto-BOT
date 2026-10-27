"""Explicit packet files, separate SQLite, atomic anchors; never real data."""
from contextlib import closing, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.financial_evidence import AUTHORITY, canonical
from trader.financial_evidence_io import (ingest_financial_files, read_financial_overlay,
    read_retained_json)
from trader.migration_evidence import register_forward_cohort
from scripts.ingest_financial_evidence import main
from tests.test_financial_evidence import ACCOUNT, POSITION, fixture, iso, reseal


class ExplicitFinancialIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.journal=self.root/'financial-evidence.sqlite3';self.anchor=self.root/'financial-evidence.anchor.json'
        self.reg=self.root/'registration.json';self.original=self.root/'original.json';self.bundle=self.root/'bundle.json'
        self.originals=self.root/'originals.json'
        self.f=fixture(held=True);self.write(self.f)

    def write(self,f):
        for path,value in ((self.reg,f[0]),(self.original,f[1]),(self.bundle,f[2]),(self.originals,[f[1]])):
            path.write_text(canonical(value),encoding='utf-8')

    def ingest(self,*,now=None,reconcile=False):
        return ingest_financial_files(self.reg,self.original,self.bundle,journal_path=self.journal,
            anchor_path=self.anchor,reconcile_anchor=reconcile,clock=lambda:iso(now or self.f[3]))

    def overlay(self,*,now=None,**changes):
        return read_financial_overlay(self.journal,self.anchor,self.f[0],[self.f[1]],
            **{'now':iso(now or self.f[3]),'expected_cohort_digest':register_forward_cohort(self.f[0]).digest,
               'expected_account_ref':ACCOUNT,'expected_unit_scale':6,**changes})

    def test_ingest_retains_one_window_without_touching_original_files(self):
        before={p:p.read_bytes() for p in (self.reg,self.original,self.bundle,self.originals)}
        result=self.ingest()
        self.assertEqual(result['state'],'PACKET_RETAINED');self.assertTrue(result['packet_received'])
        self.assertTrue(result['supplied_window_complete']);self.assertFalse(result['coverage_verified'])
        self.assertFalse(result['external_attestation']);self.assertFalse(result['automatic_source_producer'])
        self.assertTrue(all(result[k] is False for k in AUTHORITY))
        projection=self.overlay();self.assertTrue(projection['coverage_verified'])
        self.assertEqual(projection['valid_windows'],1);self.assertEqual(projection['qualified_days'],0)
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        for private in (POSITION,ACCOUNT,'100000','quantity_units','balance_start_units'):
            self.assertNotIn(private,canonical(projection));self.assertNotIn(private,canonical(result))

    def test_duplicate_keeps_anchor_bytes_and_receipt_time_unchanged(self):
        from datetime import timedelta
        self.ingest();anchor=self.anchor.read_bytes();raw=self.journal.read_bytes()
        result=self.ingest(now=self.f[3]+timedelta(hours=3))
        self.assertEqual(result['state'],'PACKET_ALREADY_RETAINED');self.assertTrue(result['duplicate'])
        self.assertEqual(anchor,self.anchor.read_bytes());self.assertEqual(raw,self.journal.read_bytes())

    def test_partial_sources_are_received_but_do_not_prove_coverage(self):
        f=deepcopy(self.f);f[2]['exchange']['coverage']['fills_exhausted']=False;reseal(f[2]);self.write(f)
        result=self.ingest();self.assertTrue(result['packet_received']);self.assertFalse(result['supplied_window_complete'])
        projection=self.overlay();self.assertTrue(projection['journal_verified'])
        self.assertFalse(projection['coverage_verified']);self.assertEqual(projection['valid_windows'],0)

    def test_unknown_files_bad_json_duplicate_keys_and_oversize_are_closed(self):
        for raw in ('{"schema":1,"schema":1}','{"value":NaN}','x'*262145):
            self.bundle.write_text(raw)
            self.assertEqual(self.ingest()['state'],'RETAINED_PACKET_REJECTED')
            self.assertFalse(self.journal.exists());self.assertFalse(self.anchor.exists())
        missing=self.root/'missing.json'
        with self.assertRaises(ValueError):read_retained_json(missing)
        self.assertFalse(missing.exists())

    def test_manual_completeness_flags_and_concurrent_writer_fail_closed(self):
        f=deepcopy(self.f);f[2]['financial_window_complete']=True;self.write(f)
        self.assertEqual(self.ingest()['state'],'RETAINED_PACKET_REJECTED')
        self.assertFalse(self.journal.exists())
        self.write(self.f)
        from trader.financial_evidence_io import _writer_lock
        with _writer_lock(Path(str(self.journal)+'.ingest.lock')):
            self.assertEqual(self.ingest()['state'],'RETAINED_PACKET_REJECTED')
        self.assertFalse(self.journal.exists());self.assertEqual(self.ingest()['state'],'PACKET_RETAINED')

    def test_input_output_alias_and_operating_database_are_rejected(self):
        result=ingest_financial_files(self.reg,self.original,self.bundle,journal_path=self.bundle,
            anchor_path=self.anchor,clock=lambda:iso(self.f[3]))
        self.assertEqual(result['state'],'RETAINED_PACKET_REJECTED')
        with closing(sqlite3.connect(self.journal)) as db,db:db.execute('CREATE TABLE trades(id INTEGER)')
        before=self.journal.read_bytes()
        self.assertEqual(self.ingest()['state'],'RETAINED_PACKET_REJECTED');self.assertEqual(before,self.journal.read_bytes())
        with closing(sqlite3.connect(self.journal)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE name='financial_receipts'").fetchall(),[])

    def test_dotdot_output_alias_preserves_retained_input(self):
        (self.root/'nested').mkdir()
        before=self.bundle.read_bytes()
        result=ingest_financial_files(self.reg,self.original,self.bundle,journal_path=self.journal,
            anchor_path=self.root/'nested'/'..'/self.bundle.name,clock=lambda:iso(self.f[3]))
        self.assertEqual(result['state'],'RETAINED_PACKET_REJECTED')
        self.assertEqual(before,self.bundle.read_bytes());self.assertFalse(self.journal.exists())

    def test_ingest_lock_does_not_write_before_acquiring_ownership(self):
        from trader.financial_evidence_io import _writer_lock
        lock=Path(str(self.journal)+'.ingest.lock')
        with _writer_lock(lock):
            self.assertEqual(lock.stat().st_size,0)
        self.assertEqual(lock.read_bytes(),b'')

    def test_hardlinks_and_symlinks_cannot_redirect_ingest(self):
        linked=self.root/'hardlinked.json';os.link(self.bundle,linked)
        self.assertEqual(self.ingest()['state'],'RETAINED_PACKET_REJECTED')
        linked.unlink()
        with patch.object(Path,'is_symlink',lambda self:True):
            self.assertEqual(self.ingest()['state'],'RETAINED_PACKET_REJECTED')

    def test_missing_read_is_pure_and_wrong_account_or_cohort_cannot_qualify(self):
        before=sorted(p.name for p in self.root.iterdir())
        self.assertEqual(self.overlay()['valid_windows'],0)
        self.assertEqual(before,sorted(p.name for p in self.root.iterdir()))
        self.ingest()
        for changes in ({'expected_account_ref':'a'*64},{'expected_cohort_digest':'b'*64},{'expected_unit_scale':2}):
            self.assertEqual(self.overlay(**changes)['valid_windows'],0)

    def test_old_or_replaced_anchor_cannot_qualify_later_commit(self):
        self.ingest();old=self.anchor.read_bytes();nxt=fixture(1,held=True);self.write(nxt)
        self.assertEqual(self.ingest(now=nxt[3])['state'],'PACKET_RETAINED')
        self.anchor.write_bytes(old)
        self.assertFalse(self.overlay(now=nxt[3])['journal_verified'])
        self.assertEqual(self.ingest(now=nxt[3])['state'],'ANCHOR_RECONCILIATION_REQUIRED')
        self.assertEqual(self.ingest(now=nxt[3],reconcile=True)['state'],'ANCHOR_RECONCILED')

    def test_failed_anchor_publication_blocks_until_exact_packet_reconciliation(self):
        with patch('trader.financial_evidence_io._atomic_anchor',side_effect=OSError('synthetic anchor failure')):
            result=self.ingest()
        self.assertEqual(result['state'],'JOURNAL_COMMITTED_ANCHOR_PENDING');self.assertTrue(self.journal.exists())
        self.assertFalse(self.anchor.exists());self.assertFalse(self.overlay()['journal_verified'])
        self.assertEqual(self.ingest()['state'],'ANCHOR_RECONCILIATION_REQUIRED')
        f=deepcopy(self.f);f[2]['ledger']['balance_end_units']+=1;reseal(f[2]);self.write(f)
        self.assertEqual(self.ingest(reconcile=True)['state'],'RETAINED_PACKET_REJECTED')
        self.write(self.f);self.assertEqual(self.ingest(reconcile=True)['state'],'ANCHOR_RECONCILED')
        self.assertEqual(self.overlay()['valid_windows'],1)

    def test_process_crash_after_commit_before_anchor_fails_closed(self):
        script='''import os,sys
sys.path.insert(0,sys.argv[1])
import trader.financial_evidence_io as m
m._atomic_anchor=lambda *args:os._exit(9)
m.ingest_financial_files(*sys.argv[2:5],journal_path=sys.argv[5],anchor_path=sys.argv[6])
'''
        process=subprocess.run([sys.executable,'-I','-B','-c',script,str(Path(__file__).resolve().parents[1]),
            str(self.reg),str(self.original),str(self.bundle),str(self.journal),str(self.anchor)],capture_output=True,timeout=15)
        self.assertEqual(process.returncode,9,process.stderr.decode(errors='replace'))
        self.assertEqual(process.stdout,b'');self.assertFalse(self.anchor.exists())
        self.assertFalse(self.overlay()['journal_verified'])
        # Child used current UTC, so reconcile at current UTC rather than a
        # synthetic earlier clock; preserved available_at must not be backdated.
        from datetime import UTC,datetime
        now=datetime.now(UTC)
        self.assertEqual(self.ingest(now=now,reconcile=True)['state'],'ANCHOR_RECONCILED')
        self.assertEqual(self.overlay(now=now)['valid_windows'],1)

    def test_late_receipt_and_anchor_are_unavailable_at_earlier_asof(self):
        from datetime import timedelta
        late=self.f[3]+timedelta(days=3);self.ingest(now=late)
        self.assertEqual(self.overlay(now=late-timedelta(seconds=1))['valid_windows'],0)
        today=self.overlay(now=late);self.assertEqual(today['valid_windows'],1)
        self.assertEqual(today['late_reconciled_windows'],1)
        self.assertFalse(json.loads(self.original.read_text())['reconciled'])

    def test_cli_sanitizes_errors_rejects_backdating_and_reads_coverage(self):
        base=['--registration',str(self.reg),'--journal',str(self.journal),'--anchor',str(self.anchor)]
        def call(args):
            capture=io.StringIO()
            with redirect_stdout(capture):code=main(args)
            return code,capture.getvalue(),json.loads(capture.getvalue())
        code,text,result=call(base+['--original',str(self.original),'--bundle',str(self.bundle)])
        self.assertEqual(code,0);self.assertFalse(result['coverage_verified'])
        code,text,result=call(base+['--coverage','--originals',str(self.originals),'--cohort-digest',
            register_forward_cohort(self.f[0]).digest,'--account-ref',ACCOUNT,'--unit-scale','6'])
        self.assertEqual(code,0);self.assertEqual(result['valid_windows'],1)
        for args in (['--unexpected','secret-value'],base+['--now',iso(self.f[3])]):
            code,text,result=call(args);self.assertEqual(code,2);self.assertNotIn('secret-value',text)
        self.assertNotIn(POSITION,text);self.assertNotIn(ACCOUNT,text)


if __name__=='__main__':unittest.main()
