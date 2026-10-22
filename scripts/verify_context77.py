"""Acceptance check of task 020: lint's context of 1Cv7.MD modules and forms against the native probes and corpora.

Needs local data that is not in Git: the probe evidence (.artifacts/stage20-context-probes-*.json, the
latest series of a case wins), the runs they name (.artifacts/runs: the message window of the batches),
the stand base (1Cv7.MD, ExtForms, the FIO.ERT template); optionally another base's 1Cv7.MD (read only)
and the KUDiR corpus. The probe work directory is rebuilt as the probes built it.

  python scripts/verify_context77.py --evidence .artifacts/stage20-context-probes-20261021.json
      --evidence ...-20261021-2.json --evidence ...-20261022-3.json --evidence ...-20261022-4.json
      --base .local/bases/base-for-test --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT
      --work .local/stage20-native --foreign C:/…/test-base-surgut/1Cv7.MD --kudir research/kudir/corpus
      --output .artifacts/stage20-acceptance-YYYYMMDD.json
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

from harness77 import ert_module as ert  # noqa: E402
from harness77 import lint77  # noqa: E402
from probe_context77 import FOLDER, PROCEDURE, build_cases  # noqa: E402
from probe_rules77 import PROBE, module_text  # noqa: E402
from verify_metadata_names77 import lint_quietly  # noqa: E402

UNDECLARED = re.compile(r"Переменная не определена \((\w+)\)")
MISSING_FIELD = "Поле агрегатного объекта не обнаружено"
# Snippets the x-* cases compile through ВыполняемыйМодуль: (owner of the context or None, code).
SNIPPETS = {"x-api": (("Документ", "АвансовыйОтчет"), ""), "x-attribute": (("Документ", "АвансовыйОтчет"), "Х = Сотрудник;"),
            "x-missing": (("Документ", "АвансовыйОтчет"), "Х = Нет77;"), "x-no-context": (None, "Х = Сотрудник;"),
            "x-builtin": (("Документ", "АвансовыйОтчет"), "Х = НомерДок; Х = ДатаДок;"),
            "x-common": (("Документ", "АвансовыйОтчет"), "Х = Комментарий;"),
            "x-table": (("Документ", "АвансовыйОтчет"), "Х = КомуЗаЧто;"),
            "x-catalog": (("Справочник", "Банки"), "Х = КоррСчет; Х = Код; Х = Наименование;"),
            "x-catalog-missing": (("Справочник", "Банки"), "Х = Нет77;")}
# ВыполнитьМодуль answers 1 once execution starts, a failing line included: no check of the chain.
INFORMATIONAL = {"x-chain"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence_rows(paths, metadata):
    rows = {}
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data["metadata_sha256"] != metadata.sha256:
            raise SystemExit(f"{path}: probes ran on another 1Cv7.MD")
        for row in data["cases"]:
            if row.get("verdict") != "blocked":
                rows[row["id"]] = (row, Path(path).name)
    return rows


def messages_by_module(run_id):
    """Compile errors of a batch from the run's message window, by the module mark before them."""
    text = (ROOT / ".artifacts" / "runs" / run_id / "native" / "Протоколы проверки" / "execute.txt").read_bytes()
    found, current = collections.defaultdict(list), None
    for line in text.decode("cp1251", "replace").splitlines():
        mark = re.search(r"harness77-module:(\S+)", line)
        if mark:
            current = mark.group(1)
            continue
        error = re.search(r"\{\((\d+)\)\}: (.+)", line)
        if error:
            found[current].append((int(error.group(1)), error.group(2).strip()))
    return found


def lint_l7711(source):
    return sorted({(d["line"], d["message"]) for d in lint77.analyze([source])["diagnostics"] if d["rule"] == "L7711"})


