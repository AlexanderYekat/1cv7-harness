"""Task 022: forms of a 1Cv7.MD by description — md-extract, md-build, and a run with a changed form.

The configuration is the synthetic 1Cv7.MD of task 021 with dialogs in the 1C 7.7 layout: a
document's form with a table part (Browser), a catalog's element form and a processing's form.
The native acceptance of the built forms is docs/tasks/022-md-forms-acceptance.md.
"""

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from pathlib import Path

from harness77 import ert_module as ert
from harness77 import form77, md77

from test_ert_dialog import DIALOG
from test_md77 import MODULES, md_bytes, streams_of

DOCUMENT = "Document/Document_Number238/WorkBook/Dialog Stream"
ELEMENT = "Subconto/Subconto_Number133/WorkBook/Dialog Stream"
PROCESSING = "CalcVar/CalcVar_Number25804/WorkBook/Dialog Stream"
OPERATION = "Operation/Operation_Number2/WorkBook/Dialog Stream"
DOCUMENT_FORM = "Документ/Выписка/Форма.json"
ELEMENT_FORM = "Справочник/Контрагенты/ФормаЭлемента.json"
PROCESSING_FORM = "Обработка/ВводАдреса/Форма.json"
TABLE = (7, 20, 300, 100)


def with_table(text, box=TABLE):
    """The dialog with a table part: the one Multicolumn record of a Browser section (as 1C writes it)."""
    tree = ert.parse_dialog(text)
    record = list([s for s in tree[1:] if s[:1] == ["Controls"]][0][1])
    record[1], record[9], record[11], record[12] = "browse", "4151", "", ""
    record[3:7] = map(str, box)
    browser = ["Browser", "26", "1", ["Multicolumn", record],
               ["Fixed", ["1", "Сумма", "75", "1CEDIT", "4152", "", "", "Сумма", "13043", "1", "10", "0"]]]
    tree.insert(2, browser)
    return form77.serialize_dialog(tree)


# The document's form: its third control is the field of the head attribute Сотрудник.
DOCUMENT_TEXT = with_table(DIALOG.replace("выбДатаНач", "Сотрудник"))
GLOBAL = "Процедура глОткрыть() Экспорт\r\nКонецПроцедуры\r\n\r\nПерем глВерсия Экспорт;\r\nглВерсия = 1;\r\n"


def forms_md(dialogs=None, modules=MODULES):
    dialogs = dict({DOCUMENT: DOCUMENT_TEXT, ELEMENT: DIALOG, PROCESSING: DIALOG, OPERATION: '{"Dialogs"}'},
                   **(dialogs or {}))
    return md_bytes(modules=modules, extra={path: ert.encode_dialog(text) for path, text in dialogs.items()})


def added(**control):
    return dict({"x": 20, "y": 125, "width": 60, "height": 13}, **control)


class MdFormTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h77-mdf-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.md = self.root / "1Cv7.MD"
        self.md.write_bytes(forms_md())
        self.report = md77.extract(self.md, self.root / "x")
        self.folder = self.root / "x"
        self.count = 0

    def description(self, file):
        return json.loads((self.folder / file).read_text(encoding="utf-8"))

    def build(self, files):
        """md-build from a new directory holding only the given {file: text or description}."""
        self.count += 1
        folder = self.root / f"changes{self.count}"
        for file, value in files.items():
            (folder / file).parent.mkdir(parents=True, exist_ok=True)
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            (folder / file).write_bytes(text.encode("utf-8"))
        return md77.build(self.md, folder, self.root / f"out{self.count}.MD")

    def changed(self, file, *controls, height=None):
        description = copy.deepcopy(self.description(file))
        description["controls"] += list(controls)
        if height:
            description["form"]["height"] = height
        return description

    def refused(self, pattern, files):
        with self.assertRaisesRegex(ert.ErtError, pattern):
            self.build(files)

    def test_a_description_next_to_each_form_module(self):
        index = json.loads((self.folder / md77.INDEX).read_text(encoding="utf-8"))
        self.assertEqual(index["schema_version"], 2)
        rows = {row["file"]: row for row in index["forms"]}
        self.assertEqual(set(rows), {DOCUMENT_FORM, ELEMENT_FORM, PROCESSING_FORM, "Прочие/Operation_Number2.json"})
        self.assertEqual(rows[DOCUMENT_FORM]["path"], DOCUMENT)
        self.assertEqual((rows[DOCUMENT_FORM]["object"], rows[DOCUMENT_FORM]["module"]), ("Документ.Выписка", "Форма"))
        self.assertFalse(rows["Прочие/Operation_Number2.json"]["described"])
        self.assertEqual(self.report["output"]["forms"], 3)
        self.assertEqual([row["file"] for row in self.report["forms_not_described"]], ["Прочие/Operation_Number2.json"])
        self.assertIn("разметке", self.report["forms_not_described"][0]["reason"])
        self.assertFalse((self.folder / "Прочие" / "Operation_Number2.json").exists())
        self.assertEqual(self.description(DOCUMENT_FORM), form77.describe(DOCUMENT_TEXT))
        self.assertTrue((self.folder / "Документ" / "Выписка" / "Форма.1s").is_file())

    def test_the_extraction_builds_the_template(self):
        report = md77.build(self.md, self.folder, self.root / "same.MD")
        self.assertEqual((self.root / "same.MD").read_bytes(), self.md.read_bytes())
        self.assertEqual((report["rebuilt"], report["changed_forms"], report["unchanged_forms"]), (False, [], 4))
        self.assertEqual((report["modules"]["files"], report["modules"]["forms"]), (len(MODULES), 3))

    def test_a_changed_description_changes_only_its_dialog(self):
        button = added(**{"class": "BUTTON", "caption": "Проверка 77", "formula": "глОткрыть()"})
        report = self.build({PROCESSING_FORM: self.changed(PROCESSING_FORM, button),
                             "ГлобальныйМодуль.1s": GLOBAL})
        before, after = streams_of(self.md.read_bytes()), streams_of((self.root / "out1.MD").read_bytes())
        self.assertEqual({path for path in before if before[path] != after[path]},
                         {PROCESSING, "TypedText/ModuleText_Number1/MD Programm text"})
        row, = report["changed_forms"]
        self.assertEqual((row["file"], row["object"], row["module_file"]),
                         (PROCESSING_FORM, "Обработка.ВводАдреса", "Обработка/ВводАдреса/Форма.1s"))
        self.assertEqual(row["changes"], [{"control": 4155, "added": "BUTTON"}])
        rebuilt = form77.describe(ert.decode_dialog(after[PROCESSING]))
        self.assertEqual(rebuilt["controls"][-1]["formula"], "глОткрыть()")
        self.assertEqual(row["dialog_sha256_after"], form77.sha256(ert.decode_dialog(after[PROCESSING]).encode("cp1251")))
        self.assertEqual(report["unchanged_forms"], 3)
        # The rebuilt configuration extracts to the changed description.
        md77.extract(self.root / "out1.MD", self.root / "again")
        self.assertEqual(json.loads((self.root / "again" / PROCESSING_FORM).read_text(encoding="utf-8"))["controls"],
                         rebuilt["controls"])

    def test_a_formula_calls_the_form_module_the_global_module_or_the_platform(self):
        call = lambda formula: added(**{"class": "BUTTON", "caption": "77", "formula": formula})
        self.refused("ни среди экспортных процедур глобального модуля",
                     {PROCESSING_FORM: self.changed(PROCESSING_FORM, call("глОткрыть()"))})
        self.build({PROCESSING_FORM: self.changed(PROCESSING_FORM, call("Нажатие77()")),
                    "Обработка/ВводАдреса/Форма.1s": "Процедура Нажатие77()\r\nКонецПроцедуры\r\n"})
        self.build({PROCESSING_FORM: self.changed(PROCESSING_FORM, call("Сообщить(1)"))})

    def test_a_field_of_a_head_attribute_takes_its_type(self):
        report = self.build({DOCUMENT_FORM: self.changed(
            DOCUMENT_FORM, added(**{"class": "BMASKED", "identifier": "Основание",
                                    "type": {"kind": "reference", "object": "Документ"}}),
            added(**{"class": "BMASKED", "identifier": "Автор", "x": 90,
                     "type": {"kind": "reference", "object": "Справочник.Сотрудники"}}))})
        changes = report["changed_forms"][0]["changes"]
        self.assertEqual([change.get("attribute") for change in changes if change["control"]],
                         ["Документ.Выписка.Основание", "Документ.Выписка.Автор"])
        # 1C creates the windows from the last record: the table part keeps its place after the
        # template's 26 when the two new records come first (series 1: 26 windows, then the table part).
        self.assertIn({"control": None, "property": "table_part_position", "from": 26, "to": 28}, changes)
        dialog = ert.decode_dialog(streams_of((self.root / "out1.MD").read_bytes())[DOCUMENT])
        self.assertEqual([s for s in ert.parse_dialog(dialog)[1:] if s[:1] == ["Browser"]][0][1], "28")
        self.refused(r"поле реквизита Документ\.Выписка\.Вид должно иметь тип реквизита \(Перечисление\.Пол\), "
                     r"в описании — строка длины 10", {DOCUMENT_FORM: self.changed(DOCUMENT_FORM, added(**{
                         "class": "1CEDIT", "identifier": "Вид", "type": {"kind": "string", "length": 10}}))})
        self.refused("элемент класса BUTTON не поле", {DOCUMENT_FORM: self.changed(DOCUMENT_FORM, added(**{
            "class": "BUTTON", "caption": "77", "identifier": "Основание", "formula": "Сообщить(1)"}))})

    def test_table_and_built_in_attributes_and_rebinding_are_refused(self):
        string = {"class": "1CEDIT", "type": {"kind": "string", "length": 10}}
        self.refused("реквизит табличной части Документ.Выписка",
                     {DOCUMENT_FORM: self.changed(DOCUMENT_FORM, added(identifier="Сумма", **string))})
        self.refused("встроенный реквизит Документ.Выписка",
                     {DOCUMENT_FORM: self.changed(DOCUMENT_FORM, added(identifier="НомерДок", **string))})
        self.refused("встроенный реквизит Справочник.Контрагенты",
                     {ELEMENT_FORM: self.changed(ELEMENT_FORM, added(identifier="наименование", **string))})
        renamed = self.changed(DOCUMENT_FORM)
        renamed["controls"][2]["identifier"] = "Сотрудник2"
        self.refused("меняет привязку поля к реквизиту Документ.Выписка.Сотрудник", {DOCUMENT_FORM: renamed})
        # A form attribute of another name, and a catalog attribute of the element form, are fields as in an ERT.
        self.build({DOCUMENT_FORM: self.changed(DOCUMENT_FORM, added(identifier="Поле77", **string)),
                    ELEMENT_FORM: self.changed(ELEMENT_FORM, added(**{"class": "1CEDIT", "identifier": "ИНН",
                                                                      "type": {"kind": "string"}}))})

    def test_the_table_part_is_an_obstacle(self):
        over = added(**{"class": "STATIC", "caption": "Надпись", "y": 60})
        self.refused(r"накладывается на табличную часть \(7, 20, 300×100\)",
                     {DOCUMENT_FORM: self.changed(DOCUMENT_FORM, over)})
        # The processing's form has no table part: the same place is free.
        report = self.build({PROCESSING_FORM: self.changed(PROCESSING_FORM, over)})
        self.assertEqual(report["changed_forms"][0]["changes"], [{"control": 4155, "added": "STATIC"}])
        # Moving a control changes no table part position.
        moved = self.changed(DOCUMENT_FORM)
        moved["controls"][0]["y"] = 125
        report = self.build({DOCUMENT_FORM: moved})
        self.assertEqual([c["property"] for c in report["changed_forms"][0]["changes"]], ["y"])

    def test_a_stale_description_and_a_description_of_no_form_are_refused(self):
        description = self.changed(PROCESSING_FORM, added(**{"class": "STATIC", "caption": "Надпись"}))
        self.md.write_bytes(forms_md({PROCESSING: DIALOG.replace('" "', '"Обработка"', 1)}))
        self.refused(r"Обработка/ВводАдреса/Форма\.json: Описание сделано для другого шаблона",
                     {PROCESSING_FORM: description})
        self.refused("нет такой формы", {"Документ/Выписка/Нет.json": description})
        self.refused("Прочие/Operation_Number2.json: .*разметке", {"Прочие/Operation_Number2.json": description})

    def test_an_index_of_task_021_is_read(self):
        index = json.loads((self.folder / md77.INDEX).read_text(encoding="utf-8"))
        del index["forms"]
        index["schema_version"] = 1
        report = self.build({md77.INDEX: index, "ГлобальныйМодуль.1s": GLOBAL})
        self.assertEqual([row["file"] for row in report["changed"]], ["ГлобальныйМодуль.1s"])

    def test_the_platform_names_a_processing_form_module(self):
        # Series 0: «{Обработка.ВыводТаблицыЗначений.Форма.Модуль(10)}» in the copy's event log.
        self.assertEqual(md77.platform_module("Обработка.ВыводТаблицыЗначений.Форма.Модуль"),
                         "Обработка/ВыводТаблицыЗначений/Форма.1s")
        self.assertIsNone(md77.platform_module("Отчет.Анализ.Форма.Модуль"))
        row, = md77.configuration_diagnostics(
            [{"event": "GrbgSyntaxErr", "time": "09:25:58",
              "text": "Х = Флажок77<<?>>; : {Обработка.ВводАдреса.Форма.Модуль(10)}: Переменная не определена (Флажок77)"}],
            [{"file": "Обработка/ВводАдреса/Форма.1s", "object": "Обработка.ВводАдреса"}])
        self.assertEqual((row["file"], row["line"], row["changed"]), ("Обработка/ВводАдреса/Форма.1s", 10, True))

    def test_cli(self):
        folder = self.root / "cli"
        (folder / "Обработка" / "ВводАдреса").mkdir(parents=True)
        (folder / PROCESSING_FORM).write_text(json.dumps(self.changed(PROCESSING_FORM, added(**{
            "class": "STATIC", "caption": "Надпись"})), ensure_ascii=False), encoding="utf-8")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = md77.main("md-build", ["--template", str(self.md), "--modules", str(folder),
                                          "--output", str(self.root / "cli.MD")])
        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual((report["rebuilt"], report["changed_forms"][0]["file"]), (True, PROCESSING_FORM))
        self.assertTrue(report["verification"]["changed_dialogs"])


