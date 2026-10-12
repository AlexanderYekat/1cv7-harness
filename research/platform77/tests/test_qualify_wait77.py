"""Recovery is a predeclared sequence, never retries until success."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qualify_wait77 as qualification
from shutdown77 import PINNED, atomic_json


def report(case="ok"):
    return {"run_id": str(uuid.uuid4()), "case": case,
        "status": "blocked" if case == "wait" else "passed", "ert": {"timeout_verified": case == "wait"},
        "cleanup_verified": True, "desktop_closed": True, "cleanup_errors": [],
        "first_chance_av_observed": False, "av_dump_saved": False, "forced_cleanup": False,
        "hashes_before": PINNED, "hashes_after": PINNED,
        "server_exit_code": 0, "helper_exit_code": 0, "debugger_exit_code": 0,
        "identity_observer_profile": qualification.DEFAULT_OBSERVER,
        "shutdown_timeout_seconds": 10, "ert_operation_timeout_seconds": 30, "timeout_seconds": 145}


class QualificationTests(unittest.TestCase):
    def setUp(self):
        # Concurrent identity validation has its own adversarial tests. Here
        # isolate sequence/deadline policy from the detailed native evidence.
        self.guard = patch.object(qualification, "concurrency_issues", return_value=[])
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_fresh_uuid_required_even_when_every_result_passed(self):
        value = report()
        self.assertTrue(qualification.expectation_met(value, 0, "ok", set()))
        self.assertFalse(qualification.expectation_met(value, 0, "ok", {value["run_id"]}))
        for run_id in (None, "", "old", 7):
            self.assertFalse(qualification.expectation_met(dict(value, run_id=run_id), 0, "ok", set()))

    def test_wait_is_accepted_only_as_verified_blocked_exit_two(self):
        value = report("wait")
        self.assertTrue(qualification.expectation_met(value, 2, "wait", set()))
        for code, status, verified in ((0, "passed", True), (2, "blocked", False), (1, "blocked", True)):
            changed = dict(value, status=status, ert={"timeout_verified": verified})
            self.assertFalse(qualification.expectation_met(changed, code, "wait", set()))

    def test_cleanup_errors_wrong_case_or_larger_deadlines_block(self):
        value = report()
        for key, replacement in (("forced_cleanup", True), ("error", "timeout"), ("cleanup_errors", ["failed"]),
                ("helper_exit_code", False), ("case", "syntax"), ("identity_observer_profile", "continuous-v1"),
                ("shutdown_timeout_seconds", 20), ("ert_operation_timeout_seconds", 40), ("timeout_seconds", 200)):
            with self.subTest(key=key):
                self.assertFalse(qualification.expectation_met(dict(value, **{key: replacement}), 0, "ok", set()))

    def sequence(self, fail_at=None, duplicate_at=None):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "sequence"
            emitted = []

            def run(command):
                planned = json.loads((out / "qualification.json").read_text(encoding="utf-8"))
                self.assertEqual(len(planned["planned_runs"]), 9)
                case = command[command.index("--case") + 1]
                destination = Path(command[command.index("--output") + 1])
                destination.mkdir(parents=True)
                value = report(case)
                if len(emitted) == fail_at:
                    value["forced_cleanup"] = True
                if len(emitted) == duplicate_at:
                    value["run_id"] = emitted[0]["run_id"]
                emitted.append(copy.deepcopy(value))
                atomic_json(destination / "run.json", value)
                return 2 if case == "wait" else 0

            args = ["--user", "test", "--cycles", "3", "--output", str(out)]
            for name in ("base", "exe", "cdb", "com-cleanup-dll", "identity-dll"):
                args.extend(["--" + name, temporary])
            with patch.object(qualification, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
                code = qualification.main(args)
            return code, json.loads((out / "qualification.json").read_text(encoding="utf-8")), emitted

    def test_three_consecutive_cycles_all_required(self):
        code, result, emitted = self.sequence()
        self.assertEqual(code, 0)
        self.assertTrue(result["complete"])
        self.assertEqual([r["case"] for r in emitted], ["ok", "wait", "ok"] * 3)

    def test_stop_first_failure_without_retry_or_recovery_attempt(self):
        code, result, emitted = self.sequence(fail_at=1)
        self.assertEqual(code, 2)
        self.assertFalse(result["complete"])
        self.assertEqual(len(emitted), 2)

    def test_reused_uuid_stops_recovery(self):
        code, result, emitted = self.sequence(duplicate_at=2)
        self.assertEqual(code, 2)
        self.assertFalse(result["complete"])
        self.assertEqual(len(emitted), 3)


if __name__ == "__main__":
    unittest.main()
