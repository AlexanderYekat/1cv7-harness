"""Task 019: attributes of objects in module code (L7714) and Метаданные guards of L7712-L7714.

Expected outcomes follow the native probes on 1C 7.7.027 (docs/tasks/019-attributes-acceptance.md):
a missing attribute loads and fails when the line runs, a Метаданные check answers 0 for it.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness77 import ert_module as ert
from harness77 import lint77
from harness77 import metadata77

from test_lint77_metadata import make_md_with_module
from test_metadata77 import make_md


def record(number, name, code="S", kind=0, size=10):
    """An attribute record as 1Cv7.MD has it: name, type code at 4, kind number at 7."""
    fields = [str(number), name, "", "", code, "0", "0", str(kind)]
    return "{" + ",".join(f'"{x}"' for x in fields + ["0"] * (size - len(fields))) + "}"


def section(name, *records):
    return "{" + ",\r\n".join([f'"{name}"', *records]) + "}"


ATTRIBUTE_TEXT = (
    '{\r\n{"MainDataContDef","48514","10011","7120"},\r\n'
    '{"TaskItem",\r\n{"1","Тестовая конфигурация","7.70.431","","","1","493","0","0","493"}},\r\n'
    + section("GenJrnlFldDef", record(475, "Комментарий", size=11), record(74, "Автор", "B", 208, 11)) + ',\r\n'
    '{"Consts",\r\n{"15","АдресОрганизации","","","S","240","0","0","0","0","0"}},\r\n'
    '{"SbCnts",\r\n'
    '{"133","Контрагенты","","","0",\r\n'
    + section("Params", record(66, "ИНН", size=17), record(67, "ОсновнойДоговор", "B", 112, 17)) + ',\r\n{"Form"}},\r\n'
    '{"112","Договоры","","","133",\r\n' + section("Params", record(68, "Срок", "D", size=17)) + ',\r\n{"Form"}},\r\n'
    '{"208","Сотрудники","","","0",\r\n' + section("Params", record(69, "Должность", size=17)) + ',\r\n{"Form"}}},\r\n'
    '{"Registers",\r\n{"639","ОстаткиТоваров","","","0"," ","0","0",\r\n'
    + section("Props", record(641, "Товар", "B", 133, 12)) + ',\r\n'
    + section("Figures", record(644, "Количество", "N")) + ',\r\n'
    + section("Flds", record(686, "Цена", "N", size=11)) + '}},\r\n'
    '{"Documents",\r\n{"238","Выписка","","","8",\r\n{"22314","","","",\r\n{"Refers"}},\r\n'
    + section("Head Fields", record(13025, "Сотрудник", "B", 208), record(13026, "Основание", "O", 0),
              record(13027, "Вид", "E", 21439)) + ',\r\n'
    + section("Table Fields", record(13043, "Сумма", "N", size=11)) + '}},\r\n'
    '{"EnumList",\r\n{"21439","Пол","","",\r\n{"EnumVal",\r\n{"21437","Мужской","",""}}}},\r\n'
    '{"Buh",\r\n{"2","","","",\r\n{"Plans"}}}}'
)


def metadata(text=ATTRIBUTE_TEXT):
    return lint77.base_metadata(metadata77.Metadata(make_md(text)))


def analyze(text, *, md=True, strict=False, dialog=None, allow=()):
    source = lint77.Source("test.1s", "", text, dialog=dialog, metadata=metadata() if md else None)
    return lint77.analyze([source], allow=allow, strict=strict)


def found(text, rule="L7714", **kwargs):
    return [(d["line"], d["column"], d["severity"]) for d in analyze(text, **kwargs)["diagnostics"]
            if d["rule"] == rule]


def lines(*items):
    return "\r\n".join(items)


CATALOG = 'Спр = СоздатьОбъект("Справочник.Контрагенты");'


class MetadataAttributeTests(unittest.TestCase):
    """metadata77 reads the attributes of catalogs, documents (with the common ones) and registers."""

    def names(self, cls, kind):
        return sorted(a.name for a in metadata().attributes(cls, kind).values())

    def test_attributes_of_each_class(self):
        self.assertEqual(self.names("Справочник", "Контрагенты"), ["ИНН", "ОсновнойДоговор"])
        self.assertEqual(self.names("Документ", "ВЫПИСКА"), ["Автор", "Вид", "Комментарий", "Основание",
                                                              "Сотрудник", "Сумма"])
        self.assertEqual(self.names("Регистр", "ОстаткиТоваров"), ["Количество", "Товар", "Цена"])
        self.assertEqual(self.names("Справочник", "Сотрудники"), ["Должность"])
        self.assertIsNone(metadata().attributes("Справочник", "Нет"))

    def test_reference_attributes_name_their_kind(self):
        document = metadata().attributes("Документ", "Выписка")
        self.assertEqual(document["сотрудник"].target, ("Справочник", "Сотрудники"))
        self.assertEqual(document["автор"].target, ("Справочник", "Сотрудники"))
        # Any document (number 0) and an enumeration lead nowhere; a string has no kind.
        self.assertIsNone(document["основание"].target)
        self.assertEqual((document["вид"].code, document["вид"].kind), ("E", "Пол"))
        self.assertIsNone(document["вид"].target)
        self.assertIsNone(document["сумма"].kind)

    def test_unknown_attribute_record_refuses_the_analysis_but_not_the_form_metadata(self):
        cases = {"SbCnts Контрагенты Params": record(66, "ИНН", size=17).replace('"S"', '"X"'),
                 "SbCnts Контрагенты Params ": '{"66","ИНН"}'}
        for where, broken in cases.items():
            text = ATTRIBUTE_TEXT.replace(record(66, "ИНН", size=17), broken)
            md = metadata77.Metadata(make_md(text))
            self.assertEqual(md.number("B", "Контрагенты"), 133)
            with self.subTest(where=where), self.assertRaisesRegex(
                    ert.ErtError, f"неизвестная запись реквизита в разделе {where.strip()}"):
                lint77.base_metadata(md)

    def test_repeated_attribute_names_are_refused(self):
        cases = {"в таблице и шапке": ATTRIBUTE_TEXT.replace(record(13043, "Сумма", "N", size=11),
                                                           record(13043, "сотрудник", "N", size=11)),
                 "общий и шапки": ATTRIBUTE_TEXT.replace(record(475, "Комментарий", size=11),
                                                        record(475, "Основание", size=11))}
        for name, text in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ert.ErtError, "Documents Выписка повторяется имя"):
                metadata(text)
        twice = ATTRIBUTE_TEXT.replace('{"Form"}},\r\n{"112"', section("Params") + '},\r\n{"112"')
        with self.assertRaisesRegex(ert.ErtError, "в записи SbCnts Контрагенты повторяется список реквизитов"):
            metadata(twice)


class AttributeRuleTests(unittest.TestCase):
    """L7714: an attribute of an object СоздатьОбъект made that the base's metadata lack."""

    def test_missing_attributes_are_reported_at_the_name(self):
        cases = {
            lines(CATALOG, "Х = Спр.Нет;"): (2, 9),
            lines(CATALOG, "Спр.Нет = 1;"): (2, 5),
            lines('Док = СоздатьОбъект("Документ.Выписка");', "Х = Док.Нет;"): (2, 9),
            lines('Рег = СоздатьОбъект("Регистр.ОстаткиТоваров");', "Х = Рег.Нет;"): (2, 9),
            lines('Док = CreateObject("Документ.Выписка");', "Х = Док.Сотрудник.Нет;"): (2, 19),
            lines(CATALOG, "Х = Спр.ОсновнойДоговор.Нет;"): (2, 25),
            lines('Рег = СоздатьОбъект("Регистр.ОстаткиТоваров");', "Х = Рег.Товар.ОсновнойДоговор.Нет;"): (2, 31),
        }
        for text, position in cases.items():
            with self.subTest(text=text):
                self.assertEqual(found(text), [(*position, "warning")])

    def test_message_names_the_object_the_base_and_the_assignment(self):
        message, = [d["message"] for d in analyze(lines("", 'Док = СоздатьОбъект("Документ.Выписка");',
                                                        "Х = Док.Сотрудник.Нет;"))["diagnostics"]]
        self.assertIn("Док.Сотрудник.Нет: у объекта Справочник.Сотрудники (реквизит Сотрудник)", message)
        self.assertIn("Тестовая конфигурация", message)
        self.assertIn('Док — СоздатьОбъект("Документ.Выписка") в строке 2', message)
        self.assertIn("«Поле агрегатного объекта не обнаружено (Нет)»", message)

    def test_existing_builtin_and_method_names_are_silent(self):
        text = lines(CATALOG, 'Док = СоздатьОбъект("Документ.Выписка");',
                     'Рег = СоздатьОбъект("Регистр.ОстаткиТоваров");',
                     "Х = Спр.ИНН + Спр.инн + Спр.Код + Спр.Description + Спр.Родитель.Нет + Спр.Владелец;",
                     "Х = Спр.ОсновнойДоговор.Срок + Спр.ОсновнойДоговор.Наименование;",
                     "Х = Док.Сумма + Док.Комментарий + Док.Автор.Должность + Док.НомерДок + Док.DocDate;",
                     "Х = Док.Основание.Нет + Док.Вид.Нет + Док.Сумма.Нет;",
                     "Х = Рег.Товар.ИНН + Рег.Количество + Рег.Цена + Рег.Приход;",
                     "Спр.ВыбратьЭлементы(); Х = Спр.ТекущийЭлемент().Нет; Х = Спр.Нет();")
        report = analyze(text)
        self.assertEqual([d for d in report["diagnostics"] if d["rule"] == "L7714"], [])
        self.assertEqual(report["attributes_checked"], 24)

    def test_names_that_may_hold_another_value_are_not_followed(self):
        cases = [
            lines("Процедура П(Спр)", CATALOG, "Х = Спр.Нет;", "КонецПроцедуры"),
            lines("Процедура П()", "Для Спр = 1 По 2 Цикл КонецЦикла;", CATALOG, "Х = Спр.Нет;", "КонецПроцедуры"),
            lines("Процедура Заполнить(Знач)", "КонецПроцедуры", "Процедура П()", CATALOG, "Заполнить(Спр);",
                  "Х = Спр.Нет;", "КонецПроцедуры"),
            lines(CATALOG, 'Если 1 = 1 Тогда Спр = СоздатьОбъект("Справочник.Договоры"); КонецЕсли;', "Х = Спр.Нет;"),
            lines(CATALOG, "Спр = Спр.ТекущийЭлемент();", "Х = Спр.Нет;"),
            lines('Спр = СоздатьОбъект("Справочник.Контрагенты").ТекущийЭлемент();', "Х = Спр.Нет;"),
            lines('Спр = СоздатьОбъект("Справочник.Нет");', "Х = Спр.Нет;"),
            lines('Спр = СоздатьОбъект("Документ");', "Х = Спр.Нет;"),
            lines('Спр = СоздатьОбъект("Справочник.Контрагенты.ФормаСписка");', "Х = Спр.Нет;"),
            lines("Перем Спр Экспорт;", "Процедура П()", "Х = Спр.Нет;", "КонецПроцедуры", CATALOG),
            lines("Перем Спр;", "Процедура П()", CATALOG, "КонецПроцедуры",
                  "Процедура Д()", 'Спр = СоздатьОбъект("Справочник.Договоры");', "КонецПроцедуры", "Х = Спр.Нет;"),
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(found(text), [])
        self.assertEqual(found(lines("Процедура П()", CATALOG, "Х = Спр.Нет;", "КонецПроцедуры"), allow=["Спр"]), [])
        self.assertEqual(found(lines("Процедура П()", CATALOG, "Х = Спр.Нет;", "КонецПроцедуры"),
                               dialog=frozenset({"спр"})), [])

    def test_own_procedure_named_like_the_platform_function_makes_nothing_known(self):
        text = lines("Функция СоздатьОбъект(Имя)", "Возврат Имя;", "КонецФункции",
                     "Процедура П()", CATALOG, "Х = Спр.Нет;", "КонецПроцедуры")
        self.assertEqual(found(text), [])

    def test_module_variables_and_scopes(self):
        # A module variable assigned in the main program is the object in every procedure.
        text = lines("Перем Спр;", "Процедура П()", "Х = Спр.Нет;", "КонецПроцедуры", CATALOG)
        self.assertEqual(found(text), [(3, 9, "warning")])
        # A local Перем hides the module variable; locals of two procedures are different names.
        text = lines("Перем Спр;", "Процедура П()", "Перем Спр;", CATALOG, "Х = Спр.Нет;", "КонецПроцедуры",
                     "Процедура Д()", 'Спр = СоздатьОбъект("Справочник.Договоры");', "Х = Спр.Срок;", "КонецПроцедуры")
        self.assertEqual(found(text), [(5, 9, "warning")])
        text = lines("Процедура П()", CATALOG, "КонецПроцедуры", "Процедура Д()", "Х = Спр.Нет;", "КонецПроцедуры")
        self.assertEqual(found(text), [])

    def test_strict_makes_errors_and_no_metadata_no_check(self):
        text = lines(CATALOG, "Х = Спр.Нет;")
        self.assertEqual(found(text, strict=True), [(2, 9, "error")])
        self.assertEqual(found(text, md=False), [])
        self.assertEqual(analyze(text, md=False)["attributes_checked"], 0)


class GuardTests(unittest.TestCase):
    """Inside an Если whose condition checks the name in Метаданные, L7712-L7714 stay silent."""

    def test_guarded_names_in_every_branch(self):
        create = 'О = СоздатьОбъект("Справочник.Нет");'
        cases = [
            f'Если Метаданные.Справочник("Нет").Выбран() = 1 Тогда {create} КонецЕсли;',
            f'Если Метаданные.Справочник("нет").Выбран() = 0 Тогда Х = 1; Иначе {create} КонецЕсли;',
            f'Если 1 = 0 Тогда Х = 1; ИначеЕсли Метаданные.Справочник("Нет").Выбран() = 1 Тогда {create} КонецЕсли;',
            f'Если (Метаданные.Справочник("Нет").Выбран() = 1) И (1 = 1) Тогда Если 1 = 1 Тогда {create} '
            'КонецЕсли; КонецЕсли;',
        ]
        for text in cases:
            with self.subTest(text=text):
                report = analyze(text)
                self.assertEqual([d["rule"] for d in report["diagnostics"]], [])
                self.assertEqual(report["metadata_guarded"], 1)

    def test_lines_outside_the_statement_and_other_names_are_reported(self):
        text = lines('Если Метаданные.Справочник("Нет").Выбран() = 1 Тогда Х = 1; КонецЕсли;',
                     'О = СоздатьОбъект("Справочник.Нет");',
                     'Если Метаданные.Справочник("Другой").Выбран() = 1 Тогда О = СоздатьОбъект("Справочник.Нет"); '
                     'КонецЕсли;',
                     'Если Метаданные.Документ("Нет").Выбран() = 1 Тогда О = СоздатьОбъект("Справочник.Нет"); КонецЕсли;',
                     'Если 1 = 1 Тогда Х = Метаданные.Справочник("Нет").Выбран(); О = СоздатьОбъект("Справочник.Нет"); '
                     'КонецЕсли;')
        self.assertEqual([d["line"] for d in analyze(text)["diagnostics"] if d["rule"] == "L7713"], [2, 3, 4, 5])

    def test_global_attributes_and_attributes(self):
        cases = {
            'Если Метаданные.Константа("Нет").Выбран() = 1 Тогда Х = Константа.Нет; КонецЕсли;': "L7712",
            'Если Метаданные.Перечисление("Нет").Выбран() = 1 Тогда Х = Перечисление.Нет.А; КонецЕсли;': "L7712",
            'Если Метаданные.Перечисление("Пол").Значение("Средний").Выбран() = 1 Тогда '
            'Х = Перечисление.Пол.Средний; КонецЕсли;': "L7712",
            lines(CATALOG, 'Если Метаданные.Справочник("Контрагенты").Реквизит("Нет").Выбран() = 1 Тогда '
                  'Х = Спр.Нет; КонецЕсли;'): "L7714",
            lines('Док = СоздатьОбъект("Документ.Выписка");', 'Если Метаданные.Документ("Выписка")'
                  '.РеквизитШапки("Нет").Выбран() = 1 Тогда Док.Нет = 1; КонецЕсли;'): "L7714",
            lines('Док = СоздатьОбъект("Документ.Выписка");', 'Если Метаданные.ОбщийРеквизитДокумента("Нет")'
                  '.Выбран() = 1 Тогда Док.Нет = 1; КонецЕсли;'): "L7714",
        }
        for text, rule in cases.items():
            with self.subTest(text=text):
                report = analyze(text)
                self.assertEqual(report["diagnostics"], [])
                self.assertEqual(report["metadata_guarded"], 1)
        # The kind alone does not guard a value or an attribute of a kind the base has.
        text = 'Если Метаданные.Перечисление("Пол").Выбран() = 1 Тогда Х = Перечисление.Пол.Средний; КонецЕсли;'
        self.assertEqual(found(text, "L7712"), [(1, 77, "warning")])
        text = lines(CATALOG, 'Если Метаданные.Справочник("Контрагенты").Выбран() = 1 Тогда Х = Спр.Нет; КонецЕсли;')
        self.assertEqual(found(text), [(2, 70, "warning")])


class ForeignBaseTests(unittest.TestCase):
    """A global function called through another object belongs to that object's base (V77.CreateObject)."""

    def test_global_functions_through_an_object_are_not_checked(self):
        text = lines('V77 = CreateObject("V77.Application");', 'Спр = V77.CreateObject("Справочник.Нет");',
                     'Спр = База.СоздатьОбъект("Справочник.Нет"); База.ОткрытьФорму("Отчет.Нет");',
                     "Х = Спр.Нет;")
        self.assertEqual([d["rule"] for d in analyze(text)["diagnostics"]], [])

    def test_methods_are_checked_as_before(self):
        text = lines('ТЗ = СоздатьОбъект("ТаблицаЗначений");', 'ТЗ.НоваяКолонка("К", "Справочник.Нет");',
                     'Конт.ОткрытьПодбор("Справочник.Нет");', 'О = СоздатьОбъект("Справочник.Нет");')
        self.assertEqual([(d["rule"], d["line"]) for d in analyze(text)["diagnostics"]],
                         [("L7713", 2), ("L7713", 3), ("L7713", 4)])


class ContextTests(unittest.TestCase):
    """CLI and the modules of a 1Cv7.MD; the report counts what L7714 compared and what guards left out."""

    def test_cli_reports_the_attribute_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "1Cv7.MD").write_bytes(make_md(ATTRIBUTE_TEXT))
            (folder / "m.1s").write_text(lines(CATALOG, "Х = Спр.Нет + Спр.ИНН;",
                                               'Если Метаданные.Константа("Нет").Выбран() = 1 Тогда '
                                               'Х = Константа.Нет; КонецЕсли;'), encoding="utf-8")
            completed = subprocess.run([sys.executable, "-m", "harness77", "lint", str(folder / "m.1s"), "--metadata",
                                        str(folder / "1Cv7.MD"), "--format", "json"],
                                       capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["version"], "0.4.0")
        self.assertEqual([d["rule"] for d in report["diagnostics"]], ["L7714"])
        self.assertEqual((report["attributes_checked"], report["metadata_guarded"]), (2, 1))

    def test_modules_of_a_1cv7_md_check_attributes_on_its_own_metadata(self):
        module = lines(CATALOG, "Х = Спр.Нет;")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "1Cv7.MD"
            path.write_bytes(make_md_with_module(module, ATTRIBUTE_TEXT))
            report = lint77.analyze(lint77.load_sources(path))
        self.assertEqual([(d["rule"], d["line"]) for d in report["diagnostics"]], [("L7714", 2)])

    def test_broken_attribute_record_is_refused_by_the_cli(self):
        text = ATTRIBUTE_TEXT.replace(record(66, "ИНН", size=17), '{"66","ИНН"}')
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "1Cv7.MD").write_bytes(make_md(text))
            (folder / "m.1s").write_text("Х = 1;", encoding="utf-8")
            completed = subprocess.run([sys.executable, "-m", "harness77", "lint", str(folder / "m.1s"), "--metadata",
                                        str(folder / "1Cv7.MD")], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("неизвестная запись реквизита", completed.stderr)


if __name__ == "__main__":
    unittest.main()
