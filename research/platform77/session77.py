"""One guarded Windows session for the pinned shutdown qualification.

The legacy research controller keeps its diagnostic switches and verdicts.
This controller has no register edits, skipped instructions or arbitrary script
input in its CLI. The shared Win32 primitives never identify ownership by PID
alone, and an unverified handle must not be passed to TerminateProcess.
"""
import ctypes as C
from ctypes import wintypes as W
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time

from shutdown77 import Deadline, atomic_json, read_events, sha256
from win32_session77 import kernel, processes, register_cleanup_helper


def run_session(base, exe, cdb, helper_dll, user, out, report, desktop=None, identity_dll=None):
    def hashes():
        return {name: sha256(path) for name, path in {
            "exe": exe, "helper": helper_dll,
            **{name: base / name for name in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll")},
        }.items()}

    report.update(started_at=dt.datetime.now().astimezone().isoformat(),
                  forced_cleanup=False, cleanup_errors=[], debugger_ready=False,
                  debugger_stops_at_first_chance_av=True, shutdown_started_observed=False,
                  diagnostic_execution_modified=False, shutdown_execution_modified=True,
                  timeout_seconds=145, shutdown_timeout_seconds=10)
    commands = out / "debugger.txt"
    observer = ""
    if identity_dll is not None:
        from proxy_debug77 import DEFAULT_OBSERVER, prepare_observer, observed_identity, observer_retired
        profile = report.setdefault("identity_observer_profile", DEFAULT_OBSERVER)
        observer, report["identity_challenge"] = prepare_observer(out, report["run_id"], profile)
        report["identity_observer_hashes_before"] = {p.name: sha256(p) for p in out.glob("identity-*.txt")}
    commands.write_text(
        'sxe -c ".echo HARNESS77_FIRST_CHANCE_AV; .exr -1; r; kv; ~*kv; lm; '
        '.dump /ma ' + (out / "first-av.dmp").as_posix() + '; q" av\n'
        + observer + '.echo HARNESS77_DEBUGGER_READY\ng\n', encoding="ascii")
    report["debugger_commands_sha256"] = sha256(commands)
    started = time.monotonic()
    deadline = Deadline(started)
    debugger = client = registration_cleanup = None
    identity_cleanup = baseline = None
    handle = None
    owned = False
    if desktop is not None:
        report["private_desktop"] = desktop
        report["desktop_switch_requested"] = False
    operation_started = {}
    recovery_until = None
    open_started = None
    shutdown_observed_at = None
    report["shutdown_observations"] = []

    def launch(command, stdout, cwd=None):
        if desktop is not None:
            from desktop77 import DesktopProcess
            return DesktopProcess(command, desktop, stdout, cwd)
        return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout,
            stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW, cwd=cwd)

    def debug_text():
        path = out / "debugger.log"
        return path.read_text(errors="replace") if path.exists() else ""

    def observe_timing(now, step):
        from win32_session77 import process_cpu_ms
        report["shutdown_observations"].append({
            "elapsed_seconds": round(now - shutdown_observed_at, 3), "last_step": step,
            "cpu_ms": {name: process_cpu_ms(h) for name, h in
                       (("server", handle), ("client", int(client._handle)), ("debugger", int(debugger._handle)))},
            "debugger_log_bytes": (out / "debugger.log").stat().st_size})

    try:
        report["hashes_before"] = hashes()
        if report.get("open_failure_probe"):
            from win32_session77 import base_titles_fingerprint
            report["base_titles_before"] = base_titles_fingerprint()
        # Recheck immediately before launching, including after CLI preflight.
        report["processes_before"] = processes()
        if identity_dll is not None:
            if not desktop:
                raise ValueError("concurrent sessions require a private desktop")
            from win32_session77 import BaselineProcesses
            from concurrent77 import IDENTITY_SHA, unexpected_processes, validate_proxy
            baseline = BaselineProcesses(report["processes_before"])
            report["baseline_identity"] = baseline.evidence()
            report["concurrent_mode"] = "verified-proxy-v1"
            report["identity_hash_before"] = sha256(identity_dll)
            if report["identity_hash_before"] != IDENTITY_SHA:
                raise ValueError("proxy inspector changed after preflight")
            identity_cleanup = register_cleanup_helper(identity_dll, report, identity=True)
        elif report["processes_before"]:
            raise RuntimeError("existing 1C process; no process was started")
        from shutdown77 import PINNED
        if report["hashes_before"] != PINNED:
            raise RuntimeError("pinned files changed since preflight")
        registration_cleanup = register_cleanup_helper(helper_dll, report)
        with (out / "cdb-stdout.txt").open("wb") as debug_stdout, (out / "client-stdout.txt").open("wb") as client_stdout:
            debugger = launch(
                [str(cdb), "-hd", "-G", "-sins", "-y", str(out), "-logo",
                 str(out / "debugger.log"), "-cf", str(commands), str(exe), "-Embedding"],
                stdout=debug_stdout, cwd=str(exe.parent))
            report["debugger_pid"] = debugger.pid
            while time.monotonic() < started + 20:
                children = [p for p in processes() if p["parent_pid"] == debugger.pid]
                if len(children) == 1:
                    candidate = children[0]
                    handle = kernel.OpenProcess(0x100000 | 0x1000 | 1, False, candidate["pid"])
                    if not handle:
                        raise C.WinError(C.get_last_error())
                    buf = C.create_unicode_buffer(32768)
                    size = W.DWORD(len(buf))
                    if not kernel.QueryFullProcessImageNameW(handle, 0, buf, C.byref(size)):
                        raise C.WinError(C.get_last_error())
                    if Path(buf.value).resolve() != exe:
                        raise RuntimeError("server executable mismatch; handle not owned")
                    times = [W.FILETIME() for _ in range(4)]
                    if not kernel.GetProcessTimes(handle, *[C.byref(t) for t in times]):
                        raise C.WinError(C.get_last_error())
                    server_time = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                    debug_times = [W.FILETIME() for _ in range(4)]
                    if not kernel.GetProcessTimes(int(debugger._handle), *[C.byref(t) for t in debug_times]):
                        raise C.WinError(C.get_last_error())
                    debug_time = (debug_times[0].dwHighDateTime << 32) | debug_times[0].dwLowDateTime
                    # Recheck ancestry after acquiring the handle, ruling out a
                    # recycled Toolhelp PID between enumeration and OpenProcess.
                    if server_time < debug_time or candidate not in processes():
                        raise RuntimeError("server identity changed; handle not owned")
                    owned = True
                    report["server"] = dict(candidate, image=buf.value,
                        creation_filetime=server_time, ownership_verified=True,
                        ownership="direct CDB child; image/time verified; retained HANDLE")
                    atomic_json(out / "owner.json", report)
                    break
                if debugger.poll() is not None:
                    raise RuntimeError("CDB exited before ownership was established")
                time.sleep(0.1)
            else:
                report["timeout_phase"] = "ownership"
                raise TimeoutError("server ownership deadline")
            while time.monotonic() < started + 30:
                startup_log = debug_text()
                if "Couldn't resolve error" in startup_log:
                    raise RuntimeError("debugger observer could not resolve COM entry point")
                if ("\nHARNESS77_DEBUGGER_READY\n" in startup_log
                        and (identity_dll is None or "\nHARNESS77_FACTORY_WATCH\n" in startup_log)):
                    report["debugger_ready"] = True
                    break
                if debugger.poll() is not None:
                    raise RuntimeError("CDB exited before ready")
                time.sleep(0.1)
            else:
                report["timeout_phase"] = "debugger-ready"
                raise TimeoutError("CDB readiness deadline")
            # Allow the OLE class factory to register before activation.
            time.sleep(1)
            current = processes()
            expected = report["processes_before"] + [{"pid": report["server"]["pid"], "parent_pid": debugger.pid}]
            if sorted(current, key=lambda p: p["pid"]) != sorted(expected, key=lambda p: p["pid"]):
                raise RuntimeError("process inventory changed before OLE activation")
            client = launch(
                [os.path.join(os.environ["WINDIR"], "SysWOW64", "cscript.exe"),
                 "//B", "//NoLogo", "//T:140", str(out / "client.vbs"),
                 str(base), user, str(out / "client.log"), str(report["server"]["pid"]),
                 "activation-only" if report.get("activation_only") else "ert"],
                stdout=client_stdout)
            report["helper_pid"] = client.pid
            while True:
                now = time.monotonic()
                if identity_dll is not None and not report.get("proxy_verified_before_initialize"):
                    challenge_path = out / "proxy-challenge-complete"
                    identity = observed_identity(debug_text(), report["run_id"], report["server"])
                    retired = (profile != "challenge-only-v2" or
                               observer_retired(debug_text(), report["run_id"], report["server"]))
                    if identity and retired and challenge_path.exists():
                        if challenge_path.read_text(encoding="ascii").strip() != report["run_id"]:
                            raise ValueError("foreign client challenge")
                        validate_proxy(identity, report["run_id"], report["server"])
                        if kernel.WaitForSingleObject(handle, 0) != 0x102:
                            raise RuntimeError("owned server exited before Initialize")
                        from desktop77 import verify_server_desktop
                        verify_server_desktop(identity["tid"], identity["pid"], desktop)
                        report["server_desktop_verified"] = True
                        report["proxy_identity"] = identity
                        if profile == "challenge-only-v2":
                            report["identity_observer_retired_before_initialize"] = True
                        report["proxy_verified_before_initialize"] = True
                        atomic_json(out / "proxy-verified.json", {"identity": identity, "server": report["server"], "desktop": desktop})
                        permit = out / "initialize-permit.tmp"
                        permit.write_text(report["run_id"], encoding="ascii")
                        permit.replace(out / "initialize-permit")
                try:
                    events = read_events(out)
                except (OSError, UnicodeError, ValueError):
                    # Appended last line may be incomplete. Final validation is strict.
                    events = []
                if any(isinstance(e, dict) and e.get("run_id") == report["run_id"]
                       and e.get("name") == "modules_released" for e in events):
                    deadline.observe_shutdown(now)
                    report["shutdown_started_observed"] = True
                    if shutdown_observed_at is None:
                        shutdown_observed_at = now
                    step = events[-1].get("name")
                    if not report["shutdown_observations"] or report["shutdown_observations"][-1]["last_step"] != step:
                        observe_timing(now, step)
                expired = deadline.expired(now)
                if expired:
                    if shutdown_observed_at is not None:
                        observe_timing(now, "deadline")
                    report["timeout_phase"] = expired
                    raise TimeoutError(expired + " deadline")
                log = debug_text()
                if "\nHARNESS77_FIRST_CHANCE_AV\n" in log:
                    raise RuntimeError("first chance AV; guarded session stopped")
                if any(message in log for message in (
                        "Numeric expression missing", "Syntax error at", "Unable to insert breakpoint", "Couldn't resolve error")):
                    raise RuntimeError("debugger command failed")
                inventory = processes()
                if identity_dll is not None:
                    if not baseline.preserved() or unexpected_processes(inventory, report["processes_before"], report["server"]):
                        raise RuntimeError("concurrent process inventory changed; stop only owned session")
                elif any(p["pid"] != report["server"]["pid"] for p in inventory):
                    raise RuntimeError("foreign 1C process appeared; stop only owned session")
                if report.get("open_failure_probe") and (out / "base-open-started").exists():
                    if (out / "base-open-started").read_text(encoding="ascii").strip() != report["run_id"]:
                        raise ValueError("foreign base-open marker")
                    if open_started is None:
                        open_started = now
                    if not (out / "base-open-finished").exists():
                        if now - open_started >= 2 and not report.get("open_windows_snapshot_saved"):
                            from win32_modal77 import OwnedModal
                            modal = OwnedModal(handle, report["server"], report["proxy_identity"]["tid"], desktop, report["run_id"])
                            windows = modal.snapshot()
                            atomic_json(out / "base-open-windows.json", {"run_id": report["run_id"], "windows": windows})
                            report["open_windows_snapshot_saved"] = True
                            target = out / ("absent-base-" + report["run_id"])
                            if target.exists():
                                raise RuntimeError("missing database path unexpectedly appeared")
                            report["registration_cancel"] = modal.cancel_registration(windows, target)
                        if (now - open_started >= 4 and report.get("registration_cancel")
                                and not report.get("open_after_cancel_snapshot_saved")):
                            from win32_modal77 import OwnedModal
                            modal = OwnedModal(handle, report["server"], report["proxy_identity"]["tid"], desktop, report["run_id"])
                            windows = modal.snapshot()
                            atomic_json(out / "base-open-after-cancel.json", {"run_id": report["run_id"], "windows": windows})
                            report["open_after_cancel_snapshot_saved"] = True
                            report["launcher_cancel"] = modal.cancel_launcher(windows,
                                out / ("absent-base-" + report["run_id"]), report["registration_cancel"])
                        if now - open_started >= 30:
                            report["timeout_phase"] = "open-base"
                            raise TimeoutError("Initialize did not return for missing database path")
                if report.get("ert_operation_timeout_seconds"):
                    for command in report["ert_commands"]:
                        marker = out / ("ert-" + command + "-started")
                        finished = out / ("ert-" + command + "-finished")
                        if marker.exists():
                            if marker.read_text(encoding="ascii").strip() != report["run_id"]:
                                raise ValueError("foreign ERT operation marker")
                            operation_started.setdefault(command, now)
                        if command not in operation_started:
                            continue
                        if finished.exists():
                            if finished.read_text(encoding="ascii").strip() != report["run_id"]:
                                raise ValueError("foreign ERT completion marker")
                            if command == "wait" and recovery_until is not None:
                                report["wait_call_returned_after_dismissal"] = True
                                recovery_until = None
                            continue
                        if recovery_until is not None:
                            if now >= recovery_until:
                                report["timeout_phase"] = "modal-recovery"
                                raise TimeoutError("modal call did not return after dismissal")
                            continue
                        if now - operation_started[command] < report["ert_operation_timeout_seconds"]:
                            continue
                        report["timeout_phase"] = "ert-operation"
                        report["timeout_operation"] = command
                        if command != "wait" or report.get("case") != "wait" or not report.get("proxy_verified_before_initialize"):
                            raise TimeoutError("native ERT operation deadline")
                        from win32_modal77 import OwnedModal
                        modal = OwnedModal(handle, report["server"], report["proxy_identity"]["tid"], desktop, report["run_id"])
                        windows = modal.snapshot()
                        snapshot = {"run_id": report["run_id"], "elapsed_seconds": round(now - operation_started[command], 3),
                            "call_finished": finished.exists(), "protocol_finished": (out / report.get("ert_protocol_paths", {}).get("wait", "wait.txt")).exists(),
                            "events": [json.loads(line) for line in (out / "ert-events.jsonl").read_text(encoding="utf-16").splitlines()],
                            "windows": windows}
                        report["wait_timeout"] = snapshot
                        atomic_json(out / "wait-timeout.json", snapshot)
                        if snapshot["call_finished"] or snapshot["protocol_finished"]:
                            raise RuntimeError("modal wait already returned before dismissal")
                        report["modal_dismissal"] = modal.dismiss(windows)
                        recovery_until = time.monotonic() + 10
                if client.poll() is not None and client.returncode != 0:
                    raise RuntimeError("client failed with code " + str(client.returncode))
                if debugger.poll() is not None and client.poll() is not None:
                    if shutdown_observed_at is not None:
                        report["shutdown_elapsed_seconds"] = round(now - shutdown_observed_at, 3)
                        observe_timing(now, "processes-exited")
                    break
                time.sleep(0.1)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        # Every cleanup step is independent; a failed step must not skip the rest.
        def attempt(label, action):
            try:
                action()
            except Exception as error:
                report["cleanup_errors"].append(f"{label}: {type(error).__name__}: {error}")

        def stop_client():
            if client is not None and client.poll() is None:
                (out / "cancel").write_text("release owned OLE session\n", encoding="ascii")
                report["cancellation_requested"] = True
                try:
                    client.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    report["forced_cleanup"] = True
                    client.kill()
                    client.wait(timeout=5)

        def stop_server():
            if handle and owned:
                waited = kernel.WaitForSingleObject(handle, 5000)
                if waited == 0x102:
                    report["forced_cleanup"] = True
                    if not kernel.TerminateProcess(handle, 0xE0000077):
                        raise C.WinError(C.get_last_error())
                    waited = kernel.WaitForSingleObject(handle, 5000)
                if waited != 0:
                    raise RuntimeError("owned server did not exit; wait=" + str(waited))
                code = W.DWORD()
                if not kernel.GetExitCodeProcess(handle, C.byref(code)):
                    raise C.WinError(C.get_last_error())
                report["server_exit_code"] = code.value

        def stop_debugger():
            if debugger is not None:
                if debugger.poll() is None:
                    try:
                        debugger.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        report["forced_cleanup"] = True
                        debugger.kill()
                        debugger.wait(timeout=5)
                if debugger.stdin:
                    debugger.stdin.close()

        attempt("client", stop_client)
        attempt("server", stop_server)
        attempt("debugger", stop_debugger)
        if handle:
            kernel.CloseHandle(handle)
        if registration_cleanup:
            attempt("registration", registration_cleanup)
        if identity_cleanup:
            attempt("identity registration", identity_cleanup)
        if baseline is not None:
            attempt("baseline identity", lambda: report.update(baseline_preserved=baseline.preserved()))
            baseline.close()
        if identity_dll is not None:
            attempt("identity hash", lambda: report.update(identity_hash_after=sha256(identity_dll)))
            attempt("observer hashes", lambda: report.update(identity_observer_hashes_after={p.name: sha256(p) for p in out.glob("identity-*.txt")}))
            if profile == "challenge-only-v2":
                attempt("observer retirement", lambda: report.update(
                    identity_observer_retired_verified=observer_retired(debug_text(), report["run_id"], report["server"])))
        report["helper_exit_code"] = client.poll() if client else None
        report["debugger_exit_code"] = debugger.poll() if debugger else None
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        attempt("hashes", lambda: report.update(hashes_after=hashes()))
        if report.get("open_failure_probe"):
            attempt("user database list", lambda: report.update(base_titles_after=base_titles_fingerprint()))
        attempt("process inventory", lambda: report.update(processes_after=processes()))
        attempt("debugger log", lambda: report.update(
            first_chance_av_observed="\nHARNESS77_FIRST_CHANCE_AV\n" in debug_text()))
        report["av_dump_saved"] = (out / "first-av.dmp").exists()
        # The durable gate is removed only after independently verifiable cleanup.
        registration = report.get("temporary_com_registration")
        expected_after = report["processes_before"] if identity_dll is not None else []
        report["cleanup_verified"] = (not report["cleanup_errors"]
            and sorted(report.get("processes_after", []), key=lambda p: p["pid"]) == sorted(expected_after, key=lambda p: p["pid"])
            and (registration is None or registration.get("removed") is True)
            and (identity_cleanup is None or report.get("identity_registration", {}).get("removed") is True)
            and (debugger is None or debugger.poll() is not None)
            and (client is None or client.poll() is not None))
    return report
