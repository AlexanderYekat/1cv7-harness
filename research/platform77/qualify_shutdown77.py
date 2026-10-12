"""Sequential native checks for the pinned policy; stop on unsafe cleanup or AV."""
import argparse
import contextlib
import io
import json
from pathlib import Path

from run_shutdown77 import main as run
from shutdown77 import PINNED, atomic_json, read_events


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    for name in ("base", "exe", "cdb", "com-cleanup-dll", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--user", required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for name, fault in (("success-before", "none"), ("com-error", "com-error"),
                        ("release-timeout", "release-timeout"), ("success-after", "none")):
        destination = out / name
        command = ["--base", str(args.base), "--user", args.user, "--exe", str(args.exe),
                   "--cdb", str(args.cdb), "--com-cleanup-dll", str(args.com_cleanup_dll),
                   "--output", str(destination), "--fault", fault]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = run(command)
        if not (destination / "run.json").exists():
            results.append({"name": name, "exit_code": code, "expectation_met": False,
                            "error": output.getvalue()})
            break
        report = json.loads((destination / "run.json").read_text(encoding="utf-8"))
        clean = (report.get("cleanup_verified") is True and not report.get("first_chance_av_observed")
                 and not report.get("av_dump_saved") and not report.get("forced_cleanup")
                 and report.get("hashes_before") == PINNED and report.get("hashes_after") == PINNED
                 and report.get("server_exit_code") == 0 and report.get("debugger_exit_code") == 0)
        expected = (code == 0 and report["status"] == "passed" if fault == "none"
                    else code == 2 and report["status"] == "blocked")
        if fault == "com-error":
            expected = expected and any(e.get("name") == "error" and
                e.get("value", "").startswith("injected-com-error:") for e in read_events(destination))
            expected = expected and report.get("helper_exit_code") == 2
        if fault == "release-timeout":
            expected = expected and report.get("timeout_phase") == "shutdown" and report.get("cancellation_requested") is True
        row = {"name": name, "exit_code": code, "status": report["status"],
               "expectation_met": bool(expected and clean), "cleanup_verified": report.get("cleanup_verified"),
               "elapsed_seconds": report.get("elapsed_seconds"), "output": str(destination),
               "server_exit_code": report.get("server_exit_code"), "helper_exit_code": report.get("helper_exit_code"),
               "debugger_exit_code": report.get("debugger_exit_code"), "timeout_phase": report.get("timeout_phase")}
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        atomic_json(out / "qualification.json", {"complete": False, "runs": results})
        if not row["expectation_met"]:
            break
    accepted = len(results) == 4 and all(row["expectation_met"] for row in results)
    atomic_json(out / "qualification.json", {"complete": accepted,
        "scope": "coordinated-icpp-v1 fixed module suite only; ERT/P00-P08 remain open", "runs": results})
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
