"""Native launcher bridge for the harness77 stage-4 full cycle.

The product's native backend (``harness77.native77``) invokes this script on the
real stand. It drives *this run's already-built ERT* through the accepted
research controller (``session77.run_session``: ownership proven before
Initialize, private desktop, coordinated-icpp-v1 shutdown, baseline preserved)
and writes ``platform-result.json`` in the contract the backend expects.

It does not relax any research guard. The ERT's module must cooperate with the
headless contract (a ``ПриОткрытии`` that reports ``loaded:harness77`` /
``completed:harness77`` and, on ``execute``, ``value:<n>``; ``СтатусВозврата(0)``
so no form is shown). The constant marker ties the response to the module, while
the run_id and the ERT SHA-256 (verified here and echoed to the backend) tie the
result to this run.

Deadlines come from section 8.5 (``--deadlines-json``): each ERT command gets
the calculation deadline, the session limit is total (it covers opening the
base, reindexing included), and the client (cscript) limit covers total +
shutdown, so a tens-of-minutes report is not cut at 140 s. A
``cancel`` file in the run directory (written by the backend on Ctrl+C) stops
the session through the same owned-only cleanup as a deadline.

An application with its own headless contract plugs in as an *adapter*
(task 006): its commands, controller, environment, base preflight, reading of
the response and result files. ``Harness77Adapter`` is the stage-4 contract.
"""

import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import uuid

import ert_probe77 as probe
from module_suite77 import vb_assignment
from run_shutdown77 import preflight
from shutdown77 import MODE, assess, atomic_json, prepare_shutdown, sha256
from concurrent77 import IDENTITY_SHA

IDENTITY = "harness77"            # constant cooperation marker; run identity is separate
COMMANDS = ("check", "execute")   # compile-only, then the control/report call
PROTOCOL_DIRECTORY = probe.PROTOCOL_DIRECTORY
# Core timeout phases in the section 8.5 vocabulary of the run report.
PHASES = {"ownership": "open", "debugger-ready": "open", "open-base": "open", "open": "open",
          "ert-operation": "calculation", "modal-recovery": "calculation",
          "session": "total", "shutdown": "shutdown"}


