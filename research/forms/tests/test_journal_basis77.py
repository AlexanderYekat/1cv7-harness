"""040: fail closed before native dispatch or a transition to the wrong document."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import journal_basis77 as basis
import scenario77 as scenario
import form_launcher77 as form
import test_journal_copy77 as copy_tests
from test_journal_copy77 import BEFORE, NEW
from test_journal_existing77 import parameters, trip

ACTION = dict(journal_basis='Приходный кассовый ордер', source='РасходнаяНакладная', link='ДокументОснование')
ANSWER = NEW.replace('journal-copy:1', 'journal-basis:1') + '\njournal-link:source\njournal-comment:Введен на основании: source'


def profile(**changes):
    return parameters(form_object='Документ.ПриходныйОрдер', **dict(dict(steps=[
        dict(find_document=True, open=False), ACTION, dict(click='Записать'), dict(created=True), dict(reopen=True)]), **changes))


class BasisTests(unittest.TestCase):
    def test_kind_chooser_matches_exact_unique_caption_before_selecting(self):
        import ctypes as C
        import journal77
        for names, succeeds in ((['other', 'target'], True), (['target suffix'], False), (['target', 'target'], False)):
            owned = Mock()
            selected = []
            def send(hwnd, message, wparam=0, lparam=0):
                if message == 0x18B:
                    return True, len(names), 0
                if message == 0x18A:
                    return True, len(names[wparam]), 0
                if message == 0x189:
                    value = C.create_unicode_buffer(names[wparam])
                    C.memmove(lparam, value, C.sizeof(value))
                    return True, len(names[wparam]), 0
                if message == 0x186:
                    selected.append(wparam)
                    return True, wparam, 0
                if message == 0x188:
                    return True, selected[-1], 0
                raise AssertionError(message)
            owned.send.side_effect = send
            owned.answer.return_value = dict(requested=True)
            window = dict(hwnd=1, text='Выбор вида документа', children=[dict(parent=1, hwnd=2,
                visible=True, enabled=True, **{'class': 'ListBox'})])
            evidence = {}
            with patch('scenario77.answer_plan', return_value=(dict(id=1), None, None)):
                if succeeds:
                    journal77.select_kind(owned, window, 'target', evidence=evidence)
                    self.assertEqual(selected, [1])
                else:
                    with self.assertRaises(RuntimeError):
                        journal77.select_kind(owned, window, 'target', evidence=evidence)
                    self.assertEqual(selected, [])
                    owned.answer.assert_not_called()
            self.assertEqual(evidence['names'], names)

    def test_returned_journal_requires_declared_layout_saved_transition_and_native_identity(self):
        for hwnd, expected in ((200, True), (999, False)):
            watcher, owned, _, opened = copy_tests.CopyTests().watcher()
            watcher.return_description = dict(watcher.created_description, form=dict(caption='Касса'))
            watcher.steps = [dict(kind='journal_basis', return_journal='Журнал.Касса.ФормаСписка.ФормаСписка'), dict(kind='created'), dict(kind='click')]
            watcher.round_trip = Mock(return_value=dict(returned=True, complete=True, diagnostics=[],
                journal_return='1', journal_reference='saved', journal_hwnd=str(hwnd)))
            chain = Mock(trips=[], record={})
            with patch('form_window77.fit_units', return_value=dict(consistent=True)):
                if expected:
                    self.assertTrue(basis.returned_journal(watcher, owned, dict(index=3, kind='click', closes=True),
                        [dict(hwnd=200, text='Касса (period)')], chain))
                else:
                    with self.assertRaises(RuntimeError):
                        basis.returned_journal(watcher, owned, dict(index=3, kind='click', closes=True),
                            [dict(hwnd=200, text='Касса (period)')], chain)
            watcher.round_trip.reset_mock()
            self.assertFalse(basis.returned_journal(watcher, owned, dict(index=3, kind='input'),
                [dict(hwnd=200, text='Касса (period)')], chain))
            watcher.round_trip.assert_not_called()
            watcher.steps[0].pop('return_journal')
            self.assertFalse(basis.returned_journal(watcher, owned, dict(index=3, kind='click', closes=True),
                [dict(hwnd=200, text='Касса (period)')], chain))
            watcher.round_trip.assert_not_called()

    def test_runtime_caption_is_explicit_and_cannot_mask_other_controls(self):
        description = dict(controls=[dict(id=1, identifier='Status', caption='original', **{'class': 'STATIC'})])
        step = dict(caption_control='Status', caption_text='expected')
        changed = basis.runtime_description(description, step)
        self.assertEqual(changed['controls'][0]['caption'], 'expected')
        self.assertEqual(description['controls'][0]['caption'], 'original')
        for controls in ([], [dict(description['controls'][0], **{'class': 'BUTTON'})],
                         [dict(description['controls'][0], formula='Value()')]):
            with self.assertRaises(ValueError):
                basis.runtime_description(dict(controls=controls), step)
        with self.assertRaises(ValueError):
            scenario.steps(profile(steps=[dict(find_document=True, open=False), dict(ACTION, caption_control='Status')]))

    def test_order_distinct_kinds_and_identifiers_are_required(self):
        form.FormAdapter().commands(profile(), ['verify'])
        for action in (dict(ACTION, source=''), dict(ACTION, source='ПриходныйОрдер'),
                       dict(ACTION, source='x); Записать()'), dict(ACTION, link=''), dict(ACTION, link='x.y')):
            with self.subTest(action=action), self.assertRaises(ValueError):
                scenario.steps(profile(steps=[dict(find_document=True, open=False), action]))
        for steps in ([ACTION], [dict(find_document=True), ACTION],
                      [dict(find_document=True, open=False), ACTION, ACTION],
                      [dict(find_document=True, open=False), ACTION, dict(reopen=True)],
                      [dict(find_document=True, open=False), dict(ACTION, cancel=True), dict(created=True)]):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                scenario.steps(profile(steps=steps))

    def test_missing_wrong_or_duplicate_basis_link_cannot_pass(self):
        basis.checked_new(trip(ANSWER))
        for answer in ('', ANSWER.replace('journal-link:source', 'journal-link:other'),
                       ANSWER.replace('journal-new:1', 'journal-new:0'),
                       ANSWER.replace('journal-posted:0', 'journal-posted:1'),
                       ANSWER + '\njournal-link:source', ANSWER.replace('journal-comment:', 'journal-error:')):
            with self.subTest(answer=answer), self.assertRaises(RuntimeError):
                basis.checked_new(trip(answer))

    def test_controller_reads_source_and_result_as_distinct_kinds_and_checks_link(self):
        p = profile()
        text = form.controller_text(p, {'type': 'Документ', 'kind': 'РасходнаяНакладная'})
        text = scenario.controller(text, scenario.steps(p), journal_kind='ПриходныйОрдер')
        self.assertIn('Документ.РасходнаяНакладная', text)
        self.assertIn('Документ.ПриходныйОрдер', text)
        self.assertIn('Новый77Контекст.ДокументОснование <> Объект77Данных', text)
        self.assertIn('Док77Чтения.ДокументОснование', text)
        for forbidden in ('.Копировать(', '.Новый(', '.Записать(', '.Провести(', '.ВводНаОсновании('):
            self.assertNotIn(forbidden, text)

    def test_disabled_native_menu_or_wrong_cursor_sends_no_command(self):
        for response, enabled in ((BEFORE, False), (BEFORE.replace('journal-match:1', 'journal-match:0'), True)):
            watcher, owned, inspection, _ = copy_tests.CopyTests().watcher()
            watcher.round_trip = Mock(return_value=trip(response))
            with patch('journal77.native_menu', return_value=dict(enabled=enabled)), patch('form_window77.Pending') as pending:
                with self.assertRaises(RuntimeError):
                    basis.execute(watcher, owned, inspection, dict(index=3), {})
                pending.assert_not_called()

    def test_wrong_link_changed_source_or_stale_form_is_rejected(self):
        for answer, expected in ((ANSWER, True), (ANSWER.replace('hwnd:200', 'hwnd:100'), False),
                                 (ANSWER.replace('journal-source:source', 'journal-source:other'), False),
                                 (ANSWER.replace('journal-value:unchanged', 'journal-value:changed'), False)):
            watcher, owned, inspection, opened = copy_tests.CopyTests().watcher()
            watcher.round_trip = Mock(side_effect=[trip(BEFORE), trip(answer)])
            owned.modal_window.return_value = dict(hwnd=300, text='Выбор вида документа')
            owned.alive.return_value = False
            with patch('journal77.native_menu', return_value=dict(enabled=True)), \
                    patch('journal77.select_kind', return_value=dict(answer=dict(requested=True))), \
                    patch('form_window77.Pending') as pending, patch('form_window77.fit_units', return_value=dict(consistent=True)):
                pending.return_value.done.return_value = True
                pending.return_value.outcome = dict(returned=True)
                if expected:
                    self.assertIs(basis.execute(watcher, owned, inspection, dict(index=3, target='ПКО'), {}), opened)
                else:
                    with self.assertRaises(RuntimeError):
                        basis.execute(watcher, owned, inspection, dict(index=3, target='ПКО'), {})

    def test_unknown_kind_is_cancelled_without_trying_another_kind(self):
        watcher, owned, inspection, _ = copy_tests.CopyTests().watcher()
        watcher.round_trip = Mock(return_value=trip(BEFORE))
        chooser = dict(hwnd=300, text='Выбор вида документа')
        owned.modal_window.return_value = chooser
        with patch('journal77.native_menu', return_value=dict(enabled=True)), \
                patch('journal77.select_kind', side_effect=RuntimeError('not unique')), \
                patch('form_window77.Pending'), patch('scenario77.safe_button', return_value=dict(id=2)):
            with self.assertRaisesRegex(RuntimeError, 'not unique'):
                basis.execute(watcher, owned, inspection, dict(index=3, target='missing'), {})
            owned.answer.assert_called_once_with(chooser, dict(id=2))


if __name__ == '__main__':
    unittest.main()
