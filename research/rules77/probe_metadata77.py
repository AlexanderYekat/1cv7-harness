"""Native probes for the metadata name rules (L7712, L7713) through `harness77 run`; task 018.

Every case is one cooperating external processing (probe_rules77) whose construct runs
in Harness77Контроль inside Попытка: the load tells the compile outcome, the marker
`runtime-error:` or `value:` the run outcome. Expectations are fixed here, before the
run ("ok", "error", "?"). Two batch cases check the reading of 1Cv7.MD itself: 1C
lists the names of each class (n-survey) and accesses every name read (a-survey).

Usage (local stand profile, base-for-test, the FIO.ERT template):
  python research/rules77/probe_metadata77.py --stand .local/stage14-native/stand.toml
      --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --metadata .local/bases/base-for-test/1Cv7.MD
      --work .local/stage18-native --evidence .artifacts/stage18-metadata-probes-YYYYMMDD.json
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))

from probe_rules77 import PROBE, ROOT, module_text, observe, project_text, sha256  # noqa: E402


def run_line(statement, result="    Возврат 42;"):
    """The construct on the probe line, then the value the control function returns."""
    return f"    {statement} {PROBE}\n{result}"


MISSING = dict(compile="?", runtime="error")
CASES = [
    # L7712: objects through the global attributes.
    dict(id="g-enum-kind", rule="L7712", control=run_line("З77 = Перечисление.Нет77;"), **MISSING),
    dict(id="g-enum-value", rule="L7712", control=run_line("З77 = Перечисление.Булево.Нет77;"), **MISSING),
    dict(id="g-enum-control", rule="L7712", compile="ok", runtime="ok", value="Да",
         control=run_line("З77 = Перечисление.Булево.Да;", "    Возврат З77.Идентификатор();")),
    dict(id="g-enum-case", rule="L7712", compile="ok", runtime="ok", value="Да",
         control=run_line("З77 = Перечисление.булево.да;", "    Возврат З77.Идентификатор();")),
    dict(id="g-enum-method", rule="L7712", compile="ok", runtime="ok", value="2",
         control=run_line("З77 = Перечисление.Булево.КоличествоЗначений();", "    Возврат З77;")),
    dict(id="g-const", rule="L7712", control=run_line("З77 = Константа.Нет77;"), **MISSING),
    dict(id="g-const-assign", rule="L7712", compile="?", runtime="?", control=run_line("Константа.Нет77 = 1;")),
    dict(id="g-const-control", rule="L7712", compile="ok", runtime="ok", value="42",
         control=run_line("З77 = Константа.АдресОрганизации;")),
    dict(id="g-const-method", rule="L7712", compile="ok", runtime="ok", value="42",
         control=run_line("З77 = Константа.ПолучитьАтрибут(\"АдресОрганизации\");")),
    dict(id="g-subconto", rule="L7712", control=run_line("З77 = ВидыСубконто.Нет77;"), **MISSING),
    dict(id="g-subconto-control", rule="L7712", compile="ok", runtime="ok", value="Договоры",
         control=run_line("З77 = ВидыСубконто.Договоры;", "    Возврат З77.Идентификатор();")),
    dict(id="g-plan", rule="L7712", control=run_line("З77 = ПланыСчетов.Нет77;"), **MISSING),
    dict(id="g-plan-control", rule="L7712", compile="ok", runtime="ok", value="Основной",
         control=run_line("З77 = ПланыСчетов.Основной;", "    Возврат З77.Идентификатор();")),
    # L7713: "Type.Kind" strings in the arguments of functions taking a type name.
    dict(id="s-catalog", rule="L7713", compile="ok", runtime="error",
         control=run_line("О77 = СоздатьОбъект(\"Справочник.Нет77\");")),
    dict(id="s-catalog-control", rule="L7713", compile="ok", runtime="ok", value="Банки",
         control=run_line("О77 = СоздатьОбъект(\"Справочник.Банки\");", "    Возврат О77.Вид();")),
    dict(id="s-catalog-case", rule="L7713", compile="ok", runtime="ok", value="Банки",
         control=run_line("О77 = СоздатьОбъект(\"справочник.банки\");", "    Возврат О77.Вид();")),
    dict(id="s-document", rule="L7713", compile="ok", runtime="error",
         control=run_line("О77 = СоздатьОбъект(\"Документ.Нет77\");")),
    dict(id="s-document-control", rule="L7713", compile="ok", runtime="ok", value="АвансовыйОтчет",
         control=run_line("О77 = СоздатьОбъект(\"Документ.АвансовыйОтчет\");", "    Возврат О77.Вид();")),
    dict(id="s-register", rule="L7713", compile="ok", runtime="error",
         control=run_line("О77 = СоздатьОбъект(\"Регистр.Нет77\");"), note="в базе стенда регистров нет"),
    dict(id="s-account", rule="L7713", compile="ok", runtime="error",
         control=run_line("О77 = СоздатьОбъект(\"Счет.Нет77\");")),
    dict(id="s-account-control", rule="L7713", compile="ok", runtime="ok", value="42",
         control=run_line("О77 = СоздатьОбъект(\"Счет.Основной\");")),
    dict(id="s-empty", rule="L7713", compile="ok", runtime="?",
         control=run_line("З77 = ПолучитьПустоеЗначение(\"Справочник.Нет77\");",
                          "    Возврат \"[\" + ТипЗначенияСтр(З77) + \"]\";")),
    dict(id="s-empty-control", rule="L7713", compile="ok", runtime="ok", value="[Справочник]",
         control=run_line("З77 = ПолучитьПустоеЗначение(\"Справочник.Банки\");",
                          "    Возврат \"[\" + ТипЗначенияСтр(З77) + \"]\";")),
    dict(id="s-column", rule="L7713", compile="ok", runtime="?",
         control="    Т77 = СоздатьОбъект(\"ТаблицаЗначений\");\n    Тип77 = \"\";\n"
                 + run_line("Т77.НоваяКолонка(\"К\", \"Справочник.Нет77\");",
                            "    Т77.ПолучитьПараметрыКолонки(1, Тип77);\n    Возврат \"[\" + Тип77 + \"]\";")),
    dict(id="s-column-control", rule="L7713", compile="ok", runtime="ok", value="[Справочник.Банки]",
         control="    Т77 = СоздатьОбъект(\"ТаблицаЗначений\");\n    Тип77 = \"\";\n"
                 + run_line("Т77.НоваяКолонка(\"К\", \"Справочник.Банки\");",
                            "    Т77.ПолучитьПараметрыКолонки(1, Тип77);\n    Возврат \"[\" + Тип77 + \"]\";")),
    dict(id="s-literal", rule="L7713", compile="ok", runtime="ok", value="42",
         control=run_line("Т77 = \"Справочник.Нет77\";"), note="строка вне аргумента функции не проверяется"),
    # Forms with a missing name; an existing one would open a window, so it is not executed.
    dict(id="f-report", rule="L7713", compile="ok", runtime="?", control=run_line("ОткрытьФорму(\"Отчет.Нет77\");")),
    dict(id="f-processing", rule="L7713", compile="ok", runtime="?",
         control=run_line("ОткрытьФорму(\"Обработка.Нет77\");")),
    dict(id="f-journal", rule="L7713", compile="ok", runtime="?", control=run_line("ОткрытьФорму(\"Журнал.Нет77\");")),
    dict(id="f-catalog", rule="L7713", compile="ok", runtime="?",
         control=run_line("ОткрытьФорму(\"Справочник.Нет77\");")),
    dict(id="f-modal", rule="L7713", compile="ok", runtime="?",
         control=run_line("ОткрытьФормуМодально(\"Обработка.Нет77\");")),
    dict(id="f-hash", rule="L7713", compile="ok", runtime="?",
         control=run_line("ОткрытьФорму(\"Обработка.Нет77#Ключ\");")),
    # Added after the first lint of the base's own 1Cv7.MD: its modules name objects its
    # metadata lacks (a trimmed test configuration). The lines as the modules have them.
    dict(id="c-enum-value", rule="L7712", compile="ok", runtime="error",
         control=run_line("З77 = Перечисление.ВидыРасчетовСПокупателями.РасчетыЗаТовары;"),
         note="Transact_Number308, строка 173"),
    dict(id="c-const", rule="L7712", compile="ok", runtime="error",
         control=run_line("Если Константа.ИспользоватьТипыЦен = Нет Тогда З77 = 1; КонецЕсли;"),
         note="Document_Number11012, строка 1518"),
    dict(id="c-catalog", rule="L7713", compile="ok", runtime="error",
         control=run_line("СпрЕдиницы = СоздатьОбъект(\"Справочник.Единицы\");"),
         note="CalcVar_Number25505, строка 27"),
    # Added after s-empty and s-column: a missing kind there is no error, the type loses
    # its kind. The other functions of the rule, expectations by that analogy.
    dict(id="s-insert-column", rule="L7713", compile="ok", runtime="ok", value="[Справочник]",
         control="    Т77 = СоздатьОбъект(\"ТаблицаЗначений\");\n    Тип77 = \"\";\n"
                 + run_line("Т77.ВставитьКолонку(\"К\", 1, \"Справочник.Нет77\");",
                            "    Т77.ПолучитьПараметрыКолонки(1, Тип77);\n    Возврат \"[\" + Тип77 + \"]\";")),
    dict(id="s-column-parameters", rule="L7713", compile="ok", runtime="ok", value="[Справочник]",
         control="    Т77 = СоздатьОбъект(\"ТаблицаЗначений\");\n    Т77.НоваяКолонка(\"К\");\n    Тип77 = \"\";\n"
                 + run_line("Т77.УстановитьПараметрыКолонки(1, \"Справочник.Нет77\");",
                            "    Т77.ПолучитьПараметрыКолонки(1, Тип77);\n    Возврат \"[\" + Тип77 + \"]\";")),
    dict(id="s-access-right", rule="L7713", compile="ok", runtime="?",
         control=run_line("З77 = ПравоДоступа(\"Чтение\", \"Справочник.Нет77\");", "    Возврат З77;")),
    dict(id="s-access-right-control", rule="L7713", compile="ok", runtime="?",
         control=run_line("З77 = ПравоДоступа(\"Чтение\", \"Справочник.Банки\");", "    Возврат З77;")),
    dict(id="f-choice", rule="L7713", compile="ok", runtime="error",
         control=run_line("ОткрытьПодбор(\"Справочник.Нет77\");")),
    # ТипЗначенияСтр does not show the kind of s-empty: Вид() of the empty value does.
    dict(id="s-empty-kind", rule="L7713", compile="ok", runtime="ok", value="[]",
         control=run_line("З77 = ПолучитьПустоеЗначение(\"Справочник.Нет77\");",
                          "    Возврат \"[\" + З77.Вид() + \"]\";")),
    dict(id="s-empty-kind-control", rule="L7713", compile="ok", runtime="ok", value="[Банки]",
         control=run_line("З77 = ПолучитьПустоеЗначение(\"Справочник.Банки\");",
                          "    Возврат \"[\" + З77.Вид() + \"]\";")),
]

# Метаданные.<method>() lists a class; the class names follow metadata77.CLASSES.
LISTED = ["Константа", "Справочник", "Документ", "Перечисление", "Регистр", "Отчет", "Обработка", "Журнал",
          "ПланСчетов", "ВидСубконто"]
COMPARE = """Функция Сверить77(Класс77, Факт77, Ожидание77)
    Лишние77 = ""; Нет77 = ""; Ф77 = СтрЗаменить(Факт77, ";", РазделительСтрок);
    О77 = СтрЗаменить(Ожидание77, ";", РазделительСтрок);
    Всего77 = 0; Прочитано77 = 0;
    Для Н77 = 1 По СтрКоличествоСтрок(Ф77) Цикл
        И77 = СтрПолучитьСтроку(Ф77, Н77);
        Если ПустаяСтрока(И77) = 0 Тогда
            Всего77 = Всего77 + 1;
            Если Найти(";" + ВРег(Ожидание77) + ";", ";" + ВРег(И77) + ";") = 0 Тогда Лишние77 = Лишние77 + "," + И77; КонецЕсли;
        КонецЕсли;
    КонецЦикла;
    Для Н77 = 1 По СтрКоличествоСтрок(О77) Цикл
        И77 = СтрПолучитьСтроку(О77, Н77);
        Если ПустаяСтрока(И77) = 0 Тогда
            Прочитано77 = Прочитано77 + 1;
            Если Найти(";" + ВРег(Факт77) + ";", ";" + ВРег(И77) + ";") = 0 Тогда Нет77 = Нет77 + "," + И77; КонецЕсли;
        КонецЕсли;
    КонецЦикла;
    Возврат "|" + Класс77 + ":1С=" + СокрЛП(Всего77) + ",прочитано=" + СокрЛП(Прочитано77)
        + ",лишние=" + Лишние77 + ",нет=" + Нет77;
