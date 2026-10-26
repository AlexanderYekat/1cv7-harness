"""Native probes of modal windows in steps; task 026, expectations in docs/tasks/026-modal-dialogs.md.

Each case is one `harness77 run` on the run's copy with [configuration]: the element form of «Банки»
gets a button «Окно 77» (or a field with a formula) and the procedure it calls at the end of its
module; fixture_setup writes a known bank first (task 024). The handler opens a modal window —
Предупреждение, Вопрос, ВвестиСтроку/Число/Дату — and the dialog steps answer it.

The series runner, observation and evidence are task 022's (probe_md_forms77.run_series); preparing
and judging a case are task 025's (probe_scenario77). After the series the stand base and the
user's list of bases must be as they were.

Usage (the task 021 stand profile with copy_path):
  python research/forms/probe_modal77.py --stand .local/stage21-native/stand.toml
      --work .local/stage26-native/s0 --evidence .artifacts/stage26-modal-dialogs-YYYYMMDD-0.json
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

SCOPE = "task 026: modal windows in steps"
WINDOW_BUTTON = base.control(**{"class": "BUTTON", "caption": "Окно 77", "formula": "Harness77Окно()",
                                "x": 180, "y": 155, "width": 54, "height": 13})
# m-field: a number field whose formula warns when the value is over 100.
CHECKED_NUMBER = base.control(**{"class": "BMASKED", "identifier": "Число77", "formula": "Harness77Проверка()",
                                 "type": {"kind": "number", "length": 10, "precision": 2},
                                 "x": 180, "y": 135, "width": 52, "height": 13})


def handler(body):
    return "\nПроцедура Harness77Окно()\n" + body.strip("\n") + "\nКонецПроцедуры\n"


WARNING = handler("""
    Сообщить("до 77");
    Предупреждение("Harness77 предупреждение");
    Сообщить("после 77");""")
QUESTION = handler("""
    Ответ77 = Вопрос("Harness77 вопрос?", "Да+Нет");
    Сообщить("ответ " + Ответ77);""")
CHAIN = handler("""
    Если Вопрос("Harness77 продолжить?", "Да+Нет+Отмена") = "Да" Тогда
        Предупреждение("Harness77 готово");
    КонецЕсли;
    Сообщить("конец 77");""")


def prompt(initial, call, name):
    """A handler that asks for a value in an input window and reports it, or the refusal."""
    return handler(f"""
    Знач77 = {initial};
    Если {call} = 1 Тогда
        Сообщить("{name} " + Знач77);
    Иначе
        Сообщить("{name} отказ");
    КонецЕсли;""")


STRING = prompt('""', 'ВвестиСтроку(Знач77, "Harness77 строка", 20)', "строка")
NUMBER = prompt("0", 'ВвестиЧисло(Знач77, "Harness77 число", 10, 2)', "число")
DATE = prompt("'00.00.00'", 'ВвестиДату(Знач77, "Harness77 дата")', "дата")
FIELD = """
Процедура Harness77Проверка()
    Если Число77 > 100 Тогда
        Предупреждение("Harness77 больше 100");
    КонецЕсли;
КонецПроцедуры
"""


def window(id, module, steps, **fields):
    """A case on the element form of «Банки» with the button «Окно 77» calling ``module``'s handler."""
    return scenario.bank(id, steps, module_end=module, change=base.added([WINDOW_BUTTON]), **fields)


CASES = [
    window("m-warning", WARNING, [
        {"click": "Окно 77"},
        {"dialog": "Harness77 предупреждение"},
        {"message": "до 77"},
        {"message": "после 77"},
    ]),
    window("m-question", QUESTION, [
        {"click": "Окно 77"},
        {"dialog": "Harness77 вопрос?", "button": "Нет"},
        {"message": "ответ Нет"},
    ]),
    window("m-chain", CHAIN, [
        {"click": "Окно 77"},
        {"dialog": "Harness77 продолжить?", "button": "Да"},
        {"dialog": "Harness77 готово"},
        {"message": "конец 77"},
    ]),
    window("m-string", STRING, [
        {"click": "Окно 77"},
        {"dialog": "Harness77 строка", "text": "abc77", "button": "ОК"},
        {"message": "строка abc77"},
    ]),
    window("m-number", NUMBER, [
        {"click": "Окно 77"},
        {"dialog": "Harness77 число", "text": "12.5", "button": "ОК"},
        {"message": "число 12.5"},
    ]),
    window("m-date", DATE, [
        {"click": "Окно 77"},
        # Series 0b: the window of an empty date shows today's date, so the date typed is another one.
        {"dialog": "Harness77 дата", "text": "010126", "button": "ОК"},
        {"message": "дата 01.01.26"},
    ]),
    scenario.bank("m-field", [
        {"input": "Число77", "text": "500"},
        {"dialog": "Harness77 больше 100"},
        {"value": "Число77", "text": "500"},
    ], module_end=FIELD, change=base.added([CHECKED_NUMBER])),
    # 1C asks after #Закрыть returned (series 0c): a wrong text fails the step, the window is closed with
    # «Отмена» and the controller closes the form.
    scenario.failing("m-close", [
        {"input": "Наименование", "text": "Harness77 изменено 026"},
        {"click": "Закрыть"},
        {"dialog": "Harness77 заведомо не тот текст", "button": "Нет"},
    ], "step 3 (dialog 'Harness77 заведомо не тот текст'): the window shows 'Сохранить изменения?' "
       "with buttons ['Да', 'Нет', 'Отмена']", 3),
    scenario.failing("m-unexpected", [
        {"click": "Окно 77"},
        {"check": "Наименование", "text": "Harness77 банк 025"},
    ], "step 1 (click 'Окно 77'): an unexpected modal window 'Harness77 предупреждение'", 1,
        maker=lambda id, steps, **fields: window(id, WARNING, steps, **fields)),
    scenario.failing("m-no-dialog", [
        {"input": "Код", "text": "047777777"},
        {"click": "Записать"},
        {"dialog": "Harness77 предупреждение"},
    ], "step 3 (dialog 'Harness77 предупреждение'): no modal window opened", 3),
]


