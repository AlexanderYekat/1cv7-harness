"""Task 037: exact journal cursor, UI confirmation and disabled repeated command."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_journal_existing77 import parameters, trip
import scenario77
import journal77
import form_launcher77 as launcher


def snapshot(posted='1', hwnd=100, **changes):
    return dict(trip(f'journal-current:target\njournal-match:1\njournal-hwnd:{hwnd}\njournal-posted:{posted}\njournal-value:ok'), **changes)


class JournalUnpostTests(unittest.TestCase):
    def test_profile_requires_cursor_selection_and_expected_readback(self):
        selection = dict(find_document=True, open=False)
        action = dict(journal_unpost=True, expected='ok')
        self.assertEqual(len(scenario77.steps(parameters(steps=[selection, action]))), 2)
        for steps in ([action], [dict(find_document=True), action], [selection, dict(journal_unpost=True)],
                      [selection, dict(action, cancel='yes')], [selection, dict(reopen=True)],
                      [selection, dict(check='Комментарий', text='x')], [selection, dict(key='Down'), action]):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                scenario77.steps(parameters(steps=steps))

    def watcher(self):
        watcher = launcher.FormWatcher(Path('.'), {'run_id': 'test'}, 'private', {}, [], Path('.'))
        owned = Mock()
        owned.inventory.return_value = []
        initial = dict(chain=[dict(hwnd=100)], controls=[dict(id=4151, hwnd=101)])
        return watcher, owned, initial

    def test_selected_search_never_sends_enter_or_binds_document_form(self):
        watcher, owned, initial = self.watcher()
        owned.post_key.return_value = dict(returned=True)
        watcher.round_trip = Mock(return_value=trip('journal-current:target\njournal-match:1\njournal-hwnd:100'))
        record = {}
        self.assertIs(watcher.find_document(owned, initial, dict(index=1, limit=1, open=False), record), initial)
        self.assertTrue(record['cursor_verified'])
        self.assertEqual([c.args[1] for c in owned.post_key.call_args_list], ['End'])
        owned.inspect.assert_not_called()

    def test_changed_or_foreign_cursor_blocks_command_before_menu_access(self):
        for changes in (dict(journal_match='0'), dict(journal_hwnd='999'), dict(complete=False),
                        dict(journal_error='failure'), dict(journal_posted='unknown')):
            watcher, owned, initial = self.watcher()
            watcher.round_trip = Mock(return_value=snapshot(**changes))
            with patch('journal77.unpost_menu') as menu, self.assertRaises(RuntimeError):
                watcher.journal_unpost(owned, initial, dict(index=2, expected='ok'), {})
            menu.assert_not_called()
            owned.post.assert_not_called()

    def test_disabled_repeat_reads_state_without_sending_command(self):
        watcher, owned, initial = self.watcher()
        watcher.round_trip = Mock(return_value=snapshot('0'))
        record = {}
        with patch('journal77.unpost_menu', return_value=dict(enabled=False)):
            watcher.journal_unpost(owned, initial, dict(index=4, enabled=False, expected='ok'), record)
        self.assertFalse(record['action']['requested'])
        self.assertEqual([c.args[0] for c in watcher.round_trip.call_args_list], [-105008, -105009])
        owned.post.assert_not_called()
        with patch('journal77.unpost_menu', return_value=dict(enabled=False)), self.assertRaises(RuntimeError):
            watcher.journal_unpost(owned, initial, dict(index=5, expected='ok'), {})

    def test_only_the_native_unpost_question_can_be_answered(self):
        window = dict(hwnd=1, text='1С:Предприятие', **{'class': '#32770'}, children=[
            dict(hwnd=2, parent=1, id=65535, text=journal77.UNPOST_QUESTION, **{'class': 'Static'}),
            dict(hwnd=3, parent=1, id=6, text='&Да', visible=True, enabled=True, style=0, **{'class': 'Button'}),
            dict(hwnd=4, parent=1, id=7, text='&Нет', visible=True, enabled=True, style=0, **{'class': 'Button'})])
        self.assertEqual(journal77.unpost_answer(window)['id'], 6)
        self.assertEqual(journal77.unpost_answer(window, True)['id'], 7)
        window['children'][0]['text'] = 'Удалить документ?'
        with self.assertRaises(RuntimeError):
            journal77.unpost_answer(window)

    def test_controller_only_reads_saved_state_and_never_reads_document_table_on_journal(self):
        steps = scenario77.steps(parameters(steps=[dict(find_document=True, open=False), dict(journal_unpost=True, expected='ok')]))
        code = scenario77.step_function(steps, table=True, journal_kind='ГотоваяПродукция')
        self.assertIn('Док77Чтения.Проведен()', code)
        self.assertNotIn('Ответ77 = Ответ77 + Harness77Таблица();', code)
        self.assertNotIn('.СделатьНеПроведенным(', code)
        self.assertNotIn('.Провести(', code)


if __name__ == '__main__':
    unittest.main()
