"""090: native stale-focus old/fixed comparison and journal-date regression."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import harness77
from harness77 import basecopy77
from harness77.config77 import load_stand
from harness77.doctor_windows77 import COM_KEYS, TITLES, WindowsInspector
from verify_doctor77 import digest, registry_tree
from verify_cell_input77 import cell_evidence
from verify_document_form77 import check, excluded, read
from verify_journal_period77 import check as period_check
from verify_suite77 import verify
import scenario77


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controls", type=Path, required=True, help="profiles from cell_input_probe77.py --prepare")
    parser.add_argument("--period", type=Path, required=True, help="profiles from examples/journal-period/prepare.py")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    controls, period, output = args.controls.resolve(strict=True), args.period.resolve(strict=True), args.output.resolve()
    if os.name != "nt" or sys.prefix == sys.base_prefix or os.environ.get("PYTHONPATH") or os.environ.get("PYTHONHOME"):
        parser.error("requires a clean Windows venv")
    if not Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        parser.error("harness77 must be installed in this venv")
    stand = load_stand(controls / "stand.toml")
    inspector = WindowsInspector()
    lock = basecopy77.lock_path(stand.copy_path)
    guard = lock.with_name(lock.name + ".guard")

    def snapshot():
        return {"source": basecopy77.listing(stand.base),
                "hashes": {n: digest(stand.base / n) for n in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll")},
                "registry": {key: registry_tree(key) for key in (TITLES, *COM_KEYS)}, "processes": inspector.processes(),
                "copy": stand.copy_path.exists(), "lock": lock.exists(), "guard": digest(guard) if guard.exists() else None}

    before = snapshot()
    output.mkdir(parents=True, exist_ok=False)
    working = output / "working"
    working.mkdir()
    evidence = {"status": "running", "suites": [], "runs": [], "module": harness77.__file__}
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")

    def execute(name, profiles, expected):
        result = subprocess.run([sys.executable, "-B", "-m", "harness77", "suite", "--suite", str(profiles / "suite.toml"),
                                 "--stand", str(profiles / "stand.toml"), "--output-root", str(output / name), "--suite-id", name],
                                cwd=working, env=env, capture_output=True, timeout=1500)
        (output / (name + ".log")).write_bytes(result.stdout + result.stderr)
        assert result.returncode == expected, name + ": unexpected exit; see log"
        folder = output / name / name
        verified = verify(folder, native=True)
        evidence["suites"].append(verified)
        assert not verified["issues"], verified
        return folder, json.loads((folder / "suite.json").read_text(encoding="utf-8"))

    try:
        assert not before["processes"] and not before["copy"] and not before["lock"]
        folder, suite = execute("ab", controls, 1)
        assert [(r["id"], r["status"]) for r in suite["scenarios"]] == [("old", "failed"), ("fixed", "passed")]
        for row in suite["scenarios"]:
            run = (folder / row["report"]["path"]).parent
            steps = json.loads((run / "form/form-window.json").read_text(encoding="utf-8"))["steps"]
            action = next(s["action"] for s in steps if s["kind"] == "cell")
            assert action["cell_probe"]["mode"] == "one-stale-wrapper-snapshot"
            assert len(action["cell_probe"]["observations"]) == 1
            if row["id"] == "old":
                record = excluded(run)
                assert not record["issues"], record
                assert action["typing"]["hwnd"] == action["editor_before"]["hwnd"]
                assert action["typing"]["text_before"].strip() == action["typing"]["text_after"].strip() == "1.000"
                assert steps[-1]["index"] == 3 and steps[-1]["kind"] == "value" and steps[-1]["status"] == "failed"
                raw = scenario77.answer(read(run / "native/form-step-3-done"))
                assert raw["value"] == "10", raw
                record["wrapper_ignored_input"] = True
            else:
                record = check(run, "success", row["report"]["sha256"])
                assert not record["issues"], record
                cell = cell_evidence(run)
                assert cell["wrapper_wait_observed"], cell
                record["cell"] = cell
            evidence["runs"].append(record)
        assert snapshot() == before, "stand changed after controlled comparison"
        folder, suite = execute("period", period, 0)
        assert len(suite["scenarios"]) == 2
        for row in suite["scenarios"]:
            run = (folder / row["report"]["path"]).parent
            record = period_check(run, "success", row["report"]["sha256"])
            assert not record["issues"], record
            evidence["runs"].append(record)
        evidence["status"] = "passed"
    except Exception as error:
        evidence.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        after = snapshot()
        evidence["unchanged"] = {key: value == after[key] for key, value in before.items()}
        if not all(evidence["unchanged"].values()):
            evidence["status"] = "failed"
        (output / "verified.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output / "verified.json")
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
