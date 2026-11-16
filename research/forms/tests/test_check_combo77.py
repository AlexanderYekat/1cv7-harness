"""108: exact list assertions use the existing non-mutating reader and evidence."""
import json
from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_inspect_combo77 import scenario, launcher


class CheckComboTests(unittest.TestCase):
    def parsed(self, items):
        return scenario.steps({'steps': [{'check_combo': 'Список', 'items': items}]})[0]

    def test_schema_literal_items_and_resolution(self):
        items = ['', 'А', 'А', ' а ', 'А\nБ']
        step = self.parsed(items)
        items.append('late mutation')
        self.assertEqual(step['items'], ['', 'А', 'А', ' а ', 'А\nБ'])
        description = {'controls': [{'id': 7, 'identifier': 'Список', 'caption': '&Тип', 'class': 'COMBOBOX'}]}
        for target in ('Список', 'Тип'):
            resolved, = scenario.resolve([dict(step, target=target)], description)
            self.assertEqual(resolved['record_id'], 7)
            self.assertNotIn(resolved['kind'], scenario.ACTIONS)
        self.assertEqual(self.parsed([])['items'], [])
        self.assertEqual(len(self.parsed(['x' * 4096] * 1000)['items']), 1000)
        for bad in (None, '', {}, [1], [False], [[]], ['x' * 4097], ['x'] * 1001, ['\0'], ['🙂']):
            with self.subTest(bad=str(bad)[:30]), self.assertRaises(ValueError):
                self.parsed(bad)
        for item in ({'check_combo': 'Список'}, {'check_combo': 'Список', 'items': [], 'text': ''},
                     {'check_combo': 'Список', 'items': [], 'closes': True}):
            with self.assertRaises(ValueError):
                scenario.steps({'steps': [item]})
        for controls in ([], description['controls'] * 2,
                         [dict(description['controls'][0], **{'class': 'BUTTON'})]):
            with self.assertRaises(ValueError):
                scenario.resolve([step], {'controls': controls})
        with self.assertRaises(ValueError):
            scenario.steps({'steps': [{'check_combo': 'Список', 'items': []}, {'dialog': 'x'}]})
        from test_tabs77 import TabsTests
        readonly = TabsTests().parameters()
        readonly['steps'].append({'check_combo': 'Список', 'items': ['А']})
        self.assertEqual(scenario.steps(readonly)[-1]['kind'], 'check_combo')

    def test_exact_comparison_first_difference_and_presence(self):
        expected = ['Первый', '', 'А', 'А', ' а ']
        self.assertTrue(scenario.compare_combo(expected, list(expected))['matches'])
        self.assertTrue(scenario.compare_combo([], [])['matches'])
        for actual, index, wanted, shown in (
            (['Первый', 'А', 'А', ' а '], 1, '', 'А'),  # removal
            (expected + [''], 5, None, ''),  # addition of an empty item
            (['Первый', '', 'Б', 'А', ' а '], 2, 'А', 'Б'),  # rename
            (['', 'Первый', 'А', 'А', ' а '], 0, 'Первый', ''),  # reorder
            (expected[:-1], 4, ' а ', None),
            (['Первый', '', 'А', 'А', 'а'], 4, ' а ', 'а'),  # whitespace
            (['Первый', '', 'А', 'А', ' А '], 4, ' а ', ' А '),  # case
            ([], 0, 'Первый', None),
        ):
            with self.subTest(actual=actual):
                comparison = scenario.compare_combo(expected, actual)
                self.assertFalse(comparison['matches'])
                diff = comparison['first_difference']
                self.assertEqual((diff['index'], diff['expected'], diff['actual']), (index, wanted, shown))
                self.assertEqual(diff['expected_present'], index < len(expected))
                self.assertEqual(diff['actual_present'], index < len(actual))
                self.assertEqual(comparison['actual_count'], len(actual))

    def test_judgment_requires_verified_read_and_preserves_failure_details(self):
        step = self.parsed(['', 'А'])
        record = {'round_trip': {'returned': True, 'complete': True}}
        self.assertIn('not verified', scenario.judge(step, record, [], True))
        self.assertNotIn('combo_comparison', record)
        record['combo_inspection'] = dict(read_only_verified=True, items=[''])
        issue = scenario.judge(step, record, [], True)
        self.assertIn("items[1]: expected 'А', actual <absent>", issue)
        self.assertEqual(record['combo_comparison']['first_difference']['path'], '/items/1')
        record['round_trip']['complete'] = False
        self.assertIn('not saved completely', scenario.judge(step, record, [], True))

    def test_watcher_saves_complete_actual_snapshot_even_on_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher = object.__new__(launcher.FormWatcher)
            watcher.evidence_dir = Path(tmp) / 'form'
            watcher.evidence_dir.mkdir()
            watcher.description = {'controls': [{'id': 7, 'identifier': 'Список', 'class': 'COMBOBOX'}]}
            watcher.steps = scenario.resolve([self.parsed(['А', ''])], watcher.description)
            watcher.round_trip = Mock(return_value=dict(returned=True, complete=True, diagnostics=[], messages=[]))
            form = Mock()
            form.alive.return_value = True
            form.inspect_combo.return_value = dict(items=['А'], selected_index=0, selected_text='А',
                visible=False, enabled=False, read_only_verified=True)
            inspection = dict(chain=[{'hwnd': 10}], controls=[{'id': 4152, 'hwnd': 20}])
            record, = watcher.run_steps(form, inspection)
            self.assertEqual(record['status'], 'failed')
            self.assertFalse(record['combo_comparison']['matches'])
            ref = record['inspection_file']
            self.assertEqual(json.loads((Path(tmp)/ref['path']).read_text('utf-8'))['items'], ['А'])
            self.assertEqual(launcher.FormAdapter().result_files(Path(tmp), [])[0]['sha256'], ref['sha256'])
            form.inspect_combo.return_value['items'] = ['А', '']
            self.assertEqual(watcher.run_steps(form, inspection)[0]['status'], 'passed')
            for failure in ('read', 'round_trip', 'save'):
                with self.subTest(failure=failure):
                    form.inspect_combo.side_effect = RuntimeError('read failed') if failure == 'read' else None
                    watcher.round_trip.return_value['complete'] = failure != 'round_trip'
                    with patch.object(launcher, 'atomic_json', side_effect=OSError('save failed')) if failure == 'save' else nullcontext():
                        record, = watcher.run_steps(form, inspection)
                    self.assertEqual(record['status'], 'failed')
                    self.assertNotIn('inspection_file', record)


if __name__ == '__main__':
    unittest.main()
