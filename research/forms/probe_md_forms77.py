"""Native probes for forms of 1Cv7.MD by description on a copy of the base; task 022.

Each case is one `harness77 run` with [configuration] (only the case's files in the md-extract
layout: the changed form module and, when the case changes the form, its description) and the
form launcher with [platform.parameters] form_object: the controller opens the configuration
form, the watcher finds it by the control IDs of its dialog in the copy's 1Cv7.MD. The form
module answers the protocol of the ERT form probes (tasks 008, 011–013): loaded:harness77-form
when opened, handler lines in Форма.Параметр. Expectations are fixed in
docs/tasks/022-md-forms.md before the run; "?" leaves the outcome to the probe. After the series
the stand base and the user's list of bases must be as they were.

The visual cases (series 2) compare the capture of the open form with the baseline md-open in
--baselines: v-first runs without it (the visual stage blocks), the baseline is approved from its
run with `harness77 visual approve`, v-same and v-shifted compare against it.

Usage (the task 021 stand profile with copy_path and copy_exclude; FIO.ERT is the run's ERT,
which the configuration cases never open):
  python research/forms/probe_md_forms77.py --stand .local/stage21-native/stand.toml
      --work .local/stage22-native/s1 --evidence .artifacts/stage22-md-forms-YYYYMMDD-1.json
      [--case ID ...] [--baselines .local/stage22-native/baselines]
"""

import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "platform77"))
sys.path.insert(0, str(ROOT / "src"))

from harness77 import basecopy77, md77  # noqa: E402
from harness77.config77 import load_stand  # noqa: E402

TEMPLATE = ROOT / ".local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT"
SOURCE = HERE / "probe_module77.1s"
PROCESSING = "Обработка/ВыводТаблицыЗначений/Форма"
DOCUMENT = "Документ/Доверенность/Форма"
OBJECTS = {PROCESSING: "Обработка.ВыводТаблицыЗначений", DOCUMENT: "Документ.Доверенность"}
OPENING = "Процедура ПриОткрытии()"
CLOSING = "Процедура ПриЗакрытии()"

# The protocol of the ERT form probes, as procedures before the module's own (7.7 compiles in one
# pass: a procedure is called after its definition) and a module variable before them.
PROTOCOL = """Процедура Harness77Добавить(Текст)
    Если ТипЗначенияСтр(Форма.Параметр) = "СписокЗначений" Тогда
        Форма.Параметр.ДобавитьЗначение(Текст);
    КонецЕсли;
КонецПроцедуры

{procedures}Процедура Harness77Нажатие()
    Нажатий77 = Нажатий77 + 1;
    Harness77Добавить("clicked:" + СокрЛП(Строка(Нажатий77)));
{values}КонецПроцедуры
"""
# Only a form with the check box Флажок77 may read it: 7.7 refuses to compile a module reading an
# undefined name (series 0: «Переменная не определена (Флажок77)»).
FLAG = """Процедура Harness77Флажок()
    Harness77Добавить("flag:" + СокрЛП(Строка(Флажок77)));
КонецПроцедуры

"""
ELEMENT_VALUES = """    Harness77Добавить("value:Строка77=" + ТипЗначенияСтр(Строка77) + "|" + СокрП(Строка77) + "|"
        + СокрЛП(Строка(СтрДлина(Строка77))));
    Harness77Добавить("value:Число77=" + ТипЗначенияСтр(Число77) + "|" + СокрЛП(Строка(Число77)));
    Harness77Добавить("value:Флажок77=" + ТипЗначенияСтр(Флажок77) + "|" + СокрЛП(Строка(Флажок77)));
    Harness77Добавить("value:Валюта77=" + ТипЗначенияСтр(Валюта77) + "|" + Валюта77.Вид());
"""
DOCUMENT_VALUES = """    Harness77Добавить("value:РасчетныйСчет=" + ТипЗначенияСтр(РасчетныйСчет) + "|" + РасчетныйСчет.Вид() + "|"
        + СокрЛП(Строка(РасчетныйСчет.Выбран())));
    Harness77Добавить("repr:РасчетныйСчет=" + СокрЛП(Строка(РасчетныйСчет)));
"""
# The probe's own ПриОткрытии statements, first in the module's ПриОткрытии.
OPEN_PLAIN = '    Нажатий77 = 0; Harness77Добавить("loaded:harness77-form");'
OPEN_ELEMENTS = ('    Нажатий77 = 0; Строка77 = ""; Число77 = 12.5; Флажок77 = 1;'
                 ' Harness77Добавить("loaded:harness77-form");')
