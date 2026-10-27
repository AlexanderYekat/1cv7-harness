"""Re-read task 027 native runs and compare them to the current probe expectations.

Pass --evidence for each series 1 file in chronological order (the latest result of a case wins),
--example-run for each run of examples/table-part and --regression KIND=RUN_ID for the earlier tasks
(026 = examples/modal-dialogs, 025 = examples/form-steps, 022 = f-elements). Files are in
.artifacts/runs. Reports include hashes; local databases/results are not part of the repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research/forms"))
import probe_table77 as probes  # noqa: E402
import scenario77  # noqa: E402

scenario = probes.scenario
base = probes.base


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def example_case(folder):
    """An example's scenario as a probe case: every step and its tests must pass."""
    text = tomllib.loads((ROOT / "examples" / folder / "scenario.toml").read_text(encoding="utf-8"))
    case = {"id": "example-" + folder, "parameters": {"steps": text["platform"]["parameters"]["steps"]}}
    verify = next((t for t in text["platform"]["tests"] if t["command"] == "verify"), None)
    if verify is not None:
        case["verify_value"] = verify["expect_value"]
    return case


REGRESSIONS = {"026": (scenario.judge, example_case("modal-dialogs")),
               "025": (scenario.judge, example_case("form-steps")),
               "022": (base.judge, next(c for c in base.CASES if c["id"] == "f-elements"))}


def table_states(result):
    """What the table steps saw: the state before and after, the cell editor, the keys and the windows."""
    rows = []
    for step in result.get("steps") or []:
        if not (step.get("before") or step["kind"] in scenario77.TABLE_KINDS + ("key",)):
            continue
        action, trip = step.get("action") or {}, step.get("round_trip") or {}
        rows.append({"step": step["index"], "kind": step["kind"],
                     "before": {k: (step.get("before") or {}).get(k) for k in ("rows", "row", "column")},
                     "after": {k: trip.get(k) for k in ("rows", "row", "column", "value", "total")},
                     "key": action.get("key"), "input_enters": len(action.get("input_enters") or []),
                     "editor": {k: (action.get("editor_before") or {}).get(k) for k in ("class", "id")},
                     "typed": {k: (action.get("typing") or {}).get(k) for k in ("text_before", "text_after")},
                     "committed": action.get("committed"),
                     "window": scenario77.dialog_text(step["unexpected"]) if step.get("unexpected") else None,
                     "dismissed_open": (step.get("dismissed") or {}).get("open")})
    return rows


def check(case, run_id, judge=scenario.judge, run_hash=None):
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
        if (folder / "native" / "ert-check-started").exists() or (folder / "native" / "debugger.log").exists():
            issues.append("a session started although the case is refused before it")
    elif observed["shutdown"] != "passed":
        issues.append("session shutdown not confirmed")
    report = json.loads(path.read_text(encoding="utf-8"))
    platform = json.loads((folder / "platform-result.json").read_text(encoding="utf-8"))
    if platform.get("base_list", {}).get("unchanged") is False:
        issues.append("base list changed")
    result = observed["operations"].get("result") or {}
    states = table_states(result)
    if any(row["dismissed_open"] for row in states):
        issues.append("a window of a failed step stayed open")
    return {"id": case["id"], "run_id": run_id, "run_sha256": digest(path),
            "status": "failed" if issues else "passed", "issues": issues,
            "run_status": report["status"], "reason": observed["platform_reason"], "tests": observed["tests"],
            "steps": [{k: s.get(k) for k in ("index", "kind", "target", "status", "issue")}
                      for s in result.get("steps") or []],
            "table": states, "form_issues": result.get("form_issues"),
            "source_unchanged": copied.get("source_unchanged"), "copy_removed": copied.get("removal")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", action="append", required=True, type=Path)
    parser.add_argument("--example-run", action="append", required=True)
    parser.add_argument("--regression", action="append", default=[], help="026|025|022=RUN_ID")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    latest, series_checks = {}, []
    for path in args.evidence:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        latest.update({case["id"]: case for case in evidence["cases"]})
        series_checks.append({"path": path.name, "sha256": digest(path), "checks": evidence["series"]})
    expected = {case["id"]: case for case in probes.CASES}
    missing = sorted(set(expected) - set(latest))
    rows = [check(dict(expected[name]), row["run_id"], run_hash=row["run_json_sha256"])
            for name, row in latest.items() if name in expected]
    examples = [check(example_case("table-part"), run_id) for run_id in args.example_run]
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
                  "research/forms/scenario77.py", "research/forms/probe_table77.py",
                  "examples/table-part/scenario.toml", "examples/table-part/prepare.py")}}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
    print(json.dumps({"status": result["status"], "cases": len(rows), "examples": len(examples),
                      "regressions": len(regressions), "missing": missing, "output": str(args.output)},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
