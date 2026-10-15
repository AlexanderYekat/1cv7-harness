"""Native probes for the stage-5 lint rules (L7708-L7711) through `harness77 run`.

Every case is one cooperating external processing (the stage-4 headless contract)
with a single construct under test. Expectations are fixed here, before the run:
"error" - 1C 7.7 must reject the module, "ok" - it must load/execute, "?" - the
outcome is unknown and the probe establishes it. The survey case compiles each
built-in name through 1C++ `ВыполняемыйМодуль` in three positions in one session.

Usage (local stand profile, template with the Фамилия/Имя/Отчество dialog):
  python research/rules77/probe_rules77.py --stand .local/stage4-native/stand-native.toml
      --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --work .local/stage5-native --evidence .artifacts/stage5-rule-probes-YYYYMMDD.json
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROBE = "// probe-line"

SKELETON = """{vars}
{procedures}
Функция Harness77Контроль() Экспорт
{control}
КонецФункции

Процедура Выполнить()
КонецПроцедуры

Процедура Очистить()
КонецПроцедуры

Процедура ПриОткрытии()
    СтатусВозврата(0);
    Параметры77 = Форма.Параметр;
    Команда77 = Параметры77.ПолучитьЗначение(1);
    Параметры77.ДобавитьЗначение("loaded:harness77");
    Если Команда77 = "execute" Тогда
        Попытка
            Ответ77 = Harness77Контроль();
            Параметры77.ДобавитьЗначение("value:" + СокрЛП(Строка(Ответ77)));
        Исключение
            Параметры77.ДобавитьЗначение("runtime-error:" + ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
    Параметры77.ДобавитьЗначение("completed:harness77");
КонецПроцедуры
{body}"""

RETURN_42 = "    Возврат 6 * 7;"


def reader(statement):
    """A procedure that is compiled but never called: compile-only probes."""
    return "Процедура Читать77()\n" + statement + " " + PROBE + "\nКонецПроцедуры\n"


CASES = [
    # L7708: built-in function names declared as identifiers.
    dict(id="b-param-stroka", rule="L7708", compile="error", message="Ожидается имя формального параметра",
         procedures="Процедура Проба77(Знач Строка) " + PROBE + "\nКонецПроцедуры\n",
         note="повтор корня P1"),
    dict(id="b-param-chislo", rule="L7708", compile="?",
         procedures="Процедура Проба77(Число) " + PROBE + "\nКонецПроцедуры\n"),
    dict(id="b-var-data", rule="L7708", compile="?", vars="Перем Дата; " + PROBE),
    dict(id="b-assign-min", rule="L7708", compile="?", procedures=reader("    Мин = 1;")),
    dict(id="b-for-maks", rule="L7708", compile="?",
         procedures=reader("    Для Макс = 1 По 2 Цикл КонецЦикла;")),
    dict(id="b-assign-soobshit", rule="L7708", compile="?", procedures=reader("    Сообщить = 1;")),
    dict(id="b-param-control", rule="L7708", compile="ok",
         procedures="Процедура Проба77(Знач Строка1) " + PROBE + "\nКонецПроцедуры\n"),
    dict(id="b-assign-method-name", rule="L7708", compile="ok",
         procedures=reader("    ПолучитьПроводку = 1;")),
    # L7709: more arguments than the method accepts.
    dict(id="m-too-many", rule="L7709", compile="ok", runtime="error", message="Слишком много параметров",
         control="    Т77 = СоздатьОбъект(\"ТаблицаЗначений\");\n    Возврат Т77.КоличествоСтрок(1); " + PROBE),
    # Added after m-too-many contradicted its expectation (ТаблицаЗначений ignores the
    # extra argument): the KUDiR case itself and one more object, outcomes unknown.
    dict(id="m-operation", rule="L7709", compile="ok", runtime="?",
         control="    О77 = СоздатьОбъект(\"Операция\");\n    Возврат О77.ПолучитьПроводку(1); " + PROBE,
         note="случай КУДиР KUDIR4_20261011_001"),
    dict(id="m-operation-control", rule="L7709", compile="ok", runtime="?",
         control="    О77 = СоздатьОбъект(\"Операция\");\n    Возврат О77.ПолучитьПроводку(); " + PROBE),
    dict(id="m-list", rule="L7709", compile="ok", runtime="?",
         control="    С77 = СоздатьОбъект(\"СписокЗначений\");\n    Возврат С77.РазмерСписка(1); " + PROBE),
    dict(id="m-control", rule="L7709", compile="ok", runtime="ok", value="42",
         control="    Т77 = СоздатьОбъект(\"ТаблицаЗначений\");\n    Возврат Т77.КоличествоСтрок() + 42; " + PROBE),
    # L7710: long physical lines.
    dict(id="l-comment-600", rule="L7710", compile="?", runtime="ok", value="42",
         procedures="// " + "к" * 597 + " " + "\n", control=RETURN_42),
    dict(id="l-comment-5000", rule="L7710", compile="?", runtime="ok", value="42",
         procedures="// " + "к" * 4997 + " " + "\n", control=RETURN_42),
    dict(id="l-literal-600", rule="L7710", compile="?", runtime="?",
         control="    С77 = \"" + "ж" * 586 + "\"; " + PROBE + "\n    Возврат СтрДлина(С77);"),
    dict(id="l-literal-5000", rule="L7710", compile="?", runtime="?",
         control="    С77 = \"" + "ж" * 4986 + "\"; " + PROBE + "\n    Возврат СтрДлина(С77);"),
    # L7711: reads of names that are not declared at that point.
    dict(id="u-undeclared", rule="L7711", compile="error", message="Переменная не определена",
         procedures=reader("    Сообщить(Неизвестная77);")),
    dict(id="u-read-before-assign", rule="L7711", compile="error", message="Переменная не определена",
         procedures="Процедура Читать77()\n    А77 = Б77; " + PROBE + "\n    Б77 = 1;\nКонецПроцедуры\n",
         note="повтор корня P1, строка 101"),
    dict(id="u-other-procedure", rule="L7711", compile="?",
         procedures="Процедура Задать77()\n    Х77 = 1;\nКонецПроцедуры\n" + reader("    Сообщить(Х77);")),
    dict(id="u-module-body", rule="L7711", compile="?", procedures=reader("    Сообщить(М77);"),
         body="М77 = 1;"),
    dict(id="u-module-var", rule="L7711", compile="ok", vars="Перем П77;",
         procedures=reader("    Сообщить(П77);")),
    dict(id="u-procedure-var", rule="L7711", compile="ok",
         procedures="Процедура Читать77()\n    Перем Л77;\n    Сообщить(Л77); " + PROBE + "\nКонецПроцедуры\n"),
    dict(id="u-dialog", rule="L7711", compile="ok", procedures=reader("    Сообщить(Фамилия);")),
    dict(id="u-dialog-missing", rule="L7711", compile="error", message="Переменная не определена",
         procedures=reader("    Сообщить(Фамилия2);")),
    dict(id="u-arg-method", rule="L7711", compile="?",
         procedures=reader("    Т77 = СоздатьОбъект(\"ТаблицаЗначений\");\n"
                           "    Т77.ПолучитьПараметрыКолонки(1, Тип77, Длина77);")),
    dict(id="u-arg-own", rule="L7711", compile="?",
         procedures="Процедура Задать77(Рез)\n    Рез = 1;\nКонецПроцедуры\n" + reader("    Задать77(Выход77);")),
    dict(id="u-loop-counter", rule="L7711", compile="ok",
         procedures=reader("    Для Н77 = 1 По 2 Цикл Сообщить(Н77); КонецЦикла;")),
    dict(id="u-globals", rule="L7711", compile="?",
         procedures=reader("    Г77 = Константа; Г77 = Перечисление; Г77 = Метаданные; Г77 = ПланыСчетов;\n"
                           "    Г77 = ВидыСубконто; Г77 = Регистры; Г77 = ФС; Г77 = Форма;\n"
                           "    Г77 = РазделительСтрок; Г77 = СимволТабуляции; Г77 = РазделительСтраниц;")),
    dict(id="u-form-parameter", rule="L7711", compile="?", procedures=reader("    Сообщить(Параметр);")),
    # Added after u-globals stopped at Регистры (no operational-accounting component in
    # this configuration): the names after it, each in its own statement line.
    dict(id="u-globals-2", rule="L7711", compile="?",
         procedures="Процедура Читать77()\n    Г77 = ФС;\n    Г77 = Форма;\n    Г77 = РазделительСтрок;\n"
                    "    Г77 = СимволТабуляции;\n    Г77 = РазделительСтраниц; " + PROBE + "\nКонецПроцедуры\n"),
]


def survey_names():
    """Every built-in function name in the catalog and dll, plus controls."""
    sys.path.insert(0, str(ROOT / "src"))
    from harness77.catalog77 import load_packaged
    catalog = load_packaged()
    names = []
    for item in catalog["items"]:
        if item["kind"] in ("global_function", "global_constant"):
            names += [item["name_ru"], item["name_en"]]
    names += [p[key] for p in catalog["pairs"] if 1640 <= p["id"] <= 1720 for key in ("ru", "en")]
    names += ["ПолучитьПроводку", "КоличествоСтрок", "Документ", "Справочник", "ТаблицаЗначений",
              "Константа", "Перечисление", "Метаданные", "ФС", "Форма", "Проба77Имя"]
    seen, result = set(), []
    for name in names:
        if name and name.casefold() not in seen and name.replace("_", "a").isalnum():
            seen.add(name.casefold())
            result.append(name)
    return result


def survey_case():
    adds = "\n".join(f'    Имена77.ДобавитьЗначение("{name}");' for name in survey_names())
    procedures = """Функция Компилировать77(Т77)
    Попытка
        М77 = СоздатьОбъект("ВыполняемыйМодуль");
        М77.УстановитьМодуль(Т77);
        Возврат СокрЛП(Строка(М77.КомпилироватьМодуль()));
    Исключение
        Возврат "E";
    КонецПопытки;
КонецФункции
"""
    control = f"""    Имена77 = СоздатьОбъект("СписокЗначений");
{adds}
    Ответ77 = "";
    Для Н77 = 1 По Имена77.РазмерСписка() Цикл
        И77 = Имена77.ПолучитьЗначение(Н77);
        П77 = Компилировать77("Процедура П77(Знач " + И77 + ")" + РазделительСтрок + "КонецПроцедуры");
        А77 = Компилировать77("Процедура П77()" + РазделительСтрок + И77 + " = 1;" + РазделительСтрок + "КонецПроцедуры");
        В77 = Компилировать77("Перем " + И77 + ";");
        Ответ77 = Ответ77 + И77 + "=" + П77 + "," + А77 + "," + В77 + ";";
    КонецЦикла;
    Возврат Ответ77;"""
    return dict(id="b-survey", rule="L7708", compile="ok", runtime="ok", procedures=procedures,
                control=control, note="пакет: параметр, присваивание, Перем через ВыполняемыйМодуль 1С++")


def platform_names():
    """Every platform name the catalog knows (items, pairs, quoted folder names), unreserved."""
    import re
    sys.path.insert(0, str(ROOT / "src"))
    from harness77.catalog77 import load_packaged
    catalog = load_packaged()
    reserved = {n.casefold() for n in catalog["reserved"]["names"]}
    names = [n for item in catalog["items"] for n in (item["name_ru"], item["name_en"])]
    names += [p[key] for p in catalog["pairs"] for key in ("ru", "en")]
    names += [m for item in catalog["items"] for m in re.findall(r"''(\w+)''", item["folder"])]
    names += ["Неизвестная77"]
    seen, result = set(), []
    for name in names:
        key = (name or "").casefold()
        if name and re.fullmatch(r"[A-Za-zА-Яа-яЁё_]\w*", name) and key not in seen and key not in reserved:
            seen.add(key)
            result.append(name)
    return result


def readable_case():
    adds = "\n".join(f'    Имена77.ДобавитьЗначение("{name}");' for name in platform_names())
    procedures = survey_case()["procedures"]
    control = f"""    Имена77 = СоздатьОбъект("СписокЗначений");
{adds}
    Ответ77 = "total=" + СокрЛП(Строка(Имена77.РазмерСписка()));
    Для Н77 = 1 По Имена77.РазмерСписка() Цикл
        И77 = Имена77.ПолучитьЗначение(Н77);
        Если Компилировать77("Процедура П77()" + РазделительСтрок + "Х77 = " + И77 + ";" + РазделительСтрок + "КонецПроцедуры") = "1" Тогда
            Ответ77 = Ответ77 + ";" + И77;
        КонецЕсли;
    КонецЦикла;
    Возврат Ответ77;"""
    return dict(id="u-survey", rule="L7711", compile="ok", runtime="ok", procedures=procedures,
                control=control, note="пакет: какие имена платформы читаются без объявления (ВыполняемыйМодуль)")


def module_text(case):
    return SKELETON.format(vars=case.get("vars", ""), procedures=case.get("procedures", ""),
                           control=case.get("control", RETURN_42), body=case.get("body", ""))


def project_text(template, deadline):
    return f"""schema_version = 1
[project]
id = "rule-probe"
[build]
template = {json.dumps(str(template))}
source = "module.1s"
encoding = "utf-8"
[[platform.tests]]
name = "probe"
command = "execute"
expect = "passed"
[deadlines]
open_timeout_s = 60
calculation_timeout_s = {deadline}
cancel_timeout_s = 15
shutdown_timeout_s = 30
total_timeout_s = {deadline + 120}
"""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observe(run_dir):
    report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    stages = {s["stage"]: s for s in report["stages"]}
    platform = stages.get("platform_check", {})
    observed = {"run_status": report["status"], "platform_status": platform.get("status"),
                "platform_reason": platform.get("reason"), "platform_checked": report.get("platform_checked"),
                "diagnostics": platform.get("diagnostics", []), "shutdown": report.get("shutdown"),
                "runtime": None, "runtime_error": None, "value": None}
    if platform.get("reason") == "compilation_failed":
        observed["compile"] = "error"
    elif (platform.get("load") or {}).get("status") == "passed":
        observed["compile"] = "ok"
    else:
        observed["compile"] = "blocked"
    events = run_dir / "native" / "ert-events.jsonl"
    if observed["compile"] == "ok" and events.exists():
        for line in events.read_text(encoding="utf-16").splitlines():
            event = json.loads(line)
            if event.get("kind") == "ert" and event.get("name") == "execute":
                lines = event.get("value", "").splitlines()
                error = next((x.split(":", 1)[1] for x in lines if x.startswith("runtime-error:")), None)
                value = next((x.split(":", 1)[1] for x in lines if x.startswith("value:")), None)
                observed["runtime"] = "error" if error is not None else ("ok" if value is not None else None)
                observed["runtime_error"], observed["value"] = error, value
    return report, observed


def judge(case, observed, probe_line):
    checks = []
    if case["compile"] != "?":
        checks.append(observed["compile"] == case["compile"])
    if case.get("runtime") not in (None, "?"):
        checks.append(observed["runtime"] == case["runtime"])
    if case.get("value") is not None:
        checks.append(observed["value"] == case["value"])
    if case.get("message"):
        texts = [d.get("message", "") for d in observed["diagnostics"]] + [observed["runtime_error"] or ""]
        checks.append(any(case["message"] in text for text in texts))
    if observed["compile"] == "error" and probe_line is not None and case["compile"] == "error":
        checks.append(any(d.get("line") == probe_line for d in observed["diagnostics"]))
    if observed["compile"] == "blocked":
        return "blocked"
    if not checks:
        return "observed"
    return "confirmed" if all(checks) else "contradicted"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path, help="local directory for generated cases")
    parser.add_argument("--output-root", type=Path, default=ROOT / ".artifacts" / "runs")
    parser.add_argument("--evidence", required=True, type=Path, help="new JSON file with all results")
    parser.add_argument("--case", action="append", default=[], help="run only these case ids")
    args = parser.parse_args(argv)
    if os.path.lexists(args.evidence):
        parser.error(f"evidence file exists: {args.evidence}")
    cases = CASES + [survey_case(), readable_case()]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    template = args.template.resolve(strict=True)
    rows = []
    for case in cases:
        folder = args.work.resolve() / "cases" / case["id"]
        folder.mkdir(parents=True, exist_ok=True)
        text = module_text(case)
        (folder / "module.1s").write_text(text, encoding="utf-8", newline="\n")
        deadline = 600 if case["id"] in ("b-survey", "u-survey") else 60
        (folder / "project.toml").write_text(project_text(template, deadline), encoding="utf-8")
        probe_line = next((n for n, line in enumerate(text.splitlines(), 1) if PROBE in line), None)
        completed = subprocess.run([sys.executable, "-m", "harness77", "run", "--project", str(folder / "project.toml"),
                                    "--stand", str(args.stand.resolve()), "--output-root", str(args.output_root.resolve())],
                                   capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        try:
            summary = json.loads(completed.stdout)
        except ValueError:
            rows.append({"id": case["id"], "verdict": "blocked", "stderr": completed.stderr[-2000:]})
            print(case["id"], "blocked: no run summary", file=sys.stderr)
            continue
        run_dir = Path(summary["run_dir"])
        report, observed = observe(run_dir)
        verdict = judge(case, observed, probe_line)
        row = {"id": case["id"], "rule": case["rule"], "note": case.get("note"),
               "expected": {k: case.get(k) for k in ("compile", "runtime", "value", "message")},
               "probe_line": probe_line,
               "construct": next((line.replace(PROBE, "").strip() for line in text.splitlines() if PROBE in line), None),
               "observed": observed, "verdict": verdict, "run_id": summary["run_id"],
               "module_sha256": sha256(folder / "module.1s"),
               "ert_sha256": (report.get("artifact") or {}).get("sha256"),
               "run_json_sha256": sha256(run_dir / "run.json")}
        if case["rule"] == "L7710":
            row["max_line_length"] = max(len(line) for line in text.splitlines())
        rows.append(row)
        print(case["id"], verdict, observed["compile"], observed["runtime"],
              [d.get("message") for d in observed["diagnostics"]][:2], file=sys.stderr)
    evidence = {"schema_version": 1, "scope": "stage-5 lint rule probes on real 1C 7.7",
                "generated": datetime.datetime.now().astimezone().isoformat(),
                "stand": "local-7.70.027 (base-for-test, pinned)", "template_sha256": sha256(template),
                "cases": rows}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with open(args.evidence, "x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=1)
    return 0 if all(r["verdict"] in ("confirmed", "observed") for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
