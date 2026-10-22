"""Native probes for changed 1Cv7.MD modules on a copy of the base through `harness77 run`; task 021.

Each case is one `harness77 run` with [configuration]: the changed modules of the stand
base's 1Cv7.MD (only the files of the case, in the md-extract layout), and a cooperating
external processing (probe_rules77) whose Harness77Контроль reads what the changed
configuration did. Expectations are fixed in docs/tasks/021-md-modules.md before the
run; "?" leaves the outcome to the probe. After the series the stand base and the user's
list of bases must be as they were.

Usage (local stand profile with copy_exclude, base-for-test, the FIO.ERT template):
  python research/md/probe_md77.py --stand .local/stage21-native/stand.toml
      --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --work .local/stage21-native --evidence .artifacts/stage21-md-probes-YYYYMMDD.json
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "rules77"))
sys.path.insert(0, str(ROOT / "research" / "platform77"))
sys.path.insert(0, str(ROOT / "src"))

from probe_rules77 import RETURN_42, module_text, observe, project_text, sha256  # noqa: E402

from harness77 import basecopy77, md77  # noqa: E402
from harness77.config77 import load_stand  # noqa: E402

GLOBAL = "ГлобальныйМодуль.1s"
TRANSACT = "Документ/НезавершенноеПроизводство/МодульДокумента.1s"
FORM = "Документ/Доверенность/Форма.1s"
END = re.compile(r"\s*Конец(Процедуры|Функции)\b", re.I)


def function(code):
    """Insert code after the last procedure or function: before the module's main program."""
    def change(lines):
        last = max(n for n, line in enumerate(lines) if END.match(line))
        return lines[:last + 1] + [""] + code.splitlines() + lines[last + 1:]
    return change


def variable(lines):
    """An exported global variable, declared before any procedure."""
    return ["Перем глХарнесс77 Экспорт;"] + lines


def main(statement):
    def change(lines):
        return lines + [statement]
    return change


def at_start(header, statement):
    """The statement as the first one of a procedure."""
    def change(lines):
        found = [n for n, line in enumerate(lines) if line.strip().casefold().startswith(header.casefold())]
        if len(found) != 1:
            raise ValueError(f"{header}: found {len(found)} times")
        return lines[:found[0] + 1] + [statement] + lines[found[0] + 1:]
    return change


def append(code):
    def change(lines):
        return lines + [""] + code.splitlines()
    return change


EXPORT_42 = "Функция Харнесс77Конфигурация() Экспорт\n    Возврат 42;\nКонецФункции"
BROKEN_42 = "Функция Харнесс77Конфигурация() Экспорт\n    Возврат 42 +;\nКонецФункции"
EXPORT_45 = "Функция Харнесс77Документ() Экспорт\n    Возврат 45;\nКонецФункции"
POSTING = "Процедура ОбработкаПроведения()"
OPENING = "Процедура ПриОткрытии()"
POST = """    глХарнесс77 = 0;
    Док77 = СоздатьОбъект("Документ.НезавершенноеПроизводство");
    Док77.Новый();
    Док77.Записать();
    Р77 = Док77.Провести(1);
    Возврат Строка(глХарнесс77) + ";" + Строка(Р77);"""
OPEN = """    глХарнесс77 = 0;
    ОткрытьФорму("Документ.Доверенность");
    Возврат глХарнесс77;"""
EXPORT_CALL = """    Док77 = СоздатьОбъект("Документ.НезавершенноеПроизводство");
    Возврат Док77.Харнесс77Документ();"""
TRANSACT2 = "Документ/ЗаписьКнигиПродажТорг/МодульДокумента.1s"
UNPOSTED = """    Док77 = СоздатьОбъект("Документ.НезавершенноеПроизводство");
    Док77.Новый();
    Док77.Записать();
    Возврат Док77.Провести(1);"""
POST2 = POST.replace("НезавершенноеПроизводство", "ЗаписьКнигиПродажТорг")
EXPORT_CALL2 = EXPORT_CALL.replace("НезавершенноеПроизводство", "ЗаписьКнигиПродажТорг")

