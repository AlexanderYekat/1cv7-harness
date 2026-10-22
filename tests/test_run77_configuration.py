"""Task 021: a run with changed modules of 1Cv7.MD on a copy of the stand base.

The simulation stand drives the same cycle without 1C: the configuration is built, the
changed modules are analysed in its context, the base is copied with the built 1Cv7.MD
and removed afterwards, and the stand base stays as it was. The native launcher is a
fake one here; the real 1C is the native acceptance.
"""

import hashlib
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from harness77 import basecopy77
from harness77 import md77

from stage4_fixtures import base_scenario, run, windows_only, write_project, write_sim_stand
from test_md77 import MODULES as MD_MODULES, md_bytes

GLOBAL = "Перем глВерсия Экспорт;\r\n\r\nФункция Харнесс77Конфигурация() Экспорт\r\n    Возврат 42;\r\nКонецФункции\r\n\r\nглВерсия = 1;\r\n"
ERT_MODULE = "Функция Проверка() Экспорт\n    Возврат Харнесс77Конфигурация() + глВерсия;\nКонецФункции\n"
LOG_LINE = '20261022;10:00:01;ВВВ;E;Grbgs;GrbgSyntaxErr;5;"Х = ; : {(3)}: Ожидается выражение";;\r\n'


def fake_base(folder):
    """A base with a configuration, a users table, a log, a user directory and a big folder to leave out."""
    folder.mkdir(parents=True)
    (folder / "1Cv7.MD").write_bytes(md_bytes())
    (folder / "1Cv7.DD").write_bytes(b"DD")
    (folder / "1SUSERS.DBF").write_bytes(b"users")
    (folder / "SYSLOG").mkdir()
    (folder / "SYSLOG" / "1cv7.mlg").write_bytes("20261021;09:00:00;ВВВ;E;Sys;OpenSession;0;;;\r\n".encode("cp1251"))
    (folder / "Вера").mkdir()
    (folder / "Вера" / "1Cv7.CFG").write_bytes(b"saved values")
    (folder / "ExtForms").mkdir()
    (folder / "ExtForms" / "big.ert").write_bytes(b"x" * 1000)
    return folder


class BaseCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h77-copy-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = fake_base(self.root / "base-for-test")
        self.copy = self.root / "harness77-copy"
        self.built = self.root / "built.MD"
        self.built.write_bytes(b"built configuration")

    def test_copy_leaves_out_named_folders_and_carries_the_built_configuration(self):
        evidence, before = basecopy77.copy(self.base, self.copy, ("extforms", "Нет"), self.built, "run-1")
        self.assertEqual((self.copy / "1Cv7.MD").read_bytes(), b"built configuration")
        self.assertEqual((self.copy / "Вера" / "1Cv7.CFG").read_bytes(), b"saved values")
        self.assertFalse((self.copy / "ExtForms").exists())
        marker = json.loads((self.copy / basecopy77.MARKER).read_text(encoding="utf-8"))
        self.assertEqual((marker["run_id"], marker["complete"]), ("run-1", True))
        self.assertEqual((evidence["excluded"], evidence["excluded_absent"]), (["ExtForms"], ["Нет"]))
        self.assertEqual(evidence["md_sha256"], hashlib.sha256(b"built configuration").hexdigest())
        self.assertEqual(evidence["source_md_sha256"], hashlib.sha256((self.base / "1Cv7.MD").read_bytes()).hexdigest())
        self.assertEqual((evidence["files"], evidence["previous_run_id"]), (5, None))
        self.assertEqual(basecopy77.unchanged(self.base, before), {"unchanged": True, "differences": [], "count": 0})
        self.assertEqual(basecopy77.remove(self.copy), {"removed": True, "error": None, "errors": 0})
        self.assertFalse(self.copy.exists())

    def test_the_next_run_replaces_a_marked_copy_only(self):
        basecopy77.copy(self.base, self.copy, run_id="run-1")
        (self.copy / "left.txt").write_bytes(b"left by run-1")
        evidence, _ = basecopy77.copy(self.base, self.copy, run_id="run-2")
        self.assertEqual(evidence["previous_run_id"], "run-1")
        self.assertFalse((self.copy / "left.txt").exists())
        (self.copy / basecopy77.MARKER).unlink()
        with self.assertRaisesRegex(basecopy77.BaseCopyError, "без метки"):
            basecopy77.copy(self.base, self.copy, run_id="run-3")
        self.assertEqual(basecopy77.remove(self.copy)["removed"], False)
        self.assertTrue((self.copy / "1Cv7.MD").exists())

    def test_the_lock_keeps_a_second_run_away(self):
        self.assertEqual(basecopy77.acquire(self.copy, "run-1"), {"lock": "harness77-copy.lock", "stale_run_id": None})
        with self.assertRaisesRegex(basecopy77.BaseCopyError, "занят прогоном run-1"):
            basecopy77.acquire(self.copy, "run-2")
        self.assertFalse(basecopy77.release(self.copy, "run-2"))
        self.assertTrue(basecopy77.release(self.copy, "run-1"))
        # A lock whose process is gone is taken over.
        basecopy77.lock_path(self.copy).write_text(json.dumps({"run_id": "dead", "pid": 0}), encoding="utf-8")
        self.assertEqual(basecopy77.acquire(self.copy, "run-3")["stale_run_id"], "dead")

    def test_a_base_open_in_1c_is_not_copied(self):
        with mock.patch.object(Path, "open", side_effect=PermissionError("locked")):
            self.assertEqual(basecopy77.open_in_1c(self.base), "1SUSERS.DBF")
        with mock.patch.object(basecopy77, "open_in_1c", return_value="1SUSERS.DBF"):
            with self.assertRaisesRegex(basecopy77.BaseCopyError, "открыта в 1С"):
                basecopy77.copy(self.base, self.copy)
        self.assertFalse(self.copy.exists())

    def test_nested_paths_are_refused(self):
        for target in (self.base / "copy", self.base):
            with self.subTest(target=target.name), self.assertRaisesRegex(basecopy77.BaseCopyError, "вкладываться"):
                basecopy77.copy(self.base, target)

    def test_a_changed_source_is_reported(self):
        _, before = basecopy77.copy(self.base, self.copy)
        (self.base / "1SUSERS.DBF").write_bytes(b"users, changed")
        result = basecopy77.unchanged(self.base, before)
        self.assertEqual((result["unchanged"], result["differences"]), (False, ["1SUSERS.DBF"]))

    def test_the_session_part_of_the_log(self):
        basecopy77.copy(self.base, self.copy)
        offset = basecopy77.log_size(self.copy)
        with (self.copy / basecopy77.LOG).open("ab") as stream:
            stream.write(LOG_LINE.encode("cp1251"))
        log = basecopy77.session_log(self.copy, offset, self.root / "session.txt")
        self.assertEqual((log["count"], log["offset"]), (1, offset))
        self.assertEqual(log["entries"][0], {"date": "20261022", "time": "10:00:01", "user": "ВВВ", "mode": "E",
                                             "category": "Grbgs", "event": "GrbgSyntaxErr",
                                             "text": "Х = ; : {(3)}: Ожидается выражение"})
        self.assertEqual((self.root / "session.txt").read_bytes(), LOG_LINE.encode("cp1251"))


class ConfigurationRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h77-cfg-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = fake_base(self.root / "base-for-test")
        self.modules = self.root / "configuration"
        md77.extract(self.base / "1Cv7.MD", self.modules)
        (self.modules / "ГлобальныйМодуль.1s").write_text(GLOBAL, encoding="utf-8", newline="")

    def project(self, keep_copy=False, modules=None):
        path = write_project(self.root / "project", source_text=ERT_MODULE)
        text = path.read_text(encoding="utf-8")
        text += (f'[configuration]\nmodules = "{(modules or self.modules).as_posix()}"\n'
                 f"keep_copy = {'true' if keep_copy else 'false'}\n")
        path.write_text(text, encoding="utf-8")
        return path

    def stand(self, pinned=None, copy_path=True):
        path = write_sim_stand(self.root, base_scenario(), base=self.base.as_posix())
        text = path.read_text(encoding="utf-8") + 'copy_exclude = ["ExtForms"]\n'
        if copy_path:
            text += f'copy_path = "{(self.root / "harness77-copy").as_posix()}"\n'
        if pinned:
            text += "[stand.pinned]\n" + "".join(f'"{k}" = "{v}"\n' for k, v in pinned.items())
        path.write_text(text, encoding="utf-8")
        return path

    def stage(self, report, name):
        return next(s for s in report["stages"] if s["stage"] == name)

    def test_changed_global_module_runs_on_a_removed_copy(self):
        before = basecopy77.listing(self.base)
        report = run(self.project(), self.stand(), self.root / "runs")
        self.assertEqual((report["status"], report["exit_code"]), ("passed", 0))
        self.assertEqual([s["stage"] for s in report["stages"]],
                         ["configuration", "static", "build", "platform_check", "tests"])
        configuration = self.stage(report, "configuration")
        self.assertEqual([row["file"] for row in configuration["changed"]], ["ГлобальныйМодуль.1s"])
        self.assertEqual(configuration["template_sha256"], hashlib.sha256((self.base / "1Cv7.MD").read_bytes()).hexdigest())
        self.assertEqual(report["configuration"]["sha256"], configuration["md_sha256"])
        self.assertEqual(report["platform"]["base_usage"], "copy-per-run")
        # The ERT's module calls the new global function and reads the global variable: no unknown names.
        static = self.stage(report, "static")
        self.assertEqual(static["configuration_modules"], ["TypedText/ModuleText_Number1/MD Programm text"])
        self.assertFalse([d for d in static["diagnostics"] if "Харнесс77Конфигурация" in d["message"]
                          or "глВерсия" in d["message"]])
        copy = self.stage(report, "platform_check")["base_copy"]
        self.assertEqual((copy["md_sha256"], copy["excluded"], copy["kept"]),
                         (configuration["md_sha256"], ["ExtForms"], False))
        self.assertEqual((copy["removal"]["removed"], copy["source_check"]["unchanged"]), (True, True))
        self.assertEqual(copy["session_log"]["count"], 0)
        self.assertEqual((copy["lock"]["released"], copy["path"]["name"]), (True, "harness77-copy"))
        run_dir = Path(report["run_dir"])
        self.assertFalse((self.root / "harness77-copy").exists())
        self.assertFalse((self.root / "harness77-copy.lock").exists())
        self.assertTrue((run_dir / "configuration" / "1Cv7.MD").is_file())
        self.assertTrue((run_dir / "base-session-log.txt").is_file())
        self.assertEqual(self.stage(report, "platform_check")["platform_checked"], False)
        self.assertEqual(basecopy77.listing(self.base), before)

    def test_keep_copy(self):
        report = run(self.project(keep_copy=True), self.stand(), self.root / "runs")
        copy = self.stage(report, "platform_check")["base_copy"]
        self.assertEqual((copy["kept"], copy["removal"]), (True, None))
        self.assertTrue((self.root / "harness77-copy" / "Вера" / "1Cv7.CFG").is_file())

    def test_changed_modules_only_are_analysed(self):
        # The document module gets an error; the unchanged form reads an undeclared name and stays silent.
        (self.modules / "Документ" / "Выписка" / "МодульДокумента.1s").write_text(
            "Процедура ОбработкаПроведения()\r\n    Если 1 = 1 Тогда\r\nКонецПроцедуры\r\n", encoding="utf-8", newline="")
        report = run(self.project(), self.stand(), self.root / "runs")
        static = self.stage(report, "static")
        self.assertEqual(static["status"], "failed")
        modules = {d["module"] for d in static["diagnostics"]}
        self.assertEqual(modules, {"TypedText/Transact_Number238/MD Programm text"})

    def test_an_unknown_module_file_blocks_before_1c(self):
        (self.modules / "Документ" / "Нет").mkdir()
        (self.modules / "Документ" / "Нет" / "Форма.1s").write_text("// x", encoding="utf-8")
        report = run(self.project(), self.stand(), self.root / "runs")
        self.assertEqual((report["status"], report["exit_code"]), ("blocked", 2))
        self.assertEqual(self.stage(report, "configuration")["status"], "blocked")
        self.assertIn("configuration_error", report["reason"])
        self.assertEqual(self.stage(report, "platform_check")["reason"], "no configuration was built")
        self.assertFalse((self.root / "harness77-copy").exists())

    def test_the_stand_base_must_carry_its_pinned_configuration(self):
        report = run(self.project(), self.stand(pinned={"1Cv7.MD": "0" * 64}), self.root / "runs")
        self.assertEqual(self.stage(report, "configuration")["status"], "blocked")
        self.assertIn("закреплённым хешем", report["reason"])

    def test_a_compile_error_of_a_changed_module_fails_the_platform_check(self):
        # 1C compiles a document module at posting: Провести returns 0, the ERT's test passes,
        # the copy's event log tells (task 021, m-transact2-error).
        (self.modules / "Документ" / "Выписка" / "МодульДокумента.1s").write_text(
            "Процедура ОбработкаПроведения()\r\n    глВерсия = 43 +;\r\nКонецПроцедуры\r\n", encoding="utf-8",
            newline="")
        log = {"count": 2, "entries": [
            {"event": "GrbgSyntaxErr", "time": "07:19:34",
             "text": "глВерсия = 43 +<<?>>; : {Документ.Выписка.Модуль Документа(2)}: Ошибка в выражении"},
            {"event": "GrbgSyntaxErr", "time": "07:19:35",
             "text": "Х = 1 +<<?>>; : {Документ.Прочий.Модуль Документа(5)}: Ошибка в выражении"}]}
        with mock.patch.object(basecopy77, "session_log", return_value=log):
            report = run(self.project(), self.stand(), self.root / "runs")
        platform = self.stage(report, "platform_check")
        self.assertEqual((report["status"], report["exit_code"], platform["status"]), ("failed", 1, "failed"))
        self.assertEqual(platform["reason"], "configuration_compilation_failed: "
                                             "Документ/Выписка/МодульДокумента.1s:2: Ошибка в выражении")
        own, other = platform["configuration_diagnostics"]
        self.assertEqual((own["file"], own["line"], own["column"], own["source_line"], own["changed"]),
                         ("Документ/Выписка/МодульДокумента.1s", 2, 20, "глВерсия = 43 +;", True))
        self.assertEqual((other["file"], other["changed"]), ("Документ/Прочий/МодульДокумента.1s", False))
        self.assertEqual(self.stage(report, "tests")["status"], "skipped")

    def test_only_new_remarks_of_a_changed_module(self):
        # The template's form already calls an unknown function; the change adds another.
        before = "Процедура ПриОткрытии()\r\n    Старая77();\r\nКонецПроцедуры\r\n"
        base = fake_base(self.root / "other-base")
        (base / "1Cv7.MD").write_bytes(md_bytes(modules=dict(MD_MODULES, **{
            "Document/Document_Number238/WorkBook": before})))
        (self.modules / "Документ" / "Выписка" / "Форма.1s").write_text(
            "Процедура ПриОткрытии()\r\n    Новая77();\r\n    Старая77();\r\nКонецПроцедуры\r\n", encoding="utf-8",
            newline="")
        (self.modules / md77.INDEX).unlink()
        stand = self.stand()
        stand.write_text(stand.read_text(encoding="utf-8").replace(self.base.as_posix(), base.as_posix()),
                         encoding="utf-8")
        report = run(self.project(), stand, self.root / "runs")
        static = self.stage(report, "static")
        remarks = [d["message"] for d in static["diagnostics"] if d["module"].startswith("Document/")]
        self.assertEqual(len(remarks), 1)
        self.assertIn("Новая77", remarks[0])
        self.assertEqual(static["configuration_preexisting"], 1)

    def test_a_stand_without_a_copy_path_blocks_the_platform_stage(self):
        report = run(self.project(), self.stand(copy_path=False), self.root / "runs")
        self.assertIn("copy_path", self.stage(report, "platform_check")["reason"])
        self.assertEqual(self.stage(report, "tests")["status"], "skipped")

    def test_a_base_open_in_1c_blocks_the_platform_stage(self):
        with mock.patch.object(basecopy77, "open_in_1c", return_value="1SUSERS.DBF"):
            report = run(self.project(), self.stand(), self.root / "runs")
        platform = self.stage(report, "platform_check")
        self.assertEqual((report["status"], platform["status"]), ("blocked", "blocked"))
        self.assertIn("base_copy_error", platform["reason"])
        self.assertEqual(self.stage(report, "tests")["status"], "skipped")


