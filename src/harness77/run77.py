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
import os
from pathlib import Path
import threading
import uuid

from . import __version__
from .deadlines77 import Clock, RunClock
from .report77 import (BLOCKED, FAILED, PASSED, SKIPPED, Stage, atomic_json,
                       exit_code, file_evidence, sha256_bytes, sha256_file)

STAGE_SCOPES = {
    "configuration": "verified 1Cv7.MD build: the stand base's configuration with the project's changed modules",
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


def _configuration_stage(project, stand, run_dir):
    """Task 021: the stand base's 1Cv7.MD with the project's changed modules, for a copy of the base."""
    from .ert_module import ErtError
    from .md77 import build
    stage = Stage("configuration", required=True, scope=STAGE_SCOPES["configuration"])
    template = Path(stand.base) / "1Cv7.MD"
    output = run_dir / "configuration" / "1Cv7.MD"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        # The copy keeps the stand's data dictionary, so the configuration must be the pinned one.
        pinned = stand.pinned.get("1Cv7.MD")
        if pinned is not None and sha256_file(template) != pinned:
            raise ErtError("1Cv7.MD базы стенда не совпадает с закреплённым хешем")
        report = build(template, project.configuration, output)
    except (OSError, ValueError, ErtError) as error:
        return stage.finish(BLOCKED, reason=f"configuration_error: {type(error).__name__}: {error}"), None
    evidence = file_evidence(output, root=run_dir, complete=True, expected_sha256=report["output"]["sha256"])
    stage.finish(PASSED, evidence=[evidence], template_sha256=report["template"]["sha256"],
                 configuration=report["template"]["configuration"], md_sha256=report["output"]["sha256"],
                 rebuilt=report["rebuilt"], changed=report["changed"],
                 unchanged_modules=report["unchanged_modules"], index=report["modules"]["index"])
    return stage, {"path": output, "sha256": report["output"]["sha256"], "template": template,
                   "changed": [row["path"] for row in report["changed"]], "rows": report["changed"]}


def _static_stage(project, stand=None, configuration=None):
    from .ert_module import CompoundFile, ErtError
    from .lint77 import analyze, collect_paths, ert_dialog, load_metadata, load_sources
    stage = Stage("static", required=True, scope=STAGE_SCOPES["static"])
    # The base the module runs on names the objects of L7712/L7713 (task 018): the
    # project's [build] metadata, otherwise the stand base's 1Cv7.MD when there is one;
    # with a changed configuration (task 021), the built one.
    if configuration is not None:
        metadata_path, metadata_source = Path(configuration["path"]), "configuration"
    elif project.metadata is not None:
        metadata_path, metadata_source = Path(project.metadata), "project"
    elif stand is not None and (Path(stand.base) / "1Cv7.MD").is_file():
        metadata_path, metadata_source = Path(stand.base) / "1Cv7.MD", "stand"
    else:
        metadata_path = metadata_source = None
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
        metadata = load_metadata(metadata_path) if metadata_path is not None else None
        for source in sources:
            if source.metadata is None:
                source.metadata = metadata
        globals_sources = [s for path in project.globals
                           for s in load_sources(Path(path), own_metadata_names=False)]
        changed = md_sources = ()
        base_globals = list(globals_sources)
        if configuration is not None:
            # The changed modules in the context of the built configuration (task 020); its
            # global module gives its exports to them and to the ERT's module.
            built = load_sources(Path(configuration["path"]))
            changed = set(configuration["changed"])
            md_sources = [s for s in built if s.module in changed or s.is_global]
            globals_sources += [s for s in built if s.is_global]
        report = analyze(sources + list(md_sources), globals_sources, project.allow, project.strict)
        diagnostics, preexisting = report["diagnostics"], 0
        if configuration is not None:
            # The same modules of the template tell the remarks a changed module already had.
            template = before = ()
            if changed:
                template = [s for s in load_sources(Path(configuration["template"]))
                            if s.module in changed or s.is_global]
                before = analyze(template, base_globals + [s for s in template if s.is_global], project.allow,
                                 project.strict)["diagnostics"]
            diagnostics, preexisting = _own_remarks(diagnostics, before, configuration, changed, md_sources, template)
    except (OSError, ValueError, ErtError) as error:
        return stage.finish(BLOCKED, reason=f"static_input_error: {type(error).__name__}: {error}")
    errors = sum(row["severity"] == "error" for row in diagnostics)
    status = FAILED if errors else PASSED
    return stage.finish(status, diagnostics=diagnostics,
                        errors=errors, warnings=sum(row["severity"] == "warning" for row in diagnostics),
                        metadata=({"sha256": metadata.sha256, "configuration": metadata.configuration,
                                   "source": metadata_source} if metadata is not None else None),
                        **({"configuration_modules": sorted(changed), "configuration_preexisting": preexisting}
                           if configuration is not None else {}))


def _own_remarks(diagnostics, before, configuration, changed, built, template):
    """(diagnostics, count of the remarks the template's module already had) of a configuration run.

    Of the built configuration only the changed modules are this run's, and of them only what
    the template's same module did not have: a remark is its module, rule, message (without the
    hash of the metadata it names) and the text of its line, for the line numbers move with the
    change. The global module is also its own context, so a changed one repeats a parse remark.
    """
    import re
    from collections import Counter
    built_path = str(Path(configuration["path"]).resolve())
    template_path = str(Path(configuration["template"]).resolve())

    def remark(row, texts):
        lines = texts.get(row["module"], "").splitlines()
        text = lines[row["line"] - 1].strip() if 0 < row["line"] <= len(lines) else ""
        return row["module"], row["rule"], re.sub(r"[0-9a-f]{8}…", "", row["message"]), text
    had = Counter(remark(row, {s.module: s.text for s in template}) for row in before
                  if row["path"] == template_path and row["module"] in changed)
    texts = {s.module: s.text for s in built}
    kept, seen, preexisting = [], set(), 0
    for row in diagnostics:
        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key in seen or (row["path"] == built_path and row["module"] not in changed):
            continue
        seen.add(key)
        if row["path"] == built_path and had[remark(row, texts)] > 0:
            had[remark(row, texts)] -= 1
            preexisting += 1
            continue
        kept.append(row)
    return kept, preexisting


def _metadata(project, stand):
    """(1Cv7.MD path, source) the build checks the kinds of the form against (tasks 012, 013), or (None, None).

    The project's own [build] metadata wins; otherwise the stand base's 1Cv7.MD is
    taken only when the description has a field of a kind (Справочник.Контрагенты).
    """
    from .ert_module import ErtError
    from .form77 import loads, needs_metadata
    if project.form is None:
        return None, None
    if project.metadata is not None:
        return project.metadata, "project"
    try:
        needed = needs_metadata(loads(Path(project.form).read_bytes()))
    except (OSError, ErtError):
        return None, None  # the build stage reports an unreadable description
    return (Path(stand.base) / "1Cv7.MD", "stand") if needed and stand is not None else (None, None)


def _build_stage(project, run_dir, stand=None):
    from .artifacts import build
    from .ert_module import ErtError
    stage = Stage("build", required=True, scope=STAGE_SCOPES["build"])
    output = run_dir / "build" / (project.project_id + ".ert")
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata, source = _metadata(project, stand)
    try:
        report = build(project.template, project.source, output, encoding=project.encoding,
                       legacy_normalize=project.legacy_normalize, form=project.form, metadata=metadata)
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
                              ("sha256", "template_dialog_sha256", "dialog_sha256", "changes", "kinds")}}
                    if "form" in report else {}))
    if "metadata" in report.get("form", {}):
        stage.details["form"]["metadata"] = {"sha256": report["form"]["metadata"]["sha256"],
                                             "configuration": report["form"]["metadata"]["configuration"],
                                             "source": source}
    if "ert_metadata" in report.get("form", {}):
        stage.details["form"]["ert_metadata"] = report["form"]["ert_metadata"]
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


