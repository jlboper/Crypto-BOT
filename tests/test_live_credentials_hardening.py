"""Synthetic secret entry and cross-process scope admission; no provider calls."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import warnings

from scripts import configure_live_connection as cli
from trader.live_credentials import LiveCredentialVault
from trader.live_transport import LiveCredentials, LiveError

ROOT = Path(__file__).resolve().parents[1]


class SyntheticProtection:
    def protect(self, raw, purpose):
        return purpose.encode()+b'|'+bytes(value ^ 71 for value in raw)

    def unprotect(self, raw, purpose):
        prefix = purpose.encode()+b'|'
        if not raw.startswith(prefix):
            raise ValueError('SYNTHETIC_PURPOSE_MISMATCH')
        return bytes(value ^ 71 for value in raw[len(prefix):])


WORKER = r'''
import sys,time,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from trader.live_credentials import LiveCredentialVault
from trader.live_transport import LiveCredentials,LiveError
class SyntheticProtection:
 def protect(self,raw,purpose):
  time.sleep(.12)
  return purpose.encode()+b'|'+bytes(value^71 for value in raw)
 def unprotect(self,raw,purpose):
  prefix=purpose.encode()+b'|'
  if not raw.startswith(prefix):raise ValueError('SYNTHETIC_PURPOSE_MISMATCH')
  return bytes(value^71 for value in raw[len(prefix):])
path,scope,go=Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4])
import os
Path(str(go)+'.'+str(os.getpid())).write_text('ready')
deadline=time.monotonic()+15
while not go.exists():
 if time.monotonic()>deadline:raise RuntimeError('SYNTHETIC_BARRIER_TIMEOUT')
 time.sleep(.01)
vault=LiveCredentialVault(path,protection=SyntheticProtection())
try:
 vault.configure_scope(scope,LiveCredentials(scope+'-synthetic-key',scope+'-synthetic-secret'))
 print(json.dumps({'state':'COMMITTED'}))
except LiveError as error:
 print(json.dumps({'state':'REJECTED','code':str(error)}))
'''

HOLDER = r'''
import sys,time,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from trader.live_credentials import LiveCredentialVault
vault=LiveCredentialVault(Path(sys.argv[2]))
with vault._write_lock():
 Path(sys.argv[3]).write_text('ready')
 if sys.argv[5]=='crash':os._exit(0)
 deadline=time.monotonic()+15
 while not Path(sys.argv[4]).exists():
  if time.monotonic()>deadline:raise RuntimeError('SYNTHETIC_RELEASE_TIMEOUT')
  time.sleep(.01)
'''

EMPTY_HOLDER = r'''
import sys,time,os
from pathlib import Path
path,ready,release=map(Path,sys.argv[2:5])
with path.open('r+b') as handle:
 if os.name=='nt':
  import msvcrt
  msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
 else:
  import fcntl
  fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 ready.write_text('ready')
 deadline=time.monotonic()+15
 while not release.exists():
  if time.monotonic()>deadline:raise RuntimeError('SYNTHETIC_RELEASE_TIMEOUT')
  time.sleep(.01)
'''


class CredentialHardeningTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve()
        self.path = self.root/'credentials.dpapi'
        self.vault = LiveCredentialVault(self.path, protection=SyntheticProtection())

    def run_cli(self, values, *, scope='FUTURES_LIVE', replace=False):
        output = io.StringIO()
        with (patch.object(cli, 'LiveCredentialVault', return_value=self.vault),
              patch.object(cli.sys.stdin, 'isatty', return_value=True),
              patch.object(cli.getpass, 'getpass', side_effect=values), redirect_stdout(output)):
            result = cli.main(['--scope',scope]+(['--replace'] if replace else []))
        return result, output.getvalue()

    def start(self, code, *args):
        process = subprocess.Popen([sys.executable,'-I','-B','-c',code,str(ROOT),*map(str,args)],
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=self.root)
        self.addCleanup(self.finish, process)
        return process

    @staticmethod
    def finish(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def wait_file(self, path):
        deadline = time.monotonic()+10
        while not path.exists() and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertTrue(path.exists(), 'Synthetic process did not reach the barrier')

    def test_two_processes_merge_distinct_scopes_without_lost_updates(self):
        go = self.root/'go'
        processes = [self.start(WORKER,self.path,scope,go) for scope in ('SPOT_LIVE','FUTURES_LIVE')]
        for process in processes:self.wait_file(Path(str(go)+'.'+str(process.pid)))
        go.write_text('go')
        for process in processes:
            out,err = process.communicate(timeout=20)
            self.assertEqual(process.returncode,0,err)
            self.assertEqual(json.loads(out),{'state':'COMMITTED'})
        self.assertEqual(set(self.vault.read()),{'SPOT_LIVE','FUTURES_LIVE'})
        self.assertFalse(self.vault.status()['orders_enabled'])

    def test_two_processes_cannot_silently_replace_the_same_scope(self):
        go = self.root/'go'
        processes = [self.start(WORKER,self.path,'SPOT_LIVE',go) for _ in range(2)]
        for process in processes:self.wait_file(Path(str(go)+'.'+str(process.pid)))
        go.write_text('go')
        outcomes = []
        for process in processes:
            out,err = process.communicate(timeout=20)
            self.assertEqual(process.returncode,0,err)
            outcomes.append(json.loads(out))
        self.assertEqual(sum(row['state']=='COMMITTED' for row in outcomes),1)
        rejected = next(row for row in outcomes if row['state']=='REJECTED')
        self.assertEqual(rejected['code'],'EXPLICIT_CREDENTIAL_REPLACEMENT_REQUIRED')
        self.assertEqual(set(self.vault.read()),{'SPOT_LIVE'})

    def test_scope_replacement_is_explicit_and_keeps_the_other_pair(self):
        spot = LiveCredentials('spot-synthetic-key','spot-synthetic-secret')
        old = LiveCredentials('old-futures-synthetic-key','old-futures-synthetic-secret')
        new = LiveCredentials('new-futures-synthetic-key','new-futures-synthetic-secret')
        self.vault.configure({'SPOT_LIVE':spot,'FUTURES_LIVE':old})
        original = self.path.read_bytes()
        with self.assertRaisesRegex(LiveError,'EXPLICIT_CREDENTIAL_REPLACEMENT_REQUIRED'):
            self.vault.configure_scope('FUTURES_LIVE',new)
        self.assertEqual(self.path.read_bytes(),original)
        self.vault.configure_scope('FUTURES_LIVE',new,replace=True)
        self.assertEqual(self.vault.read(),{'SPOT_LIVE':spot,'FUTURES_LIVE':new})

    def test_busy_writer_preserves_record_and_os_releases_after_process_exit(self):
        self.vault.configure({'SPOT_LIVE':LiveCredentials('synthetic-key','synthetic-secret')})
        original = self.path.read_bytes()
        ready,release = self.root/'ready',self.root/'release'
        holder = self.start(HOLDER,self.path,ready,release,'hold')
        self.wait_file(ready)
        with patch('trader.live_credentials.CREDENTIAL_LOCK_WAIT_SECONDS',.08):
            with self.assertRaisesRegex(LiveError,'CREDENTIAL_STORE_BUSY'):
                self.vault.configure_scope('FUTURES_LIVE',LiveCredentials('future-key','future-secret'))
        self.assertEqual(self.path.read_bytes(),original)
        holder.kill();holder.communicate(timeout=10)
        self.vault.configure_scope('FUTURES_LIVE',LiveCredentials('future-key','future-secret'))
        self.assertEqual(set(self.vault.read()),{'SPOT_LIVE','FUTURES_LIVE'})

    def test_nonregular_or_hardlinked_lock_is_rejected_without_mutation(self):
        lock = self.path.with_name(self.path.name+'.lock')
        lock.mkdir()
        with self.assertRaises(LiveError):
            self.vault.configure_scope('SPOT_LIVE',LiveCredentials('synthetic-key','synthetic-secret'))
        self.assertFalse(self.path.exists())
        lock.rmdir()
        target = self.root/'unrelated';target.write_bytes(b'x')
        os.link(target,lock)
        with self.assertRaisesRegex(LiveError,'CREDENTIAL_LOCK_PATH_BLOCKED'):
            self.vault.configure_scope('SPOT_LIVE',LiveCredentials('synthetic-key','synthetic-secret'))
        self.assertEqual(target.read_bytes(),b'x')
        self.assertFalse(self.path.exists())

    def test_existing_empty_marker_waits_without_initialization_write(self):
        lock = self.path.with_name(self.path.name+'.lock')
        lock.write_bytes(b'')
        ready,release = self.root/'empty-ready',self.root/'empty-release'
        holder = self.start(EMPTY_HOLDER,lock,ready,release)
        self.wait_file(ready)
        with patch('trader.live_credentials.CREDENTIAL_LOCK_WAIT_SECONDS',.08):
            with self.assertRaisesRegex(LiveError,'CREDENTIAL_STORE_BUSY'):
                self.vault.configure_scope('SPOT_LIVE',LiveCredentials('synthetic-key','synthetic-secret'))
        self.assertFalse(self.path.exists())
        self.assertEqual(lock.stat().st_size,0)
        release.write_text('release')
        _,err = holder.communicate(timeout=10)
        self.assertEqual(holder.returncode,0,err)
        self.vault.configure_scope('SPOT_LIVE',LiveCredentials('synthetic-key','synthetic-secret'))
        self.assertEqual(lock.stat().st_size,0)

    def test_malformed_key_retries_without_echo_or_losing_existing_scope(self):
        spot = LiveCredentials('spot-synthetic-key','spot-synthetic-secret')
        self.vault.configure({'SPOT_LIVE':spot})
        code,output = self.run_cli(['A'*128,'B'*105,'C'*64,'D'*64])
        self.assertEqual(code,0)
        self.assertEqual(self.vault.read()['SPOT_LIVE'],spot)
        self.assertEqual(self.vault.read()['FUTURES_LIVE'],LiveCredentials('C'*64,'D'*64))
        for value in ('A'*128,'B'*105,'C'*64,'D'*64):
            self.assertNotIn(value,output)
            self.assertNotIn(value,self.path.read_text())
        self.assertIn('128 caracteres',output)
        self.assertIn('105 caracteres',output)
        self.assertIn('Finalizado.',output)

    def test_four_bad_entries_or_empty_input_never_write(self):
        for values in (['A'*105]*4,['A'*64]+['B'*128]*4,['']):
            with self.subTest(values_count=len(values)),patch.object(self.vault,'configure_scope',wraps=self.vault.configure_scope) as save:
                code,output = self.run_cli(values)
                self.assertEqual(code,2)
                save.assert_not_called()
                self.assertFalse(self.path.exists())
                self.assertIn('CONFIGURATION_NOT_CONFIRMED',output)
                for value in values:
                    if value:self.assertNotIn(value,output)

    def test_scope_added_while_owner_types_is_merged_not_overwritten(self):
        spot = LiveCredentials('spot-concurrent-key','spot-concurrent-secret')
        values = iter(['F'*64,'S'*64])
        def entered(prompt):
            value = next(values)
            if prompt.startswith('API key'):
                self.vault.configure_scope('SPOT_LIVE',spot)
            return value
        code,output = self.run_cli(entered)
        self.assertEqual(code,0)
        self.assertEqual(self.vault.read(),{'SPOT_LIVE':spot,'FUTURES_LIVE':LiveCredentials('F'*64,'S'*64)})
        self.assertNotIn(spot.api_key,output)

    def test_same_scope_added_during_input_requires_explicit_replacement(self):
        original = LiveCredentials('original-futures-key','original-futures-secret')
        values = iter(['F'*64,'S'*64])
        def entered(prompt):
            value = next(values)
            if prompt.startswith('API key'):
                self.vault.configure_scope('FUTURES_LIVE',original)
            return value
        code,output = self.run_cli(entered)
        self.assertEqual(code,2)
        self.assertEqual(self.vault.read(),{'FUTURES_LIVE':original})
        self.assertIn('CONFIGURATION_NOT_CONFIRMED',output)

    def test_getpass_warning_aborts_before_fallback_input(self):
        def fallback(prompt):
            warnings.warn('Synthetic missing protected terminal',cli.getpass.GetPassWarning)
            cli.sys.stdin.readline()
            return 'A'*64
        with patch.object(cli.sys.stdin,'readline') as read:
            code,output = self.run_cli(fallback)
        self.assertEqual(code,2)
        read.assert_not_called()
        self.assertFalse(self.path.exists())
        self.assertNotIn('Synthetic missing protected terminal',output)

    def test_status_is_json_only_and_performs_no_secret_entry(self):
        with (patch.object(cli,'LiveCredentialVault',return_value=self.vault),
              patch.object(cli.sys.stdin,'isatty',return_value=True),
              patch.object(cli.getpass,'getpass') as prompt,redirect_stdout(io.StringIO()) as output):
            self.assertEqual(cli.main(['--status']),0)
        self.assertEqual(json.loads(output.getvalue()),self.vault.status())
        prompt.assert_not_called()

    def test_invalid_arguments_never_echo_accidental_secret_values(self):
        for args in (['--api-key','SYNTHETIC_SECRET_ARGUMENT_NOT_FOR_LOGS'],
                     ['--scope','SYNTHETIC_SECRET_SCOPE_NOT_FOR_LOGS']):
            with self.subTest(option=args[0]),redirect_stdout(io.StringIO()) as out,redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as exit_result:
                    cli.main(args)
            self.assertEqual(exit_result.exception.code,2)
            self.assertNotIn(args[1],out.getvalue()+err.getvalue())
            self.assertEqual(json.loads(err.getvalue())['error'],'INVALID_LOCAL_CONFIGURATION_ARGUMENTS')
            self.assertFalse(self.path.exists())


if __name__=='__main__':
    unittest.main()
