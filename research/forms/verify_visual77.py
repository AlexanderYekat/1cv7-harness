"""Acceptance of task 010 from the evidence of the native probes V0–V6.

Reads the run directories and the approved baselines and checks every outcome
recorded in docs/tasks/010-visual-form-tests.md before the runs. Writes one
JSON with each check, its observed values and the overall status.

    python -B research/forms/verify_visual77.py --runs .artifacts/runs \
        --series .local/stage10-native/series --output .artifacts/forms/visual-acceptance-NEW.json
"""

import argparse
import hashlib
import json
from pathlib import Path

RUNS = {"V0": "53b93f39-5883-4fb9-8caa-962a853f7bd4", "V1a": "8222f1a9-247b-4283-9a18-3a8278521034",
        "V1": "5f5c042f-e2b9-43c9-b04a-41c9195d3a02", "V2": "9cafeb6a-893b-4729-bdd5-9efdb9b60d74",
        "V3": "35bb57bc-6f32-4d7c-bf5e-359ae36662ab", "V4": "091608a0-db8b-451e-b581-e80edc25cdf3",
        "V5": "9c3b5349-e842-477b-9aef-d41024ab22d1", "V6": "b5a77843-30e8-4205-bdb2-d4f493e6c818"}
BUTTON_AREA = (200, 30, 349, 70)  # x0, y0, x1, y1 of the «Проверка» corner in the 349×222 form image


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stages(report):
    return {s["stage"]: s for s in report["stages"]}


def clean(report):
    shutdown = report.get("shutdown") or {}
    return bool(report.get("platform_checked") and shutdown.get("cleanup_verified")
                and shutdown.get("others_preserved") and not shutdown.get("forced_cleanup"))


def inside(box, area=BUTTON_AREA):
    return bool(box) and box["x"] >= area[0] and box["y"] >= area[1] \
        and box["x"] + box["width"] <= area[2] and box["y"] + box["height"] <= area[3]


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
    for label, report in reports.items():
        check(f"{label}: own 1C closed cleanly, other sessions preserved", clean(report), run_id=report["run_id"])

    probe = load(args.runs / RUNS["V0"] / "form" / "form-window.json")["visual_probe"]
    shots = probe["shots"]
    check("V0: hidden captures are uniform", all(s["colours"] == 1 for s in shots if s["stage"] == "hidden"),
          hidden=len([s for s in shots if s["stage"] == "hidden"]))
    check("V0: showing without activation reaches visibility, hiding restores it",
          probe["show"]["reached"] and probe["hide"]["reached"] and not probe["hide"]["after"]["ws_visible"],
          show_s=probe["show"]["elapsed_s"], hide_s=probe["hide"]["elapsed_s"])
    full = [s for s in shots if s["stage"] != "hidden" and s["flags"] == 2]
    check("V0: PW_RENDERFULLCONTENT gives an image of the shown form", all(s["colours"] > 1 for s in full),
          colours=[s["colours"] for s in full])

    v1a = stages(reports["V1a"])["visual"]
    check("V1a: GetGUIThreadInfo from another desktop is denied and blocks", v1a["status"] == "blocked"
          and "WinError 5" in v1a["reason"], reason=v1a["reason"])

    v1 = stages(reports["V1"])
    captures = v1["platform_check"]["captures"]
    check("V1: tests pass, no baseline blocks the visual stage",
          v1["tests"]["status"] == "passed" and v1["visual"]["status"] == "blocked"
          and all("no approved baseline" in c["reason"] for c in v1["visual"]["checks"])
          and reports["V1"]["exit_code"] == 2, reason=v1["visual"]["reason"])
    check("V1: both captures stable; caret only in the open state",
          all(c["stable"] for c in captures) and captures[0]["caret"] and captures[1]["caret"] is None,
          attempts=[c["attempts"] for c in captures], caret=captures[0]["caret"])

    baselines = {}
    for name in ("form-open", "form-clicked"):
        record = load(args.series / "baselines" / f"{name}.json")
        digest = hashlib.sha256((args.series / "baselines" / f"{name}.png").read_bytes()).hexdigest()
        baselines[name] = digest
        check(f"baseline {name}: approved explicitly from V1, image matches its record",
              record["approved"]["run_id"] == RUNS["V1"] and record["image"]["sha256"] == digest
              and record["approved"]["by"], sha256=digest, by=record["approved"]["by"])
    before = (args.series / "baselines-before.txt").read_text(encoding="utf-8").split()
    after = (args.series / "baselines-after.txt").read_text(encoding="utf-8").split()
    check("baselines unchanged by the failing runs V4, V5", before == after and len(before) == 8)

    for label in ("V2", "V3"):
        rows = stages(reports[label])["visual"]["checks"]
        check(f"{label}: unchanged form passes both checks with no differing pixel",
              reports[label]["exit_code"] == 0 and all(r["status"] == "passed" and r["diff_pixels"] == 0
                                                       for r in rows),
              masked=[r["masked_pixels"] for r in rows], captures=[r["capture"]["sha256"][:12] for r in rows])

    v4 = stages(reports["V4"])
    check("V4: shifted button fails both checks around the button, tests still pass",
          reports["V4"]["exit_code"] == 1 and v4["tests"]["status"] == "passed"
          and all(r["status"] == "failed" and inside(r["diff_box"]) for r in v4["visual"]["checks"]),
          diff=[(r["diff_pixels"], r["diff_box"]) for r in v4["visual"]["checks"]])
    v5 = stages(reports["V5"])["visual"]["checks"]
    check("V5: missing button fails at the button's place",
          reports["V5"]["exit_code"] == 1 and stages(reports["V5"])["tests"]["status"] == "passed"
          and [r["status"] for r in v5] == ["failed"] and inside(v5[0]["diff_box"]),
          diff=[(r["diff_pixels"], r["diff_box"]) for r in v5])
    dpi = ["window_dpi: baseline 120, capture 96"]
    check("V6: a different recorded environment blocks without comparing pixels",
          reports["V6"]["exit_code"] == 2
          and all(r["status"] == "blocked" and "diff_pixels" not in r and r["environment_issues"] == dpi
                  for r in stages(reports["V6"])["visual"]["checks"]))

    result = {"schema_version": 1, "task": "010-visual-form-tests", "runs": RUNS, "baselines": baselines,
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
