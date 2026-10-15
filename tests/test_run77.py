"""Full-cycle orchestration: statuses, exit codes, linkage, §8.5 behaviour.

These drive the real executor through the simulation backend with a manual
clock, so scripted long runs are instant and deterministic. The simulation
never sets platform_checked; a native run is covered separately.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from stage4_fixtures import base_scenario, run, write_project, write_sim_stand


class RunCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-run-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"

    def go(self, scenario, *, tests=(("control-42", "passed"),), screenshots=False, overrides=None, run_id=None):
        project = write_project(self.root, tests=tests)
        stand = write_sim_stand(self.root, scenario, screenshots=screenshots)
        return run(project, stand, self.runs, overrides=overrides, run_id=run_id)

    def stage(self, report, name):
        return next(s for s in report["stages"] if s["stage"] == name)

    # --- the four basic outcomes -----------------------------------------

    def test_successful_full_cycle(self):
        report = self.go(base_scenario(result_files=[]))
        self.assertEqual((report["status"], report["exit_code"]), ("passed", 0))
        self.assertFalse(report["platform_checked"])  # simulation is never a native check
        self.assertTrue(self.stage(report, "platform_check")["linkage_ok"])
        self.assertEqual({s["stage"]: s["status"] for s in report["stages"]},
                         {"static": "passed", "build": "passed",
                          "platform_check": "passed", "tests": "passed"})

    def test_compile_error_is_a_checked_code_failure(self):
        scenario = base_scenario(load={"status": "failed",
                                        "diagnostics": [{"line": 2, "message": "Ошибка в выражении"}]})
        report = self.go(scenario)
        self.assertEqual((report["status"], report["exit_code"]), ("failed", 1))
        self.assertEqual(self.stage(report, "platform_check")["status"], "failed")
        self.assertEqual(self.stage(report, "tests")["status"], "skipped")

    def test_runtime_error_fails_the_test(self):
        scenario = base_scenario(operations=[{"name": "control-42", "status": "failed",
                                              "value": None, "diagnostics": [{"line": 1, "message": "Деление на 0"}]}])
        report = self.go(scenario)
        self.assertEqual((report["status"], report["exit_code"]), ("failed", 1))
        self.assertEqual(self.stage(report, "tests")["status"], "failed")

    def test_intentionally_failing_test(self):
        # The control returns 42 but the declared test expects it to fail.
        report = self.go(base_scenario(), tests=(("control-42", "failed"),))
        self.assertEqual((report["status"], report["exit_code"]), ("failed", 1))

    def test_value_assertion_passes_and_mismatch_fails(self):
        project = write_project(self.root, tests=[{"name": "control-42", "command": "control-42",
                                                   "expect": "passed", "expect_value": "42"}])
        stand = write_sim_stand(self.root, base_scenario(result_files=[]))
        passed = run(project, stand, self.runs / "ok")
        self.assertEqual(passed["status"], "passed")
        wrong = write_project(self.root / "w", tests=[{"name": "control-42", "command": "control-42",
                                                       "expect": "passed", "expect_value": "99"}])
        stand2 = write_sim_stand(self.root / "w", base_scenario(result_files=[]))
        failed = run(wrong, stand2, self.runs / "bad")
        self.assertEqual((failed["status"], failed["exit_code"]), ("failed", 1))
        row = next(s for s in failed["stages"] if s["stage"] == "tests")["tests"][0]
        self.assertFalse(row["value_met"])

    def test_verified_expected_negative_is_success(self):
        scenario = base_scenario(operations=[{"name": "control-42", "status": "failed", "value": "0"}])
        report = self.go(scenario, tests=(("control-42", "failed"),))
        self.assertEqual((report["status"], report["exit_code"]), ("passed", 0))

    # --- infrastructure outcomes -----------------------------------------

    def test_missing_base_is_blocked_not_success(self):
        scenario = base_scenario()
        scenario["open"] = {"duration_s": 1.0, "samples": 1, "status": "missing-base"}
        report = self.go(scenario)
        self.assertEqual((report["status"], report["exit_code"]), ("blocked", 2))
        self.assertEqual(report["reason"], "database_path_missing")

    def test_stale_result_is_rejected(self):
        scenario = base_scenario()
        scenario["observed_run_id"] = "00000000-0000-0000-0000-000000000000"
        report = self.go(scenario)
        self.assertEqual((report["status"], report["exit_code"]), ("blocked", 2))
        self.assertIn("run_id", report["reason"])

    def test_foreign_ert_hash_is_rejected(self):
        scenario = base_scenario()
        scenario["observed_ert_sha256"] = "f" * 64
        report = self.go(scenario)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("ERT hash", report["reason"])

    def test_partial_result_never_passes(self):
        scenario = base_scenario(result_files=[{"name": "r.csv", "size_bytes": 10, "fill": "a", "complete": False}])
        report = self.go(scenario)
        self.assertEqual((report["status"], report["exit_code"]), ("blocked", 2))

    def test_result_write_error(self):
        scenario = base_scenario(result_files=[{"name": "r.csv", "size_bytes": 10, "write_error": True}])
        report = self.go(scenario)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(self.stage(report, "platform_check")["reason"], "artifact_write_error")

    # --- section 8.5: long runs, large results, timeout, cancel ----------

    def test_long_quiet_run_with_large_verified_result(self):
        size = 3_000_000
        digest = hashlib.sha256(("a" * size).encode("latin-1")).hexdigest()
        scenario = base_scenario(duration_s=3600.0, samples=60,
                                 result_files=[{"name": "ledger.csv", "size_bytes": size, "fill": "a",
                                                "complete": True, "expected_sha256": digest}])
        report = self.go(scenario, overrides={"calculation_timeout_s": 7200, "total_timeout_s": 8000})
        self.assertEqual(report["status"], "passed")
        evidence = report["result_files"][0]
        self.assertEqual(evidence["size_bytes"], size)
        self.assertTrue(evidence["sha256_matches"])
        self.assertEqual(self.stage(report, "platform_check")["phase_durations_s"]["calculation"], 3600.0)

    def test_large_result_hash_mismatch_is_blocked(self):
        scenario = base_scenario(result_files=[{"name": "r.csv", "size_bytes": 100, "fill": "a",
                                                "complete": True, "expected_sha256": "deadbeef"}])
        report = self.go(scenario)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["result_files"][0]["sha256_matches"])

    def test_calculation_timeout(self):
        scenario = base_scenario(duration_s=600.0, samples=60,
                                 result_files=[{"name": "r.csv", "size_bytes": 10, "fill": "a", "complete": True}])
        report = self.go(scenario, overrides={"calculation_timeout_s": 120, "total_timeout_s": 1000})
        self.assertEqual((report["status"], report["exit_code"]), ("blocked", 2))
        self.assertEqual(report["timeout_phase"], "calculation")
        self.assertEqual(report["reason"], "calculation_timeout")
        self.assertFalse(report["result_files"][0]["complete"])

    def test_user_cancel_during_calculation(self):
        scenario = base_scenario(duration_s=600.0, samples=60, cancel_at_s=120.0,
                                 result_files=[{"name": "r.csv", "size_bytes": 10, "fill": "a", "complete": True}])
        report = self.go(scenario, overrides={"calculation_timeout_s": 7200, "total_timeout_s": 8000})
        self.assertEqual((report["status"], report["exit_code"]), ("blocked", 2))
        self.assertTrue(report["cancelled"])
        self.assertEqual(report["reason"], "cancelled")
        self.assertFalse(report["result_files"][0]["complete"])

    # --- recovery, linkage and secrecy -----------------------------------

    def test_fresh_run_after_failure(self):
        first = self.go(base_scenario(load={"status": "failed", "diagnostics": []}))
        second = self.go(base_scenario(result_files=[]))
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertNotEqual(first["run_dir"], second["run_dir"])
        self.assertEqual(first["status"], "failed")
        self.assertEqual(second["status"], "passed")

    def test_each_run_has_its_own_directory_and_artifact(self):
        report = self.go(base_scenario(result_files=[]), run_id="fixed-run-id")
        run_dir = Path(report["run_dir"])
        self.assertEqual(run_dir.name, "fixed-run-id")
        self.assertTrue((run_dir / "run.json").is_file())
        self.assertTrue((run_dir / "build" / "t.ert").is_file())
        self.assertEqual(report["artifact"]["sha256"], self.stage(report, "build")["ert_sha256"])

    def test_report_has_no_credentials(self):
        report = self.go(base_scenario(result_files=[]))
        blob = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("ВВВ", blob)  # user name not echoed
        self.assertIn("credential_source", json.dumps(report["platform"], ensure_ascii=False))

    def test_zero_tests_blocks_full_cycle(self):
        report = self.go(base_scenario(result_files=[]), tests=())
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(self.stage(report, "tests")["status"], "blocked")

    def test_screenshots_attached_on_failure(self):
        scenario = base_scenario(duration_s=600.0, samples=60,
                                 result_files=[{"name": "r.csv", "size_bytes": 10, "fill": "a", "complete": True}])
        scenario["screenshots"] = {"own_pid": 11, "desktop": "harness77_sim", "size_bytes": 40,
                                   "windows": [{"hwnd": 5, "pid": 11, "tid": 2, "class": "#32770",
                                                "text": "warn", "desktop": "harness77_sim"},
                                               {"hwnd": 6, "pid": 999, "desktop": "harness77_sim"}]}
        report = self.go(scenario, screenshots=True,
                         overrides={"calculation_timeout_s": 120, "total_timeout_s": 1000})
        shots = report["screenshots"]
        self.assertEqual(len(shots), 2)
        self.assertTrue(shots[0]["captured"])
        self.assertFalse(shots[1]["captured"])  # foreign process refused
        self.assertIn("another process", shots[1]["error"])


if __name__ == "__main__":
    unittest.main()
