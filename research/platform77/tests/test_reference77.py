"""Portable tampering checks; the mock bytes do not stand for a native ERT."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ert_probe77 import read_results
from reference77 import CASES, prepare, verify_package, verified_run, compare_reference
from shutdown77 import MODE, PINNED, STEPS, assess, atomic_json, sha256


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.donors = {}
        for case in CASES:
            out = self.root / case
            out.mkdir()
            self.donors[case] = out
            for name in ("sample.ert", "client.vbs", "shutdown-installer.1s"):
                (out / name).write_bytes((case + ":" + name).encode())
            target = out / "sample.ert"
            manifest = {"run_id": case, "case": case, "identity": case + ":" + case,
                "ert_path": str(target), "commands": ["check", "execute"],
                "sources": {target.name: sha256(target)},
                "expected_error_line": None if case == "ok" else 2 if case == "syntax" else 6}
            shutdown_manifest = {"run_id": case, "mode": MODE, "fault": "none",
                "sources": {name: sha256(out / name) for name in ("client.vbs", "shutdown-installer.1s")}}
            lifecycle = {"run_id": case, "case": case, "shutdown_mode": MODE, "fault": "none",
                "private_desktop": "fixture", "desktop_closed": True,
                "forced_cleanup": False, "first_chance_av_observed": False,
                "av_dump_saved": False, "diagnostic_execution_modified": False,
                "server_exit_code": 0, "helper_exit_code": 0, "debugger_exit_code": 0,
                "processes_before": [], "processes_after": [],
                "hashes_before": PINNED.copy(), "hashes_after": PINNED.copy(),
                "temporary_com_registration": {"removed": True, "sha256": PINNED["helper"]},
                "server": {"pid": 77, "parent_pid": 12, "ownership_verified": True, "creation_filetime": 123},
                "debugger_pid": 12, "debugger_ready": True,
                "debugger_stops_at_first_chance_av": True, "shutdown_started_observed": True}
            shutdown_events = [{"run_id": case, "name": name,
                "value": "77" if value == "pid" else "2" if value == "positive" else value}
                for name, value in STEPS]
            (out / "shutdown-events.jsonl").write_text(
                "\n".join(json.dumps(row) for row in shutdown_events), encoding="utf-16")
            events = [{"run_id": case, "kind": "phase", "name": name, "value": "ok", "elapsed_ms": 1}
                for name in ("base", "controller")]
            for command in manifest["commands"]:
                actual = "selected:" + str(target) + "\nopen-return:0\n"
                protocol = "HARNESS77-BEGIN:" + case + ":" + command + "\n"
                if case == "ok":
                    actual += "loaded:" + manifest["identity"] + "\n"
                    actual += "value:42\n" if command == "execute" else ""
                    actual += "completed:" + manifest["identity"] + "\n"
                else:
                    protocol += "{" + str(target) + "(" + str(manifest["expected_error_line"]) + ")}: test error\n"
                protocol += "HARNESS77-END:" + case + ":" + command
                (out / (command + ".txt")).write_text(protocol, encoding="utf-16")
                events.append({"run_id": case, "kind": "ert", "name": command, "value": actual, "elapsed_ms": 1})
            events.append({"run_id": case, "kind": "complete", "name": "ert", "value": "done", "elapsed_ms": 1})
            (out / "ert-events.jsonl").write_text("\n".join(json.dumps(row) for row in events), encoding="utf-16")
            lifecycle["ert"] = read_results(out, manifest, lifecycle, assess(out, shutdown_manifest, lifecycle))
            lifecycle["status"] = lifecycle["ert"]["status"]
            self.assertEqual(lifecycle["status"], "passed")
            atomic_json(out / "ert-manifest.json", manifest)
            atomic_json(out / "shutdown-manifest.json", shutdown_manifest)
            atomic_json(out / "run.json", lifecycle)
        self.output = self.root / "reference"

    def test_exact_copies_do_not_claim_manual_acceptance(self):
        result = prepare(self.donors, self.output)
        self.assertEqual(result["status"], "awaiting_reference")
        for row in result["cases"]:
            self.assertEqual(row["reference_status"], "not_run")
            self.assertEqual((self.output / row["file"]).read_bytes(), Path(row["donor_ert"]).read_bytes())
        self.assertEqual(verify_package(self.output)["reference_acceptance"], "not_assessed")

    def test_changed_reference_copy_is_rejected(self):
        prepare(self.donors, self.output)
        (self.output / "01-ok.ert").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "reference ERT changed"):
            verify_package(self.output)

    def test_saved_success_does_not_hide_missing_current_evidence(self):
        (self.donors["syntax"] / "ert-events.jsonl").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "donor evidence not verified"):
            prepare(self.donors, self.output)
        self.assertFalse(self.output.exists())

    def test_shutdown_failure_cannot_be_accepted_from_old_passed(self):
        path = self.donors["ok"] / "run.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["server_exit_code"] = 1
        atomic_json(path, report)
        with self.assertRaisesRegex(ValueError, "donor evidence not verified"):
            prepare(self.donors, self.output)

    def test_donor_mutation_after_freeze_is_rejected(self):
        prepare(self.donors, self.output)
        path = self.donors["ok"] / "run.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["extra"] = "subsequent edit"
        atomic_json(path, report)
        with self.assertRaisesRegex(ValueError, "donor changed"):
            verify_package(self.output)

    def test_existing_package_is_not_overwritten(self):
        prepare(self.donors, self.output)
        before = (self.output / "reference-manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            prepare(self.donors, self.output)
        self.assertEqual((self.output / "reference-manifest.json").read_bytes(), before)

    def test_wrong_case_is_rejected_before_copying(self):
        self.donors["syntax"] = self.donors["ok"]
        with self.assertRaisesRegex(ValueError, "donor case mismatch"):
            prepare(self.donors, self.output)
        self.assertFalse(self.output.exists())

    def test_selected_ert_must_be_in_source_manifest(self):
        path = self.donors["ok"] / "ert-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["sources"] = {}
        atomic_json(path, manifest)
        with self.assertRaisesRegex(ValueError, "selected ERT is not pinned"):
            verified_run(self.donors["ok"], "ok")

    def observations(self):
        manifest = prepare(self.donors, self.output)
        rows = []
        for frozen in manifest["cases"]:
            row = {key: frozen[key] for key in ("case", "file", "sha256")}
            row.update(selected_path=str(self.output / row["file"]),
                       screenshot=row["file"] + ".png",
                       status="passed" if row["case"] == "ok" else "failed")
            # Synthetic evidence tests hashing only, not screenshot recognition.
            (self.output / row["screenshot"]).write_bytes(b"synthetic screenshot")
            row["screenshot_sha256"] = sha256(self.output / row["screenshot"])
            if row["case"] == "ok":
                row["success_message"] = "Синтаксических ошибок не обнаружено!"
            else:
                path = (self.output / row["file"]).with_suffix(".txt")
                path.write_bytes(("{" + row["selected_path"] + "(" + str(frozen["expected_error_line"])
                    + ")}: test error\r\nПри проверке модуля обнаружены синтаксические ошибки!\r\n").encode("cp1251"))
                row["protocol_sha256"] = sha256(path)
            rows.append(row)
        result = {"participation": "assisted", "cases": rows}
        atomic_json(self.output / "observations.json", result)
        return result

    def test_comparison_matches_complete_explicit_observations(self):
        self.observations()
        result = compare_reference(self.output)
        self.assertEqual(result["comparison"], "matched")
        self.assertEqual(result["cases"][1]["protocol_import"]["status"], "failed")

    def test_comparison_preserves_different_message(self):
        observations = self.observations()
        row = observations["cases"][1]
        path = (self.output / row["file"]).with_suffix(".txt")
        path.write_bytes(path.read_bytes().replace(b"test error", b"different error"))
        row["protocol_sha256"] = sha256(path)
        atomic_json(self.output / "observations.json", observations)
        result = compare_reference(self.output)
        self.assertEqual(result["comparison"], "mismatched")
        self.assertTrue(result["cases"][1]["comparisons"][0]["lines_match"])
        self.assertFalse(result["cases"][1]["comparisons"][0]["messages_match"])

    def test_silence_is_not_positive_reference(self):
        observations = self.observations()
        observations["cases"][0].pop("success_message")
        atomic_json(self.output / "observations.json", observations)
        with self.assertRaisesRegex(ValueError, "explicit positive"):
            compare_reference(self.output)

    def test_partial_reference_is_blocked_even_with_matching_hash(self):
        observations = self.observations()
        row = observations["cases"][1]
        path = (self.output / row["file"]).with_suffix(".txt")
        path.write_bytes(path.read_bytes().split(b"\r\n")[0])
        row["protocol_sha256"] = sha256(path)
        atomic_json(self.output / "observations.json", observations)
        with self.assertRaisesRegex(ValueError, "complete unchanged"):
            compare_reference(self.output)

    def test_wrong_selected_artifact_is_blocked(self):
        observations = self.observations()
        observations["cases"][0]["selected_path"] = str(self.root / "other.ert")
        atomic_json(self.output / "observations.json", observations)
        with self.assertRaisesRegex(ValueError, "observed artifact mismatch"):
            compare_reference(self.output)

    def test_changed_screenshot_is_blocked(self):
        observations = self.observations()
        (self.output / observations["cases"][0]["screenshot"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "screenshot changed"):
            compare_reference(self.output)

    def test_top_level_blocked_donor_is_rejected(self):
        path = self.donors["ok"] / "run.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["status"] = "blocked"
        atomic_json(path, report)
        with self.assertRaisesRegex(ValueError, "donor evidence not verified"):
            prepare(self.donors, self.output)


if __name__ == "__main__":
    unittest.main()
