"""Portable contract/deadline tests, not substitutes for Windows integration."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import module_suite77 as suite
import shutdown77 as shutdown
import run_shutdown77 as runner


class ShutdownEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name).resolve()
        self.fragment, self.manifest = shutdown.prepare_shutdown(self.out, "test-run")
        (self.out / "client.vbs").write_text(self.fragment, encoding="utf-16")
        self.manifest["sources"]["client.vbs"] = shutdown.sha256(self.out / "client.vbs")
        self.lifecycle = {
            "run_id": "test-run", "shutdown_mode": shutdown.MODE, "fault": "none",
            "forced_cleanup": False, "first_chance_av_observed": False,
            "av_dump_saved": False, "diagnostic_execution_modified": False,
            "server_exit_code": 0, "helper_exit_code": 0, "debugger_exit_code": 0,
            "processes_before": [], "processes_after": [],
            "hashes_before": shutdown.PINNED.copy(), "hashes_after": shutdown.PINNED.copy(),
            "temporary_com_registration": {"removed": True, "sha256": shutdown.PINNED["helper"]},
            "server": {"pid": 77, "parent_pid": 12, "ownership_verified": True, "creation_filetime": 123},
            "debugger_pid": 12, "debugger_ready": True,
            "debugger_stops_at_first_chance_av": True, "shutdown_started_observed": True,
        }
        self.events = [{"run_id": "test-run", "name": name,
                        "value": "77" if expected == "pid" else "2" if expected == "positive" else expected}
                       for name, expected in shutdown.STEPS]

    def result(self):
        (self.out / "shutdown-events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in self.events) + "\n", encoding="utf-16")
        return shutdown.assess(self.out, self.manifest, self.lifecycle)

    def test_complete_contract(self):
        self.assertEqual(self.result()["status"], "passed")

    def test_a_built_configuration_is_judged_by_the_caller_s_pins(self):
        # Task 021: a run's copy of the base carries the configuration it built.
        built = dict(shutdown.PINNED, **{"1Cv7.MD": "b" * 64})
        self.lifecycle.update(hashes_before=dict(built), hashes_after=dict(built))
        self.assertIn("pinned binary/configuration hashes do not match", self.result()["issues"])
        (self.out / "shutdown-events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in self.events) + "\n", encoding="utf-16")
        self.assertEqual(shutdown.assess(self.out, self.manifest, self.lifecycle, pinned=built)["status"], "passed")

    def test_legacy_success_flag_is_insufficient(self):
        self.lifecycle = {"normal_shutdown_observed": True}
        self.assertEqual(self.result()["status"], "blocked")

    def test_each_step_required_ordered_once(self):
        original = copy.deepcopy(self.events)
        for index in range(len(original)):
            for change in ("missing", "duplicate", "wrong", "foreign"):
                with self.subTest(index=index, change=change):
                    self.events = copy.deepcopy(original)
                    if change == "missing":
                        self.events.pop(index)
                    elif change == "duplicate":
                        self.events.insert(index, self.events[index].copy())
                    elif change == "wrong":
                        self.events[index]["value"] = "-4"
                    else:
                        self.events[index]["run_id"] = "old-run"
                    self.assertEqual(self.result()["status"], "blocked")

    def test_reordered_events(self):
        self.events[7], self.events[8] = self.events[8], self.events[7]
        self.assertEqual(self.result()["status"], "blocked")

    def test_numeric_pid_and_boolean_exit_code_are_not_accepted(self):
        self.events[5]["value"] = 77
        self.assertEqual(self.result()["status"], "blocked")
        self.events[5]["value"] = "77"
        self.lifecycle["server_exit_code"] = False
        self.assertEqual(self.result()["status"], "blocked")

    def test_each_lifecycle_failure_blocks(self):
        original = copy.deepcopy(self.lifecycle)
        failures = {
            "run_id": "old", "fault": "com-error", "forced_cleanup": True,
            "first_chance_av_observed": True, "av_dump_saved": True,
            "diagnostic_execution_modified": True, "server_exit_code": 1,
            "helper_exit_code": 2, "debugger_exit_code": 3,
            "processes_before": [{"pid": 33}], "processes_after": [{"pid": 77}],
            "hashes_before": {}, "hashes_after": {}, "temporary_com_registration": {},
            "server": {}, "debugger_ready": False, "debugger_stops_at_first_chance_av": False,
            "shutdown_started_observed": False, "error": "I/O error",
            "registration_cleanup_error": "access denied", "cleanup_errors": ["server still alive"],
            "timeout_phase": "shutdown",
        }
        for name, value in failures.items():
            with self.subTest(name=name):
                self.lifecycle = copy.deepcopy(original)
                self.lifecycle[name] = value
                self.assertEqual(self.result()["status"], "blocked")

    def test_each_hash_is_required(self):
        for name in shutdown.PINNED:
            with self.subTest(name=name):
                self.lifecycle["hashes_after"] = shutdown.PINNED.copy()
                self.lifecycle["hashes_after"][name] = "0" * 64
                self.assertEqual(self.result()["status"], "blocked")

    def test_mismatched_com_pid(self):
        self.events[5]["value"] = "88"
        self.assertEqual(self.result()["status"], "blocked")

    def test_installer_and_client_hashes_checked(self):
        for name in ("client.vbs", "shutdown-installer.1s"):
            with self.subTest(name=name):
                path = self.out / name
                data = path.read_bytes()
                path.write_bytes(data + b"changed")
                self.assertEqual(self.result()["status"], "blocked")
                path.write_bytes(data)

    def test_missing_source_and_manifest_block(self):
        (self.out / "client.vbs").unlink()
        self.assertEqual(self.result()["status"], "blocked")
        self.manifest["sources"] = {}
        self.assertEqual(self.result()["status"], "blocked")

    def test_missing_malformed_and_denied_evidence(self):
        self.assertEqual(shutdown.assess(self.out, self.manifest, self.lifecycle)["status"], "blocked")
        (self.out / "shutdown-events.jsonl").write_text('{"run_id":', encoding="utf-16")
        self.assertEqual(shutdown.assess(self.out, self.manifest, self.lifecycle)["status"], "blocked")
        with patch.object(shutdown, "read_events", side_effect=PermissionError("denied")):
            self.assertEqual(shutdown.assess(self.out, self.manifest, self.lifecycle)["status"], "blocked")

    def test_non_object_events_block(self):
        self.events[0] = []
        self.assertEqual(self.result()["status"], "blocked")

    def test_loaded_library_cannot_be_released_in_policy(self):
        self.events[11]["value"] = "1"
        self.assertEqual(self.result()["status"], "blocked")
        # Generated client guards absence before invoking the helper's release.
        self.assertLess(self.fragment.index('ShutdownRequire "loaded_after_flush", result, 0'),
                        self.fragment.index('result = v.EvalExpr("H77Release()")'))

    def test_failed_atomic_publication_does_not_replace_prior_report(self):
        path = self.out / "run.json"
        path.write_text("old-report", encoding="utf-8")
        with patch.object(Path, "replace", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                shutdown.atomic_json(path, {"status": "passed"})
        self.assertEqual(path.read_text(encoding="utf-8"), "old-report")
        with self.assertRaises(ValueError):
            shutdown.atomic_json(path, {"time": float("nan")})
        self.assertEqual(path.read_text(encoding="utf-8"), "old-report")

    def test_full_client_hooks_and_fault_markers(self):
        client, _ = suite.prepare_client(self.out, 1, self.fragment,
                                         'ShutdownEvent "server_released", "ok"')
        self.assertLess(client.index("Set controller = Nothing"), client.index('ShutdownEvent "modules_released"'))
        self.assertLess(client.index("Set v = Nothing"), client.index('ShutdownEvent "server_released"'))
        self.assertNotIn("__AFTER_RELEASE__", client)
        for fault in ("com-error", "release-timeout"):
            _, manifest = shutdown.prepare_shutdown(self.out, "test-run", fault)
            self.assertEqual(manifest["fault"], fault)
        with self.assertRaises(ValueError):
            shutdown.prepare_shutdown(self.out, "test-run", "arbitrary")


class DeadlineTests(unittest.TestCase):
    def test_total_deadline_inclusive(self):
        limit = shutdown.Deadline(100)
        self.assertIsNone(limit.expired(244.999))
        self.assertEqual(limit.expired(245), "session")

    def test_shutdown_deadline_never_extends(self):
        limit = shutdown.Deadline(100)
        limit.observe_shutdown(105)
        limit.observe_shutdown(110)
        self.assertIsNone(limit.expired(114.999))
        self.assertEqual(limit.expired(115), "shutdown")

    def test_total_limit_still_applies_late_in_shutdown(self):
        limit = shutdown.Deadline(100)
        limit.observe_shutdown(244)
        self.assertEqual(limit.expired(245), "session")


class PreflightTests(unittest.TestCase):
    def test_output_base_overlap_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            base = root / ".local/bases/base-for-test"
            base.mkdir(parents=True)
            with patch.object(runner, "ROOT", root):
                for out in (base, base / "run", base.parent, root):
                    with self.subTest(out=out), self.assertRaisesRegex(ValueError, "overlap"):
                        runner.preflight(base, root, root, root, out)
                existing = root / "existing"
                existing.mkdir()
                with self.assertRaises(ValueError):
                    runner.preflight(base, root, root, root, existing)
                other = root / "other-base"
                other.mkdir()
                with self.assertRaisesRegex(ValueError, "only the existing"):
                    runner.preflight(other, root, root, root, root / "result")


if __name__ == "__main__":
    unittest.main()
