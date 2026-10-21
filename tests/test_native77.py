"""Native backend contract via a fake launcher; no 1C is started.

These validate how the native backend validates the stand, invokes a launcher,
re-evidences result files from disk and refuses to infer a clean shutdown. The
real 1C run is the native acceptance and is out of scope for a portable test.
"""

import hashlib
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from stage4_fixtures import run, windows_only, write_project

LAUNCHER = textwrap.dedent('''
    import argparse, hashlib, json
    from pathlib import Path
    parser = argparse.ArgumentParser()
    for name in ("--run-dir", "--ert", "--ert-sha256", "--run-id", "--base", "--user",
                 "--exe", "--result", "--deadlines-json", "--cdb", "--helper", "--identity"):
        parser.add_argument(name)
    parser.add_argument("--screenshots", action="store_true")
    args, _ = parser.parse_known_args()
    run_dir = Path(args.run_dir)
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    payload = b"R" * 128
    (run_dir / "results" / "report.csv").write_bytes(payload)
    out = {"run_id": args.run_id, "ert_sha256": args.ert_sha256, "platform_checked": True,
           "status": "__STATUS__", "reason": None, "cancelled": False, "timeout_phase": None,
           "load": {"status": "passed", "diagnostics": []},
           "operations": [{"name": "control-42", "status": "passed", "value": "42"}],
           "result_files": [{"path": "results/report.csv", "sha256": hashlib.sha256(payload).hexdigest(),
                             "complete": True}],
           "phase_durations_s": {"open": 1.0, "calculation": 2.0, "shutdown": 1.0},
           "shutdown": {"status": "ok", "cleanup_verified": __CLEANUP__, "server_exit_code": 0,
                        "others_preserved": True},
           "platform_identity": {"platform_version": "7.70.027-fake"}}
    Path(args.result).write_text(json.dumps(out), encoding="utf-8")
''')


class NativeBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-nat-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base-for-test"
        self.base.mkdir()
        self.project = write_project(self.root)

    def stand(self, *, launcher_body=None, launcher="auto", exe=None, base=None):
        if launcher == "auto":
            path = self.root / "launcher.py"
            path.write_text(launcher_body, encoding="utf-8")
            launcher = path.as_posix()
        exe = (exe or Path(sys.executable)).as_posix() if not isinstance(exe, str) else exe
        base = (base or self.base).as_posix() if not isinstance(base, str) else base
        text = "\n".join([
            "schema_version = 1", "[stand]", 'name = "native"', 'backend = "native"',
            f'launcher = "{launcher}"', "[stand.paths]", f'exe = "{exe}"',
            "[stand.base]", f'path = "{base}"', 'user = "ВВВ"']) + "\n"
        path = self.root / "stand.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def go(self, stand):
        from harness77.deadlines77 import Clock
        return run(self.project, stand, self.root / "runs", clock=Clock())

    @windows_only
    def test_clean_native_run_is_checked_and_passes(self):
        report = self.go(self.stand(launcher_body=LAUNCHER.replace("__STATUS__", "passed").replace("__CLEANUP__", "True")))
        self.assertEqual((report["status"], report["exit_code"]), ("passed", 0))
        self.assertTrue(report["platform_checked"])
        self.assertTrue(report["result_files"][0]["sha256_matches"])

    @windows_only
    def test_unverified_shutdown_blocks_even_if_status_passed(self):
        report = self.go(self.stand(launcher_body=LAUNCHER.replace("__STATUS__", "passed").replace("__CLEANUP__", "False")))
        self.assertEqual(report["status"], "blocked")
        self.assertIn("shutdown", report["reason"])

    @windows_only
    def test_missing_result_file_blocks(self):
        body = "import sys\nsys.exit(0)\n"  # launcher writes no platform-result.json
        report = self.go(self.stand(launcher_body=body))
        self.assertEqual(report["status"], "blocked")
        self.assertIn("no platform-result.json", report["reason"])

    def test_off_stand_preflight_blocks_without_launcher(self):
        report = self.go(self.stand(launcher_body="pass\n", exe="C:/nonexistent/1cv7l.exe"))
        self.assertEqual(report["status"], "blocked")
        self.assertIn("native_preflight", report["reason"])
        self.assertFalse(report["platform_checked"])


if __name__ == "__main__":
    unittest.main()
