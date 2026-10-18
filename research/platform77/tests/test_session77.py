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

        with patch.object(session.subprocess, "Popen", side_effect=popen), patch.object(session.time, "sleep"):
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
