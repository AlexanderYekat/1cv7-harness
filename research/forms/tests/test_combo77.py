"""105: selection contract, dispatch and fail-closed native message outcomes."""
import ctypes as C
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scenario77 as scenario
import form_window77 as window
import form_launcher77 as launcher

DESCRIPTION = {'controls': [{'id': 42, 'class': 'COMBOBOX', 'identifier': 'Вид', 'caption': 'Тип'}]}


class ContractTests(unittest.TestCase):
    def test_select_resolution_and_dialog_chain(self):
        steps = scenario.resolve(scenario.steps({'steps': [
            {'select': 'вид', 'text': 'Второй'}, {'dialog': 'Вопрос', 'button': 'Да'}]}), DESCRIPTION)
        self.assertEqual(steps[0]['record_id'], 42)
        self.assertEqual(steps[1]['chain'], 1)
        self.assertEqual(steps[0]['dialogs'], 1)

    def test_invalid_selects(self):
        for item in ({'select': 'Вид'}, {'select': ''}, {'select': 'Вид', 'text': 2},
                     {'select': 'Вид', 'text': 'a\nb'}, {'select': 'Вид', 'text': 'a', 'row': 1},
                     {'select': 'Вид', 'text': 'a', 'index': 0}):
            with self.subTest(item=item), self.assertRaises(ValueError):
                scenario.steps({'steps': [item]})
        step = scenario.steps({'steps': [{'select': 'Тип', 'text': ''}]})
        for controls in ([], [dict(DESCRIPTION['controls'][0], **{'class': '1CEDIT'})],
                         DESCRIPTION['controls'] * 2):
            with self.assertRaises(ValueError):
                scenario.resolve(step, {'controls': controls})

    def test_unverified_selection_fails_even_with_successful_transport(self):
        step = scenario.steps({'steps': [{'select': 'Вид', 'text': 'a'}]})[0]
        record = {'action': {'combo': True, 'returned': True},
                  'round_trip': {'returned': True, 'complete': True}}
        self.assertIn('selection was not verified', scenario.judge(step, record, [], True))


class NativeContractTests(unittest.TestCase):
    def setUp(self):
        self.form = object.__new__(window.OwnedForm)
        self.form.user = Mock()
        self.form.user.GetParent.return_value = 10
        self.form.user.GetDlgCtrlID.return_value = 42
        self.form.element_state = Mock(return_value={'enabled': True, 'visible': True})
        self.form.combo_state = Mock(return_value={'items': ['Первый', 'Второй'], 'index': 0, 'text': 'Первый'})
        self.form.send = Mock(return_value=(True, 1, 0))
        self.inspection = {'controls': [{'id': 42, 'hwnd': 20}], 'chain': [{'hwnd': 10}]}

    def test_exact_unique_match_before_mutation(self):
        for text, items in [('второй', ['Первый', 'Второй']), ('Втор', ['Второй']),
                            ('Второй', ['Второй', 'Второй']), ('x', [])]:
            self.form.combo_state.return_value = dict(items=items, index=-1, text=None)
            record, pending = self.form.select_combo(self.inspection, 42, text)
            self.assertIn('matching items', record['refused'])
            self.assertIsNone(pending)
        self.form.send.assert_not_called()

    def test_select_notifies_once_and_checks_readback(self):
        with patch.object(window, 'Pending') as pending:
            record, _ = self.form.select_combo(self.inspection, 42, 'Второй')
        pending.assert_called_once_with(self.form, 10, window.WM_COMMAND, (1 << 16) | 42, 20)
        self.form.send.assert_called_once_with(20, 0x014E, 1)
        self.form.combo_state.return_value = dict(items=['Первый', 'Второй'], index=1, text='Второй')
        self.form.combo_selected(record, {'returned': True})
        self.assertTrue(record['selection_verified'])
        self.form.combo_state.return_value['text'] = 'Другой'
        self.form.combo_selected(record, {'returned': True})
        self.assertFalse(record['selection_verified'])

    def test_current_item_is_noop(self):
        record, pending = self.form.select_combo(self.inspection, 42, 'Первый')
        self.assertTrue(record['selection_verified'])
        self.assertFalse(record['notification_sent'])
        self.assertIsNone(pending)
        self.form.send.assert_not_called()

    def test_disabled_hidden_wrong_parent_or_send_failure(self):
        for state in ({'enabled': False, 'visible': True}, {'enabled': True, 'visible': False}, {'error': 'gone'}):
            self.form.element_state.return_value = state
            self.assertIn('refused', self.form.select_combo(self.inspection, 42, 'Второй')[0])
        self.form.send.assert_not_called()
        self.form.element_state.return_value = {'enabled': True, 'visible': True}
        self.form.user.GetParent.return_value = 11
        self.assertIn('parent', self.form.select_combo(self.inspection, 42, 'Второй')[0]['refused'])
        self.form.send.assert_not_called()
        self.form.user.GetParent.return_value = 10
        self.form.send.return_value = (False, 0, 1460)
        with patch.object(window, 'Pending') as pending:
            self.assertIn('CB_SETCURSEL', self.form.select_combo(self.inspection, 42, 'Второй')[0]['refused'])
            pending.assert_not_called()


