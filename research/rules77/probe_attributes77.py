"""Native probes for object attributes in module code (L7714) and Метаданные guards through `harness77 run`; task 019.

The same infrastructure as probe_metadata77: every case is one cooperating external
processing whose construct runs in Harness77Контроль inside Попытка; the load tells the
compile outcome, `runtime-error:` or `value:` the run outcome. Expectations are fixed
here, before the run ("ok", "error", "?"). Objects are made by СоздатьОбъект and Новый()
and never written. Two batch cases check the reading of the attributes: 1C lists the
attributes of each catalog and document (n-attributes) and reads every attribute read
from 1Cv7.MD (a-attributes).

Usage (local stand profile, base-for-test, the FIO.ERT template):
  python research/rules77/probe_attributes77.py --stand .local/stage14-native/stand.toml
      --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --metadata .local/bases/base-for-test/1Cv7.MD
      --work .local/stage19-native --evidence .artifacts/stage19-attribute-probes-YYYYMMDD.json
"""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))

from probe_metadata77 import arguments, assign_chunks, judge, run_cases, run_line, select  # noqa: E402

CATALOG = "    Спр77 = СоздатьОбъект(\"Справочник.Банки\");\n"
NEW_CATALOG = CATALOG + "    Спр77.Новый();\n"
NEW_DOCUMENT = "    Док77 = СоздатьОбъект(\"Документ.АвансовыйОтчет\");\n    Док77.Новый();\n"
MISSING = dict(compile="?", runtime="error")


def guarded(condition, statement, otherwise=""):
    """An Если on the probe line whose branch holds the construct; 42 when no line fails."""
    branch = f" Иначе {otherwise}" if otherwise else ""
    return run_line(f"Если {condition} Тогда {statement}{branch} КонецЕсли;")


# Метаданные checks of names present and missing; each in its own Попытка ("E" if it fails).
CHECKS = [("Метаданные.Справочник(\"Нет77\").Выбран()", "0"),
          ("Метаданные.Справочник(\"Банки\").Реквизит(\"Нет77\").Выбран()", "0"),
          ("Метаданные.Справочник(\"Банки\").Реквизит(\"КоррСчет\").Выбран()", "1"),
          ("Метаданные.Документ(\"АвансовыйОтчет\").РеквизитШапки(\"Нет77\").Выбран()", "0"),
          ("Метаданные.Документ(\"АвансовыйОтчет\").РеквизитТабличнойЧасти(\"КомуЗаЧто\").Выбран()", "1"),
          ("Метаданные.ОбщийРеквизитДокумента(\"Нет77\").Выбран()", "0"),
          ("Метаданные.ОбщийРеквизитДокумента(\"Комментарий\").Выбран()", "1"),
          ("Метаданные.Константа(\"Нет77\").Выбран()", "0"),
          ("Метаданные.Перечисление(\"Булево\").Значение(\"Нет77\").Выбран()", "0")]
GUARD_VALUES = "    Ответ77 = \"\";\n" + "\n".join(
    f"    Попытка Ответ77 = Ответ77 + \",\" + {check}; Исключение Ответ77 = Ответ77 + \",E\"; КонецПопытки;"
    for check, _ in CHECKS) + f" {run_line('', '    Возврат Сред(Ответ77, 2);').strip()}"

