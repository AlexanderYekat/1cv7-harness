"""Native probes for the forms of catalogs and journals of 1Cv7.MD on a copy of the base; task 023.

The cases of task 022 (probe_md_forms77) for other forms: a catalog's element, group and list forms,
a journal's list form and a report's form. Each case is one `harness77 run` with [configuration] (the
changed form module and, when the case changes the form, its description) and the form launcher with
[platform.parameters] form_object, named as the form's module file. Expectations are fixed in
docs/tasks/023-catalog-journal-forms.md before the run; "?" leaves the outcome to the probe. After the
series the stand base and the user's list of bases must be as they were.

Series 0 (*-name) learns how 1C names these modules in a compile error: the run fails with the name
1C gives, which the product did not map yet. The other cases are series 1.

Usage (the task 021 stand profile with copy_path and copy_exclude):
  python research/forms/probe_md_catalogs77.py --stand .local/stage21-native/stand.toml
      --work .local/stage23-native/s0 --evidence .artifacts/stage23-catalog-forms-YYYYMMDD-0.json
      [--case ID ...] [--dry-run]
"""

import argparse
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import probe_md_forms77 as base  # noqa: E402

control = base.control
SCOPE = "task 023: forms of catalogs and journals of 1Cv7.MD on a copy of the base"

BANKS_ELEMENT = "Справочник/Банки/ФормаЭлемента"
BANKS_GROUP = "Справочник/Банки/ФормаГруппы"
BANKS_LIST = "Справочник/Банки/ФормаСписка.Основная"
CURRENCIES_LIST = "Справочник/Валюты/ФормаСписка.Основная"
UNITS_ELEMENT = "Справочник/ЕдиницыИзмерений/ФормаЭлемента"
POWERS_JOURNAL = "Журнал/Доверенности/ФормаСписка.ФормаСписка"
# A journal form not named ФормаСписка: series 0 named Доверенности's «Форма.ФормаСписка».
SALARY_JOURNAL = "Журнал/ЗаработнаяПлата/ФормаСписка.Основная"
# Series 2: a catalog edited in a dialog with an element attribute not on its form, one edited both ways,
# one edited in the list (field 11 of the record: 1, 2, 0), a list form whose tree of groups is not first.
TAXES_ELEMENT = "Справочник/НалогиИОтчисления/ФормаЭлемента"
CURRENCIES_ELEMENT = "Справочник/Валюты/ФормаЭлемента"
VAT_ELEMENT = "Справочник/СтавкиНДС/ФормаЭлемента"
MATERIALS_LIST = "Справочник/Материалы/ФормаСписка.Основная"
RATES_REPORT = "Отчет/КурсыВалют/Форма"


def form_object(form):
    """The form_object of a form file: its path with dots; a report's own form is named by the report."""
    name = form.replace("/", ".")
    return name[:-len(".Форма")] if name.startswith(("Отчет.", "Обработка.", "Документ.")) else name


def button(x, y, height=13, width=54):
    return control(**{"class": "BUTTON", "caption": "Проверка 77", "formula": "Harness77Нажатие()",
                      "x": x, "y": y, "width": width, "height": height})


UNITS_CONTROLS = [
    control(**{"class": "1CEDIT", "identifier": "ПолнНаименование", "type": {"kind": "string", "length": 100},
               "x": 10, "y": 20, "width": 300, "height": 13}),
    button(130, 142, 14),
]
UNITS_VALUES = """    Harness77Добавить("value:ПолнНаименование=" + ТипЗначенияСтр(ПолнНаименование) + "|" + СокрП(ПолнНаименование));
    Harness77Добавить("repr:ПолнНаименование=" + СокрП(ПолнНаименование));
"""
TAXES_CONTROLS = [
    control(**{"class": "1CEDIT", "identifier": "Содержание", "type": {"kind": "string", "length": 200},
               "x": 10, "y": 218, "width": 225, "height": 13}),
    button(245, 218),
]
TAXES_VALUES = """    Harness77Добавить("value:Содержание=" + ТипЗначенияСтр(Содержание) + "|" + СокрП(Содержание));
    Harness77Добавить("repr:Содержание=" + СокрП(Содержание));
"""
OPEN_PLAIN = base.OPEN_PLAIN
OPEN_TAXES = '    Нажатий77 = 0; Содержание = "Содержание 77"; Harness77Добавить("loaded:harness77-form");'
OPEN_UNITS = '    Нажатий77 = 0; ПолнНаименование = "Полное 77"; Harness77Добавить("loaded:harness77-form");'
FAILED = "configuration_compilation_failed: "


