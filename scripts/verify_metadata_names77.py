"""Acceptance check of task 018: lint L7712/L7713 against the native probes and the corpora.

Needs local data that is not in Git: the probe evidence (.artifacts/stage18-metadata-probes-*.json),
the stand base (1Cv7.MD, ExtForms, the FIO.ERT template); optionally another base's 1Cv7.MD
(read only) and the KUDiR corpus.

  python scripts/verify_metadata_names77.py --evidence .artifacts/stage18-metadata-probes-20261021.json
      --evidence ...-2.json --evidence ...-3.json --base .local/bases/base-for-test
      --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --foreign C:/…/test-base-surgut/1Cv7.MD --kudir research/kudir/corpus
      --output .artifacts/stage18-acceptance-YYYYMMDD.json
"""

import argparse
import collections
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "rules77"))

from harness77 import lint77  # noqa: E402
from probe_metadata77 import CASES, module_text  # noqa: E402

RULES = ("L7712", "L7713")
# Probes of names the base has: 1C runs them and lint stays silent.
PRESENT = {"g-enum-case", "g-enum-method", "g-const-method", "s-catalog-case"}
# A missing name outside the arguments the rule reads: 1C runs it, lint stays silent by design.
OUT_OF_SCOPE = {"s-literal"}


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
        native = row["observed"]
        present = case["id"].endswith("-control") or case["id"] in PRESENT
        if native["compile"] != "ok":
            issues.append(f"1C did not load the module: {native['compile']}")
        elif present or case["id"] in OUT_OF_SCOPE:
            if native["runtime"] != "ok":
                issues.append(f"1C failed on a name the base has: {native['runtime_error']}")
            if mine:
                issues.append(f"lint reports {[(d['rule'], d['line']) for d in mine]}")
        else:
            at_probe = [d for d in mine if d["rule"] == case["rule"] and d["line"] == row["probe_line"]]
            if not at_probe:
                issues.append(f"1C {native['runtime']}, lint has no {case['rule']} on line {row['probe_line']}")
            elif native["runtime"] == "error" and "прерывает" not in at_probe[0]["message"]:
                issues.append("1C failed at run time, the message says otherwise")
            elif native["runtime"] == "ok" and "ошибки не даёт" not in at_probe[0]["message"]:
                issues.append("1C ran it without an error, the message says otherwise")
        results.append({"id": case["id"], "rule": case["rule"],
                        "native": {k: native[k] for k in ("compile", "runtime", "value", "runtime_error")},
                        "lint": [f"{d['rule']}:{d['line']}" for d in mine], "evidence": source,
                        "run_id": row["run_id"], "status": "passed" if not issues else "failed", "issues": issues})
    for survey in ("n-survey", "a-survey"):
        row, source = observed.get(survey, (None, None))
        issues = []
        if row is None:
            issues.append("no native result")
        else:
            value = row["observed"]["value"] or ""
            if survey == "n-survey":
                parts = [p for p in value.split("|") if p]
                if len(parts) != 11:
                    issues.append(f"expected 11 classes, got {len(parts)}")
                for part in parts:
                    match = re.fullmatch(r"(\w+):1С=(\d+),прочитано=(\d+),лишние=,нет=", part)
                    if not match or match.group(2) != match.group(3):
                        issues.append(f"difference: {part[:300]}")
            elif not re.fullmatch(r"обращений=\d+;отказы=", value):
                issues.append(f"failures: {value[:300]}")
        results.append({"id": survey, "rule": "metadata", "native": row and row["observed"]["value"],
                        "evidence": source, "run_id": row and row["run_id"],
                        "status": "passed" if not issues else "failed", "issues": issues})
    return results


def lint_quietly(paths, metadata=None):
    """Sources of the paths (unreadable ones counted), analysed with the base's metadata."""
    sources, unreadable = [], []
    for path in paths:
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                loaded = lint77.load_sources(path)
        except Exception as error:  # a corpus form the reader refuses is counted, not fatal
            unreadable.append({"name": path.name, "error": str(error)[:200]})
            continue
        for source in loaded:
            if source.metadata is None:
                source.metadata = metadata
        sources += loaded
    return sources, unreadable


def summary(sources, report):
    """Counts per rule; findings guarded by Метаданные.<Класс>("Имя") in the same module are counted apart."""
    texts = {(s.path, s.module): s.text.casefold() for s in sources}
    rows = [d for d in report["diagnostics"] if d["rule"] in RULES]
    names, guarded, files = collections.Counter(), 0, set()
    for d in rows:
        name = re.search(r"нет (?:объекта|значения) (?:[\wЁё]+\.)?([\wЁё]+)", d["message"])
        name = name.group(1) if name else "?"
        names[name] += 1
        files.add(d["path"])
        if re.search(r"метаданные\.\w+\(\s*\"" + re.escape(name.casefold()) + "\"", texts[(d["path"], d["module"])]):
            guarded += 1
    return {"modules": report["modules"], "metadata_context_modules": report["metadata_context_modules"],
            "by_rule": {rule: sum(d["rule"] == rule for d in rows) for rule in RULES},
            "files_with_findings": len(files), "guarded_in_module": guarded,
            "top_names": names.most_common(15), "other_errors": report["errors"]}


def corpora(base, foreign, kudir):
    md_path = base / "1Cv7.MD"
    stand = lint77.load_metadata(md_path)
    result = {}
    sources, _ = lint_quietly([md_path])
    report = lint77.analyze(sources)
    result["stand_md_own_modules"] = summary(sources, report)
    result["stand_md_own_modules"]["findings"] = [
        {"module": d["module"], "line": d["line"], "rule": d["rule"], "message": d["message"][:160]}
        for d in report["diagnostics"] if d["rule"] in RULES]
    forms = sorted({p.resolve() for p in (base / "ExtForms").rglob("*") if p.suffix.casefold() == ".ert"}, key=str)
    bases = [("stand", stand)]
    if foreign:
        bases.append(("foreign", lint77.load_metadata(foreign)))
    for label, metadata in bases:
        sources, unreadable = lint_quietly(forms, metadata)
        entry = summary(sources, lint77.analyze(sources))
        entry.update(forms=len(forms), unreadable=unreadable, metadata=metadata.public())
        result[f"extforms_{label}"] = entry
    if kudir:
        manifest = json.loads((kudir / "manifest.json").read_text(encoding="utf-8"))
        entry = {}
        for case in manifest:
            folder = kudir / case
            erts = sorted(folder.glob("*.ert"))
            if not erts:
                continue
            sources, _ = lint_quietly(erts, stand)
            report = lint77.analyze(sources)
            entry[case] = {"findings": [f"{d['rule']}:{d['line']}" for d in report["diagnostics"] if d["rule"] in RULES]}
        result["kudir_on_stand"] = entry
    result["stand_metadata"] = stand.public() | {"objects": {k: len(v) for k, v in stand.objects().items()}}
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
    result = {"schema_version": 1, "scope": "task 018 acceptance: native agreement and corpora",
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
            print(name, entry["by_rule"], "files", entry["files_with_findings"], "guarded", entry["guarded_in_module"])
    print("kudir", corpus.get("kudir_on_stand"))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
