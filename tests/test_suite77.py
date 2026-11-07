"""Task 029: real simulated cycles, durable linkage, cancellation and JUnit semantics."""

import contextlib
import dataclasses
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET

from harness77 import cli, mcp77, run77, suite77
from harness77.config77 import ConfigError, load_stand
from harness77.report77 import atomic_json, sha256_file
from stage4_fixtures import base_scenario, write_project, write_sim_stand


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h77-suite-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = write_project(self.root / "project")
        self.stand_path = write_sim_stand(self.root, base_scenario())
        self.stand = load_stand(self.stand_path)
        self.manifest = self.root / "suite.toml"
        self.output = self.root / "output"

    def profile(self, items=None, name="Формы & ссылки"):
        items = items if items is not None else [("первый", self.project), ("второй", self.project)]
        text = f'schema_version = 1\n[suite]\nid = {json.dumps(name, ensure_ascii=False)}\n'
        for identifier, path in items:
            text += '\n[[scenarios]]\nid = ' + json.dumps(identifier, ensure_ascii=False)
            text += '\nproject = ' + json.dumps(str(path).replace('\\', '/'), ensure_ascii=False) + '\n'
        if not items:
            text = 'schema_version = 1\nscenarios = []\n[suite]\nid = "empty"\n'
        self.manifest.write_text(text, encoding="utf-8")
        return suite77.load_suite(self.manifest)

    def go(self, profile=None, **kwargs):
        return suite77.execute(profile or self.profile(), self.stand, output_root=self.output, **kwargs)

    def xml(self, report):
        folder = Path(report["suite_dir"])
        self.assertEqual(json.loads((folder / "suite.json").read_text(encoding="utf-8")), report)
        self.assertEqual(sha256_file(folder / "junit.xml"), report["junit"]["sha256"])
        root = ET.parse(folder / "junit.xml").getroot()
        expected = {"tests": str(len(report["scenarios"])), "failures": str(report["counts"]["failed"]),
                    "errors": str(report["counts"]["blocked"]), "skipped": str(report["counts"]["skipped"])}
        for key, value in expected.items():
            self.assertEqual(root.get(key), value)
            self.assertEqual(root.find("testsuite").get(key), value)
        return root.findall("testsuite/testcase")

    def test_two_cycles_have_distinct_artifacts_and_linked_reports(self):
        report = self.go(self.profile([("один", Path("project/project.toml")), ("два", self.project)]))
        self.assertEqual((report["status"], report["exit_code"], report["complete"]), ("passed", 0, True))
        self.assertEqual(report["counts"], {"passed": 2, "failed": 0, "blocked": 0, "skipped": 0})
        rows = report["scenarios"]
        self.assertEqual(len({r["run_id"] for r in rows}), 2)
        for row in rows:
            path = Path(report["suite_dir"]) / row["report"]["path"]
            self.assertTrue(path.resolve().is_relative_to(self.output / "runs"))
            self.assertEqual(sha256_file(path), row["report"]["sha256"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["run_id"], row["run_id"])
            self.assertTrue((path.parent / "build/t.ert").is_file())
            self.assertFalse(row["platform_checked"])
        cases = self.xml(report)
        self.assertEqual([c.get("name") for c in cases], ["один", "два"])
        self.assertTrue(all(c.find("failure") is None and c.find("error") is None for c in cases))

    def test_failure_continues_and_expected_negative_passes(self):
        wrong = write_project(self.root / "wrong", tests=[{"name": "wrong", "command": "control-42",
                                                            "expect": "passed", "expect_value": "99"}])
        negative = write_project(self.root / "negative", tests=(("control-42", "failed"),))
        # One operation fails; an explicit expectation turns it into a passed full cycle.
        (self.root / "scenario.json").write_text(json.dumps(base_scenario(
            operations=[{"name": "control-42", "status": "failed", "value": "0"}])), encoding="utf-8")
        report = self.go(self.profile([("wrong", wrong), ("negative", negative)]))
        self.assertEqual((report["status"], report["exit_code"]), ("failed", 1))
        cases = self.xml(report)
        self.assertIsNotNone(cases[0].find("failure"))
        self.assertIsNone(cases[1].find("failure"))
        self.assertEqual(report["scenarios"][1]["status"], "passed")

    def test_project_error_is_an_error_and_next_scenario_runs(self):
        report = self.go(self.profile([("missing", self.root / "missing.toml"), ("ok", self.project)]))
        self.assertEqual((report["status"], report["exit_code"]), ("blocked", 2))
        self.assertEqual([r["status"] for r in report["scenarios"]], ["blocked", "passed"])
        self.assertIsNone(report["scenarios"][0]["run_id"])
        self.assertIsNotNone(self.xml(report)[0].find("error"))

    def test_missing_template_blocks_only_its_scenario(self):
        bad = write_project(self.root / "bad")
        (bad.parent / "form.ert").unlink()
        report = self.go(self.profile([("bad", bad), ("ok", self.project)]))
        self.assertEqual([r["status"] for r in report["scenarios"]], ["blocked", "passed"])
        self.xml(report)

    def test_invalid_manifest_never_starts_a_cycle(self):
        for items in ([], [("dup", self.project), ("DUP", self.project)], [("", self.project)]):
            with self.subTest(items=items), self.assertRaises(ConfigError):
                self.profile(items)
        self.manifest.write_text('schema_version=1\n[suite]\nid="x"\n[[scenarios]]\nid="a"\n'
                                 'project="x"\ntimeout=1\n', encoding="utf-8")
        with self.assertRaises(ConfigError):
            suite77.load_suite(self.manifest)
        self.assertFalse(self.output.exists())

    def test_output_is_new_and_identifier_cannot_escape(self):
        profile = self.profile()
        for identifier in ("../elsewhere", "C:/elsewhere", ".", "", "runs", "RUNS"):
            with self.subTest(identifier=identifier), self.assertRaises(ConfigError):
                self.go(profile, suite_id=identifier)
        self.go(profile, suite_id="fixed")
        with self.assertRaises(FileExistsError):
            self.go(profile, suite_id="fixed")

    def test_cancellation_before_start_marks_every_scenario_skipped(self):
        cancel = threading.Event()
        cancel.set()
        report = self.go(cancel=cancel, runner=lambda *a, **k: self.fail("runner started"))
        self.assertEqual((report["exit_code"], report["cancelled"]), (2, True))
        self.assertTrue(all(c.find("skipped") is not None for c in self.xml(report)))

    def test_cancellation_during_cycle_keeps_current_report_and_skips_rest(self):
        scenario = base_scenario(duration_s=60, samples=6, cancel_at_s=1)
        (self.root / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
        report = self.go()
        self.assertTrue(report["cancelled"])
        self.assertEqual([r["status"] for r in report["scenarios"]], ["blocked", "skipped"])
        self.assertIsNotNone(report["scenarios"][0]["report"])
        self.assertIsNone(report["scenarios"][1]["run_id"])
        self.xml(report)

    def test_late_cancellation_cannot_leave_an_all_green_junit(self):
        cancel = threading.Event()
        def runner(*args, **kwargs):
            result = run77.execute(*args, **kwargs)
            cancel.set()
            return result
        report = self.go(self.profile([("only", self.project)]), cancel=cancel, runner=runner)
        self.assertEqual((report["exit_code"], report["cancelled"]), (2, True))
        self.assertIsNotNone(self.xml(report)[0].find("error"))

    def test_deadline_overrides_apply_to_each_cycle(self):
        def runner(project, stand, deadlines, **kwargs):
            self.assertEqual(deadlines.calculation_s, 777)
            return run77.execute(project, stand, deadlines, **kwargs)
        report = self.go(overrides={"calculation_timeout_s": 777, "total_timeout_s": 1000}, runner=runner)
        self.assertEqual(report["counts"]["passed"], 2)
        self.xml(report)

    def test_blocked_takes_precedence_over_a_test_failure(self):
        wrong = write_project(self.root / "wrong-precedence", tests=(("control-42", "failed"),))
        report = self.go(self.profile([("failure", wrong), ("error", self.root / "missing.toml"),
                                       ("success", self.project)]))
        self.assertEqual((report["exit_code"], report["status"]), (2, "blocked"))
        self.assertEqual(report["counts"], {"passed": 1, "failed": 1, "blocked": 1, "skipped": 0})
        self.xml(report)

    def test_existing_cancel_file_blocks_before_output_creation(self):
        self.profile()
        cancel_file = self.root / "cancel"
        cancel_file.touch()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["suite", "--suite", str(self.manifest), "--stand", str(self.stand_path),
                             "--output-root", str(self.output), "--cancel-file", str(cancel_file)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err.getvalue())["status"], "blocked")
        self.assertFalse(self.output.exists())

    def test_initial_checkpoint_exists_before_first_run(self):
        def runner(*args, **kwargs):
            folder = self.output / "checkpoint"
            checkpoint = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
            self.assertFalse(checkpoint["complete"])
            self.assertEqual(checkpoint["exit_code"], 2)
            ET.parse(folder / "junit.xml")
            return run77.execute(*args, **kwargs)
        self.xml(self.go(runner=runner, suite_id="checkpoint"))

    def test_child_paths_do_not_grow_with_suite_id_and_other_suites_are_preserved(self):
        first = self.go(suite_id="short")
        saved = (Path(first["suite_dir"]) / "suite.json").read_bytes()
        second = self.go(suite_id="long-" + "x" * 120)
        paths = [Path(r["runs_dir"]) for r in (first, second)]
        self.assertEqual(paths, [self.output / "runs"] * 2)
        all_ids = [row["run_id"] for report in (first, second) for row in report["scenarios"]]
        self.assertEqual(len(set(all_ids)), 4)
        self.assertEqual((Path(first["suite_dir"]) / "suite.json").read_bytes(), saved)
        self.xml(first)
        self.xml(second)

    def test_absent_foreign_or_changed_run_report_stops_the_suite(self):
        for mutation in ("absent", "foreign", "different", "exception"):
            calls = []
            def runner(*args, **kwargs):
                calls.append(kwargs["run_id"])
                if mutation == "exception":
                    raise RuntimeError("unknown session state")
                result = run77.execute(*args, **kwargs)
                path = Path(result["run_dir"]) / "run.json"
                if mutation == "absent":
                    path.unlink()
                elif mutation == "foreign":
                    result["run_id"] = "old-run"
                    atomic_json(path, result)
                else:
                    atomic_json(path, dict(result, status="failed"))
                return result
            with self.subTest(mutation=mutation):
                report = self.go(runner=runner)
                self.assertEqual(len(calls), 1)
                self.assertEqual([r["status"] for r in report["scenarios"]], ["blocked", "skipped"])
                self.xml(report)

    def test_unverified_native_cleanup_stops_and_clean_failure_continues(self):
        simulation = self.stand
        self.stand = dataclasses.replace(simulation, backend="native")
        for clean in (False, True):
            def runner(project, stand, deadlines, **kwargs):
                result = run77.execute(project, simulation, deadlines, **kwargs)
                result["shutdown"] = {"cleanup_verified": clean, "others_preserved": True}
                result.update(status="failed", exit_code=1, reason="test failure")
                atomic_json(Path(result["run_dir"]) / "run.json", result)
                return result
            with self.subTest(clean=clean):
                report = self.go(runner=runner)
                self.assertEqual([r["status"] for r in report["scenarios"]],
                                 ["failed", "failed"] if clean else ["blocked", "skipped"])
                self.xml(report)

    def test_copy_cleanup_and_source_checks_gate_the_next_run(self):
        for part in ("removal", "lock", "source_check"):
            def runner(*args, **kwargs):
                result = run77.execute(*args, **kwargs)
                copy = {"removal": {"removed": True}, "lock": {"released": True},
                        "source_check": {"unchanged": True}}
                copy[part] = {}
                next(s for s in result["stages"] if s["stage"] == "platform_check")["base_copy"] = copy
                atomic_json(Path(result["run_dir"]) / "run.json", result)
                return result
            with self.subTest(part=part):
                report = self.go(runner=runner)
                self.assertEqual([r["status"] for r in report["scenarios"]], ["blocked", "skipped"])
                self.xml(report)

    def test_keep_copy_rejected_before_launch(self):
        with self.project.open("a", encoding="utf-8") as out:
            out.write('\n[configuration]\nmodules="configuration"\nkeep_copy=true\n')
        report = self.go(runner=lambda *a, **k: self.fail("runner started"))
        self.assertTrue(all(r["status"] == "blocked" for r in report["scenarios"]))
        self.xml(report)

    def test_xml_escapes_markup_controls_and_keeps_unicode(self):
        report = self.go(self.profile([('выбор <товара> & "имя"', self.root / "missing.toml")]))
        row = report["scenarios"][0]
        row["reason"] = 'Нет <товара> & "имя"\x00\x01\ud800'
        element = ET.fromstring(suite77.junit(report))
        case = element.find("testsuite/testcase")
        self.assertEqual(case.get("name"), 'выбор <товара> & "имя"')
        self.assertEqual(case.find("error").get("message"), 'Нет <товара> & "имя"\ufffd\ufffd\ufffd')

    def test_cli_dispatch_and_mcp_use_same_suite_contract(self):
        self.profile()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["suite", "--suite", str(self.manifest), "--stand", str(self.stand_path),
                             "--output-root", str(self.output)])
        summary = json.loads(out.getvalue())
        self.assertEqual((code, summary["status"], summary["counts"]["passed"]), (0, "passed", 2))
        tool = mcp77.TOOLS_BY_NAME["suite"]
        self.assertTrue(tool.cancel_file)
        self.assertEqual(tool.argv({"suite": "a.toml", "stand": "b.toml", "calculation_timeout_s": 120}),
                         ["suite", "--suite=a.toml", "--stand=b.toml", "--calculation-timeout-s=120"])


if __name__ == "__main__":
    unittest.main()
