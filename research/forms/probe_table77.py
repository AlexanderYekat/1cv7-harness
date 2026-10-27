"""Native probes of the table part in steps; task 027, expectations in docs/tasks/027-table-part-steps.md.

Each case is one `harness77 run` on the run's copy with [configuration]. The main form is a new
«Готовая продукция» (Документ.ГотоваяПродукция): its table part after 6 windows, columns «Товар»,
«Количество», «Стоимость», «Сумма» with the formula Пересчет(). For observation its module gets
ПриВводеСтроки and ПриУдаленииСтроки with a message, and Пересчет reports the current column and
recalculates a quantity or a cost without a chosen product. The unchanged form opens a document
fixture_setup writes (task 024); the list is the list form «Основная» of «Банки».

The series runner, observation and evidence are task 022's (probe_md_forms77.run_series); the profile
is task 025's (probe_scenario77.project_text). After the series the stand base and the user's list of
bases must be as they were.

Usage (the task 021 stand profile with copy_path):
  python research/forms/probe_table77.py --stand .local/stage21-native/stand.toml
      --work .local/stage27-native/s1 --evidence .artifacts/stage27-table-part-YYYYMMDD-1.json
      [--case ID ...] [--dry-run]
"""

import argparse
import copy
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import probe_md_forms77 as base  # noqa: E402
import probe_scenario77 as scenario  # noqa: E402
from probe_md_catalogs77 import BANKS_LIST  # noqa: E402

SCOPE = "task 027: the table part in steps"
PRODUCTION = "Документ/ГотоваяПродукция/Форма"
# Observation: the handlers of an interactive new and deleted row, and the formula of the columns.
# Series 0 and 0b printed the row number in ПриВводеСтроки (0: the new row is not current yet).
ROW_HANDLERS_0 = """Процедура ПриВводеСтроки()
    Сообщить("ввод строки " + Строка(НомерСтроки));
КонецПроцедуры

Процедура ПриУдаленииСтроки()
    Сообщить("удаление строки " + Строка(НомерСтроки));
КонецПроцедуры
"""
ROW_HANDLERS = ROW_HANDLERS_0.replace('Сообщить("ввод строки " + Строка(НомерСтроки));', 'Сообщить("ввод строки");')
HEADER = "Процедура Пересчет(Подбор=0)\n\tЕсли Товар.Выбран() = 1 Тогда"
RECALCULATION_0 = [(HEADER, "Процедура Пересчет(Подбор=0)\n\tСообщить(\"пересчет \" + Форма.ТекущаяКолонка());\n"
                            "\tЕсли (Товар.Выбран() = 1) ИЛИ (Форма.ТекущаяКолонка() <> \"Товар\") Тогда")]
# Series 1: the formula also warns over 100 (a modal window of a column's formula) and fails at 13.
ERROR_LINE = "\t\tХ77 = 1 / Делитель77;"
RECALCULATION = [(HEADER, RECALCULATION_0[0][1].replace(
    "\tЕсли (Товар", "\tЕсли Количество > 100 Тогда\n\t\tПредупреждение(\"Harness77 больше 100\");\n\tКонецЕсли;\n"
    "\tЕсли Количество = 13 Тогда\n\t\tДелитель77 = 0;\n" + ERROR_LINE + "\n\tКонецЕсли;\n\tЕсли (Товар", 1))]
PRODUCT = "Harness77 продукция 027"
# t-existing: one row of a written document, the product chosen, as the user leaves it.
DOCUMENT = f'''Спр77 = СоздатьОбъект("Справочник.Номенклатура");
Спр77.Новый();
Спр77.Наименование = "{PRODUCT}";
Спр77.Записать();
Док77 = СоздатьОбъект("Документ.ГотоваяПродукция");
Док77.Новый();
Док77.НоваяСтрока();
Док77.Товар = Спр77.ТекущийЭлемент();
Док77.Количество = 1;
Док77.Стоимость = 10;
Док77.Сумма = 10;
Док77.Записать();
Возврат Док77.ТекущийДокумент();'''


