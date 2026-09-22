import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from trader.remote_jobs import RemoteJobs

class RemoteJobTests(unittest.TestCase):
    def test_install_requires_exact_persisted_approval(self):
        with tempfile.TemporaryDirectory() as directory, patch('trader.remote_jobs.subprocess.Popen') as spawn:
            jobs = RemoteJobs(directory, directory)
            job = {'id': 4, 'action': 'update_install', 'expires': time.time()+100}
            for invalid in (None, '', 'latest', 'A'*64, 'a'*63):
                with self.assertRaises(ValueError):
                    jobs.accept({**job, 'release_id': invalid})
            spawn.assert_not_called()
            job['release_id'] = 'a'*64
            jobs.accept(job)
            jobs.accept(job)
            self.assertEqual(jobs._read(jobs.directory/'4.json')['release_id'], 'a'*64)
            with self.assertRaisesRegex(ValueError, 'identifier conflict'):
                jobs.accept({**job, 'release_id': 'b'*64})
            self.assertEqual(spawn.call_count, 1)

    def test_restore_requires_exact_persisted_snapshot_identifier(self):
        with tempfile.TemporaryDirectory() as directory, patch('trader.remote_jobs.subprocess.Popen') as spawn:
            jobs=RemoteJobs(directory,directory)
            for invalid in ('latest','A'*64,'a'*63):
                with self.assertRaises(ValueError):
                    jobs.accept({'id':5,'action':'update_restore','expires':time.time()+100,'release_id':invalid})
            jobs.accept({'id':5,'action':'update_restore','expires':time.time()+100,'release_id':'a'*64})
            self.assertEqual(spawn.call_count,1)

    def test_persisted_job_is_started_once_and_results_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch('trader.remote_jobs.subprocess.Popen') as spawn:
            jobs=RemoteJobs(directory,directory)
            job={'id':1,'action':'research','expires':time.time()+100}
            jobs.accept(job)
            RemoteJobs(directory,directory).accept(job)
            self.assertEqual(spawn.call_count,1)
            self.assertNotIn('shell',spawn.call_args.kwargs)
            self.assertIn('remote_job.py',spawn.call_args.args[0][1])
            jobs.finish(1,'completed','Done')
            result=RemoteJobs(directory,directory).results()[0]
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['action'],'research')

    def test_expired_or_arbitrary_jobs_cannot_spawn(self):
        with tempfile.TemporaryDirectory() as directory, patch('trader.remote_jobs.subprocess.Popen') as spawn:
            jobs=RemoteJobs(directory,directory)
            for job in [{'id':1,'action':'shell','expires':time.time()+100},{'id':2,'action':'research','expires':0}]:
                with self.assertRaises(ValueError):jobs.accept(job)
            spawn.assert_not_called()

    def test_spawn_failure_is_durable_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch('trader.remote_jobs.subprocess.Popen',side_effect=OSError) as spawn:
            jobs=RemoteJobs(directory,directory)
            job={'id':1,'action':'research','expires':time.time()+100}
            jobs.accept(job);jobs.accept(job)
            self.assertEqual(jobs.results()[0]['status'],'failed')
            self.assertEqual(spawn.call_count,1)

    def test_identifier_conflict_is_rejected_without_a_second_spawn(self):
        with tempfile.TemporaryDirectory() as directory, patch('trader.remote_jobs.subprocess.Popen') as spawn:
            jobs=RemoteJobs(directory,directory)
            jobs.accept({'id':7,'action':'research','expires':time.time()+100})
            with self.assertRaises(ValueError):
                jobs.accept({'id':7,'action':'update_check','expires':time.time()+100})
            self.assertEqual(spawn.call_count,1)

    def test_timeout_is_terminal_and_damaged_records_do_not_break_heartbeats(self):
        with tempfile.TemporaryDirectory() as directory, patch('trader.remote_jobs.subprocess.Popen'):
            jobs=RemoteJobs(directory,directory)
            jobs.accept({'id':1,'action':'research','expires':time.time()+100})
            record=jobs.directory/'1.json'
            data=jobs._read(record);data['at']=time.time()-7201;jobs._replace(record,data)
            self.assertEqual(jobs.results()[0]['status'],'failed')
            self.assertFalse(jobs.finish(1,'completed','Late completion'))
            self.assertEqual(jobs.results()[0]['status'],'failed')
            (jobs.directory/'2.json').write_text('{broken',encoding='utf-8')
            (jobs.directory/'notes.json').write_text('{}',encoding='utf-8')
            self.assertEqual([item['id'] for item in jobs.results()],[1])
