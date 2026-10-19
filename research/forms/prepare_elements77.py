"""Local profiles for the native probes E1–E4 of task 011 (new form controls).

Writes into a new local directory (machine paths stay out of Git):

- ``fio-elements.json`` — FIO.ERT 226×205 with seven new controls: the button
  «Проверка» of F2b (4161), a group box (4162), a label ``Надпись77`` (4163),
  a check box ``Флажок77`` (4164), number ``Число77`` 10.2 (4165), date
  ``Дата77`` (4166) and string ``Строка77`` of 20 (4167, the last record);
- ``fio-elements-short.json`` — the same with ``Строка77`` of length 3 (E3);
- ``stand.toml`` — the given stand profile (it must use the form launcher);
- ``e-elements.toml`` (E1, E2), ``e-short.toml`` (E3), ``e-conflict.toml`` (E4),
  ``e-conflict-value.toml`` (E4b: is the module's value shown in the field?).

    python -B research/forms/prepare_elements77.py --stand .local/stage10-native/series/stand.toml \
        --output .local/stage11-native/series
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prepare_cases77 as cases  # noqa: E402

form77 = cases.form77
HEIGHT = 205
ACTIONS = "type:4167=Тест77,click:4164,click:4161"
ELEMENTS = [
    cases.BUTTON,
    {"id": 4162, "class": "1CGROUPBOX", "caption": "Новые элементы", "x": 7, "y": 124, "width": 212, "height": 76},
    {"id": 4163, "class": "STATIC", "caption": "Надпись 77", "identifier": "Надпись77",
     "x": 14, "y": 136, "width": 60, "height": 8},
    {"id": 4164, "class": "CHECKBOX", "caption": "Флажок 77", "identifier": "Флажок77",
     "formula": "Harness77Флажок()", "x": 14, "y": 148, "width": 80, "height": 10},
    {"id": 4165, "class": "BMASKED", "identifier": "Число77", "type": {"kind": "number", "length": 10, "precision": 2},
     "x": 14, "y": 162, "width": 60, "height": 13},
    {"id": 4166, "class": "BMASKED", "identifier": "Дата77", "type": {"kind": "date"},
     "x": 80, "y": 162, "width": 60, "height": 13},
    {"id": 4167, "class": "1CEDIT", "identifier": "Строка77", "type": {"kind": "string", "length": 20},
     "x": 14, "y": 180, "width": 120, "height": 13},
]


def values(text, length):
    """The handler lines E1/E3 expect; a fixed-length string comes padded to its length (E1a)."""
    return (f"flag:0;clicked:1;value:Строка77=Строка|{text}|{length};value:Число77=Число|12.5;"
            "value:Дата77=Дата|2026-10-19;value:Флажок77=Число|0;label:Надпись 77")


RESULT = """[[platform.tests]]
name = "form-values"
command = "result"
expect = "passed"
expect_value = {value}
description = "Ввод WM_CHAR в 4167, BM_CLICK флажку 4164 и кнопке 4161: модуль получил значения реквизитов"
"""
CHECKS = """[visual]
baselines = "baselines"

[[visual.checks]]
name = "elements-open"
state = "open"
window = "form"

[[visual.checks]]
name = "elements-clicked"
state = "clicked"
window = "form"
"""
CONFLICT = """[[platform.tests]]
name = "form-open-conflict"
command = "open"
expect = "failed"
description = "Ожидание: модуль с Перем Фамилия (имя реквизита формы) не компилируется"
"""
OPENED = """[[platform.tests]]
name = "form-open-shadowed"
command = "open"
expect = "passed"
description = "E4b: форма открыта; текст поля «Фамилия» — свидетельство, дошло ли присвоение модуля"
"""
CASES = {  # profile: (description, module, actions, tests, visual checks)
    "e-elements": ("fio-elements.json", "elements_module77.1s", True, cases.OPEN + "\n" + RESULT.format(
        value=cases.toml_string(values("Тест77", 20))), CHECKS),
    "e-short": ("fio-elements-short.json", "elements_module77.1s", True, cases.OPEN + "\n" + RESULT.format(
        value=cases.toml_string(values("Тес", 3))), None),
    "e-conflict": (None, "conflict_module77.1s", False, CONFLICT, None),
    "e-conflict-value": (None, "conflict_value_module77.1s", False, OPENED, None),
}


def described(description, length):
    changed = copy.deepcopy(description)
    changed["form"]["height"] = HEIGHT
    changed["controls"] += [dict(copy.deepcopy(item), layer="Основной") for item in ELEMENTS]
    changed["controls"][-1]["type"]["length"] = length
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stand", type=Path, required=True, help="accepted native stand profile")
    parser.add_argument("--template", type=Path,
                        default=cases.ROOT / ".local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT")
    parser.add_argument("--output", type=Path, required=True, help="new local directory")
    args = parser.parse_args(argv)
    template = args.template.resolve()
    if hashlib.sha256(template.read_bytes()).hexdigest() != cases.FIO_SHA:
        raise SystemExit("FIO.ERT is not the pinned template")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    form77.extract(template, out / "fio-unchanged.json")
    description = form77.loads((out / "fio-unchanged.json").read_bytes())
    for name, length in (("fio-elements.json", 20), ("fio-elements-short.json", 3)):
        (out / name).write_text(form77.dumps(described(description, length)), encoding="utf-8", newline="\n")
    stand = args.stand.read_text(encoding="utf-8")
    if "launcher = " + cases.toml_string(HERE / "form_launcher77.py") not in stand:
        raise SystemExit("the stand profile does not use the form launcher")
    (out / "stand.toml").write_text(stand, encoding="utf-8", newline="\n")
    for case, (form, module, act, tests, checks) in CASES.items():
        lines = ["schema_version = 1", "", "[project]", f'id = "elements-{case}"', "", "[build]",
                 "template = " + cases.toml_string(template), "source = " + cases.toml_string(HERE / module),
                 'encoding = "utf-8"']
        if form:
            lines.append("form = " + cases.toml_string(form))
        lines += ["", "[platform]", "", "[platform.parameters]"]
        if act:
            lines.append("actions = " + cases.toml_string(ACTIONS))
        text = "\n".join(lines) + "\n\n" + tests + "\n" + (checks + "\n" if checks else "") + cases.DEADLINES
        (out / f"{case}.toml").write_text(text, encoding="utf-8", newline="\n")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}
    (out / "cases.json").write_text(json.dumps({"template_sha256": cases.FIO_SHA, "files": hashes},
                                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(hashes, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