def preflight_copy(base, exe, cdb, helper, out):
    """The core preflight for another copy of the pinned base: same hashes, any path.

    The core qualifies only .local/bases/base-for-test by path; a copy (the owner
    keeps several) must carry exactly the pinned configuration and components,
    and a base held by 1C in exclusive mode is refused before any 1C starts.
    """
    from shutdown77 import PINNED
    import run_shutdown77
    if base == (run_shutdown77.ROOT / ".local/bases/base-for-test").resolve():
        preflight(base, exe, cdb, helper, out)
        return
    if out.is_relative_to(base) or base.is_relative_to(out):
        raise ValueError("output and database trees must not overlap")
    if any(c in str(out) for c in '"; \r\n') or not str(out).isascii():
        raise ValueError("output must be ASCII without spaces or debugger separators")
    if out.exists():
        raise ValueError("output must be a fresh directory")
    for name, path in {"exe": exe, "helper": helper,
                       **{n: base / n for n in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll")}}.items():
        if sha256(path) != PINNED[name]:
            raise ValueError("unqualified binary/configuration: " + name)
    data = cdb.read_bytes()
    pe = int.from_bytes(data[0x3c:0x40], "little")
    if data[:2] != b"MZ" or data[pe:pe + 6] != b"PE\0\0\x4c\x01":
        raise ValueError("x86 CDB is required")
    try:
        with (base / "1SJOURN.DBF").open("rb") as stream:
            stream.read(32)
    except PermissionError:
        raise ValueError("the base is open in 1C in exclusive mode") from None


def base_trace(base):
    """Signs, before starting, that the previous 1C session on the base was interrupted.

    Observed natively (task 007, R1): a working 1C keeps 1Cv7.LCK without holding
    it and locks 1SUSERS.DBF, so the users table cannot be read; a normal exit
    deletes 1Cv7.LCK and sets the active-user counter to 0. An interrupted
    session leaves 1Cv7.LCK and a readable 1SUSERS.DBF with active users > 0,
    and 1C reindexes the base on the next open.
    """
    trace = {"lock_file": (base / "1Cv7.LCK").exists(), "users_readable": False, "active_users": None}
    try:
        data = (base / "1SUSERS.DBF").read_bytes()
        trace["users_readable"] = True
        records, header = int.from_bytes(data[4:8], "little"), int.from_bytes(data[8:10], "little")
        offset, position = 1, 32
        while position + 32 <= header and data[position] != 0x0D:
            name = data[position:position + 11].split(b"\0", 1)[0].decode("ascii", "replace")
            length = data[position + 16]
            if name == "USRSCNT" and records:
                trace["active_users"] = int(data[header + offset:header + offset + length].strip() or 0)
            offset += length
            position += 32
    except (OSError, ValueError):
        pass  # unreadable: a working 1C locks the users table
    trace["interrupted"] = bool(trace["lock_file"] and trace["users_readable"] and (trace["active_users"] or 0) > 0)
    return trace


def open_deadline(deadlines, trace):
    """The open deadline: the profile's open, plus the reindex allowance after an interruption."""
    extra = deadlines.get("reindex_timeout_s", 0) if trace.get("interrupted") else 0
    return int(deadlines["open_timeout_s"] + extra)


def session_limits(deadlines):
    """Core limits from the section 8.5 deadlines: (operation, session, client) seconds.

    Opening the base happens before the first ERT command and may include the
    reindexing 1C does after an interrupted session (an hour or more on some
    bases): it is covered by the session limit, which includes the open phase.
    Each ERT command gets the calculation deadline, so a hang inside a report is
    noticed after `calculation`, not after `open + calculation`.
    """
    operation = int(deadlines["calculation_timeout_s"])
    session = deadlines["total_timeout_s"]
    # The client must outlive the session deadline, which ends the run first.
    client = int(session + deadlines["shutdown_timeout_s"])
    return operation, session, client


class Harness77Adapter:
    """Stage-4 cooperation: loaded:/completed:harness77 markers and value:<n>."""

    identity = IDENTITY

    def commands(self, parameters, requested):
        return list(COMMANDS)

    def controller(self, parameters):
        return Path(probe.__file__).with_name("ert_controller77.1s").read_text(encoding="utf-8")

    def prepare(self, run_dir, parameters):
        """Environment variables for the 1C process; the default needs none."""
        return {}

    def preflight(self, base, exe, cdb, helper, drive):
        preflight(base, exe, cdb, helper, drive)

    def operation(self, command, lines, actual, row):
        """Judge one command from the controller's response; return an issue or None."""
        loaded = ("loaded:" + IDENTITY) in lines
        completed = ("completed:" + IDENTITY) in lines
        if loaded and completed and "unexpected-visible-form" not in actual and "open-error:" not in actual:
            # The module ran: passed unless it reported a runtime error.
            row["status"] = "failed" if "runtime-error:" in actual else "passed"
            row["value"] = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("value:")), None)
        elif row["diagnostics"]:
            # Not loaded, but the compiler reported errors: a checked-code defect.
            row["status"] = "failed"
        else:
            row["status"] = "blocked"
            return "no cooperation markers and no diagnostic: " + command
        return None

    def platform_status(self, operations):
        return "failed" if any(o["status"] == "failed" for o in operations) else "passed"

    def result_files(self, run_dir, operations):
        return []

    def client(self, text):
        """The VBScript client; an adapter may add steps between commands (task 008)."""
        return text

    def watch(self, out, lifecycle, desktop):
        """A context around the session for an adapter's own observer; none by default."""
        return contextlib.nullcontext()


def scaffold(out, built_ert, run_id, adapter=None, commands=COMMANDS, parameters=None):
    """Reconstruct the controller/client/shutdown scaffolding for an external ERT."""
    adapter = adapter or Harness77Adapter()
    folder = out / "Тестовые обработки"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "Обработка проверки.ert"
    shutil.copyfile(built_ert, target)
    controller = adapter.controller(parameters or {})
    (out / "ert-controller.1s").write_text(controller, encoding="utf-8")
    protocol_root = out / PROTOCOL_DIRECTORY
    protocol_root.mkdir(exist_ok=True)
    client = Path(probe.__file__).with_name("ert_probe77.vbs").read_text(encoding="utf-8")
    client = client.replace("__PROXY_IDENTITY__",
                            Path(probe.__file__).with_name("proxy_identity77.vbs").read_text(encoding="utf-8"))
    suite = Path(probe.__file__).with_name("module_suite77.vbs").read_text(encoding="utf-8")
    utilities = suite[suite.index("Function Quote"):suite.index("Sub CompileCase")]
    shutdown, shutdown_manifest = prepare_shutdown(out, run_id)
    for key, value in {"RUN_ID": probe.vb_literal(run_id), "ERT_PATH": probe.vb_literal(str(target)),
                       "IDENTITY": probe.vb_literal(IDENTITY),
                       "SOURCES": vb_assignment("sourceController", controller), "UTILITIES": utilities,
                       "COMMANDS": ", ".join(probe.vb_literal(c) for c in commands),
                       "SHUTDOWN": shutdown}.items():
        client = client.replace("__" + key + "__", value)
    client = client.replace("__PROTOCOL_ROOT__", probe.vb_literal(str(protocol_root)))
    client = adapter.client(client)
    (out / "client.vbs").write_text(client, encoding="utf-16")
    shutdown_manifest["sources"]["client.vbs"] = sha256(out / "client.vbs")
    manifest = {"schema_version": 1, "run_id": run_id, "identity": IDENTITY, "ert_path": str(target),
                "commands": list(commands),
                "protocol_paths": {c: PROTOCOL_DIRECTORY + "/" + c + ".txt" for c in commands}}
    atomic_json(out / "ert-manifest.json", manifest)
    atomic_json(out / "shutdown-manifest.json", shutdown_manifest)
    return manifest, shutdown_manifest, target


