"""Acceptance check of task 023: the forms of catalogs and journals of 1Cv7.MD on a copy of the base.

Needs local data that is not in Git: the probe evidence (.artifacts/stage23-catalog-forms-*.json and the
regression runs, the latest series of a case wins) and the runs they name (.artifacts/runs), the stand
base's 1Cv7.MD, optionally another base's 1Cv7.MD (read only). For every configuration: the launcher
builds the expected form of every catalog, journal and report form or refuses it for a known reason, the
window IDs of each are distinct, the name 1C gives each form module maps to its file, and the fields of
catalog attributes on element and group forms follow the attributes' use. The recorded inspections of
every earlier form run are judged again with the current fit.

  python scripts/verify_catalog_forms77.py --evidence .artifacts/stage23-catalog-forms-20261022-0a.json
      --evidence ...-0b.json ... --evidence ...-3b.json --evidence .artifacts/stage23-regression-022-20261022.json
      --md .local/bases/base-for-test/1Cv7.MD --md C:/…/test-base-surgut/1Cv7.MD
      --output .artifacts/stage23-acceptance-YYYYMMDD.json
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "forms"))

from harness77 import md77  # noqa: E402
from harness77.ert_module import CompoundFile  # noqa: E402
from harness77.form77 import describe  # noqa: E402
from harness77.metadata77 import Metadata  # noqa: E402

# Series 1 and 2 observations that led to the refusal of a catalog edited in its list: the run is blocked.
OBSERVATIONS = {"e-attribute": "ЕдиницыИзмерений: ОткрытьФорму returned no value",
                "e-in-list": "СтавкиНДС: ОткрытьФорму returned no value"}
REFUSALS = ("the catalog has an owner", "the catalog is edited in its list")


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
        if case_id in OBSERVATIONS:
            if observed.get("run_status") != "blocked" or observed.get("inspection", {}).get("found"):
                issues.append("the observation is not a form that did not open")
        elif case["verdict"] not in ("confirmed", "observed"):
            issues.append(f"verdict {case['verdict']}")
        copy = observed.get("copy") or {}
        refused = (observed.get("platform_reason") or "").startswith("ValueError:")
        if not refused and (not (copy.get("removal") or {}).get("removed") or copy.get("source_unchanged") is not True):
            issues.append("the copy was not removed or the stand base changed")
        if not all(series.values()):
            issues.append(f"series check {series}")
        tests = {row["name"]: (row["status"], row["value"]) for row in observed.get("tests") or []}
        rows.append({"id": case_id, "evidence": source, "verdict": case["verdict"], "form_object": case.get("form_object"),
                     "run_status": observed.get("run_status"), "platform_reason": observed.get("platform_reason"),
                     "tests": tests, "residual_px": (observed.get("inspection", {}).get("units") or {}).get("max_residual_px"),
                     "observation": OBSERVATIONS.get(case_id),
                     "status": "failed" if issues else "passed", "issues": issues})
    return rows


def platform_name(form):
    """The name 1C gives the module of a form in a compile error (task 023, series 0 and 1)."""
    cls, kind = form.object.split(".", 1)
    if form.module == "ФормаЭлемента":
        return f"{cls}.{kind}.Форма.Модуль"
    if form.module == "ФормаГруппы":
        return f"{cls}.{kind}.Форма группы.Модуль"
    if form.module.startswith("ФормаСписка."):
        name = form.module.split(".", 1)[1]
        return f"{cls}.{kind}.ФормаСписка.{name}.Модуль" if cls == "Справочник" else f"{cls}.{kind}.Форма.{name}.Модуль"
    return f"{cls}.{kind}.Форма.Модуль"


def form_object(form):
    return form.object if form.module == "Форма" else f"{form.object}.{form.module}"


def corpus(md):
    """Every catalog, journal and report form of a configuration through the launcher's view of it."""
    import form_launcher77 as launcher
    import form_window77 as window
    md = Path(md).resolve(strict=True)
    before, data = sha256(md), md.read_bytes()
    metadata = Metadata(data, md)
    forms = [form for form in md77.read_forms(CompoundFile(data), metadata)
             if form.object and form.object.split(".")[0] in ("Справочник", "Журнал", "Отчет")]
    kinds, refused, issues, names = Counter(), Counter(), [], 0
    for form in forms:
        kind = form.module.split(".")[0] if form.object.startswith(("Справочник", "Журнал")) else "Отчет"
        name = form_object(form)
        try:
            description, source = launcher.configuration_description(md, name)
        except ValueError as error:
            reason = next((r for r in REFUSALS if r in str(error)), None)
            if reason is None:
                issues.append(f"{name}: {error}")
            refused[(kind, reason)] += 1
            continue
        kinds[kind] += 1
        if source["path"] != form.path:
            issues.append(f"{name}: another dialog {source['path']}")
        ids = window.window_ids(description)
        if len(set(ids.values())) != len(ids):
            issues.append(f"{name}: repeated window IDs")
        if md77.platform_module(platform_name(form)) != form.module_file:
            issues.append(f"{name}: 1C's name {platform_name(form)!r} maps to {md77.platform_module(platform_name(form))!r}")
        else:
            names += 1
    # The attribute fields of element and group forms against the use of the attributes (field 11 and 12).
    use = Counter()
    for form in forms:
        if form.module not in ("ФормаЭлемента", "ФормаГруппы"):
            continue
        attributes = metadata.attributes("Справочник", form.object.split(".", 1)[1]) or {}
        wanted = "element" if form.module == "ФормаЭлемента" else "group"
        for control in describe(form.text, metadata)["controls"]:
            attribute = attributes.get((control.get("identifier") or "").casefold())
            if attribute is not None and attribute.use is not None:
                use[(form.module, "shown" if wanted in attribute.use else "elsewhere")] += 1
    edits = Counter(str(metadata.catalog(name)["edit"]) for name in metadata.objects()["Справочник"].values())
    result = {"md": md.name, "sha256": before, "configuration": metadata.configuration, "forms": len(forms),
              "expected": dict(kinds), "refused": {f"{k}: {r}": n for (k, r), n in refused.items()},
              "platform_names_mapped": names, "attribute_fields": {f"{k}: {v}": n for (k, v), n in use.items()},
              "catalog_edit": dict(edits), "issues": issues, "template_unchanged": sha256(md) == before}
    result["status"] = "passed" if not issues and result["template_unchanged"] else "failed"
    return result