def _stand_kinds(stand, built):
    """(reason to block or None, check) of the stand base by the names of the form's kinds (task 013).

    1C finds the kind of a field by the name the ERT's copy gives its number; a kind
    the open base lacks silently costs the field its kind (any object of the type,
    an enumeration a string). A base other than the build's metadata is checked
    here; a different number is no matter.
    """
    from .ert_module import ErtError
    from .metadata77 import Metadata
    form = (built.get("build") or {}).get("form") or {}
    target = Path(stand.base) / "1Cv7.MD"
    if not form.get("kinds") or not target.is_file():
        return None, None
    data = target.read_bytes()
    if (form.get("metadata") or {}).get("sha256") == sha256_bytes(data):
        return None, {"sha256": form["metadata"]["sha256"], "same_as_build": True, "missing": []}
    try:
        metadata = Metadata(data, target)
    except ErtError as error:
        return f"metadata_unreadable: the stand base 1Cv7.MD: {error}", None
    missing = [{"control": row["control"], "object": row["object"]} for row in form["kinds"]
               if metadata.number(row["code"], row["object"].partition(".")[2]) is None]
    check = {"sha256": metadata.sha256, "configuration": metadata.configuration, "same_as_build": False,
             "missing": missing}
    if not missing:
        return None, check
    names = ", ".join(f"{row['object']} (control {row['control']})" for row in missing)
    return (f"metadata_missing_kinds: the stand base 1Cv7.MD {metadata.sha256[:12]}… has no {names}; "
            "1C would open the form with these fields of no kind (any object of the type, "
            "an enumeration a string)"), check


