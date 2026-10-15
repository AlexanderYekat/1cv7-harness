"""Shared phase driver and the import backend."""

import tempfile
import threading
import unittest
from pathlib import Path

from harness77.backends77 import drive_phase
from harness77.deadlines77 import Deadlines, ManualClock, RunClock


def deadlines():
    return Deadlines.create(open_s=10, calculation_s=100, cancel_s=5, shutdown_s=5, total_s=1000)


class DrivePhaseTests(unittest.TestCase):
    def driver(self):
        clock = ManualClock()
        run_clock = RunClock(deadlines(), "r", clock=clock)
        observations = []
        return clock, run_clock, observations.append, observations

    def test_completed_when_steps_exhaust_within_budget(self):
        clock, run_clock, observe, records = self.driver()

        def steps(timer):
            for _ in range(3):
                clock.advance(10)
                yield None
        self.assertEqual(drive_phase(run_clock, "calculation", threading.Event(), steps, observe), "completed")
        self.assertEqual(records[0]["phase"], "calculation")

    def test_timeout_when_work_exceeds_deadline(self):
        clock, run_clock, observe, _ = self.driver()

        def steps(timer):
            while True:
                clock.advance(30)
                yield None
        self.assertEqual(drive_phase(run_clock, "calculation", threading.Event(), steps, observe),
                         "timeout:calculation")

    def test_cancel_between_steps(self):
        clock, run_clock, observe, _ = self.driver()
        cancel = threading.Event()

        def steps(timer):
            clock.advance(10)
            yield None
            cancel.set()
            clock.advance(10)
            yield None
        self.assertEqual(drive_phase(run_clock, "calculation", cancel, steps, observe), "cancelled")

    def test_silence_without_progress_is_not_a_timeout(self):
        clock, run_clock, observe, _ = self.driver()

        def steps(timer):
            clock.advance(99)  # one long quiet unit, still under the 100 s deadline
            yield None
        self.assertEqual(drive_phase(run_clock, "calculation", threading.Event(), steps, observe), "completed")


class ImportBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-imp-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_import_is_evidence_not_an_automatic_check(self):
        from harness77.backends77 import ImportBackend
        protocol = self.root / "protocol.txt"
        protocol.write_bytes(("x <<?>>\n{C:\\x.ert(2)}: Ошибка в выражении\n"
                              "При проверке модуля обнаружены синтаксические ошибки!\n").encode("cp1251"))
        clock = ManualClock()
        backend = ImportBackend(protocol, clock=clock, ert_path=self.root / "a.ert", ert_sha256="z",
                                run_id="r", run_dir=self.root, base_name="base-for-test")
        run_clock = RunClock(deadlines(), "r", clock=backend.clock)
        result = backend.run(run_clock, threading.Event(), lambda record: None)
        self.assertFalse(result["platform_checked"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "automatic_platform_check_unavailable")
        self.assertEqual(len(result["load"]["diagnostics"]), 1)


if __name__ == "__main__":
    unittest.main()
