"""Platform backends behind one interface; the native run is a separate module.

``drive_phase`` is the one place the section 8.5 loop lives: it enters a phase,
pulls bounded units of work, and after each one checks user cancellation and the
absolute deadline. Silence never expires a phase and progress never moves a
deadline, because both are decided by ``RunClock`` alone. The simulation and
native backends share this loop, so timeout and cancel behave identically.

Only the native backend sets ``platform_checked=true``. The simulation backend
drives the same control flow against a scripted scenario for tests and for
environments without 1C; the import backend records a saved protocol as provided
evidence. Neither is an automatic platform run, and neither claims one.
"""

from __future__ import annotations

import json
from pathlib import Path

from .deadlines77 import Clock
from .report77 import file_evidence


def drive_phase(run_clock, phase, cancel, steps_factory, observe):
    """Run one phase to completion, cancellation or its absolute deadline.

    Returns ``"completed"``, ``"cancelled"`` or ``"timeout:<phase|total>"``.
    ``steps_factory(timer)`` yields bounded work units (progress samples, which
    may be ``None`` when the processing reports none); each unit advances the
    external clock as a side effect (sleep+poll natively, explicit advance in
    simulation). Cancellation and expiry are checked between units only.
    """
    timer = run_clock.enter(phase)
    observe(run_clock.observe())
    iterator = iter(steps_factory(timer))
    while True:
        if cancel.is_set():
            return "cancelled"
        tripped = run_clock.expired()
        if tripped:
            return "timeout:" + tripped
        try:
            progress = next(iterator)
        except StopIteration:
            return "completed"
        run_clock.note_progress(progress)
        observe(run_clock.observe())


class _Backend:
    platform_checked = False
    name = "base"

    def __init__(self, *, ert_path, ert_sha256, run_id, run_dir, base_name=""):
        self.ert_path = Path(ert_path)
        self.ert_sha256 = ert_sha256
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.base_name = base_name

    def _skeleton(self):
        return {"backend": self.name, "platform_checked": self.platform_checked,
                "status": "blocked", "scope": "", "run_id": self.run_id,
                "ert_sha256": self.ert_sha256, "cancelled": False, "timeout_phase": None,
                "reason": None, "load": None, "operations": [], "result_files": [],
                "screenshots": [], "phase_durations_s": {}, "shutdown": None}


