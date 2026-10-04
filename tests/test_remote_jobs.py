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


class RemoteUpdateCompletionTests(unittest.TestCase):
    def setUp(self):
        import json
        from scripts import remote_job
        self.runner=remote_job
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'agent'
        self.source=Path(temporary.name)/'bot'
        self.source.mkdir()
        (self.root/'data/portal-jobs').mkdir(parents=True)
        (self.root/'data/trusted-update.pub').write_text('fixture')
        (self.root/'data/trusted-release.json').write_text(json.dumps({
            'manifest_url':'https://fixture.invalid/latest','supervised_install_enabled':True}))
        self.release='a'*64
        self.staged=dict(version='0.10.18',release_id=self.release,sequence=20,
            expires=time.time()+100,commit='b'*40,package=str(self.root/'data/staged.zip'))

    def run_update(self, action='update_install', result=None, error=None):
        import json
        from contextlib import ExitStack
        import sys
        from trader.update_manager import UpdateManager
        from trader.update_supervisor import UpdateSupervisor
        (self.root/'data/portal-jobs/9.json').write_text(json.dumps(dict(id=9,action=action,
            status='running',message='received',at=time.time(),release_id=self.release)))
        (self.source/'pyproject.toml').write_text('[project]\nversion="0.10.17"\n')
        def installed(*args,**kwargs):
            if error: raise error
            (self.source/'pyproject.toml').write_text('[project]\nversion="0.10.18"\n')
            (self.source/'config.toml').write_text('[futures_testnet]\nforward_symbols=["ADAUSDT"]\n')
            return result or dict(status='installed_healthy',version='0.10.18',release_id=self.release)
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.runner,'ROOT',self.root))
            stack.enter_context(patch.object(sys,'argv',['remote_job.py','--source',str(self.source),'--id','9']))
            # Reproduce an old imported validator that cannot parse the new schema.
            old_validator=stack.enter_context(patch.object(self.runner,'source_settings',
                side_effect=ValueError('Unsupported Futures forward symbol')))
            manager=stack.enter_context(patch('trader.update_manager.UpdateManager',spec=UpdateManager))
            manager.return_value.stage.return_value=self.staged
            supervisor=stack.enter_context(patch('trader.update_supervisor.UpdateSupervisor',spec=UpdateSupervisor))
            supervisor.return_value.install.side_effect=installed
            supervisor.return_value.restore.return_value=result
            self.runner.main()
            old_validator.assert_not_called()
        return json.loads((self.root/'data/portal-jobs/9.json').read_text()), supervisor

    def test_signed_install_completion_survives_old_validator_after_config_upgrade(self):
        result, supervisor=self.run_update()
        self.assertEqual(result['status'],'completed')
        self.assertIn('Bot 0.10.18 instalado',result['message'])
        call=supervisor.return_value.install.call_args
        self.assertEqual(call.args[2],self.release)
        self.assertEqual(call.kwargs['job_id'],9)

    def test_actual_install_failure_is_not_reported_as_completed(self):
        result,_=self.run_update(error=ValueError('failed candidate'))
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['message'],'Trabajo detenido: ValueError')

    def test_mismatched_completion_identity_fails_closed(self):
        for change in (dict(release_id='c'*64),dict(version='0.10.19'),dict(status='pending_health')):
            output=dict(status='installed_healthy',version='0.10.18',release_id=self.release)
            result,_=self.run_update(result={**output,**change})
            self.assertEqual(result['status'],'failed')

    def test_restore_completion_does_not_use_new_or_old_config_schema(self):
        result,supervisor=self.run_update(action='update_restore',result=dict(
            status='restored_healthy',version='0.10.17',restore_id=self.release))
        self.assertEqual(result['status'],'completed')
        self.assertIn('Código 0.10.17 restaurado',result['message'])
        supervisor.return_value.restore.assert_called_once_with(self.release,job_id=9)