def production(id, steps, observe=False, **fields):
    """A case on a new «Готовая продукция» whose module reports its rows and its formula."""
    parameters = dict({"steps": steps}, **fields.pop("parameters", {}))
    fields.setdefault("open", "passed")
    fields.setdefault("result", "passed")
    # Series 0 and 0b observed with the first module; series 1 judges with the final one.
    return dict(id=id, form=PRODUCTION, object="Документ.ГотоваяПродукция", value=None, parameters=parameters,
                insert=ROW_HANDLERS_0 if observe else ROW_HANDLERS, replace=RECALCULATION_0 if observe else RECALCULATION,
                observe=observe, **fields)


def existing(id, steps, verify=None, **fields):
    """A case on the unchanged form, opened on the document written by fixture_setup; ``verify`` reads it back."""
    fields.setdefault("open", "passed")
    fields.setdefault("result", "passed")
    parameters = {"fixture_setup": DOCUMENT, "steps": steps}
    if verify is not None:
        parameters["fixture_verify"] = verify
    return dict(id=id, form=PRODUCTION, object="Документ.ГотоваяПродукция", value=None, parameters=parameters, **fields)


def bank_list(id, steps, **fields):
    """A case on the unchanged list form «Основная» of «Банки»."""
    fields.setdefault("open", "passed")
    fields.setdefault("result", "passed")
    return dict(id=id, form=BANKS_LIST, object="Справочник.Банки.ФормаСписка.Основная", value=None,
                parameters={"steps": steps}, **fields)


def two_rows():
    return [{"add_row": True}, {"cell": "Количество", "text": "1"}, {"add_row": True}, {"cell": "Количество", "text": "2"}]


SERIES_0 = [
    production("t-add", [{"add_row": True}, {"message": "ввод строки 1"}, {"rows": 1}], observe=True),
    production("t-cell", [
        {"add_row": True},
        {"cell": "Количество", "text": "3"},
        {"message": "пересчет Количество"},
        {"cell": "Стоимость", "text": "10"},
        {"message": "пересчет Стоимость"},
        {"value": "Сумма", "text": "30"},
        {"value": "Количество", "text": "3"},
    ], observe=True),
    production("t-row", two_rows() + [
        {"row": 1},
        {"value": "Количество", "text": "1"},
        {"value": "Количество", "row": 2, "text": "2"},
        {"value": "НомерСтроки", "text": "1"},
        {"total": "Количество", "text": "3"},
        {"rows": 2},
    ], observe=True),
    production("t-delete", two_rows() + [
        {"row": 1},
        {"delete_row": True},
        {"message": "удаление строки 1"},
        {"rows": 1},
        {"value": "Количество", "text": "2"},
    ], observe=True),
    existing("t-existing", [
        {"row": 1},
        {"cell": "Количество", "text": "3"},
        {"value": "Сумма", "text": "30"},
        {"total": "Сумма", "text": "30"},
    ], observe=True),
    production("t-send", [{"add_row": True}, {"message": "ввод строки 1"}, {"rows": 1}], observe=True,
               parameters={"table_keys": "send"}),
    # The value is not known before: the failed step reports what 1C read.
    bank_list("t-list", [{"value": "Наименование", "text": "?"}], observe=True),
    bank_list("t-list-down", [{"key": "Down"}, {"value": "Наименование", "text": "?"}], observe=True),
    bank_list("t-list-delete", [{"key": "Delete"}, {"message": "?"}], observe=True),
]


# Series 0b: how a row's step leaves a cell's editor without cancelling a new row (series 0: Escape cancels the
# row 1C still takes the input of), and how an existing row is deleted. ПриВводеСтроки sees row number 0.
TWO_ROWS = DOCUMENT.replace("Док77.Записать();", """Док77.НоваяСтрока();
Док77.Товар = Спр77.ТекущийЭлемент();
Док77.Количество = 2;
Док77.Стоимость = 10;
Док77.Сумма = 20;
Док77.Записать();""")
SECOND_ROW = [{"add_row": True}, {"cell": "Количество", "text": "1"}, {"add_row": True}, {"rows": 2}]


def finishing(id, way, steps=SECOND_ROW, **parameters):
    return production(id, steps, observe=True, parameters=dict({"table_finish": way}, **parameters))


