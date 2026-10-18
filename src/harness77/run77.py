"""The one full-cycle command: static -> build -> platform -> tests -> report.

Each run gets a fresh ``run_id`` and its own results directory. Inputs, the
built ERT, platform evidence and test results are linked by identifier and
SHA-256, and only the ERT built by *this* run may be checked. An old, foreign,
partial or missing result never yields success. Required-stage statuses fold
into one exit code: 0 all required stages passed (including a verified
expected-negative test), 1 a confirmed defect in the checked code or a failed
test, 2 an input/infrastructure error or an incomplete required result.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import threading
import uuid

from . import __version__
from .deadlines77 import Clock, RunClock
from .report77 import (BLOCKED, FAILED, PASSED, SKIPPED, Stage, atomic_json,
                       exit_code, file_evidence, sha256_file)

STAGE_SCOPES = {
    "static": "conservative static analysis of the module source; not the 1C compiler",
    "build": "verified ERT container build from template + source",
    "platform_check": "load/compile this run's ERT on the selected stand",
    "tests": "declared operation expectations on the selected stand",
}


def _now_iso():
    return dt.datetime.now().astimezone().isoformat()


class Observations:
    """Stream phase observations to a file; keep only a small tail in memory."""

    def __init__(self, path, keep=100):
        self._stream = open(path, "w", encoding="utf-8")
        self.path = Path(path)
        self.count = 0
        self.keep = keep
        self.tail = []

    def __call__(self, record):
        self.count += 1
        self._stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._stream.flush()
        self.tail.append(record)
        if len(self.tail) > self.keep:
            self.tail.pop(0)

    def close(self):
        self._stream.close()


def _static_stage(project):
    from .ert_module import CompoundFile, ErtError
    from .lint77 import analyze, collect_paths, ert_dialog, load_sources
    stage = Stage("static", required=True, scope=STAGE_SCOPES["static"])
    try:
        sources = [s for path in collect_paths([str(project.source)]) for s in load_sources(path)]
        # The module is built into the template: its dialog, or the form description
        # built with it, is the form context (L7711).
        try:
            if project.form is not None:
                from .form77 import dialog_identifiers, loads
                dialog = dialog_identifiers(loads(Path(project.form).read_bytes()))
            else:
                dialog = ert_dialog(CompoundFile(Path(project.template).read_bytes()))
        except (OSError, ErtError):
            dialog = None  # the build stage reports an unreadable template or description
        for source in sources:
            if source.dialog is None:
                source.dialog = dialog
        globals_sources = [s for path in project.globals for s in load_sources(Path(path))]
        report = analyze(sources, globals_sources, project.allow, project.strict)
    except (OSError, ValueError, ErtError) as error:
        return stage.finish(BLOCKED, reason=f"static_input_error: {type(error).__name__}: {error}")
    status = FAILED if report["errors"] else PASSED
    return stage.finish(status, diagnostics=report["diagnostics"],
                        errors=report["errors"], warnings=report["warnings"])


def _build_stage(project, run_dir):
    from .artifacts import build
    from .ert_module import ErtError
    stage = Stage("build", required=True, scope=STAGE_SCOPES["build"])
    output = run_dir / "build" / (project.project_id + ".ert")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = build(project.template, project.source, output, encoding=project.encoding,
                       legacy_normalize=project.legacy_normalize, form=project.form)
    except (OSError, ValueError, ErtError) as error:
        return stage.finish(BLOCKED, reason=f"build_error: {type(error).__name__}: {error}",
                            output_path=str(output)), None
    evidence = file_evidence(output, root=run_dir, complete=True,
                             expected_sha256=report["output"]["sha256"])
    stage.finish(PASSED, evidence=[evidence],
                 template_sha256=report["template"]["sha256"],
                 source_sha256=report["source"]["sha256"],
                 module_sha256=report["module_sha256"],
                 ert_sha256=report["output"]["sha256"], encoding=report["source"]["encoding"],
                 normalizations=report["normalizations"],
                 preserved_streams=len(report["preserved_streams"]),
                 **({"form": {key: report["form"][key] for key in
                              ("sha256", "template_dialog_sha256", "dialog_sha256", "changes")}}
                    if "form" in report else {}))
    return stage, {"path": output, "sha256": report["output"]["sha256"], "build": report}


def _judge_tests(project, platform_result, platform_passed):
    stage = Stage("tests", required=True, scope=STAGE_SCOPES["tests"])
    if not project.tests:
        return stage.finish(BLOCKED, reason="no tests declared; the full cycle requires at least one")
    if not platform_passed:
        return stage.finish(SKIPPED, reason="platform check did not pass; tests not judged")
    operations = {op.get("name"): op for op in platform_result.get("operations", [])}
    rows, met = [], True
    for test in project.tests:
        op = operations.get(test["command"]) or operations.get(test["name"])
        if op is None:
            rows.append({**test, "status": BLOCKED, "expectation_met": False,
                         "note": "no matching operation in platform result"})
            met = False
            continue
        value_ok = "expect_value" not in test or str(op.get("value")) == test["expect_value"]
        expectation_met = op.get("status") == test["expect"] and value_ok
        rows.append({**test, "status": op.get("status"), "value": op.get("value"),
                     "value_met": value_ok, "diagnostics": op.get("diagnostics", []),
                     "expectation_met": expectation_met})
        met = met and expectation_met
    if any(r["status"] == BLOCKED for r in rows):
        return stage.finish(BLOCKED, reason="an expected operation was missing", tests=rows)
    return stage.finish(PASSED if met else FAILED, tests=rows,
                        reason=None if met else "a declared test expectation was not met")


def _triage(diagnostics, ert_path):
    """Root/cascade marking against the module this run built (task 009)."""
    from .ert_module import ErtError, extract_text
    from .triage77 import triage
    try:
        text = extract_text(Path(ert_path))
    except (OSError, ErtError):
        text = None
    try:
        result = triage(diagnostics, module_text=text)
    except ValueError as error:
        return {"error": f"{type(error).__name__}: {error}"}
    result.pop("limitations", None)
    return result


def _platform_stage(stand, built, run_id, run_dir, deadlines, clock, cancel, observe, project=None):
    from .backends77 import load_backend
    stage = Stage("platform_check", required=True, scope=STAGE_SCOPES["platform_check"])
    backend = load_backend(stand, ert_path=built["path"], ert_sha256=built["sha256"],
                           run_id=run_id, run_dir=run_dir, clock=clock,
                           parameters=project.parameters if project else None,
                           commands=project.commands() if project else (),
                           captures=project.visual.captures() if project and project.visual else ())
    # The backend owns the clock (manual for simulation, monotonic natively); the
    # run clock must share it so the §8.5 deadlines see the same time.
    run_clock = RunClock(deadlines, run_id, clock=backend.clock)
    result = backend.run(run_clock, cancel, observe)
    result["total_elapsed_s"] = round(run_clock.observe()["elapsed_s"], 3)
    # Enforce that this run's ERT, and no stale or foreign result, was checked.
    linkage = []
    if result.get("run_id") != run_id:
        linkage.append("result run_id does not match this run")
    if result.get("ert_sha256") != built["sha256"]:
        linkage.append("checked ERT hash does not match this run's build")
    # A missing or incomplete file blocks success unless it belongs to an operation
    # that already failed: then it is that failure's evidence, judged by the tests.
    statuses = {op.get("name"): op.get("status") for op in result.get("operations", [])}
    incomplete = [f for f in result.get("result_files", [])
                  if (f.get("complete") is False or f.get("exists") is False)
                  and statuses.get(f.get("operation"), PASSED) == PASSED]
    status = result.get("status", BLOCKED)
    reason = result.get("reason")
    if linkage:
        status, reason = BLOCKED, "; ".join(linkage)
    elif incomplete and status == PASSED:
        status, reason = BLOCKED, "a required result file is missing or incomplete"
    diagnostics = (result.get("load") or {}).get("diagnostics", [])
    triage = _triage(diagnostics, built["path"]) if diagnostics else None
    if triage is not None and "diagnostics" in triage:
        diagnostics = triage.pop("diagnostics")
    stage.finish(status, reason=reason, diagnostics=diagnostics, triage=triage,
                 platform_checked=result.get("platform_checked", False), backend=backend.name,
                 load=result.get("load"), linkage_ok=not linkage,
                 result_files=result.get("result_files", []),
                 cancelled=result.get("cancelled", False),
                 timeout_phase=result.get("timeout_phase"),
                 phase_durations_s=result.get("phase_durations_s", {}),
                 open=result.get("open"),
                 screenshots=result.get("screenshots", []),
                 **({"captures": result["captures"]} if "captures" in result else {}),
                 shutdown=result.get("shutdown"))
    return stage, result, backend


def _overall(stages):
    """Blocked wins over failed per §8.3; downstream skips never escalate."""
    considered = [s for s in stages if s.required and s.status != SKIPPED]
    if any(s.status == BLOCKED for s in considered):
        return BLOCKED
    if any(s.status == FAILED for s in considered):
        return FAILED
    return PASSED


def execute(project, stand, deadlines, *, output_root, run_id=None, clock=None, cancel=None):
    run_id = run_id or str(uuid.uuid4())
    clock = clock or Clock()
    cancel = cancel or threading.Event()
    run_dir = Path(output_root).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    observe = Observations(run_dir / "observations.jsonl")
    report = {"schema_version": 1, "tool": "harness77", "operation": "run", "mode": "full",
              "version": __version__, "run_id": run_id, "started_at": _now_iso(),
              "run_dir": str(run_dir), "deadlines": deadlines.effective(),
              "inputs": project.public(), "platform": stand.public(),
              "platform_checked": False, "cancelled": False, "timeout_phase": None,
              "reason": None, "stages": [], "result_files": []}
    static = _build = platform = tests = visual = None
    platform_result = None
    try:
        static = _static_stage(project)
        build_stage, built = _build_stage(project, run_dir)
        _build = build_stage
        if built is None:
            platform = Stage("platform_check", required=True, scope=STAGE_SCOPES["platform_check"]).finish(
                SKIPPED, reason="no ERT was built")
            tests = Stage("tests", required=True, scope=STAGE_SCOPES["tests"]).finish(
                SKIPPED, reason="no ERT was built")
            if project.visual is not None:
                from .visual77 import STAGE_SCOPE
                visual = Stage("visual", required=True, scope=STAGE_SCOPE).finish(SKIPPED, reason="no ERT was built")
        else:
            report["artifact"] = build_stage.evidence[0]
            report["artifact"]["module_sha256"] = build_stage.details["module_sha256"]
            platform, platform_result, backend = _platform_stage(
                stand, built, run_id, run_dir, deadlines, clock, cancel, observe, project)
            report["platform_checked"] = platform_result.get("platform_checked", False)
            report["platform"].update(platform_result.get("platform_identity", {}))
            report["cancelled"] = platform_result.get("cancelled", False)
            report["timeout_phase"] = platform_result.get("timeout_phase")
            report["result_files"] = platform_result.get("result_files", [])
            report["screenshots"] = platform_result.get("screenshots", [])
            report["shutdown"] = platform_result.get("shutdown")
            tests = _judge_tests(project, platform_result, platform.status == PASSED)
            if project.visual is not None:
                # Task 010: captures against approved baselines; a run never writes a baseline.
                from .visual77 import visual_stage
                visual = visual_stage(project.visual, platform_result, run_dir, platform.status == PASSED)
    finally:
        observe.close()
    stages = [s for s in (static, _build, platform, tests, visual) if s is not None]
    status = _overall(stages)
    first_bad = next((s for s in stages if s.required and s.status in (FAILED, BLOCKED)), None)
    report.update(status=status, exit_code=exit_code(status), finished_at=_now_iso(),
                  reason=(first_bad.reason if first_bad else None),
                  stages=[s.as_dict() for s in stages],
                  observations={"count": observe.count, "path": "observations.jsonl", "tail": observe.tail})
    atomic_json(run_dir / "run.json", report)
    return report


def _summary(report):
    keys = ("status", "exit_code", "run_id", "run_dir", "platform_checked", "reason",
            "cancelled", "timeout_phase")
    out = {k: report.get(k) for k in keys}
    out["stages"] = {s["stage"]: s["status"] for s in report.get("stages", [])}
    return out


def main(argv=None):
    import argparse
    import signal
    import sys

    from .config77 import ConfigError, load_project, load_stand, resolve_deadlines
    from .deadlines77 import DeadlineError

    parser = argparse.ArgumentParser(prog="harness77 run", allow_abbrev=False,
                                     description="Полный цикл проверки внешней обработки 1С 7.7")
    parser.add_argument("--project", required=True, type=Path, help="Профиль проекта TOML")
    parser.add_argument("--stand", required=True, type=Path, help="Профиль стенда TOML")
    parser.add_argument("--output-root", type=Path, default=Path(".artifacts/runs"),
                        help="Корень каталогов запусков; каждый запуск получает подкаталог run_id")
    for phase, key in (("open", "open-timeout-s"), ("calculation", "calculation-timeout-s"),
                       ("cancel", "cancel-timeout-s"), ("shutdown", "shutdown-timeout-s"),
                       ("total", "total-timeout-s")):
        parser.add_argument("--" + key, type=float, default=None,
                            help=f"Переопределить срок фазы {phase} (секунды)")
    parser.add_argument("--reindex-timeout-s", type=float, default=None,
                        help="Запас к сроку открытия, если прошлый сеанс 1С на базе был прерван")
    parser.add_argument("--run-id", default=None, help="Задать run_id (по умолчанию новый UUID)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        project = load_project(args.project)
        stand = load_stand(args.stand)
        overrides = {"open_timeout_s": args.open_timeout_s, "calculation_timeout_s": args.calculation_timeout_s,
                     "cancel_timeout_s": args.cancel_timeout_s, "shutdown_timeout_s": args.shutdown_timeout_s,
                     "total_timeout_s": args.total_timeout_s, "reindex_timeout_s": args.reindex_timeout_s}
        deadlines = resolve_deadlines(project, stand, overrides)
    except (ConfigError, DeadlineError, OSError) as error:
        blocked = {"schema_version": 1, "tool": "harness77", "operation": "run", "status": BLOCKED,
                   "exit_code": 2, "reason": f"{type(error).__name__}: {error}", "platform_checked": False}
        print(json.dumps(blocked, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    cancel = threading.Event()
    signals = [signal.SIGINT] + ([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else [])
    previous = {}
    try:
        for number in signals:
            previous[number] = signal.getsignal(number)
            signal.signal(number, lambda *_: cancel.set())
    except ValueError:
        previous = {}  # Not the main thread; cancellation stays injectable only.
    try:
        report = execute(project, stand, deadlines, output_root=args.output_root, run_id=args.run_id, cancel=cancel)
    except OSError as error:
        blocked = {"schema_version": 1, "tool": "harness77", "operation": "run", "status": BLOCKED,
                   "exit_code": 2, "reason": f"{type(error).__name__}: {error}", "platform_checked": False}
        print(json.dumps(blocked, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    print(json.dumps(_summary(report), ensure_ascii=False, indent=2))
    return report["exit_code"]
