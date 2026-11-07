"""Task 035: bounded search, exact references and owned fresh windows before editing."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import form_launcher77 as form
import scenario77 as scenario


def parameters(**changes):
    return dict(dict(form_object='Документ.ГотоваяПродукция', fixture_mode='journal_existing',
                     journal_form='Журнал.Материалы.ФормаСписка.ФормаСписка', fixture_setup='Возврат 0;',
                     fixture_verify='Возврат "ok";', steps=[{'find_document': True}, {'reopen': True}]), **changes)


def trip(answer):
    return dict(returned=True, complete=True, diagnostics=[], messages=[], **scenario.answer(answer))


class ExistingJournalTests(unittest.TestCase):
    def test_profile_refuses_wrong_mode_order_unbounded_search_and_programmatic_posting(self):
        p = parameters()
        form.FormAdapter().commands(p, ['verify'])
        for changes in ({'fixture_mode': 'existing'}, {'fixture_mode': 'journal'}, {'steps': None},
                        {'steps': [{'find_document': False}]}, {'fixture_post': True},
                        {'fixture_operations': [{'id': 'post', 'action': 'post'}]},
                        {'steps': [{'find_document': True, 'limit': 201}]},
                        {'steps': [{'find_document': True, 'limit': 0}]},
                        {'steps': [{'find_document': True, 'limit': True}]},
                        {'steps': [{'find_document': True}, {'close_form': False}]},
                        {'steps': [{'check': 'Комментарий', 'text': 'x'}, {'find_document': True}]},
                        {'steps': [{'find_document': True}, {'find_document': True}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                form.FormAdapter().commands(dict(p, **changes), ['verify'])
        adapter = form.FormAdapter()
        adapter.commands(p, ['verify'])
        with self.assertRaisesRegex(ValueError, 'verified base copy'):
            adapter.select_base(Path('missing'))

    def test_controller_opens_journal_without_target_and_requires_exact_saved_reference(self):
        p = parameters()
        text = form.controller_text(p, {'type': 'Документ', 'kind': 'ГотоваяПродукция'})
        text = scenario.controller(text, scenario.steps(p), table=True, journal_kind='ГотоваяПродукция')
        self.assertIn('ОткрытьФорму("Журнал.Материалы.ФормаСписка", Контекст77)', text)
        self.assertIn('fixture-initial:', text)
        self.assertIn('Ссылка77 <> Объект77Данных', text)
        self.assertIn('Док77Чтения.НайтиДокумент(Ссылка77)', text)
        # The only direct document opening is the later, explicitly requested reopen.
        self.assertEqual(text.count('ОткрытьФорму(Объект77Данных,'), 1)
        for forbidden in ('.АктивизироватьОбъект(', '.Записать(', '.Провести('):
            self.assertNotIn(forbidden, text)

    def watcher(self):
        desc = {'controls': [{'id': 4152, 'class': '1CEDIT', 'identifier': 'Комментарий',
                             'caption': '', 'x': 1, 'y': 1, 'width': 20, 'height': 10}]}
        watcher = form.FormWatcher(Path('.'), {'run_id': 'test'}, 'private', {}, [], Path('.'),
                                   created_description=desc)
        owned = Mock()
        owned.inventory.return_value = [{'hwnd': 100}, {'hwnd': 101}]
        owned.post_key.side_effect = lambda hwnd, name, *args: {'returned': True, 'key': name}
        initial = {'chain': [{'hwnd': 100}], 'controls': [{'id': 4151, 'hwnd': 101}]}
        opened = {'found': True, 'chain': [{'hwnd': 200}],
                  'controls': [{'id': 4152, 'hwnd': 201, 'rect': [0, 0, 20, 10]}]}
        owned.inspect.return_value = opened
        return watcher, owned, initial, opened

    def test_limit_missing_cursor_foreign_hwnd_or_diagnostics_never_send_enter(self):
        answers = ['journal-current:neighbor\njournal-match:0\njournal-hwnd:100',
                   'journal-match:1\njournal-hwnd:100',
                   'journal-current:target\njournal-match:1\njournal-hwnd:999',
                   'journal-current:target\njournal-match:1\njournal-match:1\njournal-hwnd:100']
        for answer in answers:
            watcher, owned, initial, _ = self.watcher()
            watcher.round_trip = Mock(return_value=trip(answer))
            with self.subTest(answer=answer), self.assertRaises(RuntimeError):
                watcher.find_document(owned, initial, {'index': 1, 'limit': 1}, {})
            self.assertEqual([c.args[1] for c in owned.post_key.call_args_list], ['End'])

    def test_exact_match_opens_with_enter_but_stale_or_foreign_form_cannot_pass(self):
        for hwnd in (100, 999, 200):
            watcher, owned, initial, opened = self.watcher()
            watcher.round_trip = Mock(side_effect=[
                trip('journal-current:neighbor\njournal-match:0\njournal-hwnd:100'),
                trip('journal-current:target\njournal-match:1\njournal-hwnd:100'),
                trip(f'journal-opened:1\njournal-match:1\njournal-reference:target\njournal-hwnd:{hwnd}')])
            record = {}
            with patch('form_window77.fit_units', return_value={'consistent': True}):
                if hwnd == 200:
                    self.assertIs(watcher.find_document(owned, initial, {'index': 1, 'limit': 2}, record), opened)
                    self.assertTrue(record['existing_form_verified'])
                else:
                    with self.assertRaisesRegex(RuntimeError, 'identity/layout'):
                        watcher.find_document(owned, initial, {'index': 1, 'limit': 2}, record)
            self.assertEqual([c.args[1] for c in owned.post_key.call_args_list], ['End', 'Up', 'Enter'])

    def test_missing_or_duplicate_opened_reference_is_a_failure(self):
        step = {'index': 1, 'kind': 'find_document', 'target': 'find_document'}
        for answer in ('', 'journal-match:1', 'journal-opened:1\njournal-match:1\njournal-error:',
                       'journal-opened:1\njournal-opened:1\njournal-match:1'):
            with self.subTest(answer=answer):
                self.assertIsNotNone(scenario.judge(step, {'existing_form_verified': True,
                                                          'round_trip': trip(answer)}, [], True))


    def test_close_frame_never_targets_uninspected_main_window(self):
        step = {'index': 1, 'kind': 'close_form', 'target': 'close_form'}
        watcher = form.FormWatcher(Path('.'), {'run_id': 'test'}, 'private', {'controls': []}, [],
                                   Path('.'), steps=[step])
        owned = Mock()
        inspection = {'chain': [{'hwnd': 100}, {'hwnd': 101}, {'hwnd': 102, 'class': 'MainWindow'}], 'controls': []}
        records = watcher.run_steps(owned, inspection)
        self.assertIn('inspected MDI', records[0]['issue'])
        owned.send.assert_not_called()
        owned.element_state.assert_not_called()

    def test_independent_verifier_rejects_unlinked_cursor_evidence(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
        from verify_journal_existing77 import step_issues
        row = {'action': {'key': 'End', 'id': 4151, 'returned': True, 'identity_rechecked': True},
               'round_trip': trip('journal-current:neighbor\njournal-match:0\njournal-hwnd:100')}
        records = [{'kind': 'find_document', 'index': 1, 'limit': 1, 'search': [row], 'status': 'failed',
                    'issue': 'document not found within journal search limit'}]
        self.assertIn('cursor inspection differs from the independently checked raw call', step_issues(records, 'wrong-limit'))
        self.assertTrue(step_issues([{'kind': 'find_document', 'index': 1}], 'success'))


if __name__ == '__main__':
    unittest.main()