КонецФункции
"""


def assign_chunks(variable, names, width=300):
    """Statements building ";"-joined names in short lines: a long literal is no part of the probe."""
    lines, chunk = [f'        {variable} = "";'], []
    for name in names:
        if chunk and len(";".join(chunk + [name])) > width:
            lines.append(f'        {variable} = {variable} + ";{";".join(chunk)}";')
            chunk = []
        chunk.append(name)
    if chunk:
        lines.append(f'        {variable} = {variable} + ";{";".join(chunk)}";')
    return "\n".join(lines)


def read_names(metadata_path):
    from harness77 import metadata77
    metadata = metadata77.load(metadata_path)
    objects = metadata.objects()
    values = {kind: metadata.enum_values(kind) for kind in objects["Перечисление"].values()}
    return metadata, objects, values


def names_case(metadata_path):
    """n-survey: 1C lists every class by Метаданные and compares with the names read here."""
    _, objects, values = read_names(metadata_path)
    blocks = []
    for name in LISTED:
        blocks.append(f"""    Попытка
{assign_chunks("Ож77", objects[name].values())}
        С77 = "";
        Для Н77 = 1 По Метаданные.{name}() Цикл
            С77 = С77 + ";" + Метаданные.{name}(Н77).Идентификатор;
        КонецЦикла;
        Ответ77 = Ответ77 + Сверить77("{name}", С77, Ож77);
    Исключение
        Ответ77 = Ответ77 + "|{name}:E:" + ОписаниеОшибки();
    КонецПопытки;""")
    expected = [f"{kind}.{value}" for kind, kinds in values.items() for value in kinds.values()]
    blocks.append(f"""    Попытка
{assign_chunks("Ож77", expected)}
        С77 = "";
        Для Н77 = 1 По Метаданные.Перечисление() Цикл
            П77 = Метаданные.Перечисление(Н77);
            Для К77 = 1 По П77.Значение() Цикл
                С77 = С77 + ";" + П77.Идентификатор + "." + П77.Значение(К77).Идентификатор;
            КонецЦикла;
        КонецЦикла;
        Ответ77 = Ответ77 + Сверить77("Значения", С77, Ож77);
    Исключение
        Ответ77 = Ответ77 + "|Значения:E:" + ОписаниеОшибки();
    КонецПопытки;""")
    control = "    Ответ77 = \"\";\n" + "\n".join(blocks) + "\n    Возврат Ответ77;"
    return dict(id="n-survey", rule="metadata", compile="ok", runtime="ok", procedures=COMPARE, control=control,
                note="1С перечисляет имена по классам (Метаданные) и сверяет с прочитанными из 1Cv7.MD")


def access_case(metadata_path):
    """a-survey: every name read is accessed the way module code names it; failures are listed."""
    _, objects, values = read_names(metadata_path)
    accesses = [f"Перечисление.{kind}" for kind in values]
    accesses += [f"Перечисление.{kind}.{value}" for kind, kinds in values.items() for value in kinds.values()]
    accesses += [f"Константа.{name}" for name in objects["Константа"].values()]
    accesses += [f"ВидыСубконто.{name}" for name in objects["ВидСубконто"].values()]
    accesses += [f"ПланыСчетов.{name}" for name in objects["ПланСчетов"].values()]
    created = [f"Справочник.{name}" for name in objects["Справочник"].values()]
    created += [f"Документ.{name}" for name in objects["Документ"].values()]
    created += [f"Счет.{name}" for name in objects["ПланСчетов"].values()]
    created += [f"Регистр.{name}" for name in objects["Регистр"].values()]
    lines = [f'    Попытка З77 = {item}; Исключение Отказ77 = Отказ77 + ";{item}"; КонецПопытки;'
             for item in accesses]
    lines += [f'    Попытка З77 = СоздатьОбъект("{item}"); Исключение Отказ77 = Отказ77 + ";{item}"; КонецПопытки;'
              for item in created]
    control = ("    Отказ77 = \"\";\n" + "\n".join(lines)
               + f"\n    Возврат \"обращений={len(lines)};отказы=\" + Отказ77;")
    return dict(id="a-survey", rule="metadata", compile="ok", runtime="ok", control=control,
                value=f"обращений={len(lines)};отказы=",
                note="обращение к каждому имени из 1Cv7.MD: значения перечислений, константы, виды субконто, "
                     "планы счетов; СоздатьОбъект справочников, документов, счетов, регистров")


def judge(case, observed):
    """The outcome against the expectation; a module 1C did not load leaves the run outcome open."""
    if observed["compile"] == "blocked":
        return "blocked"
    checks = []
    if case["compile"] != "?":
        checks.append(observed["compile"] == case["compile"])
    if observed["compile"] == "ok":
        if case.get("runtime") not in (None, "?"):
            checks.append(observed["runtime"] == case["runtime"])
        if case.get("value") is not None:
            checks.append(observed["value"] == case["value"])
    if not checks:
        return "observed"
    return "confirmed" if all(checks) else "contradicted"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path, help="1Cv7.MD of the stand base")
    parser.add_argument("--work", required=True, type=Path, help="local directory for generated cases")
    parser.add_argument("--output-root", type=Path, default=ROOT / ".artifacts" / "runs")
    parser.add_argument("--evidence", required=True, type=Path, help="new JSON file with all results")
    parser.add_argument("--case", action="append", default=[], help="run only these case ids")
    args = parser.parse_args(argv)
    if os.path.lexists(args.evidence):
        parser.error(f"evidence file exists: {args.evidence}")
    cases = CASES + [names_case(args.metadata), access_case(args.metadata)]
    if args.case:
        unknown = set(args.case) - {c["id"] for c in cases}
        if unknown:
            parser.error(f"unknown case ids: {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in args.case]
    template = args.template.resolve(strict=True)
    rows = []
    for case in cases:
        folder = args.work.resolve() / "cases" / case["id"]
        folder.mkdir(parents=True, exist_ok=True)
        text = module_text(case)
        (folder / "module.1s").write_text(text, encoding="utf-8", newline="\n")
        deadline = 300 if case["id"].endswith("-survey") else 60
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
        verdict = judge(case, observed)
        rows.append({"id": case["id"], "rule": case["rule"], "note": case.get("note"),
                     "expected": {k: case.get(k) for k in ("compile", "runtime", "value")},
                     "probe_line": probe_line,
                     "construct": next((line.replace(PROBE, "").strip() for line in text.splitlines()
                                        if PROBE in line), None),
                     "observed": observed, "verdict": verdict, "run_id": summary["run_id"],
                     "module_sha256": sha256(folder / "module.1s"),
                     "ert_sha256": (report.get("artifact") or {}).get("sha256"),
                     "run_json_sha256": sha256(run_dir / "run.json")})
        print(case["id"], verdict, observed["compile"], observed["runtime"], (observed["value"] or "")[:200],
              (observed["runtime_error"] or "")[:200],
              [d.get("message") for d in observed["diagnostics"]][:2], file=sys.stderr, flush=True)
    evidence = {"schema_version": 1, "scope": "task 018 metadata name probes on real 1C 7.7",
                "generated": datetime.datetime.now().astimezone().isoformat(),
                "stand": "local-7.70.027 (base-for-test, pinned)", "template_sha256": sha256(template),
                "metadata_sha256": sha256(args.metadata), "cases": rows}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with open(args.evidence, "x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=1)
    return 0 if all(r["verdict"] in ("confirmed", "observed") for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