CASES = [
    # L7714, a catalog object.
    dict(id="r-catalog", rule="L7714", control=CATALOG + run_line("З77 = Спр77.Нет77;"), **MISSING),
    dict(id="r-catalog-write", rule="L7714", compile="?", runtime="?", control=CATALOG + run_line("Спр77.Нет77 = 1;")),
    dict(id="r-catalog-new", rule="L7714", control=NEW_CATALOG + run_line("З77 = Спр77.Нет77;"), **MISSING),
    dict(id="r-catalog-control", rule="L7714", compile="ok", runtime="ok", value="42",
         control=NEW_CATALOG + run_line("Спр77.КоррСчет = \"42\";", "    Возврат Спр77.КоррСчет;")),
    dict(id="r-catalog-bare", rule="L7714", compile="ok", runtime="?",
         control=CATALOG + run_line("З77 = Спр77.КоррСчет;", "    Возврат \"[\" + З77 + \"]\";"),
         note="существующий реквизит у объекта без текущего элемента"),
    dict(id="r-catalog-case", rule="L7714", compile="ok", runtime="ok", value="42",
         control=NEW_CATALOG + run_line("Спр77.коррсчет = \"42\";", "    Возврат Спр77.КОРРСЧЕТ;")),
    dict(id="r-catalog-builtin", rule="L7714", compile="ok", runtime="ok", value="42",
         control=NEW_CATALOG + run_line("Спр77.Наименование = \"42\";", "    Возврат Спр77.Description;")),
    dict(id="r-catalog-owner", rule="L7714", compile="ok", runtime="?",
         control=NEW_CATALOG + run_line("З77 = Спр77.Владелец;"), note="Банки не подчинён другому справочнику"),
    dict(id="r-catalog-method", rule="L7714", compile="?", runtime="?",
         control=NEW_CATALOG + run_line("З77 = Спр77.ТекущийЭлемент;"), note="метод без скобок"),
    # L7714, a document object: head, table part, common attributes.
    dict(id="r-document", rule="L7714", control=NEW_DOCUMENT + run_line("З77 = Док77.Нет77;"), **MISSING),
    dict(id="r-document-write", rule="L7714", compile="?", runtime="?",
         control=NEW_DOCUMENT + run_line("Док77.Нет77 = 1;")),
    dict(id="r-document-head", rule="L7714", compile="ok", runtime="ok", value="42",
         control=NEW_DOCUMENT + run_line("Док77.НаименованиеАванса = \"42\";", "    Возврат Док77.НаименованиеАванса;")),
    dict(id="r-document-table", rule="L7714", compile="ok", runtime="ok", value="42",
         control=NEW_DOCUMENT + "    Док77.НоваяСтрока();\n"
         + run_line("Док77.КомуЗаЧто = \"42\";", "    Возврат Док77.КомуЗаЧто;")),
    dict(id="r-document-common", rule="L7714", compile="ok", runtime="ok", value="42",
         control=NEW_DOCUMENT + run_line("Док77.Комментарий = \"42\";", "    Возврат Док77.Комментарий;")),
    dict(id="r-document-builtin", rule="L7714", compile="ok", runtime="ok", value="1",
         control=NEW_DOCUMENT + run_line("З77 = Док77.НомерДок;", "    Возврат ?(З77 = Док77.DocNum, 1, 0);")),
    # A reference attribute leads to its catalog: Сотрудник is Справочник.Сотрудники, empty in a new document.
    dict(id="r-chain", rule="L7714", compile="?", runtime="?", control=NEW_DOCUMENT + run_line("З77 = Док77.Сотрудник.Нет77;")),
    dict(id="r-chain-control", rule="L7714", compile="ok", runtime="?",
         control=NEW_DOCUMENT + run_line("З77 = Док77.Сотрудник.ИНН;", "    Возврат \"[\" + З77 + \"]\";")),
    # Метаданные guards: 1C answers 0 for a missing name, the branch does not run, lint stays silent.
    dict(id="g-values", rule="guard", compile="ok", runtime="ok", value=",".join(v for _, v in CHECKS),
         control=GUARD_VALUES, note="Выбран() имён, которые есть и которых нет"),
    dict(id="g-catalog", rule="L7713", compile="ok", runtime="ok", value="42",
         control=guarded("Метаданные.Справочник(\"Нет77\").Выбран() = 1", "О77 = СоздатьОбъект(\"Справочник.Нет77\");")),
    dict(id="g-attribute", rule="L7714", compile="ok", runtime="ok", value="42",
         control=CATALOG + guarded("Метаданные.Справочник(\"Банки\").Реквизит(\"Нет77\").Выбран() = 1",
                                   "З77 = Спр77.Нет77;")),
    dict(id="g-constant", rule="L7712", compile="ok", runtime="ok", value="42",
         control=guarded("Метаданные.Константа(\"Нет77\").Выбран() = 1", "З77 = Константа.Нет77;")),
    dict(id="g-else", rule="L7713", compile="ok", runtime="ok", value="42",
         control=guarded("Метаданные.Справочник(\"Нет77\").Выбран() = 0", "З77 = 1;",
                         "О77 = СоздатьОбъект(\"Справочник.Нет77\");"),
         note="ветка «есть» — Иначе при условии «= 0»"),
    dict(id="g-after", rule="L7713", compile="ok", runtime="error",
         control="    Если Метаданные.Справочник(\"Нет77\").Выбран() = 1 Тогда З77 = 1; КонецЕсли;\n"
         + run_line("О77 = СоздатьОбъект(\"Справочник.Нет77\");"), note="строка после Если не защищена"),
    # Added after the first lint of the base's own 1Cv7.MD: its modules read attributes its
    # metadata lack (a trimmed test configuration). The objects and names as the modules have them.
    dict(id="c-contract", rule="L7714", compile="ok", runtime="error",
         control="    Дог = СоздатьОбъект(\"Справочник.Договоры\");\n    Дог.Новый();\n"
         + run_line("Если ПустоеЗначение(Дог.ДатаНачалаНачисленияШтрафныхСанкций) = 0 Тогда З77 = 1; КонецЕсли;"),
         note="CalcVar_Number21432, строка 2779"),
    dict(id="c-goods", rule="L7714", compile="ok", runtime="error",
         control="    СпрТовары = СоздатьОбъект(\"Справочник.Номенклатура\");\n    СпрТовары.Новый();\n"
         + run_line("З77 = СпрТовары.БазоваяЕдиница;"), note="CalcVar_Number25505, строка 61"),
]

