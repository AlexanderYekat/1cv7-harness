"""Portable evidence tests; native ERT loading is checked separately."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ert_probe77 import read_results
from shutdown77 import sha256


class ErtEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name).resolve()
        artifact = self.out / "sample.ert"
        artifact.write_bytes(b"placeholder: validator tests do not load a native ERT")
        self.manifest = {"run_id": "new-run", "identity": "new-run:ok", "case": "ok",
            "ert_path": str(artifact), "sources": {artifact.name: sha256(artifact)},
            "commands": ["check", "execute"], "expected_error_line": None}
        self.lifecycle = {"run_id": "new-run", "private_desktop": "test-private", "desktop_closed": True}
        self.shutdown = {"status": "passed"}
        self.events = []
        for name in ("base", "controller"):
            self.event("phase", name, "ok")
        for name in ("check", "execute"):
            actual = "selected:" + str(artifact) + "\nopen-return:0\nloaded:new-run:ok\n"
            if name == "execute":
                actual += "value:42\n"
            actual += "completed:new-run:ok\n"
            self.event("ert", name, actual)
            self.protocol(name)
        self.event("complete", "ert", "done")

    def event(self, kind, name, value):
        self.events.append({"run_id": "new-run", "kind": kind, "name": name, "value": value, "elapsed_ms": 1})

    def protocol(self, name, middle=""):
        marker = self.manifest["run_id"] + ":" + name
        (self.out / (name + ".txt")).write_text("HARNESS77-BEGIN:" + marker + "\n" + middle + "HARNESS77-END:" + marker, encoding="cp1251")

    def result(self):
        (self.out / "ert-events.jsonl").write_text("\n".join(json.dumps(e) for e in self.events), encoding="utf-16")
        return read_results(self.out, self.manifest, self.lifecycle, self.shutdown)

    def test_success_requires_both_loading_and_execution(self):
        self.assertEqual(self.result()["status"], "passed")
        self.events[3]["value"] = self.events[2]["value"]
        self.assertEqual(self.result()["status"], "failed")

    def test_zero_open_result_alone_is_not_success(self):
        self.events[2]["value"] = "selected:" + self.manifest["ert_path"] + "\nopen-return:0"
        self.assertEqual(self.result()["status"], "blocked")

    def test_empty_actual_and_foreign_identity_block(self):
        saved = self.events[2]["value"]
        for value in ("", saved.replace("new-run:ok", "old-run:ok"), saved.replace("selected:", "wrong:")):
            with self.subTest(value=value):
                self.events[2]["value"] = value
                self.assertEqual(self.result()["status"], "blocked")

    def test_syntax_error_has_visible_failed_operation(self):
        self.manifest.update(case="syntax", expected_error_line=2)
        for index, name in ((2, "check"), (3, "execute")):
            self.events[index]["value"] = "selected:" + self.manifest["ert_path"] + "\nopen-error:compile failed"
            self.protocol(name, "{sample.ert(2)}: Ожидается выражение\n")
        result = self.result()
        self.assertEqual(result["status"], "passed")
        self.assertTrue(all(row["status"] == "failed" for row in result["operations"]))
        self.protocol("check", "{sample.ert(9)}: Другая ошибка\n")
        self.assertEqual(self.result()["status"], "blocked")

    def test_runtime_error_is_separate_from_check(self):
        self.manifest["case"] = "runtime"
        self.events[3]["value"] = self.events[3]["value"].replace("value:42", "runtime-error:Деление на 0")
        result = self.result()
        self.assertEqual(result["status"], "passed")
        self.assertEqual([r["status"] for r in result["operations"]], ["passed", "failed"])

    def test_old_or_partial_events_block(self):
        self.events[2]["run_id"] = "previous-run"
        self.assertEqual(self.result()["status"], "blocked")
        self.events.pop()
        self.assertEqual(self.result()["status"], "blocked")

    def test_duplicate_or_unexpected_events_block(self):
        self.events.append(self.events[2])
        self.assertEqual(self.result()["status"], "blocked")

    def test_old_empty_and_duplicate_protocols_block(self):
        for data in ("", "old protocol", "HARNESS77-BEGIN:new-run:check\nHARNESS77-BEGIN:new-run:check\nHARNESS77-END:new-run:check"):
            (self.out / "check.txt").write_text(data, encoding="cp1251")
            self.assertEqual(self.result()["status"], "blocked")

    def test_changed_artifact_blocks(self):
        (self.out / "sample.ert").write_bytes(b"changed")
        self.assertEqual(self.result()["status"], "blocked")

    def test_bad_shutdown_and_desktop_cleanup_block(self):
        self.shutdown["status"] = "blocked"
        self.assertEqual(self.result()["status"], "blocked")
        self.shutdown["status"] = "passed"
        self.lifecycle["desktop_closed"] = False
        self.assertEqual(self.result()["status"], "blocked")

    def test_nan_timing_blocks(self):
        self.events[2]["elapsed_ms"] = float("nan")
        self.assertEqual(self.result()["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
