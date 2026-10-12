"""Sequential ok -> modal timeout -> fresh ok; stop at the first unexpected result."""
import argparse
import contextlib
import io
import json
from pathlib import Path

from concurrent77 import concurrency_issues
from run_ert77 import main as run
from shutdown77 import PINNED, atomic_json


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    for name in ("base", "exe", "cdb", "com-cleanup-dll", "identity-dll", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--user", required=True)
    args = parser.parse_args(argv)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for name, case in (("success-before", "ok"), ("modal-timeout", "wait"), ("success-after", "ok")):
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
            clean = (report.get("cleanup_verified") is True and report.get("desktop_closed") is True
                and not concurrency_issues(report) and not report.get("error") and not report.get("cleanup_errors")
                and all(report.get(key) is False for key in ("first_chance_av_observed", "av_dump_saved", "forced_cleanup"))
                and report.get("hashes_before") == PINNED and report.get("hashes_after") == PINNED
                and all(type(report.get(key)) is int and report[key] == 0
                        for key in ("server_exit_code", "helper_exit_code", "debugger_exit_code")))
            expected = (code == 2 and report.get("status") == "blocked" and report.get("ert", {}).get("timeout_verified") is True
                        if case == "wait" else code == 0 and report.get("status") == "passed")
            row.update(status=report.get("status"), expectation_met=bool(expected and clean),
                       run_id=report.get("run_id"), elapsed_seconds=report.get("elapsed_seconds"),
                       timeout_phase=report.get("timeout_phase"), cleanup_verified=report.get("cleanup_verified"))
        else:
            row["error"] = output.getvalue()
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        atomic_json(out / "qualification.json", {"complete": False, "runs": results})
        if not row["expectation_met"]:
            break
    accepted = len(results) == 3 and all(row["expectation_met"] for row in results)
    atomic_json(out / "qualification.json", {"complete": accepted, "status": "passed" if accepted else "blocked",
        "scope": "one synthetic modal timeout and recovery on pinned base; raw wait remains blocked; not all P00-P08", "runs": results})
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
