"""Task 018: names of configuration objects in module code (L7712, L7713) against the base's 1Cv7.MD.

Expected outcomes follow the native probes on 1C 7.7.027 (docs/tasks/018-metadata-names-acceptance.md):
every missing name loads and fails when the line runs, or quietly leaves a type without its kind.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness77 import ert_module as ert
from harness77 import lint77
from harness77 import metadata77

from stage4_fixtures import run, write_project, write_sim_stand, base_scenario
from test_ert_dialog import base_container
from test_metadata77 import make_md, renamed

# Every class module code names, in the layout of base-for-test and Торговля+Склад 9.2.
FULL_TEXT = (
    '{\r\n{"MainDataContDef","48514","10011","7120"},\r\n'
    '{"TaskItem",\r\n{"1","Тестовая конфигурация","7.70.431","","","1","493","0","0","493"}},\r\n'
    '{"Consts",\r\n{"15","АдресОрганизации","","","S","240","0","0","0","0","0"}},\r\n'
    '{"SbCnts",\r\n{"133","Контрагенты","","","0",\r\n{"Params"},\r\n{"Form",\r\n{"70","ФормаСписка","",""}}},\r\n'
    '{"208","Сотрудники","","Сотрудники","0"}},\r\n'
    '{"Registers",\r\n{"639","ОстаткиТоваров","","","0"," ","0","0",\r\n{"Props"},\r\n{"Figures"}}},\r\n'
    '{"Documents",\r\n{"238","Выписка","","","8",\r\n{"Head Fields"}}},\r\n'
    '{"Journalisters",\r\n{"481","Банк","","","-1","0","479","479","0",\r\n{"Form"}}},\r\n'
    '{"EnumList",\r\n{"21439","Пол","","",\r\n{"EnumVal",\r\n{"21437","Мужской","",""},\r\n'
    '{"21438","Женский","",""}}},\r\n{"21440","Пустое","",""}},\r\n'
    '{"ReportList",\r\n{"370","АнализСчета","",""}},\r\n'
    '{"CalcVars",\r\n{"25804","ВводАдреса","",""}},\r\n'
    '{"Buh",\r\n{"2","","","",\r\n{"AccParams"},\r\n{"Plans",\r\n{"809","Основной","","","###.##.#","###.##.#",\r\n'
    '{"Accounts"}}},\r\n{"SbKind",\r\n{"518","Договоры","","","B","0","0","133"}}}}}'
)


def metadata(text=FULL_TEXT):
    return lint77.base_metadata(metadata77.Metadata(make_md(text)))


def make_md_with_module(module, text=FULL_TEXT):
    """A 1Cv7.MD: one module stream and the Main MetaData Stream."""
    compound = ert.CompoundFile(renamed(base_container(), 2, metadata77.STREAM))
    return compound.rebuild({1: ert.compress_module(module.encode("cp1251")), 2: ert.encode_dialog(text)})


def analyze(text, *, md=True, strict=False):
    source = lint77.Source("test.1s", "", text, metadata=metadata() if md else None)
    return lint77.analyze([source], strict=strict)


def found(text, rule, **kwargs):
    return [(d["line"], d["column"], d["severity"]) for d in analyze(text, **kwargs)["diagnostics"]
            if d["rule"] == rule]


def messages(text, rule):
    return [d["message"] for d in analyze(text)["diagnostics"] if d["rule"] == rule]


class MetadataObjectTests(unittest.TestCase):
    """metadata77 reads every class by name; the form build does not depend on them."""

    def test_names_of_every_class(self):
        objects = metadata().objects()
        self.assertEqual({name: sorted(names.values()) for name, names in objects.items()}, {
            "Константа": ["АдресОрганизации"], "Справочник": ["Контрагенты", "Сотрудники"],
            "Документ": ["Выписка"], "Перечисление": ["Пол", "Пустое"], "Регистр": ["ОстаткиТоваров"],
            "Отчет": ["АнализСчета"], "Обработка": ["ВводАдреса"], "Журнал": ["Банк"],
            "ПланСчетов": ["Основной"], "ВидСубконто": ["Договоры"]})
        self.assertEqual(objects["Справочник"]["контрагенты"], "Контрагенты")

    def test_values_of_enumerations(self):
        md = metadata()
        self.assertEqual(md.enum_values("ПОЛ"), {"мужской": "Мужской", "женский": "Женский"})
        self.assertEqual(md.enum_values("Пустое"), {})
        self.assertIsNone(md.enum_values("Нет"))

    def test_sections_absent_from_a_configuration_are_empty(self):
        from test_metadata77 import EMPTY_TEXT
        objects = metadata(EMPTY_TEXT).objects()
        self.assertEqual({name: len(names) for name, names in objects.items()}, dict.fromkeys(objects, 0))

    def test_unknown_record_refuses_the_names_but_not_the_form_metadata(self):
        broken = FULL_TEXT.replace('{"15","АдресОрганизации"', '{"x","АдресОрганизации"')
        md = metadata77.Metadata(make_md(broken))
        self.assertEqual(md.number("B", "Контрагенты"), 133)
        with self.assertRaisesRegex(ert.ErtError, "неизвестная запись в разделе Consts"):
            md.objects()
        with self.assertRaisesRegex(ert.ErtError, "неизвестная запись в разделе Consts"):
            lint77.base_metadata(md)

    def test_repeated_names_are_refused(self):
        cases = {"Consts": FULL_TEXT.replace('"0","0","0","0","0"}},', '"0","0","0","0","0"},\r\n'
                                             '{"16","адресорганизации","",""}},'),
                 "EnumVal Пол": FULL_TEXT.replace('"21438","Женский"', '"21438","мужской"')}
        for section, text in cases.items():
            with self.subTest(section=section), \
                    self.assertRaisesRegex(ert.ErtError, f"в разделе {section} пусто или повторяется"):
                metadata(text)


class GlobalAttributeTests(unittest.TestCase):
    """L7712: Константа, Перечисление, ВидыСубконто, ПланыСчетов — loaded, failing when the line runs."""

    def test_missing_objects_are_reported_at_the_name(self):
        cases = {"Х = Перечисление.Нет;": 18, "Х = Перечисление.Пол.Средний;": 22, "Х = Константа.Нет;": 15,
                 "Константа.Нет = 1;": 11, "Х = ВидыСубконто.Нет;": 18, "Х = ПланыСчетов.Нет;": 17,
                 "Если Перечисление.Пол.Средний = 1 Тогда КонецЕсли;": 23}
        for text, column in cases.items():
            with self.subTest(text=text):
                self.assertEqual(found(text, "L7712"), [(1, column, "warning")])

    def test_messages_name_the_object_and_what_1c_does(self):
        message, = messages("Х = Перечисление.Пол.Средний;", "L7712")
        self.assertIn("у перечисления Пол", message)
        self.assertIn("нет значения Средний", message)
        self.assertIn("Поле агрегатного объекта не обнаружено (Средний)", message)
        self.assertIn("Тестовая конфигурация", message)
        message, = messages("Х = Константа.Нет;", "L7712")
        self.assertIn("нет объекта Константа.Нет", message)

    def test_existing_names_methods_and_other_chains_are_silent(self):
        for text in ("Х = Перечисление.Пол.Мужской;", "Х = перечисление.ПОЛ.женский;",
                     "Х = Перечисление.Пол.ЗначениеПоНомеру(1);", "Х = Перечисление.ПолучитьАтрибут(\"Нет\");",
                     "Х = Перечисление.Пол.Мужской.Идентификатор();", "Х = Перечисление.Пол;",
                     "Х = Константа.АдресОрганизации;", "Х = Константа.АдресОрганизации.Получить(Д);",
                     "Х = Константа.ПолучитьАтрибут(\"Нет\");", "Константа.УстановитьАтрибут(\"Нет\", 1);",
                     "Х = ВидыСубконто.Договоры;", "Х = ВидыСубконто.КоличествоЗначений();",
                     "Х = ПланыСчетов.Основной;", "Х = Док.Константа.Нет;", "Х = Док.Перечисление.Нет.Да;",
                     "// Константа.Нет", "Х = \"Константа.Нет\";", "Х = Перечисление;"):
            with self.subTest(text=text):
                self.assertEqual(found(text, "L7712"), [])

    def test_strict_makes_errors_and_no_metadata_no_check(self):
        self.assertEqual(found("Х = Константа.Нет;", "L7712", strict=True), [(1, 15, "error")])
        self.assertEqual(found("Х = Константа.Нет;", "L7712", md=False), [])
        report = analyze("Х = Константа.Нет;", md=False)
        self.assertEqual((report["metadata_context_modules"], report["metadata"]), (0, []))


class TypeStringTests(unittest.TestCase):
    """L7713: "Type.Kind" arguments of functions taking a type name or an object descriptor."""

    def test_missing_kinds_are_reported(self):
        for text in ('О = СоздатьОбъект("Справочник.Нет");', 'О = СоздатьОбъект("Документ.Нет");',
                     'О = СоздатьОбъект("Регистр.Нет");', 'О = СоздатьОбъект("Счет.Нет");',
                     'О = CreateObject("Справочник.Нет");', 'ОткрытьФорму("Отчет.Нет");',
                     'ОткрытьФорму("Обработка.Нет#Ключ");', 'ОткрытьФорму("Журнал.Нет");',
                     'ОткрытьФорму("Справочник.Нет.ФормаСписка");', 'ОткрытьФорму("Элемент.Нет");',
                     'ОткрытьФормуМодально("Обработка.Нет", П);', 'ОткрытьПодбор("Справочник.Нет");',
                     'Х = ПолучитьПустоеЗначение("Документ.Нет");', 'ТЗ.НоваяКолонка("К", "Справочник.Нет");',
                     'ТЗ.NewColumn("К", "Перечисление.Нет");', 'ТЗ.ВставитьКолонку("К", 1, "Справочник.Нет");',
                     'ТЗ.УстановитьПараметрыКолонки(1, "Справочник.Нет");', 'Форма.Поле.НазначитьТип("Справочник.Нет");',
                     'Х = ПравоДоступа("Чтение", "Справочник.Нет");', 'ВвестиЗначение(З, "Выбор", "Справочник.Нет");'):
            with self.subTest(text=text):
                rows = found(text, "L7713")
                self.assertEqual(len(rows), 1, rows)
                self.assertEqual(rows[0][2], "warning")

    def test_messages_follow_the_native_outcomes(self):
        cases = {'О = СоздатьОбъект("Справочник.Нет");': "Неудачная попытка создания объекта",
                 'ОткрытьФорму("Отчет.Нет");': "Неверно указан вид",
                 'ОткрытьПодбор("Справочник.Нет");': "Неверный вид справочника",
                 'ТЗ.НоваяКолонка("К", "Справочник.Нет");': "ошибки не даёт: тип останется без вида",
                 'Х = ПолучитьПустоеЗначение("Справочник.Нет");': "ошибки не даёт: тип останется без вида",
                 'Х = ПравоДоступа("Чтение", "Справочник.Нет");': "право проверяется для объекта, которого нет",
                 'Форма.Поле.НазначитьТип("Справочник.Нет");': "нативно не проверялась",
                 'ОткрытьФорму("Журнал.Нет");': "нет объекта Журнал.Нет или Документ.Нет"}
        for text, expected in cases.items():
            with self.subTest(text=text):
                message, = messages(text, "L7713")
                self.assertIn(expected, message)

    def test_existing_kinds_and_other_strings_are_silent(self):
        for text in ('О = СоздатьОбъект("Справочник.Контрагенты");', 'О = СоздатьОбъект("справочник.КОНТРАГЕНТЫ");',
                     'О = СоздатьОбъект("Справочник");', 'О = СоздатьОбъект("ТаблицаЗначений");',
                     'О = СоздатьОбъект("Регистр.ОстаткиТоваров");', 'О = СоздатьОбъект("Счет.Основной");',
                     'ОткрытьФорму("Отчет.АнализСчета");', 'ОткрытьФорму("Обработка.ВводАдреса#Ключ");',
                     'ОткрытьФорму("Журнал.Банк");', 'ОткрытьФорму("Журнал.Выписка");',
                     'ОткрытьФорму("Журнал.Подчиненные", , Док);', 'ОткрытьФорму("Справочник.Контрагенты.ЛюбаяФорма");',
                     'ОткрытьФорму("Элемент.Сотрудники");', 'ОткрытьФорму("ПланСчетов.Основной.Форма");',
                     'ОткрытьФорму("Отчет", , "C:\\Отчет.ert");', 'ОткрытьФорму("ЖурналОпераций.Нет");',
                     'ТЗ.НоваяКолонка("К", "Перечисление.Пол");', 'ТЗ.НоваяКолонка("К", "Строка", 10);',
                     'Т = "Справочник.Нет";', 'О = СоздатьОбъект("Справочник." + Вид);', 'О = СоздатьОбъект(Т);',
                     'Сообщить("Справочник.Нет");', 'О = СоздатьОбъект("Справочник.Нет" + "");',
                     'Х = Метаданные.Справочник("Нет").Выбран();'):
            with self.subTest(text=text):
                self.assertEqual(found(text, "L7713"), [])

    def test_own_procedure_of_the_same_name_is_not_the_platform_function(self):
        text = ('Процедура НазначитьТип(А, Б)\nКонецПроцедуры\nПроцедура П()\n'
                'НазначитьТип("Х", "Справочник.Нет");\nФорма.Поле.НазначитьТип("Справочник.Нет");\nКонецПроцедуры\n')
        self.assertEqual([row[0] for row in found(text, "L7713")], [5])

    def test_position_strict_and_no_metadata(self):
        text = 'Процедура П()\n    О = СоздатьОбъект("Справочник.Нет");\nКонецПроцедуры\n'
        self.assertEqual(found(text, "L7713"), [(2, 23, "warning")])
        self.assertEqual(found(text, "L7713", strict=True), [(2, 23, "error")])
        self.assertEqual(found(text, "L7713", md=False), [])


class ContextTests(unittest.TestCase):
    """--metadata for text and ERT modules; a 1Cv7.MD checks its own modules; run and MCP take the base."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-lint-md-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.md = self.root / "1Cv7.MD"
        self.md.write_bytes(make_md(FULL_TEXT))
        self.module = self.root / "module.1s"
        self.module.write_text("Х = Константа.Нет;\nО = СоздатьОбъект(\"Справочник.Контрагенты\");\n", encoding="utf-8")

    def cli(self, *args):
        completed = subprocess.run([sys.executable, "-m", "harness77", "lint", "--format=json", *args],
                                   capture_output=True, text=True, encoding="utf-8", cwd=self.root,
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        return completed.returncode, completed.stdout, completed.stderr

    def test_cli_metadata_reports_its_context(self):
        code, stdout, _ = self.cli("--metadata", str(self.md), str(self.module))
        report = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual([(d["rule"], d["line"]) for d in report["diagnostics"]], [("L7712", 1)])
        self.assertEqual(report["metadata_context_modules"], 1)
        self.assertEqual(report["metadata"], [{"path": str(self.md.resolve()),
                                               "sha256": metadata77.sha256(self.md.read_bytes()),
                                               "configuration": "Тестовая конфигурация"}])
        code, _, _ = self.cli("--strict", "--metadata", str(self.md), str(self.module))
        self.assertEqual(code, 1)
        code, stdout, _ = self.cli(str(self.module))
        self.assertEqual((code, json.loads(stdout)["diagnostics"]), (0, []))

    def test_cli_refuses_bad_metadata(self):
        broken = self.root / "broken.md"
        broken.write_bytes(b"not a compound file")
        other = self.root / "base.txt"
        other.write_bytes(make_md(FULL_TEXT))
        cases = {"1Cv7.MD": other, "не читаются как 1Cv7.MD": broken, "nowhere.md": self.root / "nowhere.md"}
        for message, path in cases.items():
            with self.subTest(path=path.name):
                code, _, stderr = self.cli("--metadata", str(path), str(self.module))
                self.assertEqual(code, 2)
                self.assertIn(message, json.loads(stderr)["fatal_error"])
        code, _, stderr = self.cli("--metadata", str(self.md), "--output", str(self.md), str(self.module))
        self.assertEqual(code, 2)
        self.assertEqual(self.md.read_bytes(), make_md(FULL_TEXT))

    def test_modules_of_a_1cv7_md_run_on_its_own_metadata(self):
        path = self.root / "own.md"
        path.write_bytes(make_md_with_module("Х = Константа.Нет;\r\nХ = Перечисление.Пол.Мужской;\r\n"))
        sources = lint77.load_sources(path)
        self.assertEqual(sources[0].metadata.configuration, "Тестовая конфигурация")
        report = lint77.analyze(sources)
        self.assertEqual([(d["rule"], d["line"]) for d in report["diagnostics"]], [("L7712", 1)])
        # --metadata of another base does not replace the configuration's own.
        other = self.root / "other.MD"
        other.write_bytes(make_md(FULL_TEXT.replace('"АдресОрганизации"', '"Нет"').replace("Тестовая", "Другая")))
        code, stdout, _ = self.cli("--metadata", str(other), str(path))
        self.assertEqual([d["rule"] for d in json.loads(stdout)["diagnostics"]], ["L7712"])
        self.assertEqual(json.loads(stdout)["metadata"][0]["configuration"], "Тестовая конфигурация")

    def test_own_names_of_an_md_are_read_only_for_its_own_modules(self):
        path = self.root / "broken-names.md"
        path.write_bytes(make_md_with_module("Х = 1;\r\n", FULL_TEXT.replace('{"15","АдресОрганизации"',
                                                                               '{"x","АдресОрганизации"')))
        with self.assertRaisesRegex(ert.ErtError, "неизвестная запись в разделе Consts"):
            lint77.load_sources(path)
        # As --globals the configuration gives only its exports: its object names are not read.
        self.assertIsNone(lint77.load_sources(path, own_metadata_names=False)[0].metadata)

    def test_md_without_a_metadata_stream_is_linted_without_names(self):
        from test_lint77 import make_ert as make_module_cfb
        path = self.root / "plain.md"
        path.write_bytes(make_module_cfb("Х = Константа.Нет;\r\n"))
        report = lint77.analyze(lint77.load_sources(path))
        self.assertEqual((report["metadata_context_modules"], report["diagnostics"]), (0, []))

    def project(self, metadata=None):
        project = write_project(self.root / "project", source_text=self.module.read_text(encoding="utf-8"))
        if metadata:
            text = project.read_text(encoding="utf-8").replace(
                'source = "module.1s"', f'source = "module.1s"\nmetadata = "{Path(metadata).as_posix()}"')
            project.write_text(text, encoding="utf-8")
        return project

    def static(self, project, base):
        stand = write_sim_stand(self.root, base_scenario(), base=Path(base).as_posix())
        report = run(project, stand, self.root / "runs")
        return report, {s["stage"]: s for s in report["stages"]}["static"]

    def test_run_takes_the_stand_base_metadata(self):
        report, static = self.static(self.project(), self.root)
        self.assertEqual(static["status"], "passed")
        self.assertEqual([(d["rule"], d["line"]) for d in static["diagnostics"]], [("L7712", 1)])
        self.assertEqual(static["metadata"], {"sha256": metadata77.sha256(self.md.read_bytes()),
                                              "configuration": "Тестовая конфигурация", "source": "stand"})
        self.assertEqual(report["exit_code"], 0)

    def test_run_prefers_the_project_metadata_and_tolerates_a_base_without_one(self):
        other = self.root / "other.MD"
        other.write_bytes(make_md(FULL_TEXT.replace('"АдресОрганизации"', '"Нет"').replace("Тестовая", "Другая")))
        _, static = self.static(self.project(other), self.root)
        self.assertEqual((static["diagnostics"], static["metadata"]["source"]), ([], "project"))
        self.assertEqual(static["metadata"]["configuration"], "Другая конфигурация")
        _, static = self.static(self.project(), self.root / "nowhere")
        self.assertEqual((static["status"], static["diagnostics"], static["metadata"]), ("passed", [], None))

    def test_run_blocks_on_unreadable_metadata(self):
        broken = self.root / "broken"
        broken.mkdir()
        (broken / "1Cv7.MD").write_bytes(b"not a compound file")
        report, static = self.static(self.project(), broken)
        self.assertEqual(static["status"], "blocked")
        self.assertIn("не читаются как 1Cv7.MD", static["reason"])
        self.assertEqual(report["exit_code"], 2)

    def test_mcp_lint_passes_the_metadata(self):
        from harness77 import mcp77
        self.assertEqual(mcp77.TOOLS_BY_NAME["lint"].argv({"paths": ["a.1s"], "metadata": "1Cv7.MD"}),
                         ["lint", "--format=json", "--metadata=1Cv7.MD", "--", "a.1s"])


if __name__ == "__main__":
    unittest.main()
