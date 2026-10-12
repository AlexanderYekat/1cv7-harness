import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qualify_recovery77 import semantic_result


class SemanticTests(unittest.TestCase):
    def fixture(self, run_id="fresh", path="C:/fresh/test.ert"):
        manifest = {"run_id": run_id, "ert_path": path}
        report = {"run_id": run_id, "pid": 123, "elapsed_seconds": 1,
            "ert": {"operations": [{"name": "execute", "status": "passed", "expectation_met": True,
                "actual": "selected:" + path + "\nloaded:" + run_id + ":ok\nvalue:42\n",
                "protocol": "HARNESS77-BEGIN:" + run_id + ":execute\nHARNESS77-END:" + run_id + ":execute",
                "diagnostics": []}]}}
        return report, manifest

    def test_only_run_identity_path_and_external_timing_vary(self):
        first, manifest = self.fixture()
        second, new_manifest = self.fixture("other", "C:/other/test.ert")
        second.update(pid=999, elapsed_seconds=20)
        self.assertEqual(semantic_result(first, manifest), semantic_result(second, new_manifest))

    def test_value_diagnostic_or_operation_changes_are_preserved(self):
        original, manifest = self.fixture()
        for key, value in (("actual", "value:43"), ("status", "failed"), ("expectation_met", False),
                           ("diagnostics", [{"line": 6, "message": "error"}]), ("protocol", "partial")):
            changed = copy.deepcopy(original)
            changed["ert"]["operations"][0][key] = value
            with self.subTest(key=key):
                self.assertNotEqual(semantic_result(original, manifest), semantic_result(changed, manifest))

    def test_compiler_uppercase_path_is_equivalent_but_other_paths_are_not(self):
        first, manifest = self.fixture(path="C:/Fresh/Проверка syntax.ert")
        second = copy.deepcopy(first)
        first["ert"]["operations"][0]["protocol"] = "{" + manifest["ert_path"] + "(2)}: error"
        second["ert"]["operations"][0]["protocol"] = "{" + manifest["ert_path"].upper() + "(2)}: error"
        self.assertEqual(semantic_result(first, manifest), semantic_result(second, manifest))
        second["ert"]["operations"][0]["protocol"] = "{C:/other.ert(2)}: error"
        self.assertNotEqual(semantic_result(first, manifest), semantic_result(second, manifest))


if __name__ == "__main__":
    unittest.main()
