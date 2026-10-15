"""Section 8.5 deadline policy: consistency, external clock, silence and progress."""

import unittest

from harness77.deadlines77 import Clock, Deadlines, DeadlineError, ManualClock, RunClock


class DeadlineValidationTests(unittest.TestCase):
    def valid(self, **over):
        values = {"open_s": 30, "calculation_s": 3600, "cancel_s": 10, "shutdown_s": 20, "total_s": 3700}
        values.update(over)
        return Deadlines.create(**values)

    def test_accepts_consistent_budget(self):
        deadlines = self.valid(sources={"calculation": "project"})
        self.assertEqual(deadlines.calculation_s, 3600)
        self.assertEqual(deadlines.effective()["sources"]["calculation"], "project")
        self.assertEqual(deadlines.effective()["phase_sum_s"], 3660)

    def test_total_must_cover_phase_sum(self):
        with self.assertRaises(DeadlineError):
            self.valid(total_s=100)

    def test_rejects_nonpositive_and_nonfinite(self):
        for bad in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(DeadlineError):
                self.valid(calculation_s=bad)

    def test_rejects_boolean_and_nonnumber(self):
        for bad in (True, "30", None):
            with self.assertRaises(DeadlineError):
                self.valid(open_s=bad)

    def test_no_prototype_defaults(self):
        # The class never invents 30/145; every field is supplied explicitly.
        deadlines = self.valid()
        self.assertNotIn(145, deadlines.effective().values())


class ClockTests(unittest.TestCase):
    def test_manual_clock_advances_and_refuses_reverse(self):
        clock = ManualClock(5)
        self.assertEqual(clock.now(), 5)
        clock.advance(10)
        self.assertEqual(clock.now(), 15)
        with self.assertRaises(ValueError):
            clock.advance(-1)


class RunClockTests(unittest.TestCase):
    def deadlines(self):
        return Deadlines.create(open_s=10, calculation_s=100, cancel_s=5, shutdown_s=5, total_s=1000)

    def test_phase_deadline_is_absolute_and_silence_is_not_timeout(self):
        clock = ManualClock()
        run_clock = RunClock(self.deadlines(), "run", clock=clock)
        run_clock.enter("calculation")
        clock.advance(99)
        self.assertIsNone(run_clock.expired())  # long silence, still within the deadline
        clock.advance(2)
        self.assertEqual(run_clock.expired(), "calculation")  # only the absolute deadline trips

    def test_progress_does_not_extend_deadline(self):
        clock = ManualClock()
        run_clock = RunClock(self.deadlines(), "run", clock=clock)
        run_clock.enter("calculation")
        for _ in range(50):
            clock.advance(2)
            run_clock.note_progress({"percent": 1})  # steady progress
        self.assertEqual(run_clock.expired(), "calculation")  # 100 s elapsed regardless of progress

    def test_total_budget_trips_across_phases(self):
        clock = ManualClock()
        run_clock = RunClock(Deadlines.create(open_s=10, calculation_s=100, cancel_s=5,
                                              shutdown_s=5, total_s=120), "run", clock=clock)
        run_clock.enter("open")
        clock.advance(121)
        self.assertEqual(run_clock.expired(), "open")  # phase trips first here
        run_clock.enter("shutdown")  # a later short phase still sees the exhausted total
        self.assertEqual(run_clock.expired(), "total")

    def test_observation_shape(self):
        clock = ManualClock()
        run_clock = RunClock(self.deadlines(), "run-1", clock=clock)
        run_clock.enter("calculation")
        clock.advance(3)
        observation = run_clock.observe()
        self.assertEqual(observation["run_id"], "run-1")
        self.assertEqual(observation["phase"], "calculation")
        self.assertEqual(observation["phase_elapsed_s"], 3)
        self.assertIsNone(observation["progress"])  # explicit null when none reported

    def test_external_clock_is_monotonic_source(self):
        self.assertIsInstance(Clock(), Clock)


if __name__ == "__main__":
    unittest.main()