def _platform_stage(stand, built, run_id, run_dir, deadlines, clock, cancel, observe, project=None,
                    configuration=None):
    """With a changed configuration (task 021) 1C opens a copy of the base with the built 1Cv7.MD at
    the stand's copy_path; the copy is removed afterwards and the stand base is checked as it was."""
    stage = Stage("platform_check", required=True, scope=STAGE_SCOPES["platform_check"])
    if configuration is None:
        return _platform_run(stage, stand, built, run_id, run_dir, deadlines, clock, cancel, observe, project)
    import dataclasses
    from . import basecopy77

    def refused(reason, **details):
        return (stage.finish(BLOCKED, reason=f"base_copy_error: {reason}", platform_checked=False, **details),
                {"status": BLOCKED}, None)
    if stand.copy_path is None:
        return refused("the stand has no [stand.base] copy_path: the path of the copy, registered once "
                       "in the 1C list of bases (1C 7.7 opens through OLE only a registered base)")
    source, target = Path(stand.base), Path(stand.copy_path)
    try:
        lock = basecopy77.acquire(target, run_id)
    except (OSError, basecopy77.BaseCopyError) as error:
        return refused(f"{type(error).__name__}: {error}")
    try:
        copy, before = basecopy77.copy(source, target, stand.copy_exclude, configuration["path"], run_id)
    except (OSError, basecopy77.BaseCopyError) as error:
        removal = basecopy77.remove(target)
        basecopy77.release(target, run_id)
        return refused(f"{type(error).__name__}: {error}", base_copy={"lock": lock, "removal": removal})
    copy["lock"] = lock
    # The copy carries the stand's files but the built configuration; its pin replaces the stand's.
    pinned = dict(stand.pinned)
    if "1Cv7.MD" in pinned:
        pinned["1Cv7.MD"] = configuration["sha256"]
    on_copy = dataclasses.replace(stand, base=target, pinned=pinned)
    offset = basecopy77.log_size(target)
    try:
        stage, result, backend = _platform_run(stage, on_copy, built, run_id, run_dir, deadlines, clock, cancel,
                                               observe, project, base_name=source.name,
                                               configuration_sha256=configuration["sha256"])
    finally:
        # The copy's event log keeps what 1C reported about the configuration, compile errors of
        # its modules included; it goes with the copy, so this session's part is kept here.
        copy["session_log"] = basecopy77.session_log(target, offset, run_dir / "base-session-log.txt")
        copy["kept"] = bool(project and project.keep_copy)
        copy["removal"] = None if copy["kept"] else basecopy77.remove(target)
        copy["lock"]["released"] = basecopy77.release(target, run_id)
        copy["source_check"] = basecopy77.unchanged(source, before)
        stage.details["base_copy"] = copy
    _configuration_compiled(stage, result, configuration, copy["session_log"].get("entries", []))
    return stage, result, backend


def _configuration_compiled(stage, result, configuration, entries):
    """Compile errors of the changed modules make the platform check fail (task 021).

    1C compiles a document's module at posting and a form's module at opening without an
    exception in the caller (Провести returns 0, the form stays closed), and with a broken
    global module 1C++ never loads, so the stand's controller cannot run: the event log of
    the copy is what tells. A session that ended unclean stays blocked.
    """
    from .md77 import configuration_diagnostics, read_modules
    found = configuration_diagnostics(entries, configuration["rows"])
    if not found:
        return
    if any(row.get("source_line") for row in found):
        from .ert_module import CompoundFile
        from .metadata77 import Metadata
        data = Path(configuration["path"]).read_bytes()
        files = {row["file"] for row in configuration["rows"]}
        texts = {module.file: module.raw.decode("cp1251")
                 for module in read_modules(CompoundFile(data), Metadata(data)) if module.file in files}
        found = configuration_diagnostics(entries, configuration["rows"], texts)
    stage.details["configuration_diagnostics"] = found
    own = [row for row in found if row["changed"]]
    shutdown = stage.details.get("shutdown") or {}
    clean = shutdown.get("cleanup_verified") is True and not shutdown.get("forced_cleanup")
    if own and (stage.status == PASSED or (stage.status == BLOCKED and clean)):
        first = own[0]
        where = f"{first['file'] or first['module']}:{first['line']}"
        stage.status = FAILED
        stage.reason = f"configuration_compilation_failed: {where}: {first['message']}"
        result["status"] = FAILED


