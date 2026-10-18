"""Native probes for task 009: how 1C 7.7 continues after a compile error.

Every K case is one cooperating external processing (the stage-4 headless
contract) with one defect and up to three signals, run through `harness77 run`:
  late   - `Процедура Поздняя77() Далее` at the top, defined at the end of the
           module: its "объявлена, но не определена" means compilation stopped early;
  beacon - `Х77 = Неизвестная77;` after the defect: its "Переменная не определена"
           means compilation went past the defect;
  link   - a call of `НетТакой77()`: "Процедура не обнаружена" means linking ran.
P1n/P2n load the KUDiR corpus cases (template = the case ERT, module = the module
extracted from it) and compare the native protocol with the owner's Configurator one.
Expectations are fixed here, before the run (docs/tasks/009-protocol-root-cascade.md);
None means the probe establishes the outcome.

Usage:
  python research/protocol77/probe_cascade77.py --stand .local/stage4-native/stand-native.toml
      --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --corpus research/kudir/corpus --work .local/stage9-native
      --evidence .artifacts/protocol/probes-YYYYMMDD.json
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

COOPERATE = """Функция Harness77Контроль() Экспорт
    Возврат 6 * 7;
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
"""

HEADER_ERROR = "Ожидается имя формального параметра"
UNDEFINED = "Переменная не определена"
NOT_FOUND = "Процедура не обнаружена"
UNRESOLVED = "Процедура или функция с указанным именем объявлена, но не определена в текущем модуле"
END_PROCEDURE = "Ожидается ключевое слово 'КонецПроцедуры' ('EndProcedure')"


def proc(body, header="Процедура Дефект77()", end="КонецПроцедуры"):
    return f"{header}\n{body}\n{end}\n"


# expect: messages that must appear, as (tag or None, text prefix); "only" lists the
# exact set of messages; beacon/late/link: True, False or None (the probe decides).
CASES = [
    dict(id="K0", defect="", expect=dict(beacon=True, late=False, link=None, at_defect=[]),
         note="только сигналы: идёт ли связывание при ошибке компиляции"),
    dict(id="K1", defect="", signals=("link",),
         expect=dict(only=[("link", NOT_FOUND + " (НетТакой77)")]), note="одно связывание, как P2"),
    dict(id="K2", defect="", signals=("late-undefined",),
         expect=dict(only=[(None, UNRESOLVED + " (Поздняя77)")]),
         note="объявление Далее без определения; позиция сообщения — устанавливается"),
    dict(id="K3", defect=proc("    А77 = ; // probe-defect"),
         expect=dict(at_defect=["Ожидается выражение"], beacon=None, late=None, link=None)),
    dict(id="K4", defect=proc("    А77 = 1;\n    Возврат А77 + ; // probe-defect",
                              header="Функция Дефект77()", end="КонецФункции"),
         expect=dict(at_defect=["Ошибка в выражении"], beacon=None, late=None, link=None)),
    dict(id="K5", defect=proc("    Тогда = 1; // probe-defect"),
         expect=dict(at_defect=["Неопознанный оператор"], beacon=None, late=None, link=None)),
    dict(id="K6", defect=proc("    А77 = 1 // probe-defect\n    Б77 = 2;"),
         expect=dict(beacon=None, late=None, link=None), note="пропущена ';' — сообщение устанавливается"),
    dict(id="K7", defect=proc("    А77 = 1;\n    Если А77 = 1 Тогда // probe-defect\n        А77 = 2;"),
         expect=dict(beacon=None, late=None, link=None), note="нет КонецЕсли — сообщение устанавливается"),
    dict(id="K8", defect=proc("    А77 = 1;\n    Если А77 = 1 ИЛИ А77 = 2 Тогда // probe-defect\n"
                              "        А77 = 3;\n    КонецЕсли;"),
         expect=dict(at_defect=["Неправильное использование арифметической или строковой операции"],
                     beacon=None, late=None, link=None), note="008 F0-a"),
    dict(id="K9", defect=proc("    Ф77 = 1;\n    Если Ф77 = 1 Тогда\n        Ф77 = Строка + \"x\"; // probe-use\n"
                              "    КонецЕсли;",
                              header="Процедура Дефект77(Знач Путь77, Знач Строка) // probe-defect"),
         expect=dict(at_defect=[HEADER_ERROR], present=[(None, UNDEFINED + " (Ф77)"),
                                                         ("use", "Ожидается символ '('")],
                     beacon=None, late=None, link=None), note="как P1 304"),
    dict(id="K10", defect=proc("    Ф77 = 1;\n    Если Ф77 = 1 Тогда\n        Ф77 = Строка1 + \"x\"; // probe-use\n"
                               "    КонецЕсли;",
                               header="Процедура Дефект77(Знач Путь77, Знач Строка1) // probe-defect"),
         expect=dict(at_defect=[], beacon=True, late=False, link=None), note="контроль K9"),
    dict(id="K11", defect=proc("    Ф77 = 1;\n    Если Ф77 = 1 Тогда\n        Ф77 = Путь77 + \"x\";\n    КонецЕсли;",
                               header="Процедура Дефект77(Знач Путь77, Знач Строка) // probe-defect"),
         expect=dict(at_defect=[HEADER_ERROR], beacon=None, late=None, link=None),
         note="без обращения к Строка: каскад «Переменная не определена (Ф77)» — устанавливается"),
    dict(id="K12", defect="Процедура Дефект77(Знач Строка) Далее // probe-defect\n"
                          "Процедура Другая77() Далее // probe-next\n"
                          + proc("", header="Процедура Другая77()") + proc("", header="Процедура Дефект77(Знач Стр77)"),
         expect=dict(at_defect=[HEADER_ERROR], present=[("next", END_PROCEDURE)],
                     beacon=None, late=None, link=None), note="как P1 63/64"),
    dict(id="K13", defect=proc("    А77 = 1;", header="Процедура Дубль77() // probe-defect")
                          + proc("    А77 = 2;", header="Процедура Дубль77() // probe-second"),
         expect=dict(beacon=None, late=None, link=None), note="повтор определения — сообщение устанавливается"),
    # Added after the first series (K0-K13), before their own run.
    dict(id="K14", defect=proc("    А77 = 1;", header="Процедура Дефект77(Знач Строка) // probe-defect")
                          + proc("    Дефект77(\"x\"); // probe-call", header="Процедура Вызов77()"),
         expect=dict(at_defect=[HEADER_ERROR], beacon=None, late=None, link=None),
         note="вызов процедуры с упавшим заголовком: «Процедура не обнаружена» — устанавливается"),
    dict(id="K15", defect=proc("    А77 = 1;\n    Б77 = Хвост77; // probe-tail",
                               header="Процедура Дефект77(Знач Строка, Знач Хвост77) // probe-defect"),
         expect=dict(at_defect=[HEADER_ERROR], beacon=None, late=None, link=None),
         note="параметр после упавшего: «Переменная не определена (Хвост77)» — устанавливается"),
    dict(id="K16", defect=proc("    FSO77 = СоздатьОбъект(\"Scripting.FileSystemObject\");\n"
                               "    Если FSO77.FileExists(Путь77) = 1 Тогда\n"
                               "        TS77 = FSO77.OpenTextFile(Путь77, 8, 0);\n"
                               "    Иначе\n"
                               "        TS77 = FSO77.CreateTextFile(Путь77, 1, 0);\n"
                               "    КонецЕсли;\n"
                               "    TS77.Write(Строка + Симв(13) + Симв(10)); // probe-use\n"
                               "    TS77.Close();",
                               header="Процедура Дефект77(Знач Путь77, Знач Строка) // probe-defect"),
         expect=dict(at_defect=[HEADER_ERROR], present=[(None, UNDEFINED + " (FSO77)"),
                                                         ("use", "Ожидается символ '('"),
                                                         ("use", "Неопознанный оператор")],
                     beacon=False, late=True, link=False),
         note="P1 304-313: ожидается остановка компиляции на строке use, как P1 311"),
]
CORPUS = [dict(id="P1n", case="p1-compile-errors", ert="kudir_export.ert"),
          dict(id="P2n", case="p2-compile-errors", ert="kudir_export_agent.ert")]
PAIR = re.compile(r"^\{[^\r\n]*\(([0-9]+)\)\}:[ \t]*([^\r\n]*)", re.M)


def module_text(case):
    signals = case.get("signals", ("late", "beacon", "link"))
    parts = []
    if "late" in signals or "late-undefined" in signals:
        parts.append("Процедура Поздняя77() Далее // probe-late\n")
    if case["defect"]:
        parts.append(case["defect"])
    if "beacon" in signals:
        parts.append("Процедура Маяк77()\n    Х77 = Неизвестная77; // probe-beacon\nКонецПроцедуры\n")
    if "link" in signals:
        parts.append("Процедура Связь77()\n    НетТакой77(); // probe-link\nКонецПроцедуры\n")
    parts.append(COOPERATE)
    if "late" in signals:
        parts.append("Процедура Поздняя77() // probe-late-definition\nКонецПроцедуры\n")
    return "\n".join(parts)


def tags(text):
    found = {}
    for number, line in enumerate(text.splitlines(), 1):
        match = re.search(r"// probe-([a-z-]+)", line)
        if match:
            found[match.group(1)] = number
    return found


def project_text(template, source, name):
    return f"""schema_version = 1
