"""109: bounded atomic publication and failure evidence, portable fault injection."""
import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from startup77 import StartupTrace, StartupWriteError


def denied(code=5):
    error=PermissionError(errno.EACCES,'held by reader')
    error.winerror=code
    return error


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='startup109-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.now=0.
        self.sleeps=[]
        self.trace=StartupTrace(self.root,'r109',publish=False,write_clock=lambda:self.now,pause=self.pause)
        self.trace.path.write_text('{"old":true}',encoding='utf-8')
        self.original=self.trace.path.read_bytes()

    def pause(self,seconds):
        self.sleeps.append(seconds)
        self.now+=seconds

    def assert_clean(self):
        self.assertFalse(list(self.root.glob('*.tmp')))
        self.assertFalse(list(self.root.glob('.*.tmp')))

    def test_windows_denial_recovers_with_old_json_intact_until_commit(self):
        replace=Path.replace
        calls=[]
        def held(path,target):
            calls.append(path)
            if len(calls)<3:
                self.assertEqual(target.read_bytes(),self.original)
                raise denied()
            return replace(path,target)
        with patch.object(Path,'replace',held):
            self.trace.note('registration_acquired',waiting_for='debugger_create')
        data=json.loads(self.trace.path.read_text('utf-8'))
        self.assertEqual(data['waiting_for'],'debugger_create')
        retry,=data['write_retries']
        self.assertEqual((retry['attempts'],retry['winerror'],retry['recovered']),(3,5,True))
        self.assertEqual(len(set(calls)),1)  # one owned unique temporary file per publication
        self.assertEqual(len(self.sleeps),2)
        self.assert_clean()

    def test_persistent_denial_is_bounded_and_never_overwrites_old_json(self):
        with patch.object(Path,'replace',side_effect=denied()) as replace:
            with self.assertRaises(StartupWriteError) as error:
                self.trace.save()
        self.assertLessEqual(replace.call_count,26)
        self.assertLessEqual(self.now,1.000001)
        self.assertEqual(self.trace.path.read_bytes(),self.original)
        self.assertFalse(self.trace.data['write_retries'][0]['recovered'])
        self.assertEqual(error.exception.detail['winerror'],5)
        self.assert_clean()

    def test_other_errors_write_failures_and_non_windows_permissions_are_not_retried(self):
        for error in (OSError(errno.ENOSPC,'full'),PermissionError(errno.EACCES,'permanent'),denied(2)):
            with self.subTest(error=error),patch.object(Path,'replace',side_effect=error) as replace:
                with self.assertRaises(StartupWriteError):self.trace.save()
                self.assertEqual(replace.call_count,1)
                self.assertEqual(self.trace.path.read_bytes(),self.original)
                self.assert_clean()
        with patch.object(Path,'write_text',side_effect=OSError(errno.ENOSPC,'full')):
            with self.assertRaises(StartupWriteError) as error:self.trace.save()
        self.assertEqual(error.exception.detail['stage'],'write')
        self.assertEqual(self.trace.path.read_bytes(),self.original)
        self.assert_clean()

    def test_cancellation_stops_retry_and_keeps_the_prior_file(self):
        def check():
            if self.now>=0.04:raise RuntimeError('cancelled by caller')
        self.trace.check=check
        with patch.object(Path,'replace',side_effect=denied()) as replace:
            with self.assertRaisesRegex(RuntimeError,'cancelled'):self.trace.save()
        self.assertEqual(replace.call_count,1)
        self.assertEqual(self.trace.path.read_bytes(),self.original)
        self.assert_clean()

    def test_phase_deadline_caps_sleep_and_never_replaces_after_expiry(self):
        def check():
            if self.now>=0.015:raise TimeoutError('open deadline')
            return 0.015-self.now
        self.trace.check=check
        with patch.object(Path,'replace',side_effect=denied()) as replace:
            with self.assertRaisesRegex(TimeoutError,'open deadline'):self.trace.save()
        self.assertEqual(replace.call_count,1)
        self.assertEqual(self.sleeps,[0.015])
        self.assertEqual(self.trace.path.read_bytes(),self.original)
        self.assert_clean()

    def test_error_finish_is_single_attempt_without_cancel_guard_or_sleep(self):
        self.trace.check=lambda: (_ for _ in ()).throw(RuntimeError('cancelled'))
        with patch.object(Path,'replace',side_effect=denied()) as replace:
            with self.assertRaises(StartupWriteError):self.trace.finish('primary failure',True)
        self.assertEqual(replace.call_count,1)
        self.assertEqual(self.sleeps,[])
        self.assertEqual(self.trace.data['error'],'primary failure')
        self.assertEqual(self.trace.path.read_bytes(),self.original)
        self.assert_clean()

    def test_late_system_call_preserves_deadline_classification(self):
        def check():
            if self.now >= 0.015:raise TimeoutError('open deadline')
        self.trace.check=check
        original=Path.replace
        for failed in (True,False):
            self.now=0.
            def delayed(path,target):
                self.now=2.
                if failed:raise denied()
                return original(path,target)
            with self.subTest(failed=failed),patch.object(Path,'replace',delayed):
                with self.assertRaisesRegex(TimeoutError,'open deadline'):self.trace.save()
                self.assert_clean()
        self.assertEqual(self.sleeps,[])

    def test_successful_final_publication_does_not_reclassify_completed_shutdown(self):
        self.trace.check=lambda: (_ for _ in ()).throw(TimeoutError('already exited'))
        self.trace.finish()
        self.assertEqual(json.loads(self.trace.path.read_text('utf-8'))['status'],'ready')
        self.assertEqual(self.sleeps,[])
        self.assert_clean()

    def test_serialization_failure_does_not_touch_any_file(self):
        self.trace.data['bad']=float('nan')
        with self.assertRaises(ValueError):self.trace.save()
        self.assertEqual(self.trace.path.read_bytes(),self.original)
        self.assert_clean()


if __name__=='__main__':unittest.main()
