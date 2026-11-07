"""Independently re-read a suite, its JUnit, hashes, child results and native cleanup."""

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(folder, native=False):
    report = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
    issues = []
    def require(condition, message):
        if not condition:
            issues.append(message)
    rows = report["scenarios"]
    layout = report.get("layout")
    require(layout in (None, "shared-runs-v1"), "unknown result layout")
    run_root = folder.parent / "runs" if layout == "shared-runs-v1" else folder / "runs"
    if layout:
        require(Path(report["runs_dir"]).resolve() == run_root.resolve(), "foreign run root")
    counts = {s: sum(r["status"] == s for r in rows) for s in ("passed", "failed", "blocked", "skipped")}
    require(report["complete"], "suite is incomplete")
    require(bool(rows), "suite has no scenarios")
    require(counts == report["counts"], "JSON counts differ")
    expected = "blocked" if report["cancelled"] or counts["blocked"] or counts["skipped"] else (
        "failed" if counts["failed"] else "passed")
    require(report["status"] == expected, "suite status differs")
    require(report["exit_code"] == {"passed": 0, "failed": 1, "blocked": 2}[expected], "exit code differs")
    require(digest(folder / "junit.xml") == report["junit"]["sha256"], "JUnit hash differs")
    xml = ET.parse(folder / "junit.xml").getroot()
    for element in (xml, xml.find("testsuite")):
        for key, value in {"tests": len(rows), "failures": counts["failed"], "errors": counts["blocked"],
                           "skipped": counts["skipped"]}.items():
            require(element.get(key) == str(value), f"JUnit {key} differs")
    cases = xml.findall("testsuite/testcase")
    require(len(cases) == len(rows), "JUnit testcase count differs")
    require(len({r["id"].casefold() for r in rows}) == len(rows), "duplicate scenario id")
    ids = [r["run_id"] for r in rows if r.get("run_id")]
    require(len(set(ids)) == len(ids), "reused run_id")
    for row, case in zip(rows, cases):
        prefix = row["id"] + ": "
        require(case.get("name") == row["id"], prefix + "JUnit name differs")
        tag = {"failed": "failure", "blocked": "error", "skipped": "skipped"}.get(row["status"])
        outcomes = [c.tag for c in case if c.tag in ("failure", "error", "skipped")]
        require(outcomes == ([tag] if tag else []), prefix + "JUnit status differs")
        output = json.loads(case.findtext("system-out"))
        require(output["run_id"] == row["run_id"] and output["report"] == row["report"],
                prefix + "JUnit linkage differs")
        evidence = row.get("report")
        if evidence is None:
            require(row["status"] in ("blocked", "skipped"), prefix + "missing result for a checked scenario")
            continue
        path = folder / evidence["path"]
        require(path.resolve() == (run_root / row["run_id"] / "run.json").resolve(),
                prefix + "foreign run path")
        require(digest(path) == evidence["sha256"], prefix + "run.json hash differs")
        child = json.loads(path.read_text(encoding="utf-8"))
        require(child["run_id"] == row["run_id"], prefix + "foreign run_id")
        require(row["status"] == child["status"] or row["status"] == "blocked", prefix + "status differs")
        require(row["platform_checked"] == child["platform_checked"], prefix + "platform claim differs")
        if native:
            platform = next(s for s in child["stages"] if s["stage"] == "platform_check")
            require(child["platform_checked"], prefix + "no native check")
            require(child["shutdown"]["cleanup_verified"] and child["shutdown"]["others_preserved"],
                    prefix + "shutdown not verified")
            copy = platform.get("base_copy") or {}
            require(copy.get("source_check", {}).get("unchanged"), prefix + "source preservation not verified")
            require(copy.get("removal", {}).get("removed"), prefix + "copy removal not verified")
            require(copy.get("lock", {}).get("released"), prefix + "lock release not verified")
            require(platform.get("base_list", {}).get("unchanged"), prefix + "base list preservation not verified")
    return {"status": "failed" if issues else "passed", "suite_status": report["status"],
            "suite_id": report["suite_id"], "counts": counts, "issues": issues,
            "suite_sha256": digest(folder / "suite.json"), "junit_sha256": digest(folder / "junit.xml")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    value = verify(args.folder.resolve(), args.native)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
