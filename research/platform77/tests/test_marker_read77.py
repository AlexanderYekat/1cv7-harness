"""The monitor only retries reading the existing marker."""
import errno
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marker_read77 import MarkerReadError, read_marker


class MarkerReadTests(unittest.TestCase):
    def setUp(self):
        self.path = Mock(spec=Path)
        self.path.__str__ = Mock(return_value="ert-result-finished")
        self.error = PermissionError(errno.EACCES, "sharing denied")
        self.retries = []
        self.now = 0
        self.check = Mock()

    def pause(self, seconds):
        self.now += seconds

    def read(self):
        return read_marker(self.path, self.retries, check=self.check, clock=lambda: self.now, pause=self.pause)

    def test_access_retry_reads_the_same_file(self):
        self.path.read_text.side_effect = [self.error, "current-run\n"]
        self.assertEqual(self.read(), "current-run")
        self.assertEqual(self.path.read_text.call_count, 2)
        self.assertEqual(self.check.call_count, 2)
        self.assertEqual(self.retries[0]["errno"], errno.EACCES)
        self.assertEqual(self.retries[0]["path"], "ert-result-finished")

    def test_challenge_retry_reports_its_own_operation(self):
        self.path.__str__.return_value = "proxy-challenge-complete"
        self.path.read_text.side_effect = [self.error, "current-run\n"]
        value = read_marker(self.path, self.retries, check=self.check, operation="proxy-challenge-read",
                            clock=lambda: self.now, pause=self.pause)
        self.assertEqual(value, "current-run")
        self.assertEqual(self.retries[0]["operation"], "proxy-challenge-read")
        self.assertEqual(self.retries[0]["path"], "proxy-challenge-complete")
        self.assertEqual(self.check.call_count, 2)

    def test_permanent_access_denial_has_a_bounded_diagnostic(self):
        self.path.read_text.side_effect = self.error
        with self.assertRaises(MarkerReadError) as caught:
            self.read()
        detail = caught.exception.detail
        self.assertEqual(detail["attempts"], self.path.read_text.call_count)
        self.assertLessEqual(detail["attempts"], 26)
        self.assertAlmostEqual(self.now, 1)
        self.assertIn("sharing denied", detail["error"])

    def test_missing_or_invalid_marker_is_not_retried(self):
        for error in (FileNotFoundError(errno.ENOENT, "missing"), PermissionError(errno.EPERM, "denied"),
                      UnicodeDecodeError("ascii", b"\xff", 0, 1, "not ASCII")):
            self.path.read_text.reset_mock(side_effect=True)
            self.path.read_text.side_effect = error
            with self.subTest(error=error), self.assertRaises(MarkerReadError) as caught:
                self.read()
            self.assertEqual(caught.exception.detail["attempts"], 1)
            self.path.read_text.assert_called_once_with(encoding="ascii")
        self.assertEqual(self.retries, [])

    def test_cancellation_between_attempts_prevents_another_read(self):
        self.path.read_text.side_effect = self.error
        self.check.side_effect = [None, TimeoutError("shutdown deadline")]
        with self.assertRaisesRegex(TimeoutError, "shutdown deadline"):
            self.read()
        self.path.read_text.assert_called_once_with(encoding="ascii")