class SimulationBackend(_Backend):
    """Deterministic, scripted platform behaviour; never a real platform check."""

    name = "simulation"

    def __init__(self, scenario, *, clock, captures=(), **kwargs):
        super().__init__(**kwargs)
        self.scenario = scenario
        self.clock = clock
        self.captures = list(captures)

    def _steps(self, spec, timer, cancel):
        duration = float(spec.get("duration_s", 0.0))
        samples = int(spec.get("samples", 4)) if duration > 0 else 0
        progress = spec.get("progress")
        cancel_at = spec.get("cancel_at_s")

        def generate():
            step = duration / samples if samples else 0.0
            for index in range(samples):
                self.clock.advance(step)
                if cancel_at is not None and self.clock.now() - timer.started_at >= cancel_at:
                    cancel.set()
                yield progress[index] if isinstance(progress, list) and index < len(progress) else None
        return generate()

    def _durations(self, run_clock, phase, result):
        timer = run_clock._phase
        if timer is not None:
            result["phase_durations_s"][phase] = round(run_clock.clock.now() - timer.started_at, 3)

    def run(self, run_clock, cancel, observe):
        result = self._skeleton()
        result["scope"] = "scripted simulation of a platform run; not an automatic 1C check"
        result["platform_identity"] = dict(self.scenario.get("platform_identity", {}),
                                            base=self.base_name, backend=self.name)
        # The scenario may claim a stale/foreign run so run77's linkage check can reject it.
        result["run_id"] = self.scenario.get("observed_run_id", self.run_id)
        result["ert_sha256"] = self.scenario.get("observed_ert_sha256", self.ert_sha256)

        open_spec = self.scenario.get("open", {})
        outcome = drive_phase(run_clock, "open", cancel, lambda t: self._steps(open_spec, t, cancel), observe)
        self._durations(run_clock, "open", result)
        if outcome != "completed":
            return self._stop(result, run_clock, cancel, observe, outcome)
        if open_spec.get("status") == "missing-base":
            result["reason"] = "database_path_missing"
            self._screenshots(result, "open")
            self._shutdown(result, run_clock, cancel, observe)
            result["status"] = "blocked"
            return result

        calc = self.scenario.get("calculation", {})
        load = calc.get("load", {"status": "passed", "diagnostics": []})
        result["load"] = {"status": load.get("status", "passed"),
                          "diagnostics": load.get("diagnostics", [])}
        outcome = drive_phase(run_clock, "calculation", cancel,
                              lambda t: self._steps(calc, t, cancel), observe)
        self._durations(run_clock, "calculation", result)
        if outcome != "completed":
            return self._stop(result, run_clock, cancel, observe, outcome)
        if result["load"]["status"] != "passed":
            # A compilation defect ends the run before any operation executes.
            result["reason"] = "compilation_failed"
            self._screenshots(result, "calculation")
            self._shutdown(result, run_clock, cancel, observe)
            result["status"] = "failed"
            return result
        result["operations"] = [dict(op) for op in calc.get("operations", [])]
        self._persist_results(calc, result)
        self._captures(result)
        if result["reason"] == "artifact_write_error":
            self._screenshots(result, "calculation")
            self._shutdown(result, run_clock, cancel, observe)
            result["status"] = "blocked"
            return result
        self._shutdown(result, run_clock, cancel, observe)
        if result["shutdown"]["status"] != "ok":
            result["reason"] = "shutdown_error"
            result["status"] = "blocked"
        else:
            result["status"] = "passed"
        return result

    def _persist_results(self, calc, result):
        for spec in calc.get("result_files", []):
            name = spec["name"]
            target = self.run_dir / "results" / name
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if spec.get("write_error"):
                    raise OSError("смоделированная ошибка записи результата")
                payload = (spec.get("fill", "x") * spec["size_bytes"])[:spec["size_bytes"]]
                target.write_bytes(payload.encode("latin-1"))
                complete = spec.get("complete", True)
            except OSError as error:
                result["reason"] = "artifact_write_error"
                result["result_files"].append({"name": name, "exists": False,
                                                "complete": False, "error": str(error)})
                return
            evidence = file_evidence(target, root=self.run_dir, complete=complete,
                                     expected_sha256=spec.get("expected_sha256"))
            result["result_files"].append(evidence)

    def _captures(self, result):
        """Scripted form captures (task 010): each requested state and window the scenario draws."""
        if not self.captures:
            return
        from .visual77 import Image, encode_png
        drawn = {(c.get("state"), c.get("window")): c for c in self.scenario.get("captures", [])}
        result["captures"] = []
        for request in self.captures:
            spec = drawn.get((request["state"], request["window"]))
            if spec is None:
                continue  # not captured: the visual stage blocks the check
            record = {key: spec[key] for key in ("environment", "caret", "error") if key in spec}
            record.update(state=request["state"], window=request["window"], stable=spec.get("stable", True),
                          attempts=spec.get("attempts", 2))
            if "image" in spec:
                width, height = spec["image"]["width"], spec["image"]["height"]
                pixels = bytearray(bytes(spec["image"].get("fill", [240, 240, 240])) * (width * height))
                for x, y, w, h, colour in spec["image"].get("rects", []):
                    for row in range(y, y + h):
                        pixels[(row * width + x) * 3:(row * width + x + w) * 3] = bytes(colour) * w
                target = self.run_dir / "form" / f"capture-{request['state']}-{request['window']}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(encode_png(Image(width, height, bytes(pixels))))
                record["file"] = file_evidence(target, root=self.run_dir, complete=True)
                record.update(width=width, height=height)
            result["captures"].append(record)

    def _stop(self, result, run_clock, cancel, observe, outcome):
        if outcome == "cancelled":
            result["cancelled"] = True
            result["reason"] = "cancelled"
            # Bounded wait for the blocking call to return before shutting down.
            drive_phase(run_clock, "cancel", cancel, lambda t: iter(()), observe)
            self._durations(run_clock, "cancel", result)
        elif outcome.startswith("timeout:"):
            phase = outcome.split(":", 1)[1]
            result["timeout_phase"] = phase
            result["reason"] = "calculation_timeout" if phase == "calculation" else phase + "_timeout"
        # Any produced result so far is partial and must be marked incomplete.
        for spec in self.scenario.get("calculation", {}).get("result_files", []):
            result["result_files"].append({"name": spec["name"], "exists": False,
                                            "complete": False, "note": "no complete result on abort"})
        self._screenshots(result, result["timeout_phase"] or "cancel")
        self._shutdown(result, run_clock, cancel, observe)
        result["status"] = "blocked"
        return result

    def _screenshots(self, result, phase):
        spec = self.scenario.get("screenshots")
        if not spec:
            return
        from . import screenshots77
        fill = bytes((spec.get("fill", 137),)) * int(spec.get("size_bytes", 64))

        def capture(hwnd, path):
            Path(path).write_bytes(fill)
        result["screenshots"] = screenshots77.collect(
            spec.get("windows", []), own_pid=spec.get("own_pid", 4321),
            desktop=spec.get("desktop", "harness77_sim"), run_id=self.run_id, phase=phase,
            out_dir=self.run_dir / "screenshots", capture=capture)

    def _shutdown(self, result, run_clock, cancel, observe):
        spec = self.scenario.get("shutdown", {"duration_s": 0.0, "status": "ok"})
        # Cancellation during shutdown is ignored: the session must close cleanly.
        import threading
        drive_phase(run_clock, "shutdown", threading.Event(),
                    lambda t: self._steps(spec, t, threading.Event()), observe)
        self._durations(run_clock, "shutdown", result)
        result["shutdown"] = {"status": spec.get("status", "ok"),
                              "forced_cleanup": bool(spec.get("forced_cleanup", False)),
                              "server_exit_code": spec.get("server_exit_code", 0),
                              "cleanup_verified": spec.get("cleanup_verified", True),
                              "others_preserved": spec.get("others_preserved", True)}