def interpret(out, manifest, lifecycle, shutdown_result, adapter=None):
    """Validate the external-ERT response with the run markers; the adapter judges."""
    import re
    adapter = adapter or Harness77Adapter()
    operations, issues = [], []
    try:
        events = [json.loads(line) for line in (out / "ert-events.jsonl").read_text(encoding="utf-16").splitlines()]
    except (OSError, UnicodeError, ValueError) as error:
        return [], ["missing/malformed events: " + str(error)]
    by_command = {e.get("name"): e for e in events if isinstance(e, dict) and e.get("kind") == "ert"}
    for command in manifest["commands"]:
        event = by_command.get(command)
        row = {"name": command, "status": "blocked", "value": None, "diagnostics": [], "expectation_met": None}
        if event is None or event.get("run_id") != manifest["run_id"]:
            issues.append("missing operation: " + command)
            operations.append(row)
            continue
        actual = event.get("value", "")
        lines = actual.splitlines()
        protocol = ""
        try:
            data = (out / manifest["protocol_paths"][command]).read_bytes()
            protocol = data.decode("utf-16" if data.startswith(b"\xff\xfe") else "cp1251")
        except (OSError, UnicodeError) as error:
            issues.append("protocol unavailable for " + command + ": " + str(error))
        marker = manifest["run_id"] + ":" + command
        row["diagnostics"] = [{"line": int(m[1]), "message": m[2]} for m in re.finditer(
            r"^\{[^\r\n]*\(([0-9]{1,9})\)\}:[ \t]*([^\r\n]*)", protocol, re.MULTILINE)]
        begin_ok = lines and lines[0] == "selected:" + manifest["ert_path"]
        marker_ok = protocol.splitlines()[:1] == ["HARNESS77-BEGIN:" + marker] and \
            protocol.splitlines()[-1:] == ["HARNESS77-END:" + marker]
        if not begin_ok or not marker_ok:
            issues.append("protocol/selected marker mismatch: " + command)
        issue = adapter.operation(command, lines, actual, row)
        if issue:
            issues.append(issue)
        operations.append(row)
    return operations, issues


