"""Task 034: reject stale/saved contexts, unverified references and unsafe profiles."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import form_launcher77 as form
import fixture77
import journal77
import scenario77 as scenario


def parameters(**changes):
    return dict(form_object='Документ.ГотоваяПродукция', fixture_mode='journal',
                journal_form='Журнал.Товары.ФормаСписка.ФормаСписка',
                fixture_setup='Возврат 0;', fixture_verify='Возврат "ok";',
                steps=[{'create': 'Готовая продукция'}, {'click': 'Записать'}, {'created': True},
                       {'reopen': True}], **changes)


def trip(text):
    return dict(returned=True, complete=True, diagnostics=[], messages=[], **scenario.answer(text))


class JournalTests(unittest.TestCase):
    def test_requires_verified_copy_and_explicit_journal_with_no_programmatic_posting(self):
        p = parameters()
        adapter = form.FormAdapter()
        adapter.commands(p, ['verify'])
        with self.assertRaisesRegex(ValueError, 'verified base copy'):
            adapter.select_base(Path('missing'))
        for changes in ({'fixture_post': True}, {'fixture_operations': [{'id': 'a', 'action': 'post'}]},
                        {'journal_form': None}, {'journal_form': 'Документ.ГотоваяПродукция'},
                        {'fixture_verify': ''}, {'form_object': 'Справочник.Банки.ФормаЭлемента'},
                        {'fixture_mode': 'existing'}, {'steps': None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                adapter.commands(dict(p, **changes), ['verify'])

    def test_creation_starts_in_journal_and_capture_precedes_reopening(self):
        p = parameters()
        self.assertEqual(len(scenario.steps(p)), 4)
        for steps in ([{'create': ''}], [{'created': True}],
                      [{'create': 'Готовая продукция'}, {'reopen': True}],
                      [{'click': 'Записать'}, {'create': 'Готовая продукция'}]):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                scenario.steps(dict(p, steps=steps))

    def test_missing_ambiguous_or_unsaved_reference_cannot_pass(self):
        capture = dict(index=3, kind='created', target='created')
        for answer in ('', 'journal-saved:0\njournal-reference:doc', 'journal-saved:1',
                       'journal-saved:1\njournal-reference:doc\njournal-saved:1',
                       'journal-saved:1\njournal-reference:doc\njournal-saved:1\njournal-error:',
                       'journal-saved:1\njournal-reference:doc\njournal-unknown:1',
                       'journal-saved:1\njournal-reference:doc\njournal-error:',
                       'journal-saved:1\njournal-reference:doc\njournal-error:foreign'):
            with self.subTest(answer=answer):
                self.assertIsNotNone(scenario.judge(capture, {'round_trip': trip(answer)}, [], True))
        self.assertIsNone(scenario.judge(capture, {'round_trip': trip('journal-saved:1\njournal-reference:doc')}, [], True))
        create = dict(index=1, kind='create', target='Готовая продукция')
        record = dict(round_trip=trip('journal-new:1\njournal-hwnd:200'))
        self.assertIsNotNone(scenario.judge(create, record, [], True))
        record['new_form_verified'] = True
        self.assertIsNone(scenario.judge(create, record, [], True))
        record['round_trip'] = trip('journal-new:1\njournal-new:1\njournal-hwnd:200')
        self.assertIsNotNone(scenario.judge(create, record, [], True))

    def test_controller_opens_journal_and_only_reads_new_document_reference(self):
        p = parameters()
        text = form.controller_text(p, {'kind': 'ГотоваяПродукция'})
        text = scenario.controller(text, scenario.steps(p), table=True, journal_kind='ГотоваяПродукция')
        self.assertIn('ОткрытьФорму("Журнал.Товары.ФормаСписка", Контекст77)', text)
        self.assertIn('Сервис77.АктивныйКонтекст(Новый77Контекст)', text)
        self.assertIn('Ссылка77.Выбран() <> 0', text)
        self.assertIn('Док77Чтения.НайтиДокумент(Ссылка77)', text)
        self.assertIn('Объект77Данных <> Ссылка77', text)
        for forbidden in ('.Новый(', '.Записать(', '.Провести(', '.СделатьНеПроведенным('):
            self.assertNotIn(forbidden, text)

    def test_kind_selection_rejects_foreign_and_ambiguous_windows_before_answering(self):
        owned = Mock()
        for window in ({'text': 'Чужое окно'}, {'text': 'Выбор вида документа', 'hwnd': 1, 'children': []}):
            with self.assertRaises(RuntimeError):
                journal77.select_kind(owned, window, 'Готовая продукция')
        owned.answer.assert_not_called()

    def test_creation_refuses_old_or_foreign_form_hwnd_even_with_success_response(self):
        desc = {'controls': [{'id': 4152, 'class': '1CEDIT', 'identifier': 'Комментарий',
                              'caption': '', 'x': 1, 'y': 1, 'width': 20, 'height': 10}]}
        watcher = form.FormWatcher(Path('.'), {'run_id': 'test'}, 'private', {}, [], Path('.'),
                                   created_description=desc)
        owned = Mock()
        owned.inventory.return_value = [{'hwnd': 100}, {'hwnd': 101}]
        owned.top_windows.return_value = {100}
        owned.modal_window.return_value = {'hwnd': 150, 'text': 'Выбор вида документа'}
        owned.alive.return_value = False
        owned.post_key.return_value = {'returned': True}
        created = {'found': True, 'chain': [{'hwnd': 200}],
                   'controls': [{'id': 4152, 'hwnd': 201, 'rect': [0, 0, 20, 10]}]}
        owned.inspect.return_value = created
        initial = {'chain': [{'hwnd': 100}], 'controls': [{'id': 4151, 'hwnd': 101}]}
        step = {'index': 1, 'kind': 'create', 'target': 'Готовая продукция'}
        with patch('journal77.select_kind', return_value={'answer': {'requested': True}}), \
                patch('form_window77.fit_units', return_value={'consistent': True}):
            for hwnd in ('100', '999'):
                watcher.round_trip = Mock(return_value=trip(f'journal-new:1\njournal-hwnd:{hwnd}'))
                with self.subTest(hwnd=hwnd), self.assertRaisesRegex(RuntimeError, 'identity/layout'):
                    watcher.create_document(owned, initial, step, {})
            watcher.round_trip = Mock(return_value=trip('journal-new:1\njournal-hwnd:200'))
            record = {}
            self.assertIs(watcher.create_document(owned, initial, step, record), created)
            self.assertTrue(record['new_form_verified'])

    def test_independent_verifier_rejects_missing_ui_creation_provenance(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
        from verify_journal_document77 import step_issues
        self.assertTrue(step_issues([], 'success'))
        self.assertTrue(step_issues([{'kind': 'create', 'status': 'passed', 'new_form_verified': True,
                                     'round_trip': {'journal_new': '1'}}], 'cancel'))


if __name__ == '__main__':
    unittest.main()