class ImportBackend(_Backend):
    """Record a saved Configurator protocol as provided evidence, not a run."""

    name = "import"

    def __init__(self, protocol_path, *, clock, **kwargs):
        super().__init__(**kwargs)
        self.protocol_path = Path(protocol_path)
        self.clock = clock

    def run(self, run_clock, cancel, observe):
        from .compiler_protocol77 import parse_protocol  # lazy; keeps import optional
        result = self._skeleton()
        result["scope"] = "imported Configurator protocol; provided evidence, not an automatic platform run"
        result["platform_identity"] = {"backend": self.name, "base": self.base_name}
        run_clock.enter("open")
        observe(run_clock.observe())
        try:
            parsed = parse_protocol(self.protocol_path.read_bytes())
            result["load"] = {"status": parsed.get("status", "blocked"),
                              "diagnostics": parsed.get("diagnostics", []),
                              "protocol": file_evidence(self.protocol_path, root=self.run_dir, complete=True)}
        except (OSError, ValueError, TypeError) as error:
            result["reason"] = f"import_error: {type(error).__name__}: {error}"
        # Imported evidence never satisfies the required automatic platform check.
        result["reason"] = result["reason"] or "automatic_platform_check_unavailable"
        result["status"] = "blocked"
        result["phase_durations_s"]["open"] = round(run_clock.observe()["phase_elapsed_s"] or 0.0, 3)
        return result


def load_backend(stand, *, ert_path, ert_sha256, run_id, run_dir, clock=None, parameters=None, commands=(),
                 captures=(), base_name=None, configuration_sha256=None):
    """base_name: the stand base's name when 1C opens a copy of it; configuration_sha256: the
    built 1Cv7.MD of that copy (task 021), which only the native launcher must be told."""
    common = {"ert_path": ert_path, "ert_sha256": ert_sha256, "run_id": run_id,
              "run_dir": run_dir, "base_name": base_name or Path(stand.base).name}
    if stand.backend == "simulation":
        from .deadlines77 import ManualClock
        scenario = json.loads(Path(stand.scenario).read_text(encoding="utf-8"))
        # Simulation drives time explicitly, so scripted long runs are instant.
        return SimulationBackend(scenario, clock=ManualClock(), captures=captures, **common)
    if stand.backend == "import":
        return ImportBackend(stand.import_protocol, clock=clock or Clock(), **common)
    if stand.backend == "native":
        from . import native77
        return native77.NativeBackend(stand, clock=clock or Clock(), parameters=parameters,
                                      commands=commands, captures=captures,
                                      configuration_sha256=configuration_sha256, **common)
    raise ValueError(f"unknown backend: {stand.backend}")
