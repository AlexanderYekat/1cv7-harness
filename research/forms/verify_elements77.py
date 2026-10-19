"""Acceptance of task 011 from the evidence of the native probes E1a–E4b.

Reads the run directories and the approved baselines and checks every outcome
recorded in docs/tasks/011-form-elements.md before the runs. Writes one JSON
with each check, its observed values and the overall status.

    python -B research/forms/verify_elements77.py --runs .artifacts/runs \
        --series .local/stage11-native/series --output .artifacts/forms/elements-acceptance-NEW.json
"""

import argparse
import hashlib
import json
from pathlib import Path

RUNS = {"E1a": "9def5909-dad9-45eb-a2fd-91bda4e67f1b", "E1": "fbb1d3d6-9f5a-4fe7-8d54-3331d35d8ea9",
        "E2": "98959995-e860-484a-919f-9758e1e8e339", "E3": "c2ea9bbb-2b53-494b-be70-26b5e42d8ec5",
        "E4": "1596dfd7-e1ab-42ff-bd65-167a12ce8817", "E4b": "85e994f7-bb92-488d-aa78-cee344e240cd"}
VALUES = ("flag:0;clicked:1;value:Строка77=Строка|{};value:Число77=Число|12.5;value:Дата77=Дата|2026-10-19;"
          "value:Флажок77=Число|0;label:Надпись 77")
# Window ID of record i of 16 is 4152 + 15 − i (task 008): the new records 4161–4167.
CLASSES = {4158: "Button", 4157: "Button", 4156: "Static", 4155: "Button", 4154: "BMASKED", 4153: "BMASKED",
           4152: "1CEDIT"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stages(report):
    return {s["stage"]: s for s in report["stages"]}


def clean(report):
    shutdown = report.get("shutdown") or {}
    return bool(report.get("platform_checked") and shutdown.get("cleanup_verified")
                and shutdown.get("others_preserved") and not shutdown.get("forced_cleanup"))


def tests(report):
    return {t["name"]: t for t in stages(report)["tests"].get("tests", [])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    checks = []

    def check(name, ok, **observed):
        checks.append({"check": name, "passed": bool(ok), **observed})

    reports = {label: load(args.runs / run_id / "run.json") for label, run_id in RUNS.items()}
    windows = {label: load(args.runs / run_id / "form" / "form-window.json") for label, run_id in RUNS.items()}
    for label, report in reports.items():
        check(f"{label}: own 1C closed cleanly, other sessions preserved", clean(report), run_id=report["run_id"])

    e1a = windows["E1a"]
    typed = e1a["actions"][0]
    check("E1a: WM_CHAR to the 1CEDIT wrapper returns but changes nothing; the focus is an inner window (ID 0)",
          typed["returned"] and typed["characters_sent"] == 6 and typed["text_after"] == ""
          and e1a["captures"][0]["focus"] == {"id": 0},
          text_after=typed["text_after"], focus=e1a["captures"][0]["focus"])
    value = tests(reports["E1a"])["form-values"]["value"]
    check("E1a: a string of length 20 comes back padded to 20", "value:Строка77=Строка|" + " " * 20 + ";" in value,
          value=value)

    e1, w1 = reports["E1"], windows["E1"]
    rows = tests(e1)
    check("E1: the form opens with 16 windows on one mapping and the described captions",
          rows["form-open"]["status"] == "passed" and rows["form-open"]["expectation_met"]
          and w1["units"]["consistent"] and w1["units"]["controls"] == 16,
          max_residual_px=w1["units"]["max_residual_px"])
    classes = {c["id"]: c["class"] for c in w1["controls"]}
    check("E1: window classes of the new controls", all(classes.get(i) == k for i, k in CLASSES.items()),
          classes={str(i): classes.get(i) for i in CLASSES})
    opened, after = w1["fields_open"], w1["fields_after"]
    check("E1: at open the fields show the module's values and the check box is checked",
          opened["4164"] == {"checked": 1} and opened["4165"]["text"].strip() == "12.50"
          and opened["4166"] == {"text": "19.10.26"} and opened["4167"] == {"text": ""},
          fields=opened)
    caret = w1["captures"][0]
    check("E1: the caret at open is in the string field (the last record comes first)",
          caret["focus"] == {"id": 0} and caret["caret"] and caret["caret"]["y"] > 290, caret=caret["caret"])
    target = w1["actions"][0]
    check("E1: typing into the inner window reaches the field, the click clears the check box",
          target["target"]["class"] == "1CEDITSPR" and target["text_after"] == "Тест77"
          and after["4167"] == {"text": "Тест77"} and after["4164"] == {"checked": 0},
          target=target["target"], fields=after)
    check("E1: the module received every value", rows["form-values"]["expectation_met"]
          and rows["form-values"]["value"] == VALUES.format("Тест77|20"), value=rows["form-values"]["value"])
    visual = stages(e1)["visual"]
    check("E1: no baseline blocks the visual stage", e1["exit_code"] == 2 and visual["status"] == "blocked"
          and all("no approved baseline" in c["reason"] for c in visual["checks"]), reason=visual["reason"])

    baselines = {}
    for name in ("elements-open", "elements-clicked"):
        record = load(args.series / "baselines" / f"{name}.json")
        digest = hashlib.sha256((args.series / "baselines" / f"{name}.png").read_bytes()).hexdigest()
        baselines[name] = digest
        check(f"baseline {name}: approved explicitly from E1, image matches its record",
              record["approved"]["run_id"] == RUNS["E1"] and record["image"]["sha256"] == digest
              and record["approved"]["by"], sha256=digest, by=record["approved"]["by"])
    before = (args.series / "baselines-before.txt").read_text(encoding="utf-8").split()
    after_runs = (args.series / "baselines-after.txt").read_text(encoding="utf-8").split()
    check("baselines unchanged by the later runs", before == after_runs and len(before) == 8)

    e2 = reports["E2"]
    rows = stages(e2)["visual"]["checks"]
    check("E2: the same form passes both visual checks with no differing pixel and the same values",
          e2["exit_code"] == 0 and all(r["status"] == "passed" and r["diff_pixels"] == 0 for r in rows)
          and tests(e2)["form-values"]["value"] == VALUES.format("Тест77|20"),
          masked=[r["masked_pixels"] for r in rows])

    e3, w3 = reports["E3"], windows["E3"]
    typed = w3["actions"][0]
    check("E3: a string field of length 3 accepts only three of six characters",
          typed["characters_sent"] == 6 and typed["text_after"] == "Тес" and e3["exit_code"] == 0
          and tests(e3)["form-values"]["value"] == VALUES.format("Тес|3"),
          text_after=typed["text_after"], value=tests(e3)["form-values"]["value"])

    e4 = tests(reports["E4"])["form-open-conflict"]
    check("E4: expectation refuted — 1C compiles a module Перем named as a form attribute",
          e4["status"] == "passed" and not e4["expectation_met"] and not e4["diagnostics"]
          and reports["E4"]["exit_code"] == 1, status=e4["status"])
    e4b = windows["E4b"]
    check("E4b: the module's Перем shadows the attribute — its assignment does not reach the field",
          tests(reports["E4b"])["form-open-shadowed"]["expectation_met"]
          and e4b["fields_open"]["4159"] == {"text": ""}, field=e4b["fields_open"]["4159"])

    result = {"schema_version": 1, "task": "011-form-elements", "runs": RUNS, "baselines": baselines,
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
