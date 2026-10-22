"""Task 020: the context of 1Cv7.MD modules and of forms (L7711, L7714), table areas, date literals.

Expected outcomes follow the native probes on 1C 7.7.027 (docs/tasks/020-md-module-context-acceptance.md):
a module of an object reads its attributes bare, a report or processing form module reads the named
areas of its first table, 'ОК' is a date literal.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from harness77 import ert_module as ert
from harness77 import lint77
from harness77 import metadata77
from harness77 import moxcel77

from test_lint77_attributes import ATTRIBUTE_TEXT, record, section

FREE, END, FAT_SECTOR = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD


def make_cfb(streams):
    """A CFB v3 holding streams by path ("a/b/name"), storages made on the way.

    Every stream lies in regular sectors (mini stream cutoff 0); siblings are chained by
    their right pointer, a storage points to its first child.
    """
    nodes = [{"name": "Root Entry", "kind": 5, "children": {}, "data": b""}]
    for path, data in streams.items():
        node = nodes[0]
        *folders, name = path.split("/")
        for folder in folders:
            if folder not in node["children"]:
                nodes.append({"name": folder, "kind": 1, "children": {}, "data": b""})
                node["children"][folder] = len(nodes) - 1
            node = nodes[node["children"][folder]]
        nodes.append({"name": name, "kind": 2, "children": {}, "data": data})
        node["children"][name] = len(nodes) - 1
    directory_sectors = (len(nodes) + 3) // 4
    data_sectors = sum((len(n["data"]) + 511) // 512 for n in nodes)
    fat_sectors = 1
    while fat_sectors * 128 < fat_sectors + directory_sectors + data_sectors:
        fat_sectors += 1
    fat = [FAT_SECTOR] * fat_sectors
    fat += [fat_sectors + i + 1 for i in range(directory_sectors - 1)] + [END]
    body, starts = b"", {}
    for number, node in enumerate(nodes):
        count = (len(node["data"]) + 511) // 512
        if count:
            starts[number] = len(fat)
            fat += [len(fat) + i + 1 for i in range(count - 1)] + [END]
            body += node["data"].ljust(count * 512, b"\0")
    fat += [FREE] * (fat_sectors * 128 - len(fat))
    header = bytearray(512)
    header[:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<II", header, 44, fat_sectors, fat_sectors)
    struct.pack_into("<IIIII", header, 56, 0, END, 0, END, 0)
    struct.pack_into("<109I", header, 76, *range(fat_sectors), *([FREE] * (109 - fat_sectors)))
    entries = b""
    for number, node in enumerate(nodes):
        entry = bytearray(128)
        encoded = (node["name"] + "\0").encode("utf-16le")
        entry[:len(encoded)] = encoded
        struct.pack_into("<HBB", entry, 64, len(encoded), node["kind"], 1)
        order = next((list(p["children"].values()) for p in nodes if number in p["children"].values()), [number])
        right = order[order.index(number) + 1] if order.index(number) + 1 < len(order) else FREE
        child = next(iter(node["children"].values()), FREE)
        struct.pack_into("<III", entry, 68, FREE, right, child)
        struct.pack_into("<IQ", entry, 116, starts.get(number, END), len(node["data"]))
        entries += bytes(entry)
    entries = entries.ljust(directory_sectors * 512, b"\0")
    return bytes(header) + b"".join(struct.pack("<128I", *fat[i:i + 128]) for i in range(0, len(fat), 128)) \
        + entries + body


def worksheet(*names):
    """A MOXCEL stream: some cells, then its named areas."""
    tail = struct.pack("<I", len(names))
    for name in names:
        encoded = name.encode("cp1251")
        size = bytes([len(encoded)]) if len(encoded) < 255 else b"\xff" + struct.pack("<H", len(encoded))
        tail += size + encoded + struct.pack("<7I", 1, 0, 3, 4, 5, 4, 5)
    return b"MOXCEL\x00\x00" + bytes(range(40)) + tail


def contents(*pages):
    return ('{"Container.Contents",{"TextDocument","MD Programm text","Module text",""}'
            + "".join(f',{{"Moxcel.Worksheet","{page}","{page}",""}}' for page in pages) + "}").encode("cp1251")


def dialog(*identifiers, columns=()):
    """A dialog with a button per identifier and list columns (Browser/Fixed)."""
    controls = ",".join(f'{{"{name}","BUTTON","0","0","0","0","0","0","0","4152","","","{name}","0"}}'
                        for name in identifiers)
    fixed = ",".join(f'{{"4","{name}","213","STATIC","4153","","Владелец","{name}","0"}}' for name in columns)
    browser = f'{{"Browser","0","1",{{"Fixed",{fixed}}}}},' if columns else ""
    return ert.encode_dialog(f'{{"Dialogs",{browser}{{"Controls",{controls}}}}}')


def module(text):
    return ert.compress_module(text.encode("cp1251"))


def lint(path):
    report = lint77.analyze(lint77.load_sources(path))
    return report, [(d["module"].split("/")[0], d["line"], d["rule"], d["message"].split(":")[0])
                    for d in report["diagnostics"] if d["rule"] in ("L7711", "L7714")]


class MoxcelTests(unittest.TestCase):
    """moxcel77 reads the named areas from the end of a worksheet stream."""

    def test_areas_of_a_worksheet(self):
        self.assertEqual(moxcel77.area_names(worksheet("П001", "Итог_1")), ["П001", "Итог_1"])
        self.assertEqual(moxcel77.area_names(worksheet()), [])
        self.assertEqual(moxcel77.area_names(worksheet("200", "Ж" * 300)), ["200", "Ж" * 300])

    def test_other_streams_are_not_worksheets(self):
        self.assertIsNone(moxcel77.area_names(b"NOTMOX" + bytes(40)))
        self.assertIsNone(moxcel77.area_names(b"MOXCEL" + b"\xff" * 12))
        self.assertIsNone(moxcel77.area_names(worksheet("П001")[:-3]))

    def test_the_profile_names_the_form_s_table(self):
        self.assertEqual(moxcel77.worksheets(contents("Page.2", "Page.1")), [("Page.2", "Page.2"), ("Page.1", "Page.1")])
        self.assertEqual(moxcel77.form_table(contents("Page.2", "Page.1"), profile("Page.1")), "Page.1")
        self.assertIsNone(moxcel77.form_table(contents("Page.2"), profile("\x01Blank")))
        self.assertIsNone(moxcel77.form_table(contents("Page.2"), b""))


def profile(name):
    """A Container.Profile naming the form's table by its title."""
    return ('{\r\n{"MoxelName","' + name + '",""},\r\n{"MoxelPos","0",""},\r\n{"Entry","1",""}}').encode("cp1251")


