"""Native probes for the context of configuration and form modules (L7711, L7714) through `harness77 run`; task 020.

The infrastructure of probe_metadata77: each case is one cooperating external processing,
its construct in Harness77Контроль inside Попытка. Two new means:

- modules of the stand's 1Cv7.MD are compiled in the probe's session by 1C++'s
  ВыполняемыйМодуль (the base's global module loads 1cpp.dll) in the context of an object
  (НазначитьКонтекст) or of the probe's form; the text is read from a cp1251 file the
  script writes, nothing in 1Cv7.MD changes;
- table cases build the probe on a template with tables (ОбработкаПросмотраСчетаНаОплату.ert
  of the stand's ExtForms) and on its copy whose Container.Contents lists Page.6 first.

Usage (local stand profile, base-for-test, the FIO.ERT template):
  python research/rules77/probe_context77.py --stand .local/stage14-native/stand.toml
      --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --metadata .local/bases/base-for-test/1Cv7.MD
      --work .local/stage20-native --evidence .artifacts/stage20-context-probes-YYYYMMDD.json
"""

from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))

from probe_metadata77 import arguments, judge, run_cases, run_line, select  # noqa: E402
from probe_rules77 import PROBE, RETURN_42, reader  # noqa: E402

TABLES = Path("ExtForms") / "Diadoc_2_23_01" / "ОбработкаПросмотраСчетаНаОплату.ert"
ZML1 = Path("ExtForms") / "rp14q1.GRP" / "ZML1.ERT"
# The template's button calls this procedure; the probe keeps its name defined.
TABLE_BUTTON = "Процедура ПодписатьИОтправитьПриНажатии()\nКонецПроцедуры\n"
FOLDER = re.compile(r"(?:\w+/)?(\w+?)_Number(\d+)/")

COMPILE = """Функция Прочитать77(Путь77)
    Т77 = СоздатьОбъект("Текст");
    Т77.Открыть(Путь77);
    Весь77 = ""; Блок77 = "";
    Для Н77 = 1 По Т77.КоличествоСтрок() Цикл
        Блок77 = Блок77 + Т77.ПолучитьСтроку(Н77) + РазделительСтрок;
        Если Н77 % 200 = 0 Тогда
            Весь77 = Весь77 + Блок77; Блок77 = "";
        КонецЕсли;
    КонецЦикла;
    Возврат Весь77 + Блок77;
КонецФункции

Функция Компилировать77(Текст77, Контекст77, Назначить77, Выполнить77)
    М77 = СоздатьОбъект("ВыполняемыйМодуль");
    Если Назначить77 = 1 Тогда
        М77.НазначитьКонтекст(Контекст77);
    КонецЕсли;
    М77.УстановитьМодуль(Текст77);
    // As task 005 did: the result is 1 or 0, the error text goes to the message window.
    Попытка
        Если М77.КомпилироватьМодуль() <> 1 Тогда
            Возврат "0";
        КонецЕсли;
    Исключение
        Возврат "E:" + ОписаниеОшибки();
    КонецПопытки;
    Если Выполнить77 = 0 Тогда
        Возврат "ok";
    КонецЕсли;
    Попытка
        Если М77.ВыполнитьМодуль() <> 1 Тогда
            Возврат "ok;0";
        КонецЕсли;
    Исключение
        Возврат "ok;E:" + ОписаниеОшибки();
    КонецПопытки;
    Возврат "ok;ok";
КонецФункции
"""
PROCEDURE = "Процедура П77()\n{}\nКонецПроцедуры\n"


def literal(text):
    """A 1C string literal of one line of text."""
    return '"' + text.replace('"', '""') + '"'


def one_line(text):
    """A module text as a 1C expression: lines joined by РазделительСтрок."""
    return " + РазделительСтрок + ".join(literal(line) for line in text.split("\n"))


def compiled(code, context, assign=1, execute=0, prepare=""):
    """A control compiling code (a module text) in a context expression; the result is the value."""
    return (f"    Конт77 = {context};\n{prepare}"
            + run_line(f"Ответ77 = Компилировать77({one_line(code)}, Конт77, {assign}, {execute});",
                       "    Возврат Ответ77;"))


DOCUMENT = 'СоздатьОбъект("Документ.АвансовыйОтчет")'
CATALOG = 'СоздатьОбъект("Справочник.Банки")'


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("cp1251"))


