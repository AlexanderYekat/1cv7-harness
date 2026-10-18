"""Local profiles for the native visual probes V1–V6 of task 010.

Writes into a new local directory (machine paths stay out of Git):

- ``fio-button.json`` — FIO.ERT plus the button «Проверка» of F2b (x 152, y 16);
- ``fio-button-shifted.json`` — the same button 12 units to the left (x 140);
- ``fio-unchanged.json`` — FIO.ERT without the button;
- ``stand.toml`` — the given stand profile with the form launcher;
- ``v-button.toml`` (V1–V3), ``v-shifted.toml`` (V4), ``v-missing.toml`` (V5),
  ``v-env.toml`` (V6) — project profiles; all compare with ``baselines/``,
  V6 with ``baselines-env/``.

    python -B research/forms/prepare_visual77.py --stand .local/stage8-native/r2/stand.toml \
        --output .local/stage10-native/series

After the baselines are approved from V1, ``--derive-env DIR`` writes
``DIR/baselines-env``: the same images with the window DPI of their records
set to 120, an environment the capture does not have (V6).
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prepare_cases77 as cases  # noqa: E402

form77 = cases.form77
SHIFTED_X = 140
CLICK = """[[platform.tests]]
name = "click-4161"
command = "result"
expect = "passed"
expect_value = "clicked:1"
description = "BM_CLICK кнопке 4161 вызывает Harness77Нажатие ровно один раз"
"""
CHECK = """[[visual.checks]]
name = "{name}"
state = "{state}"
window = "form"
"""
CASES = {  # profile: (description, click, visual checks, baselines)
    "v-button": ("fio-button.json", True, ("open", "clicked"), "baselines"),
    "v-shifted": ("fio-button-shifted.json", True, ("open", "clicked"), "baselines"),
    "v-missing": ("fio-unchanged.json", False, ("open",), "baselines"),
    "v-env": ("fio-button.json", True, ("open", "clicked"), "baselines-env"),
}


def derive_env(directory):
    source, target = directory / "baselines", directory / "baselines-env"
    target.mkdir(exist_ok=False)
    for record_path in sorted(source.glob("*.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["environment"]["window_dpi"] = 120
        record["derived_for"] = "V6: a capture environment that differs from the baseline's (window DPI)"
        (target / record_path.name).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8", newline="\n")
        shutil.copyfile(record_path.with_suffix(".png"), target / record_path.with_suffix(".png").name)
    return sorted(p.name for p in target.iterdir())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stand", type=Path, help="accepted native stand profile")
    parser.add_argument("--template", type=Path,
                        default=cases.ROOT / ".local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT")
    parser.add_argument("--output", type=Path, help="new local directory")
    parser.add_argument("--derive-env", type=Path, help="series directory with approved baselines/")
    args = parser.parse_args(argv)
    if args.derive_env:
        print(json.dumps(derive_env(args.derive_env.resolve()), indent=1))
        return 0
    if not args.stand or not args.output:
        parser.error("--stand and --output are required")
    template = args.template.resolve()
    if hashlib.sha256(template.read_bytes()).hexdigest() != cases.FIO_SHA:
        raise SystemExit("FIO.ERT is not the pinned template")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    form77.extract(template, out / "fio-unchanged.json")
    description = form77.loads((out / "fio-unchanged.json").read_bytes())
    for name, x in (("fio-button.json", cases.BUTTON["x"]), ("fio-button-shifted.json", SHIFTED_X)):
        changed = json.loads(json.dumps(description))
        changed["controls"].append(dict(cases.BUTTON, x=x))
        (out / name).write_text(form77.dumps(changed), encoding="utf-8", newline="\n")
    stand = args.stand.read_text(encoding="utf-8")
    if "launcher = " + cases.toml_string(HERE / "form_launcher77.py") not in stand:
        raise SystemExit("the stand profile does not use the form launcher")
    (out / "stand.toml").write_text(stand, encoding="utf-8", newline="\n")
    for case, (form, click, states, baselines) in CASES.items():
        lines = ["schema_version = 1", "", "[project]", f'id = "visual-{case}"', "", "[build]",
                 "template = " + cases.toml_string(template),
                 "source = " + cases.toml_string(HERE / "visual_module77.1s"),
                 'encoding = "utf-8"', "form = " + cases.toml_string(form), "", "[platform]", "",
                 "[platform.parameters]"]
        if click:
            lines.append("click_id = 4161")
        text = "\n".join(lines) + "\n\n" + cases.OPEN + "\n" + (CLICK + "\n" if click else "")
        text += f'[visual]\nbaselines = "{baselines}"\n\n'
        text += "\n".join(CHECK.format(name="form-" + state, state=state) for state in states)
        text += "\n" + cases.DEADLINES
        (out / f"{case}.toml").write_text(text, encoding="utf-8", newline="\n")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}
    (out / "cases.json").write_text(json.dumps({"template_sha256": cases.FIO_SHA, "files": hashes},
                                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(hashes, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
