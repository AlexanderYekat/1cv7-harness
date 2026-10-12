"""Freeze already verified ERT bytes for an independent Configurator check.

This tool never starts 1C or treats missing manual evidence as success.
"""
import argparse
import json
import ntpath
from pathlib import Path
import shutil

from ert_probe77 import read_results, protocol_path
from shutdown77 import assess, atomic_json, sha256
from compiler_protocol77 import parse_protocol


CASES = ("ok", "syntax", "unused-syntax", "unused-name")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verified_run(folder, case):
    """Re-read original evidence rather than trusting a saved passed flag."""
    manifest = load(folder / "ert-manifest.json")
    lifecycle = load(folder / "run.json")
    if manifest.get("case") != case or lifecycle.get("case") != case:
        raise ValueError("donor case mismatch: " + case)
    shutdown = assess(folder, load(folder / "shutdown-manifest.json"), lifecycle)
    result = read_results(folder, manifest, lifecycle, shutdown)
    if (lifecycle.get("status") != "passed" or result != lifecycle.get("ert") or result.get("status") != "passed"
            or not result.get("expectations_met") or result.get("issues")):
        raise ValueError("donor evidence not verified: " + case)
    target = Path(manifest["ert_path"]).resolve(strict=True)
    relative = str(target.relative_to(folder))
    # The selected path must itself be covered by the source manifest.
    if manifest["sources"].get(relative) != sha256(target):
        raise ValueError("selected ERT is not pinned: " + case)
    expected = "passed" if case == "ok" else "failed"
    if [(row["name"], row["status"]) for row in result["operations"]] != [
            ("check", expected), ("execute", expected)]:
        raise ValueError("unexpected native operations: " + case)
    evidence = [folder / name for name in (
        "run.json", "ert-manifest.json", "shutdown-manifest.json",
        "ert-events.jsonl", "shutdown-events.jsonl")]
    evidence += [protocol_path(folder, manifest, name) for name in manifest["commands"]]
    evidence += [folder / name for name in manifest["sources"]]
    return target, {
        "case": case, "run_id": manifest["run_id"], "donor": str(folder),
        "donor_ert": str(target), "sha256": sha256(target),
        "expected_error_line": manifest["expected_error_line"],
        "native_operations": result["operations"],
        "donor_evidence": {str(p.relative_to(folder)): sha256(p) for p in evidence},
    }


def prepare(donors, output):
    if set(donors) != set(CASES):
        raise ValueError("exactly four reference cases are required")
    # Validate everything before creating the destination; never replace old runs.
    verified = [verified_run(Path(donors[case]).resolve(strict=True), case) for case in CASES]
    if len({row["run_id"] for _, row in verified}) != len(CASES):
        raise ValueError("duplicate donor run identity")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for number, (source, row) in enumerate(verified, 1):
        target = output / ("%02d-%s.ert" % (number, row["case"]))
        shutil.copyfile(source, target)
        if sha256(target) != row["sha256"]:
            raise ValueError("copied ERT differs from native donor")
        row["file"] = target.name
        row["reference_status"] = "not_run"
        rows.append(row)
    result = {"schema_version": 1, "scope": "P01-P03 same-byte Configurator comparison",
              "status": "awaiting_reference", "participation": "assisted",
              "cases": rows}
    atomic_json(output / "reference-manifest.json", result)
    return result


def verify_package(output):
    """Check frozen copies and original evidence; no manual acceptance inferred."""
    manifest = load(output / "reference-manifest.json")
    if [row["case"] for row in manifest["cases"]] != list(CASES):
        raise ValueError("reference case set/order mismatch")
    for row in manifest["cases"]:
        _, current = verified_run(Path(row["donor"]), row["case"])
        for key in current:
            if current[key] != row[key]:
                raise ValueError("donor changed: " + row["case"] + ": " + key)
        if Path(row["file"]).name != row["file"]:
            raise ValueError("reference file must be a basename")
        if sha256(output / row["file"]) != row["sha256"]:
            raise ValueError("reference ERT changed: " + row["case"])
    return {"package_integrity": "passed", "reference_acceptance": "not_assessed",
            "cases": len(CASES)}