OPEN_DOCUMENT = ('    Нажатий77 = 0; Спр77 = СоздатьОбъект("Справочник.БанковскиеСчета");'
                 ' Если Спр77.ВыбратьЭлементы() = 1 Тогда Если Спр77.ПолучитьЭлемент() = 1 Тогда'
                 ' РасчетныйСчет = Спр77.ТекущийЭлемент(); КонецЕсли; КонецЕсли;'
                 ' Harness77Добавить("loaded:harness77-form");')
# Under the probe controller the document does not open its journal when closed.
CLOSE_DOCUMENT = '    Если ТипЗначенияСтр(Форма.Параметр) = "СписокЗначений" Тогда Возврат; КонецЕсли;'
BROKEN = "\nПроцедура Harness77Ошибка()\n    Х77 = 1 +;\nКонецПроцедуры\n"


def control(**item):
    return item


BUTTON_154 = control(**{"class": "BUTTON", "caption": "Проверка 77", "formula": "Harness77Нажатие()",
                        "x": 65, "y": 142, "width": 54, "height": 13})
# Строка77 is the last record: the initial focus is there (task 011), and a field without the focus does not take the
# text typed into it — the formula of the check box refreshes the form and the text is gone (series 2).
ELEMENTS = [
    control(**{"class": "STATIC", "caption": "Надпись 77", "identifier": "Надпись77", "x": 7, "y": 161,
               "width": 55, "height": 8}),
    control(**{"class": "CHECKBOX", "caption": "Флажок 77", "identifier": "Флажок77",
               "formula": "Harness77Флажок()", "x": 70, "y": 159, "width": 70, "height": 10}),
    control(**{"class": "BMASKED", "identifier": "Число77", "type": {"kind": "number", "length": 10, "precision": 2},
               "x": 240, "y": 158, "width": 60, "height": 13}),
    control(**{"class": "BMASKED", "identifier": "Валюта77",
               "type": {"kind": "reference", "object": "Справочник.Валюты"}, "x": 7, "y": 176, "width": 100,
               "height": 13}),
    control(**{"class": "BUTTON", "caption": "Проверка 77", "formula": "Harness77Нажатие()",
               "x": 120, "y": 176, "width": 54, "height": 13}),
    control(**{"class": "1CEDIT", "identifier": "Строка77", "type": {"kind": "string", "length": 20},
               "x": 150, "y": 158, "width": 80, "height": 13}),
]
DOCUMENT_CONTROLS = [
    control(**{"class": "BMASKED", "identifier": "РасчетныйСчет",
               "type": {"kind": "reference", "object": "Справочник.БанковскиеСчета"},
               "x": 74, "y": 222, "width": 160, "height": 13}),
    control(**{"class": "BUTTON", "caption": "Проверка 77", "formula": "Harness77Нажатие()",
               "x": 300, "y": 222, "width": 54, "height": 13}),
]


def moved(description):
    description["controls"][0].update(x=120, caption="Закрыть 77")


SHIFTED_154 = dict(BUTTON_154, x=BUTTON_154["x"] + 30)


def grown(height, controls):
    def change(description):
        description["form"]["height"] = height
        description["controls"] += copy.deepcopy(controls)
    return change


def added(controls):
    def change(description):
        description["controls"] += copy.deepcopy(controls)
    return change


ELEMENT_VALUE = ("flag:0;clicked:1;value:Строка77=Строка|Тест77|20;value:Число77=Число|12.5;"
                 "value:Флажок77=Число|0;value:Валюта77=Справочник|Валюты")
