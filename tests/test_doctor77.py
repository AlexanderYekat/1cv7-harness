"""Prerequisite diagnoses, refusal cases and observational-only behavior."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness77 import basecopy77, cli, doctor77


def pe(machine=0x14c):
    header = bytearray(64)
    header[:2] = b"MZ"
    header[60:64] = (64).to_bytes(4, "little")
    return bytes(header) + b"PE\0\0" + machine.to_bytes(2, "little")


class Observer:
    def registered(self, path):
        return True

    def com_registrations(self):
        return []

    def processes(self):
        return []


class DoctorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="h77-doctor-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.base = self.root / "base"
        self.base.mkdir()
        self.copy = self.root / "copy"
        self.out = self.root / "results"
        self.project = self.root / "project.toml"
        self.stand = self.root / "stand.toml"
        for name in ("1Cv7.MD", "1Cv7.DD", "1SUSERS.DBF", "1SJOURN.DBF"):
            (self.base / name).write_bytes(b"database")
        for name in ("1CPP.dll", "FormEx.dll"):
            (self.base / name).write_bytes(pe())
        for name in ("exe", "cdb", "helper", "identity"):
            (self.root / (name + ".bin")).write_bytes(pe())
        for name in ("template.ert", "source.1s", "launcher.py"):
            (self.root / name).write_text("input", encoding="utf-8")
        (self.root / "modules").mkdir()
        self.project.write_text('''schema_version=1
[project]
id="doctor"
[build]
template="template.ert"
source="source.1s"
[configuration]
modules="modules"
[deadlines]
open_timeout_s=30
calculation_timeout_s=60
cancel_timeout_s=10
shutdown_timeout_s=10
total_timeout_s=120
''', encoding="utf-8")
        self.stand.write_text('''schema_version=1
[stand]
name="doctor"
backend="native"
launcher="launcher.py"
[stand.paths]
exe="exe.bin"
cdb="cdb.bin"
helper="helper.bin"
identity="identity.bin"
[stand.base]
path="base"
copy_path="copy"
[stand.pinned]
"1Cv7.MD"="''' + hashlib.sha256(b"database").hexdigest() + '"\n', encoding="utf-8")
        self.observer = Observer()

    def report(self, **kwargs):
        return doctor77.diagnose(self.project, self.stand, output_root=self.out, windows=self.observer, **kwargs)

    def check(self, report, id_):
        return next(row for row in report["checks"] if row["id"] == id_)

    def test_ready_observation_never_claims_platform_execution(self):
        report = self.report()
        self.assertEqual((report["status"], report["exit_code"]), ("ready", 0))
        self.assertFalse(report["platform_checked"])
        self.assertFalse(report["launch_performed"])
        self.assertEqual(self.check(report, "stand.launcher")["details"]["path"], str(self.root / "launcher.py"))

    def test_missing_dll_unregistered_copy_and_wrong_hash_are_all_reported(self):
        (self.root / "helper.bin").unlink()
        (self.base / "1Cv7.MD").write_bytes(b"changed")
        self.observer.registered = lambda _: False
        report = self.report()
        self.assertEqual(report["exit_code"], 2)
        for id_, code in (("stand.helper", "file_missing"), ("copy.registration", "copy_unregistered"),
                          ("pinned.1Cv7.MD", "hash_mismatch")):
            self.assertEqual(self.check(report, id_)["code"], code)

    def test_wrong_relative_launcher_resolves_at_profile_not_cwd(self):
        text = self.stand.read_text(encoding="utf-8").replace('launcher="launcher.py"', 'launcher="missing/launcher.py"')
        self.stand.write_text(text, encoding="utf-8")
        report = self.report()
        row = self.check(report, "stand.launcher")
        self.assertEqual(row["code"], "file_missing")
        self.assertEqual(row["details"]["path"], str(self.root / "missing/launcher.py"))

    def test_packaged_runtime_is_inspected_and_damage_blocks_doctor(self):
        from harness77.native_runtime77 import RuntimeUnavailable
        self.stand.write_text(self.stand.read_text(encoding='utf-8').replace('launcher="launcher.py"', 'runtime="forms"'), encoding='utf-8')
        with mock.patch('harness77.native_runtime77.inspect_runtime', return_value={'runtime_version': 'test', 'files_checked': 33}) as inspect:
            report = self.report()
            self.assertEqual(report['status'], 'ready')
            self.assertEqual(self.check(report, 'stand.runtime')['code'], 'runtime_verified')
            inspect.assert_called_once_with('forms')
        with mock.patch('harness77.native_runtime77.inspect_runtime', side_effect=RuntimeUnavailable('hash mismatch')):
            report = self.report()
            self.assertEqual(report['exit_code'], 2)
            self.assertIn('hash mismatch', self.check(report, 'stand.runtime')['message'])

    def test_packaged_runtime_requires_a_project_on_a_copy(self):
        self.stand.write_text(self.stand.read_text(encoding='utf-8').replace('launcher="launcher.py"', 'runtime="headless"'), encoding='utf-8')
        self.project.write_text(self.project.read_text(encoding='utf-8').replace('[configuration]\nmodules="modules"\n', ''), encoding='utf-8')
        with mock.patch('harness77.native_runtime77.inspect_runtime', return_value={}):
            self.assertEqual(self.check(self.report(), 'runtime.copy')['code'], 'runtime_requires_copy')

    def test_x64_cdb_and_invalid_dll_are_blocked(self):
        (self.root / "cdb.bin").write_bytes(pe(0x8664))
        (self.root / "identity.bin").write_bytes(b"not a PE")
        report = self.report()
        self.assertEqual(self.check(report, "pe.cdb")["code"], "pe_wrong_machine")
        self.assertEqual(self.check(report, "pe.identity")["status"], "blocked")

    def test_existing_copy_and_lock_are_preserved_and_blocked(self):
        self.copy.mkdir()
        lock = basecopy77.lock_path(self.copy)
        lock.write_bytes(b"unreadable owner")
        report = self.report()
        self.assertEqual(self.check(report, "copy.state")["status"], "blocked")
        self.assertEqual(lock.read_bytes(), b"unreadable owner")
        self.assertTrue(self.copy.is_dir())

    def test_idle_guard_does_not_block_or_get_created(self):
        guard = basecopy77.lock_path(self.copy).with_suffix(".lock.guard")
        self.assertEqual(self.report()["status"], "ready")
        self.assertFalse(guard.exists())
        guard.write_bytes(b"guard")
        self.assertEqual(self.report()["status"], "ready")
        self.assertEqual(guard.read_bytes(), b"guard")

    def test_unused_copy_does_not_block_direct_project(self):
        self.project.write_text(self.project.read_text(encoding="utf-8").replace('[configuration]\nmodules="modules"\n', ''), encoding="utf-8")
        basecopy77.lock_path(self.copy).write_bytes(b"someone else's copy")
        self.observer.registered = mock.Mock(side_effect=AssertionError("unused copy"))
        report = self.report()
        self.assertEqual(report["status"], "ready")
        self.assertEqual(self.check(report, "copy.path")["code"], "copy_not_required")

    def test_busy_or_unreadable_table_is_blocked(self):
        with mock.patch.object(doctor77, "open_in_1c", return_value="1SUSERS.DBF"):
            self.assertEqual(self.check(self.report(), "base.idle")["code"], "base_busy_or_unreadable")

    def test_com_is_blocking_and_unrelated_processes_only_warn(self):
        self.observer.processes = lambda: [{"pid": 123, "image": "1cv7l.exe"}]
        report = self.report()
        self.assertEqual(report["status"], "ready")
        self.assertEqual(self.check(report, "native.processes")["status"], "warning")
        self.observer.com_registrations = lambda: ["owned-or-stale-root"]
        self.assertEqual(self.check(self.report(), "native.com")["code"], "com_registration_present")

    def test_unreadable_registry_does_not_suppress_other_checks(self):
        self.observer.registered = mock.Mock(side_effect=PermissionError("registry denied"))
        report = self.report()
        self.assertEqual(self.check(report, "copy.registration")["status"], "blocked")
        self.assertEqual(self.check(report, "native.com")["status"], "passed")

    def test_output_and_copy_overlap_are_blocked_without_creating_output(self):
        self.out = self.base / "results"
        self.assertEqual(self.check(self.report(), "paths.overlap")["code"], "paths_overlap")
        self.assertFalse(self.out.exists())
        self.out = self.copy / "results"
        self.assertEqual(self.check(self.report(), "paths.overlap")["status"], "blocked")

    def test_copy_inside_source_is_blocked(self):
        text = self.stand.read_text(encoding="utf-8").replace('copy_path="copy"', 'copy_path="base/copy"')
        self.stand.write_text(text, encoding="utf-8")
        self.assertEqual(self.check(self.report(), "paths.overlap")["status"], "blocked")

    def test_existing_output_file_is_blocked(self):
        self.out.write_bytes(b"keep")
        self.assertEqual(self.check(self.report(), "output.directory")["code"], "output_is_file")
        self.assertEqual(self.out.read_bytes(), b"keep")

    def test_output_parent_is_a_file(self):
        self.out.write_bytes(b"keep")
        self.out = self.out / "nested"
        self.assertEqual(self.check(self.report(), "output.directory")["status"], "blocked")

    def test_overlap_through_symlink_is_detected(self):
        link = self.root / "alias"
        try:
            link.symlink_to(self.base, target_is_directory=True)
        except OSError:
            self.skipTest("symlink unavailable")
        self.out = link / "results"
        self.assertEqual(self.check(self.report(), "paths.overlap")["status"], "blocked")

    def test_missing_inputs_and_invalid_deadlines(self):
        (self.root / "source.1s").unlink()
        self.project.write_text(self.project.read_text(encoding="utf-8").replace("total_timeout_s=120", "total_timeout_s=1"), encoding="utf-8")
        report = self.report()
        self.assertEqual(self.check(report, "project.source")["code"], "file_missing")
        self.assertEqual(self.check(report, "deadlines")["status"], "blocked")

    def test_missing_and_malformed_profiles_return_machine_report(self):
        self.project.unlink()
        self.stand.write_text("stand = 123\nschema_version=1", encoding="utf-8")
        report = self.report()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(len(report["checks"]), 2)
        json.dumps(report)

    def test_password_value_is_not_echoed(self):
        self.stand.write_text(self.stand.read_text(encoding="utf-8").replace('[stand.base]', '[stand.base]\npassword="very-secret"'), encoding="utf-8")
        report = self.report()
        self.assertEqual(report["status"], "blocked")
        self.assertNotIn("very-secret", json.dumps(report))

    def test_tool_hashes_and_invalid_expected_hashes(self):
        with self.stand.open("a", encoding="utf-8") as stream:
            stream.write('[stand.tool_hashes]\nhelper="' + '0' * 64 + '"\nunknown="bad"\nidentity="bad"\n')
        report = self.report()
        for id_ in ("tool_hash.helper", "tool_hash.unknown", "tool_hash.identity"):
            self.assertEqual(self.check(report, id_)["status"], "blocked")

    def test_no_launch_lock_or_filesystem_mutation(self):
        def snapshot():
            return {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.root.rglob("*") if p.is_file()}
        before = snapshot()
        with mock.patch("subprocess.Popen", side_effect=AssertionError("launch")), \
             mock.patch.object(basecopy77, "acquire", side_effect=AssertionError("lock")), \
             mock.patch.object(basecopy77, "_lock_updates", side_effect=AssertionError("guard")):
            self.assertEqual(self.report()["status"], "ready")
        self.assertEqual(before, snapshot())
        self.assertFalse(self.out.exists())
        self.assertFalse(self.copy.exists())

    def test_cli_json_uses_stdout_and_status_code(self):
        self.project.unlink()
        capture, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(errors):
            code = cli.main(["doctor", "--project", str(self.project), "--stand", str(self.stand), "--format", "json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(capture.getvalue())["operation"], "doctor")
        self.assertEqual(errors.getvalue(), "")

    def test_text_cli_and_simulation_work_from_foreign_cwd(self):
        self.stand.write_text('''schema_version=1
[stand]
name="simulation"
backend="simulation"
scenario="scenario.json"
[stand.base]
path="unused-base"
''', encoding="utf-8")
        (self.root / "scenario.json").write_text("{}", encoding="utf-8")
        foreign = self.root / "foreign"
        foreign.mkdir()
        result = subprocess.run([sys.executable, "-B", "-m", "harness77", "doctor", "--project", str(self.project),
                                 "--stand", str(self.stand)], cwd=foreign, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertIn("doctor: ready", result.stdout.decode("utf-8"))
        self.assertFalse((foreign / ".artifacts").exists())

    def test_native_on_non_windows_is_explicitly_blocked(self):
        if os.name == "nt":
            self.skipTest("non-Windows assertion")
        report = doctor77.diagnose(self.project, self.stand, output_root=self.out)
        self.assertEqual(self.check(report, "native.windows")["code"], "windows_required")


if __name__ == "__main__":
    unittest.main()
