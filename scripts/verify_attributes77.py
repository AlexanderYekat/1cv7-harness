"""Acceptance check of task 019: lint L7714 and the Метаданные guards against the native probes and the corpora.

Needs local data that is not in Git: the probe evidence (.artifacts/stage19-attribute-probes-*.json),
the stand base (1Cv7.MD, ExtForms, the FIO.ERT template); optionally another base's 1Cv7.MD
(read only) and the KUDiR corpus.

  python scripts/verify_attributes77.py --evidence .artifacts/stage19-attribute-probes-20261021.json
      --base .local/bases/base-for-test --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --foreign C:/…/test-base-surgut/1Cv7.MD --kudir research/kudir/corpus
      --output .artifacts/stage19-acceptance-YYYYMMDD.json
"""

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "rules77"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness77 import lint77  # noqa: E402
from probe_attributes77 import CASES  # noqa: E402
from probe_rules77 import module_text  # noqa: E402
from verify_metadata_names77 import lint_quietly  # noqa: E402

RULES = ("L7712", "L7713", "L7714")
# What lint says on the probe line, fixed with the cases; any other probe: no L7712-L7714 at all.
REPORTED = {"r-catalog": "L7714", "r-catalog-write": "L7714", "r-catalog-new": "L7714",
            "r-catalog-method": "L7714", "r-document": "L7714", "r-document-write": "L7714",
            "r-chain": "L7714", "g-after": "L7713", "c-contract": "L7714", "c-goods": "L7714"}
GUARDED = {"g-catalog", "g-attribute", "g-constant", "g-else"}
MISSING_FIELD = "Поле агрегатного объекта не обнаружено"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_agreement(evidence_paths, template, metadata):
    dialog = lint77.dialog_context(template)
    observed = {}
    for path in evidence_paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data["metadata_sha256"] != metadata.sha256:
            raise SystemExit(f"{path}: probes ran on another 1Cv7.MD")
        for row in data["cases"]:
            if row.get("verdict") != "blocked":
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
        lint = lint77.analyze([lint77.Source("module.1s", "", text, dialog=dialog, metadata=metadata)])
        mine = [d for d in lint["diagnostics"] if d["rule"] in RULES]
        native, rule = row["observed"], REPORTED.get(case["id"])
        error = native["runtime_error"] or ""
        if native["compile"] != "ok":
            issues.append(f"1C did not load the module: {native['compile']}")
        elif rule:
            at_probe = [d for d in mine if d["rule"] == rule and d["line"] == row["probe_line"]]
            if not at_probe:
                issues.append(f"lint has no {rule} on line {row['probe_line']}")
            elif native["runtime"] != "error":
                issues.append(f"lint reports {rule}, 1C ran the line: {native['value']}")
            elif rule == "L7714" and MISSING_FIELD not in error:
                issues.append(f"1C failed otherwise: {error}")
            elif "прерывает" not in at_probe[0]["message"]:
                issues.append("1C failed at run time, the message says otherwise")
        else:
            if mine:
                issues.append(f"lint reports {[(d['rule'], d['line']) for d in mine]}")
            if MISSING_FIELD in error:
                issues.append(f"1C misses a name lint takes as present: {error}")
            if case["id"] in GUARDED and (native["runtime"] != "ok" or lint["metadata_guarded"] < 1):
                issues.append(f"guarded line: 1C {native['runtime']}, lint guarded {lint['metadata_guarded']}")
        results.append({"id": case["id"], "rule": case["rule"],
                        "native": {k: native[k] for k in ("compile", "runtime", "value", "runtime_error")},
                        "lint": [f"{d['rule']}:{d['line']}" for d in mine], "guarded": lint["metadata_guarded"],
                        "evidence": source, "run_id": row["run_id"], "verdict": row["verdict"],
                        "status": "passed" if not issues else "failed", "issues": issues})
    for survey in ("n-attributes", "a-attributes"):
        row, source = observed.get(survey, (None, None))
        issues = []
        if row is None:
            issues.append("no native result")
        else:
            value = row["observed"]["value"] or ""
            pattern = r"реквизитов=\d+;расхождения=" if survey == "n-attributes" else r"обращений=\d+;отказы=\|.*"
            if row["verdict"] != "confirmed" or not re.fullmatch(pattern, value, re.S):
                issues.append(f"{row['verdict']}: {value[:300]} {row['observed']['runtime_error'] or ''}")
        results.append({"id": survey, "rule": "metadata", "native": row and row["observed"]["value"],
                        "evidence": source, "run_id": row and row["run_id"],
                        "status": "passed" if not issues else "failed", "issues": issues})
    return results


