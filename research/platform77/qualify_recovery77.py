"""P08: two predeclared ok/syntax/ok cycles; compare content, stop on failure."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import re

from qualify_wait77 import expectation_met
from run_ert77 import main as run
from shutdown77 import atomic_json


def semantic_result(report, manifest):
    """Normalize only run identity and selected path, retaining diagnostics/value."""
    def normalize(text):
        # 7.7 prints compiler filenames in upper case on this Windows target.
        # Match only this exact path, case-insensitively; retain other text.
        return re.sub(re.escape(manifest["ert_path"]), lambda unused: "<ERT>", text,
                      flags=re.IGNORECASE).replace(manifest["run_id"], "<RUN>")
    return [{"name": row["name"], "status": row["status"], "expectation_met": row["expectation_met"],
             "actual": normalize(row["actual"]), "protocol": normalize(row["protocol"]),
             "diagnostics": row["diagnostics"]} for row in report["ert"]["operations"]]


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    for name in ("base", "exe", "cdb", "com-cleanup-dll", "identity-dll", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--user", required=True)
    args = parser.parse_args(argv)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    plan = [(str(Path("cycle-%02d" % cycle) / name), case) for cycle in (1, 2)
            for name, case in (("success-before", "ok"), ("syntax", "syntax"), ("success-after", "ok"))]
    rows, seen, contents = [], set(), {}
    summary = {"planned_runs": [{"name": name, "case": case} for name, case in plan], "runs": rows,
               "scope": "P08 two ok/syntax/ok cycles on the same pinned base; no retries"}
    atomic_json(out / "qualification.json", dict(summary, status="running", complete=False))
    for name, case in plan:
        destination = out / name
        command = ["--user", args.user, "--case", case, "--output", str(destination)]
        for key in ("base", "exe", "cdb", "com-cleanup-dll", "identity-dll"):
            command.extend(["--" + key, str(getattr(args, key.replace("-", "_")))])
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = run(command)
        row = {"name": name, "case": case, "exit_code": code, "expectation_met": False}
        if (destination / "run.json").exists():
            report = json.loads((destination / "run.json").read_text(encoding="utf-8"))
            row.update(status=report.get("status"), run_id=report.get("run_id"),
                       expectation_met=expectation_met(report, code, case, seen))
            if row["expectation_met"]:
                manifest = json.loads((destination / "ert-manifest.json").read_text(encoding="utf-8"))
                content = semantic_result(report, manifest)
                row["semantic_match"] = content == contents.setdefault(case, content)
                row["expectation_met"] = row["semantic_match"]
                row["shutdown_elapsed_seconds"] = report["shutdown_elapsed_seconds"]
                atomic_json(destination / "semantic-result.json", content)
            if isinstance(report.get("run_id"), str):
                seen.add(report["run_id"])
        else:
            row["error"] = captured.getvalue()
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        atomic_json(out / "qualification.json", dict(summary, status="running", complete=False))
        if not row["expectation_met"]:
            break
    accepted = len(rows) == len(plan) and all(row["expectation_met"] for row in rows)
    atomic_json(out / "qualification.json", dict(summary, status="passed" if accepted else "blocked", complete=accepted))
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
