"""Native probes of steps on an open form; task 025, expectations in docs/tasks/025-form-steps.md.

Each case is one `harness77 run`. A form of the configuration (the element form of «Банки») runs on
the run's copy with [configuration]: without a module or a description in the case's directory the
form is the stand base's own, unchanged; fixture_setup writes a known bank first (task 024). The ERT
case opens FIO.ERT with steps_module77.1s on the stand base, without [configuration]. No case adds the
harness protocol to the form's module: the steps read the windows, 1C's messages and attributes.

The series runner, observation and evidence are task 022's (probe_md_forms77.run_series); this file
prepares the profiles and judges the cases. After the series the stand base and the user's list of
bases must be as they were.

Usage (the task 021 stand profile with copy_path):
  python research/forms/probe_scenario77.py --stand .local/stage21-native/stand.toml
      --work .local/stage25-native/s0 --evidence .artifacts/stage25-form-steps-YYYYMMDD-0.json
      [--case ID ...] [--dry-run]
"""

import argparse
import copy
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import probe_md_forms77 as base  # noqa: E402
from probe_md_catalogs77 import BANKS_ELEMENT, button  # noqa: E402

SCOPE = "task 025: steps on an open form"
ERT_SOURCE = HERE / "steps_module77.1s"
BIK_WARNING = "Возможно, БИК указан неверно."

BANK = '''Спр77 = СоздатьОбъект("Справочник.Банки");
Спр77.Новый();
Спр77.УстановитьНовыйКод("77");
Спр77.Наименование = "Harness77 банк 025";
Спр77.Записать();
Возврат Спр77.ТекущийЭлемент();'''
VERIFY_BANK = '''Спр77 = СоздатьОбъект("Справочник.Банки");
Если Спр77.НайтиЭлемент(Объект77) <> 1 Тогда Возврат "not found"; КонецЕсли;
Возврат СокрЛП(Спр77.Наименование) + "|" + СокрЛП(Спр77.Код);'''
# s-error: a button whose handler fails at run time, after a message (the module is changed only here).
FAILING = """Процедура Harness77Ошибка()
    Делитель77 = 0;
    Сообщить("до ошибки 77");
    Х77 = 1 / Делитель77;
КонецПроцедуры
"""
FAILING_BUTTON = dict(button(180, 155), caption="Ошибка 77", formula="Harness77Ошибка()")


def bank(id, steps, **fields):
    """A case on the unchanged element form of «Банки», opened on the bank written by fixture_setup."""
    parameters = {"fixture_setup": BANK, "steps": steps}
    if "verify_value" in fields:
        parameters["fixture_verify"] = VERIFY_BANK
    fields.setdefault("open", "passed")
    fields.setdefault("result", "passed")
    return dict(id=id, form=BANKS_ELEMENT, object="Справочник.Банки.ФормаЭлемента", value=None,
                parameters=parameters, **fields)


CASES = [
    bank("s-input", [
        {"check": "Наименование", "text": "Harness77 банк 025"},
        {"input": "Код", "text": "12345"},
        {"check": "Код", "text": "12345"},
        {"value": "Код", "text": "12345"},
    ]),
    bank("s-message", [
        {"input": "Код", "text": "12345"},
        {"click": "Записать"},
        {"message": BIK_WARNING},
        {"input": "Код", "text": "047777777"},
        {"click": "КнЗаписать"},
        {"no_message": BIK_WARNING},
    ]),
    bank("s-ok", [
        {"input": "Код", "text": "047777777"},
        {"input": "Наименование", "text": "Harness77 изменено 025"},
        {"click": "ОК", "closes": True},
        {"no_message": BIK_WARNING},
    ], verify_value="Harness77 изменено 025|047777777"),
    bank("s-error", [
        {"click": "Ошибка 77"},
        {"check": "Наименование", "text": "Harness77 банк 025"},
    ], module=FAILING, change=base.added([FAILING_BUTTON]), result="failed",
        issue="step 1 (click 'Ошибка 77'): 1C reported an error: line "),
    dict(id="s-ert", ert=True, object="FIO.ERT", value=None, open="passed", result="passed", parameters={"steps": [
        {"check": "Фамилия", "text": "Иванов"},
        {"click": "Очистить"},
        {"check": "Фамилия", "text": ""},
        {"input": "Фамилия", "text": "Петров"},
        {"input": "Имя", "text": "Пётр"},
        {"value": "Имя", "text": "Пётр"},
        {"click": "ОК", "closes": True},
        {"message": "ФИО: Петров Пётр"},
    ]}),
]