def case(id, form, **fields):
    fields.setdefault("opening", OPEN_PLAIN)
    fields.setdefault("values", "")
    return dict(id=id, form=form, object=form_object(form), **fields)


def name_case(id, form):
    """Series 0: a broken module; the run fails with the module name 1C gives, under its object."""
    owner = ".".join(form_object(form).split(".")[:2])
    return case(id, form, broken=True, open="failed", result="failed", value=None, reason=f"{FAILED}{owner}.")


def error_case(id, form):
    """Series 1: a broken module fails the run with its file and the line of the error."""
    return case(id, form, broken=True, open="failed", result="failed", value=None,
                reason=FAILED + form + base.md77.SUFFIX + ":{line}: ")


CASES = [
    name_case("e-name", BANKS_ELEMENT),
    name_case("g-name", BANKS_GROUP),
    name_case("l-name", BANKS_LIST),
    name_case("j-name", POWERS_JOURNAL),
    name_case("r-name", RATES_REPORT),
    case("e-button", BANKS_ELEMENT, change=base.added([button(180, 155)]), actions="click:4167", open="passed",
         result="passed", value="clicked:1"),
    case("e-attribute", UNITS_ELEMENT, opening=OPEN_UNITS, values=UNITS_VALUES, change=base.added(UNITS_CONTROLS),
         actions="click:4155", open="passed", result="passed",
         value="clicked:1;value:ПолнНаименование=Строка|Полное 77", representation=("ПолнНаименование", 4154)),
    case("g-button", BANKS_GROUP, change=base.added([button(180, 50)]), actions="click:4159", open="passed",
         result="passed", value="clicked:1"),
    case("l-button", BANKS_LIST, change=base.added([button(120, 120)]), actions="click:4156", open="passed",
         result="passed", value="clicked:1"),
    case("l-same", CURRENCIES_LIST, open="passed", result="passed", value=None),
    case("j-button", POWERS_JOURNAL, change=base.added([button(175, 127)]), actions="click:4157", open="passed",
         result="passed", value="clicked:1"),
    case("r-button", RATES_REPORT, change=base.added([button(110, 73)]), actions="click:4164", open="passed",
         result="passed", value="clicked:1"),
    # Series 2.
    case("e-field", TAXES_ELEMENT, opening=OPEN_TAXES, values=TAXES_VALUES, change=base.grown(240, TAXES_CONTROLS),
         actions="click:4194", open="passed", result="passed", value="clicked:1;value:Содержание=Строка|Содержание 77",
         representation=("Содержание", 4193)),
    case("e-both", CURRENCIES_ELEMENT, open="passed", result="passed", value=None),
    case("e-in-list", VAT_ELEMENT, open="passed", result="passed", value="?"),
    case("l-tree", MATERIALS_LIST, open="passed", result="passed", value=None),
    case("l-tree-third", MATERIALS_LIST, change=base.added([button(226, 191, width=40), button(268, 191, width=40)]),
         actions="click:4157", open="passed", result="passed", value="clicked:1"),
    # Series 3: the element form of a catalog edited in its list is refused before 1C starts.
    case("e-in-list-refused", VAT_ELEMENT, open="blocked", result="blocked", value=None,
         blocked="the catalog is edited in its list"),
    error_case("e-error", BANKS_ELEMENT),
    error_case("g-error", BANKS_GROUP),
    error_case("l-error", BANKS_LIST),
    error_case("j-error", POWERS_JOURNAL),
    error_case("j-other-error", SALARY_JOURNAL),
    error_case("r-error", RATES_REPORT),
]


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path, help="new local directory for generated cases")
    parser.add_argument("--output-root", type=Path, default=base.ROOT / ".artifacts" / "runs")
    parser.add_argument("--evidence", required=True, type=Path, help="new JSON file with all results")
    parser.add_argument("--case", action="append", default=[], help="run only these case ids")
    parser.add_argument("--dry-run", action="store_true", help="prepare the cases and build them, no 1C")
    args = parser.parse_args(argv)
    args.baselines = None
    if os.path.lexists(args.evidence) and not args.dry_run:
        parser.error(f"evidence file exists: {args.evidence}")
    unknown = set(args.case) - {c["id"] for c in CASES}
    if unknown:
        parser.error(f"unknown case ids: {sorted(unknown)}")
    return args, [dict(c) for c in CASES if not args.case or c["id"] in args.case]


if __name__ == "__main__":
    arguments_, cases_ = arguments()
    raise SystemExit(base.dry_run(cases_, arguments_) if arguments_.dry_run
                     else base.run_series(cases_, arguments_, SCOPE))
