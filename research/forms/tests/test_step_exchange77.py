"""045: fatal evidence cannot belong to another run/step; old responses cannot replay."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import step_exchange77 as exchange
from form_launcher77 import FormWatcher
import scenario77


class ExchangeTests(unittest.TestCase):
    def detail(self, **changes):
        return dict(dict(schema_version=1, run_id='run', step=3, operation='answer-publish', path='answer',
                         error_number=70, error_source='VBScript', error_description='Permission denied',
                         attempts=1, elapsed_ms=0, controller_may_have_executed=True), **changes)

    def watcher(self, folder):
        watcher = FormWatcher.__new__(FormWatcher)
        watcher.out = folder
        watcher.lifecycle = {'run_id':'run'}
        watcher.stopped = threading.Event()
        return watcher

    def test_error_sidecar_is_utf16_and_preserves_uncertain_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.assertIsNone(exchange.failure(folder,'run',3))
            path = folder / exchange.FAILURE
            path.write_text(json.dumps(self.detail()),encoding='utf-16')
            self.assertTrue(exchange.failure(folder,'run',3)['controller_may_have_executed'])
            value = self.detail(step=None,operation='request-open',controller_may_have_executed=False)
            path.write_text(json.dumps(value),encoding='utf-16')
            self.assertEqual(exchange.failure(folder,'run',3),value)

    def test_foreign_malformed_or_ambiguous_diagnostic_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            path = folder / exchange.FAILURE
            values = [[],{},self.detail(run_id='other'),self.detail(step=4),self.detail(step=True),
                      self.detail(controller_may_have_executed=1),self.detail(error_number='70'),
                      self.detail(attempts=0),self.detail(path=''),self.detail(operation='')]
            for value in values:
                path.write_text(json.dumps(value),encoding='utf-16')
                with self.subTest(value=value),self.assertRaises(ValueError):
                    exchange.failure(folder,'run',3)
            path.write_text('{partial',encoding='utf-16')
            with self.assertRaises(ValueError): exchange.failure(folder,'run',3)

    def test_old_done_and_partial_answers_refuse_replay_before_publication(self):
        for name in ('form-step-3-done','form-step-3.tmp'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                (folder/name).write_text('value:old',encoding='utf-16')
                result = self.watcher(folder).round_trip(3)
                self.assertFalse(result['returned'])
                self.assertIn('refusing replay',result['error'])
                self.assertFalse((folder/scenario77.REQUEST).exists())
                self.assertFalse((folder/(scenario77.REQUEST+'.tmp')).exists())

    def test_stopped_client_returns_original_fatal_operation_and_path(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/exchange.FAILURE).write_text(json.dumps(self.detail()),encoding='utf-16')
            watcher = self.watcher(folder)
            watcher.stopped.set()
            result = watcher.round_trip(3)
            self.assertFalse(result['returned'])
            self.assertEqual(result['exchange_error'],self.detail())
            self.assertIn('answer-publish: 70',result['error'])
            self.assertFalse((folder/scenario77.REQUEST).exists())

    def test_stopped_client_does_not_accept_foreign_failure_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/exchange.FAILURE).write_text(json.dumps(self.detail(run_id='other')),encoding='utf-16')
            watcher=self.watcher(folder);watcher.stopped.set()
            result=watcher.round_trip(3)
            self.assertFalse(result['returned'])
            self.assertIn('invalid exchange failure evidence',result['error'])
            self.assertNotIn('exchange_error',result)

    def test_retry_is_limited_to_pre_controller_file_access(self):
        code = scenario77.client('form-click-done',60000)
        self.assertEqual(code.count('controller.Harness77Step('),1)
        self.assertEqual(code.count('For attempts = 1 To 26'),2)
        for function in ('OpenStepRequest','DeleteStepRequest'):
            block = code.split(('Function ' if function.startswith('Open') else 'Sub ')+function,1)[1].split('End Function' if function.startswith('Open') else 'End Sub',1)[0]
            self.assertIn('number <> 70',block)
            self.assertIn('Elapsed(started) >= 1000',block)
            self.assertNotIn('controller.Harness77Step',block)
        self.assertIn('h77StepControllerStarted = True',code)
        self.assertIn('StepExchangeCheck "answer-publish"',code)

    def test_answer_read_waits_for_access_without_republishing_or_recalling(self):
        path = Mock()
        path.read_text.side_effect = [PermissionError(13,'busy'), 'value:3']
        pause=Mock()
        answer,retries,error=exchange.read_answer(path,'run',3,clock=Mock(return_value=0),pause=pause)
        self.assertEqual(answer,'value:3')
        self.assertIsNone(error)
        self.assertEqual(len(retries),1)
        self.assertTrue(retries[0]['controller_may_have_executed'])
        self.assertEqual(path.read_text.call_count,2)
        pause.assert_called_once_with(.04)
        path.write_text.assert_not_called()
        path.replace.assert_not_called()

    def test_answer_read_denial_is_bounded_and_other_errors_do_not_retry(self):
        path=Mock()
        path.read_text.side_effect=PermissionError(13,'persistent')
        answer,retries,error=exchange.read_answer(path,'run',3,clock=Mock(return_value=0),pause=Mock())
        self.assertIsNone(answer)
        self.assertEqual(len(retries),25)
        self.assertEqual(error['attempts'],26)
        self.assertTrue(error['controller_may_have_executed'])
        for error_value in (FileNotFoundError(2,'missing'),UnicodeError('corrupt')):
            path.read_text.reset_mock()
            path.read_text.side_effect=error_value
            pause=Mock()
            answer,retries,error=exchange.read_answer(path,'run',3,clock=Mock(return_value=0),pause=pause)
            self.assertIsNone(answer)
            self.assertEqual(retries,[])
            self.assertEqual(path.read_text.call_count,1)
            pause.assert_not_called()


if __name__=='__main__':
    unittest.main()
