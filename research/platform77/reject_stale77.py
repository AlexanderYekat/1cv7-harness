"""P07: challenge result validation with files from a real prior successful run.

This probe never launches 1C. New manifests/ERTs have fresh UUIDs, while the
purported run.json remains the old genuine success. Missing/empty/partial and
complete stale raw results must all be blocked by the current validators.
"""
import argparse
import json
from pathlib import Path
import shutil

from ert_probe77 import prepare, protocol_path, read_results
from shutdown77 import assess, atomic_json, sha256


def read_verified(out, case):
    report = json.loads((out / "run.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "ert-manifest.json").read_text(encoding="utf-8"))
    shutdown_manifest = json.loads((out / "shutdown-manifest.json").read_text(encoding="utf-8"))
    shutdown = assess(out, shutdown_manifest, report)
    result = read_results(out, manifest, report, shutdown)
    expected_issues = ["timeout_phase: ert-operation"] if case == "wait" else []
    if (manifest["case"] != case or result != report["ert"] or not result.get("expectations_met")
            or result["issues"] or shutdown["issues"] != expected_issues
            or (case == "wait" and result.get("timeout_verified") is not True)
            or (case != "wait" and result["status"] != "passed")):
        raise ValueError("donor or wait evidence did not independently validate")
    return report, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    parser.add_argument("--source-ok", required=True, type=Path)
    parser.add_argument("--after-wait", type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    source = args.source_ok.resolve(strict=True)
    donor, source_manifest = read_verified(source, "ok")
    waited = None
    if args.after_wait:
        waited, unused = read_verified(args.after_wait.resolve(strict=True), "wait")
        if waited["run_id"] == donor["run_id"] or waited["started_at"] <= donor["started_at"]:
            raise ValueError("the verified timeout must follow the successful donor")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_files = [source / name for name in ("run.json", "ert-events.jsonl")]
    source_files.extend(protocol_path(source, source_manifest, c) for c in ("check", "execute"))
    before = {p.name: sha256(p) for p in source_files}
    rows, ids = [], {donor["run_id"]}
    for variant in ("report-only", "stale-complete", "empty-current", "partial-current"):
        destination = out / variant
        destination.mkdir()
        manifest, shutdown_manifest = prepare(destination, args.template.resolve(strict=True), "ok", concurrent=True)
        if manifest["run_id"] in ids:
            raise ValueError("duplicate probe UUID")
        ids.add(manifest["run_id"])
        shutil.copyfile(source / "run.json", destination / "run.json")
        if variant != "report-only":
            shutil.copyfile(source / "ert-events.jsonl", destination / "ert-events.jsonl")
            for command in ("check", "execute"):
                shutil.copyfile(protocol_path(source, source_manifest, command), protocol_path(destination, manifest, command))
            if variant == "empty-current":
                (destination / "ert-events.jsonl").write_text("", encoding="utf-16")
            elif variant == "partial-current":
                events = (destination / "ert-events.jsonl").read_text(encoding="utf-16").splitlines()
                # A new writer has started this result but never completed it.
                (destination / "ert-events.jsonl").write_text(
                    events[0].replace(donor["run_id"], manifest["run_id"]) + "\n", encoding="utf-16")
        alleged = json.loads((destination / "run.json").read_text(encoding="utf-8"))
        shutdown = assess(destination, shutdown_manifest, alleged)
        result = read_results(destination, manifest, alleged, shutdown)
        rejected = (alleged["status"] == "passed" and result["status"] == "blocked"
                    and "lifecycle run_id mismatch" in result["issues"] and bool(shutdown["issues"]))
        row = {"variant": variant, "expected_run_id": manifest["run_id"], "stale_run_id": donor["run_id"],
               "alleged_status": alleged["status"], "status": result["status"], "expectation_met": rejected,
               "issues": result["issues"], "shutdown_issues": shutdown["issues"]}
        atomic_json(destination / "rejection.json", row)
        rows.append(row)
    unchanged = before == {p.name: sha256(p) for p in source_files}
    accepted = unchanged and all(row["expectation_met"] for row in rows)
    atomic_json(out / "qualification.json", {"status": "passed" if accepted else "blocked",
        "scope": "P07 offline file injection using native donor evidence; no new platform execution",
        "after_wait_run_id": waited["run_id"] if waited else None,
        "donor": str(source), "donor_sha256": before, "donor_unchanged": unchanged, "runs": rows})
    print(json.dumps({"status": "passed" if accepted else "blocked", "rejected": sum(r["expectation_met"] for r in rows),
                      "after_wait_run_id": waited["run_id"] if waited else None}, ensure_ascii=False))
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
