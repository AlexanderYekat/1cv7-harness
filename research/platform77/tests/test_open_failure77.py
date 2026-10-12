"""P05 must stay blocked and must prove the native rejection and clean exit."""
import json
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import open_failure77 as probe
from shutdown77 import PINNED


def registration(run_id, target):
    controls = [("Static", 65535, "&Название:"), ("Edit", 4361, "Информационная База #12"),
                ("Static", 65535, "&Путь:"), ("Edit", 4359, str(target) + "\\"),
                ("Button", 4360, "..."), ("Button", 1, "OK"), ("Button", 2, "Отмена")]
    return {"hwnd": 100, "pid": 77, "tid": 88, "desktop": "harness77_test", "class": "#32770",
            "text": "Регистрация Информационной Базы", "visible": True, "enabled": True,
            "owner": None, "owner_pid": 0, "owner_tid": 0,
            "children": [{"hwnd": 101 + index, "pid": 77, "tid": 88, "class": cls, "id": id,
                          "text": text, "visible": True, "enabled": True}
                         for index, (cls, id, text) in enumerate(controls)]}


def launcher():
    controls = [("Static", 65535, "&В режиме:", True), ("ComboBox", 4356, "8", True),
                ("Button", 4357, "&Монопольно", False), ("Static", 65535, "Информационные &Базы:", True),
                ("ListBox", 4355, "", True), ("Button", 1, "OK", True), ("Button", 2, "Отмена", True),
                ("Button", 4353, "&Изменить", True), ("Button", 4352, "&Добавить", True),
                ("Button", 4354, "&Удалить", True), ("Static", 4358, "C:\\unrelated-user-base\\", True),
                ("Button", 57670, "Помощь", True)]
    return {"hwnd": 200, "pid": 77, "tid": 88, "desktop": "harness77_test", "class": "#32770",
            "text": "Запуск 1С:Предприятия", "visible": True, "enabled": True,
            "owner": None, "owner_pid": 0, "owner_tid": 0,
            "children": [{"hwnd": 201 + index, "pid": 77, "tid": 88, "class": cls, "id": id,
                          "text": text, "visible": visible, "enabled": True}
                         for index, (cls, id, text, visible) in enumerate(controls)]}


class OpenFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name).resolve()
        self.manifest = probe.prepare(self.out)
        self.report = {"run_id": self.manifest["run_id"], "case": "missing-base",
            "forced_cleanup": False, "first_chance_av_observed": False, "av_dump_saved": False,
            "diagnostic_execution_modified": False, "server_exit_code": 0, "helper_exit_code": 0,
            "debugger_exit_code": 0, "cleanup_verified": True, "desktop_closed": True,
            "debugger_ready": True, "debugger_stops_at_first_chance_av": True,
            "hashes_before": PINNED, "hashes_after": PINNED,
            "temporary_com_registration": {"removed": True},
            "server": {"pid": 77}, "proxy_identity": {"tid": 88}, "private_desktop": "harness77_test",
            "base_titles_before": {"sha256": "hash"}, "base_titles_after": {"sha256": "hash"}}
        self.window = registration(self.manifest["run_id"], self.manifest["target"])
        (self.out / "base-open-windows.json").write_text(json.dumps(
            {"run_id": self.manifest["run_id"], "windows": [self.window]}), encoding="utf-8")
        self.report["registration_cancel"] = {"dialog": self.window, "requested": True,
            "message": "WM_COMMAND/BN_CLICKED", "control_id": 2, "identity_rechecked": True}
        self.launcher = launcher()
        (self.out / "base-open-after-cancel.json").write_text(json.dumps(
            {"run_id": self.manifest["run_id"], "windows": [self.launcher]}), encoding="utf-8")
        self.report["launcher_cancel"] = {"dialog": self.launcher, "requested": True,
            "message": "WM_COMMAND/BN_CLICKED", "control_id": 2, "identity_rechecked": True}
        self.events = [{"run_id": self.manifest["run_id"], "kind": kind, "name": name,
                        "value": value, "elapsed_ms": 1} for kind, name, value in (
            ("phase", "open-start", self.manifest["target"]), ("open", "return", "0"),
            ("open", "variant-type", "11"), ("open", "return-text", "Ложь"),
            ("open", "error-number", "0"), ("open", "error-description", ""),
            ("phase", "released", "ok"), ("complete", "open-failure", "done"))]
        for state in ("started", "finished"):
            (self.out / ("base-open-" + state)).write_text(self.manifest["run_id"], encoding="ascii")
        guard = patch.object(probe, "concurrency_issues", return_value=[])
        guard.start()
        self.addCleanup(guard.stop)

    def assess(self):
        (self.out / "open-events.jsonl").write_text("\n".join(map(json.dumps, self.events)), encoding="utf-16")
        return probe.assess(self.out, self.manifest, self.report)

    def test_native_false_clean_release_is_expected_but_still_blocked(self):
        result = self.assess()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "database_path_missing")
        self.assertTrue(result["expectation_met"])
        self.assertFalse(Path(self.manifest["target"]).exists())

    def test_fallback_base_success_or_arbitrary_com_error_is_not_accepted(self):
        self.events[1]["value"] = "1"
        self.assertFalse(self.assess()["expectation_met"])
        self.events[1]["value"] = "0"
        self.events[4]["value"] = "438"
        self.assertFalse(self.assess()["expectation_met"])

    def test_missing_old_partial_or_changed_client_evidence_blocks(self):
        original = copy.deepcopy(self.events)
        files = {name: (self.out / name).read_bytes() for name in ("base-open-finished", "client.vbs")}
        for action in (lambda: (self.out / "base-open-finished").unlink(),
                       lambda: self.events.pop(),
                       lambda: self.events[0].update(run_id="old"),
                       lambda: (self.out / "client.vbs").write_text("changed", encoding="utf-16")):
            action()
            self.assertFalse(self.assess()["expectation_met"])
            self.events = copy.deepcopy(original)
            for name, data in files.items():
                (self.out / name).write_bytes(data)

    def test_creating_the_missing_path_invalidates_probe(self):
        Path(self.manifest["target"]).mkdir()
        self.assertFalse(self.assess()["expectation_met"])

    def test_timeout_forced_exit_or_failed_cleanup_cannot_pass(self):
        for change in ({"timeout_phase": "open-base"}, {"forced_cleanup": True}, {"server_exit_code": 1},
                       {"server_exit_code": False}, {"cleanup_verified": False}, {"desktop_closed": False}):
            previous = self.report.copy()
            self.report.update(change)
            self.assertFalse(self.assess()["expectation_met"])
            self.report = previous

    def test_wrong_cancel_button_or_changed_user_database_list_blocks(self):
        self.report["registration_cancel"]["control_id"] = 1
        self.assertFalse(self.assess()["expectation_met"])
        self.report["registration_cancel"]["control_id"] = 2
        self.report["base_titles_after"] = {"sha256": "changed"}
        self.assertFalse(self.assess()["expectation_met"])

    def test_registration_requires_owned_exact_uuid_path_and_controls(self):
        choose = lambda windows: probe.select_registration(windows, self.manifest["run_id"], 77, 88,
                                                          "harness77_test", self.manifest["target"])
        self.assertEqual(choose([self.window]), self.window)
        for key, value in (("pid", 99), ("tid", 99), ("desktop", "Default"), ("visible", False),
                           ("enabled", False), ("text", "Other"), ("owner", 42)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                choose([dict(self.window, **{key: value})])
        for index, key, value in ((3, "text", "C:\\another-base\\"), (6, "id", 1), (6, "enabled", False),
                                   (6, "text", "OK"), (0, "pid", 99)):
            changed = copy.deepcopy(self.window)
            changed["children"][index][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                choose([changed])
        for windows in ([], [self.window, self.window]):
            with self.assertRaises(ValueError):
                choose(windows)

    def test_cancel_posts_only_id_two_after_fresh_snapshot(self):
        from test_modal_wait77 import native
        from unittest.mock import Mock
        modal = native.OwnedModal.__new__(native.OwnedModal)
        modal.server, modal.tid = {"pid": 77}, 88
        modal.desktop, modal.run_id = "harness77_test", self.manifest["run_id"]
        modal.user = Mock()
        modal.snapshot = Mock(return_value=[self.window])
        result = modal.cancel_registration([self.window], self.manifest["target"])
        self.assertEqual(result["control_id"], 2)
        modal.user.PostMessageW.assert_called_once_with(100, 0x0111, 2, 107)
        modal.user.PostMessageW.reset_mock()
        modal.snapshot.return_value = [dict(self.window, hwnd=200)]
        with self.assertRaises(RuntimeError):
            modal.cancel_registration([self.window], self.manifest["target"])
        modal.user.PostMessageW.assert_not_called()

    def test_fallback_cancel_requires_prior_owned_uuid_registration(self):
        choose = lambda windows, prior: probe.select_launcher(windows, self.manifest["run_id"], 77, 88,
                                  "harness77_test", self.manifest["target"], prior)
        prior = self.report["registration_cancel"]
        self.assertEqual(choose([self.launcher], prior), self.launcher)
        for invalid in ({}, dict(prior, control_id=1), dict(prior, requested=False),
                        dict(prior, dialog=dict(self.window, pid=99))):
            with self.assertRaises(ValueError):
                choose([self.launcher], invalid)
        for windows in ([], [self.launcher, self.launcher], [dict(self.launcher, pid=99)],
                        [dict(self.launcher, desktop="Default")]):
            with self.assertRaises(ValueError):
                choose(windows, prior)

    def test_fallback_only_cancels_and_never_accepts_selected_other_base(self):
        from test_modal_wait77 import native
        from unittest.mock import Mock
        modal = native.OwnedModal.__new__(native.OwnedModal)
        modal.server, modal.tid = {"pid": 77}, 88
        modal.desktop, modal.run_id = "harness77_test", self.manifest["run_id"]
        modal.user = Mock()
        modal.snapshot = Mock(return_value=[self.launcher])
        modal.cancel_launcher([self.launcher], self.manifest["target"], self.report["registration_cancel"])
        modal.user.PostMessageW.assert_called_once_with(200, 0x0111, 2, 207)
        self.report["launcher_cancel"]["control_id"] = 1
        self.assertFalse(self.assess()["expectation_met"])


if __name__ == "__main__":
    unittest.main()