# Series 1: element states. ПриОткрытии disables «Записать» and hides the field «Телефоны»; the description
# adds a check box without a formula (its attribute is the form's).
STATES = """
Процедура ПриОткрытии()
    Форма.КнЗаписать.Доступность(0);
    Форма.Телефоны.Видимость(0);
КонецПроцедуры
"""
FLAG = base.control(**{"class": "CHECKBOX", "caption": "Флажок 77", "identifier": "Флажок77",
                       "x": 180, "y": 137, "width": 52, "height": 10})


def states(id, steps, **fields):
    return bank(id, steps, module_end=STATES, change=base.added([FLAG]), **fields)


def failing(id, steps, issue, stopped_at, **fields):
    """A scenario that fails at step ``stopped_at`` with ``issue``; the test expects result failed."""
    maker = fields.pop("maker", bank)
    return maker(id, steps, result="failed", issue=issue, stopped_at=stopped_at, **fields)


def refused(id, steps, reason, **fields):
    """Refused before 1C opens the form: the run is blocked with ``reason``."""
    case = (ert if fields.pop("ert", False) else bank)(id, steps, **fields)
    return dict(case, blocked=reason)


def ert(id, steps, **fields):
    fields.setdefault("open", "passed")
    fields.setdefault("result", "passed")
    return dict(id=id, ert=True, object="FIO.ERT", value=None, parameters={"steps": steps}, **fields)


CASES += [
    states("s-states", [
        {"check": "КнЗаписать", "enabled": False},
        {"check": "Телефоны", "visible": False},
        {"check": "Наименование", "visible": True},
        {"check": "Флажок77", "checked": False},
        {"click": "Флажок77"},
        {"check": "Флажок 77", "checked": True},
        {"value": "Флажок77", "text": "1"},
    ]),
    failing("s-disabled", [{"click": "Записать"}, {"check": "Наименование", "text": "x"}],
            "step 1 (click 'Записать'): the element is disabled", 1, maker=states),
    failing("s-wrong-check", [{"check": "Наименование", "text": "Другое"}, {"input": "Код", "text": "1"}],
            "step 1 (check 'Наименование'): shows 'Harness77 банк 025', expected 'Другое'", 1),
    failing("s-wrong-value", [{"input": "Код", "text": "12345"}, {"value": "Код", "text": "99999"}],
            "step 2 (value 'Код'): is '12345", 2),
    failing("s-wrong-message", [{"input": "Код", "text": "047777777"}, {"click": "Записать"}, {"message": BIK_WARNING}],
            f"step 3 (message '{BIK_WARNING}'): no such message among []", 3),
    failing("s-unexpected-message", [{"input": "Код", "text": "12345"}, {"click": "Записать"}, {"no_message": BIK_WARNING}],
            f"step 3 (no_message '{BIK_WARNING}'): the message is there", 3),
    failing("s-not-closed", [{"click": "Записать", "closes": True}, {"message": BIK_WARNING}],
            "step 1 (click 'Записать'): the form did not close", 1),
    failing("s-closed", [{"click": "ОК"}, {"check": "Наименование", "text": "x"}],
            "step 1 (click 'ОК'): the form closed", 1),
    failing("s-wrong-attribute", [{"value": "НетТакого77", "text": ""}],
            "step 1 (value 'НетТакого77'): 1C did not read the attribute: ", 1),
    refused("s-unknown", [{"click": "Удалить"}], "step 1 (click 'Удалить'): no element with this identifier or caption"),
    refused("s-wrong-class", [{"input": "Записать", "text": "1"}], "needs 1CEDIT or BMASKED"),
    refused("s-ambiguous", [{"input": "Кем", "text": "1"}], "step 1 (input 'Кем'): 3 elements match", ert=True),
    refused("s-after-close", [{"click": "ОК", "closes": True}, {"check": "Наименование", "text": "x"}],
            "step 2 (check): the form is closed at step 1"),
]


# Series 2: input into masked fields (number and date), not covered natively before (task 022 typed into 1CEDIT).
MASKED = [
    base.control(**{"class": "BMASKED", "identifier": "Число77", "type": {"kind": "number", "length": 10, "precision": 2},
                    "x": 180, "y": 135, "width": 52, "height": 13}),
    base.control(**{"class": "BMASKED", "identifier": "Дата77", "type": {"kind": "date"},
                    "x": 180, "y": 80, "width": 52, "height": 13}),
]
CASES.append(bank("s-masked", [
    {"input": "Число77", "text": "12.5"},
    {"value": "Число77", "text": "12.5"},
    {"check": "Число77", "text": "12.50"},
    {"input": "Дата77", "text": "251026"},
    {"check": "Дата77", "text": "25.10.26"},
    {"value": "Дата77", "text": "25.10.26"},
], change=base.added(MASKED)))


