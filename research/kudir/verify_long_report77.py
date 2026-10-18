"""Acceptance of task 006: the long native KUDiR report through `harness77 run`.

  python research/kudir/verify_long_report77.py --kudir <KUDiR project> --accepted KUDIR4_20261015_002
      --before .artifacts/stage6-state-before.json --after .artifacts/stage6-state-after.json
      --run N1=<run_id> --run N2=<run_id> ... --output .artifacts/stage6-acceptance-<date>.json

Each run is judged against the expectation written in docs/tasks/006-long-native-report.md
before it ran. The package of a complete export is compared with the accepted one by the
KUDiR project's own check (reports/check_e07.py files); the longest pause between lines of
its 1c_export.log shows the report ran without messages for that long and still passed.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ACCEPTED_ERT = "75a8b8dfb2382b7f5dfcc07d2864b511e192b4c6d29cb64bcf805b0fbafb91e7"  # kudir_export.ert 2026.10.15-01, commit 54b0d4e
LOG_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2} +\d{1,2}:\d{2}:\d{2}) \|", re.M)
EXPECT = {
    "N1": {"status": "passed", "tests": {"check": "2026.10.15-01"}},
    "N2": {"status": "passed", "tests": {"full": "COMPLETE"}, "package": "complete"},
    # Added before it ran, because N2 took 6 min 17 s instead of 10-30 min.
    "N2b": {"status": "passed", "tests": {"series": "COMPLETE;COMPLETE;COMPLETE"}, "package": "complete",
            "packages": 3, "min_session_s": 900},
    "N3": {"status": "passed", "tests": {"write-fault": "FAILED"}, "package": "incomplete"},
    "N4": {"status": "blocked", "timeout_phase": "calculation", "package": "incomplete", "forced": True},
    "N5": {"status": "blocked", "cancelled": True, "package": "incomplete", "forced": True},
    "N5b": {"status": "blocked", "cancelled": True, "package": "incomplete", "forced": True},
    "N6": {"status": "passed", "tests": {"full": "COMPLETE"}, "package": "complete"},
    # Added after N5b left a stale user record: a normal session clears it (and reindexes),
    # then a full export must still equal the accepted package.
    "N7": {"status": "passed", "tests": {"check": "2026.10.15-01"}},
    "N8": {"status": "passed", "tests": {"full": "COMPLETE"}, "package": "complete"},
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def longest_pause(log_text):
    times = [datetime.datetime.strptime(" ".join(m.split()), "%Y-%m-%d %H:%M:%S") for m in LOG_TIME.findall(log_text)]
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    return max(gaps, default=None), (times[-1] - times[0]).total_seconds() if len(times) > 1 else None


def check_package(kudir, package, accepted):
    completed = subprocess.run([sys.executable, "reports/check_e07.py", "files", str(package),
                                "--accepted", str(kudir / "exchange" / accepted)],
                               cwd=kudir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [line for line in completed.stdout.splitlines() if line.strip()][-3:]
    return {"exit_code": completed.returncode, "tail": tail}


def judge(role, run_dir, kudir, accepted):
    report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    expect, issues = EXPECT[role], []
    stages = {s["stage"]: s for s in report["stages"]}
    platform = stages.get("platform_check", {})
    shutdown = report.get("shutdown") or {}
    if report["status"] != expect["status"]:
        issues.append(f"status {report['status']}, expected {expect['status']}")
    if (report.get("artifact") or {}).get("sha256") != ACCEPTED_ERT:
        issues.append("the checked ERT is not the accepted 2026.10.15-01 build")
    for name, value in expect.get("tests", {}).items():
        test = next((t for t in stages.get("tests", {}).get("tests", []) if t["name"] == name), None)
        if not test or not test.get("expectation_met") or test.get("value") != value:
            issues.append(f"test {name}: {test and (test.get('status'), test.get('value'))}, expected {value}")
    if expect.get("timeout_phase") and report.get("timeout_phase") != expect["timeout_phase"]:
        issues.append(f"timeout_phase {report.get('timeout_phase')}")
    if bool(report.get("cancelled")) != bool(expect.get("cancelled")):
        issues.append(f"cancelled {report.get('cancelled')}")
    if not shutdown.get("cleanup_verified") or not shutdown.get("others_preserved"):
        issues.append(f"shutdown not verified: {shutdown}")
    if shutdown.get("forced_cleanup") and not expect.get("forced"):
        issues.append("forced cleanup in a run that had to end normally")
    packages = sorted(p for p in (run_dir / "kudir" / "exchange").iterdir() if p.is_dir()) \
        if (run_dir / "kudir" / "exchange").is_dir() else []
    files = report.get("result_files", [])
    row = {"role": role, "run_id": report["run_id"], "status": report["status"], "reason": report.get("reason"),
           "timeout_phase": report.get("timeout_phase"), "cancelled": report.get("cancelled"),
           "session_s": (platform.get("phase_durations_s") or {}).get("session"),
           "shutdown": shutdown, "packages": [p.name for p in packages],
           "result_files": len(files), "result_bytes": sum(f.get("size_bytes", 0) for f in files),
           "run_json_sha256": sha256(run_dir / "run.json")}
    if expect.get("min_session_s") and (row["session_s"] or 0) < expect["min_session_s"]:
        issues.append(f"session {row['session_s']} s, expected at least {expect['min_session_s']} s")
    if expect.get("package") == "complete":
        count = expect.get("packages", 1)
        if len(packages) != count or not files or not all(f.get("complete") and f.get("sha256_matches") for f in files):
            issues.append(f"expected {count} complete package(s) with verified files")
        else:
            pauses, row["check_e07"] = [], []
            for package in packages:
                log = (package / "1c_export.log").read_bytes().decode("cp1251", "replace")
                pauses.append(longest_pause(log))
                result = check_package(kudir, package, accepted)
                row["check_e07"].append(dict(result, package=package.name))
                if result["exit_code"] != 0:
                    issues.append(f"check_e07 files of {package.name} against the accepted package failed")
            row["longest_pause_s"] = max(p[0] for p in pauses)
            row["export_s"] = [p[1] for p in pauses]
    elif expect.get("package") == "incomplete":
        complete = [f for f in files if f.get("complete")]
        statuses = {p.name: (p / "export_status.csv").read_bytes().decode("cp1251", "replace")
                    if (p / "export_status.csv").exists() else None for p in packages}
        row["export_status"] = statuses
        if complete or any(s and "status;COMPLETE" in s for s in statuses.values()):
            issues.append("a package was published COMPLETE")
    row["issues"] = issues
    row["verdict"] = "confirmed" if not issues else "contradicted"
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kudir", required=True, type=Path)
    parser.add_argument("--accepted", required=True)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--run", action="append", required=True, metavar="ROLE=RUN_ID")
    parser.add_argument("--runs-root", type=Path, default=ROOT / ".artifacts" / "runs")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.path.lexists(args.output):
        parser.error(f"output exists: {args.output}")
    rows = []
    for item in args.run:
        role, run_id = item.split("=", 1)
        rows.append(judge(role, args.runs_root / run_id, args.kudir, args.accepted))
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    state = {"kudir_packages_before": len(before["packages"]),
             "kudir_packages_unchanged": before["packages"] == {k: after["packages"].get(k) for k in before["packages"]},
             "kudir_packages_added": sorted(set(after["packages"]) - set(before["packages"])),
             "base_files_changed": sorted(name for name, entry in before["base_files"].items()
                                          if after["base_files"].get(name, {}).get("sha256") != entry["sha256"]),
             "base_files_added": sorted(set(after["base_files"]) - set(before["base_files"]))}
    leftovers = subprocess.run(["tasklist"], capture_output=True, text=True, errors="replace").stdout
    state["leftover_1c_processes"] = [line for line in leftovers.splitlines()
                                      if line.lower().startswith(("1cv7", "cdb.exe"))]
    ok = all(r["verdict"] == "confirmed" for r in rows) and state["kudir_packages_unchanged"] \
        and not state["kudir_packages_added"] and not state["leftover_1c_processes"]
    summary = {"schema_version": 1, "scope": "task 006: long native KUDiR report through harness77 run",
               "generated": datetime.datetime.now().astimezone().isoformat(), "runs": rows, "state": state,
               "status": "passed" if ok else "failed"}
    with open(args.output, "x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=1)
    for r in rows:
        print(r["role"], r["verdict"], r["status"], r.get("session_s"), r.get("longest_pause_s"), "; ".join(r["issues"]))
    print("state", json.dumps(state, ensure_ascii=False))
    print("status", summary["status"])
    return 0 if ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
