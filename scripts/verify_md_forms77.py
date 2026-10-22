"""Acceptance check of task 022: forms of 1Cv7.MD by description on a copy of the base.

Needs local data that is not in Git: the probe evidence (.artifacts/stage22-md-forms-*.json, the latest
series of a case wins) and the runs they name (.artifacts/runs), the stand base's 1Cv7.MD, optionally
another base's 1Cv7.MD (read only). For every configuration: md-extract describes the forms, md-build
without changes gives the template byte for byte, md-build with the caption of every described form
changed changes exactly their dialogs, md-extract of the result gives the changed descriptions, lint
reads the result.

  python scripts/verify_md_forms77.py --evidence .artifacts/stage22-md-forms-20261022-0.json
      --evidence ...-1.json --evidence ...-2.json --evidence ...-3.json
      --md .local/bases/base-for-test/1Cv7.MD --md C:/…/test-base-surgut/1Cv7.MD
      --output .artifacts/stage22-acceptance-YYYYMMDD.json
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

from harness77 import form77, lint77, md77  # noqa: E402
from harness77.ert_module import CompoundFile, decode_dialog  # noqa: E402
from harness77.lint77 import cfb_paths  # noqa: E402

MARK = " 77"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native(evidence_paths):
    """The latest outcome of each case, its run.json re-read: the one the evidence names."""
    latest = {}
    for path in evidence_paths:
        evidence = json.loads(Path(path).read_text(encoding="utf-8"))
        for case in evidence["cases"]:
            latest[case["id"]] = (case, Path(path).name, evidence["series"])
    rows = []
    for case_id, (case, source, series) in latest.items():
        issues, observed = [], case.get("observed") or {}
        run = ROOT / ".artifacts" / "runs" / case["run_id"] / "run.json"
        if not run.is_file() or sha256(run) != case["run_json_sha256"]:
            issues.append("run.json missing or changed")
        if case["verdict"] not in ("confirmed", "observed"):
            issues.append(f"verdict {case['verdict']}")
        copy = observed.get("copy") or {}
        if not (copy.get("removal") or {}).get("removed") or copy.get("source_unchanged") is not True:
            issues.append("the copy was not removed or the stand base changed")
        if not all(series.values()):
            issues.append(f"series check {series}")
        tests = {row["name"]: (row["status"], row["value"]) for row in observed.get("tests") or []}
        rows.append({"id": case_id, "evidence": source, "verdict": case["verdict"], "form_object": case.get("form_object"),
                     "run_status": observed.get("run_status"), "platform_reason": observed.get("platform_reason"),
                     "tests": tests, "visual": [(v["name"], v["status"], v.get("diff_pixels")) for v in observed.get("visual") or []],
                     "status": "failed" if issues else "passed", "issues": issues})
    return rows


def dialogs(data):
    compound = CompoundFile(data)
    paths = cfb_paths(compound)
    return {paths[e.entry_id]: compound.read_stream(e) for e in compound.directory_entries
            if e.object_type == 2 and e.entry_id in paths}


def round_trip(md):
    """md-extract, md-build without changes and with every described form's caption changed, md-extract again."""
    md = Path(md).resolve(strict=True)
    before = sha256(md)
    result = {"md": md.name, "sha256": before}
    with tempfile.TemporaryDirectory(prefix="h77-v22-") as temp:
        temp = Path(temp)
        started = time.monotonic()
        extracted = md77.extract(md, temp / "x")
        index = json.loads((temp / "x" / md77.INDEX).read_text(encoding="utf-8"))
        described = [row for row in index["forms"] if row["described"]]
        result.update(configuration=extracted["input"]["configuration"], modules=extracted["output"]["modules"],
                      forms=len(index["forms"]), described=len(described),
                      not_described=[row["path"] for row in extracted["forms_not_described"]],
                      extract_seconds=round(time.monotonic() - started, 2))
        same = md77.build(md, temp / "x", temp / "same.MD")
        result["unchanged_build_is_template"] = (temp / "same.MD").read_bytes() == md.read_bytes() and not same["rebuilt"]
        expected, originals = {}, {}
        for row in described:
            path = temp / "x" / row["file"]
            originals[row["file"]] = path.read_bytes()
            description = json.loads(originals[row["file"]].decode("utf-8"))
            description["form"]["caption"] += MARK
            path.write_text(json.dumps(description, ensure_ascii=False), encoding="utf-8")
            expected[row["file"]] = description
        # A longer caption may move a short dialog's length prefix from one byte to 0xFF + uint16: md-build refuses
        # such a change (not checked in 1C 7.7, task 008). Those forms keep their description and are listed.
        result["prefix_refused"], attempt = [], 0
        while True:
            attempt += 1
            started = time.monotonic()
            try:
                changed = md77.build(md, temp / "x", temp / f"changed{attempt}.MD")
                break
            except md77.ErtError as error:
                file, _, message = str(error).partition(": ")
                if file not in expected or "Заголовок длины диалога" not in message or attempt > 20:
                    raise
                result["prefix_refused"].append({"file": file, "error": message})
                (temp / "x" / file).write_bytes(originals.pop(file))
                del expected[file]
        result["build_seconds"] = round(time.monotonic() - started, 2)
        old, new = dialogs(md.read_bytes()), dialogs((temp / f"changed{attempt}.MD").read_bytes())
        paths = {row["path"] for row in described if row["file"] in expected}
        result["changed_forms"] = len(changed["changed_forms"])
        result["every_form_changed"] = {row["path"] for row in changed["changed_forms"]} == paths
        result["captions"] = all(form77.describe(decode_dialog(new[p]))["form"]["caption"]
                                 == form77.describe(decode_dialog(old[p]))["form"]["caption"] + MARK for p in paths)
        result["other_streams_identical"] = set(old) == set(new) and all(old[p] == new[p] for p in old if p not in paths)
        md77.extract(temp / f"changed{attempt}.MD", temp / "again")
        result["extract_of_build"] = all(
            {k: v for k, v in json.loads((temp / "again" / file).read_text(encoding="utf-8")).items()
             if k != "template_dialog_sha256"} == {k: v for k, v in description.items() if k != "template_dialog_sha256"}
            for file, description in expected.items())
        with contextlib.redirect_stderr(io.StringIO()):
            result["lint_reads"] = bool(lint77.load_sources(temp / f"changed{attempt}.MD"))
    result["template_unchanged"] = sha256(md) == before
    checks = ("unchanged_build_is_template", "every_form_changed", "captions", "other_streams_identical",
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
    result = {"schema_version": 1, "scope": "task 022 acceptance: native series and form round trips",
              "evidence": [{"name": p.name, "sha256": sha256(p)} for p in args.evidence],
              "native": agreement, "corpora": corpora,
              "status": "passed" if all(r["status"] == "passed" for r in agreement + corpora) else "failed"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
    for row in agreement:
        print(row["id"], row["status"], row["verdict"], row["run_status"], (row["platform_reason"] or "")[:80],
              row["tests"], row["visual"], "; ".join(row["issues"]))
    for row in corpora:
        print(row["md"], row["configuration"], row["status"], row["modules"], row["forms"], row["described"],
              "extract", row["extract_seconds"], "build", row["build_seconds"],
              {k: row[k] for k in ("unchanged_build_is_template", "every_form_changed", "captions",
                                   "other_streams_identical", "extract_of_build", "lint_reads")})
    print("status", result["status"])
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
