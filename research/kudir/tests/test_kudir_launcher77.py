"""KUDiR adapter of the stage-4 launcher (task 006): portable, no 1C is started."""

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kudir_launcher77 as kudir  # noqa: E402

launcher = kudir.launcher
WINDOW = {"start": "2026-01-01", "end": "2026-10-10"}


def row(command, diagnostics=()):
    return {"name": command, "status": "blocked", "value": None, "diagnostics": list(diagnostics)}


def judge(command, lines, diagnostics=()):
    item = row(command, diagnostics)
    issue = kudir.KudirAdapter().operation(command, lines, "\n".join(lines), item)
    return item, issue


class CommandTests(unittest.TestCase):
    def test_check_first_then_test_commands_once(self):
        adapter = kudir.KudirAdapter()
        self.assertEqual(adapter.commands(WINDOW, ["full", "check", "full_ledger62", "full"]),
                         ["check", "full", "full_ledger62"])
        self.assertEqual(adapter.commands({}, []), ["check"])

    def test_unknown_command_and_bad_window_are_refused(self):
        adapter = kudir.KudirAdapter()
        for requested, parameters in ((["full_oops"], WINDOW), (["execute"], WINDOW),
                                      (["full"], {}), (["full"], {"start": "2026-13-01", "end": "2026-10-10"}),
                                      (["full"], {"start": "2026-10-11", "end": "2026-10-10"})):
            with self.subTest(requested=requested, parameters=parameters), self.assertRaises(ValueError):
                adapter.commands(parameters, requested)

    def test_controller_carries_the_window_and_the_client_signature(self):
        source = kudir.KudirAdapter().controller(WINDOW)
        self.assertIn("Функция Harness77Ert(Путь, Команда, Протокол, Метка) Экспорт", source)
        self.assertIn('ДобавитьЗначение("KUDIR4-HEADLESS")', source)
        self.assertIn("Дата(2026, 1, 1)", source)
        self.assertIn("Дата(2026, 10, 10)", source)
        self.assertNotIn("__", source)


class ResponseTests(unittest.TestCase):
    SELECTED = ["selected:C:/run/native/Тестовые обработки/Обработка проверки.ert", "open-return:0"]

    def test_check_passes_with_the_module_version(self):
        item, issue = judge("check", self.SELECTED + ["loaded:2026.10.15-01"])
        self.assertEqual((item["status"], item["value"], issue), ("passed", "2026.10.15-01", None))

    def test_complete_export_passes(self):
        item, _ = judge("full", self.SELECTED + ["loaded:2026.10.15-01", "catalog:C:\\r\\KUDIR4_1",
                                                 "status:COMPLETE"])
        self.assertEqual((item["status"], item["value"]), ("passed", "COMPLETE"))
        self.assertEqual(item["packages"], [{"catalog": "C:\\r\\KUDIR4_1", "status": "COMPLETE"}])

    def test_failed_step_and_incomplete_series_fail(self):
        for command, lines, value in (
                ("full_ledger62", ["catalog:a", "status:FAILED"], "FAILED"),
                ("full_ok_ok", ["catalog:a", "status:COMPLETE"], "COMPLETE"),  # second export missing
                ("full", ["error:unknown step x"], None)):
            with self.subTest(command=command):
                item, issue = judge(command, self.SELECTED + ["loaded:v"] + lines)
                self.assertEqual((item["status"], item["value"], issue), ("failed", value, None))

    def test_compile_errors_fail_and_silence_blocks(self):
        item, issue = judge("check", self.SELECTED, diagnostics=[{"line": 5, "message": "Ошибка"}])
        self.assertEqual((item["status"], issue), ("failed", None))
        item, issue = judge("check", self.SELECTED)
        self.assertEqual(item["status"], "blocked")
        self.assertIn("no KUDiR loaded marker", issue)

    def test_runtime_error_after_loading_fails_and_visible_form_blocks(self):
        item, _ = judge("full", self.SELECTED + ["loaded:v", "open-error:Деление на 0"])
        self.assertEqual(item["status"], "failed")
        item, issue = judge("full", self.SELECTED + ["loaded:v", "unexpected-visible-form"])
        self.assertEqual(item["status"], "blocked")
        self.assertIn("visible", issue)


class ResultFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kudir-adapter-")
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name).resolve()
        self.environment = kudir.KudirAdapter().prepare(self.run, WINDOW)
        self.exchange = self.run / "kudir" / "exchange"

    def package(self, name, status=None, files=("ledger62.csv",)):
        directory = self.exchange / name
        directory.mkdir()
        for file in files:
            (directory / file).write_bytes(b"data " + file.encode())
        if status:
            (directory / "export_status.csv").write_bytes(
                f"key;value\r\nrun_id;{name}\r\nschema_version;4\r\nstatus;{status}\r\n".encode("cp1251"))
        return directory

    def test_environment_points_the_export_into_the_run(self):
        self.assertEqual(self.environment, {"KUDIR_PROTO_ROOT": str(self.run / "kudir")})
        self.assertTrue(self.exchange.is_dir())

    def test_complete_failed_and_unreported_packages(self):
        done = self.package("KUDIR4_A", "COMPLETE")
        failed = self.package("KUDIR4_B", "FAILED")
        self.package("KUDIR4_C")  # cancelled mid-export: never reported, no status file
        operations = [{"name": "full", "packages": [{"catalog": str(done), "status": "COMPLETE"}]},
                      {"name": "full_ledger62", "packages": [{"catalog": str(failed) + "\\", "status": "FAILED"}]}]
        files = kudir.KudirAdapter().result_files(self.run, operations)
        by_package = {}
        for spec in files:
            by_package.setdefault(spec["package"], []).append(spec)
        self.assertEqual({k: {s["complete"] for s in v} for k, v in by_package.items()},
                         {"KUDIR4_A": {True}, "KUDIR4_B": {False}, "KUDIR4_C": {False}})
        self.assertEqual({s["operation"] for s in by_package["KUDIR4_C"]}, {None})
        first = by_package["KUDIR4_A"][0]
        self.assertEqual(first["path"], "kudir/exchange/KUDIR4_A/export_status.csv")
        self.assertEqual(first["sha256"], hashlib.sha256((done / "export_status.csv").read_bytes()).hexdigest())

    def test_status_file_must_agree_with_the_module(self):
        directory = self.package("KUDIR4_A", "WRITING")
        files = kudir.KudirAdapter().result_files(
            self.run, [{"name": "full", "packages": [{"catalog": str(directory), "status": "COMPLETE"}]}])
        self.assertEqual({s["complete"] for s in files}, {False})

    def test_package_outside_the_run_is_refused(self):
        with self.assertRaises(ValueError):
            kudir.KudirAdapter().result_files(
                self.run, [{"name": "full", "packages": [{"catalog": str(self.run.parent), "status": "COMPLETE"}]}])


class BaseCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kudir-base-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.base, self.out = root / "копия базы", root / "out"
        self.base.mkdir()
        for name in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll", "1SJOURN.DBF"):
            (self.base / name).write_bytes(name.encode())
        self.exe, self.helper, self.cdb = root / "1cv7l.exe", root / "helper.dll", root / "cdb.exe"
        for path in (self.exe, self.helper):
            path.write_bytes(path.name.encode())
        self.cdb.write_bytes(b"MZ" + bytes(0x3a) + (0x40).to_bytes(4, "little") + b"PE\0\0\x4c\x01")

    def preflight(self):
        pinned = {"exe": "1cv7l.exe", "helper": "helper.dll", "1Cv7.MD": "1Cv7.MD", "1Cv7.DD": "1Cv7.DD",
                  "1CPP.dll": "1CPP.dll", "FormEx.dll": "FormEx.dll"}
        with patch.dict("shutdown77.PINNED", pinned, clear=True), \
                patch.object(launcher, "sha256", side_effect=lambda p: Path(p).read_bytes().decode()):
            kudir.KudirAdapter().preflight(self.base, self.exe, self.cdb, self.helper, self.out)

    def test_copy_with_pinned_files_and_source_id_is_accepted(self):
        (self.base / "kudir_source_id.txt").write_text("ctoksm-buh", encoding="ascii")
        self.preflight()

    def test_copy_without_source_id_or_with_other_configuration_is_refused(self):
        with self.assertRaises(ValueError):
            self.preflight()
        (self.base / "kudir_source_id.txt").write_text("ctoksm-buh", encoding="ascii")
        (self.base / "1Cv7.MD").write_bytes(b"other configuration")
        with self.assertRaisesRegex(ValueError, "1Cv7.MD"):
            self.preflight()


class DefaultAdapterTests(unittest.TestCase):
    """The stage-4 contract is unchanged by the adapter refactoring."""

    def test_stage4_markers(self):
        adapter = launcher.Harness77Adapter()
        lines = ["selected:x", "loaded:harness77", "value:42", "completed:harness77"]
        item = row("execute")
        self.assertIsNone(adapter.operation("execute", lines, "\n".join(lines), item))
        self.assertEqual((item["status"], item["value"]), ("passed", "42"))
        item = row("execute")
        self.assertIn("no cooperation markers", adapter.operation("execute", ["selected:x"], "selected:x", item))
        self.assertEqual(adapter.commands({"start": "x"}, ["full"]), ["check", "execute"])
        self.assertEqual(adapter.platform_status([{"status": "failed"}]), "failed")

    def test_reindexing_on_open_does_not_eat_the_report_deadline(self):
        # Opening (with a possible hour-long reindex) is covered by total, not by each command.
        deadlines = {"open_timeout_s": 3600, "calculation_timeout_s": 3600, "cancel_timeout_s": 15,
                     "shutdown_timeout_s": 30, "total_timeout_s": 7300}
        self.assertEqual(launcher.session_limits(deadlines), (3600, 7300, 7330))

    def test_core_phases_map_to_section_8_5(self):
        self.assertEqual(launcher.PHASES["ert-operation"], "calculation")
        self.assertEqual(launcher.PHASES["session"], "total")
        self.assertEqual(launcher.PHASES["debugger-ready"], "open")


if __name__ == "__main__":
    unittest.main()