COMPARE = """Функция Сверить77(Объект77, Факт77, Ожидание77)
    Лишние77 = ""; Нет77 = ""; Ф77 = СтрЗаменить(Факт77, ";", РазделительСтрок);
    О77 = СтрЗаменить(Ожидание77, ";", РазделительСтрок);
    Для Н77 = 1 По СтрКоличествоСтрок(Ф77) Цикл
        И77 = СтрПолучитьСтроку(Ф77, Н77);
        Если ПустаяСтрока(И77) = 0 Тогда
            Всего77 = Всего77 + 1;
            Если Найти(";" + ВРег(Ожидание77) + ";", ";" + ВРег(И77) + ";") = 0 Тогда Лишние77 = Лишние77 + "," + И77; КонецЕсли;
        КонецЕсли;
    КонецЦикла;
    Для Н77 = 1 По СтрКоличествоСтрок(О77) Цикл
        И77 = СтрПолучитьСтроку(О77, Н77);
        Если (ПустаяСтрока(И77) = 0) И (Найти(";" + ВРег(Факт77) + ";", ";" + ВРег(И77) + ";") = 0) Тогда
            Нет77 = Нет77 + "," + И77;
        КонецЕсли;
    КонецЦикла;
    Если ПустаяСтрока(Лишние77 + Нет77) = 1 Тогда Возврат ""; КонецЕсли;
    Возврат "|" + Объект77 + ":лишние=" + Лишние77 + ",нет=" + Нет77;
КонецФункции
"""


def read_attributes(metadata_path):
    from harness77 import metadata77
    metadata = metadata77.load(metadata_path)
    objects = metadata.objects()
    return {cls: {kind: [a.name for a in metadata.attributes(cls, kind).values()]
                  for kind in objects[cls].values()} for cls in ("Справочник", "Документ")}


