"""Acceptance check of task 021: changed 1Cv7.MD modules on a copy of the base.

Needs local data that is not in Git: the probe evidence (.artifacts/stage21-md-probes-*.json, the
latest series of a case wins) and the runs they name (.artifacts/runs), the stand base's 1Cv7.MD,
optionally another base's 1Cv7.MD (read only). For every configuration: md-extract, md-build without
changes gives the template byte for byte, md-build with every module changed changes exactly the
modules, md-extract of the result gives the changed texts, lint reads all of them.

  python scripts/verify_md77.py --evidence .artifacts/stage21-md-probes-20261022-1.json
      --evidence ...-20261022-2.json --evidence ...-20261022-3.json --evidence ...-20261022-3b.json
      --md .local/bases/base-for-test/1Cv7.MD --md C:/…/test-base-surgut/1Cv7.MD
      --output .artifacts/stage21-acceptance-YYYYMMDD.json
"""

import argparse
import collections
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

from harness77 import lint77, md77  # noqa: E402
from harness77.ert_module import CompoundFile, decompress_module  # noqa: E402
from harness77.lint77 import cfb_paths  # noqa: E402

MARK = "\r\n// harness77 task 021\r\n"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native(evidence_paths):
    """The latest outcome of each case, re-read from its run: run.json is the one the evidence names."""
    latest = {}
    for path in evidence_paths:
        evidence = json.loads(Path(path).read_text(encoding="utf-8"))
        for case in evidence["cases"]:
            latest[case["id"]] = (case, Path(path).name, evidence["series"])
    rows = []
    for case_id, (case, source, series) in latest.items():
        issues = []
        run = ROOT / ".artifacts" / "runs" / case["run_id"] / "run.json"
        if not run.is_file() or sha256(run) != case["run_json_sha256"]:
            issues.append("run.json missing or changed")
        if case["verdict"] not in ("confirmed", "observed"):
            issues.append(f"verdict {case['verdict']}")
        copy = case.get("copy") or {}
        if not (copy.get("removal") or {}).get("removed") or copy.get("source_unchanged") is not True:
            issues.append("the copy was not removed or the stand base changed")
        if not all(series.values()):
            issues.append(f"series check {series}")
        rows.append({"id": case_id, "evidence": source, "verdict": case["verdict"], "expected": case.get("expected"),
                     "expected_error": case.get("expected_error"), "expected_reason": case.get("expected_reason"),
                     "value": case["observed"]["value"], "runtime_error": case["observed"]["runtime_error"],
                     "platform_reason": case["observed"]["platform_reason"],
                     "copy_seconds": copy.get("seconds"), "status": "failed" if issues else "passed", "issues": issues})
    return rows


def streams(data):
    compound = CompoundFile(data)
    paths = cfb_paths(compound)
    return {paths[e.entry_id]: compound.read_stream(e) for e in compound.directory_entries
            if e.object_type == 2 and e.entry_id in paths}


def round_trip(md):
    """md-extract, md-build without and with every module changed, md-extract again, lint."""
    md = Path(md).resolve(strict=True)
    before = sha256(md)
    result = {"md": md.name, "sha256": before}
    with tempfile.TemporaryDirectory(prefix="h77-v21-") as temp:
        temp = Path(temp)
        started = time.monotonic()
        extracted = md77.extract(md, temp / "modules")
        index = json.loads((temp / "modules" / md77.INDEX).read_text(encoding="utf-8"))
        files = collections.Counter(row["file"].split("/", 1)[0] if "/" in row["file"] else row["file"]
                                    for row in index["modules"])
        result.update(configuration=extracted["input"]["configuration"], modules=extracted["output"]["modules"],
                      by_folder=dict(sorted(files.items())), extract_seconds=round(time.monotonic() - started, 2))
        same = md77.build(md, temp / "modules", temp / "same.MD")
        result["unchanged_build_is_template"] = (temp / "same.MD").read_bytes() == md.read_bytes() and not same["rebuilt"]
        for row in index["modules"]:
            path = temp / "modules" / row["file"]
            path.write_bytes(path.read_bytes() + MARK.encode("utf-8"))
        started = time.monotonic()
        changed = md77.build(md, temp / "modules", temp / "changed.MD")
        result["build_seconds"] = round(time.monotonic() - started, 2)
        old, new = streams(md.read_bytes()), streams((temp / "changed.MD").read_bytes())
        paths = {row["path"] for row in index["modules"]}
        result["changed_modules"] = len(changed["changed"])
        result["every_module_changed"] = {row["path"] for row in changed["changed"]} == paths
        result["changed_texts"] = all(decompress_module(new[p]) == decompress_module(old[p]) + MARK.encode("cp1251")
                                      for p in paths)
        result["other_streams_identical"] = set(old) == set(new) and all(old[p] == new[p] for p in old if p not in paths)
        again = md77.extract(temp / "changed.MD", temp / "again")
        result["extract_of_build"] = again["output"]["modules"] == len(paths) and all(
            (temp / "again" / row["file"]).read_bytes() == (temp / "modules" / row["file"]).read_bytes()
            for row in index["modules"])
        with contextlib.redirect_stderr(io.StringIO()):
            sources = lint77.load_sources(temp / "changed.MD")
        result["lint_reads"] = sum(1 for s in sources if not s.module.startswith("TypedText/UserHelp")) == len(paths)
    result["template_unchanged"] = sha256(md) == before
    checks = ("unchanged_build_is_template", "every_module_changed", "changed_texts", "other_streams_identical",
              "extract_of_build", "lint_reads", "template_unchanged")
    result["status"] = "passed" if all(result[key] for key in checks) else "failed"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence", required=True, action="append", type=Path)
    parser.add_argument("--md", required=True, action="append", type=Path, help="a 1Cv7.MD, read only")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.path.lexists(args.output):
        parser.error(f"output exists: {args.output}")
    agreement = native(args.evidence)
    corpora = [round_trip(md) for md in args.md]
    result = {"schema_version": 1, "scope": "task 021 acceptance: native series and md round trips",
              "evidence": [{"name": p.name, "sha256": sha256(p)} for p in args.evidence],
              "native": agreement, "corpora": corpora,
              "status": "passed" if all(r["status"] == "passed" for r in agreement + corpora) else "failed"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
    for row in agreement:
        print(row["id"], row["status"], row["verdict"], row["value"], (row["runtime_error"] or "")[:60],
              (row["platform_reason"] or "")[:90], "; ".join(row["issues"]))
    for row in corpora:
        print(row["md"], row["configuration"], row["status"], row["modules"], row["by_folder"],
              "extract", row["extract_seconds"], "build", row["build_seconds"])
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