SERIES_0B = [
    production("b-enter-key", [
        {"add_row": True}, {"cell": "Количество", "text": "1"}, {"key": "Enter"}, {"rows": 1},
        {"add_row": True}, {"rows": 2}, {"cell": "Количество", "text": "2"}, {"key": "Enter"},
        {"value": "Количество", "row": 1, "text": "1"}, {"value": "Количество", "row": 2, "text": "2"},
    ], observe=True),
    finishing("b-editor", "editor"),
    finishing("b-command", "editor", table_rows="command"),
    finishing("b-activate", "activate"),
    finishing("b-leave", "leave"),
    finishing("b-enter", "enter"),
    production("b-row", [{"add_row": True}, {"cell": "Количество", "text": "1"}, {"row": 1}, {"rows": 1},
                         {"value": "Количество", "text": "1"}], observe=True),
    dict(existing("b-delete", [{"row": 1}, {"delete_row": True}, {"message": "удаление строки 1"}, {"rows": 1},
                               {"value": "Количество", "text": "2"}]),
         insert=ROW_HANDLERS_0, replace=RECALCULATION_0, observe=True,
         parameters={"fixture_setup": TWO_ROWS, "steps": [{"row": 1}, {"delete_row": True}, {"message": "удаление строки 1"},
                                                          {"rows": 1}, {"value": "Количество", "text": "2"}]}),
    dict(existing("b-delete-command", []), insert=ROW_HANDLERS_0, replace=RECALCULATION_0, observe=True,
         parameters={"fixture_setup": TWO_ROWS, "table_rows": "command",
                     "steps": [{"row": 1}, {"delete_row": True}, {"message": "удаление строки 1"}, {"rows": 1},
                               {"value": "Количество", "text": "2"}]}),
]


# Series 1 (final code): a row's step ends the input of a new row with Enter, as the keyboard user does, before
# its key (series 0b); the module of series 1; the unchanged form; the list; failures and refusals.
TWO_ENTERED = two_rows()
DELETE_QUESTION = "Объект будет помечен на удаление !"
# The example's flow: the changed quantity is written by the form's button and read back from the base.
VERIFY_ROW = '''Док77 = СоздатьОбъект("Документ.ГотоваяПродукция");
Если Док77.НайтиДокумент(Объект77) <> 1 Тогда Возврат "not found"; КонецЕсли;
Док77.ВыбратьСтроки();
Если Док77.ПолучитьСтроку() <> 1 Тогда Возврат "no row"; КонецЕсли;
Возврат Строка(Док77.КоличествоСтрок()) + "|" + Строка(Док77.Количество) + "|" + Строка(Док77.Сумма);'''


def failing(maker, id, steps, issue, stopped_at, **fields):
    return maker(id, steps, result="failed", issue=issue, stopped_at=stopped_at, **fields)


def refused(maker, id, steps, reason, **fields):
    return dict(maker(id, steps, **fields), blocked=reason)


def written(id, steps, observe=False):
    """A case on the unchanged form, opened on a written document with two rows (quantity 1 and 2, cost 10)."""
    return dict(existing(id, steps, observe=observe), parameters={"fixture_setup": TWO_ROWS, "steps": steps})