class ReadbackTests(unittest.TestCase):
    def setUp(self):
        self.form = object.__new__(window.OwnedForm)
        self.form.modal = Mock(server={'pid': 10}, tid=11)
        self.form.modal.owner.return_value = (10, 11)
        self.form.user = Mock()
        def name(hwnd, buffer, size):
            buffer.value = 'ComboBox'
            return 8
        self.form.user.GetClassNameW.side_effect = name
        self.form.style = Mock(return_value=3)
        self.items = ['Оказание услуг', 'Оказание посредн. услуг в торговле']
        def send(hwnd, message, wparam=0, lparam=0):
            if message == 0x0146:
                value = len(self.items)
            elif message == 0x0147:
                value = 1
            elif message == 0x0149:
                value = len(self.items[wparam])
            else:
                buffer = C.create_unicode_buffer(self.items[wparam])
                C.memmove(lparam, buffer, C.sizeof(buffer))
                value = len(self.items[wparam])
            return True, value, 0
        self.form.send = Mock(side_effect=send)

    def test_unicode_items_and_zero_based_selection(self):
        state = self.form.combo_state(20)
        self.assertEqual(state, dict(items=self.items, index=1, text=self.items[1]))

    def test_foreign_window_and_unsupported_style_refused_without_messages(self):
        self.form.modal.owner.return_value = (99, 11)
        with self.assertRaisesRegex(RuntimeError, 'verified server thread'):
            self.form.combo_state(20)
        self.form.modal.owner.return_value = (10, 11)
        for style in (1, 3 | 0x10, 2 | 0x20):
            self.form.style.return_value = style
            with self.assertRaisesRegex(RuntimeError, 'with strings'):
                self.form.combo_state(20)
        self.form.send.assert_not_called()

    def test_count_errors_and_bounds(self):
        for result in ((False, 0, 1460), (True, 0xffffffff, 0), (True, 1001, 0)):
            self.form.send.side_effect = None
            self.form.send.return_value = result
            with self.assertRaises(RuntimeError):
                self.form.combo_state(20)

    def test_missing_selection_and_oversized_text(self):
        original = self.form.send.side_effect
        self.form.send.side_effect = lambda hwnd, msg, *args: ((True, 0xffffffff, 0)
            if msg == 0x0147 else original(hwnd, msg, *args))
        self.assertIsNone(self.form.combo_state(20)['text'])
        self.form.send.side_effect = lambda hwnd, msg, *args: ((True, 4097, 0)
            if msg == 0x0149 else original(hwnd, msg, *args))
        with self.assertRaisesRegex(RuntimeError, '4096'):
            self.form.combo_state(20)


class DispatchTests(unittest.TestCase):
    def test_select_uses_native_combo_action_and_rechecks_after_round_trip(self):
        watcher = object.__new__(launcher.FormWatcher)
        form = Mock()
        form.top_windows.return_value = set()
        record = dict(combo=True, returned=True)
        form.select_combo.return_value = record, None
        step = {'index': 1, 'kind': 'select', 'text': 'Второй'}
        chain = watcher.begin(form, {}, step, {'id': 42}, {}, {})
        form.select_combo.assert_called_once_with({}, 42, 'Второй')
        watcher.call = Mock(return_value={'complete': True})
        form.modal_window.return_value = None
        watcher.settle(form, chain, step)
        form.combo_selected.assert_called_once_with(record, {'returned': True, 'last_error': 0})


if __name__ == '__main__':
    unittest.main()
