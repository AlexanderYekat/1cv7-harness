"""106: read-only discovery, stable snapshots and the public evidence contract."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scenario77 as scenario
import form_window77 as window
import form_launcher77 as launcher


class InspectTests(unittest.TestCase):
    def test_schema_and_resolution(self):
        description = {'controls': [{'id': 7, 'identifier': 'Список', 'caption': '&Тип', 'class': 'COMBOBOX'}]}
        for target in ('Список', 'Тип'):
            step, = scenario.resolve(scenario.steps({'steps': [{'inspect_combo': target}]}), description)
            self.assertEqual(step['record_id'], 7)
            self.assertNotIn(step['kind'], scenario.ACTIONS)
        for bad in ({'inspect_combo': ''}, {'inspect_combo': 1}, {'inspect_combo': 'Список', 'text': 'x'},
                    {'inspect_combo': 'Список', 'closes': True}):
            with self.assertRaises(ValueError):
                scenario.steps({'steps': [bad]})
        for controls in ([], description['controls'] * 2,
                         [dict(description['controls'][0], **{'class': 'BUTTON'})]):
            with self.assertRaises(ValueError):
                scenario.resolve([step], {'controls': controls})
        with self.assertRaises(ValueError):
            scenario.steps({'steps': [{'inspect_combo': 'Список'}, {'dialog': 'x'}]})

    def native(self, items, index):
        form = object.__new__(window.OwnedForm)
        form.user = Mock()
        form.user.GetParent.return_value = 10
        form.user.GetDlgCtrlID.return_value = 20
        form.combo_state = Mock(return_value=dict(items=items, index=index, text=items[index] if index >= 0 else None))
        form.element_state = Mock(return_value=dict(text='', visible=False, enabled=False))
        form.focused = Mock(return_value={'hwnd': 30, 'id': 40})
        form.send = Mock(side_effect=AssertionError('inspection must not send a mutating message'))
        form.post = form.send
        return form

    def test_literal_items_and_absent_selection(self):
        for items, index in ((['А', '', 'А', ' а '], 1), ([], -1), (['Б', 'А'], -1)):
            form = self.native(items, index)
            state = form.inspect_combo({'chain': [{'hwnd': 10}]}, {'hwnd': 15, 'id': 20})
            self.assertEqual(state['items'], items)
            self.assertEqual(state['selected_index'], None if index == -1 else index)
            self.assertEqual(state['selected_text'], items[index] if index >= 0 else None)
            self.assertFalse(state['visible'])
            self.assertFalse(state['enabled'])
            self.assertTrue(state['read_only_verified'])
            self.assertEqual(state['focus_before'], state['focus_after'])
            form.send.assert_not_called()

    def test_changed_state_focus_and_read_errors_are_not_complete_results(self):
        for change in ('items', 'focus', 'state', 'error', 'parent', 'id'):
            form = self.native(['А'], 0)
            if change == 'items':
                form.combo_state.side_effect = [form.combo_state.return_value, dict(items=['Б'], index=0, text='Б')]
            elif change == 'focus':
                form.focused.side_effect = [None, {'hwnd': 99}]
            elif change == 'state':
                form.element_state.side_effect = [dict(visible=False, enabled=False), dict(visible=True, enabled=False)]
            elif change == 'error':
                form.combo_state.side_effect = [form.combo_state.return_value, RuntimeError('CB_GETLBTEXT timed out')]
            elif change == 'parent':
                form.user.GetParent.return_value = 99
            else:
                form.user.GetDlgCtrlID.return_value = 99
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                form.inspect_combo({'chain': [{'hwnd': 10}]}, {'hwnd': 15, 'id': 20})

    def test_judgment_rejects_unverified_or_incomplete_reads(self):
        step = dict(index=1, kind='inspect_combo', target='Список')
        record = dict(round_trip=dict(returned=True, complete=True))
        self.assertIn('not verified', scenario.judge(step, record, [], True))
        record['combo_inspection'] = dict(read_only_verified=True)
        self.assertIsNone(scenario.judge(step, record, [], True))
        record['round_trip']['complete'] = False
        self.assertIsNotNone(scenario.judge(step, record, [], True))

    def test_artifact_has_version_binding_hash_and_is_collected_for_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watcher = object.__new__(launcher.FormWatcher)
            watcher.evidence_dir = root / 'form'
            watcher.evidence_dir.mkdir()
            step = dict(index=3, target='Список', record_id=7)
            record = dict(combo_inspection=dict(items=['', 'А', 'А'], selected_index=None, selected_text=None,
                visible=False, enabled=False, read_only_verified=True, focus_before=None, focus_after=None))
            watcher.save_combo_inspection(step, {'id': 20}, record)
            entry = record['inspection_file']
            payload = json.loads((root / entry['path']).read_text(encoding='utf-8'))
            self.assertEqual((payload['schema_version'], payload['step_index'], payload['window_id']), (1, 3, 20))
            self.assertEqual(payload['items'], ['', 'А', 'А'])
            self.assertNotIn('focus_before', payload)  # volatile HWND belongs in the step evidence
            files = launcher.FormAdapter().result_files(root, [])
            self.assertEqual([(f['path'], f['sha256'], f['size']) for f in files],
                             [(entry['path'], entry['sha256'], entry['size'])])
            with patch.object(launcher, 'atomic_json', side_effect=OSError('write failed')):
                failed = dict(combo_inspection=record['combo_inspection'])
                with self.assertRaises(OSError):
                    watcher.save_combo_inspection(dict(step, index=4), {'id': 20}, failed)
                self.assertNotIn('inspection_file', failed)

    def test_watcher_writes_only_after_successful_read_and_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher = object.__new__(launcher.FormWatcher)
            watcher.evidence_dir = Path(tmp) / 'form'
            watcher.evidence_dir.mkdir()
            watcher.description = {'controls': [{'id': 7, 'identifier': 'Список', 'class': 'COMBOBOX'}]}
            watcher.steps = scenario.resolve(scenario.steps({'steps': [{'inspect_combo': 'Список'}]}), watcher.description)
            watcher.round_trip = Mock(return_value=dict(returned=True, complete=True, diagnostics=[], messages=[]))
            form = Mock()
            form.alive.return_value = True
            form.inspect_combo.return_value = dict(items=['А'], selected_index=0, selected_text='А',
                visible=True, enabled=True, read_only_verified=True)
            inspection = dict(chain=[{'hwnd': 10}], controls=[{'id': 4152, 'hwnd': 20}])
            records = watcher.run_steps(form, inspection)
            self.assertEqual(records[0]['status'], 'passed', records)
            self.assertTrue((Path(tmp) / records[0]['inspection_file']['path']).is_file())
            form.inspect_combo.side_effect = RuntimeError('read failed after first item')
            with patch.object(watcher, 'save_combo_inspection') as save:
                records = watcher.run_steps(form, inspection)
                self.assertEqual(records[0]['status'], 'failed')
                self.assertNotIn('combo_inspection', records[0])
                self.assertNotIn('inspection_file', records[0])
                save.assert_not_called()
            watcher.round_trip.return_value['returned'] = False
            form.inspect_combo.reset_mock()
            records = watcher.run_steps(form, inspection)
            self.assertEqual(records[0]['status'], 'failed')
            form.inspect_combo.assert_not_called()


if __name__ == '__main__':
    unittest.main()
