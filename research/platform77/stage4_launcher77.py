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
result to this run. The short control cycle uses the accepted research core
limits (operation 30 s, session 145 s); a tens-of-minutes application report
needs a launcher that raises those explicitly, which stays an owner step.
"""

import argparse
import json
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


def scaffold(out, built_ert, run_id):
    """Reconstruct the controller/client/shutdown scaffolding for an external ERT."""
    folder = out / "Тестовые обработки"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "Обработка проверки.ert"
    shutil.copyfile(built_ert, target)
    controller = Path(probe.__file__).with_name("ert_controller77.1s").read_text(encoding="utf-8")
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
                       "COMMANDS": ", ".join(probe.vb_literal(c) for c in COMMANDS),
                       "SHUTDOWN": shutdown}.items():
        client = client.replace("__" + key + "__", value)
    client = client.replace("__PROTOCOL_ROOT__", probe.vb_literal(str(protocol_root)))
    (out / "client.vbs").write_text(client, encoding="utf-16")
    shutdown_manifest["sources"]["client.vbs"] = sha256(out / "client.vbs")
    manifest = {"schema_version": 1, "run_id": run_id, "identity": IDENTITY, "ert_path": str(target),
                "commands": list(COMMANDS),
                "protocol_paths": {c: PROTOCOL_DIRECTORY + "/" + c + ".txt" for c in COMMANDS}}
    atomic_json(out / "ert-manifest.json", manifest)
    atomic_json(out / "shutdown-manifest.json", shutdown_manifest)
    return manifest, shutdown_manifest, target


def interpret(out, manifest, lifecycle, shutdown_result):
    """Validate the external-ERT response with the constant marker; own judging."""
    import re
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
        loaded = ("loaded:" + IDENTITY) in lines
        completed = ("completed:" + IDENTITY) in lines
        if not begin_ok or not marker_ok:
            issues.append("protocol/selected marker mismatch: " + command)
        visible = "unexpected-visible-form" in actual
        open_error = "open-error:" in actual
        if loaded and completed and not visible and not open_error:
            # The module ran: passed unless it reported a runtime error.
            runtime_error = "runtime-error:" in actual
            row["status"] = "failed" if runtime_error else "passed"
            row["value"] = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("value:")), None)
        elif row["diagnostics"]:
            # Not loaded, but the compiler reported errors: a checked-code defect.
            row["status"] = "failed"
        else:
            row["status"] = "blocked"
            issues.append("no cooperation markers and no diagnostic: " + command)
        operations.append(row)
    return operations, issues


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    for name in ("run-dir", "ert", "ert-sha256", "run-id", "base", "user", "exe", "result", "deadlines-json"):
        parser.add_argument("--" + name, required=True)
    for name in ("cdb", "com-cleanup-dll", "helper", "identity"):
        parser.add_argument("--" + name)
    parser.add_argument("--screenshots", action="store_true")
    args, _ = parser.parse_known_args(argv)
    out = Path(args.run_dir).resolve()
    result_path = Path(args.result)
    deadlines = json.loads(args.deadlines_json)
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
        # preflight requires a fresh output directory, so validate before creating it.
        preflight(base, exe, cdb, helper, drive)
        drive.mkdir(parents=True, exist_ok=False)
        manifest, shutdown_manifest, ert_target = scaffold(drive, built, args.run_id)
        # Honour the configured section 8.5 deadlines in this process (the owner's
        # long-report launchers do the same). The general executor never hardcodes
        # the research prototype 30/145; the core enforces whatever is configured.
        operation_timeout = int(deadlines["open_timeout_s"] + deadlines["calculation_timeout_s"])
        import session77
        import shutdown77
        total_s, shutdown_s = deadlines["total_timeout_s"], deadlines["shutdown_timeout_s"]
        session77.Deadline = lambda started: shutdown77.Deadline(started, total=total_s, shutdown=shutdown_s)
        lifecycle = {"schema_version": 1, "scope": "stage-4 native full cycle", "shutdown_mode": MODE,
                     "fault": "none", "status": "blocked", "run_id": args.run_id,
                     "ert_operation_timeout_seconds": operation_timeout,
                     "identity_observer_profile": "challenge-only-v2",
                     "client_log_profile": "held-streams-v2", "ert_commands": list(COMMANDS),
                     "ert_protocol_paths": manifest["protocol_paths"]}
        from session77 import run_session
        from desktop77 import PrivateDesktop
        with PrivateDesktop() as desktop:
            lifecycle = run_session(base, exe, cdb, helper, args.user, drive, lifecycle,
                                    desktop=desktop.name, identity_dll=identity_dll)
        lifecycle["desktop_closed"] = True
        shutdown_result = assess(drive, shutdown_manifest, lifecycle)
        operations, issues = interpret(drive, manifest, lifecycle, shutdown_result)
        report["operations"] = operations
        report["load"] = {"status": operations[0]["status"] if operations else "blocked",
                          "diagnostics": operations[0]["diagnostics"] if operations else []}
        report["phase_durations_s"] = {"session": lifecycle.get("elapsed_seconds"),
                                       "shutdown": lifecycle.get("shutdown_elapsed_seconds")}
        report["shutdown"] = {"status": shutdown_result["status"],
                              "cleanup_verified": bool(lifecycle.get("cleanup_verified")),
                              "forced_cleanup": bool(lifecycle.get("forced_cleanup")),
                              "server_exit_code": lifecycle.get("server_exit_code"),
                              "others_preserved": bool(lifecycle.get("baseline_preserved")),
                              "issues": shutdown_result["issues"]}
        report["platform_identity"]["platform_version"] = "7.70.027"
        report["cancelled"] = bool(lifecycle.get("cancellation_requested"))
        report["timeout_phase"] = lifecycle.get("timeout_phase")
        clean = (not issues and not lifecycle.get("error") and lifecycle.get("cleanup_verified")
                 and shutdown_result["status"] == "passed")
        report["platform_checked"] = bool(clean)
        if lifecycle.get("timeout_phase"):
            report["status"], report["reason"] = "blocked", lifecycle["timeout_phase"] + "_timeout"
        elif not clean:
            report["status"] = "blocked"
            report["reason"] = lifecycle.get("error") or "; ".join(issues + shutdown_result["issues"]) or "native run not clean"
        elif report["load"]["status"] == "failed":
            report["status"], report["reason"] = "failed", "compilation_failed"
        else:
            report["status"] = "failed" if any(o["status"] == "failed" for o in operations) else "passed"
    except Exception as error:  # noqa: BLE001 - record any native failure as blocked
        report["reason"] = f"{type(error).__name__}: {error}"
        report["status"] = "blocked"
    atomic_json(result_path, report)
    return 0 if report["status"] == "passed" else 1 if report["status"] == "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
