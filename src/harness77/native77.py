"""Native 1C 7.7 backend: drive the real stand through a configured launcher.

Stage 4 does not reimplement the accepted research controller. The native
backend runs a stand-provided *launcher* (the proven ``research/platform77``
controller, or a project launcher built on it) that opens this run's ERT on the
pinned base, performs the declared commands with the section 8.5 deadlines from
:mod:`harness77.deadlines77`, and writes ``platform-result.json`` in the run
directory. This backend validates the stand, forwards cancellation with a
bounded wait, enforces a wall-clock backstop, and never infers a clean shutdown
from the launcher process merely exiting.

``platform_checked`` is true only when the launcher reports a real native run.
Off-stand (wrong OS, missing binaries, no launcher) the backend returns a
blocked result with a precise reason; it never fabricates platform success.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .report77 import file_evidence, sha256_file

# Only these launcher-reported reasons are treated as infrastructure (blocked).
INFRA_REASONS = {"database_path_missing", "artifact_write_error", "shutdown_error",
                 "calculation_timeout", "open_timeout", "cancel_timeout", "shutdown_timeout",
                 "cancelled", "native_preflight", "native_launcher_error"}


class NativeBackend:
    platform_checked = True  # Only asserted after the launcher confirms a native run.
    name = "native"

    def __init__(self, stand, *, clock, ert_path, ert_sha256, run_id, run_dir, base_name="",
                 parameters=None, commands=()):
        self.stand = stand
        self.parameters = dict(parameters or {})
        self.commands = list(commands)
        self.clock = clock
        self.ert_path = Path(ert_path)
        self.ert_sha256 = ert_sha256
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.base_name = base_name

    def _blocked(self, reason, **extra):
        return {"backend": self.name, "platform_checked": False, "status": "blocked",
                "scope": "native stand unavailable; no automatic platform check performed",
                "run_id": self.run_id, "ert_sha256": self.ert_sha256, "cancelled": False,
                "timeout_phase": None, "reason": reason, "load": None, "operations": [],
                "result_files": [], "phase_durations_s": {}, "shutdown": None,
                "platform_identity": {"backend": self.name, "base": self.base_name}, **extra}

    def _preflight(self):
        if os.name != "nt":
            return "native_preflight: 1C 7.7 requires Windows; this is " + os.name
        launcher = self.stand.extra.get("launcher")
        if not launcher:
            return "native_preflight: stand.launcher is not configured"
        required = {"exe": self.stand.exe, "base": self.stand.base}
        for role, path in required.items():
            if path is None or not Path(path).exists():
                return f"native_preflight: missing {role} on the stand"
        for name, expected in self.stand.pinned.items():
            candidate = self.stand.base / name if name not in ("exe",) else self.stand.exe
            try:
                if sha256_file(candidate) != expected:
                    return f"native_preflight: pinned hash mismatch for {name}"
            except OSError:
                return f"native_preflight: pinned file absent: {name}"
        return None

    def run(self, run_clock, cancel, observe):
        run_clock.enter("open")
        observe(run_clock.observe())
        reason = self._preflight()
        if reason is not None:
            return self._blocked(reason)
        launcher = Path(self.stand.extra["launcher"])
        result_path = self.run_dir / "platform-result.json"
        deadlines = run_clock.deadlines
        command = [sys.executable, "-B", str(launcher),
                   "--run-dir", str(self.run_dir), "--ert", str(self.ert_path),
                   "--ert-sha256", self.ert_sha256, "--run-id", self.run_id,
                   "--base", str(self.stand.base), "--user", self.stand.user,
                   "--exe", str(self.stand.exe), "--result", str(result_path),
                   "--deadlines-json", json.dumps(deadlines.effective()),
                   "--parameters-json", json.dumps(self.parameters, ensure_ascii=False),
                   "--commands-json", json.dumps(self.commands, ensure_ascii=False)]
        for role in ("cdb", "helper", "identity"):
            path = getattr(self.stand, role)
            if path is not None:
                command += ["--" + role, str(path)]
        if self.stand.screenshots:
            command.append("--screenshots")
        # The launcher owns the phase deadlines; this is only a hard wall-clock backstop.
        backstop = deadlines.total_s + max(30.0, deadlines.shutdown_s)
        # After a cancellation the launcher gets the cancel and shutdown phases to return.
        after_cancel = deadlines.cancel_s + deadlines.shutdown_s + 10.0
        started = time.monotonic()
        # Console Ctrl+C reaches only this process; the launcher learns of it by file.
        group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       creationflags=group)
        except OSError as error:
            return self._blocked(f"native_launcher_error: {type(error).__name__}: {error}")
        cancelled = forced = False
        cancelled_at = None
        while process.poll() is None:
            observe(run_clock.observe())
            if cancel.is_set() and not cancelled:
                cancelled, cancelled_at = True, time.monotonic()
                # Ask the launcher to cancel; it must return and shut down cleanly.
                (self.run_dir / "cancel").write_text(self.run_id, encoding="ascii")
            now = time.monotonic()
            if now - started > backstop or (cancelled and now - cancelled_at > after_cancel):
                process.kill()
                forced = True
                break
            time.sleep(0.1)
        try:
            output = process.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            process.kill()
            output = process.communicate()[0]
            forced = True
        exit_code = process.returncode
        (self.run_dir / "native-launcher-stdout.txt").write_bytes(output or b"")
        if not result_path.exists():
            return self._blocked(
                f"native_launcher_error: no platform-result.json (exit={exit_code}, forced={forced})",
                launcher_exit_code=exit_code, forced_cleanup=forced)
        try:
            produced = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return self._blocked(f"native_launcher_error: unreadable result: {error}")
        return self._map(produced, exit_code, forced, cancelled)

    def _map(self, produced, exit_code, forced, cancelled):
        result = {"backend": self.name, "scope": "native 1C 7.7 run via the stand launcher",
                  "run_id": produced.get("run_id"), "ert_sha256": produced.get("ert_sha256"),
                  "platform_checked": bool(produced.get("platform_checked", False)) and not forced,
                  "status": produced.get("status", "blocked"),
                  "reason": produced.get("reason"), "cancelled": bool(produced.get("cancelled", cancelled)),
                  "timeout_phase": produced.get("timeout_phase"),
                  "load": produced.get("load"), "operations": produced.get("operations", []),
                  "phase_durations_s": produced.get("phase_durations_s", {}),
                  "shutdown": produced.get("shutdown"),
                  "platform_identity": dict(produced.get("platform_identity", {}),
                                            backend=self.name, base=self.base_name),
                  "launcher_exit_code": exit_code, "forced_cleanup": forced}
        self.platform_checked = result["platform_checked"]
        result["screenshots"] = produced.get("screenshots", [])
        # Re-evidence result files from disk; never trust a reported hash alone.
        result["result_files"] = [
            dict(file_evidence(self.run_dir / spec["path"], root=self.run_dir,
                               complete=spec.get("complete"), expected_sha256=spec.get("sha256")),
                 **{key: spec[key] for key in ("operation", "package", "package_status") if key in spec})
            if "path" in spec else spec
            for spec in produced.get("result_files", [])]
        if forced and result["status"] == "passed":
            result["status"], result["reason"] = "blocked", "launcher terminated by backstop; shutdown unverified"
        # A clean shutdown is never inferred from the process exiting.
        shutdown = result.get("shutdown") or {}
        if result["status"] == "passed" and shutdown.get("cleanup_verified") is not True:
            result["status"], result["reason"] = "blocked", "native shutdown cleanup not verified"
        return result