def _platform_run(stage, stand, built, run_id, run_dir, deadlines, clock, cancel, observe, project=None,
                  base_name=None, configuration_sha256=None):
    from .backends77 import load_backend
    missing, check = _stand_kinds(stand, built)
    if missing:
        return (stage.finish(BLOCKED, reason=missing, platform_checked=False, metadata_check=check),
                {"status": BLOCKED}, None)
    backend = load_backend(stand, ert_path=built["path"], ert_sha256=built["sha256"],
                           run_id=run_id, run_dir=run_dir, clock=clock,
                           parameters=project.parameters if project else None,
                           commands=project.commands() if project else (),
                           captures=project.visual.captures() if project and project.visual else (),
                           base_name=base_name, configuration_sha256=configuration_sha256)
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
                 **({"metadata_check": check} if check else {}),
                 **({"base_list": result["base_list"]} if result.get("base_list") else {}),
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
    static = _build = platform = tests = visual = configuration_stage = configuration = None
    platform_result = None
    try:
        if project.configuration is not None:
            configuration_stage, configuration = _configuration_stage(project, stand, run_dir)
            report["platform"]["base_usage"] = "copy-per-run"
        static = _static_stage(project, stand, configuration)
        build_stage, built = _build_stage(project, run_dir, stand)
        _build = build_stage
        unbuilt = ("no ERT was built" if built is None else
                   "no configuration was built" if project.configuration is not None and configuration is None
                   else None)
        if unbuilt:
            platform = Stage("platform_check", required=True, scope=STAGE_SCOPES["platform_check"]).finish(
                SKIPPED, reason=unbuilt)
            tests = Stage("tests", required=True, scope=STAGE_SCOPES["tests"]).finish(SKIPPED, reason=unbuilt)
            if project.visual is not None:
                from .visual77 import STAGE_SCOPE
                visual = Stage("visual", required=True, scope=STAGE_SCOPE).finish(SKIPPED, reason=unbuilt)
        else:
            report["artifact"] = build_stage.evidence[0]
            report["artifact"]["module_sha256"] = build_stage.details["module_sha256"]
            if configuration is not None:
                report["configuration"] = configuration_stage.evidence[0]
            platform, platform_result, backend = _platform_stage(
                stand, built, run_id, run_dir, deadlines, clock, cancel, observe, project, configuration)
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
    stages = [s for s in (configuration_stage, static, _build, platform, tests, visual) if s is not None]
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


def _watch_cancel_file(path, cancel, done, interval=0.2):
    """Set ``cancel`` once ``path`` appears: cancellation without a console (task 014)."""
    while not done.wait(interval):
        if os.path.lexists(path):
            cancel.set()
            return


def main(argv=None):
    import argparse
    import signal
    import sys

    from .config77 import ConfigError, load_project, load_stand, resolve_deadlines
    from .deadlines77 import DeadlineError

    parser = argparse.ArgumentParser(prog="harness77 run", allow_abbrev=False,
                                     description="Полный цикл проверки внешней обработки 1С 7.7; с [configuration] "
                                                 "в профиле проекта — и изменённых модулей 1Cv7.MD на копии базы")
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
    parser.add_argument("--cancel-file", type=Path, default=None,
                        help="Отменить запуск, когда появится этот файл (как Ctrl+C, но без консоли)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        if args.cancel_file is not None and os.path.lexists(args.cancel_file):
            raise FileExistsError(f"the cancel file already exists: {args.cancel_file}")
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
    done = threading.Event()
    if args.cancel_file is not None:
        threading.Thread(target=_watch_cancel_file, args=(args.cancel_file, cancel, done), daemon=True).start()
    try:
        report = execute(project, stand, deadlines, output_root=args.output_root, run_id=args.run_id, cancel=cancel)
    except OSError as error:
        blocked = {"schema_version": 1, "tool": "harness77", "operation": "run", "status": BLOCKED,
                   "exit_code": 2, "reason": f"{type(error).__name__}: {error}", "platform_checked": False}
        print(json.dumps(blocked, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    finally:
        done.set()
        for number, handler in previous.items():
            signal.signal(number, handler)
    print(json.dumps(_summary(report), ensure_ascii=False, indent=2))
    return report["exit_code"]
