"""Timeout/dismissal evidence and rejection of foreign or ambiguous windows."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ert_probe77 import read_results
from modal_wait77 import modal_text, select_dialog
from shutdown77 import sha256, atomic_json

# Import the adapter without loading any native library on portable test hosts.
spec = importlib.util.spec_from_file_location("modal77_simulated", Path(__file__).resolve().parents[1] / "win32_modal77.py")
native = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"desktop77": Mock(), "win32_session77": Mock()}):
    spec.loader.exec_module(native)


def dialog():
    return {"hwnd": 100, "pid": 77, "tid": 88, "class": "#32770", "desktop": "harness77_test",
            "visible": True, "owner": 99, "owner_pid": 77, "owner_tid": 88, "owner_enabled": False,
            "children": [{"hwnd": 101, "pid": 77, "tid": 88, "class": "Static", "text": modal_text("new-run")},
                         {"hwnd": 102, "pid": 77, "tid": 88, "class": "Button", "id": 2, "text": "OK",
                          "visible": True, "enabled": True}]}


class ModalPolicyTests(unittest.TestCase):
    def choose(self, windows):
        return select_dialog(windows, "new-run", 77, 88, "harness77_test")

    def test_unique_warning_and_ignore_foreign_windows(self):
        foreign = dict(dialog(), pid=123)
        self.assertEqual(self.choose([foreign, dialog()]), dialog())

    def test_no_global_fallback_or_ambiguous_choice(self):
        for windows in ([], [dialog(), dialog()]):
            with self.assertRaises(ValueError):
                self.choose(windows)

    def test_each_identity_and_modal_constraint(self):
        for key, value in {"pid": 123, "tid": 123, "desktop": "Default", "class": "Other",
                           "visible": False, "owner": 0, "owner_pid": 123, "owner_tid": 123,
                           "owner_enabled": True}.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.choose([dict(dialog(), **{key: value})])

    def test_foreign_text_button_and_child_rejected(self):
        for index, key, value in ((0, "text", modal_text("old-run")), (0, "pid", 99),
                                  (0, "tid", 99), (1, "id", 1), (1, "text", "Cancel"), (1, "enabled", False),
                                  (1, "visible", False), (1, "class", "Other")):
            changed = dialog()
            changed["children"][index][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.choose([changed])
        changed = dialog()
        changed["children"].append(changed["children"][1].copy())
        with self.assertRaises(ValueError):
            self.choose([changed])


class ModalMessageTests(unittest.TestCase):
    def setUp(self):
        self.modal = native.OwnedModal.__new__(native.OwnedModal)
        self.modal.server, self.modal.tid = {"pid": 77}, 88
        self.modal.desktop, self.modal.run_id = "harness77_test", "new-run"
        self.modal.user = Mock()
        self.modal.snapshot = Mock(return_value=[dialog()])

    def test_only_exact_revalidated_dialog_receives_command(self):
        result = self.modal.dismiss([dialog()])
        self.modal.snapshot.assert_called_once_with()
        self.modal.user.PostMessageW.assert_called_once_with(100, 0x0111, 2, 102)
        self.assertTrue(result["identity_rechecked"])

    def test_disappeared_changed_or_foreign_dialog_is_never_messaged(self):
        for replacement in ([], [dict(dialog(), hwnd=200)], [dict(dialog(), pid=99)]):
            self.modal.snapshot.return_value = replacement
            with self.subTest(replacement=replacement), self.assertRaises((RuntimeError, ValueError)):
                self.modal.dismiss([dialog()])
            self.modal.user.PostMessageW.assert_not_called()

    def test_process_identity_failure_never_sends_message(self):
        self.modal.snapshot.side_effect = RuntimeError("retained server exited")
        with self.assertRaises(RuntimeError):
            self.modal.dismiss([dialog()])
        self.modal.user.PostMessageW.assert_not_called()


class WaitEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name)
        artifact = self.out / "test.ert"
        artifact.write_bytes(b"validator fixture only")
        self.manifest = {"run_id": "new-run", "identity": "new-run:wait", "case": "wait",
            "ert_path": str(artifact), "sources": {artifact.name: sha256(artifact)},
            "commands": ["check", "wait"], "expected_error_line": None}
        self.events = [{"kind": "phase", "name": name, "value": "ok", "run_id": "new-run", "elapsed_ms": 0}
                       for name in ("base", "controller")]
        for name in ("check", "wait"):
            self.events.append({"kind": "ert", "name": name, "run_id": "new-run", "elapsed_ms": 31000 if name == "wait" else 1,
                "value": "selected:" + str(artifact) + "\nopen-return:0\nloaded:new-run:wait\ncompleted:new-run:wait\n"})
            (self.out / (name + ".txt")).write_text("HARNESS77-BEGIN:new-run:" + name + "\nHARNESS77-END:new-run:" + name, encoding="cp1251")
        self.events.append({"kind": "complete", "name": "ert", "run_id": "new-run", "value": "done", "elapsed_ms": 0})
        self.evidence = {"run_id": "new-run", "elapsed_seconds": 30.05, "call_finished": False,
                         "protocol_finished": False, "events": copy.deepcopy(self.events[:3]), "windows": [dialog()]}
        self.lifecycle = {"run_id": "new-run", "private_desktop": "harness77_test", "desktop_closed": True,
            "ert_operation_timeout_seconds": 30, "wait_timeout": self.evidence, "server": {"pid": 77},
            "proxy_identity": {"tid": 88}, "timeout_phase": "ert-operation", "timeout_operation": "wait",
            "wait_call_returned_after_dismissal": True, "cleanup_verified": True,
            "modal_dismissal": {"dialog": dialog(), "requested": True, "message": "WM_COMMAND/BN_CLICKED",
                                "control_id": 2, "identity_rechecked": True}}
        self.shutdown = {"status": "blocked", "issues": ["timeout_phase: ert-operation"]}
        for name in ("ert-wait-started", "ert-wait-finished"):
            (self.out / name).write_text("new-run\n", encoding="ascii")

    def result(self):
        atomic_json(self.out / "wait-timeout.json", self.evidence)
        (self.out / "ert-events.jsonl").write_text("\n".join(json.dumps(e) for e in self.events), encoding="utf-16")
        return read_results(self.out, self.manifest, self.lifecycle, self.shutdown)

    def test_expected_timeout_never_becomes_success(self):
        result = self.result()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["timeout_verified"])
        self.assertTrue(result["expectations_met"])
        self.assertEqual(result["operations"][1]["outcome"], "timeout")

    def test_early_late_nan_or_already_returned_call_rejected(self):
        original = copy.deepcopy(self.evidence)
        for key, value in (("elapsed_seconds", 29.9), ("elapsed_seconds", 36),
                           ("elapsed_seconds", "30"), ("call_finished", True), ("protocol_finished", True),
                           ("events", self.events), ("events", []), ("windows", []), ("run_id", "old")):
            self.evidence = dict(copy.deepcopy(original), **{key: value})
            self.lifecycle["wait_timeout"] = self.evidence
            with self.subTest(key=key):
                self.assertFalse(self.result().get("timeout_verified", False))

    def test_unverified_dismissal_recovery_or_cleanup_rejected(self):
        original = copy.deepcopy(self.lifecycle)
        for key, value in (("wait_call_returned_after_dismissal", False), ("timeout_phase", "shutdown"),
                           ("timeout_operation", "check"), ("modal_dismissal", {}), ("cleanup_verified", False),
                           ("desktop_closed", False), ("ert_operation_timeout_seconds", 10)):
            self.lifecycle = dict(copy.deepcopy(original), **{key: value})
            with self.subTest(key=key):
                self.assertFalse(self.result().get("timeout_verified", False))

    def test_other_shutdown_failure_cannot_be_waived(self):
        self.shutdown["issues"].append("forced_cleanup must be false")
        self.assertFalse(self.result().get("timeout_verified", False))

    def test_short_native_call_or_inconsistent_pending_events_rejected(self):
        self.events[3]["elapsed_ms"] = 1
        self.assertFalse(self.result().get("timeout_verified", False))
        self.events[3]["elapsed_ms"] = 31000
        self.evidence["events"][2]["value"] = "foreign"
        self.assertFalse(self.result().get("timeout_verified", False))

    def test_missing_late_protocol_or_foreign_marker_blocks(self):
        (self.out / "wait.txt").unlink()
        self.assertFalse(self.result()["timeout_verified"])
        (self.out / "ert-wait-finished").write_text("old-run")
        self.assertFalse(self.result().get("timeout_verified", False))


if __name__ == "__main__":
    unittest.main()