CASES = [
    production("r-add", [{"add_row": True}, {"message": "ввод строки"}, {"rows": 1}, {"value": "НомерСтроки", "text": "1"}]),
    production("r-cell", [
        {"add_row": True},
        {"cell": "Количество", "text": "3"},
        {"message": "пересчет Количество"},
        {"cell": "Стоимость", "text": "10"},
        {"message": "пересчет Стоимость"},
        {"value": "Сумма", "text": "30"},
        {"total": "Сумма", "text": "30"},
    ]),
    production("r-rows", TWO_ENTERED + [
        {"rows": 2},
        {"row": 1},
        {"value": "Количество", "text": "1"},
        {"value": "Количество", "row": 2, "text": "2"},
        {"value": "НомерСтроки", "text": "1"},
        {"total": "Количество", "text": "3"},
    ]),
    production("r-delete", TWO_ENTERED + [
        {"row": 1},
        {"delete_row": True},
        {"message": "удаление строки 1"},
        {"rows": 1},
        {"value": "Количество", "text": "2"},
    ]),
    # Delete while 1C still takes the new row's input: Enter ends it, then the row is deleted.
    production("r-delete-new", [
        {"add_row": True},
        {"cell": "Количество", "text": "1"},
        {"delete_row": True},
        {"message": "удаление строки 1"},
        {"rows": 0},
    ]),
    production("r-keys", TWO_ENTERED + [
        {"key": "Enter"},
        {"row": 2},
        {"key": "Up"},
        {"value": "НомерСтроки", "text": "1"},
        {"key": "Down"},
        {"value": "НомерСтроки", "text": "2"},
    ]),
    production("r-dialog", [
        {"add_row": True},
        {"cell": "Количество", "text": "500"},
        {"dialog": "Harness77 больше 100"},
        {"value": "Количество", "text": "500"},
        {"message": "пересчет Количество"},
    ]),
    failing(production, "r-error", [{"add_row": True}, {"cell": "Количество", "text": "13"}, {"rows": 1}],
            "step 2 (cell 'Количество'): 1C reported an error: line ", 2),
    existing("r-existing", [
        {"row": 1},
        {"cell": "Количество", "text": "3"},
        {"value": "Сумма", "text": "30"},
        {"total": "Сумма", "text": "30"},
        {"rows": 1},
    ]),
    # Series 2: the second row of a written document, the form's own Пересчет (7 × 10), by the keys (series 1e).
    written("r-row-existing", [
        {"row": 2},
        {"value": "НомерСтроки", "text": "2"},
        {"cell": "Количество", "text": "7"},
        {"value": "Количество", "row": 2, "text": "7"},
        {"value": "Количество", "row": 1, "text": "1"},
        {"value": "Сумма", "text": "70"},
        {"total": "Сумма", "text": "80"},
    ]),
    existing("r-save", [
        {"row": 1},
        {"cell": "Количество", "text": "3"},
        {"value": "Сумма", "text": "30"},
        {"click": "Записать"},
        {"click": "Закрыть", "closes": True},
    ], verify=VERIFY_ROW, verify_value="1|3|30"),
    bank_list("r-list", [
        {"value": "Наименование", "text": "АБ АСПЕКТ ЗАО"},
        {"key": "Down"},
        {"value": "Наименование", "text": "АБ БАНК ПРОЕКТНОГО ФИНАНСИРОВАНИЯ ЗАО"},
        {"key": "Up"},
        {"value": "Наименование", "text": "АБ АСПЕКТ ЗАО"},
    ]),
    bank_list("r-list-delete", [
        {"key": "Delete"},
        {"dialog": DELETE_QUESTION, "button": "Нет"},
        {"value": "Наименование", "text": "АБ АСПЕКТ ЗАО"},
    ]),
    failing(production, "r-wrong-rows", [{"add_row": True}, {"rows": 2}], "step 2 (rows 2): the table has 1 rows, expected 2", 2),
    failing(production, "r-no-row", [{"row": 3}], "step 1 (row 3): 1C refused: no row 3 of 0", 1),
    failing(production, "r-wrong-total", [{"add_row": True}, {"cell": "Количество", "text": "3"}, {"total": "Количество", "text": "4"}],
            "step 3 (total 'Количество'): is '3', expected '4'", 3),
    failing(production, "r-unexpected", [{"add_row": True}, {"cell": "Количество", "text": "500"}, {"rows": 1}],
            "step 2 (cell 'Количество'): an unexpected modal window 'Harness77 больше 100'", 2),
    refused(production, "r-reference", [{"add_row": True}, {"cell": "Товар", "text": "x"}],
            "step 2 (cell 'Товар'): column 'Товар' holds a reference (B)"),
    refused(bank_list, "r-list-add", [{"add_row": True}],
            "step 1 (add_row): only the table part of a document's form; a list takes key steps"),
    refused(production, "r-unknown-column", [{"cell": "Цена", "text": "1"}],
            "step 1 (cell 'Цена'): no column of the table part"),
    refused(scenario.ert, "r-ert", [{"add_row": True}],
            "table steps need a form of the configuration with a table part or a list"),
]


