"""090: a wrapper is not a ready cell editor; input is never replayed."""
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import form_launcher77 as launcher
import form_window77 as window

WRAPPER = {"hwnd": 20, "id": 4160, "class": "1CEDIT", "visible": True, "enabled": True}
OUTER = {"hwnd": 20, "id": 4160, "parent_id": 4151}
INNER = {"hwnd": 21, "id": 0, "parent_id": 4160}


class CellReadyTests(unittest.TestCase):
    def setUp(self):
        self.watcher = launcher.FormWatcher(None, {}, None, {}, [], None)
        self.watcher.call = Mock(return_value={"returned": True, "complete": True, "column": "Количество"})
        self.form = Mock()
        self.form.editor_of.return_value = WRAPPER
        self.form.replace_text.return_value = {"typed": True}
        self.form.post_key.return_value = {"returned": True}
        self.form.await_action.return_value = {"returned": True}
        self.step = {"kind": "cell", "column": "Количество", "column_window": 4160, "text": "3"}

    def begin(self):
        return self.watcher.begin_table(self.form, {"chain": [{"hwnd": 10}]}, self.step, {"hwnd": 11}, [])

    def test_ready_requires_inner_focus_for_1cedit(self):
        self.assertFalse(window.cell_editor_ready(OUTER, WRAPPER))
        self.assertTrue(window.cell_editor_ready(INNER, WRAPPER))
        self.assertTrue(window.cell_editor_ready(OUTER, dict(WRAPPER, **{"class": "BMASKED"})))
        for focus, control in ((None, WRAPPER), (INNER, None), (INNER, dict(WRAPPER, enabled=False)),
                               (INNER, dict(WRAPPER, visible=False))):
            self.assertFalse(window.cell_editor_ready(focus, control))

    def test_delayed_inner_editor_is_waited_for_without_reactivation_or_retyping(self):
        self.form.focused.side_effect = [OUTER, OUTER, INNER, INNER]
        chain = self.begin()
        self.watcher.call.assert_called_once_with(self.step)
        self.form.replace_text.assert_called_once_with(21, "3")
        self.form.post_key.assert_called_once_with(21, *launcher.scenario77.KEYS["enter"])
        self.assertEqual([o["ready"] for o in chain.record["editor_wait"]["observations"]], [False, False, True])
        self.assertTrue(chain.record["editor_wait"]["ready"])

    def test_permanent_wrapper_times_out_before_any_write_or_enter(self):
        self.form.focused.return_value = OUTER
        with patch.object(launcher, "CELL_EDITOR_WAIT_S", 0):
            chain = self.begin()
        self.assertIn("no cell editor", chain.record["refused"])
        self.assertFalse(chain.record["editor_wait"]["ready"])
        self.form.replace_text.assert_not_called()
        self.form.post_key.assert_not_called()
        self.watcher.call.assert_called_once()

    def test_cancellation_during_wait_never_types(self):
        self.form.focused.return_value = OUTER
        self.watcher.stopped.set()
        chain = self.begin()
        self.assertIn("no cell editor", chain.record["refused"])
        self.form.replace_text.assert_not_called()
        self.form.post_key.assert_not_called()

    def test_focus_change_after_typing_refuses_enter_without_retyping(self):
        self.form.focused.side_effect = [INNER, {"hwnd": 99}]
        chain = self.begin()
        self.assertIn("focus changed before Enter", chain.record["refused"])
        self.form.replace_text.assert_called_once_with(21, "3")
        self.form.post_key.assert_not_called()


class TextTarget:
    replace_text = window.OwnedForm.replace_text

    def __init__(self, focus=None, fail=None):
        self.user = Mock()
        self.user.GetDlgCtrlID.return_value = 0
        self.user.IsWindowUnicode.return_value = True
        self.focused = Mock(side_effect=focus) if focus is not None else Mock(return_value=INNER)
        self.text = Mock(side_effect=["1.000", "3.000"])
        self.sent = []
        self.fail = fail

    def send(self, hwnd, message, wparam, lparam, timeout_ms, ansi=False):
        self.sent.append((hwnd, message, wparam))
        return (False, 0, 5) if message == self.fail else (True, 0, 0)


class TextTargetTests(unittest.TestCase):
    def test_no_messages_if_focus_is_not_the_target(self):
        target = TextTarget(focus=[OUTER])
        result = target.replace_text(21, "3")
        self.assertFalse(result["typed"])
        self.assertEqual(result["failed_stage"], "focus_before_select")
        self.assertEqual(target.sent, [])

    def test_focus_is_rechecked_before_each_character(self):
        target = TextTarget(focus=[INNER, INNER, OUTER])
        result = target.replace_text(21, "35")
        self.assertFalse(result["typed"])
        self.assertEqual(target.sent, [(21, window.EM_SETSEL, 0), (21, window.WM_CHAR, ord("3"))])

    def test_failed_character_is_never_retried(self):
        target = TextTarget(fail=window.WM_CHAR)
        result = target.replace_text(21, "3")
        self.assertFalse(result["typed"])
        self.assertEqual(result["failed_stage"], "type")
        self.assertEqual([x[1] for x in target.sent], [window.EM_SETSEL, window.WM_CHAR])

    def test_success_has_one_selection_one_character_and_readback(self):
        target = TextTarget()
        result = target.replace_text(21, "3")
        self.assertTrue(result["typed"])
        self.assertEqual(result["text_after"], "3.000")
        self.assertEqual([c["stage"] for c in result["focus_checks"]], ["select", "type", "after_type"])
        self.assertEqual([x[1] for x in target.sent], [window.EM_SETSEL, window.WM_CHAR])

    def test_focus_lost_after_character_refuses_success(self):
        target = TextTarget(focus=[INNER, INNER, OUTER])
        result = target.replace_text(21, "3")
        self.assertFalse(result["typed"])
        self.assertEqual(result["failed_stage"], "focus_after_type")
        self.assertEqual(len(target.sent), 2)


if __name__ == "__main__":
    unittest.main()
