"""Task 021: modules of a 1Cv7.MD by name, md-extract and md-build.

The configuration is a synthetic 1Cv7.MD with every folder kind of base-for-test; the
native acceptance of the built configuration is docs/tasks/021-md-modules-acceptance.md.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from harness77 import ert_module as ert
from harness77 import md77
from harness77.lint77 import cfb_paths

from test_lint77_context import MD_TEXT, make_cfb, module

TEXT = MD_TEXT.replace('{"Buh"', '{"ReportList",\r\n{"370","АнализСубконто","",""}},\r\n'
                                 '{"CalcVars",\r\n{"25804","ВводАдреса","",""}},\r\n{"Buh"')
MODULES = {
    "TypedText/ModuleText_Number1": "Перем глВерсия Экспорт;\r\nглВерсия = 1;\r\n",
    "TypedText/Transact_Number238": "Процедура ОбработкаПроведения()\r\nКонецПроцедуры\r\n",
    "Document/Document_Number238/WorkBook": "Процедура ПриОткрытии()\r\nКонецПроцедуры\r\n",
    "Subconto/Subconto_Number133/WorkBook": "// элемент\r\n",
    "SubFolder/SubFolder_Number112/WorkBook": "// группа\r\n",
    "SubList/SubList_Number132/WorkBook": "// список\r\n",
    "Journal/Journal_Number479/WorkBook": "// журнал\r\n",
    "Report/Report_Number370/WorkBook": "// отчёт\r\n",
    "CalcVar/CalcVar_Number25804/WorkBook": "// обработка\r\n",
    "Operation/Operation_Number2/WorkBook": "// операция\r\n",
    "Document/Document_Number999/WorkBook": "// документа 999 нет\r\n",
}
FILES = {
    "ГлобальныйМодуль.1s": ("TypedText/ModuleText_Number1", None, "ГлобальныйМодуль"),
    "Документ/Выписка/МодульДокумента.1s": ("TypedText/Transact_Number238", "Документ.Выписка", "МодульДокумента"),
    "Документ/Выписка/Форма.1s": ("Document/Document_Number238/WorkBook", "Документ.Выписка", "Форма"),
    "Справочник/Контрагенты/ФормаЭлемента.1s": ("Subconto/Subconto_Number133/WorkBook", "Справочник.Контрагенты",
                                                "ФормаЭлемента"),
    "Справочник/Договоры/ФормаГруппы.1s": ("SubFolder/SubFolder_Number112/WorkBook", "Справочник.Договоры",
                                           "ФормаГруппы"),
    "Справочник/Контрагенты/ФормаСписка.ФормаСписка.1s": ("SubList/SubList_Number132/WorkBook",
                                                          "Справочник.Контрагенты", "ФормаСписка.ФормаСписка"),
    "Журнал/Банк/ФормаСписка.ФормаСписка.1s": ("Journal/Journal_Number479/WorkBook", "Журнал.Банк",
                                               "ФормаСписка.ФормаСписка"),
    "Отчет/АнализСубконто/Форма.1s": ("Report/Report_Number370/WorkBook", "Отчет.АнализСубконто", "Форма"),
    "Обработка/ВводАдреса/Форма.1s": ("CalcVar/CalcVar_Number25804/WorkBook", "Обработка.ВводАдреса", "Форма"),
    "Прочие/Operation_Number2.1s": ("Operation/Operation_Number2/WorkBook", None, None),
    "Прочие/Document_Number999.1s": ("Document/Document_Number999/WorkBook", None, None),
}


def md_bytes(text=TEXT, modules=MODULES, extra=None):
    streams = {"Metadata/Main MetaData Stream": ert.encode_dialog(text), "Metadata/GUIDData": b"GUID" * 40,
               "Document/Document_Number238/WorkBook/Dialog Stream": ert.encode_dialog('{"Dialogs"}'),
               "TypedText/UserHelp_Number238/MD Programm text": module("Описание документа\r\n")}
    for folder, code in modules.items():
        streams[f"{folder}/MD Programm text"] = module(code)
    streams.update(extra or {})
    return make_cfb(streams)


def streams_of(data):
    compound = ert.CompoundFile(data)
    paths = cfb_paths(compound)
    return {paths[e.entry_id]: compound.read_stream(e) for e in compound.directory_entries
            if e.object_type == 2 and e.entry_id in paths}


class Md77Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h77-md-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.md = self.root / "1Cv7.MD"
        self.md.write_bytes(md_bytes())

    def extract(self, md=None, name="modules"):
        return md77.extract(md or self.md, self.root / name), self.root / name

    def build(self, folder, name="new.MD", template=None):
        report = md77.build(template or self.md, folder, self.root / name)
        return report, (self.root / name).read_bytes()

    def test_files_of_every_folder(self):
        report, folder = self.extract()
        index = json.loads((folder / md77.INDEX).read_text(encoding="utf-8"))
        found = {row["file"]: (row["path"].rsplit("/", 1)[0], row["object"], row["module"])
                 for row in index["modules"]}
        self.assertEqual(found, FILES)
        self.assertEqual(report["output"]["modules"], len(FILES))
        # Descriptions are no modules; the files hold the text in UTF-8 with the CRLF of 1C.
        self.assertFalse(any("UserHelp" in row["path"] for row in index["modules"]))
        self.assertEqual((folder / "Документ" / "Выписка" / "Форма.1s").read_bytes(),
                         MODULES["Document/Document_Number238/WorkBook"].encode("utf-8"))
        self.assertEqual(index["md"]["configuration"], "Тестовая конфигурация")

    def test_build_without_changes_is_the_template(self):
        _, folder = self.extract()
        report, data = self.build(folder)
        self.assertEqual(data, self.md.read_bytes())
        self.assertEqual((report["rebuilt"], report["changed"], report["unchanged_modules"]), (False, [], len(FILES)))
        self.assertEqual(report["modules"]["files"], len(FILES))

    def test_one_changed_module_changes_only_its_stream(self):
        _, folder = self.extract()
        target = folder / "Документ" / "Выписка" / "МодульДокумента.1s"
        new = "Процедура ОбработкаПроведения()\r\n    глВерсия = 43;\r\nКонецПроцедуры\r\n"
        target.write_text(new, encoding="utf-8", newline="")
        report, data = self.build(folder)
        self.assertTrue(report["rebuilt"])
        self.assertEqual([(row["file"], row["object"], row["module"]) for row in report["changed"]],
                         [("Документ/Выписка/МодульДокумента.1s", "Документ.Выписка", "МодульДокумента")])
        before, after = streams_of(self.md.read_bytes()), streams_of(data)
        self.assertEqual(set(before), set(after))
        changed = "TypedText/Transact_Number238/MD Programm text"
        self.assertEqual(ert.decompress_module(after[changed]), new.encode("cp1251"))
        self.assertEqual({k: v for k, v in before.items() if k != changed},
                         {k: v for k, v in after.items() if k != changed})

    def test_newlines_alone_are_no_change(self):
        _, folder = self.extract()
        target = folder / "Документ" / "Выписка" / "Форма.1s"
        target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n"))
        report, data = self.build(folder)
        self.assertEqual((report["changed"], data), ([], self.md.read_bytes()))

    def test_a_directory_of_changed_files_only(self):
        folder = self.root / "changed"
        (folder / "Обработка" / "ВводАдреса").mkdir(parents=True)
        (folder / "Обработка" / "ВводАдреса" / "Форма.1s").write_text("// новая\n", encoding="cp1251")
        report, data = self.build(folder)
        self.assertIsNone(report["modules"]["index"])
        self.assertEqual(report["changed"][0]["encoding"], "cp1251")
        self.assertEqual(ert.decompress_module(streams_of(data)["CalcVar/CalcVar_Number25804/WorkBook/MD Programm text"]),
                         "// новая\r\n".encode("cp1251"))

    def test_refusals(self):
        _, folder = self.extract()
        cases = {"unknown object": ("Документ/Нет/Форма.1s", "// x"),
                 "not a module": ("readme.txt", "notes"),
                 "outside cp1251": ("ГлобальныйМодуль.1s", "Перем глВерсия Экспорт;\r\nглВерсия = \"✓\";\r\n")}
        for label, (name, text) in cases.items():
            with self.subTest(label):
                copy = self.root / label
                copy.mkdir()
                (copy / name).parent.mkdir(parents=True, exist_ok=True)
                (copy / name).write_text(text, encoding="utf-8", newline="")
                with self.assertRaises(ert.ErtError) as caught:
                    md77.build(self.md, copy, self.root / f"{label}.MD")
                self.assertFalse((self.root / f"{label}.MD").exists())
                if label == "outside cp1251":
                    self.assertIn("строка 2:13", str(caught.exception))
        with self.assertRaisesRegex(ert.ErtError, "Выход уже существует"):
            md77.build(self.md, folder, self.md)

    def test_the_index_catches_a_template_changed_after_extraction(self):
        _, folder = self.extract()
        # The template changes the document module after the extraction.
        changed = dict(MODULES, **{"TypedText/Transact_Number238": "// изменено в шаблоне\r\n"})
        newer = self.root / "newer.MD"
        newer.write_bytes(md_bytes(modules=changed))
        # An edit of that module, or of another one with the stale file left in place, is refused.
        for edited in ("Документ/Выписка/МодульДокумента.1s", "Документ/Выписка/Форма.1s"):
            with self.subTest(edited):
                (folder / edited).write_text("// правка\r\n", encoding="utf-8", newline="")
                with self.assertRaisesRegex(ert.ErtError, "изменился в шаблоне после извлечения"):
                    md77.build(newer, folder, self.root / "x.MD")
        # Without the stale file only the edit is applied.
        (folder / "Документ" / "Выписка" / "МодульДокумента.1s").unlink()
        report, data = self.build(folder, template=newer)
        self.assertEqual([row["file"] for row in report["changed"]], ["Документ/Выписка/Форма.1s"])
        self.assertEqual(report["modules"]["index"]["md_sha256"], md77.sha256(self.md.read_bytes()))
        self.assertEqual(ert.decompress_module(streams_of(data)["TypedText/Transact_Number238/MD Programm text"]),
                         "// изменено в шаблоне\r\n".encode("cp1251"))

    def test_a_file_not_in_the_index_is_refused(self):
        _, folder = self.extract()
        index = json.loads((folder / md77.INDEX).read_text(encoding="utf-8"))
        index["modules"] = [row for row in index["modules"] if row["file"] != "ГлобальныйМодуль.1s"]
        (folder / md77.INDEX).write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        (folder / "ГлобальныйМодуль.1s").write_text("// правка\r\n", encoding="utf-8")
        with self.assertRaisesRegex(ert.ErtError, "файл не из этого извлечения"):
            md77.build(self.md, folder, self.root / "x.MD")

    def test_two_modules_of_one_file_are_refused(self):
        text = TEXT.replace('{"132","ФормаСписка","",""}', '{"132","Ф","",""},\r\n{"134","Ф","",""}')
        modules = dict(MODULES, **{"SubList/SubList_Number134/WorkBook": "// второй\r\n"})
        self.md.write_bytes(md_bytes(text, modules))
        with self.assertRaisesRegex(ert.ErtError, "один файл"):
            self.extract()
        self.assertFalse((self.root / "modules").exists())

    def test_modules_as_1c_names_them_in_a_compile_error(self):
        # The names of series 1 and 2 of the native probes (task 021).
        self.assertEqual(md77.platform_module("Глобальный модуль"), "ГлобальныйМодуль.1s")
        self.assertEqual(md77.platform_module("Документ.ЗаписьКнигиПродажТорг.Модуль Документа"),
                         "Документ/ЗаписьКнигиПродажТорг/МодульДокумента.1s")
        self.assertEqual(md77.platform_module("Документ.Доверенность.Форма.Модуль"), "Документ/Доверенность/Форма.1s")
        self.assertIsNone(md77.platform_module("Справочник.Банки.ФормаЭлемента"))
        entries = [
            {"event": "GrbgSyntaxErr", "text": "Возврат 42 +<<?>>; : {Глобальный модуль(9812)}: Ошибка в выражении"},
            {"event": "GrbgSyntaxErr", "text": "Х = 1 +<<?>>; : {Справочник.Банки.Нечто(3)}: Ошибка в выражении"},
            {"event": "GrbgSyntaxErr", "text": "Х<<?>> = 1; : {(734)}: Переменная не определена (Х)"},
            {"event": "DocNew", "text": ""}]
        changed = [{"file": "ГлобальныйМодуль.1s", "object": None},
                   {"file": "Справочник/Банки/ФормаЭлемента.1s", "object": "Справочник.Банки"}]
        found = md77.configuration_diagnostics(entries, changed, {"ГлобальныйМодуль.1s": "А\r\n\tВозврат 42 +;\r\n"})
        self.assertEqual([(row["file"], row["line"], row["changed"]) for row in found],
                         [("ГлобальныйМодуль.1s", 9812, True), (None, 3, True)])
        # The line 9812 is not in this text: no column; the source line stays.
        self.assertNotIn("column", found[0])
        self.assertEqual(found[0]["source_line"], "Возврат 42 +;")
        found = md77.configuration_diagnostics([dict(entries[0], text=entries[0]["text"].replace("9812", "2"))],
                                               changed, {"ГлобальныйМодуль.1s": "А\r\n\tВозврат 42 +;\r\n"})
        self.assertEqual(found[0]["column"], 14)

    def test_cli(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(md77.main("md-extract", [str(self.md), "--output", str(self.root / "cli")]), 0)
            self.assertEqual(md77.main("md-build", ["--template", str(self.md), "--modules", str(self.root / "cli"),
                                                    "--output", str(self.root / "cli.MD")]), 0)
            self.assertEqual(md77.main("md-build", ["--template", str(self.md), "--modules", str(self.root / "cli"),
                                                    "--output", str(self.root / "cli.MD")]), 2)
        text, reports, decoder = stdout.getvalue(), [], json.JSONDecoder()
        while text.strip():
            report, end = decoder.raw_decode(text.strip())
            reports.append(report)
            text = text.strip()[end:]
        self.assertEqual([r["operation"] for r in reports], ["md-extract", "md-build"])
        failure = json.loads(stderr.getvalue())
        self.assertEqual((failure["operation"], failure["status"]), ("md-build", "blocked"))


if __name__ == "__main__":
    unittest.main()