def batch_agreement(row, sources, linted):
    """1C's undeclared names per module against lint's L7711 on that module, the whole 1Cv7.MD linted."""
    native = messages_by_module(row["run_id"])
    results = []
    for module, source in sources.items():
        names = sorted({UNDECLARED.search(m).group(1).casefold() for _, m in native.get(module, []) if UNDECLARED.search(m)})
        mine = sorted(linted.get(source.module, set()))
        status, note = "passed", None
        if names != mine:
            parsed = lint77.parse(source)
            # A dialog control named like a procedure of the module: the probe could not declare it.
            gap = [n for n in set(names) - set(mine) if n in (source.dialog or ()) and n in parsed.symbols]
            if set(names) - set(mine) == set(gap) and not set(mine) - set(names):
                note = f"не объявлены пробой (элемент диалога и процедура модуля): {gap}"
            else:
                status = "failed"
        if names or mine or status != "passed":
            results.append({"module": module, "native": names, "lint": mine, "status": status, "note": note,
                            "other_errors": sorted({re.sub(r"\(.*\)", "(…)", m) for _, m in native.get(module, [])
                                                   if not UNDECLARED.search(m)})})
    return results


def native_agreement(evidence, work, template, metadata, base):
    rows = evidence_rows(evidence, metadata)
    args = argparse.Namespace(work=work, metadata=base / "1Cv7.MD")
    md_sources, everything = {}, lint77.load_sources(base / "1Cv7.MD")
    for source in everything:
        match = FOLDER.match(source.module)
        if match:
            md_sources[f"{match.group(1)}_{match.group(2)}"] = source
    # As lint checks a configuration: every module with the exports of its global module.
    linted = collections.defaultdict(set)
    for d in lint77.analyze(everything)["diagnostics"]:
        if d["rule"] == "L7711":
            linted[d["module"]].add(UNDECLARED.search(d["message"]).group(1).casefold())
    results = []
    for case in build_cases(args):
        row, name = rows.get(case["id"], (None, None))
        if row is None:
            results.append({"id": case["id"], "status": "failed", "issues": ["no native result"]})
            continue
        text, issues, extra = module_text(case), [], {}
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != row["module_sha256"]:
            issues.append("probe module differs from the one run natively")
        native = row["observed"]
        diagnostics = [d.get("message", "") for d in native["diagnostics"]]
        if case["id"] in ("b-transact", "b-forms"):
            modules = re.findall(r'harness77-module:(\w+)"', text)
            agreement = batch_agreement(row, {m: md_sources[m] for m in modules}, linted)
            extra["modules"] = agreement
            issues += [f"{a['module']}: 1С {a['native']}, lint {a['lint']}" for a in agreement if a["status"] != "passed"]
        elif case["id"] in SNIPPETS:
            owner, code = SNIPPETS[case["id"]]
            source = lint77.Source("snippet.1s", "", PROCEDURE.format("    " + code), dialog=frozenset(),
                                   metadata=metadata, owner=owner)
            mine = lint_l7711(source)
            failed = native["value"] == "0"
            if failed != bool(mine):
                issues.append(f"1C compile {'0' if failed else 'ok'}, lint {mine}")
        elif case["id"] in INFORMATIONAL:
            extra["informational"] = "ВыполнитьМодуль отвечает 1, если исполнение началось, и при ошибке в строке"
        else:
            own = Path(case["template"]) if case.get("template") else template
            dialog = lint77.ert_dialog(ert.CompoundFile(own.read_bytes()))
            report = lint77.analyze([lint77.Source("module.1s", "", text, dialog=dialog, metadata=metadata)])
            at_probe = [d for d in report["diagnostics"] if d["line"] == row["probe_line"] and d["rule"] in ("L7711", "L7714")]
            if native["compile"] == "error":
                names = {m.group(1) for m in map(UNDECLARED.search, diagnostics) if m}
                reported = [d["message"] for d in at_probe if d["rule"] == "L7711"]
                if not names or not all(any(f"({n})" in m for m in reported) for n in names):
                    issues.append(f"1C refused {diagnostics}, lint at the probe {[d['rule'] for d in at_probe]}")
            elif native["runtime"] == "error" and MISSING_FIELD in (native["runtime_error"] or ""):
                if not any(d["rule"] == "L7714" for d in at_probe):
                    issues.append("1C failed on a missing attribute, lint has no L7714 at the probe")
            elif native["compile"] == "ok" and at_probe:
                issues.append(f"1C compiled, lint reports {[d['rule'] for d in at_probe]}")
            extra["lint"] = [f"{d['rule']}:{d['line']}" for d in at_probe]
        results.append({"id": case["id"], "evidence": name, "run_id": row["run_id"], "verdict": row["verdict"],
                        "native": {k: native[k] for k in ("compile", "runtime", "value", "runtime_error")}
                        | {"diagnostics": diagnostics[:5]},
                        "status": "passed" if not issues else "failed", "issues": issues, **extra})
    return results


