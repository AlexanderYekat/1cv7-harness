"""Portable simulated process/registry failures; never call native APIs."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shutdown77 import PINNED

# Load an isolated controller with an entirely fake Windows adapter, including
# on Windows. Do not leak this adapter to other tests or real session imports.
spec = importlib.util.spec_from_file_location("session77_simulated", Path(__file__).resolve().parents[1] / "session77.py")
session = importlib.util.module_from_spec(spec)
adapter = types.SimpleNamespace(kernel=Mock(), processes=Mock(), register_cleanup_helper=Mock())
with patch.dict(sys.modules, {"win32_session77": adapter}):
    spec.loader.exec_module(session)


class SessionFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name).resolve()
        self.exe = self.out / "1cv7l.exe"
        self.helper = self.out / "cleanup.dll"
        self.kernel = Mock()
        self.kernel.OpenProcess.return_value = 123
        self.kernel.WaitForSingleObject.side_effect = [0x102, 0]
        self.kernel.TerminateProcess.return_value = 1

        def process_times(handle, created, *unused):
            created._obj.dwLowDateTime = 500 if handle == 123 else 100
            return 1

        def exit_code(handle, result):
            result._obj.value = 0xE0000077
            return 1

        self.kernel.GetProcessTimes.side_effect = process_times
        self.kernel.GetExitCodeProcess.side_effect = exit_code
        self.debugger = Mock(pid=10, _handle=42)
        self.debugger.poll.return_value = 0
        self.candidate = {"pid": 77, "parent_pid": 10}
        self.inventory = [[], [self.candidate], [self.candidate], []]
        self.report = {"run_id": "simulation"}
        self.cleanup = Mock()

    def run_simulated(self, wrong_image=False):
        def image_name(handle, flags, buf, size):
            buf.value = str(self.out / "foreign.exe" if wrong_image else self.exe)
            return 1

        def digest(path):
            return PINNED["exe" if path == self.exe else "helper" if path == self.helper else path.name]

        self.kernel.QueryFullProcessImageNameW.side_effect = image_name
        if wrong_image:
            self.inventory = [[], [self.candidate], []]
        with (patch.object(session, "kernel", self.kernel),
              patch.object(session, "processes", side_effect=self.inventory),
              patch.object(session, "register_cleanup_helper", return_value=self.cleanup),
              patch.object(session, "sha256", side_effect=lambda p: "commands" if p.name == "debugger.txt" else digest(p)),
              patch.object(session.subprocess, "Popen", return_value=self.debugger),
              patch.object(session.subprocess, "CREATE_NO_WINDOW", 0, create=True)):
            return session.run_session(self.out / "base", self.exe, self.out / "cdb.exe",
                                       self.helper, "test", self.out, self.report)

    def test_unverified_handle_is_closed_but_never_terminated(self):
        result = self.run_simulated(wrong_image=True)
        self.assertIn("executable mismatch", result["error"])
        self.kernel.TerminateProcess.assert_not_called()
        self.kernel.WaitForSingleObject.assert_not_called()
        self.kernel.CloseHandle.assert_called_once_with(123)
        self.cleanup.assert_called_once()
        self.assertNotIn("server", result)

    def test_caller_cancel_takes_the_owned_cleanup_and_client_limit_is_configurable(self):
        # Reach the main loop: the debugger reports ready, the client is a separate process.
        (self.out / "debugger.log").write_text("\nHARNESS77_DEBUGGER_READY\n", encoding="ascii")
        client = Mock(pid=11, _handle=43)
        client.poll.return_value = None
        # The client process ends once the cleanup asked it to and waited.
        client.wait.side_effect = lambda timeout=None: setattr(client.poll, "return_value", 0)
        cancel = self.out / "caller-cancel"
        cancel.write_text("simulation", encoding="ascii")
        self.report.update(cancel_path=str(cancel), client_timeout_seconds=3600)
        # before, ownership, ancestry recheck, before activation, after cleanup
        self.inventory = [[], [self.candidate], [self.candidate], [self.candidate], []]
        launched = []

        def popen(command, **kwargs):
            launched.append(command)
            return self.debugger if len(launched) == 1 else client

        with patch.object(session.subprocess, "Popen", side_effect=popen), patch.object(session.time, "sleep"):
            result = self.run_simulated_popen()
        self.assertIn("//T:3600", launched[1])
        self.assertTrue(result["user_cancelled"])
        self.assertIn("cancelled by the caller", result["error"])
        self.assertIsNone(result.get("timeout_phase"))
        client.wait.assert_called()
        self.kernel.TerminateProcess.assert_called_once_with(123, 0xE0000077)
        self.assertTrue(result["cleanup_verified"])

    def test_open_deadline_stops_a_session_whose_first_command_never_starts(self):
        (self.out / "debugger.log").write_text("\nHARNESS77_DEBUGGER_READY\n", encoding="ascii")
        client = Mock(pid=11, _handle=43)
        client.poll.return_value = None
        client.wait.side_effect = lambda timeout=None: setattr(client.poll, "return_value", 0)
        # Opening (base, reindex, controller) has not reached the first command in time.
        self.report.update(open_timeout_seconds=0.001, ert_commands=["check"])
        self.inventory = [[], [self.candidate], [self.candidate], [self.candidate], []]
        launched = []

        def popen(command, **kwargs):
            launched.append(command)
            return self.debugger if len(launched) == 1 else client

        # A 1-s-per-read clock: Windows monotonic() before 3.13 ticks by ~16 ms and may not move at all.
        ticks = iter(range(100000))
        with patch.object(session.subprocess, "Popen", side_effect=popen), patch.object(session.time, "sleep"), \
                patch.object(session.time, "monotonic", side_effect=lambda: next(ticks)):
            result = self.run_simulated_popen()
        self.assertEqual(result["timeout_phase"], "open")
        self.assertIn("open deadline", result["error"])
        self.kernel.TerminateProcess.assert_called_once_with(123, 0xE0000077)
        self.assertTrue(result["cleanup_verified"])

    def test_client_limit_defaults_to_the_accepted_140_seconds(self):
        self.assertIn('report.get("client_timeout_seconds", 140)',
                      (Path(__file__).resolve().parents[1] / "session77.py").read_text(encoding="utf-8"))

    def run_simulated_popen(self):
        """run_simulated with the caller's Popen patch left in place."""
        def image_name(handle, flags, buf, size):
            buf.value = str(self.exe)
            return 1

        def digest(path):
            return PINNED["exe" if path == self.exe else "helper" if path == self.helper else path.name]

        self.kernel.QueryFullProcessImageNameW.side_effect = image_name
        with (patch.object(session, "kernel", self.kernel),
              patch.object(session, "processes", side_effect=self.inventory),
              patch.object(session, "register_cleanup_helper", return_value=self.cleanup),
              patch.object(session, "sha256", side_effect=lambda p: "commands" if p.name == "debugger.txt" else digest(p)),
              patch.object(session.subprocess, "CREATE_NO_WINDOW", 0, create=True)):
            return session.run_session(self.out / "base", self.exe, self.out / "cdb.exe",
                                       self.helper, "test", self.out, self.report)

    def run_to_exit(self, events, deadline=None):
        """A session whose client and debugger have exited when the main loop first checks.

        `events` are the successive reads of the shutdown events.
        """
        (self.out / "debugger.log").write_text("\nHARNESS77_DEBUGGER_READY\n", encoding="ascii")
        client = Mock(pid=11, _handle=43, returncode=0)
        client.poll.return_value = 0
        self.kernel.WaitForSingleObject.side_effect = None
        self.kernel.WaitForSingleObject.return_value = 0
        # before, ownership, ancestry recheck, before activation, main loop, after cleanup
        self.inventory = [[], [self.candidate], [self.candidate], [self.candidate], [self.candidate], []]
        launched = []

        def popen(command, **kwargs):
            launched.append(command)
            return self.debugger if len(launched) == 1 else client

        fake = types.SimpleNamespace(process_cpu_ms=Mock(return_value=1.0))
        patches = [patch.object(session.subprocess, "Popen", side_effect=popen), patch.object(session.time, "sleep"),
                   patch.object(session, "read_events", side_effect=events),
                   patch.dict(sys.modules, {"win32_session77": fake})]
        if deadline:
            patches.append(patch.object(session, "Deadline", deadline))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return self.run_simulated_popen()

    def test_shutdown_between_the_read_and_the_exit_check_is_observed_after_exit(self):
        # N1c (task 014): the whole coordinated shutdown fell between two checks.
        events = [{"run_id": "simulation", "name": "modules_released", "value": "ok"},
                  {"run_id": "simulation", "name": "server_released", "value": "ok"}]
        result = self.run_to_exit([[], events])
        self.assertNotIn("error", result)
        self.assertTrue(result["shutdown_started_observed"])
        self.assertTrue(result["shutdown_observed_after_exit"])
        self.assertLess(result["shutdown_exit_after_read_seconds"], 5)
        self.assertEqual(result["poll_rounds"]["count"], 0)

    def test_shutdown_seen_after_exit_is_not_a_timeout_however_long_the_round(self):
        # R1 (task 015): under load one polling round outlasted the 10 s limit; the shutdown
        # itself took ~2 s and both processes had exited, so nothing could hang any more.
        from shutdown77 import Deadline
        events = [{"run_id": "simulation", "name": "modules_released", "value": "ok"}]
        result = self.run_to_exit([[], events], deadline=lambda started: Deadline(started, shutdown=0))
        self.assertNotIn("error", result)
        self.assertIsNone(result.get("timeout_phase"))
        self.assertTrue(result["shutdown_started_observed"])

    def test_exit_without_shutdown_events_stays_unarmed(self):
        result = self.run_to_exit([[], []])
        self.assertFalse(result["shutdown_started_observed"])
        self.assertNotIn("shutdown_observed_after_exit", result)

    def test_started_processes_are_recorded_in_the_registration(self):
        self.run_to_exit([[], []])
        self.assertEqual([c.args[:2] for c in self.cleanup.note_process.call_args_list],
                         [("debugger", 10), ("server", 77), ("client", 11)])
        self.assertEqual(self.cleanup.note_process.call_args_list[1].args[2], 123)

    def slow_start(self, startup=None):
        """1C appears as the CDB child only after 30 s of a 3-s-per-read clock."""
        ticks = iter(range(0, 100000, 3))
        if startup:
            self.report["startup_timeout_seconds"] = startup
        # before, 10 rounds without 1C, ownership, ancestry recheck, after cleanup
        self.inventory = [[]] * 11 + [[self.candidate]] * 2 + [[]]
        # The debugger never becomes ready: the run stops right after ownership.
        self.debugger.poll.return_value = None
        with patch.object(session.time, "monotonic", side_effect=lambda: next(ticks)), \
                patch.object(session.time, "sleep"):
            return self.run_simulated()

    def test_startup_waits_for_the_callers_deadline(self):
        result = self.slow_start(startup=180)
        self.assertGreater(result["startup_elapsed_seconds"]["ownership"], 20)
        self.assertTrue(result["server"]["ownership_verified"])
        self.assertEqual(result["timeout_phase"], "debugger-ready")

    def test_startup_keeps_the_research_20_s_by_default(self):
        result = self.slow_start()
        self.assertEqual(result["timeout_phase"], "ownership")
        self.assertNotIn("server", result)

    def test_refusal_before_ownership_is_a_verified_cleanup_with_the_identity_observer(self):
        # L4/L5: an existing registration refused, nothing started, nothing to retire.
        identity = self.out / "proxy_identity77.dll"
        identity.write_bytes(b"identity")
        refusal = RuntimeError("refusing to overwrite existing COM registration: x: owner process alive: 1")
        fake = types.SimpleNamespace(BaselineProcesses=Mock(return_value=Mock(preserved=Mock(return_value=True))))
        concurrent = types.SimpleNamespace(IDENTITY_SHA="identity", unexpected_processes=Mock(), validate_proxy=Mock())
        self.inventory = [[], []]
        self.report["run_id"] = "8d3a4f0e-2c1b-4e5f-9a7b-6c5d4e3f2a10"  # the observer needs a UUID
        with (patch.object(session, "kernel", self.kernel), patch.object(session, "processes", side_effect=self.inventory),
              patch.object(session, "register_cleanup_helper", side_effect=refusal),
              patch.object(session, "sha256", side_effect=lambda p: "identity" if p == identity else "commands"),
              patch.dict(sys.modules, {"win32_session77": fake, "concurrent77": concurrent})):
            result = session.run_session(self.out / "base", self.exe, self.out / "cdb.exe", self.helper, "test",
                                         self.out, self.report, desktop="desktop", identity_dll=identity)
        self.assertIn("owner process alive", result["error"])
        self.assertEqual(result["cleanup_errors"], [])
        self.assertTrue(result["cleanup_verified"])
        self.kernel.TerminateProcess.assert_not_called()

    def test_failure_stops_only_verified_handle_and_records_registry_error(self):
        self.cleanup.side_effect = PermissionError("registry cleanup denied")
        result = self.run_simulated()
        self.assertTrue(result["server"]["ownership_verified"])
        self.kernel.TerminateProcess.assert_called_once_with(123, 0xE0000077)
        self.kernel.CloseHandle.assert_called_once_with(123)
        self.assertTrue(result["forced_cleanup"])
        self.assertFalse(result["cleanup_verified"])
        self.assertIn("registry cleanup denied", result["cleanup_errors"][0])
        self.assertEqual(result["server_exit_code"], 0xE0000077)
        self.assertEqual(result["processes_after"], [])


if __name__ == "__main__":
    unittest.main()
