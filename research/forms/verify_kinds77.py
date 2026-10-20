"""Acceptance of task 013 from the evidence of the native probes K1–K5b and the corpus round trips.

Reads the run directories, the probe profiles and the corpus results and checks
every outcome recorded in docs/tasks/013-kind-name-checks.md before the runs
(the first K1 with its layout check, K5 refuted in its reason and the probe K5b
added). Writes one JSON with each check, its observed values and the overall status.

    python -B research/forms/verify_kinds77.py --runs .artifacts/runs --series .local/stage13-native \
        --corpus .artifacts/forms/corpus-20261019-013 --corpus-md .artifacts/forms/corpus-20261019-013-md \
        --corpus-foreign .artifacts/forms/corpus-20261019-013-ts --output .artifacts/forms/kinds-acceptance-NEW.json
"""

import argparse
import json
from pathlib import Path

RUNS = {"K1-first": "62be9163-89b3-4ace-91a8-a23cc273c154", "K1-repeat-old": "192efb2d-e18d-421a-8761-a86ff46ebad9",
        "K1": "99800da3-87ea-4121-992b-ec36872cb806", "K2": "71147c54-2744-48b7-b08c-9ade174bacdc",
        "K3": "85486e4c-d1fd-44bb-a786-8c380b511e7c", "K4": "a22b52e9-6980-435c-a598-656cefcf6101",
        "K5": "32ab0147-5fb5-4f58-9740-9ff9e74c2318", "K5b": "3937dcf4-cec2-4c5c-86fc-94b9c45ad839"}
SERIES = {"K1-first": "series-k1", "K1-repeat-old": "series-k1", "K5b": "series-k5b"}
PROFILES = {"K1-first": "k1-unchanged", "K1-repeat-old": "k1-unchanged", "K1": "k1-unchanged", "K2": "k2-kept",
            "K3": "k3-replaced", "K4": "k4-foreign", "K5": "k5-stale", "K5b": "k5b-stale-assign"}
TEMPLATE_SHA = "f5aacf9d8fd2e99784aeb72c2c9f72e133c9a9abb3aad2cfb49da80d02ef5102"  # Договор_Оргтехники.ert
STAND_MD = "931b26eb2e388ba3000196ab024351e65cb324e02e885dc4cef5be68059ecfa1"
STAND_COPY = "17cb7258aadc8b3e40fc97eb145823a84f7d78a4966ce3c79b7200760d58e22e"  # its Main MetaData Stream + NUL
TEMPLATE_COPY = "de999484e13b75a8159eed6de45831bc4a647fef5d62959954add7b2cd0ebd10"
CONFIGURATION = "Бухгалтерский учет, редакция 4.2"
OLD = "value:Тариф=Справочник|Тарифы;value:ВыбранДоговор=Справочник|Договоры"
TARIFF, CONTRACT = ("Справочник.Тарифы", "B"), ("Справочник.Договоры", "B")


def kind(control, name, number, target):
    return {"control": control, "object": name[0], "code": name[1], "object_id": number, "target_object_id": target}


KINDS = {"K1": [kind(4154, TARIFF, 25507, 26051), kind(4157, CONTRACT, 112, 112)]}
KINDS["K2"] = KINDS["K1"] + [kind(4160, ("Документ.Выписка", "O"), 238, 238)]
KINDS["K3"] = [kind(4154, TARIFF, 26051, 26051)] + KINDS["K2"][1:] + [kind(4161, ("Справочник.ТипыЦен", "B"),
                                                                         26080, 26080)]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stages(report):
    return {s["stage"]: s for s in report["stages"]}


def clean(report):
    shutdown = report.get("shutdown") or {}
    return bool(shutdown.get("cleanup_verified") and shutdown.get("others_preserved")
                and not shutdown.get("forced_cleanup") and shutdown.get("server_exit_code") == 0)


def tests(report):
    return {t["name"]: t for t in stages(report)["tests"].get("tests", [])}


def answers(run_dir):
    """The controller's answer per command: the lines 1C returned (UTF-16 event log)."""
    text = (run_dir / "native" / "ert-events.jsonl").read_bytes().decode("utf-16")
    return {e["name"]: e["value"] for e in map(json.loads, filter(None, map(str.strip, text.splitlines())))
            if e.get("kind") == "ert"}


