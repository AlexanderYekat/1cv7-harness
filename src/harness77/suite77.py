"""Sequential full-cycle scenarios with linked JSON results and JUnit XML (task 029)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET

from . import __version__
from .config77 import (ConfigError, _load_toml, _resolve, load_project, load_stand,
                       path_tag, resolve_deadlines, FixtureFileError)
from .deadlines77 import DeadlineError
from .progress77 import publish_suite_scenario
from .report77 import BLOCKED, FAILED, PASSED, SKIPPED, atomic_json, exit_code, file_evidence
from . import run77

DEFAULT_OUTPUT_ROOT = Path(".artifacts/suites")
SUITE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    project: Path


@dataclass(frozen=True)
class SuiteProfile:
    path: Path
    suite_id: str
    scenarios: tuple[Scenario, ...]


def _name(value, where):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ConfigError(f"{where}: expected a non-empty name without control characters")
    return value


def load_suite(path):
    data, path = _load_toml(path)
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ConfigError("suite: schema_version = 1 is required")
    if set(data) != {"schema_version", "suite", "scenarios"}:
        raise ConfigError("suite: only schema_version, [suite] and [[scenarios]] are allowed")
    header, items = data["suite"], data["scenarios"]
    if not isinstance(header, dict) or set(header) != {"id"}:
        raise ConfigError("[suite] requires only id")
    name = _name(header["id"], "suite.id")
    if not isinstance(items, list) or not items:
        raise ConfigError("suite requires at least one scenario")
    scenarios, seen = [], set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or set(item) != {"id", "project"}:
            raise ConfigError(f"scenario {index}: only id and project are required")
        identifier = _name(item["id"], f"scenario {index}.id")
        if identifier.casefold() in seen:
            raise ConfigError(f"duplicate scenario id: {identifier}")
        seen.add(identifier.casefold())
        project = _resolve(path.parent, item["project"], f"scenario {index}.project")
        scenarios.append(Scenario(identifier, project))
    return SuiteProfile(path, name, tuple(scenarios))


def _counts(rows):
    return {status: sum(row["status"] == status for row in rows)
            for status in (PASSED, FAILED, BLOCKED, SKIPPED)}


def _status(report):
    counts = report["counts"]
    if not report["complete"] or report["cancelled"] or counts[BLOCKED] or counts[SKIPPED]:
        return BLOCKED
    return FAILED if counts[FAILED] else PASSED


# XML 1.0 text, including the allowed astral planes; ET alone does not filter controls.
_XML_BAD = re.compile("[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def _xml_text(value):
    return _XML_BAD.sub("\ufffd", str(value))


def _junit_counts(report):
    counts = report["counts"]
    return {"tests": str(len(report["scenarios"])), "failures": str(counts[FAILED]),
            "errors": str(counts[BLOCKED]), "skipped": str(counts[SKIPPED])}


def _junit_link(row):
    return {key: row.get(key) for key in ("run_id", "report", "platform_checked", "cancelled", "timeout_phase")}


def junit(report):
    """One testcase per scenario, judged by the full cycle, not raw operation statuses."""
    attributes = {"name": _xml_text(report["name"]), **_junit_counts(report), "time": str(report["duration_s"])}
    root = ET.Element("testsuites", attributes)
    suite = ET.SubElement(root, "testsuite", attributes)
    properties = ET.SubElement(suite, "properties")
    for key in ("suite_id", "complete", "cancelled", "status", "exit_code"):
        ET.SubElement(properties, "property", name=key, value=_xml_text(report[key]))
    for row in report["scenarios"]:
        case = ET.SubElement(suite, "testcase", name=_xml_text(row["id"]),
                             classname=_xml_text(report["name"]), time=str(row["duration_s"]))
        tag = {FAILED: "failure", BLOCKED: "error", SKIPPED: "skipped"}.get(row["status"])
        if tag:
            outcome = ET.SubElement(case, tag, message=_xml_text(row["reason"] or row["status"]))
            outcome.text = _xml_text(json.dumps(row.get("problems", []), ensure_ascii=False, indent=2))
        ET.SubElement(case, "system-out").text = _xml_text(json.dumps(_junit_link(row), ensure_ascii=False))
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def junit_issue(data, report):
    """Compare the JUnit cases with a verified, completed suite report."""
    try:
        xml = data.decode("utf-8")
        if "<!DOCTYPE" in xml:
            return "junit.xml содержит объявление DOCTYPE"
        root = ET.fromstring(xml)
    except (ValueError, ET.ParseError):
        return "junit.xml содержит некорректный XML"
    if root.tag != "testsuites" or len(root) != 1 or root[0].tag != "testsuite":
        return "структура junit.xml не совпадает с форматом suite"
    suite = root[0]
    counters = _junit_counts(report)
    if any(node.get(key) != value for node in (root, suite) for key, value in counters.items()):
        return "счётчики junit.xml не совпадают с suite.json"
    cases = suite.findall("testcase")
    rows = report["scenarios"]
    if len(cases) != len(rows):
        return "число testcase в junit.xml не совпадает с suite.json"
    suite_name = report.get("name")
    if not isinstance(suite_name, str) or any(node.get("name") != _xml_text(suite_name) for node in (root, suite)):
        return "имя набора в junit.xml не совпадает с suite.json"
    for row, case in zip(rows, cases):
        label = f"сценарий «{row['id']}»"
        if case.get("name") != _xml_text(row["id"]) or case.get("classname") != _xml_text(suite_name):
            return f"{label}: имя testcase в junit.xml не совпадает с suite.json"
        outcomes = [node for node in case if node.tag in ("failure", "error", "skipped")]
        if [node.tag for node in outcomes] != (["failure"] if row["status"] == FAILED else []):
            return f"{label}: исход testcase в junit.xml не совпадает с suite.json"
        if outcomes and outcomes[0].get("message") != _xml_text(row.get("reason") or row["status"]):
            return f"{label}: причина провала в junit.xml не совпадает с suite.json"
        outputs = case.findall("system-out")
        if len(outputs) != 1 or len(outputs[0]):
            return f"{label}: отсутствует однозначная ссылка system-out в junit.xml"
        try:
            link = json.loads(outputs[0].text or "")
        except ValueError:
            return f"{label}: system-out в junit.xml содержит некорректный JSON"
        if json.dumps(link, sort_keys=True) != json.dumps(_junit_link(row), sort_keys=True):
            return f"{label}: ссылка system-out в junit.xml не совпадает с suite.json"
    return None


def _publish_with_retry(write, *args):
    # Readers of the previous checkpoint can briefly deny replacement on Windows.
    until = time.monotonic() + 1
    while True:
        try:
            write(*args)
            return
        except PermissionError as error:
            remaining = until - time.monotonic()
            if getattr(error, "winerror", None) not in (5, 32, 33) or remaining <= 0:
                raise
            time.sleep(min(0.025, remaining))


def _publish(folder, report, started):
    report["duration_s"] = round(time.monotonic() - started, 3)
    report["counts"] = _counts(report["scenarios"])
    report["status"] = _status(report)
    report["exit_code"] = exit_code(report["status"])
    temporary = folder / "junit.xml.tmp"
    temporary.write_bytes(junit(report))
    _publish_with_retry(temporary.replace, folder / "junit.xml")
    report["junit"] = file_evidence(folder / "junit.xml", root=folder, complete=True)
    _publish_with_retry(atomic_json, folder / "suite.json", report)


def _continuation_issue(report, stand):
    """Do not hand an unverified session or copy to the next scenario."""
    platform = next((s for s in report["stages"] if s["stage"] == "platform_check"), {})
    copy = platform.get("base_copy")
    # Leaving the copy queue without acquiring a lock never starts a native session.
    if (platform.get("status") == BLOCKED and copy is not None and set(copy) == {"wait"}
            and copy["wait"].get("acquired") is False):
        return None
    shutdown = report.get("shutdown") or {}
    # A native platform stage can fail before starting the launcher. Continuing without
    # shutdown evidence would make that distinction an unsafe inference.
    if stand.backend == "native" and platform.get("status") != SKIPPED:
        wait = (platform.get("open") or {}).get("registration_wait") or {}
        # The launcher takes its process baseline only after acquiring the stand.
        reason = platform.get("reason")
        cancelled = reason == "cancelled" and report.get("cancelled") is True
        timed_out = reason == "open_timeout" and report.get("timeout_phase") == "open"
        stopped_in_queue = (platform.get("status") == BLOCKED and wait.get("acquired") is False
                            and shutdown.get("forced_cleanup") is False and (cancelled or timed_out))
        if shutdown.get("cleanup_verified") is not True or (
                shutdown.get("others_preserved") is not True and not stopped_in_queue):
            return "native session cleanup was not verified"
    if copy is not None:
        if (copy.get("removal") or {}).get("removed") is not True:
            return "base copy removal was not verified"
        if (copy.get("lock") or {}).get("released") is not True:
            return "base copy lock release was not verified"
        if (copy.get("source_check") or {}).get("unchanged") is not True:
            return "source base preservation was not verified"
    if (platform.get("base_list") or {}).get("unchanged") is False:
        return "the registered base list changed"
    return None


def _run_result(folder, row, expected_id, returned):
    """Read the actual report; absent, stale or inconsistent results cannot pass."""
    path = folder.parent / "runs" / expected_id / "run.json"
    disk = json.loads(path.read_text(encoding="utf-8"))
    if disk != returned or disk.get("run_id") != expected_id or disk.get("operation") != "run":
        raise ValueError("run.json is foreign or differs from the executor result")
    if disk.get("status") not in (PASSED, FAILED, BLOCKED) or disk.get("exit_code") != exit_code(disk["status"]):
        raise ValueError("run.json has an inconsistent status or exit code")
    if not isinstance(disk.get("stages"), list) or not disk["stages"]:
        raise ValueError("run.json has no stage results")
    evidence = file_evidence(path, complete=True)
    evidence["path"] = os.path.relpath(path, folder).replace("\\", "/")
    row.update(status=disk["status"], reason=disk.get("reason"), report=evidence,
               platform_checked=disk.get("platform_checked", False),
               cancelled=disk.get("cancelled", False), timeout_phase=disk.get("timeout_phase"),
               stages={s["stage"]: s["status"] for s in disk["stages"]},
               problems=_problems(disk["stages"]))
    return disk


def _problems(stages):
    """Keep the aggregate concise; complete diagnostics and values remain in run.json."""
    rows = []
    for stage in stages:
        if not stage.get("required") or stage["status"] not in (FAILED, BLOCKED):
            continue
        tests = [t for t in stage.get("tests", []) if not t.get("expectation_met")]
        diagnostics = stage.get("diagnostics", [])
        rows.append({"stage": stage["stage"], "status": stage["status"], "reason": stage.get("reason"),
                     "diagnostics_count": len(diagnostics), "diagnostics": diagnostics[:20],
                     "unmet_tests_count": len(tests), "unmet_tests": [
                         {**{k: str(t[k])[:2000] for k in ("name", "expect", "status", "expect_value", "value", "note")
                             if k in t},
                          **({'structured': {k: t['structured'][k] for k in
                                             ('status', 'difference_count', 'differences_truncated', 'result', 'diagnostics')
                                             if k in t['structured']}}
                             if 'structured' in t else {})} for t in tests[:20]]})
    return rows


def execute(suite, stand, *, output_root, suite_id=None, overrides=None, cancel=None, runner=None,
            wait_for_copy=False):
    """Execute independent runs in manifest order. The injected runner has run77.execute's API."""
    suite_id = str(uuid.uuid4()) if suite_id is None else suite_id
    if not SUITE_ID_PATTERN.fullmatch(suite_id):
        raise ConfigError("suite-id must be a single ASCII identifier (letters, digits, _ or -)")
    if suite_id.casefold() == "runs":
        raise ConfigError("suite-id 'runs' is reserved for child run results")
    cancel = cancel if cancel is not None else threading.Event()
    runner = runner or run77.execute
    run_options = {"wait_for_copy": True} if wait_for_copy else {}
    folder = Path(output_root).resolve() / suite_id
    # Keep the native launcher's paths independent of the suite identifier's length.
    # Deeply nesting UUID/suite/runs/UUID reproduced open_timeout on the pinned 1C 7.7 stand.
    runs = folder.parent / "runs"
    folder.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {"schema_version": 1, "tool": "harness77", "operation": "suite", "version": __version__,
              "suite_id": suite_id, "name": suite.suite_id, "suite_dir": str(folder),
              "layout": "shared-runs-v1", "runs_dir": str(runs),
              "inputs": {"suite": path_tag(suite.path), "sha256": file_evidence(suite.path)["sha256"]},
              "platform": stand.public(), "started_at": run77._now_iso(), "finished_at": None,
              "complete": False, "cancelled": False, "reason": None,
              "scenarios": [{"id": s.scenario_id, "project": path_tag(s.project), "status": SKIPPED,
                             "reason": "not started", "duration_s": 0.0, "run_id": None,
                             "report": None, "platform_checked": False} for s in suite.scenarios]}
    _publish(folder, report, started)
    stop = None
    for index, (scenario, row) in enumerate(zip(suite.scenarios, report["scenarios"]), 1):
        if cancel.is_set():
            report["cancelled"] = True
            stop = "cancelled"
        if stop:
            row["reason"] = "not started: " + stop
            continue
        publish_suite_scenario(index, len(suite.scenarios), scenario.scenario_id)
        began = time.monotonic()
        try:
            project = load_project(scenario.project)
            if project.keep_copy:
                raise ConfigError("suite scenarios require configuration.keep_copy = false")
            deadlines = resolve_deadlines(project, stand, overrides)
        except (OSError, ValueError, TypeError, KeyError) as error:
            # No platform process has started; this scenario cannot prevent later ones.
            row.update(status=BLOCKED, reason=f"project_error: {type(error).__name__}: {error}")
        else:
            row["run_id"] = str(uuid.uuid4())
            row.update(status=BLOCKED, reason="scenario is running; no complete result yet")
            _publish(folder, report, started)
            try:
                result = runner(project, stand, deadlines, output_root=runs,
                                run_id=row["run_id"], cancel=cancel, **run_options)
                disk = _run_result(folder, row, row["run_id"], result)
                stop = _continuation_issue(disk, stand)
                if stop:
                    row.update(status=BLOCKED, reason=stop)
                if disk.get("cancelled"):
                    report["cancelled"] = True
                    stop = "cancelled"
                if cancel.is_set() and row["status"] == PASSED:
                    row.update(status=BLOCKED, reason="cancelled before scenario completion was recorded")
            except FixtureFileError as error:  # execute refresh refused inputs before creating a run/session.
                row.update(status=BLOCKED, reason=f'project_error: {error}', run_id=None)
            except Exception as error:  # A runner failure leaves session state unknown; never start another.
                stop = f"run_error: {type(error).__name__}: {error}"
                row.update(status=BLOCKED, reason=stop)
        row["duration_s"] = round(time.monotonic() - began, 3)
        _publish(folder, report, started)
    report["cancelled"] = report["cancelled"] or cancel.is_set()
    if report["cancelled"] and all(r["status"] == PASSED for r in report["scenarios"]):
        report["scenarios"][-1].update(status=BLOCKED, reason="cancelled before suite completion was recorded")
    report.update(complete=True, finished_at=run77._now_iso())
    report["reason"] = stop or ("cancelled" if report["cancelled"] else None) or next(
        (r["reason"] for r in report["scenarios"] if r["status"] != PASSED), None)
    _publish(folder, report, started)
    return report