def toml(value):
    """A TOML value of a profile: strings as JSON escapes them (valid TOML basic strings), tables inline."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[\n" + "".join(f"    {toml(item)},\n" for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key} = {toml(item)}" for key, item in value.items()) + " }"
    raise TypeError(type(value))


def project_text(case, modules):
    parameters = ([] if case.get("ert") else [f"form_object = {toml(case['object'])}"]) + [
        f"{key} = {toml(value)}" for key, value in case["parameters"].items()]
    tests = [("form-open", "open", case["open"], "1" if case["open"] == "passed" else None),
             ("form-steps", "result", case["result"], None)]
    if "verify_value" in case:
        tests.append(("data-verify", "verify", "passed", case["verify_value"]))
    lines = ["schema_version = 1", "", "[project]", f'id = "form-steps-{case["id"]}"', "", "[build]",
             f"template = {toml(base.TEMPLATE.as_posix())}",
             # Task 026 gives an ERT case its own module (source).
             f"source = {toml((case.get('source') or (ERT_SOURCE if case.get('ert') else base.SOURCE)).as_posix())}",
             'encoding = "utf-8"', ""]
    if modules is not None:
        lines += ["[configuration]", f"modules = {toml(modules.as_posix())}", ""]
    lines += ["[platform.parameters]", *parameters, ""]
    for name, command, expect, value in tests:
        lines += ["[[platform.tests]]", f'name = "{name}"', f'command = "{command}"', f'expect = "{expect}"',
                  *([f"expect_value = {toml(value)}"] if value is not None else []), ""]
    lines += ["[deadlines]", "open_timeout_s = 120", "calculation_timeout_s = 120", "cancel_timeout_s = 15",
              "shutdown_timeout_s = 30", "total_timeout_s = 600", ""]
    return "\n".join(lines)


def prepare(case, extraction, folder, baselines=None):
    """The case's profile; a configuration directory with only what the case changes (often nothing)."""
    # The ERT case runs on a copy too: a session on the stand base writes its log and the user's settings
    # (series 0, s-ert: 1SUSERS.DBF, SYSLOG, Вера/1Cv7.CFG, 1cv7flt.lst).
    modules = folder / "configuration"
    modules.mkdir(parents=True)
    if not case.get("ert"):
        if case.get("module") or case.get("module_end"):
            original = (extraction / (case["form"] + base.md77.SUFFIX)).read_bytes().decode("utf-8")
            lines = original.splitlines()
            first = base._first_procedure(lines)
            lines = lines[:first] + (case.get("module") or "").splitlines() + [""] + lines[first:] \
                + (case.get("module_end") or "").splitlines()
            text = "\r\n".join(lines) + "\r\n"
            if case.get("module"):
                # The line 1C names in its run-time error.
                case["error_line"] = text.split("\r\n").index("    Х77 = 1 / Делитель77;") + 1
            target = modules / (case["form"] + base.md77.SUFFIX)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
        if case.get("change"):
            description = json.loads((extraction / (case["form"] + base.md77.FORM_SUFFIX)).read_text(encoding="utf-8"))
            case["change"](description)
            target = modules / (case["form"] + base.md77.FORM_SUFFIX)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(description, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "project.toml").write_text(project_text(case, modules), encoding="utf-8")
    return folder / "project.toml"


def judge(case, observed):
    if case.get("blocked"):
        # Refused before 1C opens the form: no form window was inspected.
        return "confirmed" if observed["run_status"] == "blocked" and case["blocked"] in (
            observed["platform_reason"] or "") and observed["inspection"]["found"] is None else "contradicted"
    tests = {row["name"]: row for row in observed["tests"]}
    met = all(row.get("expectation_met") for row in tests.values()) and len(tests) == (
        3 if "verify_value" in case else 2) and observed["run_status"] == "passed"
    result = observed["operations"].get("result") or {}
    if case.get("issue"):
        issues = result.get("form_issues") or []
        met = met and any(issue.startswith(case["issue"]) for issue in issues)
        if case.get("error_line"):
            met = met and any(f"line {case['error_line']}:" in issue for issue in issues)
        if case.get("stopped_at"):
            # The scenario stopped at the failed step: the steps after it did not run.
            steps = result.get("steps") or []
            met = met and len(steps) == case["stopped_at"] and steps[-1].get("status") == "failed"
    else:
        steps = result.get("steps") or []
        met = met and len(steps) == len(case["parameters"]["steps"]) and all(s.get("status") == "passed" for s in steps)
    return "confirmed" if met else "contradicted"


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
        return dry_run(cases, args)
    return base.run_series(cases, args, SCOPE, prepare_case=prepare, judge_case=judge)


if __name__ == "__main__":
    raise SystemExit(main())
