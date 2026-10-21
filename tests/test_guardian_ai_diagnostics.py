"""Metadata diagnostics only: synthetic keys/transports/journals; no API calls."""
import copy
from contextlib import closing,redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader import guardian_ai as ai
from tests.test_guardian_ai import FakeOpener,Clock,FAKE_KEY,report,advisory,response_body


class GuardianAIDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        environment=patch.dict(os.environ,{'OPENAI_API_KEY':FAKE_KEY})
        environment.start();self.addCleanup(environment.stop)
        network=patch('urllib.request.urlopen',side_effect=AssertionError('real API forbidden'))
        network.start();self.addCleanup(network.stop)
        self.clock=Clock();self.sequence=0

    def reviewer(self,behavior):
        self.sequence+=1
        return ai.GuardianAIReviewer(self.root/str(self.sequence),daily_cap=2,clock=self.clock,opener=FakeOpener(behavior))

    def diagnostic(self,reviewer):
        with closing(sqlite3.connect(reviewer.path)) as db:
            row=db.execute('SELECT outcome,failure_code,result FROM guardian_ai_attempts').fetchone()
        self.assertEqual(row[:2],('FAILED','AI_COMMENTARY_INVALID'))
        value=json.loads(row[2]);self.assertEqual(ai._closed_commentary_diagnostic(value),value)
        self.assertNotIn(FAKE_KEY,reviewer.path.read_bytes().decode('latin1'))
        return value

    def test_each_validator_rejection_gets_exact_closed_subcode_without_changing_acceptance(self):
        identity=report()['assessment_id']
        cases=[('FIELD_SET',lambda value:None),('FIELD_SET',lambda value:{**value,'extra':FAKE_KEY}),
            ('SUMMARY_TYPE',lambda value:{**value,'summary':7}),
            ('SUMMARY_BOUNDS',lambda value:{**value,'summary':''}),
            ('SUMMARY_BOUNDS',lambda value:{**value,'summary':'😀'*281}),
            ('POSTURE_ENUM',lambda value:{**value,'posture':FAKE_KEY}),
            ('CAUTIONS_TYPE',lambda value:{**value,'cautions':{}}),
            ('CAUTIONS_COUNT',lambda value:{**value,'cautions':['x']*5}),
            ('CAUTION_TYPE',lambda value:{**value,'cautions':[7]}),
            ('CAUTION_BOUNDS',lambda value:{**value,'cautions':['x'*121]}),
            ('EVIDENCE_TYPE',lambda value:{**value,'evidence_ids':{}}),
            ('EVIDENCE_COUNT',lambda value:{**value,'evidence_ids':[]}),
            ('EVIDENCE_COUNT',lambda value:{**value,'evidence_ids':[identity]*5}),
            ('EVIDENCE_IDS',lambda value:{**value,'evidence_ids':[FAKE_KEY]}),
            ('EVIDENCE_IDS',lambda value:{**value,'evidence_ids':[['untrusted']]}),
            ('EVIDENCE_IDS',lambda value:{**value,'evidence_ids':[{'nonce':FAKE_KEY}]})]
        for expected,mutate in cases:
            invalid=mutate(advisory(identity))
            with self.subTest(expected=expected,kind=type(invalid).__name__):
                with self.assertRaises(ValueError):ai._validate_commentary(invalid,[identity])
                def body(request,invalid=invalid):
                    result=response_body(request);result['output_text']=json.dumps(invalid);return result
                reviewer=self.reviewer(body)
                result=reviewer(report())
                self.assertEqual(result,ai.GuardianAIReviewer._unavailable('AI_COMMENTARY_INVALID'))
                self.assertEqual(self.diagnostic(reviewer)['code'],expected)
                self.assertEqual(reviewer.health()['used_today'],1)
                self.assertEqual(len(reviewer.opener.calls),1)

    def test_parse_extraction_and_private_material_are_distinct_without_raw_text(self):
        for kind,expected in [('parse','JSON_DECODE'),('type','JSON_TEXT_TYPE'),
                              ('extract','TEXT_EXTRACTION'),('private','PRIVATE_MATERIAL')]:
            def body(request,kind=kind):
                result=response_body(request)
                if kind=='parse':result['output_text']='untrusted '+FAKE_KEY
                elif kind=='type':result['output_text']={'nonce':FAKE_KEY}
                elif kind=='extract':
                    result.pop('output_text');result['output']=[{'content':[{'type':'output_text','text':7}]}]
                else:
                    value=advisory(report()['assessment_id']);value['summary']=FAKE_KEY
                    result['output_text']=json.dumps(value)
                return result
            with self.subTest(kind=kind):
                reviewer=self.reviewer(body);self.assertEqual(reviewer(report())['reason'],'AI_COMMENTARY_INVALID')
                self.assertEqual(self.diagnostic(reviewer)['code'],expected)

    def test_valid_unicode_and_sanitization_still_accept_without_diagnostics(self):
        def body(request):
            result=response_body(request);value=advisory(report()['assessment_id'])
            value.update(summary='😀'*278+'\r\n',cautions=['é'*120])
            result['output_text']=json.dumps(value);return result
        reviewer=self.reviewer(body);result=reviewer(report())
        self.assertEqual(result['state'],'COMPLETED')
        self.assertEqual(result['commentary']['summary'],'😀'*278+'  ')
        self.assertIsNone(ai.guardian_ai_diagnostics(reviewer.path.parent)['attempts'][0]['diagnostic'])

    def test_failed_metadata_is_not_cached_and_consumes_existing_budget_across_restart(self):
        reviewer=self.reviewer(lambda request:{'status':'completed','output_text':'invalid'})
        reviewer(report());self.clock.now+=3601
        restarted=ai.GuardianAIReviewer(reviewer.path.parent,daily_cap=2,clock=self.clock,opener=FakeOpener())
        self.assertEqual(restarted(report(at=self.clock.now))['state'],'COMPLETED')
        self.clock.now+=1
        self.assertEqual(restarted(report(at=self.clock.now))['state'],'CACHED_HISTORICAL')
        self.assertEqual(restarted.health()['used_today'],2)
        self.clock.now+=3601
        self.assertEqual(restarted(report(at=self.clock.now))['reason'],'AI_BUDGET_OR_INTERVAL')
        self.assertEqual(len(restarted.opener.calls),1)

    def test_readonly_report_never_reads_completed_commentary_or_changes_sources(self):
        reviewer=self.reviewer(lambda request:{'status':'completed','output_text':'invalid'})
        reviewer(report())
        with closing(sqlite3.connect(reviewer.path)) as db,db:
            db.execute("INSERT INTO guardian_ai_attempts(at,day,fingerprint,assessment_id,model,outcome,reserved_estimate_usd,result) VALUES(?,?,?,?,?,'COMPLETED',0,?)",
                (self.clock.now,'2027-01-01','private','a'*64,ai.PRICE['model'],FAKE_KEY))
        before=hashlib.sha256(reviewer.path.read_bytes()).hexdigest()
        with patch.object(ai.GuardianAIReviewer,'__init__',side_effect=AssertionError('reader constructed client')):
            result=ai.guardian_ai_diagnostics(reviewer.path.parent)
        self.assertEqual(result['state'],'AVAILABLE');self.assertEqual(result['api_calls_made'],0)
        self.assertIsNone(result['attempts'][0]['diagnostic'])
        self.assertEqual(result['attempts'][1]['diagnostic']['code'],'JSON_DECODE')
        self.assertNotIn(FAKE_KEY,json.dumps(result))
        self.assertEqual(hashlib.sha256(reviewer.path.read_bytes()).hexdigest(),before)

    def test_tampered_subcode_types_counts_and_extension_text_are_not_projected(self):
        reviewer=self.reviewer(lambda request:{'status':'completed','output_text':'invalid'})
        reviewer(report());valid=self.diagnostic(reviewer)
        cases=[{**valid,'code':FAKE_KEY},{**valid,'extra':FAKE_KEY},{**valid,'text_type':FAKE_KEY},
               {**valid,'schema':True},{**valid,'text_chars':True},{**valid,'text_chars':32769},
               {**valid,'summary_chars':float('nan')},{**valid,'value_type':[]}]
        for invalid in cases:
            with closing(sqlite3.connect(reviewer.path)) as db,db:
                db.execute('UPDATE guardian_ai_attempts SET result=?',(json.dumps(invalid),))
            result=ai.guardian_ai_diagnostics(reviewer.path.parent)
            self.assertIsNone(result['attempts'][0]['diagnostic'])
            self.assertNotIn(FAKE_KEY,json.dumps(result))

    def test_absent_legacy_and_corrupt_journals_are_readonly_without_migration(self):
        missing=self.root/'absent'
        self.assertEqual(ai.guardian_ai_diagnostics(missing)['state'],'NOT_STARTED');self.assertFalse(missing.exists())
        directory=self.root/'legacy';directory.mkdir();path=directory/'guardian-ai.db'
        with closing(sqlite3.connect(path)) as db,db:
            db.execute('CREATE TABLE guardian_ai_attempts(id INTEGER,at REAL,model TEXT,outcome TEXT,input_tokens INTEGER,output_tokens INTEGER,cached_tokens INTEGER,result TEXT)')
            db.execute('INSERT INTO guardian_ai_attempts VALUES(1,?,?,?,?,?,?,?)',
                (self.clock.now,ai.PRICE['model'],'FAILED',None,None,None,None))
        before=path.read_bytes();result=ai.guardian_ai_diagnostics(directory)
        self.assertEqual(result['state'],'AVAILABLE');self.assertIsNone(result['attempts'][0]['failure_code'])
        self.assertEqual(path.read_bytes(),before)
        path.write_bytes(b'not sqlite private '+FAKE_KEY.encode())
        self.assertEqual(ai.guardian_ai_diagnostics(directory)['state'],'UNAVAILABLE')

    def test_cli_outputs_only_the_same_closed_metadata(self):
        from scripts.guardian_ai_diagnostics import main
        reviewer=self.reviewer(lambda request:{'status':'completed','output_text':'invalid'})
        reviewer(report());output=io.StringIO()
        with redirect_stdout(output):
            code=main(['--data-dir',str(reviewer.path.parent),'--limit','1'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(output.getvalue()),ai.guardian_ai_diagnostics(reviewer.path.parent,limit=1))


if __name__=='__main__':unittest.main()