def operations(run_dir):
    return {op["name"]: op for op in load(run_dir / "platform-result.json")["operations"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--series", type=Path, required=True, help="the local stage13-native directory")
    parser.add_argument("--corpus", type=Path, required=True, help="corpus result without --metadata")
    parser.add_argument("--corpus-md", type=Path, required=True, help="corpus result with the stand base's 1Cv7.MD")
    parser.add_argument("--corpus-foreign", type=Path, required=True,
                        help="corpus result with the 1Cv7.MD of Торговля+Склад 9.2")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    checks = []

    def check(name, ok, **observed):
        checks.append({"check": name, "passed": bool(ok), **observed})

    reports = {label: load(args.runs / run_id / "run.json") for label, run_id in RUNS.items()}
    for label, report in reports.items():
        files = load(args.series / SERIES.get(label, "series") / "cases.json")["files"]
        inputs, build = report["inputs"], stages(report)["build"]
        template = TEMPLATE_SHA if label not in ("K5", "K5b") else files["dogovor-basecopy.ert"]
        check(f"{label}: the run used its prepared profile, module and template",
              inputs["project_id"] == f"kinds-{PROFILES[label]}" and inputs["profile"]["name"] == f"{PROFILES[label]}.toml"
              and (label == "K4" or (build["source_sha256"] == files[inputs["source"]["name"]]
                                     and build["template_sha256"] == template)), run_id=report["run_id"])
        if label != "K4":
            check(f"{label}: own 1C closed cleanly, other sessions preserved", clean(report), run_id=report["run_id"])

    for label in ("K1-first", "K1-repeat-old"):
        report = reports[label]
        build, rows = stages(report)["build"]["form"], tests(report)
        layout = operations(args.runs / RUNS[label])["open"]["form_issues"]
        check(f"{label}: built as expected and the module got the kinds, but the launcher's layout check failed",
              build["kinds"] == KINDS["K1"] and build["changes"] == [] and rows["form-kinds"]["value"] == OLD
              and rows["form-kinds"]["expectation_met"] and not rows["form-open"]["expectation_met"]
              and layout == ["positions do not follow one mapping: max residual 2.32"] and report["exit_code"] == 1,
              form_issues=layout)

    for label in ("K1", "K2", "K3"):
        report = reports[label]
        build = stages(report)["build"]["form"]
        copy = build["ert_metadata"]
        rows = tests(report)
        expected = OLD + {"K1": "", "K2": ";value:Выписка77=Документ|Выписка",
                          "K3": ";value:Выписка77=Документ|Выписка;value:ТипЦен77=Справочник|ТипыЦен"}[label]
        check(f"{label}: built by the stand base's metadata, checked by names, kinds as planned",
              build["metadata"] == {"sha256": STAND_MD, "configuration": CONFIGURATION, "source": "stand"}
              and build["kinds"] == KINDS[label] and copy["template_sha256"] == TEMPLATE_COPY
              and stages(report)["platform_check"]["metadata_check"] == {"sha256": STAND_MD, "same_as_build": True,
                                                                         "missing": []},
              kinds=build["kinds"], ert_metadata=copy)
        check(f"{label}: 1C created the report, the module got the type and kind of every field",
              report["exit_code"] == 0 and rows["form-load"]["expectation_met"]
              and rows["form-kinds"]["expectation_met"] and rows["form-kinds"]["value"] == expected,
              value=rows["form-kinds"]["value"])
    k1, k2, k3 = (stages(reports[label])["build"]["form"] for label in ("K1", "K2", "K3"))
    check("K1: the unchanged description keeps the copy and the dialog; 25507 «Тарифы» works in a base with 26051",
          k1["ert_metadata"]["action"] == "kept" and k1["changes"] == []
          and k1["dialog_sha256"] == k1["template_dialog_sha256"])
    check("K2: Документ.Выписка is in the copy: the copy stays, the new field takes 238, «Тариф» keeps 25507",
          k2["ert_metadata"]["action"] == "kept" and k2["changes"][-1] == {
              "control": 4160, "added": "BMASKED", "type": {"object": "Документ.Выписка", "code": "O", "object_id": 238}})
    check("K3: Справочник.ТипыЦен is not in the copy: replaced by the stand's metadata, «Тариф» renumbered by name",
          k3["ert_metadata"]["action"] == "replaced" and k3["ert_metadata"]["sha256"] == STAND_COPY
          and k3["changes"][-1] == {"control": 4154, "property": "object_id", "from": 25507, "to": 26051,
                                    "object": "Справочник.Тарифы"}
          and k3["changes"][-2]["type"] == {"object": "Справочник.ТипыЦен", "code": "B", "object_id": 26080},
          changes=k3["changes"])

    k4 = stages(reports["K4"])
    reason = k4["build"].get("reason") or ""
    check("K4: the kinds Торговля+Склад 9.2 lacks block the build by name; those it has do not; 1C is not started",
          k4["build"]["status"] == "blocked" and "Торговля+Склад, редакция 9.2" in reason
          and "элемент 4154 Справочник.Тарифы, новый элемент 4160 Документ.Выписка;" in reason
          and "Договоры" not in reason and "ТипыЦен" not in reason and k4["platform_check"]["status"] == "skipped"
          and not reports["K4"]["platform_checked"] and reports["K4"]["exit_code"] == 2
          and not (args.runs / RUNS["K4"] / "native").exists(), reason=reason)

    for label, value in (("K5", "value:Тариф=Справочник|;value:ВыбранДоговор=Справочник|Договоры"),
                         ("K5b", "value:Тариф=Справочник|Сотрудники;value:ВыбранДоговор=Справочник|Договоры")):
        report = reports[label]
        rows, answer = tests(report), answers(args.runs / RUNS[label])
        check(f"{label}: built without a description from the template with the stand's copy; 1C creates the report",
              "form" not in stages(report)["build"] and "open-return:1" in answer["check"]
              and rows["form-load"]["expectation_met"], check=answer["check"].splitlines()[1])
        check(f"{label}: «Тариф», whose 25507 the copy lacks, is a catalog of no kind",
              rows["form-kinds"]["value"] == value and rows["form-kinds"]["expectation_met"] == (label == "K5b")
              and report["exit_code"] == (1 if label == "K5" else 0), value=rows["form-kinds"]["value"])

    plain, named, foreign = (load(path / "result.json") for path in (args.corpus, args.corpus_md, args.corpus_foreign))
    exact = {"exact": 416, "refused": 2, "duplicate": 5}
    check("corpus without --metadata: 416 forms byte for byte, 150 reference fields named by their ERT's copy",
          plain["counts"] == exact and plain["corpus_unchanged"] and plain["references"]["named"] == 150
          and plain["references"]["by_number"] == 0 and plain["references"]["kinds"] == 112,
          references=plain["references"])
    check("corpus with the stand base's 1Cv7.MD: 416 forms byte for byte, every kind there by name, one by "
          "another number", named["counts"] == exact and named["corpus_unchanged"]
          and named["metadata"]["sha256"] == STAND_MD and named["references"]["missing"] == 0
          and named["references"]["other_number"] == 1, references=named["references"])
    refused = [row for row in foreign["rows"] if row["outcome"] == "refused" and row["detail"].startswith("build:")]
    check("corpus with Торговля+Склад 9.2: the forms with kinds it lacks are refused naming them, the rest rebuild",
          foreign["counts"] == {"exact": 385, "refused": 33, "duplicate": 5} and foreign["corpus_unchanged"]
          and foreign["references"]["forms_missing"] == 31 and foreign["references"]["missing"] == 50
          and len(refused) == 31 and all("нет видов полей формы" in row["detail"] for row in refused)
          and all(row["references"]["missing"] for row in refused), references=foreign["references"])

    result = {"schema_version": 1, "task": "013-kind-name-checks", "runs": RUNS, "checks": checks,
              "status": "passed" if all(c["passed"] for c in checks) else "failed"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise SystemExit(f"{args.output} exists; acceptance files are not overwritten")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": len(checks),
                      "failed": [c["check"] for c in checks if not c["passed"]]}, ensure_ascii=False, indent=1))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