class FormContextTests(unittest.TestCase):
    """A form module reads its controls, list columns, Таблица and the areas of its named table."""

    def ert(self, folder, code, *, named="Page.2", page2=worksheet("П001", "200"), tables=("Page.2", "Page.1")):
        path = Path(folder) / "form.ert"
        streams = {"MD Programm text": module(code), "Dialog Stream": dialog("Поле1", columns=("Колонка1",)),
                   "Container.Contents": contents(*tables), "Container.Profile": profile(named)}
        streams.update({"Page.2": page2, "Page.1": worksheet("Шапка")} if tables else {})
        path.write_bytes(make_cfb(streams))
        return path

    def test_controls_columns_and_the_named_table_are_declared(self):
        with tempfile.TemporaryDirectory() as folder:
            code = "Процедура П()\r\nХ = Поле1 + Колонка1 + П001 + Таблица;\r\nХ = Шапка;\r\nКонецПроцедуры"
            report, found = lint(self.ert(folder, code))
        self.assertEqual(report["form_context_modules"], 1)
        self.assertEqual([(line, rule) for _, line, rule, _ in found], [(3, "L7711")])

    def test_the_named_table_not_the_first_listed(self):
        with tempfile.TemporaryDirectory() as folder:
            code = "Процедура П()\r\nХ = Шапка;\r\nХ = П001;\r\nКонецПроцедуры"
            _, found = lint(self.ert(folder, code, named="Page.1"))
        self.assertEqual([line for _, line, _, _ in found], [3])

    def test_no_named_table_no_areas(self):
        with tempfile.TemporaryDirectory() as folder:
            code = "Процедура П()\r\nХ = Таблица;\r\nХ = Шапка + П001;\r\nКонецПроцедуры"
            _, found = lint(self.ert(folder, code, named="\x01Blank"))
        self.assertEqual([(line, head) for _, line, _, head in found],
                         [(3, "Переменная не определена (Шапка)"), (3, "Переменная не определена (П001)")])

    def test_unreadable_named_table_leaves_the_context_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            report, found = lint(self.ert(folder, "Процедура П()\r\nХ = Нет77;\r\nКонецПроцедуры", page2=b"MOXCEL\xff\xff"))
        self.assertEqual((report["form_context_modules"], found), (0, []))

    def test_without_tables_no_table_attribute(self):
        with tempfile.TemporaryDirectory() as folder:
            _, found = lint(self.ert(folder, "Процедура П()\r\nХ = Поле1 + Таблица + Нет77;\r\nКонецПроцедуры",
                                     tables=()))
        self.assertEqual([head for _, _, _, head in found],
                         ["Переменная не определена (Таблица)", "Переменная не определена (Нет77)"])


