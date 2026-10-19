"""Acceptance of task 012 from the evidence of the native probes R1–R5 and the corpus round trip.

Reads the run directories, the approved baselines and the corpus results and
checks every outcome recorded in docs/tasks/012-reference-fields.md before the
runs (R1 refuted, its diagnosis R1a–R1c, the changed method and its repeat).
Writes one JSON with each check, its observed values and the overall status.

    python -B research/forms/verify_references77.py --runs .artifacts/runs \
        --series .local/stage12-native/series --corpus .artifacts/forms/corpus-20261019-v3 \
        --corpus-md .artifacts/forms/corpus-20261019-v3-md --output .artifacts/forms/references-acceptance-NEW.json
"""

import argparse
import hashlib
import json
from pathlib import Path

RUNS = {"R1-first": "afbc3f6b-5394-415c-96c4-cb6106cff51f", "R1a": "c415d4da-0e9b-4be4-bb3b-971b986b8a16",
        "only-Контрагент77": "2cf06a20-9ab0-4632-96b7-c93d1d0e725c",
        "only-Справочник77": "ababe411-d670-4a1d-afeb-29c33bd6526c",
        "only-Документ77": "4ae432b5-edcb-423a-ae02-92a7316c48a7",
        "only-Пол77": "861ac881-f4bb-48f4-ac01-c73a173f8b8f",
        "only-Счет77": "9f1769b2-5d26-4550-8657-8c0ef78b4179",
        "only-ВидСубконто77": "2ae231db-f48d-4dec-a21f-4aa7ac53f9ed",
        "R1b": "f8f0fa38-4495-482f-826e-f78b8c7cda7b", "R1c": "9b0d87fa-09e9-403a-a2da-86fe60a08b5d",
        "R1": "a4e4af88-a837-45b6-b3aa-5d934bb2af68", "R2": "1df3630f-fd10-431c-9c4c-f48d1096d568",
        "R3": "b0587e43-cc9d-41b7-8bab-8fa96e296d93", "R4": "b5fc0462-d3e3-45c3-bdf3-6ae1d31899a4",
        "R5": "a5bdc155-c495-41b5-9f77-d0fe9653b28b"}
STAND_MD = "931b26eb2e388ba3000196ab024351e65cb324e02e885dc4cef5be68059ecfa1"
FIELDS = ("Контрагент77", "Справочник77", "Документ77", "Пол77", "Счет77", "ВидСубконто77")
KINDS = {"Контрагент77": "Справочник|Контрагенты", "Справочник77": "Справочник|Сотрудники",
         "Документ77": "Документ|Выписка", "Пол77": "Перечисление|Пол", "Счет77": "Счет|Основной",
         "ВидСубконто77": "ВидСубконто|-"}
# The dialog records of the six fields (task 012 survey): code and object number, any = 0.
NUMBERS = {4163: ("B", "133"), 4164: ("B", "0"), 4165: ("O", "0"), 4166: ("E", "21439"), 4167: ("T", "809"),
           4168: ("K", "0")}


