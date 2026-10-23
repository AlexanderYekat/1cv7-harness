"""Re-read task 024 native runs and compare them to the current probe expectations.

Pass --evidence for each series in chronological order (latest case wins),
--no-copy-run RUN_ID and --example-run RUN_ID. Files are in .artifacts/runs.
Reports include hashes; local databases/results are not part of the repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research/forms"))
import probe_test_data77 as probes


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(case, run_id, run_hash=None):
    folder = ROOT / ".artifacts/runs" / run_id
    path = folder / "run.json"
    observed = probes.base.observe(folder)
    issues = []
    if run_hash and digest(path) != run_hash:
        issues.append("run.json changed since the series")
    if probes.base.judge(case, observed) != "confirmed":
        issues.append("current expectations do not match the run")
    copied = observed["copy"]
    if not copied.get("source_unchanged") or not (copied.get("removal") or {}).get("removed"):
        issues.append("source preservation/copy removal not confirmed")
    if observed["shutdown"] != "passed":
        issues.append("session shutdown not confirmed")
    report = json.loads(path.read_text(encoding="utf-8"))
    platform = json.loads((folder / "platform-result.json").read_text(encoding="utf-8"))
    if platform.get("base_list", {}).get("unchanged") is False:
        issues.append("base list changed")
    return {"id": case["id"], "run_id": run_id, "run_sha256": digest(path),
            "status": "failed" if issues else "passed", "issues": issues,
            "run_status": report["status"], "tests": observed["tests"],
            "source_unchanged": copied.get("source_unchanged"), "copy_removed": copied.get("removal"),
            "max_residual_px": (observed["inspection"].get("units") or {}).get("max_residual_px")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", action="append", required=True, type=Path)
    parser.add_argument("--no-copy-run", required=True)
    parser.add_argument("--example-run", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    latest, series_checks = {}, []
    for path in args.evidence:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        latest.update({case["id"]: case for case in evidence["cases"]})
        series_checks.append({"path": path.name, "sha256": digest(path), "checks": evidence["series"]})
    expected = {case["id"]: case for case in probes.CASES}
    missing = sorted(set(expected) - set(latest))
    rows = [check(expected[name], row["run_id"], row["run_json_sha256"])
            for name, row in latest.items() if name in expected]
    examples = [check(expected["example"], run_id) for run_id in args.example_run]
    rejected = ROOT / ".artifacts/runs" / args.no_copy_run
    refused = json.loads((rejected / "run.json").read_text(encoding="utf-8"))
    refusal_ok = (refused["status"] == "blocked" and "verified base copy" in (refused.get("reason") or "")
                  and not (rejected / "native").exists())
    ok = not missing and refusal_ok and all(row["status"] == "passed" for row in rows + examples) \
        and all(all(series["checks"].values()) for series in series_checks)
    result = {"schema_version": 1, "scope": probes.SCOPE, "status": "passed" if ok else "failed",
              "missing": missing, "series": series_checks, "cases": rows, "examples": examples,
              "sources": {name: digest(ROOT / name) for name in (
                  "research/forms/form_launcher77.py", "research/forms/fixture77.py",
                  "research/forms/probe_test_data77.py", "examples/test-data/prepare.py")},
              "without_copy": {"run_id": args.no_copy_run, "refused_before_session": refusal_ok,
                               "run_sha256": digest(rejected / "run.json")}}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
    print(json.dumps({"status": result["status"], "cases": len(rows), "examples": len(examples),
                      "missing": missing, "output": str(args.output)}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