def summary(sources):
    report = lint77.analyze(sources)
    rows = [d for d in report["diagnostics"] if d["rule"] in ("L7711", "L7714")]
    folder = collections.Counter()
    for d in rows:
        match = FOLDER.match(d["module"])
        folder[(d["rule"], match.group(1) if match else Path(d["path"]).suffix)] += 1
    return {"modules": report["modules"], "form_context_modules": report["form_context_modules"],
            "md_context_modules": report["md_context_modules"], "attributes_checked": report["attributes_checked"],
            "by_rule": {rule: sum(d["rule"] == rule for d in rows) for rule in ("L7711", "L7714")},
            "by_folder": {f"{rule}/{name}": count for (rule, name), count in sorted(folder.items())},
            "findings": [{"path": Path(d["path"]).name, "module": d["module"], "line": d["line"], "rule": d["rule"],
                          "message": d["message"][:160]} for d in rows][:200]}


def corpora(base, foreign, kudir):
    result = {"stand_md_own_modules": summary(lint_quietly([base / "1Cv7.MD"])[0])}
    if foreign:
        result["foreign_md_own_modules"] = summary(lint_quietly([foreign])[0])
    forms = sorted({p.resolve() for p in (base / "ExtForms").rglob("*") if p.suffix.casefold() == ".ert"}, key=str)
    sources, unreadable = lint_quietly(forms)
    entry = summary(sources)
    entry.pop("findings")
    with mock.patch.object(lint77, "form_table", lambda contents, profile: None):
        without = lint77.analyze(lint_quietly(forms)[0])
    entry["L7711_without_table_areas"] = sum(d["rule"] == "L7711" for d in without["diagnostics"])
    entry.update(forms=len(forms), unreadable=len(unreadable))
    result["extforms"] = entry
    if kudir:
        manifest = json.loads((kudir / "manifest.json").read_text(encoding="utf-8"))
        result["kudir"] = {case: sorted(f"{d['rule']}:{d['line']}" for d in lint77.analyze(
            lint_quietly(sorted((kudir / case).glob("*.ert")))[0])["diagnostics"] if d["rule"] in ("L7711", "L7714"))
            for case in manifest if list((kudir / case).glob("*.ert"))}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence", required=True, action="append", type=Path)
    parser.add_argument("--base", required=True, type=Path, help="stand base directory (1Cv7.MD, ExtForms)")
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path, help="the probes' work directory")
    parser.add_argument("--foreign", type=Path, help="1Cv7.MD of another base, read only")
    parser.add_argument("--kudir", type=Path, help="KUDiR corpus (research/kudir/corpus)")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.path.lexists(args.output):
        parser.error(f"output exists: {args.output}")
    metadata = lint77.load_metadata(args.base / "1Cv7.MD")
    agreement = native_agreement(args.evidence, args.work.resolve(), args.template.resolve(), metadata, args.base.resolve())
    corpus = corpora(args.base, args.foreign, args.kudir)
    result = {"schema_version": 1, "scope": "task 020 acceptance: native agreement and corpora",
              "lint_version": lint77.VERSION, "evidence": [{"name": p.name, "sha256": sha256(p)} for p in args.evidence],
              "native_agreement": agreement, "corpora": corpus,
              "status": "passed" if all(r["status"] == "passed" for r in agreement) else "failed"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
    for row in agreement:
        print(row["id"], row["status"], "; ".join(row["issues"])[:300])
    for name, entry in corpus.items():
        if isinstance(entry, dict) and "by_rule" in entry:
            print(name, entry["by_rule"], entry.get("by_folder"), "checked", entry["attributes_checked"],
                  "without areas", entry.get("L7711_without_table_areas"))
    print("kudir", corpus.get("kudir"))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