CASES = [
    dict(id="m-same", changes={}, control=RETURN_42, value="42",
         note="каталог без изменений: 1Cv7.MD копии = шаблон"),
    dict(id="m-global", changes={GLOBAL: [function(EXPORT_42)]},
         control="    Возврат Харнесс77Конфигурация();", value="42"),
    dict(id="m-global-var", changes={GLOBAL: [variable, main("глХарнесс77 = 41;")]},
         control="    Возврат глХарнесс77;", value="41"),
    dict(id="m-transact", changes={GLOBAL: [variable], TRANSACT: [at_start(POSTING, "    глХарнесс77 = 43;")]},
         control=POST, value="43;1"),
    dict(id="m-form", changes={GLOBAL: [variable],
                               FORM: [at_start(OPENING, "    глХарнесс77 = 44; СтатусВозврата(0); Возврат;")]},
         control=OPEN, value="44"),
    dict(id="m-global-error", changes={GLOBAL: [function(BROKEN_42)]}, control=RETURN_42, value="?"),
    dict(id="m-transact-error", changes={GLOBAL: [variable], TRANSACT: [at_start(POSTING, "    глХарнесс77 = 43 +;")]},
         control=POST, value="?"),
    dict(id="m-export", changes={TRANSACT: [append(EXPORT_45)]}, control=EXPORT_CALL, value="?"),
    # Series 2: НезавершенноеПроизводство is not posted (field 18 of its record is 0); a posted kind.
    dict(id="m-unposted", changes={}, control=UNPOSTED, value=None, error="Документ не может быть проведен!",
         series=2),
    dict(id="m-transact2", changes={GLOBAL: [variable], TRANSACT2: [at_start(POSTING, "    глХарнесс77 = 43; Возврат;")]},
         control=POST2, value="43;1", series=2),
    dict(id="m-transact2-error", changes={GLOBAL: [variable], TRANSACT2: [at_start(POSTING, "    глХарнесс77 = 43 +;")]},
         control=POST2, value="?", series=2),
    dict(id="m-export2", changes={TRANSACT2: [append(EXPORT_45)]}, control=EXPORT_CALL2, value=None,
         error="Поле агрегатного объекта не обнаружено", series=2),
    dict(id="m-form-error", changes={GLOBAL: [variable], FORM: [at_start(OPENING, "    глХарнесс77 = 44 +;")]},
         control=OPEN, value="?", series=2),
]


# Series 3 (docs/tasks/021-md-modules.md): every case on the final code, the expectations set by
# series 1 and 2; reason is the platform check's, a compile error of a changed module fails it.
COMPILE = "configuration_compilation_failed: "
FINAL = {
    "m-same": dict(value="42"), "m-global": dict(value="42"), "m-global-var": dict(value="41"),
    "m-transact": dict(value=None, error="Документ не может быть проведен!"),
    "m-form": dict(value="44"),
    "m-global-error": dict(value=None, reason=COMPILE + "ГлобальныйМодуль.1s:9812: Ошибка в выражении"),
    "m-transact-error": dict(value=None, error="Документ не может быть проведен!"),
    "m-export": dict(value=None, error="Поле агрегатного объекта не обнаружено"),
    "m-unposted": dict(value=None, error="Документ не может быть проведен!"),
    "m-transact2": dict(value="43;1"),
    "m-transact2-error": dict(value=None, reason=COMPILE + "Документ/ЗаписьКнигиПродажТорг/МодульДокумента.1s:"),
    "m-export2": dict(value=None, error="Поле агрегатного объекта не обнаружено"),
    "m-form-error": dict(value=None, reason=COMPILE + "Документ/Доверенность/Форма.1s:191: Ошибка в выражении"),
}


def changed_modules(case, originals, folder):
    """The case's module files in the md-extract layout: each original text with its changes."""
    for file, changes in case["changes"].items():
        lines = originals[file].splitlines()
        for change in changes:
            lines = change(lines)
        target = folder / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def configuration_project(template, deadline, modules):
    """The probe project with the case's modules; opening the copy gets 120 s, as a fresh base may need."""
    text = project_text(template, deadline).replace(
        "[deadlines]", f"[configuration]\nmodules = {json.dumps(str(modules))}\n[deadlines]")
    text = re.sub(r"open_timeout_s = \d+", "open_timeout_s = 120", text)
    return re.sub(r"total_timeout_s = \d+", f"total_timeout_s = {deadline + 240}", text)


def evidence_of(report):
    """What the run reports about the configuration and the copy of the base."""
    stages = {s["stage"]: s for s in report["stages"]}
    configuration = stages.get("configuration", {})
    platform = stages.get("platform_check", {})
    copy = platform.get("base_copy") or {}
    log = copy.get("session_log") or {}
    return {"configuration": {"status": configuration.get("status"), "reason": configuration.get("reason"),
                              "md_sha256": configuration.get("md_sha256"), "rebuilt": configuration.get("rebuilt"),
                              "changed": [row["file"] for row in configuration.get("changed", [])]},
            "static": {"status": stages.get("static", {}).get("status"),
                       "errors": stages.get("static", {}).get("errors"),
                       "diagnostics": [(d["module"], d["line"], d["rule"], d["message"])
                                       for d in stages.get("static", {}).get("diagnostics", [])][:10]},
            "copy": {key: copy.get(key) for key in ("seconds", "files", "bytes", "excluded", "md_sha256",
                                                    "removal", "kept")}
            | {"source_unchanged": (copy.get("source_check") or {}).get("unchanged")},
            "session_log": {"count": log.get("count"),
                            "errors": [entry for entry in log.get("entries", [])
                                       if entry["event"].endswith("Err") or entry["event"].endswith("Error")][:20],
                            "events": sorted({entry["event"] for entry in log.get("entries", [])})},
            "base_list": platform.get("base_list"), "open": platform.get("open"),
            "timeout_phase": report.get("timeout_phase"), "phase_durations_s": platform.get("phase_durations_s")}


