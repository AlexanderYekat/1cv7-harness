"""Evidence validation tests; none of these start 1C or replace native probes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import module_suite77 as suite


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name).resolve()
        _, self.manifest = suite.prepare_client(self.out, 1000)
        self.lifecycle = {"normal_shutdown_observed": True, "elapsed_seconds": 8.0}
        self.events = []
        for name, (expected, _) in suite.CASES.items():
            value = (f"error|({expected})Возврат <<?>>;\tОжидается выражение"
                     if isinstance(expected, int) else "42" if name.startswith("value_") else expected)
            self.event("case", name, value)
            if name.startswith("compile_"):
                marker = self.manifest["run_id"] + ":" + name
                (self.out / (name + ".txt")).write_text(
                    "HARNESS77-BEGIN:" + marker + "\nHARNESS77-END:" + marker + "\n", encoding="cp1251")
        for name in suite.PHASES:
            self.event("phase", name, "ok")
        for name in suite.BATCHES:
            self.event("batch", name, "ok")
        self.event("complete", "suite", "done")

    def event(self, kind, name, value):
        self.events.append({"run_id": self.manifest["run_id"], "kind": kind, "name": name,
                            "value": value, "elapsed_ms": 15.625})

    def result(self):
        (self.out / "suite-events.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in self.events) + "\n", encoding="utf-16")
        return suite.read_results(self.out, self.manifest, self.lifecycle)

    def test_expected_assertion_failure_is_visible(self):
        result = self.result()
        self.assertEqual(result["status"], "passed")
        failure = next(c for c in result["cases"] if c["name"] == "value_wrong")
        self.assertEqual(failure["status"], "failed")
        self.assertTrue(failure["expectation_met"])
        self.assertEqual(failure["expected_value"], 43)
        self.assertEqual(failure["actual"], "42")

    def test_incorrect_function_result_is_not_accepted(self):
        next(e for e in self.events if e["name"] == "value_correct")["value"] = "41"
        self.assertEqual(self.result()["status"], "failed")

    def test_unrelated_compile_error_is_not_accepted(self):
        next(e for e in self.events if e["name"] == "compile_syntax")["value"] = "error|class not registered"
        self.assertEqual(self.result()["status"], "failed")

    def test_wrong_error_line_is_not_accepted(self):
        next(e for e in self.events if e["name"] == "compile_unused")["value"] = "error|(2)wrong location"
        self.assertEqual(self.result()["status"], "failed")

    def test_foreign_run_is_blocked(self):
        self.events[0]["run_id"] = "old-run"
        self.assertEqual(self.result()["status"], "blocked")

    def test_duplicate_and_missing_events_are_blocked(self):
        self.events[-1] = self.events[0].copy()
        self.assertEqual(self.result()["status"], "blocked")

    def test_failure_after_results_blocks_suite(self):
        self.lifecycle["normal_shutdown_observed"] = False
        result = self.result()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(len(result["cases"]), 7)

    def test_diagnostic_intervention_is_not_acceptance(self):
        self.lifecycle["diagnostic_execution_modified"] = True
        result = self.result()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["test_expectations_met"])

    def test_modified_shutdown_requires_its_own_contract(self):
        self.lifecycle["shutdown_execution_modified"] = True
        result = self.result()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["test_expectations_met"])

    def test_cleanup_runs_after_module_release_before_server_release(self):
        client, _ = suite.prepare_client(self.out, 1, 'Log "cleanup-marker"')
        marker = client.index('Log "cleanup-marker"')
        self.assertLess(client.index("Set controller = Nothing"), marker)
        self.assertLess(client.rindex("Set target = Nothing"), marker)
        self.assertLess(marker, client.index("Set v = Nothing"))
        self.assertNotIn("__BEFORE_RELEASE__", client)
        ordinary, _ = suite.prepare_client(self.out, 1)
        self.assertNotIn("cleanup-marker", ordinary)
        self.assertNotIn("__BEFORE_RELEASE__", ordinary)

    def test_native_protocol_supplies_error_line(self):
        for name, line in (("compile_syntax", 2), ("compile_unused", 5)):
            next(e for e in self.events if e["name"] == name)["value"] = "return|0"
            marker = self.manifest["run_id"] + ":" + name
            (self.out / (name + ".txt")).write_text(
                "HARNESS77-BEGIN:" + marker + "\r\nА =<<?>> ;\r\n{(" + str(line)
                + ")}: Ожидается выражение\r\nHARNESS77-END:" + marker, encoding="cp1251")
        self.assertEqual(self.result()["status"], "passed")

    def test_foreign_protocol_is_blocked(self):
        (self.out / "compile_valid.txt").write_text("HARNESS77-BEGIN:old\nHARNESS77-END:old", encoding="cp1251")
        self.assertEqual(self.result()["status"], "blocked")

    def test_reversed_protocol_markers_are_blocked(self):
        marker = self.manifest["run_id"] + ":compile_valid"
        (self.out / "compile_valid.txt").write_text(
            "HARNESS77-END:" + marker + "\nHARNESS77-BEGIN:" + marker, encoding="cp1251")
        self.assertEqual(self.result()["status"], "blocked")

    def test_modified_source_blocks_suite(self):
        (self.out / "valid.1s").write_text("changed", encoding="utf-8")
        self.assertEqual(self.result()["status"], "blocked")

    def test_incomplete_json_blocks_suite(self):
        (self.out / "suite-events.jsonl").write_text('{"run_id":', encoding="utf-16")
        self.assertEqual(suite.read_results(self.out, self.manifest, self.lifecycle)["status"], "blocked")

    def test_invalid_timings_are_blocked(self):
        self.events[0]["elapsed_ms"] = float("nan")
        self.assertEqual(self.result()["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
