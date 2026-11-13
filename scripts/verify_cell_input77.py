"""090: verify cell input on independent fresh copies, without retrying failed runs."""
import argparse
from decimal import Decimal
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


def cell_evidence(folder):
    inspection = json.loads((folder / "form/form-window.json").read_text(encoding="utf-8"))
    rows = [r for r in inspection["steps"] if r["kind"] == "cell"]
    assert len(rows) == 1, "expected one quantity input, no replay"
    action = rows[0]["action"]
    wait, focus, control, typing = [action[k] for k in ("editor_wait", "focus_before", "editor_before", "typing")]
    assert wait["ready"] and wait["observations"][-1]["ready"]
    assert control["class"] == "1CEDIT" and control["id"] == 4160
    assert focus["id"] == 0 and focus["hwnd"] != control["hwnd"]
    assert typing["hwnd"] == focus["hwnd"] == action["focus_before_enter"]["hwnd"]
    assert typing["typed"] and action["committed"]
    assert [c["stage"] for c in typing["focus_checks"]] == ["select", "type", "after_type"]
    assert all(c["matches"] and c["focus"]["hwnd"] == focus["hwnd"] for c in typing["focus_checks"])
    assert Decimal(typing["text_after"].strip()) == Decimal(typing["text"]) == 3
    delayed = any(o["editor"] and o["focus"] and o["editor"]["class"] == "1CEDIT"
                  and o["editor"]["hwnd"] == o["focus"]["hwnd"] and not o["ready"]
                  for o in wait["observations"])
    return {"run_id": folder.name, "input_target": typing["hwnd"], "wrapper": control["hwnd"],
            "text_after": typing["text_after"], "wrapper_wait_observed": delayed,
            "observations": len(wait["observations"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=16, help="independent success scenarios, 1..100")
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        parser.error("count must be 1..100")
    kit, output = args.kit.resolve(strict=True), args.output.resolve()
    if os.name != "nt" or sys.prefix == sys.base_prefix or os.environ.get("PYTHONPATH") or os.environ.get("PYTHONHOME"):
        parser.error("requires a clean Windows venv")
    if not Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        parser.error("harness77 must be installed in the venv")
    output.mkdir(parents=True, exist_ok=False)
    working = output / "working"
    working.mkdir()
    stand = load_stand(kit / "stand.toml")
    manifest = json.loads((kit / "kit.json").read_text(encoding="utf-8"))
    inspector = WindowsInspector()
    lock = basecopy77.lock_path(stand.copy_path)
    guard = lock.with_name(lock.name + ".guard")
    sys.path[:0] = [str(kit / "native/forms"), str(kit / "verification")]
    from verify_document_form77 import check
    from verify_suite77 import verify

    def snapshot():
        return {"source": basecopy77.listing(stand.base),
                "base_hashes": {n: digest(stand.base / n) for n in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll")},
                "registry": {key: registry_tree(key) for key in (TITLES, *COM_KEYS)},
                "processes": inspector.processes(), "copy_exists": stand.copy_path.exists(),
                "lock_exists": lock.exists(), "guard": digest(guard) if guard.exists() else None,
                "kit": {n: digest(kit / n) for n in manifest["files"]}}

    before = snapshot()
    evidence = {"status": "running", "count": args.count, "cells": [], "suites": [],
                "environment": {"python": sys.executable, "module": harness77.__file__},
                "kit_sha256": digest(kit / "kit.json")}
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")

    def execute(name, command, expected):
        result = subprocess.run(command, cwd=working, env=env, capture_output=True, timeout=1000 * (args.count + 4))
        (output / (name + ".log")).write_bytes(result.stdout + result.stderr)
        assert result.returncode == expected, name + ": unexpected exit; see log"

    def suite(folder, expected_count):
        result = verify(folder, native=True)
        evidence["suites"].append(result)
        assert not result["issues"], result["issues"]
        report = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
        assert len(report["scenarios"]) == expected_count
        for row in report["scenarios"]:
            run = (folder / row["report"]["path"]).parent
            verified = check(run, "wrong" if row["id"] == "wrong" else "success", row["report"]["sha256"])
            assert not verified["issues"], verified
            evidence["cells"].append(cell_evidence(run))

    try:
        assert not before["processes"] and not before["copy_exists"] and not before["lock_exists"]
        execute("doctor-before", [sys.executable, "-B", "-m", "harness77", "doctor", "--project", str(kit / "success/project.toml"),
                                  "--stand", str(kit / "stand.toml"), "--output-root", str(output / "results"), "--format", "json"], 0)
        execute("smoke", [sys.executable, "-B", str(kit / "run.py"), "--output", str(output / "smoke")], 0)
        suite(output / "smoke/results/suite", 2)
        suite(output / "smoke/results/suite-failure", 2)
        text = 'schema_version=1\n[suite]\nid="cell-input-090"\n'
        for index in range(args.count):
            text += '[[scenarios]]\nid="cell-' + str(index + 1) + '"\nproject=' + json.dumps((kit / "success/project.toml").as_posix()) + '\n'
        profile = output / "stress.toml"
        profile.write_text(text, encoding="utf-8")
        execute("stress", [sys.executable, "-B", "-m", "harness77", "suite", "--suite", str(profile),
                           "--stand", str(kit / "stand.toml"), "--output-root", str(output / "results"), "--suite-id", "stress"], 0)
        suite(output / "results/stress", args.count)
        execute("doctor-after", [sys.executable, "-B", "-m", "harness77", "doctor", "--project", str(kit / "success/project.toml"),
                                "--stand", str(kit / "stand.toml"), "--output-root", str(output / "results"), "--format", "json"], 0)
        evidence["wrapper_waits"] = sum(c["wrapper_wait_observed"] for c in evidence["cells"])
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