FAKE_LAUNCHER = textwrap.dedent('''
    import argparse, hashlib, json
    from pathlib import Path
    parser = argparse.ArgumentParser()
    for name in ("--run-dir", "--ert", "--ert-sha256", "--run-id", "--base", "--user", "--exe", "--result",
                 "--deadlines-json", "--configuration-sha256"):
        parser.add_argument(name)
    args, _ = parser.parse_known_args()
    md = hashlib.sha256((Path(args.base) / "1Cv7.MD").read_bytes()).hexdigest()
    marker = json.loads((Path(args.base) / "harness77-copy.json").read_text(encoding="utf-8"))
    seen = {"base": str(Path(args.base).resolve()), "configuration": args.configuration_sha256, "md": md,
            "marker_run_id": marker["run_id"]}
    (Path(args.run_dir) / "seen.json").write_text(json.dumps(seen), encoding="utf-8")
    out = {"run_id": args.run_id, "ert_sha256": args.ert_sha256, "platform_checked": True, "status": "passed",
           "load": {"status": "passed", "diagnostics": []},
           "operations": [{"name": "control-42", "status": "passed", "value": "42"}],
           "shutdown": {"status": "ok", "cleanup_verified": True, "server_exit_code": 0, "others_preserved": True},
           "base_list": {"before": {"sha256": "a"}, "after": {"sha256": "a"}, "unchanged": True}}
    Path(args.result).write_text(json.dumps(out), encoding="utf-8")
''')


class NativeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h77-ncfg-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = fake_base(self.root / "base-for-test")
        self.modules = self.root / "configuration"
        self.modules.mkdir()
        (self.modules / "ГлобальныйМодуль.1s").write_text(GLOBAL, encoding="utf-8", newline="")

    @windows_only
    def test_the_launcher_gets_the_copy_and_the_built_configuration(self):
        launcher = self.root / "launcher.py"
        launcher.write_text(FAKE_LAUNCHER, encoding="utf-8")
        source_md = hashlib.sha256((self.base / "1Cv7.MD").read_bytes()).hexdigest()
        stand = self.root / "stand.toml"
        stand.write_text("\n".join([
            "schema_version = 1", "[stand]", 'name = "native"', 'backend = "native"',
            f'launcher = "{launcher.as_posix()}"', "[stand.paths]", f'exe = "{Path(sys.executable).as_posix()}"',
            "[stand.base]", f'path = "{self.base.as_posix()}"', 'user = "ВВВ"', 'copy_exclude = ["ExtForms"]',
            f'copy_path = "{(self.root / "harness77-copy").as_posix()}"',
            "[stand.pinned]", f'"1Cv7.MD" = "{source_md}"']) + "\n", encoding="utf-8")
        project = write_project(self.root / "project", source_text=ERT_MODULE)
        project.write_text(project.read_text(encoding="utf-8")
                           + f'[configuration]\nmodules = "{self.modules.as_posix()}"\n', encoding="utf-8")
        from harness77.deadlines77 import Clock
        report = run(project, stand, self.root / "runs", clock=Clock())
        self.assertEqual((report["status"], report["platform_checked"]), ("passed", True))
        run_dir = Path(report["run_dir"])
        seen = json.loads((run_dir / "seen.json").read_text(encoding="utf-8"))
        built = next(s for s in report["stages"] if s["stage"] == "configuration")["md_sha256"]
        self.assertEqual(seen, {"base": str((self.root / "harness77-copy").resolve()), "configuration": built,
                                "md": built, "marker_run_id": report["run_id"]})
        platform = next(s for s in report["stages"] if s["stage"] == "platform_check")
        self.assertTrue(platform["base_list"]["unchanged"])
        self.assertEqual(report["platform"]["base"], "base-for-test")
        self.assertTrue(platform["base_copy"]["removal"]["removed"])


if __name__ == "__main__":
    unittest.main()