def judge(case, observed):
    if case.get("reason"):
        return "confirmed" if (observed["run_status"], observed["platform_status"]) == ("failed", "failed") \
            and (observed["platform_reason"] or "").startswith(case["reason"]) else "contradicted"
    if case["value"] == "?":
        return "observed"
    if observed["compile"] != "ok":
        return "contradicted" if observed["compile"] == "error" else "blocked"
    if case.get("error"):
        return "confirmed" if case["error"] in (observed["runtime_error"] or "") else "contradicted"
    return "confirmed" if observed["value"] == case["value"] else "contradicted"


def run_series(cases, args):
    stand = load_stand(args.stand)
    base = Path(stand.base)
    template = args.template.resolve(strict=True)
    originals = {module.file: module.raw.decode("cp1251") for module in
                 md77._open((base / "1Cv7.MD").read_bytes(), base / "1Cv7.MD")[2]}
    from win32_session77 import base_titles_fingerprint
    listing, titles = basecopy77.listing(base), base_titles_fingerprint()
    rows = []
    for case in cases:
        folder = args.work.resolve() / "cases" / case["id"]
        modules = folder / "configuration"
        modules.mkdir(parents=True, exist_ok=False)
        changed_modules(case, originals, modules)
        text = module_text(case)
        (folder / "module.1s").write_text(text, encoding="utf-8", newline="\n")
        (folder / "project.toml").write_text(configuration_project(template, 60, modules), encoding="utf-8")
        completed = subprocess.run([sys.executable, "-m", "harness77", "run", "--project", str(folder / "project.toml"),
                                    "--stand", str(args.stand.resolve()), "--output-root", str(args.output_root.resolve())],
                                   capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        try:
            summary = json.loads(completed.stdout)
        except ValueError:
            rows.append({"id": case["id"], "verdict": "blocked", "stderr": completed.stderr[-2000:]})
            print(case["id"], "blocked: no run summary", completed.stderr[-500:], file=sys.stderr)
            continue
        run_dir = Path(summary["run_dir"])
        report, observed = observe(run_dir)
        verdict = judge(case, observed)
        rows.append({"id": case["id"], "note": case.get("note"), "expected": case["value"],
                     "expected_error": case.get("error"), "expected_reason": case.get("reason"), "verdict": verdict,
                     "observed": observed, **evidence_of(report), "run_id": summary["run_id"],
                     "module_sha256": sha256(folder / "module.1s"),
                     "ert_sha256": (report.get("artifact") or {}).get("sha256"),
                     "run_json_sha256": sha256(run_dir / "run.json")})
        print(case["id"], verdict, observed["run_status"], observed["platform_reason"], observed["compile"],
              observed["value"], (observed["runtime_error"] or "")[:200],
              [d.get("message") for d in observed["diagnostics"]][:2], file=sys.stderr, flush=True)
    after = {"base_unchanged": basecopy77.listing(base) == listing, "base_list_unchanged": base_titles_fingerprint() == titles}
    evidence = {"schema_version": 1, "scope": "task 021: changed 1Cv7.MD modules on a copy of the base",
                "generated": datetime.datetime.now().astimezone().isoformat(),
                "stand": "local-7.70.027 (base-for-test, pinned)", "template_sha256": sha256(template),
                "metadata_sha256": sha256(base / "1Cv7.MD"), "copy_exclude": list(stand.copy_exclude),
                "series": after, "cases": rows}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with open(args.evidence, "x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=1)
    print("series", after, file=sys.stderr)
    return 0 if all(r["verdict"] in ("confirmed", "observed") for r in rows) and all(after.values()) else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path, help="local directory for generated cases")
    parser.add_argument("--output-root", type=Path, default=ROOT / ".artifacts" / "runs")
    parser.add_argument("--evidence", required=True, type=Path, help="new JSON file with all results")
    parser.add_argument("--case", action="append", default=[], help="run only these case ids")
    parser.add_argument("--final", action="store_true", help="series 3: every case with the expectations of FINAL")
    args = parser.parse_args(argv)
    if os.path.lexists(args.evidence):
        parser.error(f"evidence file exists: {args.evidence}")
    cases = CASES
    if args.case:
        unknown = set(args.case) - {c["id"] for c in CASES}
        if unknown:
            parser.error(f"unknown case ids: {sorted(unknown)}")
        cases = [c for c in CASES if c["id"] in args.case]
    if args.final:
        cases = [{key: value for key, value in case.items() if key not in ("value", "error", "reason")}
                 | FINAL[case["id"]] for case in cases]
    return args, cases


if __name__ == "__main__":
    arguments_, cases_ = arguments()
    raise SystemExit(run_series(cases_, arguments_))
