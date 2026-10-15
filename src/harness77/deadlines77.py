"""Section 8.5 deadline policy for long calculations and large reports.

Separate, finite deadlines for opening, calculation, cancellation and shutdown,
plus a total budget that must cover the allowed phase time. Time is measured by
an external monotonic clock; a deadline is absolute from the moment a phase
starts and is never renewed by progress messages or by silence. Silence alone is
never a timeout: only reaching the absolute deadline is. The research prototype
limits (30 s per operation, 145 s per session) are deliberately not defaults.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

# Phases that consume the total budget, in the order a run performs them.
PHASES = ("open", "calculation", "cancel", "shutdown")


class DeadlineError(ValueError):
    """Rejected timing configuration; raised before any launch."""


def _finite_positive(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DeadlineError(f"{name}: срок должен быть числом секунд")
    if not math.isfinite(value) or value <= 0:
        raise DeadlineError(f"{name}: срок должен быть конечным и положительным")
    return float(value)


@dataclass(frozen=True)
class Deadlines:
    """Validated per-phase seconds with the source of each effective value."""

    open_s: float
    calculation_s: float
    cancel_s: float
    shutdown_s: float
    total_s: float
    sources: dict

    @classmethod
    def create(cls, *, open_s, calculation_s, cancel_s, shutdown_s, total_s, sources=None):
        values = {"open": open_s, "calculation": calculation_s, "cancel": cancel_s,
                  "shutdown": shutdown_s, "total": total_s}
        checked = {name: _finite_positive(name, value) for name, value in values.items()}
        allowed = checked["open"] + checked["calculation"] + checked["cancel"] + checked["shutdown"]
        if checked["total"] < allowed:
            raise DeadlineError(
                "total: общий срок %.3f с меньше суммы разрешённого времени фаз %.3f с "
                "(open+calculation+cancel+shutdown)" % (checked["total"], allowed))
        sources = dict(sources or {})
        return cls(checked["open"], checked["calculation"], checked["cancel"],
                   checked["shutdown"], checked["total"],
                   {name: sources.get(name, "default") for name in values})

    def limit(self, phase):
        if phase not in PHASES:
            raise KeyError(phase)
        return getattr(self, phase + "_s")

    def effective(self):
        return {"open_timeout_s": self.open_s, "calculation_timeout_s": self.calculation_s,
                "cancel_timeout_s": self.cancel_s, "shutdown_timeout_s": self.shutdown_s,
                "total_timeout_s": self.total_s, "phase_sum_s": round(
                    self.open_s + self.calculation_s + self.cancel_s + self.shutdown_s, 6),
                "sources": dict(self.sources),
                "clock": "external monotonic; absolute per-phase deadlines; progress does not extend"}


class Clock:
    """External monotonic clock; injectable for tests. Never the wall clock."""

    def __init__(self, source=time.monotonic):
        self._source = source

    def now(self):
        return self._source()


class ManualClock(Clock):
    """Deterministic clock advanced explicitly, so scripted long runs are instant.

    The simulation backend advances this between steps instead of sleeping, and
    tests use it to reach a deadline or inject cancellation at an exact moment.
    """

    def __init__(self, start=0.0):
        super().__init__(self._read)
        self._value = float(start)

    def _read(self):
        return self._value

    def advance(self, seconds):
        if seconds < 0:
            raise ValueError("время идёт только вперёд")
        self._value += float(seconds)
        return self._value


class PhaseTimer:
    """One absolute deadline from a phase start; silence does not expire it."""

    def __init__(self, phase, started_at, limit_s):
        self.phase = phase
        self.started_at = started_at
        self.limit_s = limit_s
        self.deadline_at = started_at + limit_s

    def elapsed(self, now):
        return now - self.started_at

    def remaining(self, now):
        return self.deadline_at - now

    def expired(self, now):
        # Strictly reaching the absolute deadline; a lull with time left is not a timeout.
        return now >= self.deadline_at


class RunClock:
    """Track the total budget and the currently active phase for observation.

    The total deadline is absolute from run start. Each phase gets its own
    absolute deadline when entered. ``expired`` reports which bound tripped, so
    the caller distinguishes a phase timeout from exhausting the total budget.
    """

    def __init__(self, deadlines: Deadlines, run_id, clock: Clock | None = None):
        self.deadlines = deadlines
        self.run_id = run_id
        self.clock = clock or Clock()
        self.started_at = self.clock.now()
        self.total_at = self.started_at + deadlines.total_s
        self._phase: PhaseTimer | None = None
        self.progress = None

    def enter(self, phase):
        self._phase = PhaseTimer(phase, self.clock.now(), self.deadlines.limit(phase))
        self.progress = None
        return self._phase

    def note_progress(self, progress):
        # Progress is recorded for observation only; it never moves a deadline.
        self.progress = progress

    def expired(self):
        now = self.clock.now()
        if self._phase is not None and self._phase.expired(now):
            return self._phase.phase
        if now >= self.total_at:
            return "total"
        return None

    def observe(self):
        now = self.clock.now()
        phase = self._phase
        return {"run_id": self.run_id,
                "phase": phase.phase if phase else None,
                "elapsed_s": round(now - self.started_at, 3),
                "phase_elapsed_s": round(phase.elapsed(now), 3) if phase else None,
                "phase_deadline_s": round(phase.limit_s, 3) if phase else None,
                "phase_remaining_s": round(phase.remaining(now), 3) if phase else None,
                "total_remaining_s": round(self.total_at - now, 3),
                "progress": self.progress}
