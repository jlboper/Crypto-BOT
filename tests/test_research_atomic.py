"""Atomic Research JSON writes on synthetic files; never launch a worker/bot."""
from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from trader import research_runtime as runtime


def denied(winerror=5):
    error=PermissionError(errno.EACCES,'synthetic replacement denial')
    error.winerror=winerror
    return error


class ResearchAtomicTests(unittest.TestCase):
    def setUp(self):
        self.temporary=TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.path=self.root/'state.json'
        self.old=b'{"status":"COMPLETED","preserve":"previous evidence"}\n'
        self.path.write_bytes(self.old)
        self.previous=self.root/'state.tmp'
        self.previous.write_bytes(b'PREVIOUS TEMP EVIDENCE')
        self.other=self.root/'.state.json.previous.tmp'
        self.other.write_bytes(b'ANOTHER INVOCATION')
        self.original_replace=Path.replace

    def unchanged(self):
        self.assertEqual(self.path.read_bytes(),self.old)
        self.assertEqual(self.previous.read_bytes(),b'PREVIOUS TEMP EVIDENCE')
        self.assertEqual(self.other.read_bytes(),b'ANOTHER INVOCATION')

    def no_own_temporaries(self):
        self.assertEqual(set(self.root.iterdir()),{self.path,self.previous,self.other})

    def test_success_closes_and_fsyncs_unique_same_directory_file_before_replace(self):
        created=[]
        original=runtime.tempfile.NamedTemporaryFile
        def named(**kwargs):
            self.assertEqual(Path(kwargs['dir']),self.root)
            self.assertFalse(kwargs['delete'])
            handle=original(**kwargs);created.append(handle)
            return handle
        value={'status':'RUNNING','progress':'Datos Spot BTCUSDT (1/10)'}
        def replace(source,target):
            self.assertEqual(target,self.path)
            self.assertEqual(source.parent,self.root)
            self.assertTrue(created[0].closed)
            self.assertNotEqual(source,self.previous)
            self.assertNotEqual(source,self.other)
            self.assertEqual(json.loads(source.read_text(encoding='utf-8')),value)
            return self.original_replace(source,target)
        with patch.object(runtime.tempfile,'NamedTemporaryFile',side_effect=named), \
                patch.object(runtime.os,'fsync',wraps=runtime.os.fsync) as fsync, \
                patch.object(Path,'replace',autospec=True,side_effect=replace) as replaced:
            runtime.atomic(self.path,value)
        self.assertEqual(fsync.call_count,1)
        self.assertEqual(replaced.call_count,1)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')),value)
        self.assertEqual(self.previous.read_bytes(),b'PREVIOUS TEMP EVIDENCE')
        self.assertEqual(self.other.read_bytes(),b'ANOTHER INVOCATION')
        self.no_own_temporaries()

    def test_serialization_failure_preserves_previous_bytes_and_cleans_only_own_temp(self):
        for value in ({'invalid':float('nan')},{'invalid':object()}):
            with self.subTest(kind=type(value['invalid']).__name__), \
                    patch.object(Path,'replace',autospec=True) as replaced:
                with self.assertRaises((ValueError,TypeError)):
                    runtime.atomic(self.path,value)
                replaced.assert_not_called()
                self.unchanged();self.no_own_temporaries()

    def test_stream_write_failure_preserves_previous_bytes_and_own_temp_cleanup(self):
        error=OSError(errno.ENOSPC,'synthetic disk full')
        def failed_dump(value,handle,**kwargs):
            handle.write('{"partial":')
            raise error
        with patch.object(runtime.json,'dump',side_effect=failed_dump), \
                patch.object(Path,'replace',autospec=True) as replaced:
            with self.assertRaises(OSError) as caught:runtime.atomic(self.path,{'new':True})
        self.assertIs(caught.exception,error)
        replaced.assert_not_called()
        self.unchanged();self.no_own_temporaries()

    def test_fsync_failure_never_replaces_previous_file(self):
        error=OSError(errno.EIO,'synthetic fsync failure')
        with patch.object(runtime.os,'fsync',side_effect=error), \
                patch.object(Path,'replace',autospec=True) as replaced:
            with self.assertRaises(OSError) as caught:runtime.atomic(self.path,{'new':True})
        self.assertIs(caught.exception,error)
        replaced.assert_not_called()
        self.unchanged();self.no_own_temporaries()

    def test_retryable_windows_denial_reuses_own_complete_temp_without_touching_old_target(self):
        for winerror in (5,32,33):
            self.path.write_bytes(self.old)
            sources=[]
            def replace(source,target):
                sources.append(source)
                if len(sources)<=2:
                    self.unchanged()
                    raise denied(winerror)
                return self.original_replace(source,target)
            with self.subTest(winerror=winerror),patch.object(runtime,'_WINDOWS',True), \
                    patch.object(Path,'replace',autospec=True,side_effect=replace), \
                    patch.object(runtime.time,'sleep') as sleep:
                runtime.atomic(self.path,{'new':True})
            self.assertEqual(len(sources),3)
            self.assertEqual(len(set(sources)),1)
            self.assertEqual([call.args[0] for call in sleep.call_args_list],list(runtime._REPLACE_RETRY_DELAYS[:2]))
            self.assertEqual(json.loads(self.path.read_text()),{'new':True})
            self.no_own_temporaries()

    def test_exhausted_windows_denial_is_bounded_and_preserves_original_error_and_old_target(self):
        error=denied(5)
        with patch.object(runtime,'_WINDOWS',True), \
                patch.object(Path,'replace',autospec=True,side_effect=error) as replaced, \
                patch.object(runtime.time,'sleep') as sleep:
            with self.assertRaises(PermissionError) as caught:runtime.atomic(self.path,{'new':True})
        self.assertIs(caught.exception,error)
        self.assertEqual(replaced.call_count,len(runtime._REPLACE_RETRY_DELAYS)+1)
        self.assertEqual([call.args[0] for call in sleep.call_args_list],list(runtime._REPLACE_RETRY_DELAYS))
        self.assertLessEqual(sum(runtime._REPLACE_RETRY_DELAYS),.5)
        self.unchanged();self.no_own_temporaries()

    def test_non_windows_and_non_sharing_errors_are_not_retried(self):
        for windows,error in ((False,denied(5)),(True,denied(87)),
                              (True,PermissionError(errno.EACCES,'plain POSIX denial')),
                              (True,OSError(errno.EIO,'synthetic I/O failure'))):
            with self.subTest(windows=windows,winerror=getattr(error,'winerror',None)), \
                    patch.object(runtime,'_WINDOWS',windows), \
                    patch.object(Path,'replace',autospec=True,side_effect=error) as replaced, \
                    patch.object(runtime.time,'sleep') as sleep:
                with self.assertRaises(OSError) as caught:runtime.atomic(self.path,{'new':True})
            self.assertIs(caught.exception,error)
            self.assertEqual(replaced.call_count,1)
            sleep.assert_not_called()
            self.unchanged();self.no_own_temporaries()

    def test_cleanup_failure_never_masks_replace_failure_or_deletes_previous_temp(self):
        error=OSError(errno.EIO,'synthetic replace failure')
        cleanup=[]
        def held_temp(source,**kwargs):
            cleanup.append(source)
            raise denied(5)
        with patch.object(Path,'replace',autospec=True,side_effect=error), \
                patch.object(Path,'unlink',autospec=True,side_effect=held_temp):
            with self.assertRaises(OSError) as caught:runtime.atomic(self.path,{'new':True})
        self.assertIs(caught.exception,error)
        self.assertEqual(len(cleanup),1)
        self.assertNotIn(cleanup[0],{self.path,self.previous,self.other})
        self.assertEqual(cleanup[0].parent,self.root)
        self.assertTrue(cleanup[0].is_file())
        self.unchanged()
        cleanup[0].unlink()
        self.no_own_temporaries()

    def test_concurrent_writers_use_distinct_temps_and_leave_one_complete_json(self):
        barrier=threading.Barrier(2)
        lock=threading.Lock();first_seen=set();sources=[]
        def replace(source,target):
            identity=threading.get_ident()
            with lock:
                first=identity not in first_seen
                if first:first_seen.add(identity);sources.append(source)
            if first:barrier.wait(timeout=5)
            return self.original_replace(source,target)
        values=[{'writer':name,'payload':name*10000} for name in ('A','B')]
        with patch.object(Path,'replace',autospec=True,side_effect=replace), \
                ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(runtime.atomic,self.path,value) for value in values]
            for future in futures:future.result(timeout=10)
        self.assertEqual(len(set(sources)),2)
        self.assertIn(json.loads(self.path.read_text(encoding='utf-8')),values)
        self.assertEqual(self.previous.read_bytes(),b'PREVIOUS TEMP EVIDENCE')
        self.assertEqual(self.other.read_bytes(),b'ANOTHER INVOCATION')
        self.no_own_temporaries()

    @unittest.skipUnless(os.name=='nt','native Windows sharing semantics')
    def test_real_windows_reader_denies_replace_then_release_during_retry_succeeds(self):
        held=self.path.open('rb')
        self.addCleanup(held.close)
        failures=[]
        def replace(source,target):
            try:return self.original_replace(source,target)
            except PermissionError as error:
                failures.append(getattr(error,'winerror',None))
                self.unchanged()
                raise
        def release(delay):
            self.assertFalse(held.closed)
            self.assertEqual(delay,runtime._REPLACE_RETRY_DELAYS[0])
            held.close()
        with patch.object(Path,'replace',autospec=True,side_effect=replace) as replaced, \
                patch.object(runtime.time,'sleep',side_effect=release) as sleep:
            runtime.atomic(self.path,{'status':'RUNNING'})
        self.assertEqual(len(failures),1)
        self.assertIn(failures[0],(5,32,33))
        self.assertEqual(replaced.call_count,2)
        self.assertEqual(sleep.call_count,1)
        self.assertEqual(json.loads(self.path.read_text()),{'status':'RUNNING'})
        self.no_own_temporaries()


if __name__=='__main__':unittest.main()