CASES = [
    dict(id="f-same", form=PROCESSING, opening=OPEN_PLAIN, values="", open="passed", result="passed", value=None),
    dict(id="f-button", form=PROCESSING, opening=OPEN_PLAIN, values="", change=added([BUTTON_154]),
         actions="click:4154", open="passed", result="passed", value="clicked:1"),
    dict(id="f-moved", form=PROCESSING, opening=OPEN_PLAIN, values="", change=moved, open="passed",
         result="passed", value=None),
    dict(id="f-elements", form=PROCESSING, opening=OPEN_ELEMENTS, values=ELEMENT_VALUES, procedures=FLAG,
         change=grown(200, ELEMENTS), actions="type:4159=Тест77,click:4155,click:4158", open="passed",
         result="passed", value=ELEMENT_VALUE),
    dict(id="f-doc", form=DOCUMENT, opening=OPEN_DOCUMENT, closing=CLOSE_DOCUMENT, values=DOCUMENT_VALUES,
         change=grown(240, DOCUMENT_CONTROLS), actions="click:4192", open="passed", result="passed",
         value="clicked:1;value:РасчетныйСчет=Справочник|БанковскиеСчета|1", representation=("РасчетныйСчет", 4191)),
    dict(id="f-calc-error", form=PROCESSING, opening=OPEN_PLAIN, values="", broken=True, open="failed",
         result="failed", value=None,
         reason="configuration_compilation_failed: Обработка/ВыводТаблицыЗначений/Форма.1s:"),
    # Series 1 only: the controller of series 1 cleared the modified flag unless reset_modified = false;
    # the document closed without asking either way, and series 2 has no such parameter.
    dict(id="f-doc-close", form=DOCUMENT, opening=OPEN_DOCUMENT, closing=CLOSE_DOCUMENT, values=DOCUMENT_VALUES,
         change=grown(240, DOCUMENT_CONTROLS), actions="click:4192", open="passed", result="passed", value="?"),
    # Series 2: the visual check md-open of the open processing form with the button of f-button.
    dict(id="v-first", form=PROCESSING, opening=OPEN_PLAIN, values="", change=added([BUTTON_154]),
         actions="click:4154", open="passed", result="passed", value="clicked:1", visual="blocked"),
    dict(id="v-same", form=PROCESSING, opening=OPEN_PLAIN, values="", change=added([BUTTON_154]),
         actions="click:4154", open="passed", result="passed", value="clicked:1", visual="passed"),
    dict(id="v-shifted", form=PROCESSING, opening=OPEN_PLAIN, values="", change=added([SHIFTED_154]),
         actions="click:4154", open="passed", result="passed", value="clicked:1", visual="failed"),
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def at_start(lines, header, statement):
    found = [n for n, line in enumerate(lines) if line.strip().casefold().startswith(header.casefold())]
    if len(found) != 1:
        raise ValueError(f"{header}: found {len(found)} times")
    return lines[:found[0] + 1] + statement.splitlines() + lines[found[0] + 1:]


def _first_procedure(lines):
    """Where the protocol goes: before the module's first procedure, else before its first statement.

    A module without procedures (the empty forms of task 023) gets it after its variables and comments.
    """
    for n, line in enumerate(lines):
        if re.match(r"\s*(Процедура|Функция)\s", line, re.I):
            return n
    for n, line in enumerate(lines):
        if line.strip() and not line.strip().startswith("//") and not re.match(r"\s*Перем\s", line, re.I):
            raise ValueError("a module with statements but no procedures: the protocol has no place")
    return len(lines)


def probe_module(case, original):
    """The form module with the protocol: Перем first, the procedures before the module's own."""
    lines = original.splitlines()
    first = _first_procedure(lines)
    protocol = (PROTOCOL.replace("{procedures}", case.get("procedures", "")).replace("{values}", case["values"])
                + (BROKEN if case.get("broken") else ""))
    if not any(line.strip().casefold().startswith(OPENING.casefold()) for line in lines):
        # A form without its own ПриОткрытии (task 023): the probe's is the only one.
        protocol += "\n" + OPENING + "\nКонецПроцедуры\n"
    lines = ["Перем Нажатий77;"] + lines[:first] + protocol.splitlines() + [""] + lines[first:]
    lines = at_start(lines, OPENING, case["opening"])
    if case.get("closing"):
        lines = at_start(lines, CLOSING, case["closing"])
    return "\r\n".join(lines) + "\r\n"


def case_object(case):
    """The form_object of a case: its own (task 023) or its form's in task 022."""
    return case.get("object") or OBJECTS[case["form"]]


def project_text(case, modules, baselines=None):
    parameters = [f"form_object = {json.dumps(case_object(case), ensure_ascii=False)}"]
    if case.get("actions"):
        parameters.append(f"actions = {json.dumps(case['actions'], ensure_ascii=False)}")
    parameters += [f"{key} = {json.dumps(value, ensure_ascii=False)}"
                   for key, value in case.get("parameters", {}).items()]
    result = ["[[platform.tests]]", 'name = "form-result"', 'command = "result"', f'expect = "{case["result"]}"']
    if case["value"] not in (None, "?"):
        result.append(f"expect_value = {json.dumps(case['value'], ensure_ascii=False)}")
    return "\n".join([
        "schema_version = 1", "", "[project]", f'id = "md-form-{case["id"]}"', "", "[build]",
        f"template = {json.dumps(TEMPLATE.as_posix())}", f"source = {json.dumps(SOURCE.as_posix())}",
        'encoding = "utf-8"', "", "[configuration]", f"modules = {json.dumps(modules.as_posix())}", "",
        "[platform.parameters]", *parameters, "",
        "[[platform.tests]]", 'name = "form-open"', 'command = "open"', f'expect = "{case["open"]}"',
        *(['expect_value = "1"'] if case["open"] == "passed" else []), "", *result, "",
        *(['[[platform.tests]]', 'name = "data-verify"', 'command = "verify"',
           f'expect = "{case.get("verify_expect", "passed")}"',
           *([f"expect_value = {json.dumps(case['verify_value'], ensure_ascii=False)}"]
             if case["verify_value"] is not None else []), ""]
          if "verify_value" in case else []),
        *([f"[visual]", f"baselines = {json.dumps(Path(baselines).as_posix())}", "", "[[visual.checks]]",
           'name = "md-open"', 'state = "open"', 'window = "form"', ""] if case.get("visual") else []),
        "[deadlines]", "open_timeout_s = 120", "calculation_timeout_s = 120", "cancel_timeout_s = 15",
        "shutdown_timeout_s = 30", "total_timeout_s = 600", ""])


def prepare(case, extraction, folder, baselines=None):
    """The case's configuration directory: its form module and, when it changes the form, its description."""
    modules = folder / "configuration"
    target = modules / (case["form"] + md77.SUFFIX)
    target.parent.mkdir(parents=True)
    original = (extraction / (case["form"] + md77.SUFFIX)).read_bytes().decode("utf-8")
    text = probe_module(case, original)
    target.write_bytes(text.encode("utf-8"))
    if case.get("broken"):
        # The line 1C names in its compile error (task 023 compares it, not only the module).
        case["broken_line"] = text.split("\r\n").index(BROKEN.splitlines()[2]) + 1
    if case.get("change"):
        description = json.loads((extraction / (case["form"] + md77.FORM_SUFFIX)).read_text(encoding="utf-8"))
        case["change"](description)
        (modules / (case["form"] + md77.FORM_SUFFIX)).write_text(
            json.dumps(description, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "project.toml").write_text(project_text(case, modules, baselines), encoding="utf-8")
    return folder / "project.toml"


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def observe(run_dir):
    report = load(run_dir / "run.json") or {}
    stages = {s["stage"]: s for s in report.get("stages", [])}
    platform, configuration = stages.get("platform_check", {}), stages.get("configuration", {})
    result = load(run_dir / "platform-result.json") or {}
    inspection = load(run_dir / "form" / "form-window.json") or {}
    operations = {op.get("name"): {key: op.get(key) for key in ("status", "value", "form_issues", "representations",
                                                                  "actions", "diagnostics")}
                  for op in result.get("operations", [])}
    copy_ = platform.get("base_copy") or {}
    return {"run_status": report.get("status"), "exit_code": report.get("exit_code"), "reason": report.get("reason"),
            "stages": {name: stage.get("status") for name, stage in stages.items()},
            "platform_reason": platform.get("reason"),
            "configuration": {"md_sha256": configuration.get("md_sha256"), "reason": configuration.get("reason"),
                              "changed": [row["file"] for row in configuration.get("changed") or []],
                              "changed_forms": [{"file": row["file"], "changes": row["changes"]}
                                                for row in configuration.get("changed_forms") or []]},
            "static": {"status": stages.get("static", {}).get("status"),
                       "diagnostics": [(d["module"], d["line"], d["rule"], d["message"][:120])
                                       for d in stages.get("static", {}).get("diagnostics", [])][:10]},
            "configuration_diagnostics": platform.get("configuration_diagnostics"),
            "tests": [{key: row.get(key) for key in ("name", "status", "value", "expectation_met")}
                      for row in stages.get("tests", {}).get("tests", [])],
            "operations": operations,
            "inspection": {"found": inspection.get("found"), "reason": inspection.get("reason"),
                           "error": inspection.get("error"), "units": inspection.get("units"),
                           "fields_open": inspection.get("fields_open"), "fields_after": inspection.get("fields_after"),
                           "parents": inspection.get("parents"), "expected_ids": inspection.get("expected_ids"),
                           "chain": [{k: w.get(k) for k in ("class", "text")} for w in inspection.get("chain") or []]},
            "form_source": load(run_dir / "form" / "form-source.json"),
            "copy": {key: copy_.get(key) for key in ("files", "md_sha256", "removal", "kept")}
            | {"source_unchanged": (copy_.get("source_check") or {}).get("unchanged")},
            "session_errors": [entry for entry in (copy_.get("session_log") or {}).get("entries", [])
                               if entry.get("event", "").endswith(("Err", "Error"))][:10],
            "visual": [{key: row.get(key) for key in ("name", "status", "reason", "diff_pixels", "diff_box")}
                       for row in stages.get("visual", {}).get("checks", [])],
            "timeout_phase": report.get("timeout_phase"), "shutdown": (report.get("shutdown") or {}).get("status")}


def judge(case, observed):
    if case.get("verify_error"):
        operations = observed["operations"]
        return "confirmed" if observed["run_status"] == "failed" and operations.get("verify", {}).get("status") == "failed" \
            and all(operations.get(name, {}).get("status") == "passed" for name in ("check", "open", "result")) else "contradicted"
    if case.get("blocked"):
        # Refused before 1C opens the form (task 023): the run is blocked with this reason.
        return "confirmed" if observed["run_status"] == "blocked" and case["blocked"] in (
            observed["platform_reason"] or "") else "contradicted"
    if case.get("reason"):
        reason = case["reason"].format(line=case.get("broken_line"))
        return "confirmed" if observed["run_status"] == "failed" and (observed["platform_reason"] or "").startswith(
            reason) else "contradicted"
    if case["value"] == "?":
        return "observed"
    tests = {row["name"]: row for row in observed["tests"]}
    met = all(row.get("expectation_met") for row in tests.values()) and len(tests) == (3 if "verify_value" in case else 2)
    for record, expected in case.get("fields_open", {}).items():
        field = ((observed["inspection"]["fields_open"] or {}).get(str(record)) or {}).get("text")
        met = met and (field or "").strip() == expected
    if case.get("wrong_expectation"):
        verification = tests.get("data-verify", {})
        return "confirmed" if observed["run_status"] == "failed" and verification.get("expectation_met") is False \
            and all(tests.get(name, {}).get("expectation_met") for name in ("form-open", "form-result")) else "contradicted"
    if case.get("visual"):
        # The tests pass whatever the appearance; the run's status is the visual stage's.
        statuses = [row["status"] for row in observed["visual"]]
        status = {"passed": "passed", "failed": "failed", "blocked": "blocked"}[case["visual"]]
        return "confirmed" if met and statuses == [case["visual"]] and observed["run_status"] == status \
            else "contradicted"
    if case.get("representation"):
        name, record = case["representation"]
        shown = ((observed["operations"].get("result") or {}).get("representations") or {}).get(name)
        field = ((observed["inspection"]["fields_after"] or {}).get(str(record)) or {}).get("text")
        met = met and shown is not None and shown == (field or "").strip()
    return "confirmed" if met and observed["run_status"] == "passed" else "contradicted"


SCOPE = "task 022: forms of 1Cv7.MD by description on a copy of the base"


def run_series(cases, args, scope=SCOPE):
    stand = load_stand(args.stand)
    base = Path(stand.base)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    extraction = work / "extraction"
    md77.extract(base / "1Cv7.MD", extraction)
    text = args.stand.read_text(encoding="utf-8")
    text, count = re.subn(r"(?m)^launcher = .*$", "launcher = " + json.dumps((HERE / "form_launcher77.py").as_posix()),
                          text)
    if count != 1:
        raise SystemExit("the stand profile has no single launcher line")
    (work / "stand.toml").write_text(text, encoding="utf-8")
    from win32_session77 import base_titles_fingerprint
    listing, titles = basecopy77.listing(base), base_titles_fingerprint()
    rows = []
    for case in cases:
        folder = work / "cases" / case["id"]
        folder.mkdir(parents=True)
        # A relative path in a project profile is the profile's directory's: the baselines are one absolute place.
        project = prepare(case, extraction, folder, args.baselines.resolve() if args.baselines else None)
        completed = subprocess.run([sys.executable, "-m", "harness77", "run", "--project", str(project),
                                    "--stand", str(work / "stand.toml"), "--output-root", str(args.output_root.resolve())],
                                   capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        try:
            summary = json.loads(completed.stdout)
        except ValueError:
            rows.append({"id": case["id"], "verdict": "blocked", "stderr": completed.stderr[-2000:]})
            print(case["id"], "blocked: no run summary", completed.stderr[-500:], file=sys.stderr)
            continue
        observed = observe(Path(summary["run_dir"]))
        verdict = judge(case, observed)
        rows.append({"id": case["id"], "form_object": case_object(case), "expected_value": case["value"],
                     "expected_reason": case.get("reason", "").format(line=case.get("broken_line")) or None,
                     "verdict": verdict, "observed": observed,
                     "run_id": summary["run_id"], "project_sha256": sha256(project),
                     "run_json_sha256": sha256(Path(summary["run_dir"]) / "run.json")})
        print(case["id"], verdict, observed["run_status"], observed["platform_reason"], observed["tests"],
              observed["inspection"]["found"], observed["inspection"]["reason"], file=sys.stderr, flush=True)
    after = {"base_unchanged": basecopy77.listing(base) == listing, "base_list_unchanged": base_titles_fingerprint() == titles}
    evidence = {"schema_version": 1, "scope": scope,
                "generated": datetime.datetime.now().astimezone().isoformat(),
                "stand": "local-7.70.027 (base-for-test, pinned)", "metadata_sha256": sha256(base / "1Cv7.MD"),
                "template_sha256": sha256(TEMPLATE), "series": after, "cases": rows}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with open(args.evidence, "x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=1)
    print("series", after, file=sys.stderr)
    return 0 if all(r["verdict"] in ("confirmed", "observed") for r in rows) and all(after.values()) else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path, help="new local directory for generated cases")
    parser.add_argument("--output-root", type=Path, default=ROOT / ".artifacts" / "runs")
    parser.add_argument("--evidence", required=True, type=Path, help="new JSON file with all results")
    parser.add_argument("--case", action="append", default=[], help="run only these case ids")
    parser.add_argument("--baselines", type=Path, help="baselines of the visual cases (outside --work)")
    parser.add_argument("--dry-run", action="store_true", help="prepare the cases and build them, no 1C")
    args = parser.parse_args(argv)
    if os.path.lexists(args.evidence):
        parser.error(f"evidence file exists: {args.evidence}")
    unknown = set(args.case) - {c["id"] for c in CASES}
    if unknown:
        parser.error(f"unknown case ids: {sorted(unknown)}")
    cases = [c for c in CASES if not args.case or c["id"] in args.case]
    if any(c.get("visual") for c in cases) and args.baselines is None:
        parser.error("the visual cases need --baselines")
    return args, [c for c in CASES if not args.case or c["id"] in args.case]


def dry_run(cases, args):
    """Every case's configuration builds from the stand base (md-build) without starting 1C."""
    stand = load_stand(args.stand)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    md77.extract(Path(stand.base) / "1Cv7.MD", work / "extraction")
    for case in cases:
        folder = work / "cases" / case["id"]
        folder.mkdir(parents=True)
        prepare(case, work / "extraction", folder, args.baselines)
        report = md77.build(Path(stand.base) / "1Cv7.MD", folder / "configuration", folder / "1Cv7.MD")
        print(case["id"], [row["file"] for row in report["changed"]],
              [(row["file"], len(row["changes"])) for row in report["changed_forms"]], file=sys.stderr)
    return 0


if __name__ == "__main__":
    arguments_, cases_ = arguments()
    raise SystemExit(dry_run(cases_, arguments_) if arguments_.dry_run else run_series(cases_, arguments_))