# Series 1: the other answers, the failures of a dialog step, an ERT and refusals before the session.
ERT_MODULE = HERE / "modal_module77.1s"
SAVE_QUESTION = "Сохранить изменения?"


def on_window(module):
    return lambda id, steps, **fields: window(id, module, steps, **fields)


CASES += [
    window("m-cancel", STRING, [
        {"click": "Окно 77"},
        {"dialog": "Harness77 строка", "text": "abc77", "button": "Отмена"},
        {"message": "строка отказ"},
        {"no_message": "строка abc77"},
    ]),
    scenario.failing("m-wrong-text", [
        {"click": "Окно 77"},
        {"dialog": "Harness77 другой вопрос?", "button": "Да"},
        {"message": "ответ Да"},
    ], "step 2 (dialog 'Harness77 другой вопрос?'): the window shows 'Harness77 вопрос?' with buttons ['Да', 'Нет']", 2,
        maker=on_window(QUESTION)),
    scenario.failing("m-no-button", [
        {"click": "Окно 77"},
        {"dialog": "Harness77 вопрос?", "button": "Отмена"},
    ], "step 2 (dialog 'Harness77 вопрос?'): no button 'Отмена' among ['Да', 'Нет']", 2, maker=on_window(QUESTION)),
    scenario.failing("m-extra", [
        {"click": "Окно 77"},
        {"dialog": "Harness77 продолжить?", "button": "Да"},
        {"message": "конец 77"},
    ], "step 2 (dialog 'Harness77 продолжить?'): an unexpected modal window 'Harness77 готово' with buttons ['OK']", 2,
        maker=on_window(CHAIN)),
    scenario.ert("m-ert", [
        {"check": "Фамилия", "text": "Иванов"},
        {"click": "Очистить"},
        {"dialog": "Очистить поля?", "button": "Нет"},
        {"check": "Фамилия", "text": "Иванов"},
        {"click": "Очистить"},
        {"dialog": "Очистить поля?", "button": "Да"},
        {"check": "Фамилия", "text": ""},
        {"input": "Фамилия", "text": "Петров"},
        {"click": "ОК", "closes": True},
        {"message": "ФИО: Петров"},
    ], source=ERT_MODULE),
    # 1C's own question when a changed element form closes (series 0d): «Сохранить изменения?», Да/Нет/Отмена.
    scenario.bank("m-save", [
        {"input": "Код", "text": "047777777"},
        {"input": "Наименование", "text": "Harness77 изменено 026"},
        {"click": "Закрыть"},
        {"dialog": SAVE_QUESTION, "button": "Да", "closes": True},
        {"no_message": "Возможно, БИК указан неверно."},
    ], verify_value="Harness77 изменено 026|047777777"),
    scenario.bank("m-keep", [
        {"input": "Наименование", "text": "Harness77 изменено 026"},
        {"click": "Закрыть"},
        {"dialog": SAVE_QUESTION, "button": "Отмена"},
        {"check": "Наименование", "text": "Harness77 изменено 026"},
    ]),
    scenario.refused("m-first", [{"dialog": "Harness77 предупреждение"}, {"click": "Окно 77"}],
                     "step 1 (dialog): follows the click or input that opens the window", module_end=WARNING,
                     change=base.added([WINDOW_BUTTON])),
    scenario.refused("m-closes-early", [{"click": "Закрыть", "closes": True}, {"dialog": "Записать?", "button": "Да"}],
                     "step 1 (click): the form closes after the window; put closes on the last dialog step"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path, help="new local directory for generated cases")
    parser.add_argument("--evidence", required=True, type=Path, help="new JSON file with all results")
    parser.add_argument("--output-root", type=Path, default=base.ROOT / ".artifacts/runs")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.baselines = None
    if os.path.lexists(args.evidence):
        parser.error("evidence already exists")
    if set(args.case) - {c["id"] for c in CASES}:
        parser.error("unknown case")
    cases = [copy.deepcopy(c) for c in CASES if not args.case or c["id"] in args.case]
    if args.dry_run:
        return scenario.dry_run(cases, args)
    return base.run_series(cases, args, SCOPE, prepare_case=scenario.prepare, judge_case=scenario.judge)


if __name__ == "__main__":
    raise SystemExit(main())
