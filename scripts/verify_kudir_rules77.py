"""Acceptance check of task 005: KUDiR corpus and lint/1C 7.7 agreement on the probes.

Needs local data that is not in Git: the KUDiR corpus (research/kudir/corpus) and the
native probe evidence (.artifacts/stage5-rule-probes-*.json) with the probe template.

  python scripts/verify_kudir_rules77.py --corpus research/kudir/corpus
      --evidence .artifacts/stage5-rule-probes-20261015.json --evidence ...-rerun.json
      --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --output .artifacts/stage5-acceptance-YYYYMMDD.json
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "rules77"))

from harness77 import lint77  # noqa: E402
from probe_rules77 import CASES, module_text  # noqa: E402

CORPUS = {
    # case: (lines per rule that must be reported, rules that must stay silent)
    "p1-compile-errors": ({"L7708": {63, 66, 304}, "L7711": {101, 107}}, set()),
    "p2-compile-errors": ({"L7706": {423, 428, 1012, 1045, 1229, 1443, 2393}}, {"L7708", "L7711"}),
    "ok1-compiled-and-ran": ({}, {"L7708", "L7711", "L7710"}),
    "ok2-compiled-and-ran": ({}, {"L7708", "L7711", "L7710"}),
}
# OK1/OK2 still contain Опер.ПолучитьПроводку(н) in disabled code (KUDiR README section 11).
KNOWN_TRUE_WARNINGS = {"ok1-compiled-and-ran": {("L7709", 1396)}, "ok2-compiled-and-ran": {("L7709", 1396)},
                       "p1-compile-errors": {("L7709", 1356)}, "p2-compile-errors": {("L7709", 1404)}}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_corpus(corpus):
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    results = []
    for case, (required, silent) in CORPUS.items():
        folder, issues = corpus / case, []
        for name, expected in manifest[case].items():
            if name != "version" and sha256(folder / name) != expected:
                issues.append(f"hash mismatch: {name}")
        ert = next(folder.glob("*.ert"))
        report = lint77.analyze(lint77.load_sources(ert))
        by_rule = {}
        for d in report["diagnostics"]:
            by_rule.setdefault(d["rule"], set()).add(d["line"])
        for rule, lines in required.items():
            missing = sorted(lines - by_rule.get(rule, set()))
            if missing:
                issues.append(f"{rule} missing lines {missing}")
        if case == "p1-compile-errors" and by_rule.get("L7711", set()) != {101, 107}:
            issues.append(f"L7711 lines {sorted(by_rule.get('L7711', set()))}, expected exactly [101, 107]")
        for rule in silent:
            if by_rule.get(rule):
                issues.append(f"{rule} must be silent, found {sorted(by_rule[rule])}")
        if case.startswith("ok") and report["errors"]:
            issues.append(f"{report['errors']} errors on a module that compiled in 7.7")
        extra = {(d["rule"], d["line"]) for d in report["diagnostics"] if d["rule"] == "L7709"}
        if extra - KNOWN_TRUE_WARNINGS.get(case, set()):
            issues.append(f"unexpected L7709 {sorted(extra - KNOWN_TRUE_WARNINGS[case])}")
        results.append({"case": case, "ert_sha256": sha256(ert), "errors": report["errors"],
                        "warnings": report["warnings"],
                        "lines": {rule: sorted(lines) for rule, lines in sorted(by_rule.items())},
                        "status": "passed" if not issues else "failed", "issues": issues})
    return results


def native_agreement(evidence_paths, template):
    dialog = lint77.dialog_context(template)
    observed = {}
    for path in evidence_paths:
        for row in json.loads(Path(path).read_text(encoding="utf-8"))["cases"]:
            if row.get("verdict") != "blocked":  # infrastructure failures are rerun separately
                observed[row["id"]] = (row, Path(path).name)
    results = []
    for case in CASES:
        row, source = observed.get(case["id"], (None, None))
        if row is None:
            results.append({"id": case["id"], "status": "failed", "issues": ["no native result"]})
            continue
        text, issues = module_text(case), []
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != row["module_sha256"]:
            issues.append("probe module differs from the one run natively")
        lint = lint77.analyze([lint77.Source("module.1s", "", text, dialog=dialog)])
        mine = {(d["rule"], d["line"]) for d in lint["diagnostics"]}
        native = row["observed"]
        rule, line = case["rule"], row["probe_line"]
        if case["rule"] in ("L7708", "L7711"):
            flagged = any(r == rule for r, _ in mine)
            if native["compile"] == "error":
                for rejected in sorted({d["line"] for d in native["diagnostics"]}):
                    if (rule, rejected) not in mine:
                        issues.append(f"1C rejected line {rejected}, lint has no {rule} there")
                for diagnostic in native["diagnostics"]:
                    name = re.search(r"\((\w+)\)$", diagnostic["message"])
                    if rule == "L7711" and name and not any(
                            d["rule"] == "L7711" and name.group(1) in d["message"] for d in lint["diagnostics"]):
                        issues.append(f"lint does not name {name.group(1)}")
            elif flagged:
                issues.append(f"1C accepted the module, lint reports {rule}")
        elif rule == "L7709":
            flagged = (rule, line) in mine
            # ТаблицаЗначений.КоличествоСтрок(1) runs; the merged catalog limit for the name is 1.
            if native["runtime"] == "error" and not flagged:
                issues.append("1C failed at run time, lint has no L7709")
            if native["runtime"] == "ok" and flagged:
                issues.append("1C ran it, lint reports L7709")
        elif rule == "L7710":
            flagged = any(r == rule for r, _ in mine)
            if not flagged:
                issues.append("long line not reported")
            if native["compile"] != "ok":
                issues.append("Enterprise mode rejected a long line")
        results.append({"id": case["id"], "rule": rule, "native": {k: native[k] for k in ("compile", "runtime")},
                        "native_messages": [d["message"] for d in native["diagnostics"]] + (
                            [native["runtime_error"]] if native["runtime_error"] else []),
                        "lint": sorted(f"{r}:{n}" for r, n in mine if r in ("L7708", "L7709", "L7710", "L7711")),
                        "evidence": source, "run_id": row["run_id"],
                        "status": "passed" if not issues else "failed", "issues": issues})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--evidence", required=True, action="append", type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.path.lexists(args.output):
        parser.error(f"output exists: {args.output}")
    corpus = verify_corpus(args.corpus)
    agreement = native_agreement(args.evidence, args.template)
    summary = {"schema_version": 1, "scope": "task 005 acceptance: KUDiR corpus and native agreement",
               "lint_version": lint77.VERSION, "catalog": lint77.load_catalog().provenance,
               "evidence": [{"name": p.name, "sha256": sha256(p)} for p in args.evidence],
               "corpus": corpus, "native_agreement": agreement,
               "status": "passed" if all(r["status"] == "passed" for r in corpus + agreement) else "failed"}
    with open(args.output, "x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=1)
    for row in corpus + agreement:
        print(row.get("case") or row.get("id"), row["status"], "; ".join(row["issues"]))
    print("status", summary["status"])
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