def reordered(template, target):
    """A copy of the table template whose Container.Contents lists Page.6 first."""
    from harness77 import ert_module as ert
    from harness77.lint77 import cfb_paths
    compound = ert.CompoundFile(template.read_bytes())
    paths = cfb_paths(compound)
    replacements = {}
    for entry in compound.directory_entries:
        if entry.object_type == 2 and entry.name == "Container.Contents":
            text = compound.read_stream(entry).decode("cp1251")
            sheet = re.search(r',\{"Moxcel\.Worksheet","Page\.6","[^"]*",""\}', text)
            first = text.find('{"Moxcel.Worksheet"')
            if sheet and first >= 0:
                moved = text[:sheet.start()] + text[sheet.end():]
                moved = moved[:first] + sheet.group(0)[1:] + "," + moved[first:]
                replacements[entry.entry_id] = moved.encode("cp1251")
                print("reordered", paths.get(entry.entry_id), file=sys.stderr)
    if len(replacements) != 1:
        raise SystemExit(f"{template}: expected one Container.Contents listing Page.6")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(compound.rebuild(replacements))
    return target


def frame25(raw):
    """A Dialog Stream whose Frame record has 25 in field 24 instead of 29."""
    from harness77 import ert_module as ert
    text = ert.decode_dialog(raw)
    changed, count = re.subn(r'(\{"Frame",\s*\{(?:"[^"]*",){24})"29"', r'\1"25"', text)
    if count != 1:
        raise SystemExit("Frame record with 29 in field 24 not found")
    return ert.encode_dialog(changed)


def moxel_name(title):
    """A Container.Profile change naming this worksheet title as the form's table."""
    def change(raw):
        text, count = re.subn(r'\{"MoxelName","[^"]*",""\}', '{"MoxelName","' + title + '",""}',
                              raw.decode("cp1251"))
        if count != 1:
            raise SystemExit("Container.Profile without one MoxelName")
        return text.encode("cp1251")
    return change


