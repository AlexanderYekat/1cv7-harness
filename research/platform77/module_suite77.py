"""Small, fixed native-module experiment; not a general ERT test runner.

The Windows lifecycle is owned by diagnose_shutdown77.py. This module only
prepares a client and evaluates its evidence, and is importable on other OSes.
"""
import hashlib
import json
from pathlib import Path
import re
import uuid


VALID_SOURCE = '''Функция Harness77Sum(А, Б) Экспорт
    Возврат А + Б;
КонецФункции'''
SYNTAX_SOURCE = '''Функция Harness77Sum(А, Б) Экспорт
    Возврат А + ;
КонецФункции'''
UNUSED_SOURCE = VALID_SOURCE + '''
Процедура Harness77Unused()
    А = ;
КонецПроцедуры'''
CONTROLLER_SOURCE = '''Функция Harness77CheckSource(Текст, ПутьПротокола, Метка) Экспорт
    Сообщения = СоздатьОбъект("MessageView");
    Сообщения.SetSystemMessages();
    Сообщения.Clear();
    Сообщить("HARNESS77-BEGIN:" + Метка);
    Модуль = СоздатьОбъект("ВыполняемыйМодуль");
    Модуль.УстановитьМодуль(Текст);
    Попытка
        Результат = Модуль.КомпилироватьМодуль();
        Ответ = "return|" + СокрЛП(Строка(Результат));
    Исключение
        Ответ = "error|" + ОписаниеОшибки();
    КонецПопытки;
    Сообщить("HARNESS77-END:" + Метка);
    Сообщения.SaveToFile(ПутьПротокола);
    Возврат Ответ;
КонецФункции

Функция Harness77Repeat(Текст, Повторения) Экспорт
    Модуль = СоздатьОбъект("ВыполняемыйМодуль");
    Модуль.УстановитьМодуль(Текст);
    Если Модуль.КомпилироватьМодуль() <> 1 Тогда Возврат -1; КонецЕсли;
    Если Модуль.ВыполнитьМодуль() <> 1 Тогда Возврат -2; КонецЕсли;
    Успехи = 0;
    Для Номер = 1 По Повторения Цикл
        Если Модуль.Harness77Sum(20, 22) = 42 Тогда
            Успехи = Успехи + 1;
        КонецЕсли;
    КонецЦикла;
    Возврат Успехи;
КонецФункции'''

CASES = {
    "compile_valid": ("return|1", "passed"),
    "value_correct": ("42", "passed"),
    "value_wrong": ("43", "failed"),
    "compile_syntax": (2, "failed"),
    "compile_unused": (5, "failed"),
    "compile_recovery": ("return|1", "passed"),
    "value_recovery": ("42", "passed"),
}
PHASES = ("activation", "initialize", "base_check", "controller_load", "target_load", "release")
BATCHES = ("calls_loaded", "fresh_modules", "calls_inside_1c")


def vb_literal(value):
    return ' & vbCrLf & '.join('"' + line.replace('"', '""') + '"'
                               for line in value.splitlines())


def vb_assignment(name, source):
    return name + ' = ""\n' + '\n'.join(
        name + ' = ' + name + ' & ' + vb_literal(line) + ' & vbCrLf'
        if line else name + ' = ' + name + ' & vbCrLf' for line in source.splitlines())


