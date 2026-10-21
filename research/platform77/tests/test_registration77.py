"""Temporary COM registration with an owner record (task 015) on an in-memory registry.

Never touches the real registry or processes: winreg and kernel32 are fakes.
"""
import ctypes
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class FakeKey:
    def __init__(self, registry, path):
        self.registry, self.path = registry, path

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.Close()

    def Close(self):
        pass


class FakeRegistry:
    """winreg over {lowercase path: (path, {value name: data})}; one flat view (HKCU32)."""
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ, KEY_WRITE, KEY_SET_VALUE, KEY_WOW64_32KEY, REG_SZ = 1, 2, 4, 8, 1

    def __init__(self):
        self.keys = {}

    def _path(self, parent, sub):
        return sub if parent == self.HKEY_CURRENT_USER else parent.path + "\\" + sub

    def OpenKey(self, parent, sub, reserved=0, access=0):
        path = self._path(parent, sub)
        if path.lower() not in self.keys:
            raise FileNotFoundError(path)
        return FakeKey(self, self.keys[path.lower()][0])

    def CreateKeyEx(self, parent, sub, reserved=0, access=0):
        path = self._path(parent, sub)
        parts = path.split("\\")
        for index in range(1, len(parts) + 1):
            self.keys.setdefault("\\".join(parts[:index]).lower(), ("\\".join(parts[:index]), {}))
        return FakeKey(self, self.keys[path.lower()][0])

    def SetValueEx(self, key, name, reserved, kind, value):
        self.keys[key.path.lower()][1][name] = value

    def QueryValueEx(self, key, name):
        return self.keys[key.path.lower()][1][name], self.REG_SZ

    def _children(self, path):
        prefix = path.lower() + "\\"
        return [stored for lower, (stored, values) in self.keys.items()
                if lower.startswith(prefix) and "\\" not in lower[len(prefix):]]

    def QueryInfoKey(self, key):
        return len(self._children(key.path)), len(self.keys[key.path.lower()][1]), 0

    def EnumValue(self, key, index):
        name, value = list(self.keys[key.path.lower()][1].items())[index]
        return name, value, self.REG_SZ

    def EnumKey(self, key, index):
        return self._children(key.path)[index].rsplit("\\", 1)[1]

    def DeleteKeyEx(self, parent, sub, view=0, reserved=0):
        if self._children(sub):
            raise OSError("key has subkeys: " + sub)
        del self.keys[sub.lower()]

    def put(self, path, **values):
        self.CreateKeyEx(self.HKEY_CURRENT_USER, path)
        self.keys[path.lower()][1].update({"" if k == "default" else k: v for k, v in values.items()})


registry = FakeRegistry()
kernel = Mock()
spec = importlib.util.spec_from_file_location(
    "win32_session77_simulated", Path(__file__).resolve().parents[1] / "win32_session77.py")
session = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"winreg": registry}), patch.object(ctypes, "WinDLL", create=True, return_value=kernel):
    spec.loader.exec_module(session)