def crafted(template, target, page, data):
    """A copy of the template whose stream of this name holds new data (a table to try)."""
    from harness77 import ert_module as ert
    compound = ert.CompoundFile(template.read_bytes())
    found = [entry.entry_id for entry in compound.directory_entries if entry.object_type == 2 and entry.name == page]
    if len(found) != 1:
        raise SystemExit(f"{template}: expected one stream {page}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(compound.rebuild({found[0]: data(compound.read_stream(compound.directory_entries[found[0]]))}))
    return target


def batch(case_id, items, note, **expected):
    """Compile each module (module id, text file, context expression, declarations) in its context."""
    lines = []
    for module, path, context, prefix in items:
        # The mark puts the module's id into the message window before its compile errors.
        lines.append(f'    Сообщить("harness77-module:{module}");')
        # Контекст is no expression in 7.7 ("Ожидается выражение"): the context goes as an argument.
        lines.append(f"    Р77 = Компилировать77({prefix}Прочитать77({literal(str(path))}), {context}, 1, 0);")
        lines.append(f'    Если Р77 <> "ok" Тогда Ошибки77 = Ошибки77 + "|{module}=" + Р77; КонецЕсли;')
    control = ('    Ошибки77 = "";\n' + "\n".join(lines)
               + f'\n    Возврат "модулей={len(items)};ошибки=" + Ошибки77;')
    return dict(id=case_id, rule="L7711", compile="ok", runtime="ok", batch=True, deadline=600,
                procedures=COMPILE, control=control, note=note, **expected)


def md_cases(work, metadata_path):
    """b-transact and b-forms from the stand's 1Cv7.MD; module texts go to work/texts."""
    from harness77 import lint77
    reserved = lint77.load_catalog().reserved
    documents, forms = [], []
    for source in lint77.load_sources(Path(metadata_path)):
        match = FOLDER.match(source.module)
        if not match:
            continue
        module = f"{match.group(1)}_{match.group(2)}"
        path = work / "texts" / f"{module}.txt"
        if match.group(1) == "Transact" and source.owner:
            write_text(path, source.text)
            documents.append((module, path, f'СоздатьОбъект("Документ.{source.owner[1]}")', ""))
        elif match.group(1) in ("Report", "CalcVar") and source.dialog is not None:
            write_text(path, source.text)
            parsed = lint77.parse(source)
            own = set(lint77.module_variables(parsed)) | set(parsed.symbols) | reserved
            # Таблица, the form's table, belongs to a report form; the probe's form has none.
            names = sorted(name for name in source.dialog | {"таблица"} if name not in own
                           and re.fullmatch(r"[A-Za-zА-Яа-яЁё_][0-9A-Za-zА-Яа-яЁё_]*", name))
            # The form's context as lint knows it, declared on the first line: line numbers stay.
            prefix = (literal("Перем " + ", ".join(names) + "; ") + " + ") if names else ""
            forms.append((module, path, "Контекст", prefix))
    return [batch("b-transact", documents, "модули документов базы в контексте своего документа",
                  value=f"модулей={len(documents)};ошибки="),
            batch("b-forms", forms, "модули отчётов и обработок базы в контексте формы пробы, "
                                    "контекст их формы по lint объявлен Перем в первой строке",
                  value_prefix=f"модулей={len(forms)};ошибки=|CalcVar_25802=E:")]


def build_cases(args):
    work = args.work.resolve()
    base = Path(args.metadata).resolve().parent
    tables = (base / TABLES).resolve(strict=True)
    swapped = reordered(tables, work / "templates" / "tables-page6-first.ert")
    # Second series: is the property that makes areas variables the table's? The first table
    # (Page.5) replaced by the first table of a regulated report (ZML1.ERT, its module reads
    # areas), or with byte 31 of its header as in such tables (0x48 instead of 0x18).
    from harness77 import ert_module as ert
    zml = ert.CompoundFile((base / ZML1).read_bytes())
    report_table = zml.read_stream(zml.find_stream("Page.1"))
    borrowed = crafted(tables, work / "templates" / "tables-zml1-table.ert", "Page.5", lambda old: report_table)
    flagged = crafted(tables, work / "templates" / "tables-byte31.ert", "Page.5",
                      lambda old: old[:31] + bytes([0x48]) + old[32:])
    # Third series: field 24 of the dialog's Frame record, 25 in every form whose module reads areas.
    framed = crafted(tables, work / "templates" / "tables-frame25.ert", "Dialog Stream", frame25)
    # Fourth series: Container.Profile names the form's table (MoxelName).
    named6 = crafted(tables, work / "templates" / "tables-named-page6.ert", "Container.Profile",
                     moxel_name("СчетНаОплату_ТиС"))
    named5 = crafted(tables, work / "templates" / "tables-named-page5.ert", "Container.Profile",
                     moxel_name("СчетНаОплату_ИП"))
    write_text(work / "texts" / "read.txt", "Проверка77")
    cases = [
        dict(id="f-read", rule="infra", compile="ok", runtime="ok", value="Проверка77", procedures=COMPILE,
             control=run_line(f"Ответ77 = СокрЛП(Прочитать77({literal(str(work / 'texts' / 'read.txt'))}));",
                              "    Возврат Ответ77;")),
        # Date literals: 'ОК' in a Торговля+Склад processing.
        dict(id="d-word", rule="L7711", compile="?", procedures=reader("    Х77 = 'ОК';")),
        dict(id="d-value", rule="L7711", compile="ok", runtime="ok",
             control=run_line("З77 = '01.02.2003';", "    Возврат Строка(З77);")),
        # Named areas of the form's first table.
        dict(id="t-control", rule="L7711", compile="ok", runtime="ok", value="42", template=str(tables),
             procedures=TABLE_BUTTON, control=RETURN_42),
        dict(id="t-first", rule="L7711", compile="ok", template=str(tables),
             procedures=TABLE_BUTTON + reader("    Х77 = Получатель;")),
        dict(id="t-other", rule="L7711", compile="error", message="Переменная не определена", template=str(tables),
             procedures=TABLE_BUTTON + reader("    Х77 = АдресТелефон;")),
        dict(id="t-reorder-first", rule="L7711", compile="ok", template=str(swapped),
             procedures=TABLE_BUTTON + reader("    Х77 = АдресТелефон;")),
        dict(id="t-reorder-other", rule="L7711", compile="error", message="Переменная не определена",
             template=str(swapped), procedures=TABLE_BUTTON + reader("    Х77 = Получатель;")),
        dict(id="t-borrowed", rule="L7711", compile="?", template=str(borrowed),
             procedures=TABLE_BUTTON + reader("    Х77 = Тлф;"), note="первая таблица — Page.1 ZML1.ERT"),
        dict(id="t-borrowed-other", rule="L7711", compile="error", message="Переменная не определена",
             template=str(borrowed), procedures=TABLE_BUTTON + reader("    Х77 = Получатель;"),
             note="Получатель — область прежней первой таблицы, её больше нет"),
        dict(id="t-byte31", rule="L7711", compile="?", template=str(flagged),
             procedures=TABLE_BUTTON + reader("    Х77 = Получатель;"), note="байт 31 первой таблицы 0x18 → 0x48"),
        dict(id="t-frame25", rule="L7711", compile="?", template=str(framed),
             procedures=TABLE_BUTTON + reader("    Х77 = Получатель;"), note="Frame[24] диалога 29 → 25"),
        dict(id="t-table-attr", rule="L7711", compile="?", template=str(tables),
             procedures=TABLE_BUTTON + reader("    Х77 = Таблица;")),
        dict(id="t-frame25-table-attr", rule="L7711", compile="?", template=str(framed),
             procedures=TABLE_BUTTON + reader("    Х77 = Таблица;")),
        dict(id="t-fio-table-attr", rule="L7711", compile="error", message="Переменная не определена",
             procedures=reader("    Х77 = Таблица;"), note="FIO.ERT: таблиц нет"),
        dict(id="t-named-6", rule="L7711", compile="ok", template=str(named6),
             procedures=TABLE_BUTTON + reader("    Х77 = АдресТелефон;"), note="MoxelName — заголовок Page.6"),
        dict(id="t-named-6-other", rule="L7711", compile="error", message="Переменная не определена",
             template=str(named6), procedures=TABLE_BUTTON + reader("    Х77 = Получатель;")),
        dict(id="t-named-5", rule="L7711", compile="ok", template=str(named5),
             procedures=TABLE_BUTTON + reader("    Х77 = Получатель;"), note="MoxelName — заголовок Page.5"),
        # Module code in the context of an object (1C++ ВыполняемыйМодуль).
        dict(id="x-api", rule="L7711", compile="ok", runtime="ok", value="ok", procedures=COMPILE,
             control=compiled(PROCEDURE.format(""), DOCUMENT)),
        dict(id="x-attribute", rule="L7711", compile="ok", runtime="ok", value="ok", procedures=COMPILE,
             control=compiled(PROCEDURE.format("    Х = Сотрудник;"), DOCUMENT)),
        dict(id="x-missing", rule="L7711", compile="ok", runtime="ok", value="0", procedures=COMPILE,
             control=compiled(PROCEDURE.format("    Х = Нет77;"), DOCUMENT)),
        dict(id="x-no-context", rule="L7711", compile="ok", runtime="ok", value="0", procedures=COMPILE,
             control=compiled(PROCEDURE.format("    Х = Сотрудник;"), DOCUMENT, assign=0)),
        dict(id="x-builtin", rule="L7711", compile="ok", runtime="ok", value="ok", procedures=COMPILE,
             control=compiled(PROCEDURE.format("    Х = НомерДок; Х = ДатаДок;"), DOCUMENT)),
        dict(id="x-common", rule="L7711", compile="ok", runtime="ok", value="ok", procedures=COMPILE,
             control=compiled(PROCEDURE.format("    Х = Комментарий;"), DOCUMENT)),
        dict(id="x-table", rule="L7711", compile="ok", runtime="ok", value="ok", procedures=COMPILE,
             control=compiled(PROCEDURE.format("    Х = КомуЗаЧто;"), DOCUMENT)),
        dict(id="x-catalog", rule="L7711", compile="ok", runtime="ok", value="ok", procedures=COMPILE,
             control=compiled(PROCEDURE.format("    Х = КоррСчет; Х = Код; Х = Наименование;"), CATALOG)),
        dict(id="x-catalog-missing", rule="L7711", compile="ok", runtime="ok", value="0",
             procedures=COMPILE, control=compiled(PROCEDURE.format("    Х = Нет77;"), CATALOG)),
        dict(id="x-chain", rule="L7714", compile="ok", runtime="ok", value="ok;0", procedures=COMPILE,
             control=compiled("Х = Сотрудник.Нет77;", DOCUMENT, execute=1, prepare="    Конт77.Новый();\n")),
        # A line of the base's own document modules: an attribute its trimmed Договоры lacks.
        dict(id="c-contract", rule="L7714", compile="ok", runtime="error",
             control="    Док = СоздатьОбъект(\"Документ.ЗаписьКнигиПродаж\");\n    Док.Новый();\n"
                     + run_line("З77 = Док.Договор.ВестиУчетРасчетовУЕ;"),
             note="TypedText/Transact_Number11103, строка 192"),
    ]
    return cases + md_cases(work, args.metadata)


def judge_context(case, observed):
    """judge of probe_metadata77; a value_prefix leaves the tail (error texts) to the record."""
    if "value_prefix" not in case:
        return judge(case, observed)
    verdict = judge({**case, "value": None}, observed)
    if verdict == "confirmed" and not (observed["value"] or "").startswith(case["value_prefix"]):
        return "contradicted"
    return verdict


def main(argv=None):
    parser, args = arguments(argv, __doc__)
    cases = select(parser, args, build_cases(args))
    return run_cases(cases, args, "task 020 module context probes on real 1C 7.7", judge_context)


if __name__ == "__main__":
    raise SystemExit(main())