def prepare_client(out, iterations, before_release="", after_release=""):
    if not 1 <= iterations <= 10000:
        raise ValueError("suite iterations must be between 1 and 10000")
    sources = {"valid.1s": VALID_SOURCE, "syntax-error.1s": SYNTAX_SOURCE,
               "unused-error.1s": UNUSED_SOURCE, "controller.1s": CONTROLLER_SOURCE}
    run_id = str(uuid.uuid4())
    manifest = {"schema_version": 1, "run_id": run_id, "iterations": iterations,
                "fresh_modules": min(iterations, 100), "sources": {}}
    for name, source in sources.items():
        data = (source + "\n").encode("utf-8")
        (out / name).write_bytes(data)
        manifest["sources"][name] = hashlib.sha256(data).hexdigest()
    (out / "suite-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    client = Path(__file__).with_name("module_suite77.vbs").read_text(encoding="utf-8")
    replacements = {"RUN_ID": vb_literal(run_id), "BEFORE_RELEASE": before_release,
                    "AFTER_RELEASE": after_release,
                    "SOURCES": '\n'.join(vb_assignment(name, source) for name, source in (
                        ("sourceOk", VALID_SOURCE), ("sourceBad", SYNTAX_SOURCE),
                        ("sourceUnused", UNUSED_SOURCE), ("sourceController", CONTROLLER_SOURCE))),
                    "ITERATIONS": str(iterations), "FRESH_MODULES": str(manifest["fresh_modules"])}
    for key, value in replacements.items():
        client = client.replace("__" + key + "__", value)
    return client, manifest


def read_results(out, manifest, lifecycle, shutdown_manifest=None):
    """Fail closed on missing, stale, malformed or incomplete native evidence."""
    report = {"schema_version": 1, "run_id": manifest["run_id"], "status": "blocked",
              "scope": "synthetic native module text; not ERT or configuration validation",
              "cases": [], "timings": {}, "issues": []}
    issues = report["issues"]
    path = out / "suite-events.jsonl"
    events = []
    try:
        events = [json.loads(line) for line in path.read_text(encoding="utf-16").splitlines()]
    except (OSError, UnicodeError, ValueError) as error:
        issues.append("missing or malformed event log: " + str(error))
    indexed = {}
    for event in events:
        if not isinstance(event, dict) or event.get("run_id") != manifest["run_id"]:
            issues.append("invalid event or foreign run_id")
            continue
        kind, name = event.get("kind"), event.get("name")
        if not isinstance(kind, str) or not isinstance(name, str):
            issues.append("invalid event identity")
            continue
        key = (kind, name)
        if key in indexed:
            issues.append("duplicate event: " + name)
            continue
        indexed[key] = event
        elapsed = event.get("elapsed_ms")
        if (not isinstance(event.get("value"), str) or type(elapsed) not in (int, float)
                or not 0 <= elapsed <= 145000):
            issues.append("invalid event fields: " + name)
        if kind == "blocked":
            issues.append("client error: " + name + ": " + str(event.get("value")))
    required = ({("case", name) for name in CASES} | {("phase", name) for name in PHASES}
                | {("batch", name) for name in BATCHES} | {("complete", "suite")})
    if set(indexed) != required:
        issues.append("event set mismatch; missing=" + str(sorted(required - set(indexed)))
                      + "; unexpected=" + str(sorted(set(indexed) - required)))
    for name, digest in manifest["sources"].items():
        if not (out / name).is_file() or hashlib.sha256((out / name).read_bytes()).hexdigest() != digest:
            issues.append("source evidence changed: " + name)
    if issues:
        return report
    if not lifecycle.get("normal_shutdown_observed"):
        issues.append("native session did not finish cleanly")
    if lifecycle.get("diagnostic_execution_modified"):
        issues.append("diagnostic intervention changed execution; this is not an unmodified acceptance run")
    if lifecycle.get("shutdown_execution_modified") or shutdown_manifest is not None:
        if shutdown_manifest is None:
            issues.append("modified shutdown requires explicit policy evidence")
        else:
            from shutdown77 import assess
            report["shutdown_assessment"] = assess(out, shutdown_manifest, lifecycle)
            if shutdown_manifest.get("run_id") != manifest["run_id"]:
                issues.append("shutdown and suite run_id mismatch")
            if report["shutdown_assessment"]["status"] != "passed":
                issues.append("shutdown policy contract was not met")
    for name, (expected, expected_status) in CASES.items():
        event = indexed[("case", name)]
        actual = event["value"]
        row = {"name": name, "expected_status": expected_status,
               "actual": actual, "elapsed_ms": event["elapsed_ms"]}
        source = {"compile_syntax": "syntax-error.1s", "compile_unused": "unused-error.1s"}.get(name, "valid.1s")
        row.update(source_file=source, source_sha256=manifest["sources"][source])
        if name.startswith("compile_"):
            status = "failed" if actual.startswith(("error|", "rejected|")) or actual == "return|0" else "passed" if actual == "return|1" else "blocked"
            row["status"] = status
            protocol_path = out / (name + ".txt")
            protocol = ""
            try:
                data = protocol_path.read_bytes()
                encoding = "utf-16" if data.startswith((b'\xff\xfe', b'\xfe\xff')) else "utf-8-sig" if data.startswith(b'\xef\xbb\xbf') else "cp1251"
                protocol = data.decode(encoding)
                row["protocol_sha256"] = hashlib.sha256(data).hexdigest()
            except (OSError, UnicodeError) as error:
                issues.append("missing compiler protocol for " + name + ": " + str(error))
            marker = manifest["run_id"] + ":" + name
            lines = protocol.splitlines()
            begin, end = "HARNESS77-BEGIN:" + marker, "HARNESS77-END:" + marker
            if (not lines or lines[0] != begin or lines[-1] != end
                    or lines.count(begin) != 1 or lines.count(end) != 1):
                issues.append("incomplete or foreign compiler protocol: " + name)
            row["protocol_file"] = protocol_path.name
            row["protocol_raw"] = protocol
            if isinstance(expected, int):
                raw = actual.removeprefix("error|").removeprefix("rejected|")
                match = re.match(r"\((\d+)\)(.*)", raw, re.DOTALL)
                diagnostics = [{"line": int(m[1]), "message": m[2]} for m in re.finditer(
                    r"^\{[^\r\n]*\(([0-9]{1,9})\)\}:[ \t]*([^\r\n]*)", protocol, re.MULTILINE)]
                if match:
                    diagnostics.append({"line": int(match[1]), "message": match[2]})
                row["diagnostics"] = diagnostics
                row["expected_line"] = expected
                row["expectation_met"] = status == "failed" and any(d["line"] == expected and d["message"].strip() for d in diagnostics)
            else:
                row["expectation_met"] = actual == expected
        else:
            row["expected_value"] = int(expected)
            row["status"] = "passed" if actual == expected else "failed"
            row["expectation_met"] = actual == "42" and row["status"] == expected_status
        report["cases"].append(row)
    if indexed[("complete", "suite")]["value"] != "done":
        issues.append("missing completion marker")
    for name in PHASES:
        event = indexed[("phase", name)]
        report["timings"][name + "_ms"] = event["elapsed_ms"]
        if event["value"] != "ok":
            issues.append("phase did not succeed: " + name)
    for name, count in (("calls_loaded", manifest["iterations"]), ("fresh_modules", manifest["fresh_modules"]),
                        ("calls_inside_1c", manifest["iterations"])):
        event = indexed[("batch", name)]
        report["timings"][name] = {"count": count, "total_ms": event["elapsed_ms"],
                                   "mean_ms": round(event["elapsed_ms"] / count, 4)}
        if event["value"] != "ok":
            issues.append("batch failed: " + name)
    report["timings"]["session_seconds"] = lifecycle.get("elapsed_seconds")
    report["timings"]["clock"] = "VBScript Timer; coarse wall clock, midnight wrap handled; batch means, not per-call precision"
    report["status"] = ("blocked" if issues else "passed" if all(row["expectation_met"] for row in report["cases"]) else "failed")
    report["test_expectations_met"] = all(row["expectation_met"] for row in report["cases"])
    report["intentional_failure"] = "value_wrong expects 43 but receives 42; suite passes only if this assertion is reported failed"
    return report