[project]
id = {json.dumps(name)}
[build]
template = {json.dumps(str(template))}
source = {json.dumps(str(source))}
encoding = "utf-8"
[[platform.tests]]
name = "probe"
command = "execute"
expect = "passed"
[deadlines]
open_timeout_s = 60
calculation_timeout_s = 120
cancel_timeout_s = 15
shutdown_timeout_s = 30
total_timeout_s = 240
"""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def protocol_pairs(text):
    """(line, message, source line with marker or None) of a protocol, in order."""
    lines = text.splitlines()
    pairs = []
    for index, line in enumerate(lines):
        match = PAIR.match(line)
        if match:
            source = lines[index - 1] if index and "<<?>>" in lines[index - 1] else None
            pairs.append({"line": int(match[1]), "message": match[2], "source": source})
    return pairs


def read_protocol(path):
    data = path.read_bytes()
    text = data.decode("utf-16") if data.startswith(b"\xff\xfe") else data.decode("cp1251")
    return data, text


def observe(run_dir):
    report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    stages = {s["stage"]: s for s in report["stages"]}
    platform = stages.get("platform_check", {})
    protocol = run_dir / "native" / "Протоколы проверки" / "check.txt"
    pairs, evidence = [], None
    if protocol.exists():
        data, text = read_protocol(protocol)
        pairs = protocol_pairs(text)
        evidence = {"path": str(protocol.relative_to(run_dir)), "size": len(data), "sha256": sha256(data)}
    return report, {"run_status": report["status"], "platform_status": platform.get("status"),
                    "platform_reason": platform.get("reason"), "shutdown": report.get("shutdown"),
                    "diagnostics": pairs, "protocol": evidence}


def signals_seen(pairs):
    messages = [p["message"] for p in pairs]
    return {"beacon": UNDEFINED + " (Неизвестная77)" in messages,
            "late": UNRESOLVED + " (Поздняя77)" in messages,
            "link": NOT_FOUND + " (НетТакой77)" in messages}


def judge(case, observed, marks):
    pairs = observed["diagnostics"]
    if observed["platform_reason"] != "compilation_failed":
        return "blocked", ["platform did not report compilation_failed"]
    expect, problems = case["expect"], []
    seen = signals_seen(pairs)
    for key in ("beacon", "late", "link"):
        if expect.get(key) is not None and seen[key] != expect[key]:
            problems.append(f"{key}: expected {expect[key]}, observed {seen[key]}")
    if "at_defect" in expect:
        at = [p["message"] for p in pairs if p["line"] == marks.get("defect")]
        if not expect["at_defect"] and at:
            problems.append(f"unexpected messages at the defect line: {at}")
        for text in expect["at_defect"]:
            if not any(m.startswith(text) for m in at):
                problems.append(f"missing at the defect line: {text}")
    for tag, text in expect.get("present", []):
        if not any(p["message"].startswith(text) and (tag is None or p["line"] == marks.get(tag)) for p in pairs):
            problems.append(f"missing: {text} at {tag or 'any line'}")
    if "only" in expect:
        wanted = [(marks.get(tag) if tag else None, text) for tag, text in expect["only"]]
        if len(pairs) != len(wanted) or any(p["message"] != text or (line and p["line"] != line)
                                            for p, (line, text) in zip(pairs, wanted)):
            problems.append(f"expected only {wanted}")
    if problems:
        return "contradicted", problems
    concrete = (any(expect.get(k) is not None for k in ("beacon", "late", "link"))
                or "at_defect" in expect or "present" in expect or "only" in expect)
    return ("confirmed" if concrete else "observed"), []


def run_case(args, folder, name):
    completed = subprocess.run([sys.executable, "-m", "harness77", "run", "--project", str(folder / "project.toml"),
                                "--stand", str(args.stand.resolve()), "--output-root", str(args.output_root.resolve())],
                               capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    try:
        summary = json.loads(completed.stdout)
    except ValueError:
        return None, completed.stderr[-2000:]
    return summary, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT / ".artifacts" / "runs")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args(argv)
    if os.path.lexists(args.evidence):
        parser.error(f"evidence file exists: {args.evidence}")
    from harness77.ert_module import extract_text
    template = args.template.resolve(strict=True)
    rows = []
    selected = [c for c in CASES + CORPUS if not args.case or c["id"] in args.case]
    for case in selected:
        folder = args.work.resolve() / "cases" / case["id"]
        folder.mkdir(parents=True, exist_ok=True)
        row = {"id": case["id"], "note": case.get("note")}
        if "case" in case:
            ert = (args.corpus / case["case"] / case["ert"]).resolve(strict=True)
            reference = (args.corpus / case["case"] / "compiler-protocol.txt").read_bytes()
            text = extract_text(ert)
            (folder / "module.txt").write_text(text, encoding="utf-8", newline="")
            (folder / "project.toml").write_text(project_text(ert, "module.txt", "protocol-probe-corpus"),
                                                 encoding="utf-8")
            row.update(template={"name": ert.name, "sha256": sha256(ert.read_bytes())},
                       reference_sha256=sha256(reference))
            marks = {}
        else:
            text = module_text(case)
            (folder / "module.1s").write_text(text, encoding="utf-8", newline="\n")
            (folder / "project.toml").write_text(project_text(template, "module.1s", "protocol-probe"),
                                                 encoding="utf-8")
            marks = tags(text)
            row.update(expected=case["expect"], marks=marks)
        summary, error = run_case(args, folder, case["id"])
        if summary is None:
            row.update(verdict="blocked", stderr=error)
            rows.append(row)
            print(case["id"], "blocked: no run summary", file=sys.stderr)
            continue
        run_dir = Path(summary["run_dir"])
        report, observed = observe(run_dir)
        if "case" in case:
            expected = [(p["line"], p["message"]) for p in protocol_pairs(reference.decode("utf-8"))]
            actual = [(p["line"], p["message"]) for p in observed["diagnostics"]]
            same = expected == actual
            verdict = "blocked" if observed["platform_reason"] != "compilation_failed" else (
                "confirmed" if same else "contradicted")
            problems = [] if same else [f"expected {len(expected)} pairs, observed {len(actual)}"]
            row["reference_pairs"] = len(expected)
        else:
            verdict, problems = judge(case, observed, marks)
            row["signals"] = signals_seen(observed["diagnostics"])
        built = report.get("artifact") or {}
        row.update(observed=observed, verdict=verdict, problems=problems, run_id=summary["run_id"],
                   ert_sha256=built.get("sha256"), module_sha256=built.get("module_sha256"),
                   run_json_sha256=sha256((run_dir / "run.json").read_bytes()))
        rows.append(row)
        print(case["id"], verdict, len(observed["diagnostics"]), row.get("signals"), problems[:2], file=sys.stderr)
    evidence = {"schema_version": 1, "scope": "task 009 compiler continuation probes on real 1C 7.7",
                "generated": datetime.datetime.now().astimezone().isoformat(),
                "stand": "local-7.70.027 (base-for-test, pinned)",
                "template_sha256": sha256(template.read_bytes()), "cases": rows}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with open(args.evidence, "x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=1)
    return 0 if all(r["verdict"] in ("confirmed", "observed") for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