class FormRunTests(unittest.TestCase):
    """A run whose configuration directory changes a form: its module is checked in the new dialog."""

    def test_the_module_of_a_changed_form_is_a_changed_module(self):
        from harness77 import basecopy77
        from stage4_fixtures import run
        from test_run77_configuration import ConfigurationRunTests, fake_base
        temp = tempfile.TemporaryDirectory(prefix="h77-mdfr-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        base = fake_base(root / "base-for-test")
        modules = root / "configuration"
        # The unchanged module reads the field выбДатаНач, which the description renames: the remark
        # is new, and it comes from the form alone.
        template = md_bytes(modules=dict(MODULES, **{"CalcVar/CalcVar_Number25804/WorkBook":
                                                     "Процедура ПриОткрытии()\r\n    Сообщить(выбДатаНач);\r\n"
                                                     "КонецПроцедуры\r\n"}),
                            extra={path: ert.encode_dialog(text) for path, text in
                                   {DOCUMENT: DOCUMENT_TEXT, ELEMENT: DIALOG, PROCESSING: DIALOG}.items()})
        (base / "1Cv7.MD").write_bytes(template)
        md77.extract(base / "1Cv7.MD", modules)
        description = json.loads((modules / PROCESSING_FORM).read_text(encoding="utf-8"))
        description["controls"][2]["identifier"] = "Дата77"
        for file in [p for p in modules.rglob("*") if p.is_file()]:
            file.unlink()
        (modules / PROCESSING_FORM).write_text(json.dumps(description, ensure_ascii=False), encoding="utf-8")
        helper = ConfigurationRunTests()
        helper.root, helper.base, helper.modules = root, base, modules
        before = basecopy77.listing(base)
        report = run(helper.project(), helper.stand(), root / "runs")
        configuration = helper.stage(report, "configuration")
        self.assertEqual(configuration["status"], "passed")
        self.assertEqual([row["file"] for row in configuration["changed_forms"]], [PROCESSING_FORM])
        self.assertEqual(configuration["changed"], [])
        static = helper.stage(report, "static")
        self.assertEqual(static["configuration_modules"], ["CalcVar/CalcVar_Number25804/WorkBook/MD Programm text"])
        found = [(d["rule"], d["line"]) for d in static["diagnostics"] if d["module"].startswith("CalcVar/")
                 and "выбДатаНач" in d["message"]]
        self.assertEqual(found, [("L7711", 2)])
        self.assertEqual(basecopy77.listing(base), before)


class GlobalModuleRunTests(unittest.TestCase):
    """The owner's decision after task 022: run reads the global module of the base the module runs on.

    It comes from the same 1Cv7.MD as the metadata — the project's [build] metadata, else the stand
    base's — and completes the context of L7711: an undeclared read is an error, as 1C does not compile it.
    """

    MODULE = "Процедура П()\n    Сообщить(глВерсия);\n    Сообщить(Нет77);\nКонецПроцедуры\n"

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="h77-glob-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        (self.base / "1Cv7.MD").write_bytes(md_bytes())  # its global module exports глВерсия

    def go(self, metadata=None):
        from stage4_fixtures import base_scenario, run, write_project, write_sim_stand
        project = write_project(self.root / "project", source_text=self.MODULE)
        if metadata is not None:
            project.write_text(project.read_text(encoding="utf-8").replace(
                'source = "module.1s"', f'source = "module.1s"\nmetadata = "{metadata.as_posix()}"'), encoding="utf-8")
        stand = write_sim_stand(self.root, base_scenario(), base=self.base.as_posix())
        report = run(project, stand, self.root / "runs")
        return report, next(s for s in report["stages"] if s["stage"] == "static")

    def remarks(self, static):
        return [(d["rule"], d["line"], d["severity"]) for d in static["diagnostics"] if d["rule"] == "L7711"]

    def test_the_stand_base_global_module_makes_an_undeclared_read_an_error(self):
        report, static = self.go()
        self.assertEqual(self.remarks(static), [("L7711", 3, "error")])
        self.assertEqual((static["status"], static["global_module"], report["exit_code"]), ("failed", "stand", 1))

    def test_the_project_metadata_gives_its_global_module(self):
        other = self.root / "target.MD"
        other.write_bytes(md_bytes(modules=dict(MODULES, **{
            "TypedText/ModuleText_Number1": "Перем глВерсия Экспорт;\r\nПерем Нет77 Экспорт;\r\n"})))
        report, static = self.go(metadata=other)
        self.assertEqual((self.remarks(static), static["global_module"], report["exit_code"]), ([], "project", 0))

    def test_an_unreadable_global_module_leaves_the_context_open(self):
        (self.base / "1Cv7.MD").write_bytes(md_bytes(extra={"TypedText/ModuleText_Number1/MD Programm text": b"no"}))
        _, static = self.go()
        self.assertEqual((self.remarks(static), static["status"], static["global_module"]),
                         ([("L7711", 2, "warning"), ("L7711", 3, "warning")], "passed", None))
        self.assertIn("глобальный модуль", static["global_module_error"])


if __name__ == "__main__":
    unittest.main()
