"""039: source/copy identity, cursor and fresh-window guards before any UI write."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import form_launcher77 as form
import journal_copy77 as copying
from form_window77 import OwnedForm
import scenario77 as scenario
from test_journal_existing77 import parameters, trip


def profile():
    return parameters(steps=[{'find_document': True, 'open': False}, {'journal_copy': True},
                             {'click': 'Записать'}, {'created': True}, {'reopen': True}])


NEW = ('journal-new:1\njournal-copy:1\njournal-source:source\njournal-hwnd:200\n'
       'journal-date:2026:8:1\njournal-number:00004\njournal-posted:0\njournal-deleted:0\njournal-value:unchanged')
BEFORE = ('journal-current:source\njournal-match:1\njournal-hwnd:100\n'
          'journal-posted:1\njournal-deleted:0\njournal-value:unchanged')


class CopyTests(unittest.TestCase):
    def test_character_conversion_uses_owned_desktop_and_restores_both_layouts(self):
        for rejected in (False, True):
            owned = object.__new__(OwnedForm)
            owned.modal = Mock(server={'pid': 1}, tid=2, desktop='harness77_test')
            owned.modal.owner.return_value = (1, 2)
            owned.user = Mock()
            layouts = {0: 0x4090409, 2: 0x4090409}
            owned.user.GetKeyboardLayout.side_effect = lambda tid: layouts[tid]
            def available(count, values):
                if values is not None:
                    values[0], values[1] = 0x4090409, 0x4190419
                return 2
            def activate(layout, flags):
                self.assertEqual(flags, 0)
                old, layouts[0] = layouts[0], layout
                return old
            def send_w(hwnd, message, wparam, lparam, *args):
                if message == 0x50 and not rejected:
                    layouts[2] = lparam
                return 1
            owned.user.GetKeyboardLayoutList.side_effect = available
            owned.user.ActivateKeyboardLayout.side_effect = activate
            owned.user.SendMessageTimeoutW.side_effect = send_w
            def send_a(*args):
                self.assertEqual(layouts, {0: 0x4190419, 2: 0x4190419})
                return 1
            owned.user.SendMessageTimeoutA.side_effect = send_a
            with patch('form_window77.on_desktop', side_effect=lambda desktop, work, timeout: work()) as scope:
                if rejected:
                    with self.assertRaisesRegex(RuntimeError, 'owned editor input layout differs'):
                        owned.send(100, 0x102, 0xca, ansi=True)
                    owned.user.SendMessageTimeoutA.assert_not_called()
                else:
                    self.assertTrue(owned.send(100, 0x102, 0xca, ansi=True)[0])
                self.assertEqual(scope.call_args.args[0], 'harness77_test')
            self.assertEqual(layouts, {0: 0x4090409, 2: 0x4090409})

    def test_requires_exact_unopened_cursor_and_copy_before_capture_or_reopen(self):
        p = profile()
        form.FormAdapter().commands(p, ['verify'])
        for steps in ([{'journal_copy': True}], [{'find_document': True}, {'journal_copy': True}],
                      [{'find_document': True, 'open': False}, {'journal_copy': False}],
                      [{'find_document': True, 'open': False}, {'journal_copy': True}, {'journal_copy': True}],
                      [{'find_document': True, 'open': False}, {'journal_copy': True}, {'reopen': True}],
                      [{'find_document': True, 'open': False}, {'journal_copy': True}, {'journal_unpost': True, 'expected': 'ok'}],
                      [{'find_document': True, 'open': False}, {'created': True}]):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                scenario.steps(dict(p, steps=steps))
        adapter = form.FormAdapter()
        adapter.commands(p, ['verify'])
        with self.assertRaisesRegex(ValueError, 'verified base copy'):
            adapter.select_base(Path('missing'))

    def test_incomplete_duplicate_saved_or_posted_copy_response_cannot_pass(self):
        copying.checked_new(trip(NEW))
        for answer in ('', NEW.replace('journal-new:1', 'journal-new:0'),
                       NEW.replace('journal-posted:0', 'journal-posted:1'),
                       NEW.replace('journal-deleted:0', 'journal-deleted:1'),
                       NEW.replace('journal-source:source', 'journal-source:'),
                       NEW + '\njournal-copy:1', NEW + '\njournal-error:'):
            with self.subTest(answer=answer), self.assertRaises(RuntimeError):
                copying.checked_new(trip(answer))

    def test_controller_keeps_source_distinct_and_does_not_copy_or_save_programmatically(self):
        p = profile()
        text = form.controller_text(p, {'type': 'Документ', 'kind': 'ГотоваяПродукция'})
        text = scenario.controller(text, scenario.steps(p), table=True, journal_kind='ГотоваяПродукция')
        self.assertIn('Объект77Источник = Объект77Данных', text)
        self.assertIn('Ссылка77 = Объект77Источник', text)
        self.assertIn('Ссылка77.Выбран() <> 0', text)
        self.assertIn('Док77Чтения.НайтиДокумент(Ссылка77)', text)
        self.assertIn('Если (Номер77Шага >= 2) Тогда', text)
        for forbidden in ('.Копировать(', '.Новый(', '.Записать(', '.Провести(', '.СделатьНеПроведенным('):
            self.assertNotIn(forbidden, text)

    def watcher(self):
        desc = {'controls': [{'id': 4152, 'class': '1CEDIT', 'identifier': 'Комментарий',
                             'caption': '', 'x': 1, 'y': 1, 'width': 20, 'height': 10}]}
        watcher = form.FormWatcher(Path('.'), {'run_id': 'test'}, 'private', {}, [], Path('.'),
                                   created_description=desc)
        owned = Mock()
        owned.inventory.return_value = [{'hwnd': 100}, {'hwnd': 101}]
        owned.top_windows.return_value = {100}
        opened = {'found': True, 'chain': [{'hwnd': 200}],
                  'controls': [{'id': 4152, 'hwnd': 201, 'rect': [0, 0, 20, 10]}]}
        owned.inspect.return_value = opened
        initial = {'chain': [{'hwnd': 100}, {'hwnd': 101}], 'controls': []}
        return watcher, owned, initial, opened

    def test_unverified_cursor_never_sends_copy(self):
        for answer in ('', BEFORE.replace('journal-match:1', 'journal-match:0'),
                       BEFORE.replace('journal-hwnd:100', 'journal-hwnd:999'), BEFORE + '\njournal-current:other'):
            watcher, owned, initial, _ = self.watcher()
            watcher.round_trip = Mock(return_value=trip(answer))
            with patch('form_window77.Pending') as pending, self.assertRaises(RuntimeError):
                watcher.copy_document(owned, initial, {'index': 2}, {})
            pending.assert_not_called()

    def test_disabled_menu_never_sends_copy(self):
        watcher, owned, initial, _ = self.watcher()
        watcher.round_trip = Mock(return_value=trip(BEFORE))
        with patch('journal77.native_menu', return_value={'enabled': False}), patch('form_window77.Pending') as pending:
            with self.assertRaisesRegex(RuntimeError, 'disabled'):
                watcher.copy_document(owned, initial, {'index': 2}, {})
            pending.assert_not_called()

    def test_foreign_stale_window_or_changed_source_cannot_pass_even_after_copy_returned(self):
        for answer, expected in ((NEW, True), (NEW.replace('hwnd:200', 'hwnd:100'), False),
                                 (NEW.replace('hwnd:200', 'hwnd:999'), False),
                                 (NEW.replace('journal-source:source', 'journal-source:other'), False),
                                 (NEW.replace('journal-value:unchanged', 'journal-value:changed'), False)):
            watcher, owned, initial, opened = self.watcher()
            watcher.round_trip = Mock(side_effect=[trip(BEFORE), trip(answer)])
            with patch('journal77.native_menu', return_value={'enabled': True}), \
                    patch('form_window77.Pending') as pending, \
                    patch('form_window77.fit_units', return_value={'consistent': True}):
                pending.return_value.done.return_value = True
                pending.return_value.outcome = {'returned': True}
                if expected:
                    record = {}
                    self.assertIs(watcher.copy_document(owned, initial, {'index': 2}, record), opened)
                    self.assertTrue(record['new_form_verified'])
                else:
                    with self.assertRaises(RuntimeError):
                        watcher.copy_document(owned, initial, {'index': 2}, {})

    def test_independent_verifier_requires_search_copy_and_raw_call_provenance(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
        from verify_journal_copy77 import step_issues
        self.assertTrue(step_issues([], 'success', {}, {'pid': 1, 'tid': 2}))
        records = [{'kind': 'journal_period'}, {'kind': 'find_document', 'open': False},
                   {'kind': 'journal_copy', 'new_form_verified': True, 'round_trip': trip(NEW)}]
        self.assertTrue(step_issues(records, 'cancel', {'chain': []}, {'pid': 1, 'tid': 2}))


if __name__ == '__main__':
    unittest.main()
