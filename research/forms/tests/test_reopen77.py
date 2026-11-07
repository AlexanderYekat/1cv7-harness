"""Task 033: closed forms cannot supply stale windows or stale closing evidence."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import form_launcher77 as form
import scenario77 as scenario


def parameters(steps):
    return dict(form_object='Документ.ГотоваяПродукция', fixture_setup='Возврат 0;',
                fixture_verify='Возврат "ok";', steps=steps)


def trip(**changes):
    return dict(returned=True, complete=True, diagnostics=[], messages=[], **changes)


class ReopenTests(unittest.TestCase):
    def test_reopen_requires_preceding_steps_and_verified_document_fixture(self):
        sequence = [{'click': 'Закрыть', 'closes': True}, {'reopen': True}, {'value': 'Комментарий', 'text': 'ok'}]
        self.assertEqual(len(scenario.steps(parameters(sequence))), 3)
        for changes in ({'fixture_setup': None}, {'fixture_verify': ''}, {'fixture_mode': 'owner'},
                        {'form_object': 'Справочник.Банки.ФормаЭлемента'}, {'form_object': None},
                        {'steps': [{'reopen': True}]},
                        {'steps': [sequence[0], {'reopen': False}]},
                        {'steps': [sequence[0], {'reopen': True}, {'reopen': True}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                form.FormAdapter().commands(dict(parameters(sequence), **changes), ['verify'])
        adapter = form.FormAdapter()
        adapter.commands(parameters(sequence), ['verify'])
        with self.assertRaisesRegex(ValueError, 'verified base copy'):
            adapter.select_base(Path('does-not-exist'))

    def test_reopen_needs_identity_and_owned_window_and_rejects_ambiguous_answers(self):
        step = {'index': 2, 'kind': 'reopen', 'target': 'reopen'}
        for response in ('', 'reopen-return:0\nreopen-same:1', 'reopen-return:1\nreopen-same:0',
                         'reopen-return:1\nreopen-same:1\nreopen-return:1',
                         'reopen-return:1\nreopen-same:1\nreopen-error:failed'):
            with self.subTest(response=response):
                record = {'round_trip': trip(**scenario.answer(response)), 'reopened': {'found': True},
                          'closed_before_reopen': True}
                self.assertIsNotNone(scenario.judge(step, record, [], True))
        record = {'round_trip': trip(**scenario.answer('reopen-return:1\nreopen-same:1')),
                  'closed_before_reopen': True}
        self.assertIsNotNone(scenario.judge(step, record, [], True))
        record['reopened'] = {'found': True}
        self.assertIsNone(scenario.judge(step, record, [], True))

    def test_old_closing_does_not_prove_reopened_form_closed(self):
        records = [{'closes': True, 'form_open': False}, {'kind': 'reopen', 'form_open': True}]
        self.assertIn('the form was not closed', scenario.judge_result([{}, {}], records, False))
        self.assertEqual(scenario.judge_result([{}, {}], records, True), [])

    def test_watcher_replaces_closed_form_windows_before_next_field_check(self):
        description = {'controls': [{'id': 4152, 'class': '1CEDIT', 'identifier': 'Комментарий',
                                     'caption': '', 'x': 1, 'y': 1, 'width': 20, 'height': 10}]}
        sequence = parameters([{'click': 'Закрыть', 'closes': True}, {'reopen': True},
                               {'check': 'Комментарий', 'text': 'saved'}])
        steps = scenario.resolve(scenario.steps(sequence)[1:], description)
        watcher = form.FormWatcher(Path('.'), {'run_id': 'test'}, 'private', description, [], Path('.'), steps=steps)
        watcher.round_trip = Mock(side_effect=[trip(reopen_return='1', reopen_same='1'), trip()])
        watcher.fields = Mock(return_value={'4152': {'text': 'saved'}})
        owned = Mock()
        owned.alive.side_effect = lambda hwnd: hwnd == 200
        owned.state.return_value = {'ws_visible': True}
        reopened = {'found': True, 'chain': [{'hwnd': 200}], 'controls': [{'id': 4152, 'hwnd': 201,
                                                                                     'rect': [0, 0, 20, 10]}]}
        owned.inspect.return_value = reopened
        owned.element_state.return_value = {'text': 'saved'}
        initial = {'chain': [{'hwnd': 100}], 'controls': [{'id': 4152, 'hwnd': 101}]}
        with patch('form_window77.fit_units', return_value={'consistent': True}):
            records = watcher.run_steps(owned, initial)
        self.assertTrue(all(r['status'] == 'passed' for r in records), records)
        self.assertEqual(owned.element_state.call_args.args[0]['hwnd'], 201)
        owned.alive.side_effect = None
        owned.alive.return_value = True
        watcher.round_trip.reset_mock()
        watcher.round_trip.side_effect = [trip(reopen_close='1')]
        with patch.object(form, 'ACTION_WAIT_S', 0):
            records = watcher.run_steps(owned, initial)
        self.assertEqual(records[0]['status'], 'failed')
        self.assertIn('still open', records[0]['issue'])
        watcher.round_trip.assert_called_once()
        watcher.round_trip.reset_mock()
        watcher.round_trip.side_effect = [trip(reopen_close='1', reopen_error='duplicate reopening response')]
        records = watcher.run_steps(owned, initial)
        self.assertIn('did not close', records[0]['issue'])
        watcher.round_trip.assert_called_once()

    def test_visibility_does_not_prove_destruction_and_hidden_main_is_ignored(self):
        owned = Mock()
        owned.alive.return_value = True
        inspection = {'chain': [{'hwnd': 1}, {'hwnd': 2}, {'hwnd': 3}, {'hwnd': 4}]}
        owned.state.side_effect = lambda hwnd: {'hwnd': hwnd, 'ws_visible': hwnd < 3}
        self.assertTrue(form.FormWatcher.form_presence(owned, inspection)['open'])
        owned.state.side_effect = lambda hwnd: {'hwnd': hwnd, 'ws_visible': hwnd == 1}
        self.assertFalse(form.FormWatcher.form_presence(owned, inspection)['open'])
        self.assertTrue(all(w['exists'] for w in form.FormWatcher.form_presence(owned, inspection)['windows']))


if __name__ == '__main__':
    unittest.main()
