"""Object names of a 1Cv7.MD for reference-typed form fields (tasks 012, 013)."""

import struct
import unittest

from harness77 import ert_module as ert
from harness77 import metadata77
from test_ert_dialog import base_container

# The sections of the base-for-test survey, in its layout, with its numbers.
MD_TEXT = (
    '{\r\n{"MainDataContDef","48514","10011","7120"},\r\n'
    '{"TaskItem",\r\n{"1","Тестовая конфигурация","7.70.431","","","1","493","0","0","493"}},\r\n'
    '{"SbCnts",\r\n{"133","Контрагенты","","","0"},\r\n{"208","Сотрудники","","Сотрудники","0"}},\r\n'
    '{"Documents",\r\n{"238","Выписка","","","8",\r\n{"Head Fields"}}},\r\n'
    '{"EnumList",\r\n{"21439","Пол","","",\r\n{"EnumVal",\r\n{"21437","Мужской","",""},\r\n'
    '{"21438","Женский","",""}}}},\r\n'
    '{"Buh",\r\n{"2","","","",\r\n{"AccParams"},\r\n{"Plans",\r\n{"809","Основной","","","###.##.#","###.##.#",\r\n'
    '{"Accounts"}}},\r\n{"SbKind",\r\n{"518","Контрагенты","","","B","0","0","133"}}}}}'
)


# The copy FIO.ERT carries: configuration «Задача» without objects (196 of 416 corpus forms).
EMPTY_TEXT = ('{\r\n{"MainDataContDef","12","10011","7120"},\r\n{"TaskItem",\r\n{"1","Задача","","","","1","0","0",'
              '"1","0"}},\r\n{"SbCnts"},\r\n{"Documents"},\r\n{"EnumList"},\r\n{"Buh",\r\n{"2","","",\r\n{"Plans"}}}}')


def renamed(data, index, name):
    """The test container with directory entry index renamed."""
    data = bytearray(data)
    entry = 512 + 128 * index
    encoded = (name + "\0").encode("utf-16le")
    data[entry:entry + 64] = encoded.ljust(64, b"\0")
    struct.pack_into("<H", data, entry + 64, len(encoded))
    return bytes(data)


def make_md(text=MD_TEXT, name=metadata77.STREAM):
    """A CFB whose second stream is the Main MetaData Stream (the others are ERT streams)."""
    compound = ert.CompoundFile(renamed(base_container(), 2, name))
    return compound.rebuild({2: ert.encode_dialog(text)})


def make_ert_with_copy(dialog_text, copy_text=EMPTY_TEXT, module="Процедура Пусто()\r\nКонецПроцедуры\r\n"):
    """An ERT whose third stream is its copy of the metadata, with the NUL byte after the text."""
    compound = ert.CompoundFile(renamed(base_container(), 3, metadata77.STREAM))
    return compound.rebuild({1: ert.compress_module(module.encode("cp1251")), 2: ert.encode_dialog(dialog_text),
                             3: ert.encode_dialog(copy_text) + b"\0"})