def value(wrong=False):
    return "clicked:1;" + ";".join(
        f"value:{name}={KINDS[name]}|" + ("same:0|empty:1" if wrong and name == "Контрагент77" else "same:1|empty:0")
        for name in FIELDS)


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True, help="corpus result without --metadata")
    parser.add_argument("--corpus-md", type=Path, required=True, help="corpus result with the base's 1Cv7.MD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    checks = []

    def check(name, ok, **observed):
        checks.append({"check": name, "passed": bool(ok), **observed})

    reports = {label: load(args.runs / run_id / "run.json") for label, run_id in RUNS.items()}
    for label, report in reports.items():
        if label != "R4":
            check(f"{label}: own 1C closed cleanly, other sessions preserved", clean(report), run_id=report["run_id"])

    first = reports["R1-first"]
    built = stages(first)["build"]["form"]
    added = {c["control"]: (c["type"]["code"], str(c["type"]["object_id"]))
             for c in built["changes"] if c.get("type")}
    error = answers(args.runs / RUNS["R1-first"])["open"]
    check("R1 (first): built by the stand's metadata with the numbers of the survey, but 1C cannot create the report",
          built["metadata"]["sha256"] == STAND_MD and built["metadata"]["source"] == "stand" and added == NUMBERS
          and "Ошибка создания внешнего отчета" in error and not stages(first)["platform_check"]["diagnostics"]
          and first["exit_code"] == 2, open=error.splitlines()[-1][:80])
    error = answers(args.runs / RUNS["R1a"])["open"]
    check("R1a: the same dialog with the simple module of task 008 fails the same way: the dialog, not the module",
          "Ошибка создания внешнего отчета" in error and reports["R1a"]["exit_code"] == 2)
    singles = {label[5:]: reports[label]["exit_code"] for label in RUNS if label.startswith("only-")}
    check("one field at a time: any object (number 0) opens, a kind does not",
          singles == {"Контрагент77": 2, "Справочник77": 0, "Документ77": 0, "Пол77": 2, "Счет77": 2,
                      "ВидСубконто77": 0}, exit_codes=singles)
    check("R1b, R1c: with the copy of a corpus ERT or with the base's metadata in FIO.ERT every field opens",
          reports["R1b"]["exit_code"] == 0 and reports["R1c"]["exit_code"] == 0)

    r1, w1 = reports["R1"], load(args.runs / RUNS["R1"] / "form" / "form-window.json")
    build = stages(r1)["build"]["form"]
    copy = build["ert_metadata"]
    check("R1: the empty copy of FIO.ERT («Задача») is replaced by the stand base's metadata",
          build["metadata"] == {"sha256": STAND_MD, "configuration": "Бухгалтерский учет, редакция 4.2",
                                "source": "stand"}
          and copy["action"] == "replaced" and copy["template_configuration"] == "Задача"
          and copy["configuration"] == "Бухгалтерский учет, редакция 4.2", ert_metadata=copy)
    rows = tests(r1)
    check("R1: the form opens with 17 windows on one mapping; the fields are BMASKED",
          rows["form-open"]["expectation_met"] and w1["units"]["consistent"] and w1["units"]["controls"] == 17
          and all(c["class"] == "BMASKED" for c in w1["controls"] if 4152 <= c["id"] <= 4157),
          max_residual_px=w1["units"]["max_residual_px"])
    check("R1: the module received the type, kind and value of every field", rows["form-references"]["expectation_met"]
          and rows["form-references"]["value"] == value(), value=rows["form-references"]["value"])
    shown = load(args.runs / RUNS["R1"] / "platform-result.json")["operations"]
    shown = next(op for op in shown if op["name"] == "result")["representations"]
    texts = {name: w1["fields_open"][str(4163 + number)]["text"] for number, name in enumerate(FIELDS)}
    same = {name: texts[name] == shown[name] for name in FIELDS}
    check("R1: every field shows its value; the text equals Строка(value) except the account, shown by its mask",
          all(texts.values()) and all(same[name] for name in FIELDS if name != "Счет77")
          and shown["Счет77"] == "51" and texts["Счет77"] == "51 .  . " and shown["Пол77"] == "Женский"
          and texts["ВидСубконто77"] == "Контрагенты", texts=texts, representations=shown)
    visual = stages(r1)["visual"]
    check("R1: no baseline blocks the visual stage", r1["exit_code"] == 2 and visual["status"] == "blocked"
          and all("no approved baseline" in c["reason"] for c in visual["checks"]), reason=visual["reason"])

    baselines = {}
    for name in ("references-open", "references-clicked"):
        record = load(args.series / "baselines" / f"{name}.json")
        digest = hashlib.sha256((args.series / "baselines" / f"{name}.png").read_bytes()).hexdigest()
        baselines[name] = digest
        check(f"baseline {name}: approved explicitly from R1, image matches its record",
              record["approved"]["run_id"] == RUNS["R1"] and record["image"]["sha256"] == digest
              and record["approved"]["by"], sha256=digest, by=record["approved"]["by"])
    before = (args.series / "baselines-before.txt").read_text(encoding="utf-8").split()
    after = (args.series / "baselines-after.txt").read_text(encoding="utf-8").split()
    check("baselines unchanged by the later runs", before == after and len(before) == 8)

    r2 = reports["R2"]
    rows = stages(r2)["visual"]["checks"]
    check("R2: the same form passes both visual checks with no differing pixel and the same values",
          r2["exit_code"] == 0 and all(r["status"] == "passed" and r["diff_pixels"] == 0 for r in rows)
          and tests(r2)["form-references"]["value"] == value(), masked=[r["masked_pixels"] for r in rows])

    r3 = reports["R3"]
    w3 = load(args.runs / RUNS["R3"] / "form" / "form-window.json")
    check("R3: a kind field keeps its kind — a Сотрудники element becomes an empty Контрагенты, the field is empty",
          r3["exit_code"] == 0 and tests(r3)["form-references"]["value"] == value(wrong=True)
          and w3["fields_open"]["4163"] == {"text": ""}, value=tests(r3)["form-references"]["value"])

    r4 = stages(reports["R4"])
    check("R4: an unknown name blocks the build with its name; 1C is not started",
          r4["build"]["status"] == "blocked" and "Справочник.НетТакого" in r4["build"]["reason"]
          and r4["platform_check"]["status"] == "skipped" and not reports["R4"]["platform_checked"]
          and reports["R4"]["exit_code"] == 2 and not (args.runs / RUNS["R4"] / "native").exists(),
          reason=r4["build"]["reason"])

    r5 = reports["R5"]
    copy = stages(r5)["build"]["form"]["ert_metadata"]
    check("R5: a template whose copy has the kinds keeps it, and the form works as in R1",
          copy["action"] == "kept" and copy["template_configuration"] == "Бухгалтерский учет, редакция 4.2"
          and "sha256" not in copy and r5["exit_code"] == 0 and tests(r5)["form-references"]["value"] == value(),
          ert_metadata=copy)

    plain, named = load(args.corpus / "result.json"), load(args.corpus_md / "result.json")
    check("corpus without --metadata: 416 forms byte for byte, every reference field named by its ERT's copy",
          plain["counts"] == {"exact": 416, "refused": 2, "duplicate": 5} and plain["corpus_unchanged"]
          and plain["references"] == {"named": 150, "by_number": 0} and plain["description_schema_version"] == 3,
          references=plain["references"])
    check("corpus with the base's 1Cv7.MD: 416 forms byte for byte, 149 named, 25507 by number",
          named["counts"] == {"exact": 416, "refused": 2, "duplicate": 5} and named["corpus_unchanged"]
          and named["references"] == {"named": 149, "by_number": 1} and named["metadata"]["sha256"] == STAND_MD,
          references=named["references"])

    result = {"schema_version": 1, "task": "012-reference-fields", "runs": RUNS, "baselines": baselines,
              "checks": checks, "status": "passed" if all(c["passed"] for c in checks) else "failed"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise SystemExit(f"{args.output} exists; acceptance files are not overwritten")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": len(checks),
                      "failed": [c["check"] for c in checks if not c["passed"]]}, ensure_ascii=False, indent=1))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