# Series 1b: Up in the table part of a new document after Enter ended its input left НомерСтроки at 2 (r-keys).
# Does a cursor key move the row of the document at all, and which row does a cell step edit after it?
def two_rows_written(id, steps):
    return written(id, steps, observe=True)


SERIES_1B = [
    two_rows_written("k-down", [{"row": 1}, {"key": "Down"}, {"value": "НомерСтроки", "text": "2"},
                                {"key": "Up"}, {"value": "НомерСтроки", "text": "1"}]),
    two_rows_written("k-cell", [{"row": 1}, {"key": "Down"}, {"cell": "Количество", "text": "7"},
                                {"value": "Количество", "row": 2, "text": "7"}, {"value": "Количество", "row": 1, "text": "1"}]),
    production("k-new", TWO_ENTERED + [{"key": "Enter"}, {"row": 1}, {"value": "НомерСтроки", "text": "1"},
                                       {"key": "Down"}, {"value": "НомерСтроки", "text": "2"}], observe=True),
]
SERIES_1B[2].update(insert=ROW_HANDLERS, replace=RECALCULATION)
# Series 1c: Down moved the cursor of the window (the editor opened on row 2, k-cell) but not НомерСтроки, and the
# input did not reach row 2; АктивизироватьСтроку never moved the row so far. Where does a cell's input go?
SERIES_1C = [
    two_rows_written("c-row2", [{"row": 2}, {"value": "НомерСтроки", "text": "2"}, {"cell": "Количество", "text": "7"},
                                {"value": "Количество", "row": 2, "text": "7"}, {"value": "Количество", "row": 1, "text": "1"}]),
    two_rows_written("c-down", [{"row": 1}, {"key": "Down"}, {"cell": "Количество", "text": "7"},
                                {"value": "Количество", "row": 1, "text": "1"}, {"value": "Количество", "row": 2, "text": "7"}]),
    two_rows_written("c-down-row", [{"key": "Down"}, {"row": 2}, {"value": "НомерСтроки", "text": "2"},
                                    {"cell": "Количество", "text": "7"}, {"value": "Количество", "row": 2, "text": "7"}]),
    production("c-after-input", TWO_ENTERED + [{"row": 1}, {"value": "НомерСтроки", "text": "1"},
                                               {"cell": "Количество", "text": "5"}, {"value": "Количество", "row": 1, "text": "5"},
                                               {"value": "Количество", "row": 2, "text": "2"}], observe=True),
]
SERIES_1C[3].update(insert=ROW_HANDLERS, replace=RECALCULATION)
# Series 1d: АктивизироватьСтроку from the controller moves nothing (c-row2); the input goes to the document's
# current row, not the row of the window's cursor (c-down). Set the document's row (ПолучитьСтрокуПоНомеру),
# with or without АктивизироватьСтроку() of the current row, and see where a cell's input goes.
ROW_2 = [{"row": 2}, {"value": "НомерСтроки", "text": "2"}, {"cell": "Количество", "text": "7"},
         {"value": "Количество", "row": 2, "text": "7"}, {"value": "Количество", "row": 1, "text": "1"}]
ROW_1_AFTER_INPUT = TWO_ENTERED + [{"row": 1}, {"value": "НомерСтроки", "text": "1"}, {"cell": "Количество", "text": "5"},
                                   {"value": "Количество", "row": 1, "text": "5"}, {"value": "Количество", "row": 2, "text": "2"}]
DOWN_ROW_1 = [{"key": "Down"}, {"row": 1}, {"value": "НомерСтроки", "text": "1"}, {"cell": "Количество", "text": "7"},
              {"value": "Количество", "row": 1, "text": "7"}, {"value": "Количество", "row": 2, "text": "2"}]


def moving(id, way, steps, written=True):
    case = two_rows_written(id, steps) if written else production(id, steps, observe=True)
    if not written:
        case.update(insert=ROW_HANDLERS, replace=RECALCULATION)
    case["parameters"]["table_row"] = way
    return case


def shown(case):
    """The case with the main 1C window shown while its steps run (research, series 1e)."""
    case["parameters"]["table_show"] = True
    return case