PROGID = r"Software\Classes\Harness77Diagnostic.ComCleanup"
CLSID = r"Software\Classes\CLSID\{16B8A521-07E4-46D1-A8E7-197BD1CE4477}"


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        registry.keys.clear()
        registry.put(r"Software\Classes\CLSID")
        self.baseline = dict(registry.keys)
        kernel.reset_mock()
        kernel.CreateMutexW.return_value = 5
        kernel.WaitForSingleObject.return_value = 0
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dll = Path(self.temp.name) / "com_cleanup77.dll"
        self.dll.write_bytes(b"helper")
        # Live processes by PID: creation time of the process that has that PID now.
        self.alive = {}
        for name, value in {"creation_filetime": lambda handle: 1000 if handle == "self" else self.alive[handle],
                            "process_gone": self.gone}.items():
            patcher = patch.object(session, name, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        kernel.GetCurrentProcess.return_value = "self"
        patcher = patch.object(session.os, "getpid", return_value=4242)
        patcher.start()
        self.addCleanup(patcher.stop)

    def gone(self, entry):
        if entry["pid"] not in self.alive:
            return "absent"
        return None if self.alive[entry["pid"]] == entry["creation_filetime"] else "pid-reused"

    def leave(self, processes, *, dll=None, extra=None):
        """Keys as a killed session of this launcher leaves them."""
        record = {"schema_version": 1, "run_id": "killed", "dll": str(dll or self.dll), "processes": processes}
        registry.put(PROGID, default=session.DESCRIPTION, Harness77Owner=json.dumps(record))
        registry.put(PROGID + r"\CLSID", default="{16B8A521-07E4-46D1-A8E7-197BD1CE4477}")
        registry.put(CLSID, default=session.DESCRIPTION, **(extra or {}))
        registry.put(CLSID + r"\InprocServer32", default=str(dll or self.dll), ThreadingModel="Apartment")
        return dict(registry.keys)

    def test_fresh_registration_writes_the_owner_first_and_is_removed_by_cleanup(self):
        report = {"run_id": "fresh"}
        cleanup = session.register_cleanup_helper(self.dll, report)
        owner = json.loads(registry.keys[PROGID.lower()][1]["Harness77Owner"])
        self.assertEqual(list(registry.keys[PROGID.lower()][1]), ["Harness77Owner", ""])
        self.assertEqual(owner["processes"], [{"role": "registrar", "pid": 4242, "creation_filetime": 1000}])
        self.assertEqual(owner["run_id"], "fresh")
        self.alive[77] = 500
        cleanup.note_process("server", 77, 77)
        owner = json.loads(registry.keys[PROGID.lower()][1]["Harness77Owner"])
        self.assertEqual(owner["processes"][-1], {"role": "server", "pid": 77, "creation_filetime": 500})
        self.assertEqual(report["temporary_com_registration"]["owner"], owner)
        cleanup()
        self.assertEqual(registry.keys, self.baseline)
        self.assertTrue(report["temporary_com_registration"]["removed"])
        kernel.ReleaseMutex.assert_called_once_with(5)

    def test_registration_of_a_live_session_is_refused_untouched(self):
        self.alive.update({100: 1, 101: 2})
        before = self.leave([{"role": "registrar", "pid": 100, "creation_filetime": 1},
                             {"role": "server", "pid": 101, "creation_filetime": 2}])
        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite existing COM registration.*owner process alive: 100"):
            session.register_cleanup_helper(self.dll, {"run_id": "second"})
        self.assertEqual(registry.keys, before)

    def test_one_live_process_of_the_killed_session_is_enough_to_refuse(self):
        self.alive[101] = 2  # the launcher is gone, its 1C still runs
        before = self.leave([{"role": "registrar", "pid": 100, "creation_filetime": 1},
                             {"role": "server", "pid": 101, "creation_filetime": 2}])
        with self.assertRaisesRegex(RuntimeError, "owner process alive: 101 \\(server"):
            session.register_cleanup_helper(self.dll, {"run_id": "second"})
        self.assertEqual(registry.keys, before)

    def test_registration_of_a_finished_session_is_replaced_with_evidence(self):
        self.alive[101] = 9  # the PID now belongs to another process
        self.leave([{"role": "registrar", "pid": 100, "creation_filetime": 1},
                    {"role": "server", "pid": 101, "creation_filetime": 2}])
        report = {"run_id": "next"}
        cleanup = session.register_cleanup_helper(self.dll, report)
        state = report["temporary_com_registration"]
        self.assertEqual(state["stale_removed"]["run_id"], "killed")
        self.assertEqual([p["gone"] for p in state["stale_removed"]["processes"]], ["absent", "pid-reused"])
        self.assertEqual(len(state["stale_removed"]["keys"]), 4)
        self.assertEqual(json.loads(registry.keys[PROGID.lower()][1]["Harness77Owner"])["run_id"], "next")
        cleanup()
        self.assertEqual(registry.keys, self.baseline)

    def test_partial_layout_after_a_kill_while_creating_is_replaced(self):
        record = {"schema_version": 1, "run_id": "killed", "dll": str(self.dll),
                  "processes": [{"role": "registrar", "pid": 100, "creation_filetime": 1}]}
        registry.put(PROGID, Harness77Owner=json.dumps(record))  # default value not yet written
        report = {"run_id": "next"}
        session.register_cleanup_helper(self.dll, report)
        self.assertEqual(report["temporary_com_registration"]["stale_removed"]["keys"], [PROGID])

    def test_registration_without_owner_record_is_refused(self):
        registry.put(PROGID, default=session.DESCRIPTION)
        registry.put(CLSID, default=session.DESCRIPTION)
        before = dict(registry.keys)
        with self.assertRaisesRegex(RuntimeError, "no owner record"):
            session.register_cleanup_helper(self.dll, {"run_id": "next"})
        self.assertEqual(registry.keys, before)
        registry.keys = dict(self.baseline)
        registry.put(CLSID, default=session.DESCRIPTION)  # CLSID root alone: never left by this tool
        with self.assertRaisesRegex(RuntimeError, "no owner record"):
            session.register_cleanup_helper(self.dll, {"run_id": "next"})

    def test_changed_or_foreign_values_are_refused(self):
        before = self.leave([{"role": "registrar", "pid": 100, "creation_filetime": 1}], extra={"Foreign": "x"})
        with self.assertRaisesRegex(RuntimeError, "unexpected key or value"):
            session.register_cleanup_helper(self.dll, {"run_id": "next"})
        self.assertEqual(registry.keys, before)
        registry.keys = dict(self.baseline)
        self.leave([{"role": "registrar", "pid": 100, "creation_filetime": 1}])
        registry.put(CLSID + r"\InprocServer32", default="C:\\other.dll")  # not the recorded DLL
        with self.assertRaisesRegex(RuntimeError, "unexpected key or value"):
            session.register_cleanup_helper(self.dll, {"run_id": "next"})

    def test_a_process_that_cannot_be_checked_is_not_a_proof(self):
        self.leave([{"role": "registrar", "pid": 100, "creation_filetime": 1}])
        with patch.object(session, "process_gone", side_effect=PermissionError(5, "Access is denied")):
            with self.assertRaisesRegex(RuntimeError, "cannot be checked"):
                session.register_cleanup_helper(self.dll, {"run_id": "next"})

    def test_busy_lock_refuses_before_reading_the_registry(self):
        kernel.WaitForSingleObject.return_value = 0x102
        with self.assertRaisesRegex(RuntimeError, "lock is busy"):
            session.register_cleanup_helper(self.dll, {"run_id": "next"})
        self.assertEqual(registry.keys, self.baseline)


class ProcessGoneTests(unittest.TestCase):
    """process_gone itself over a fake kernel32."""

    def setUp(self):
        kernel.reset_mock()
        self.entry = {"pid": 100, "creation_filetime": 1}

    def check(self, *, handle=7, error=0, waited=0x102, created=1):
        kernel.OpenProcess.return_value = handle
        kernel.WaitForSingleObject.return_value = waited
        with (patch.object(session.C, "get_last_error", create=True, return_value=error),
              patch.object(session.C, "WinError", create=True, side_effect=lambda e: OSError(e, "error")),
              patch.object(session, "creation_filetime", return_value=created)):
            return session.process_gone(self.entry)

    def test_each_proof_and_a_live_process(self):
        self.assertEqual(self.check(handle=0, error=87), "absent")
        self.assertEqual(self.check(waited=0), "exited")
        self.assertEqual(self.check(created=2), "pid-reused")
        self.assertIsNone(self.check())
        kernel.CloseHandle.assert_called_with(7)

    def test_access_denied_is_not_a_proof(self):
        with self.assertRaises(OSError):
            self.check(handle=0, error=5)


if __name__ == "__main__":
    unittest.main()
