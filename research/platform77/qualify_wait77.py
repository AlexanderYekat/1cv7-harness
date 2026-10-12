"""Sequential ok -> modal timeout -> fresh ok; stop at the first unexpected result."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import uuid

from concurrent77 import concurrency_issues
from run_ert77 import main as run
from shutdown77 import PINNED, atomic_json
from proxy_debug77 import DEFAULT_OBSERVER


def expectation_met(report, code, case, seen):
    """A recovery must use a fresh UUID and retain every shutdown safeguard."""
    try:
        run_id = report["run_id"]
        fresh = str(uuid.UUID(run_id)) == run_id and run_id not in seen
    except (KeyError, ValueError, TypeError, AttributeError):
        return False
    clean = (report.get("cleanup_verified") is True and report.get("desktop_closed") is True
        and not concurrency_issues(report) and not report.get("error") and not report.get("cleanup_errors")
        and all(report.get(key) is False for key in ("first_chance_av_observed", "av_dump_saved", "forced_cleanup"))
        and report.get("hashes_before") == PINNED and report.get("hashes_after") == PINNED
        and all(type(report.get(key)) is int and report[key] == 0
                for key in ("server_exit_code", "helper_exit_code", "debugger_exit_code")))
    expected = (code == 2 and report.get("status") == "blocked" and report.get("ert", {}).get("timeout_verified") is True
                if case == "wait" else code == 0 and report.get("status") == "passed")
    return bool(fresh and report.get("case") == case and clean and expected
                and report.get("identity_observer_profile") == DEFAULT_OBSERVER
                and report.get("shutdown_timeout_seconds") == 10
                and report.get("ert_operation_timeout_seconds") == 30
                and report.get("timeout_seconds") == 145)


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    for name in ("base", "exe", "cdb", "com-cleanup-dll", "identity-dll", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--user", required=True)
    parser.add_argument("--cycles", type=int, choices=range(1, 11), default=1,
                        help="predeclared consecutive ok/wait/ok cycles; never retries failures")
    args = parser.parse_args(argv)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = []
    seen = set()
    plan = [(str(Path("cycle-%02d" % cycle) / name) if args.cycles > 1 else name, case)
            for cycle in range(1, args.cycles + 1)
            for name, case in (("success-before", "ok"), ("modal-timeout", "wait"), ("success-after", "ok"))]
    summary = {"cycles_requested": args.cycles, "planned_runs": [{"name": name, "case": case} for name, case in plan],
               "identity_observer_profile": DEFAULT_OBSERVER, "runs": results,
               "scope": "synthetic modal timeout and fresh-session recovery on pinned base; raw wait remains blocked; not all P00-P08"}
    atomic_json(out / "qualification.json", dict(summary, complete=False, status="running"))
    for name, case in plan:
        destination = out / name
        command = ["--user", args.user, "--case", case, "--output", str(destination)]
        for key in ("base", "exe", "cdb", "com-cleanup-dll", "identity-dll"):
            command.extend(["--" + key, str(getattr(args, key.replace("-", "_")))])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = run(command)
        row = {"name": name, "exit_code": code, "output": str(destination), "expectation_met": False}
        if (destination / "run.json").exists():
            report = json.loads((destination / "run.json").read_text(encoding="utf-8"))
            row.update(status=report.get("status"), expectation_met=expectation_met(report, code, case, seen),
                       run_id=report.get("run_id"), elapsed_seconds=report.get("elapsed_seconds"),
                       shutdown_elapsed_seconds=report.get("shutdown_elapsed_seconds"),
                       timeout_phase=report.get("timeout_phase"), cleanup_verified=report.get("cleanup_verified"))
            if isinstance(report.get("run_id"), str):
                seen.add(report["run_id"])
        else:
            row["error"] = output.getvalue()
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        atomic_json(out / "qualification.json", dict(summary, complete=False, status="running"))
        if not row["expectation_met"]:
            break
    accepted = len(results) == len(plan) and all(row["expectation_met"] for row in results)
    atomic_json(out / "qualification.json", dict(summary, complete=accepted, status="passed" if accepted else "blocked"))
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
