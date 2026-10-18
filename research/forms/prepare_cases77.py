"""Local profiles and form descriptions for the native probes F0–F4 of task 008.

Writes into a new local directory (machine paths stay out of Git):

- ``fio-unchanged.json`` — ``form-extract`` of the pinned FIO.ERT;
- ``fio-button.json`` — plus the button «Проверка», ID 4161, x 152, y 16,
  66×13, formula ``Harness77Нажатие()`` (F2 ran with y 4, under the caption: F2b);
- ``fio-button-empty.json`` — the same button calling ``Harness77Пусто()``;
- ``stand.toml`` — the given stand profile with ``launcher`` set to the form
  launcher;
- ``f0.toml`` … ``f4.toml`` — project profiles with the expectations of the task.

    python -B research/forms/prepare_cases77.py --stand .local/stage4-native/stand-native.toml \
        --output .local/stage8-native
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from harness77 import form77  # noqa: E402

FIO_SHA = "096e1a05f871158b9ec5adaafa397adca87cee4aae8cd6f28f130080ac318b4a"
BUTTON = {"id": 4161, "class": "BUTTON", "caption": "Проверка", "x": 152, "y": 16, "width": 66, "height": 13,
          "formula": "Harness77Нажатие()", "identifier": "", "layer": "Основной"}
DEADLINES = """[deadlines]
open_timeout_s = 120
calculation_timeout_s = 120
cancel_timeout_s = 15
shutdown_timeout_s = 30
total_timeout_s = 600
"""
OPEN = """[[platform.tests]]
name = "form-open"
command = "open"
expect = "passed"
expect_value = "1"
description = "Форма открыта видимой; окна элементов соответствуют описанию"
"""
CASES = {
    "f0": (None, None, """[[platform.tests]]
name = "form-close"
command = "result"
expect = "passed"
description = "Форма закрыта контроллером"
"""),
    "f1": ("fio-unchanged.json", None, """[[platform.tests]]
name = "form-close"
command = "result"
expect = "passed"
description = "Форма из описания без правок закрыта контроллером"
"""),
    "f2": ("fio-button.json", 4161, """[[platform.tests]]
name = "click-4161"
command = "result"
expect = "passed"
expect_value = "clicked:1"
description = "BM_CLICK кнопке 4161 вызывает Harness77Нажатие ровно один раз"
"""),
    "f3": ("fio-button-empty.json", 4161, """[[platform.tests]]
name = "click-4161-no-marker"
command = "result"
expect = "failed"
description = "Ожидаемый отрицательный: обработчик кнопки не пишет маркер"
"""),
    "f4": ("fio-unchanged.json", 4161, """[[platform.tests]]
name = "click-absent-4161"
command = "result"
expect = "failed"
description = "Ожидаемый отрицательный: кнопки 4161 в форме нет"
"""),
}


def toml_string(value):
    return json.dumps(str(value).replace("\\", "/"), ensure_ascii=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stand", type=Path, required=True, help="accepted native stand profile")
    parser.add_argument("--template", type=Path,
                        default=ROOT / ".local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT")
    parser.add_argument("--output", type=Path, required=True, help="new local directory")
    args = parser.parse_args(argv)
    template = args.template.resolve()
    if hashlib.sha256(template.read_bytes()).hexdigest() != FIO_SHA:
        raise SystemExit("FIO.ERT is not the pinned template")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    form77.extract(template, out / "fio-unchanged.json")
    description = form77.loads((out / "fio-unchanged.json").read_bytes())
    for name, formula in (("fio-button.json", BUTTON["formula"]), ("fio-button-empty.json", "Harness77Пусто()")):
        changed = json.loads(json.dumps(description))
        changed["controls"].append(dict(BUTTON, formula=formula))
        (out / name).write_text(form77.dumps(changed), encoding="utf-8", newline="\n")
    stand = args.stand.read_text(encoding="utf-8")
    stand, count = re.subn(r'(?m)^launcher = .*$', "launcher = " + toml_string(HERE / "form_launcher77.py"), stand)
    if count != 1:
        raise SystemExit("the stand profile has no single launcher line")
    (out / "stand.toml").write_text(stand, encoding="utf-8", newline="\n")
    for case, (form, click, test) in CASES.items():
        lines = ["schema_version = 1", "", "[project]", f'id = "form-{case}"', "", "[build]",
                 "template = " + toml_string(template), "source = " + toml_string(HERE / "probe_module77.1s"),
                 'encoding = "utf-8"']
        if form:
            lines.append("form = " + toml_string(form))
        lines += ["", "[platform]", "", "[platform.parameters]"]
        if click is not None:
            lines.append(f"click_id = {click}")
        text = "\n".join(lines) + "\n\n" + OPEN + "\n" + test + "\n" + DEADLINES
        (out / f"{case}.toml").write_text(text, encoding="utf-8", newline="\n")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}
    (out / "cases.json").write_text(json.dumps({"template_sha256": FIO_SHA, "files": hashes},
                                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(hashes, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