def compare_reference(output):
    """Compare explicit assisted observations; never infer success from silence.

    The operator supplies observations.json after the GUI check. Screenshot
    hashes preserve that record; this function does not interpret image pixels.
    Session/base acceptance remains separate from this diagnostic comparison.
    """
    verify_package(output)
    observations = load(output / "observations.json")
    if observations.get("participation") != "assisted":
        raise ValueError("explicit assisted observation required")
    cases = observations["cases"]
    if [row["case"] for row in cases] != list(CASES):
        raise ValueError("observation case set/order mismatch")
    rows = []
    for frozen, observed in zip(load(output / "reference-manifest.json")["cases"], cases):
        if (observed["file"] != frozen["file"] or observed["sha256"] != frozen["sha256"]
                or ntpath.normcase(observed["selected_path"]) != ntpath.normcase(str(output / frozen["file"]))):
            raise ValueError("observed artifact mismatch: " + frozen["case"])
        screenshot = observed["screenshot"]
        if Path(screenshot).name != screenshot or sha256(output / screenshot) != observed["screenshot_sha256"]:
            raise ValueError("screenshot changed or invalid")
        imported = None
        if frozen["case"] == "ok":
            if (observed.get("status") != "passed" or observed.get("success_message")
                    != "Синтаксических ошибок не обнаружено!"):
                raise ValueError("explicit positive platform observation required")
            diagnostics = []
        else:
            protocol = Path(frozen["file"]).with_suffix(".txt")
            imported = parse_protocol((output / protocol).read_bytes(), encoding="cp1251")
            if (observed.get("status") != "failed" or imported["status"] != "failed"
                    or imported["protocol_sha256"] != observed["protocol_sha256"]):
                raise ValueError("complete unchanged reference error protocol required")
            for diagnostic in imported["diagnostics"]:
                if ntpath.normcase(diagnostic["file"]) != ntpath.normcase(observed["selected_path"]):
                    raise ValueError("reference diagnostic artifact mismatch")
            diagnostics = [{key: d[key] for key in ("line", "message")} for d in imported["diagnostics"]]
        comparisons = []
        for operation in frozen["native_operations"]:
            comparisons.append({"operation": operation["name"],
                "status_match": operation["status"] == observed["status"],
                "lines_match": [d["line"] for d in operation["diagnostics"]] == [d["line"] for d in diagnostics],
                "messages_match": operation["diagnostics"] == diagnostics,
                "native_diagnostics": operation["diagnostics"]})
        rows.append({"case": frozen["case"], "reference_status": observed["status"],
                     "reference_diagnostics": diagnostics, "protocol_import": imported,
                     "comparisons": comparisons})
    matched = all(all(c[k] for k in ("status_match", "lines_match", "messages_match"))
                  for row in rows for c in row["comparisons"])
    return {"comparison": "matched" if matched else "mismatched", "participation": "assisted",
            "scope": "P01-P03 module diagnostics; not full experiment acceptance",
            "observations_sha256": sha256(output / "observations.json"), "cases": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("prepare", allow_abbrev=False)
    for case in CASES:
        build.add_argument("--" + case, required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    verify = sub.add_parser("verify", allow_abbrev=False)
    verify.add_argument("output", type=Path)
    compare = sub.add_parser("compare", allow_abbrev=False)
    compare.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare({case: getattr(args, case.replace("-", "_")) for case in CASES}, args.output)
            result = {"status": result["status"], "output": str(args.output.resolve()), "cases": len(result["cases"])}
        elif args.command == "verify":
            result = verify_package(args.output.resolve(strict=True))
        else:
            result = compare_reference(args.output.resolve(strict=True))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("comparison") == "mismatched" else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
