"""Acceptance check of task 009: root/cascade marking on the KUDiR corpus and the probes.

Needs local data that is not in Git: the KUDiR corpus (research/kudir/corpus) and the
native probe evidence (.artifacts/protocol/probes-*.json) with the run directories.

  python scripts/verify_triage77.py --corpus research/kudir/corpus
      --evidence .artifacts/protocol/probes-20261018.json --evidence ...-k14.json --evidence ...-run.json
      --output .artifacts/protocol/acceptance-YYYYMMDD.json
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# case: (ERT, expected roots, expected link lines, stop line or None)
CORPUS = {
    "p1-compile-errors": ("kudir_export.ert", [63, 66, 101, 107, 304], [], 311),
    "p2-compile-errors": ("kudir_export_agent.ert", [], [423, 428, 1012, 1045, 1229, 1443, 2393], None),
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def triage_cli(protocol, *module):
    completed = subprocess.run([sys.executable, "-m", "harness77", "triage", str(protocol), *map(str, module)],
                               capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    return completed.returncode, json.loads(completed.stdout)


def verify_corpus(corpus):
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for case, (ert, roots, links, stop) in CORPUS.items():
        folder, issues = corpus / case, []
        for name, expected in manifest[case].items():
            if name != "version" and sha256(folder / name) != expected:
                issues.append(f"hash mismatch: {name}")
        code, report = triage_cli(folder / "compiler-protocol.txt", "--ert", folder / ert)
        summary = report.get("summary", {})
        observed_roots = [d["line"] for d in report.get("diagnostics", []) if d["role"] == "root"]
        observed_links = [d["line"] for d in report.get("diagnostics", []) if d["role"] == "link"]
        if code != 1 or report.get("status") != "failed":
            issues.append(f"triage exit {code}, status {report.get('status')}")
        if not (report.get("module") or {}).get("verified"):
            issues.append(f"module not verified: {report.get('module')}")
        if observed_roots != roots:
            issues.append(f"roots {observed_roots}, expected {roots}")
        if observed_links != links:
            issues.append(f"links {observed_links}, expected {links}")
        if summary.get("compiled_through_line") != stop or summary.get("complete") != (stop is None):
            issues.append(f"stop {summary.get('compiled_through_line')}, expected {stop}")
        if summary.get("unknown"):
            issues.append(f"unknown messages: {summary['unknown']}")
        rows.append({"case": case, "status": "passed" if not issues else "failed", "issues": issues,
                     "summary": summary, "protocol_sha256": sha256(folder / "compiler-protocol.txt"),
                     "ert_sha256": sha256(folder / ert)})
    return rows


def verify_evidence(paths):
    rows = []
    for path in paths:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        for case in evidence["cases"]:
            issues = []
            if case["verdict"] not in ("confirmed", "observed"):
                issues.append(f"verdict {case['verdict']}: {case.get('problems')}")
            run_dir = ROOT / ".artifacts" / "runs" / case["run_id"]
            run_json = run_dir / "run.json"
            if not run_json.exists() or sha256(run_json) != case["run_json_sha256"]:
                issues.append("run.json missing or changed")
            shutdown = case["observed"].get("shutdown") or {}
            if not (shutdown.get("cleanup_verified") and shutdown.get("others_preserved")):
                issues.append(f"shutdown not verified: {shutdown}")
            protocol = case["observed"].get("protocol")
            if protocol is None or sha256(run_dir / protocol["path"]) != protocol["sha256"]:
                issues.append("native protocol missing or changed")
            rows.append({"evidence": path.name, "case": case["id"], "run_id": case["run_id"],
                         "verdict": case["verdict"], "status": "passed" if not issues else "failed",
                         "issues": issues})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--evidence", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.path.lexists(args.output):
        parser.error(f"output exists: {args.output}")
    corpus, probes = verify_corpus(args.corpus), verify_evidence(args.evidence)
    rows = corpus + probes
    result = {"schema_version": 1, "scope": "task 009 acceptance: KUDiR corpus marking and native probe evidence",
              "generated": datetime.datetime.now().astimezone().isoformat(),
              "status": "passed" if all(r["status"] == "passed" for r in rows) else "failed",
              "corpus": corpus, "probes": probes}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
    print(json.dumps({"status": result["status"], "corpus": [(r["case"], r["status"]) for r in corpus],
                      "probes": f"{sum(r['status'] == 'passed' for r in probes)}/{len(probes)}"}, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
