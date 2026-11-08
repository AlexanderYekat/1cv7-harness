"""Task 038: refuse an unsafe toggle, verify saved mark and exact confirmation."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_journal_existing77 import parameters, trip
import test_journal_unpost77
import journal77
import journal_deletion77 as deletion
import scenario77


def snapshot(deleted='0', posted='1', reference='target', **changes):
    return dict(trip(f'journal-current:{reference}\njournal-match:1\njournal-hwnd:100\njournal-posted:{posted}\njournal-deleted:{deleted}\njournal-value:ok'), **changes)


def window(question):
    return dict(hwnd=1, text='1С:Предприятие', **{'class': '#32770'}, children=[
        dict(hwnd=2, parent=1, id=65535, text=question, **{'class': 'Static'}),
        dict(hwnd=3, parent=1, id=6, text='&Да', visible=True, enabled=True, style=0, **{'class': 'Button'}),
        dict(hwnd=4, parent=1, id=7, text='&Нет', visible=True, enabled=True, style=0, **{'class': 'Button'})])


class JournalDeletionTests(unittest.TestCase):
    def test_profile_requires_selection_explicit_direction_and_readback(self):
        select = dict(find_document=True, open=False)
        action = dict(journal_deletion=True, deleted=True, expected='ok')
        self.assertEqual(len(scenario77.steps(parameters(steps=[select, action, dict(action, deleted=False)]))), 3)
        for steps in ([action], [dict(find_document=True), action], [select, dict(journal_deletion=True, expected='ok')],
                      [select, dict(journal_deletion=True, deleted=True)], [select, dict(action, deleted=1)],
                      [select, dict(action, cancel='yes')], [select, dict(key='Delete')]):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                scenario77.steps(parameters(steps=steps))

    def watcher(self):
        watcher, owned, inspection = test_journal_unpost77.JournalUnpostTests().watcher()
        inspection['chain'].append(dict(hwnd=110))
        watcher.calls = {}
        return watcher, owned, inspection

    def test_invalid_or_already_requested_state_never_reaches_menu_or_dispatch(self):
        for changes in (dict(journal_deleted='1'), dict(journal_deleted=None), dict(journal_deleted='2'),
                        dict(journal_match='0'), dict(journal_hwnd='999'), dict(complete=False),
                        dict(journal_error='bad'), dict(journal_posted='unknown')):
            watcher, owned, initial = self.watcher()
            watcher.round_trip = Mock(return_value=snapshot(**changes))
            with patch('journal77.native_menu') as menu, patch('form_window77.Pending') as pending, self.assertRaises(RuntimeError):
                watcher.journal_deletion(owned, initial, dict(index=2, deleted=True, expected='ok'), {})
            menu.assert_not_called()
            pending.assert_not_called()

    def test_disabled_menu_never_dispatches(self):
        watcher, owned, initial = self.watcher()
        watcher.round_trip = Mock(return_value=snapshot())
        with patch('journal77.native_menu', return_value=dict(enabled=False)), patch('form_window77.Pending') as pending, self.assertRaises(RuntimeError):
            watcher.journal_deletion(owned, initial, dict(index=2, deleted=True, expected='ok'), {})
        pending.assert_not_called()

    def test_exact_mark_and_unmark_questions_and_answer_ids(self):
        for deleted, question in ((True, deletion.MARK_QUESTION), (False, deletion.UNMARK_QUESTION)):
            self.assertEqual(deletion.answer(window(question), deleted)['id'], 6)
            self.assertEqual(deletion.answer(window(question), deleted, cancel=True)['id'], 7)
            for bad in (journal77.UNPOST_QUESTION, 'Удалить физически?', ''):
                with self.assertRaises(RuntimeError):
                    deletion.answer(window(bad), deleted)

    def run_toggle(self, before, after, deleted=True, cancel=False, confirmation=True):
        watcher, owned, initial = self.watcher()
        watcher.round_trip = Mock(side_effect=[before, after])
        watcher.settle = Mock()
        record = {}
        chain = Mock()
        chain.trips = []
        chain.window = window(deletion.MARK_QUESTION if deleted else deletion.UNMARK_QUESTION) if confirmation else None
        def wait():
            if chain.wait.call_count == 2:
                chain.window = None
        chain.wait.side_effect = wait
        owned.answer.return_value = dict(requested=True)
        def make_chain(form, action, *args):
            action['returned'] = True
            return chain
        def make_pending(*args):
            # Snapshot before sending: a fast modal must not enter the baseline set.
            self.assertTrue(owned.top_windows.called)
        with patch('journal77.native_menu', return_value=dict(enabled=True)), patch('form_window77.Pending', side_effect=make_pending), patch('form_launcher77.Chain', side_effect=make_chain):
            watcher.journal_deletion(owned, initial, dict(index=3, deleted=deleted, cancel=cancel, expected='ok'), record)
        return record

    def test_mark_unmark_and_cancel_require_persisted_state_after_ui(self):
        for deleted, cancel in ((True, False), (False, False), (True, True), (False, True)):
            before_mark = '0' if deleted else '1'
            after_mark = before_mark if cancel else str(int(deleted))
            record = self.run_toggle(snapshot(before_mark), snapshot(after_mark), deleted, cancel)
            self.assertEqual(record['calls'][0]['number'], -107006)
            self.assertEqual(record['calls'][-1]['number'], -107007)
            for changes in (dict(journal_deleted=before_mark if not cancel else str(int(deleted))),
                            dict(journal_value='changed neighbor'), dict(journal_current='other')):
                with self.subTest(deleted=deleted, cancel=cancel, changes=changes), self.assertRaises(RuntimeError):
                    self.run_toggle(snapshot(before_mark), snapshot(after_mark, **changes), deleted, cancel)
        with self.assertRaises(RuntimeError):
            self.run_toggle(snapshot(), snapshot(), cancel=True, confirmation=False)

    def test_controller_only_reads_mark_and_never_mutates_or_opens_target(self):
        items = scenario77.steps(parameters(steps=[dict(find_document=True, open=False), dict(journal_deletion=True, deleted=True, expected='ok')]))
        code = scenario77.step_function(items, table=True, journal_kind='ГотоваяПродукция')
        self.assertIn('Док77Чтения.ПометкаУдаления()', code)
        for forbidden in ('.Удалить(', '.СнятьПометкуУдаления(', '.УстановитьПометкуУдаления(', '.Провести(', '.СделатьНеПроведенным(', 'Ответ77 = Ответ77 + Harness77Таблица();'):
            self.assertNotIn(forbidden, code)
        parsed = scenario77.answer('journal-deleted:0\njournal-deleted:1')
        self.assertIn('journal_error', parsed)


if __name__ == '__main__':
    unittest.main()
