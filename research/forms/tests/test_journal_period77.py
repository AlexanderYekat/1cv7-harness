"""Task 036: interval validation, native dialog identity and independent readback."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_journal_existing77 import parameters, trip
import scenario77
import journal77


class JournalPeriodTests(unittest.TestCase):
    def test_dates_and_order_are_validated_before_launch(self):
        period = dict(journal_period=True, start='2026-07-31', end='2026-08-01')
        p = parameters(steps=[period, dict(find_document=True)])
        self.assertEqual(len(scenario77.steps(p)), 2)
        for invalid in ({'start': '2026-02-30'}, {'end': '2026-07-30'},
                        {'start': '2026-7-31'}, {'start': ''}, {'cancel': 'yes'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                scenario77.steps(parameters(steps=[dict(period, **invalid), dict(find_document=True)]))
        for steps in ([period], [dict(find_document=True), period]):
            with self.assertRaises(ValueError):
                scenario77.steps(parameters(steps=steps))

    def test_reader_refuses_errors_missing_duplicate_and_impossible_dates(self):
        valid = trip('journal-start:2026:7:31\njournal-end:2026:8:1')
        self.assertEqual(journal77.read_period(valid)[1].isoformat(), '2026-08-01')
        for changed in (dict(returned=False), dict(complete=False), dict(journal_end='2026:2:30'),
                        dict(journal_start='2027:1:1'), dict(journal_error='failure')):
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                journal77.read_period(dict(valid, **changed))
        with self.assertRaises(RuntimeError):
            journal77.read_period(trip('journal-start:2026:7:31\njournal-start:2026:7:31\njournal-end:2026:8:1'))

    def test_cancel_requires_unchanged_period_and_confirmed_closing(self):
        before = trip('journal-start:2023:12:1\njournal-end:2026:7:31')
        after = trip('journal-start:2026:7:31\njournal-end:2026:8:1')
        step = dict(start='2026-07-31', end='2026-08-01')
        record = dict(before_period=before, after_period=after, period_closed=True, answer=dict(requested=True))
        journal77.check_period(step, record)
        with self.assertRaises(RuntimeError):
            journal77.check_period(dict(step, cancel=True), record)
        journal77.check_period(dict(step, cancel=True), dict(record, after_period=before))
        with self.assertRaises(RuntimeError):
            journal77.check_period(step, dict(record, period_closed=False))

    def test_native_fields_must_be_unique_direct_enabled_children(self):
        fields = [dict(id=n, hwnd=n, parent=1, visible=True, enabled=True, **{'class': 'BMASKED'}) for n in (4674, 4676)]
        window = dict(hwnd=1, text='Параметры журнала', children=fields, **{'class': '#32770'})
        self.assertEqual(journal77.period_fields(window), fields)
        for children in (fields[:1], fields + fields[:1], [dict(fields[0], parent=2), fields[1]],
                         [dict(fields[0], enabled=False), fields[1]]):
            with self.assertRaises(RuntimeError):
                journal77.period_fields(dict(window, children=children))

    def test_controller_only_reads_interval_and_excludes_document_table_reads(self):
        steps = scenario77.steps(parameters(steps=[dict(journal_period=True, start='2026-07-31', end='2026-08-01'), dict(find_document=True)]))
        code = scenario77.step_function(steps, table=True, journal_kind='ГотоваяПродукция')
        self.assertIn('Контекст77Формы.НачалоИнтервала()', code)
        self.assertIn('Номер77Шага > -102000', code)
        self.assertIn('Номер77Шага <> 1', code)
        self.assertNotIn('УстановитьИнтервал(', code)


if __name__ == '__main__':
    unittest.main()
