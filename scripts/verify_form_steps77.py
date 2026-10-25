"""Re-read task 025 native runs and compare them to the current probe expectations.

Pass --evidence for each series in chronological order (the latest result of a case wins),
--example-run for each run of examples/form-steps and --regression KIND=RUN_ID for the earlier
tasks (024 = examples/test-data, 022 = f-elements, 023 = e-button). Files are in .artifacts/runs.
Reports include hashes; local databases/results are not part of the repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research/forms"))
import probe_md_catalogs77 as catalogs  # noqa: E402
import probe_scenario77 as probes  # noqa: E402
import probe_test_data77 as data  # noqa: E402

base = probes.base
REGRESSIONS = {"024": (data.base.judge, next(c for c in data.CASES if c["id"] == "example")),
               "022": (base.judge, next(c for c in base.CASES if c["id"] == "f-elements")),
               "023": (base.judge, next(c for c in catalogs.CASES if c["id"] == "e-button"))}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def example_case():
    """The example's scenario as a probe case: every step and the three tests must pass."""
    scenario = tomllib.loads((ROOT / "examples/form-steps/scenario.toml").read_text(encoding="utf-8"))
    verify = next(t for t in scenario["platform"]["tests"] if t["command"] == "verify")
    return {"id": "example", "parameters": {"steps": scenario["platform"]["parameters"]["steps"]},
            "verify_value": verify["expect_value"]}


def error_line(case, run_id):
    """The line of the failing statement in the module 1C ran: extracted from the run's built 1Cv7.MD."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="harness77-025-") as temporary:
        target = Path(temporary) / "modules"
        base.md77.extract(ROOT / ".artifacts/runs" / run_id / "configuration" / "1Cv7.MD", target)
        lines = (target / (case["form"] + base.md77.SUFFIX)).read_bytes().decode("utf-8").splitlines()
    return lines.index("    Х77 = 1 / Делитель77;") + 1


def check(case, run_id, judge=probes.judge, run_hash=None):
    folder = ROOT / ".artifacts/runs" / run_id
    path = folder / "run.json"
    observed = base.observe(folder)
    issues = []
    if run_hash and digest(path) != run_hash:
        issues.append("run.json changed since the series")
    if judge(case, observed) != "confirmed":
        issues.append("current expectations do not match the run")
    copied = observed["copy"]
    if not copied.get("source_unchanged") or not (copied.get("removal") or {}).get("removed"):
        issues.append("source preservation/copy removal not confirmed")
    if case.get("blocked"):
        # Refused before the session: the launcher wrote its scaffolding, 1C was not started.
        if (folder / "native" / "ert-check-started").exists() or (folder / "native" / "debugger.log").exists():
            issues.append("a session started although the case is refused before it")
    elif observed["shutdown"] != "passed":
        issues.append("session shutdown not confirmed")
    report = json.loads(path.read_text(encoding="utf-8"))
    platform = json.loads((folder / "platform-result.json").read_text(encoding="utf-8"))
    if platform.get("base_list", {}).get("unchanged") is False:
        issues.append("base list changed")
    result = (observed["operations"].get("result") or {})
    return {"id": case["id"], "run_id": run_id, "run_sha256": digest(path),
            "status": "failed" if issues else "passed", "issues": issues,
            "run_status": report["status"], "reason": observed["platform_reason"], "tests": observed["tests"],
            "steps": [{k: s.get(k) for k in ("index", "kind", "target", "status", "issue")}
                      for s in result.get("steps") or []],
            "form_issues": result.get("form_issues"),
            "source_unchanged": copied.get("source_unchanged"), "copy_removed": copied.get("removal")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", action="append", required=True, type=Path)
    parser.add_argument("--example-run", action="append", required=True)
    parser.add_argument("--regression", action="append", default=[], help="024|022|023=RUN_ID")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    latest, series_checks = {}, []
    for path in args.evidence:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        latest.update({case["id"]: case for case in evidence["cases"]})
        series_checks.append({"path": path.name, "sha256": digest(path), "checks": evidence["series"]})
    expected = {case["id"]: case for case in probes.CASES}
    missing = sorted(set(expected) - set(latest))
    rows = []
    for name, row in latest.items():
        if name in expected:
            case = dict(expected[name])
            if case.get("module"):
                case["error_line"] = error_line(case, row["run_id"])
            rows.append(check(case, row["run_id"], run_hash=row["run_json_sha256"]))
    examples = [check(example_case(), run_id) for run_id in args.example_run]
    regressions = []
    for item in args.regression:
        kind, _, run_id = item.partition("=")
        judge, case = REGRESSIONS[kind]
        regressions.append(dict(check(case, run_id, judge=judge), task=kind))
    ok = not missing and len(examples) >= 2 and all(row["status"] == "passed" for row in rows + examples + regressions) \
        and sorted(r["task"] for r in regressions) == sorted(REGRESSIONS) \
        and all(all(series["checks"].values()) for series in series_checks)
    result = {"schema_version": 1, "scope": probes.SCOPE, "status": "passed" if ok else "failed",
              "missing": missing, "series": series_checks, "cases": rows, "examples": examples,
              "regressions": regressions,
              "sources": {name: digest(ROOT / name) for name in (
                  "research/forms/form_launcher77.py", "research/forms/form_window77.py",
                  "research/forms/scenario77.py", "research/forms/probe_scenario77.py",
                  "examples/form-steps/scenario.toml", "examples/form-steps/prepare.py")}}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
    print(json.dumps({"status": result["status"], "cases": len(rows), "examples": len(examples),
                      "regressions": len(regressions), "missing": missing, "output": str(args.output)},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
