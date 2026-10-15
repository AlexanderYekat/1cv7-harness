"""Diagnostic screenshot ownership policy, evidence and bounded collection."""

import tempfile
import unittest
from pathlib import Path

from harness77 import screenshots77
from harness77.deadlines77 import ManualClock


class ScreenshotPolicyTests(unittest.TestCase):
    def window(self, **over):
        base = {"hwnd": 10, "pid": 7, "tid": 3, "class": "#32770", "text": "warn", "desktop": "harness77_d"}
        base.update(over)
        return base

    def test_own_window_is_eligible(self):
        allowed, reason = screenshots77.evaluate(self.window(), own_pid=7, desktop="harness77_d")
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_foreign_process_refused(self):
        allowed, reason = screenshots77.evaluate(self.window(pid=9), own_pid=7, desktop="harness77_d")
        self.assertFalse(allowed)
        self.assertIn("another process", reason)

    def test_wrong_desktop_refused(self):
        allowed, reason = screenshots77.evaluate(self.window(desktop="Default"), own_pid=7, desktop="harness77_d")
        self.assertFalse(allowed)
        self.assertIn("private desktop", reason)

    def test_missing_handle_refused(self):
        allowed, reason = screenshots77.evaluate(self.window(hwnd=0), own_pid=7, desktop="harness77_d")
        self.assertFalse(allowed)


class ScreenshotCollectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-shot-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_captures_own_and_records_hash(self):
        windows = [{"hwnd": 1, "pid": 7, "desktop": "d", "class": "#32770"}]

        def capture(hwnd, path):
            Path(path).write_bytes(b"PNGDATA")
        records = screenshots77.collect(windows, own_pid=7, desktop="d", run_id="r",
                                        phase="calculation", out_dir=self.root / "s", capture=capture)
        self.assertTrue(records[0]["captured"])
        self.assertEqual(records[0]["file"]["size_bytes"], 7)
        self.assertEqual(len(records[0]["file"]["sha256"]), 64)

    def test_capture_failure_is_recorded_not_raised(self):
        def capture(hwnd, path):
            raise RuntimeError("PrintWindow failed")
        records = screenshots77.collect([{"hwnd": 1, "pid": 7, "desktop": "d"}], own_pid=7,
                                        desktop="d", run_id="r", phase="open",
                                        out_dir=self.root / "s", capture=capture)
        self.assertFalse(records[0]["captured"])
        self.assertIn("capture failed", records[0]["error"])

    def test_budget_exhaustion_stops_capture(self):
        clock = ManualClock()

        def capture(hwnd, path):
            clock.advance(10)  # each capture overruns the 5 s budget
            Path(path).write_bytes(b"x")
        windows = [{"hwnd": i + 1, "pid": 7, "desktop": "d"} for i in range(3)]
        records = screenshots77.collect(windows, own_pid=7, desktop="d", run_id="r", phase="open",
                                        out_dir=self.root / "s", capture=capture, budget_s=5.0, clock=clock)
        self.assertTrue(records[0]["captured"])
        self.assertFalse(records[1]["captured"])
        self.assertIn("budget", records[1]["error"])


if __name__ == "__main__":
    unittest.main()