def rejudge():
    """Every recorded inspection of a form run judged again with the current fit (task 023 changed it)."""
    import form_window77 as window
    rows, issues = 0, []
    for run in sorted((ROOT / ".artifacts" / "runs").iterdir()):
        try:
            inspection = json.loads((run / "form" / "form-window.json").read_text(encoding="utf-8"))
            description = json.loads((run / "form" / "description.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not inspection.get("found") or not inspection.get("units"):
            continue
        rows += 1
        old = inspection["units"]
        measured = {c["id"]: tuple(c["rect"]) for c in inspection["controls"]}
        new = window.fit_units(window.expected_geometry(description), measured, edged=set(old.get("edged") or []))
        if old["consistent"] and not new["consistent"]:
            issues.append(f"{run.name}: {old['max_residual_px']} -> {new['max_residual_px']}")
    return {"inspections": rows, "newly_inconsistent": issues, "status": "failed" if issues else "passed"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence", required=True, action="append", type=Path)
    parser.add_argument("--md", required=True, action="append", type=Path, help="a 1Cv7.MD, read only")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.path.lexists(args.output):
        parser.error(f"output exists: {args.output}")
    agreement = native(args.evidence)
    corpora = [corpus(md) for md in args.md]
    judged = rejudge()
    result = {"schema_version": 1, "scope": "task 023 acceptance: native series, the forms of two configurations",
              "evidence": [{"name": p.name, "sha256": sha256(p)} for p in args.evidence],
              "native": agreement, "corpora": corpora, "rejudged": judged,
              "status": "passed" if all(r["status"] == "passed" for r in agreement + corpora + [judged]) else "failed"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
    for row in agreement:
        print(row["id"], row["status"], row["verdict"], row["run_status"], (row["platform_reason"] or "")[:80],
              row["tests"], row["residual_px"], "; ".join(row["issues"]))
    for row in corpora:
        print(row["md"], row["configuration"], row["status"], row["forms"], row["expected"], row["refused"],
              "names", row["platform_names_mapped"], row["attribute_fields"], row["catalog_edit"], row["issues"][:5])
    print("rejudged", judged)
    print("status", result["status"])
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