def summary(sources):
    """Counts per rule with and without the guards; the L7714 findings with their object."""
    with mock.patch.object(lint77, "metadata_guards", lambda tokens: []):
        unguarded = lint77.analyze(sources)
    report = lint77.analyze(sources)
    rows = [d for d in report["diagnostics"] if d["rule"] in RULES]
    names = collections.Counter(d["message"].split(":")[0].split(".", 1)[-1] for d in rows if d["rule"] == "L7714")
    return {"modules": report["modules"], "metadata_context_modules": report["metadata_context_modules"],
            "by_rule": {rule: sum(d["rule"] == rule for d in rows) for rule in RULES},
            "by_rule_without_guards": {rule: sum(d["rule"] == rule for d in unguarded["diagnostics"])
                                       for rule in RULES},
            "metadata_guarded": report["metadata_guarded"], "attributes_checked": report["attributes_checked"],
            "files_with_findings": len({d["path"] for d in rows}), "top_attributes": names.most_common(15),
            "attribute_findings": [{"path": Path(d["path"]).name, "module": d["module"], "line": d["line"],
                                    "message": d["message"][:200]} for d in rows if d["rule"] == "L7714"],
            "other_errors": report["errors"]}


def corpora(base, foreign, kudir):
    md_path = base / "1Cv7.MD"
    stand = lint77.load_metadata(md_path)
    result = {"stand_md_own_modules": summary(lint_quietly([md_path])[0])}
    if foreign:
        result["foreign_md_own_modules"] = summary(lint_quietly([foreign])[0])
    forms = sorted({p.resolve() for p in (base / "ExtForms").rglob("*") if p.suffix.casefold() == ".ert"}, key=str)
    bases = [("stand", stand)] + ([("foreign", lint77.load_metadata(foreign))] if foreign else [])
    for label, metadata in bases:
        sources, unreadable = lint_quietly(forms, metadata)
        entry = summary(sources)
        entry.pop("attribute_findings")
        entry.update(forms=len(forms), unreadable=len(unreadable), metadata=metadata.public())
        result[f"extforms_{label}"] = entry
    if kudir:
        manifest = json.loads((kudir / "manifest.json").read_text(encoding="utf-8"))
        entry = {}
        for case in manifest:
            erts = sorted((kudir / case).glob("*.ert"))
            if erts:
                sources, _ = lint_quietly(erts, stand)
                report = lint77.analyze(sources)
                entry[case] = {"findings": [f"{d['rule']}:{d['line']}" for d in report["diagnostics"]
                                            if d["rule"] in RULES], "attributes_checked": report["attributes_checked"]}
        result["kudir_on_stand"] = entry
    attributes = {cls: sum(len(stand.attributes(cls, kind)) for kind in stand.objects()[cls].values())
                  for cls in ("Справочник", "Документ", "Регистр")}
    result["stand_metadata"] = stand.public() | {"attributes": attributes}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence", required=True, action="append", type=Path)
    parser.add_argument("--base", required=True, type=Path, help="stand base directory (1Cv7.MD, ExtForms)")
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--foreign", type=Path, help="1Cv7.MD of another base, read only")
    parser.add_argument("--kudir", type=Path, help="KUDiR corpus (research/kudir/corpus)")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.path.lexists(args.output):
        parser.error(f"output exists: {args.output}")
    metadata = lint77.load_metadata(args.base / "1Cv7.MD")
    agreement = native_agreement(args.evidence, args.template, metadata)
    corpus = corpora(args.base, args.foreign, args.kudir)
    result = {"schema_version": 1, "scope": "task 019 acceptance: native agreement and corpora",
              "lint_version": lint77.VERSION,
              "evidence": [{"name": p.name, "sha256": sha256(p)} for p in args.evidence],
              "native_agreement": agreement, "corpora": corpus,
              "status": "passed" if all(r["status"] == "passed" for r in agreement) else "failed"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
    for row in agreement:
        print(row["id"], row["status"], "; ".join(row["issues"]))
    for name, entry in corpus.items():
        if isinstance(entry, dict) and "by_rule" in entry:
            print(name, entry["by_rule"], "without guards", entry["by_rule_without_guards"],
                  "checked", entry["attributes_checked"], "files", entry["files_with_findings"])
    print("kudir", corpus.get("kudir_on_stand"))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