def other_md():
    """Another configuration: the same names under other numbers."""
    return make_md(MD_TEXT.replace('"133","Контрагенты"', '"150","Контрагенты"')
                   .replace('"809","Основной"', '"901","Основной"').replace("Тестовая", "Другая"))


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.metadata = metadata77.Metadata(make_md())

    def test_identity(self):
        self.assertEqual(self.metadata.configuration, "Тестовая конфигурация")
        self.assertEqual(self.metadata.sha256, metadata77.sha256(make_md()))
        self.assertEqual(self.metadata.public()["configuration"], "Тестовая конфигурация")

    def test_names_of_every_section(self):
        self.assertEqual(self.metadata.names, {("B", 133): "Контрагенты", ("B", 208): "Сотрудники",
                                               ("O", 238): "Выписка", ("E", 21439): "Пол",
                                               ("T", 809): "Основной"})

    def test_resolve(self):
        cases = {"Справочник.Контрагенты": ("B", 133, "Справочник.Контрагенты"),
                 "справочник.КОНТРАГЕНТЫ": ("B", 133, "Справочник.Контрагенты"),
                 "Справочник": ("B", 0, "Справочник"), "Документ": ("O", 0, "Документ"),
                 "Документ.Выписка": ("O", 238, "Документ.Выписка"),
                 "Перечисление.Пол": ("E", 21439, "Перечисление.Пол"),
                 "Счет": ("T", 0, "Счет"), "Счет.Основной": ("T", 809, "Счет.Основной"),
                 "ВидСубконто": ("K", 0, "ВидСубконто"), "ПланСчетов": ("P", 0, "ПланСчетов")}
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.metadata.resolve(name), expected)

    def test_number_by_name_ignores_case(self):
        self.assertEqual(self.metadata.number("B", "контрагенты"), 133)
        self.assertEqual(self.metadata.number("O", "Выписка"), 238)
        self.assertIsNone(self.metadata.number("B", "Выписка"))
        self.assertIsNone(self.metadata.number("B", "Номенклатура"))

    def test_refusals(self):
        cases = {"Склад.Основной": "неизвестный ссылочный тип", "Перечисление": "без вида",
                 "ВидСубконто.Контрагенты": "нет видов", "ПланСчетов.Основной": "нет видов",
                 "Справочник.": "имя вида", "Справочник.Номенклатура": "нет объекта Справочник.Номенклатура",
                 "Документ.Контрагенты": "нет объекта", "Счёт.Основной": "неизвестный"}
        for name, message in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ert.ErtError, message):
                self.metadata.resolve(name)

    def test_type_names(self):
        self.assertEqual(metadata77.type_name("B", 133, self.metadata), "Справочник.Контрагенты")
        self.assertEqual(metadata77.type_name("B", 0), "Справочник")
        self.assertEqual(metadata77.type_name("T", 809, self.metadata), "Счет.Основной")
        self.assertEqual(metadata77.type_name("K", 0), "ВидСубконто")
        for code, number, metadata in (("B", 133, None), ("B", 25507, self.metadata), ("E", 0, self.metadata),
                                       ("K", 518, self.metadata), ("S", 0, None)):
            with self.subTest(code=code, number=number):
                self.assertIsNone(metadata77.type_name(code, number, metadata))

    def test_copy_carried_by_an_ert(self):
        compound = ert.CompoundFile(make_ert_with_copy('{"Dialogs"}', MD_TEXT))
        copy = metadata77.Metadata.of_ert(compound)
        self.assertEqual(copy.names, self.metadata.names)
        self.assertEqual(copy.sha256, metadata77.sha256(ert.encode_dialog(MD_TEXT) + b"\0"))
        self.assertIn("копия метаданных ERT (Тестовая конфигурация", copy.describe())
        self.assertIn("1Cv7.MD (Тестовая конфигурация", self.metadata.describe())
        self.assertIsNone(metadata77.Metadata.of_ert(ert.CompoundFile(make_md(name="Other Stream"))))
        empty = metadata77.Metadata.of_ert(ert.CompoundFile(make_ert_with_copy('{"Dialogs"}')))
        self.assertEqual((empty.configuration, empty.names), ("Задача", {}))

    def test_ert_stream_ends_with_nul_once(self):
        stream = ert.encode_dialog(MD_TEXT)
        self.assertEqual(self.metadata.stream, stream)
        self.assertEqual(self.metadata.ert_stream(), stream + b"\0")
        copy = metadata77.Metadata.of_ert(ert.CompoundFile(make_ert_with_copy('{"Dialogs"}', MD_TEXT)))
        self.assertEqual(copy.ert_stream(), stream + b"\0")

    def test_not_metadata_refused(self):
        cases = {"OLE": b"plain bytes", "ровно один поток": make_md(name="Other Stream"),
                 "MainDataContDef": make_md(MD_TEXT.replace("MainDataContDef", "Other")),
                 "повторяется": make_md(MD_TEXT.replace('"208","Сотрудники"', '"208","Контрагенты"')),
                 "неизвестная запись": make_md(MD_TEXT.replace('{"208","Сотрудники"', '{"x","Сотрудники"'))}
        for message, data in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ert.ErtError, message):
                metadata77.Metadata(data)


if __name__ == "__main__":
    unittest.main()