def names_case(metadata_path):
    """n-attributes: 1C lists the attributes of every catalog and document; differences are listed."""
    found = read_attributes(metadata_path)
    blocks = []
    for kind, names in found["Справочник"].items():
        blocks.append(f"""    Попытка
{assign_chunks("Ож77", names)}
        М77 = Метаданные.Справочник("{kind}"); С77 = "";
        Для Н77 = 1 По М77.Реквизит() Цикл С77 = С77 + ";" + М77.Реквизит(Н77).Идентификатор; КонецЦикла;
        Ответ77 = Ответ77 + Сверить77("Справочник.{kind}", С77, Ож77);
    Исключение
        Ответ77 = Ответ77 + "|Справочник.{kind}:E:" + ОписаниеОшибки();
    КонецПопытки;""")
    for kind, names in found["Документ"].items():
        blocks.append(f"""    Попытка
{assign_chunks("Ож77", names)}
        М77 = Метаданные.Документ("{kind}"); С77 = Общие77;
        Для Н77 = 1 По М77.РеквизитШапки() Цикл С77 = С77 + ";" + М77.РеквизитШапки(Н77).Идентификатор; КонецЦикла;
        Для Н77 = 1 По М77.РеквизитТабличнойЧасти() Цикл
            С77 = С77 + ";" + М77.РеквизитТабличнойЧасти(Н77).Идентификатор;
        КонецЦикла;
        Ответ77 = Ответ77 + Сверить77("Документ.{kind}", С77, Ож77);
    Исключение
        Ответ77 = Ответ77 + "|Документ.{kind}:E:" + ОписаниеОшибки();
    КонецПопытки;""")
    count = sum(len(names) for kinds in found.values() for names in kinds.values())
    control = ("    Ответ77 = \"\"; Всего77 = 0; Общие77 = \"\";\n"
               "    Для Н77 = 1 По Метаданные.ОбщийРеквизитДокумента() Цикл\n"
               "        Общие77 = Общие77 + \";\" + Метаданные.ОбщийРеквизитДокумента(Н77).Идентификатор;\n"
               "    КонецЦикла;\n" + "\n".join(blocks)
               + "\n    Возврат \"реквизитов=\" + СокрЛП(Всего77) + \";расхождения=\" + Ответ77;")
    return dict(id="n-attributes", rule="metadata", compile="ok", runtime="ok", batch=True,
                value=f"реквизитов={count};расхождения=", procedures=COMPARE, control=control,
                vars="Перем Всего77;",
                note="1С перечисляет реквизиты каждого справочника и документа (с общими) через Метаданные "
                     "и сверяет с прочитанными из 1Cv7.MD")


def access_case(metadata_path):
    """a-attributes: every attribute read is read from a new object; failures are listed, Новый() apart."""
    found = read_attributes(metadata_path)
    lines, count = [], 0
    for cls, kinds in found.items():
        for kind, names in kinds.items():
            lines.append(f'    О77 = СоздатьОбъект("{cls}.{kind}");')
            lines.append(f'    Попытка О77.Новый(); Исключение Новый77 = Новый77 + ";{kind}"; КонецПопытки;')
            if cls == "Документ":
                lines.append(f'    Попытка О77.НоваяСтрока(); Исключение Новый77 = Новый77 + ";{kind}:строка"; '
                             'КонецПопытки;')
            for name in names:
                lines.append(f'    Попытка З77 = О77.{name}; Исключение Отказ77 = Отказ77 + ";{kind}.{name}"; '
                             'КонецПопытки;')
                count += 1
    control = ("    Отказ77 = \"\"; Новый77 = \"\";\n" + "\n".join(lines)
               + f"\n    Возврат \"обращений={count};отказы=\" + Отказ77 + \"|новый=\" + Новый77;")
    return dict(id="a-attributes", rule="metadata", compile="ok", runtime="ok", batch=True,
                value_prefix=f"обращений={count};отказы=|", control=control,
                note="чтение каждого реквизита справочников и документов из 1Cv7.MD у нового объекта")


def judge_attributes(case, observed):
    """judge of probe_metadata77; a value_prefix leaves the tail (the Новый() failures) to the record."""
    if "value_prefix" not in case:
        return judge(case, observed)
    verdict = judge({**case, "value": None}, observed)
    if verdict == "confirmed" and not (observed["value"] or "").startswith(case["value_prefix"]):
        return "contradicted"
    return verdict


def main(argv=None):
    parser, args = arguments(argv, __doc__)
    cases = select(parser, args, CASES + [names_case(args.metadata), access_case(args.metadata)])
    return run_cases(cases, args, "task 019 attribute and guard probes on real 1C 7.7", judge_attributes)


if __name__ == "__main__":
    raise SystemExit(main())
