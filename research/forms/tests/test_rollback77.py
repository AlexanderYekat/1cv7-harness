"""Task 032: reject rollback evidence which never proves a partial write."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_rollback77 import partial_issues


class RollbackEvidenceTests(unittest.TestCase):
    def test_runtime_needs_exact_single_readback_before_document_error(self):
        marker = 'HARNESS77-032-PARTIAL:Harness77 runtime 032:1:5:50'
        error = '{Документ.ГотоваяПродукция.Модуль Документа(41)}: Деление на 0'
        self.assertEqual(partial_issues([marker, error], 'runtime', 5, 50), [])
        for lines in ([error], [marker], [error, marker], [marker, marker, error],
                      [marker.replace(':1:5:', ':2:5:'), error],
                      [marker.replace(':5:50', ':3:30'), error],
                      [marker, error.replace('ГотоваяПродукция', 'ДругойДокумент')]):
            with self.subTest(lines=lines):
                self.assertTrue(partial_issues(lines, 'runtime', 5, 50))

    def test_refusal_needs_partial_write_and_following_refusal_marker(self):
        marker = 'HARNESS77-032-PARTIAL:Harness77 refusal 032:1:3:30'
        refusal = 'HARNESS77-032-REFUSAL'
        self.assertEqual(partial_issues([marker, refusal], 'refusal', 3, 30), [])
        for lines in ([refusal], [marker], [refusal, marker], [marker, refusal, refusal],
                      [marker.replace('refusal', 'runtime'), refusal]):
            with self.subTest(lines=lines):
                self.assertTrue(partial_issues(lines, 'refusal', 3, 30))

    def test_unrecognized_or_ambiguous_module_is_refused(self):
        spec = importlib.util.spec_from_file_location('rollback_prepare', ROOT / 'examples/posting-rollback/prepare.py')
        prepare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prepare)
        for text in ('', 'Процедура ОбработкаПроведения()\n',
                     'Процедура ОбработкаПроведения()\n' + prepare.ANCHOR * 2):
            with self.subTest(text=text), self.assertRaises(ValueError):
                prepare.posting_module(text)


if __name__ == '__main__':
    unittest.main()
