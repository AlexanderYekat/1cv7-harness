"""096: typed business differences, invalid evidence and full-cycle compatibility."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness77 import structured77 as structured
from harness77.config77 import ConfigError, load_project
from harness77.suite77 import _problems, junit
from stage4_fixtures import base_scenario, run, write_project, write_sim_stand


EXPECTED = {'document': {'posted': True, 'rows': [{'quantity': '3', 'amount': '30'},
                                             {'quantity': '2', 'amount': '40'}]},
            'entries': [{'debit': '43', 'credit': '40', 'quantity': '3', 'amount': '30'},
                        {'debit': '43', 'credit': '40', 'quantity': '2', 'amount': '40'}]}
LABELS = {'/entries/0/amount': 'Проводка 1, сумма', '/entries/1/amount': 'Проводка 2, сумма'}


class StructuredTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='harness77-json-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_two_actual_posting_errors_are_specific_and_only_two(self):
        actual = json.loads(json.dumps(EXPECTED))
        actual['entries'][0]['amount'] = '10'
        actual['entries'][1]['amount'] = '20'
        result = structured.compare(EXPECTED, actual, LABELS)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['difference_count'], 2)
        self.assertEqual([(d['path'], d['expected'], d['actual']) for d in result['differences']],
                         [('/entries/0/amount', '30', '10'), ('/entries/1/amount', '40', '20')])
        self.assertEqual(result['differences'][0]['message'], 'Проводка 1, сумма: ожидалось "30", получено "10"')
        self.assertFalse(result['differences_truncated'])

    def test_object_order_is_ignored_array_order_and_types_are_strict(self):
        self.assertEqual(structured.compare({'a': 1, 'b': 2}, {'b': 2, 'a': 1})['status'], 'passed')
        for expected, actual in [(True, 1), (1, '1'), ([], {}), (None, ''), ([1, 2], [2, 1])]:
            with self.subTest(expected=expected, actual=actual):
                self.assertEqual(structured.compare(expected, actual)['status'], 'failed')

    def test_missing_extra_and_null_have_unambiguous_paths(self):
        result = structured.compare({'a/b~c': None, 'rows': [1, 2]}, {'rows': [1], 'extra': None})
        self.assertEqual([(d['path'], d['code']) for d in result['differences']],
                         [('/a~1b~0c', 'missing_field'), ('/rows/1', 'missing_item'), ('/extra', 'unexpected_field')])
        self.assertTrue(result['differences'][0]['expected_present'])
        self.assertIsNone(result['differences'][0]['expected'])
        self.assertFalse(result['differences'][0]['actual_present'])
        self.assertNotIn('actual', result['differences'][0])

    def test_json_numbers_compare_exactly_without_binary_rounding(self):
        self.assertEqual(structured.compare(structured.parse('1'), structured.parse('1.00'))['status'], 'passed')
        result = structured.compare(structured.parse('0.12345678901234567891'),
                                    structured.parse('0.12345678901234567892'))
        self.assertEqual(result['difference_count'], 1)
        self.assertEqual(result['differences'][0]['actual'], '0.12345678901234567892')
        self.assertEqual(result['differences'][0]['actual_type'], 'number')

    def test_difference_limit_keeps_true_count(self):
        result = structured.compare([0] * 120, [1] * 120)
        self.assertEqual((result['difference_count'], len(result['differences'])), (120, 100))
        self.assertTrue(result['differences_truncated'])

    def test_capture_is_the_exact_operation_text_linked_to_this_run(self):
        value = ' {"a": 1, "b": null} '
        result = structured.judge({'command': 'verify', 'expect_json': '{"b":null,"a":1.0}'},
                                  value, self.root, 'this-run', 3)
        self.assertEqual(result['status'], 'passed')
        evidence = result['result']
        self.assertEqual((evidence['run_id'], evidence['operation']), ('this-run', 'verify'))
        self.assertEqual((self.root / evidence['path']).read_bytes(), value.encode('utf-8'))
        self.assertEqual(evidence['sha256'], hashlib.sha256(value.encode('utf-8')).hexdigest())

    def test_missing_invalid_duplicate_nonfinite_and_huge_results_cannot_pass(self):
        invalid = [None, {}, '', '{', '{"a":1,"a":1}', 'NaN', 'Infinity', '"\\ud800"',
                   '[' * 70 + '0' + ']' * 70, ' ' * (structured.MAX_BYTES + 1),
                   '1e9999999999999999999999999999999999999']
        for index, value in enumerate(invalid):
            with self.subTest(index=index):
                result = structured.judge({'command': 'verify', 'expect_json': '{}'}, value, self.root, 'id', index)
                self.assertEqual(result['status'], 'blocked')
                self.assertIn(result['diagnostics'][0]['code'],
                              ('json_result_missing', 'json_result_invalid', 'json_result_limit'))
        self.assertTrue((self.root / 'structured/test-0003.actual.json').is_file())

    def test_write_error_blocks_and_existing_evidence_is_never_overwritten(self):
        args = ({'command': 'verify', 'expect_json': '{}'}, '{}', self.root, 'id', 1)
        self.assertEqual(structured.judge(*args)['status'], 'passed')
        duplicate = structured.judge(*args)
        self.assertEqual(duplicate['diagnostics'][0]['code'], 'json_result_write_error')
        with patch.object(Path, 'open', side_effect=PermissionError):
            self.assertEqual(structured.judge(*args)['status'], 'blocked')
        for evidence in ({'exists': False, 'complete': False},
                         {'exists': True, 'complete': False, 'sha256_matches': False}):
            with self.subTest(evidence=evidence), patch.object(structured, 'file_evidence', return_value=evidence):
                result = structured.judge(args[0], args[1], self.root, 'id', 2 + len(evidence))
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['diagnostics'][0]['code'], 'json_result_write_error')

    def project(self, text, extra=''):
        path = write_project(self.root, tests=[])
        path.write_text(path.read_text(encoding='utf-8').replace('schema_version = 1', 'schema_version = 2'), encoding='utf-8')
        with path.open('a', encoding='utf-8') as stream:
            stream.write("\n[[platform.tests]]\nname='verify-json'\ncommand='verify'\nexpect='passed'\n")
            stream.write("expect_json = '''" + text + "'''\n" + extra)
        return path

    def test_profile_validates_json_and_labels_before_launch(self):
        path = self.project('{"entries":[{"amount":"30"}]}',
                            'json_labels = {"/entries/0/amount" = "Сумма"}\n')
        test = load_project(path).tests[0]
        self.assertEqual(test['json_labels'], {'/entries/0/amount': 'Сумма'})
        for value, extra in [('{', ''), ('NaN', ''), ('{}', 'expect_value="42"\n'),
                             ('{}', 'json_labels={"/absent"="x"}\n'), ('{}', 'json_labels=[]\n')]:
            with self.subTest(value=value, extra=extra), self.assertRaises(ConfigError):
                load_project(self.project(value, extra))
        for replacement in [("expect='passed'", "expect='failed'"),
                            ('schema_version = 2', 'schema_version = 1'),
                            ("expect_json = '''{}'''", "json_labels={}"),
                            ("expect_json = '''{}'''", "expect_json={}")]:
            path = self.project('{}')
            path.write_text(path.read_text(encoding='utf-8').replace(*replacement), encoding='utf-8')
            with self.subTest(replacement=replacement), self.assertRaises(ConfigError):
                load_project(path)

    def test_full_cycle_outcomes_files_and_suite_diagnostics(self):
        project = self.project(json.dumps(EXPECTED), 'json_labels = ' +
                               '{"/entries/0/amount"="Проводка 1, сумма", "/entries/1/amount"="Проводка 2, сумма"}\n')
        for case, value, expected in [('good', json.dumps(EXPECTED), ('passed', 0)),
                                      ('bad', json.dumps(EXPECTED).replace('"amount": "30"', '"amount": "10"')
                                       .replace('"amount": "40"', '"amount": "20"'), ('failed', 1)),
                                      ('missing', None, ('blocked', 2)), ('invalid', '{', ('blocked', 2)),
                                      ('unicode', '\ud800', ('blocked', 2)), ('nontext', float('nan'), ('blocked', 2))]:
            with self.subTest(case=case):
                stand = write_sim_stand(self.root, base_scenario(operations=[{'name': 'verify', 'status': 'passed', 'value': value}]))
                report = run(project, stand, self.root / case)
                self.assertEqual((report['status'], report['exit_code']), expected)
                tests = next(s for s in report['stages'] if s['stage'] == 'tests')
                structured_result = tests['tests'][0]['structured']
                self.assertEqual(structured_result['status'], expected[0])
                if case not in ('missing', 'unicode', 'nontext'):
                    self.assertEqual(report['result_files'][-1], structured_result['result'])
                    self.assertTrue((Path(report['run_dir']) / structured_result['result']['path']).is_file())
                if case == 'bad':
                    # Both document fields and ledger were changed in this synthetic case.
                    self.assertEqual(structured_result['difference_count'], 4)
                    problems = _problems(report['stages'])
                    self.assertEqual(problems[0]['unmet_tests'][0]['structured']['difference_count'], 4)
                    suite = {'name': 'json', 'counts': {'passed': 0, 'failed': 1, 'blocked': 0, 'skipped': 0},
                             'duration_s': 1, 'suite_id': 'suite', 'complete': True, 'cancelled': False,
                             'status': 'failed', 'exit_code': 1,
                             'scenarios': [{'id': 'case', 'status': 'failed', 'duration_s': 1,
                                            'reason': report['reason'], 'problems': problems}]}
                    self.assertIn('Проводка 1, сумма', junit(suite).decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