DOWN_UP = [{"key": "Down"}, {"value": "НомерСтроки", "text": "2"}, {"key": "Up"}, {"value": "НомерСтроки", "text": "1"}]
DOWN_CELL = [{"key": "Down"}, {"cell": "Количество", "text": "7"}, {"value": "Количество", "row": 2, "text": "7"},
             {"value": "Количество", "row": 1, "text": "1"}]
SERIES_1E = [
    shown(two_rows_written("e-down", DOWN_UP)),
    shown(two_rows_written("e-down-cell", DOWN_CELL)),
    shown(two_rows_written("e-row", ROW_2)),
    shown(moving("e-input-row", "activate", ROW_1_AFTER_INPUT, written=False)),
    shown(moving("e-get", "get", ROW_2)),
]

SERIES_1D = [
    moving("d-get", "get", ROW_2),
    moving("d-get-activate", "get-activate", ROW_2),
    moving("d-input-get", "get", ROW_1_AFTER_INPUT, written=False),
    moving("d-input-get-activate", "get-activate", ROW_1_AFTER_INPUT, written=False),
    moving("d-down-get-activate", "get-activate", DOWN_ROW_1),
]


def prepare(case, extraction, folder, baselines=None):
    """The case's profile and a configuration directory with only the form module it changes, if any."""
    modules = folder / "configuration"
    modules.mkdir(parents=True)
    if case.get("insert") or case.get("replace"):
        text = (extraction / (case["form"] + base.md77.SUFFIX)).read_bytes().decode("utf-8")
        for old, new in case.get("replace") or []:
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
            if text.count(old) != 1:
                raise ValueError(f"{case['id']}: the module has {text.count(old)} places for {old[:40]!r}")
            text = text.replace(old, new)
        if case.get("insert"):
            # Procedures go before the first one: the module ends with its program's statements.
            lines = text.split("\r\n")
            first = base._first_procedure(lines)
            lines = lines[:first] + case["insert"].strip("\n").split("\n") + [""] + lines[first:]
            text = "\r\n".join(lines)
        if case.get("issue") and "line " in case["issue"]:
            # The line 1C names in its run-time error.
            case["error_line"] = text.split("\r\n").index(ERROR_LINE) + 1
        target = modules / (case["form"] + base.md77.SUFFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    (folder / "project.toml").write_text(scenario.project_text(case, modules), encoding="utf-8")
    return folder / "project.toml"


def judge(case, observed):
    """Series 0 observes: its verdict is read from the evidence; the other series judge as task 025."""
    if case.get("observe"):
        return "observed"
    return scenario.judge(case, observed)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path, help="new local directory for generated cases")
    parser.add_argument("--evidence", required=True, type=Path, help="new JSON file with all results")
    parser.add_argument("--output-root", type=Path, default=base.ROOT / ".artifacts/runs")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--series", choices=("0", "0b", "1", "1b", "1c", "1d", "1e"), default="1",
                        help="the cases of a series; 0 and 0b ran with research parameters removed since")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.baselines = None
    if os.path.lexists(args.evidence):
        parser.error("evidence already exists")
    series = {"0": SERIES_0, "0b": SERIES_0B, "1": CASES, "1b": SERIES_1B, "1c": SERIES_1C, "1d": SERIES_1D, "1e": SERIES_1E}[args.series]
    if set(args.case) - {c["id"] for c in series}:
        parser.error("unknown case")
    cases = [copy.deepcopy(c) for c in series if not args.case or c["id"] in args.case]
    if args.dry_run:
        return dry_run(cases, args)
    return base.run_series(cases, args, SCOPE, prepare_case=prepare, judge_case=judge)


def dry_run(cases, args):
    """Profiles of every case and the configurations they build, without 1C."""
    stand = base.load_stand(args.stand)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    base.md77.extract(Path(stand.base) / "1Cv7.MD", work / "extraction")
    for case in cases:
        folder = work / "cases" / case["id"]
        folder.mkdir(parents=True)
        prepare(case, work / "extraction", folder)
        report = base.md77.build(Path(stand.base) / "1Cv7.MD", folder / "configuration", folder / "1Cv7.MD")
        print(case["id"], [row["file"] for row in report["changed"]],
              [(row["file"], len(row["changes"])) for row in report["changed_forms"]], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