# The base of AttributeRuleTests with forms in its records and a journal.
MD_TEXT = ATTRIBUTE_TEXT.replace(
    '{"Form"}},\r\n{"112"', '{"Form",\r\n{"132","ФормаСписка","",""}}},\r\n{"112"').replace(
    '{"EnumList"', '{"Journalisters",\r\n{"481","Банк","","","-1","0","479","479","0",\r\n'
                   '{"Form",\r\n{"479","ФормаСписка","",""}}}},\r\n{"EnumList"')


def md_streams(**modules):
    """1Cv7.MD streams: the metadata and each module (folder path -> code) with an empty-ish dialog."""
    streams = {"Metadata/Main MetaData Stream": ert.encode_dialog(MD_TEXT)}
    for folder, code in modules.items():
        folder = folder.replace("__", "/")
        streams[f"{folder}/MD Programm text"] = module(code)
        if not folder.startswith("TypedText/"):
            streams[f"{folder}/Dialog Stream"] = dialog("Поле1", columns=("Колонка1",))
    return streams


class MdContextTests(unittest.TestCase):
    """Modules of a 1Cv7.MD read their object's attributes; L7711 runs where the context is known."""

    def lint_md(self, **modules):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "1Cv7.MD"
            path.write_bytes(make_cfb(md_streams(**modules)))
            sources = lint77.load_sources(path)
            report, found = lint(path)
        return {s.module.split("/")[1] if s.module.startswith("TypedText") else s.module.split("/")[0]:
                s.owner for s in sources}, report, found

    def test_owners_of_every_folder(self):
        owners, report, _ = self.lint_md(
            Document__Document_Number238__WorkBook="", TypedText__Transact_Number238="",
            Subconto__Subconto_Number133__WorkBook="", SubFolder__SubFolder_Number112__WorkBook="",
            SubList__SubList_Number132__WorkBook="", Journal__Journal_Number479__WorkBook="",
            Report__Report_Number370__WorkBook="", TypedText__ModuleText_Number1="")
        self.assertEqual(owners, {
            "Document": ("Документ", "Выписка"), "Transact_Number238": ("Документ", "Выписка"),
            "Subconto": ("Справочник", "Контрагенты"), "SubFolder": ("Справочник", "Договоры"),
            "SubList": ("Справочник", "Контрагенты"), "Journal": ("Журнал", "Банк"),
            "Report": None, "ModuleText_Number1": None})
        self.assertEqual(report["md_context_modules"], 8)

    def test_attributes_of_the_owner_are_declared(self):
        _, _, found = self.lint_md(
            Document__Document_Number238__WorkBook="Процедура П()\r\nХ = Сотрудник + НомерДок + Поле1 + Сумма"
                                                   " + Комментарий + Колонка1;\r\nХ = Нет77;\r\nКонецПроцедуры",
            TypedText__Transact_Number238="Процедура ОбработкаПроведения()\r\nХ = Автор + ДатаДок;\r\nХ = Нет77;\r\n"
                                          "КонецПроцедуры",
            Subconto__Subconto_Number133__WorkBook="Процедура П()\r\nХ = ИНН + Код + Наименование;\r\nХ = Нет77;\r\n"
                                                   "КонецПроцедуры",
            SubList__SubList_Number132__WorkBook="Процедура П()\r\nХ = ОсновнойДоговор + Колонка1;\r\nХ = Нет77;\r\n"
                                                 "КонецПроцедуры",
            Journal__Journal_Number479__WorkBook="Процедура П()\r\nХ = ТекущийДокумент;\r\nХ = Нет77;\r\nКонецПроцедуры")
        self.assertEqual(sorted((folder, line) for folder, line, rule, _ in found if rule == "L7711"), [
            ("Document", 3), ("Journal", 3), ("SubList", 3), ("Subconto", 3), ("TypedText", 3)])

    def test_unmodelled_forms_and_the_global_module(self):
        _, report, found = self.lint_md(
            Operation__Operation_Number2__WorkBook="Процедура П()\r\nХ = Дебет;\r\nКонецПроцедуры",
            TypedText__ModuleText_Number1="Перем глПеременная Экспорт;\r\nПроцедура П()\r\nХ = глПеременная + Нет77;"
                                          "\r\nКонецПроцедуры")
        self.assertEqual([(folder, line) for folder, line, _, _ in found], [("TypedText", 3)])
        self.assertEqual(report["md_context_modules"], 1)

    def test_l7711_is_an_error_with_the_configurations_global_module(self):
        # Task 022 (series 0; the owner's decision of 22.10.2026): with the global module of its own 1Cv7.MD the
        # context is complete — 1C does not compile the module; without it the read stays a warning.
        form = "Процедура П()\r\nХ = Нет77;\r\nКонецПроцедуры"
        levels = lambda report: [(d["module"].split("/")[0], d["severity"]) for d in report["diagnostics"]
                                 if d["rule"] == "L7711"]
        _, report, _ = self.lint_md(Document__Document_Number238__WorkBook=form,
                                    TypedText__ModuleText_Number1="Перем глВерсия Экспорт;")
        self.assertEqual(levels(report), [("Document", "error")])
        self.assertIn("1С такой модуль не компилирует", next(d["message"] for d in report["diagnostics"]
                                                              if d["rule"] == "L7711"))
        _, report, _ = self.lint_md(Document__Document_Number238__WorkBook=form)
        self.assertEqual(levels(report), [("Document", "warning")])

    def test_reference_attributes_of_the_owner_lead_on(self):
        _, _, found = self.lint_md(
            TypedText__Transact_Number238="Процедура П()\r\nХ = Сотрудник.Должность + Автор.Нет;\r\n"
                                          "Если Метаданные.Справочник(\"Сотрудники\").Реквизит(\"Пол\").Выбран() = 1 "
                                          "Тогда Х = Сотрудник.Пол; КонецЕсли;\r\nХ = Основание.Нет + Вид.Нет;\r\n"
                                          "Сотрудник = 1; Х = Сотрудник.Нет;\r\nКонецПроцедуры")
        self.assertEqual([(line, rule, head) for _, line, rule, head in found],
                         [(2, "L7714", "Автор.Нет"), (5, "L7714", "Сотрудник.Нет")])

    def test_a_local_hides_the_attribute(self):
        _, _, found = self.lint_md(
            TypedText__Transact_Number238="Процедура П(Сотрудник)\r\nХ = Сотрудник.Нет;\r\nКонецПроцедуры\r\n"
                                          "Процедура Д()\r\nПерем Сотрудник;\r\nХ = Сотрудник.Нет;\r\nКонецПроцедуры")
        self.assertEqual(found, [])

    def test_messages_name_the_owner(self):
        _, _, found = self.lint_md(TypedText__Transact_Number238="Х = Сотрудник.Нет;")
        self.assertEqual(found, [("TypedText", 1, "L7714", "Сотрудник.Нет")])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "1Cv7.MD"
            path.write_bytes(make_cfb(md_streams(TypedText__Transact_Number238="Х = Сотрудник.Нет;")))
            message, = [d["message"] for d in lint77.analyze(lint77.load_sources(path))["diagnostics"]]
        self.assertIn("у объекта Справочник.Сотрудники (реквизит Сотрудник)", message)
        self.assertIn("Сотрудник — реквизит Документ.Выписка, чей это модуль", message)


class DateLiteralTests(unittest.TestCase):
    """'01.01.2000' is one token: 'ОК' in a Торговля+Склад processing is no name."""

    def test_date_literal_is_a_token(self):
        tokens, _ = lint77.lex(lint77.Source("t.1s", "", "Х = '01.01.2000' + 'ОК'; У = '"))
        self.assertEqual([(t.kind, t.text) for t in tokens],
                         [("id", "Х"), ("punct", "="), ("date", "'01.01.2000'"), ("punct", "+"), ("date", "'ОК'"),
                          ("punct", ";"), ("id", "У"), ("punct", "="), ("punct", "'")])

    def test_word_in_quotes_is_no_undeclared_name(self):
        source = lint77.Source("t.1s", "", "Процедура П()\r\nОтвет = Вопрос(\"Нет кассы\", 'ОК', 60);\r\nКонецПроцедуры",
                               dialog=frozenset())
        self.assertEqual([d for d in lint77.analyze([source])["diagnostics"] if d["rule"] == "L7711"], [])


if __name__ == "__main__":
    unittest.main()