def main(argv=None):
    import argparse
    import signal
    import sys

    parser = argparse.ArgumentParser(prog="harness77 suite", allow_abbrev=False, description=__doc__)
    parser.add_argument("--suite", type=Path, required=True, help="TOML manifest of scenario project profiles")
    parser.add_argument("--stand", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--suite-id", help="New result directory name; default: UUID")
    parser.add_argument("--cancel-file", type=Path)
    parser.add_argument("--wait-for-copy", action="store_true", help=argparse.SUPPRESS)
    for phase in ("open", "calculation", "cancel", "shutdown", "total", "reindex"):
        parser.add_argument(f"--{phase}-timeout-s", type=float)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    cancel, done, previous = threading.Event(), threading.Event(), {}
    try:
        if args.cancel_file is not None and os.path.lexists(args.cancel_file):
            raise FileExistsError(f"the cancel file already exists: {args.cancel_file}")
        suite, stand = load_suite(args.suite), load_stand(args.stand)
        for number in [signal.SIGINT] + ([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else []):
            try:
                handler = signal.getsignal(number)
                signal.signal(number, lambda *_: cancel.set())
                previous[number] = handler
            except ValueError:
                break  # Non-main-thread callers inject cancellation through execute().
        if args.cancel_file is not None:
            threading.Thread(target=run77._watch_cancel_file,
                             args=(args.cancel_file, cancel, done), daemon=True).start()
        overrides = {f"{p}_timeout_s": getattr(args, f"{p}_timeout_s")
                     for p in ("open", "calculation", "cancel", "shutdown", "total", "reindex")}
        report = execute(suite, stand, output_root=args.output_root, suite_id=args.suite_id,
                         overrides=overrides, cancel=cancel, wait_for_copy=args.wait_for_copy)
    except (ConfigError, DeadlineError, OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"schema_version": 1, "tool": "harness77", "operation": "suite", "status": BLOCKED,
                          "exit_code": 2, "reason": f"{type(error).__name__}: {error}"}, ensure_ascii=False),
              file=sys.stderr)
        return 2
    finally:
        done.set()
        for number, handler in previous.items():
            signal.signal(number, handler)
    print(json.dumps({key: report[key] for key in ("suite_id", "suite_dir", "runs_dir", "status", "exit_code", "counts",
                                                  "complete", "cancelled", "reason", "junit")},
                     ensure_ascii=False, indent=2))
    return report["exit_code"]