def main(argv=None, adapter=None):
    adapter = adapter or Harness77Adapter()
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    for name in ("run-dir", "ert", "ert-sha256", "run-id", "base", "user", "exe", "result", "deadlines-json"):
        parser.add_argument("--" + name, required=True)
    for name in ("cdb", "com-cleanup-dll", "helper", "identity"):
        parser.add_argument("--" + name)
    parser.add_argument("--parameters-json", default="{}", help="[platform.parameters] of the project")
    parser.add_argument("--commands-json", default="[]", help="commands of the declared tests, in order")
    parser.add_argument("--screenshots", action="store_true")
    args, _ = parser.parse_known_args(argv)
    out = Path(args.run_dir).resolve()
    result_path = Path(args.result)
    deadlines = json.loads(args.deadlines_json)
    parameters = json.loads(args.parameters_json)
    report = {"run_id": args.run_id, "ert_sha256": args.ert_sha256, "platform_checked": False,
              "status": "blocked", "reason": None, "cancelled": False, "timeout_phase": None,
              "load": None, "operations": [], "result_files": [], "screenshots": [],
              "phase_durations_s": {}, "shutdown": None,
              "platform_identity": {"platform_version": "", "deadlines_effective": deadlines}}
    drive = out / "native"
    try:
        built = Path(args.ert).resolve(strict=True)
        if sha256(built) != args.ert_sha256:
            raise ValueError("built ERT hash does not match this run")
        helper = Path(args.helper or args.com_cleanup_dll).resolve(strict=True)
        exe = Path(args.exe).resolve(strict=True)
        cdb = Path(args.cdb).resolve(strict=True)
        base = Path(args.base).resolve(strict=True)
        identity_dll = Path(args.identity).resolve(strict=True)
        if sha256(identity_dll) != IDENTITY_SHA:
            raise ValueError("unqualified proxy inspector")
        commands = adapter.commands(parameters, json.loads(args.commands_json))
        # preflight requires a fresh output directory, so validate before creating it.
        adapter.preflight(base, exe, cdb, helper, drive)
        drive.mkdir(parents=True, exist_ok=False)
        manifest, shutdown_manifest, ert_target = scaffold(drive, built, args.run_id, adapter, commands, parameters)
        # The 1C process inherits the environment through CDB.
        os.environ.update(adapter.prepare(out, parameters))
        # Honour the configured section 8.5 deadlines in this process (the owner's
        # long-report launchers do the same). The general executor never hardcodes
        # the research prototype 30/145; the core enforces whatever is configured.
        operation_timeout, total_s, client_timeout = session_limits(deadlines)
        trace = base_trace(base)
        report["open"] = {"deadline_s": open_deadline(deadlines, trace),
                          "reindex_expected": bool(trace["interrupted"]), "base_trace": trace}
        shutdown_s = deadlines["shutdown_timeout_s"]
        import session77
        import shutdown77
        session77.Deadline = lambda started: shutdown77.Deadline(started, total=total_s, shutdown=shutdown_s)
        lifecycle = {"schema_version": 1, "scope": "stage-4 native full cycle", "shutdown_mode": MODE,
                     "fault": "none", "status": "blocked", "run_id": args.run_id,
                     "ert_operation_timeout_seconds": operation_timeout,
                     "open_timeout_seconds": report["open"]["deadline_s"],
                     "client_timeout_seconds": client_timeout,
                     "cancel_path": str(out / "cancel"),
                     "identity_observer_profile": "challenge-only-v2",
                     "client_log_profile": "held-streams-v2", "ert_commands": list(commands),
                     "ert_protocol_paths": manifest["protocol_paths"]}
        from session77 import run_session
        from desktop77 import PrivateDesktop
        with PrivateDesktop() as desktop, adapter.watch(drive, lifecycle, desktop.name):
            lifecycle = run_session(base, exe, cdb, helper, args.user, drive, lifecycle,
                                    desktop=desktop.name, identity_dll=identity_dll)
        lifecycle["desktop_closed"] = True
        shutdown_result = assess(drive, shutdown_manifest, lifecycle)
        operations, issues = interpret(drive, manifest, lifecycle, shutdown_result, adapter)
        report["operations"] = operations
        report["result_files"] = adapter.result_files(out, operations)
        report["load"] = {"status": operations[0]["status"] if operations else "blocked",
                          "diagnostics": operations[0]["diagnostics"] if operations else []}
        report["phase_durations_s"] = {"session": lifecycle.get("elapsed_seconds"),
                                       "shutdown": lifecycle.get("shutdown_elapsed_seconds")}
        first = drive / ("ert-" + commands[0] + "-started")
        if first.exists() and lifecycle.get("started_at"):
            import datetime
            begun = datetime.datetime.fromisoformat(lifecycle["started_at"]).timestamp()
            report["open"]["elapsed_s"] = round(first.stat().st_mtime - begun, 1)
        report["open"]["base_trace_after"] = base_trace(base)
        report["shutdown"] = {"status": shutdown_result["status"],
                              "cleanup_verified": bool(lifecycle.get("cleanup_verified")),
                              "forced_cleanup": bool(lifecycle.get("forced_cleanup")),
                              "server_exit_code": lifecycle.get("server_exit_code"),
                              "others_preserved": bool(lifecycle.get("baseline_preserved")),
                              "issues": shutdown_result["issues"]}
        report["platform_identity"]["platform_version"] = "7.70.027"
        report["cancelled"] = bool(lifecycle.get("user_cancelled"))
        native_phase = lifecycle.get("timeout_phase")
        report["timeout_phase"] = PHASES.get(native_phase, native_phase)
        report["native_timeout_phase"] = native_phase
        clean = (not issues and not lifecycle.get("error") and lifecycle.get("cleanup_verified")
                 and shutdown_result["status"] == "passed")
        report["platform_checked"] = bool(clean)
        if report["cancelled"]:
            report["status"], report["reason"] = "blocked", "cancelled"
        elif report["timeout_phase"]:
            report["status"], report["reason"] = "blocked", report["timeout_phase"] + "_timeout"
        elif not clean:
            report["status"] = "blocked"
            report["reason"] = lifecycle.get("error") or "; ".join(issues + shutdown_result["issues"]) or "native run not clean"
        elif report["load"]["status"] == "failed":
            report["status"], report["reason"] = "failed", "compilation_failed"
        else:
            report["status"] = adapter.platform_status(operations)
    except Exception as error:  # noqa: BLE001 - record any native failure as blocked
        report["reason"] = f"{type(error).__name__}: {error}"
        report["status"] = "blocked"
    atomic_json(result_path, report)
    return 0 if report["status"] == "passed" else 1 if report["status"] == "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
