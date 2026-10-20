"""Task 006: application parameters, cancellation and partial results on the native path.

A fake launcher stands in for 1C; the real long report is the native acceptance.
"""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import patch

from harness77.config77 import ConfigError, load_project
from harness77.deadlines77 import Clock
from harness77.report77 import file_evidence

from stage4_fixtures import run, write_project

ARGS = '''
import argparse, hashlib, json, sys, time
from pathlib import Path
parser = argparse.ArgumentParser()
for name in ("--run-dir", "--ert", "--ert-sha256", "--run-id", "--base", "--user", "--exe", "--result",
             "--deadlines-json", "--cdb", "--helper", "--identity", "--parameters-json", "--commands-json"):
    parser.add_argument(name)
parser.add_argument("--screenshots", action="store_true")
args, _ = parser.parse_known_args()
run_dir = Path(args.run_dir)

def finish(status="passed", reason=None, cancelled=False, operations=(), files=()):
    out = {"run_id": args.run_id, "ert_sha256": args.ert_sha256, "platform_checked": True,
           "status": status, "reason": reason, "cancelled": cancelled, "timeout_phase": None,
           "load": {"status": "passed", "diagnostics": []}, "operations": list(operations),
           "result_files": list(files), "phase_durations_s": {},
           "shutdown": {"status": "passed", "cleanup_verified": True, "server_exit_code": 0,
                        "others_preserved": True},
           "platform_identity": {"platform_version": "7.70.027-fake"}}
    Path(args.result).write_text(json.dumps(out), encoding="utf-8")
'''

ECHO = ARGS + '''
(run_dir / "launcher-args.json").write_text(json.dumps(
    {"parameters": json.loads(args.parameters_json), "commands": json.loads(args.commands_json)}), encoding="utf-8")
finish(operations=[{"name": "full", "status": "passed", "value": "COMPLETE"}])
'''

WAITS_FOR_CANCEL = ARGS + '''
deadline = time.monotonic() + 30
seen = None
# The file appears before its text is written; under load a reader can see it empty.
while not seen and time.monotonic() < deadline:
    seen = (run_dir / "cancel").read_text(encoding="ascii") if (run_dir / "cancel").exists() else None
    time.sleep(0.05)
finish(status="blocked", reason="cancelled", cancelled=seen == args.run_id)
'''

IGNORES_CANCEL = ARGS + '''
time.sleep(120)
finish()
'''

PACKAGE = ARGS + '''
package = run_dir / "kudir" / "exchange" / "KUDIR4_X"
package.mkdir(parents=True)
(package / "ledger62.csv").write_bytes(b"partial")
digest = hashlib.sha256(b"partial").hexdigest()
finish(operations=[{"name": "__COMMAND__", "status": "__OPSTATUS__", "value": "__VALUE__"}],
       files=[{"path": "kudir/exchange/KUDIR4_X/ledger62.csv", "sha256": digest, "complete": False,
               "operation": "__COMMAND__", "package": "KUDIR4_X", "package_status": "__VALUE__"}])
'''

FAST = {"open_timeout_s": 5, "calculation_timeout_s": 60, "cancel_timeout_s": 1,
        "shutdown_timeout_s": 1, "total_timeout_s": 100}


class LongNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-long-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base-for-test"
        self.base.mkdir()

    def project(self, tests, parameters=None, deadlines=FAST):
        path = write_project(self.root, tests=tests, deadlines=deadlines)
        if parameters:
            lines = ["[platform.parameters]"] + [f'{k} = "{v}"' for k, v in parameters.items()]
            path.write_text(path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")
        return path

    def stand(self, body):
        launcher = self.root / "launcher.py"
        launcher.write_text(textwrap.dedent(body), encoding="utf-8")
        path = self.root / "stand.toml"
        path.write_text("\n".join([
            "schema_version = 1", "[stand]", 'name = "native"', 'backend = "native"',
            f'launcher = "{launcher.as_posix()}"', "[stand.paths]", f'exe = "{Path(sys.executable).as_posix()}"',
            "[stand.base]", f'path = "{self.base.as_posix()}"', 'user = "ВВВ"']) + "\n", encoding="utf-8")
        return path

    def go(self, project, stand, cancel=None):
        return run(project, stand, self.root / "runs", clock=Clock(), cancel=cancel)

    def test_parameters_and_test_commands_reach_the_launcher(self):
        tests = [{"name": "check", "command": "check", "expect": "passed"},
                 {"name": "full", "command": "full", "expect": "passed", "expect_value": "COMPLETE"},
                 {"name": "again", "command": "full", "expect": "passed"}]
        project = self.project(tests, {"start": "2026-01-01", "end": "2026-10-10"})
        report = self.go(project, self.stand(ECHO))
        seen = json.loads((Path(report["run_dir"]) / "launcher-args.json").read_text(encoding="utf-8"))
        self.assertEqual(seen, {"parameters": {"start": "2026-01-01", "end": "2026-10-10"},
                                "commands": ["check", "full"]})
        self.assertEqual(report["inputs"]["parameters"], {"start": "2026-01-01", "end": "2026-10-10"})

    def test_cancel_reaches_the_launcher_by_file(self):
        cancel = threading.Event()
        threading.Timer(1.0, cancel.set).start()
        report = self.go(self.project([("full", "passed")]), self.stand(WAITS_FOR_CANCEL), cancel)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(report["cancelled"])
        platform = next(s for s in report["stages"] if s["stage"] == "platform_check")
        self.assertEqual(platform["reason"], "cancelled")

    def test_launcher_ignoring_cancel_is_stopped_after_cancel_and_shutdown_phases(self):
        cancel = threading.Event()
        threading.Timer(0.5, cancel.set).start()
        started = time.monotonic()
        report = self.go(self.project([("full", "passed")]), self.stand(IGNORES_CANCEL), cancel)
        # cancel 1 s + shutdown 1 s + 10 s margin, far before the 100 s total backstop
        self.assertLess(time.monotonic() - started, 25)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("forced=True", report["reason"])

    def test_launcher_runs_in_its_own_process_group(self):
        with patch("harness77.native77.subprocess.Popen", side_effect=OSError("stop")) as popen:
            self.go(self.project([("full", "passed")]), self.stand(ECHO))
        self.assertEqual(popen.call_args.kwargs["creationflags"],
                         getattr(__import__("subprocess"), "CREATE_NEW_PROCESS_GROUP", 0))

    def package(self, command, op_status, value, expect, expect_value):
        body = (PACKAGE.replace("__COMMAND__", command).replace("__OPSTATUS__", op_status)
                .replace("__VALUE__", value))
        tests = [{"name": command, "command": command, "expect": expect, "expect_value": expect_value}]
        return self.go(self.project(tests), self.stand(body))

    def test_incomplete_package_of_a_failed_operation_is_its_evidence(self):
        # The controlled write fault: FAILED was expected, the partial package is evidence.
        report = self.package("full_ledger62", "failed", "FAILED", "failed", "FAILED")
        self.assertEqual((report["status"], report["exit_code"]), ("passed", 0))
        evidence = report["result_files"][0]
        self.assertEqual((evidence["complete"], evidence["operation"], evidence["package"]),
                         (False, "full_ledger62", "KUDIR4_X"))
        self.assertTrue(evidence["sha256_matches"])

    def test_incomplete_package_of_a_passed_operation_blocks(self):
        report = self.package("full", "passed", "COMPLETE", "passed", "COMPLETE")
        self.assertEqual(report["status"], "blocked")
        platform = next(s for s in report["stages"] if s["stage"] == "platform_check")
        self.assertIn("incomplete", platform["reason"])


class ProfileAndEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-long-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_parameters_are_flat_values_and_commands_keep_order(self):
        path = write_project(self.root, tests=[("b", "passed"), ("a", "passed"), ("b", "failed")])
        text = path.read_text(encoding="utf-8")
        path.write_text(text + '[platform.parameters]\nstart = "2026-01-01"\nwindow = 3\n', encoding="utf-8")
        project = load_project(path)
        self.assertEqual(project.parameters, {"start": "2026-01-01", "window": 3})
        self.assertEqual(project.commands(), ["b", "a"])
        path.write_text(text + '[platform.parameters.nested]\nx = 1\n', encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_project(path)

    def test_large_result_evidence_is_streamed(self):
        payload = b"0123456789abcdef" * 200_000  # 3.2 MB
        path = self.root / "big.csv"
        path.write_bytes(payload)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("whole file read")):
            record = file_evidence(path, root=self.root, complete=True,
                                   expected_sha256=hashlib.sha256(payload).hexdigest())
        self.assertEqual((record["size_bytes"], record["sha256_matches"], record["complete"]),
                         (len(payload), True, True))


class ReindexAllowanceTests(unittest.TestCase):
    """Task 007: extra open time used only after an interrupted 1C session."""

    def test_optional_and_counted_in_the_total(self):
        from harness77.deadlines77 import DeadlineError, Deadlines
        base = dict(open_s=120, calculation_s=3600, cancel_s=15, shutdown_s=30)
        plain = Deadlines.create(total_s=3765, **base)
        self.assertEqual((plain.reindex_s, plain.effective()["sources"]["reindex"]), (0.0, "absent"))
        with self.assertRaises(DeadlineError):  # 120 + 600 + 3600 + 15 + 30 = 4365 > 4000
            Deadlines.create(total_s=4000, reindex_s=600, **base)
        with self.assertRaises(DeadlineError):
            Deadlines.create(total_s=5000, reindex_s=-1, **base)
        allowed = Deadlines.create(total_s=4400, reindex_s=600, sources={"reindex": "project"}, **base)
        self.assertEqual((allowed.effective()["reindex_timeout_s"], allowed.effective()["phase_sum_s"]), (600, 4365))

    def test_profile_and_cli_and_the_launcher_see_it(self):
        from harness77.config77 import load_stand, resolve_deadlines
        with tempfile.TemporaryDirectory(prefix="harness77-reindex-") as temp:
            root = Path(temp)
            deadlines = {"open_timeout_s": 120, "reindex_timeout_s": 600, "calculation_timeout_s": 60,
                         "cancel_timeout_s": 15, "shutdown_timeout_s": 30, "total_timeout_s": 900}
            project = load_project(write_project(root, deadlines=deadlines))
            stand_path = root / "stand.toml"
            stand_path.write_text(chr(10).join([
                "schema_version = 1", "[stand]", 'name = "s"', 'backend = "native"', 'launcher = "x.py"',
                "[stand.paths]", 'exe = "x.exe"', "[stand.base]", 'path = "base"', 'user = "u"']) + chr(10),
                encoding="utf-8")
            stand = load_stand(stand_path)
            resolved = resolve_deadlines(project, stand)
            self.assertEqual((resolved.reindex_s, resolved.sources["reindex"]), (600, "project"))
            override = resolve_deadlines(project, stand, {"reindex_timeout_s": 300})
            self.assertEqual((override.reindex_s, override.sources["reindex"]), (300, "cli"))
            self.assertEqual(json.loads(json.dumps(override.effective()))["reindex_timeout_s"], 300)


if __name__ == "__main__":
    unittest.main()
