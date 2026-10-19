"""Local profiles for the native probes R1–R4 of task 012 (reference-typed form fields).

Writes into a new local directory (machine paths stay out of Git):

- ``fio-references.json`` — FIO.ERT 226×245 with the button «Проверка» of F2b
  (4161), a group box (4162) and six reference fields named by type, not by
  number: ``Контрагент77`` Справочник.Контрагенты (4163), ``Справочник77``
  Справочник (4164), ``Документ77`` Документ (4165), ``Пол77`` Перечисление.Пол
  (4166), ``Счет77`` Счет.Основной (4167), ``ВидСубконто77`` ВидСубконто (4168);
- ``fio-unknown.json`` — the same with ``Справочник.НетТакого`` (R4);
- ``references_wrong_module77.1s`` — the probe module in its variant R3;
- ``fio-copy.ert`` — FIO.ERT whose own copy of the metadata (``Main MetaData
  Stream``) is that of the corpus ERT 2323232.ert, «Бухгалтерский учет, редакция
  4.2» (R5: the copy has the kinds and stays);
- ``stand.toml`` — the given stand profile (it must use the form launcher);
- ``r-references.toml`` (R1, R2), ``r-wrong-kind.toml`` (R3), ``r-unknown.toml`` (R4),
  ``r-kept.toml`` (R5).

The profiles give no ``[build] metadata``: the run takes the stand base's 1Cv7.MD.
FIO.ERT carries an empty copy, so for R1–R3 the build replaces it (task 012, R1c).

    python -B research/forms/prepare_references77.py --stand .local/stage11-native/series/stand.toml \
        --output .local/stage12-native/series
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
HEIGHT = 245
ACTIONS = "click:4161"
FIELDS = (("Контрагент77", "Справочник.Контрагенты"), ("Справочник77", "Справочник"), ("Документ77", "Документ"),
          ("Пол77", "Перечисление.Пол"), ("Счет77", "Счет.Основной"), ("ВидСубконто77", "ВидСубконто"))
ELEMENTS = [cases.BUTTON,
            {"id": 4162, "class": "1CGROUPBOX", "caption": "Ссылочные поля", "x": 7, "y": 124, "width": 212,
             "height": 116}]
ELEMENTS += [{"id": 4163 + number, "class": "BMASKED", "identifier": name, "type": {"kind": "reference", "object": kind},
              "x": 14, "y": 136 + 16 * number, "width": 198, "height": 13} for number, (name, kind) in enumerate(FIELDS)]
# What the handler reports per field (task 012): type, kind, same as assigned, empty.
VALUES = {"Контрагент77": "Справочник|Контрагенты|same:1|empty:0", "Справочник77": "Справочник|Сотрудники|same:1|empty:0",
          "Документ77": "Документ|Выписка|same:1|empty:0", "Пол77": "Перечисление|Пол|same:1|empty:0",
          "Счет77": "Счет|Основной|same:1|empty:0", "ВидСубконто77": "ВидСубконто|-|same:1|empty:0"}
# R3: the kind field keeps its kind; the Сотрудники element becomes an empty Контрагенты.
WRONG = dict(VALUES, Контрагент77="Справочник|Контрагенты|same:0|empty:1")


def value(values):
    return "clicked:1;" + ";".join(f"value:{name}={values[name]}" for name, _ in FIELDS)


RESULT = """[[platform.tests]]
name = "form-references"
command = "result"
expect = "passed"
expect_value = {value}
description = "BM_CLICK кнопке 4161: тип, вид и пустота значений шести ссылочных полей в модуле"
"""
CHECKS = """[visual]
baselines = "baselines"

[[visual.checks]]
name = "references-open"
state = "open"
window = "form"

[[visual.checks]]
name = "references-clicked"
state = "clicked"
window = "form"
"""
CASES = {  # profile: (template, description, module, tests, visual checks); None: FIO.ERT
    "r-references": (None, "fio-references.json", HERE / "references_module77.1s",
                     cases.OPEN + "\n" + RESULT.format(value=cases.toml_string(value(VALUES))), CHECKS),
    "r-wrong-kind": (None, "fio-references.json", "references_wrong_module77.1s",
                     cases.OPEN + "\n" + RESULT.format(value=cases.toml_string(value(WRONG))), None),
    "r-unknown": (None, "fio-unknown.json", HERE / "references_module77.1s", cases.OPEN, None),
    "r-kept": ("fio-copy.ert", "fio-references.json", HERE / "references_module77.1s",
               cases.OPEN + "\n" + RESULT.format(value=cases.toml_string(value(VALUES))), None),
}
COPY_SHA = "0a129e692570fdd705716423470f3009f3596100efd11f8cd23f999913b0495a"  # 2323232.ert


def with_copy(template, source):
    """FIO.ERT whose Main MetaData Stream is the source ERT's; every other stream is kept."""
    from harness77 import ert_module as ert
    from harness77.metadata77 import STREAM

    def entry(compound):
        return next(e for e in compound.directory_entries if e.object_type == 2 and e.name == STREAM)
    compound, other = ert.CompoundFile(template.read_bytes()), ert.CompoundFile(source.read_bytes())
    payload = other.read_stream(entry(other))
    data = compound.rebuild({entry(compound).entry_id: payload})
    built = ert.CompoundFile(data)
    for old in (e for e in compound.directory_entries if e.object_type == 2):
        new = next(e for e in built.directory_entries if e.object_type == 2 and e.name == old.name)
        expected = payload if old.name == STREAM else compound.read_stream(old)
        if built.read_stream(new) != expected:
            raise SystemExit(f"stream {old.name} differs after the copy")
    return data


def described(description, unknown=False):
    changed = copy.deepcopy(description)
    changed["form"]["height"] = HEIGHT
    changed["controls"] += [dict(copy.deepcopy(item), layer="Основной") for item in ELEMENTS]
    if unknown:
        changed["controls"][-6]["type"]["object"] = "Справочник.НетТакого"
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stand", type=Path, required=True, help="accepted native stand profile")
    parser.add_argument("--template", type=Path,
                        default=cases.ROOT / ".local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT")
    parser.add_argument("--copy-from", type=Path, default=cases.ROOT / ".local/bases/base-for-test/ExtForms/2323232.ert",
                        help="corpus ERT whose copy of the metadata R5 takes")
    parser.add_argument("--output", type=Path, required=True, help="new local directory")
    args = parser.parse_args(argv)
    template = args.template.resolve()
    if hashlib.sha256(template.read_bytes()).hexdigest() != cases.FIO_SHA:
        raise SystemExit("FIO.ERT is not the pinned template")
    if hashlib.sha256(args.copy_from.read_bytes()).hexdigest() != COPY_SHA:
        raise SystemExit("2323232.ert is not the pinned source of the copy")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "fio-copy.ert").write_bytes(with_copy(template, args.copy_from))
    form77.extract(template, out / "fio-unchanged.json")
    description = form77.loads((out / "fio-unchanged.json").read_bytes())
    for name, unknown in (("fio-references.json", False), ("fio-unknown.json", True)):
        (out / name).write_text(form77.dumps(described(description, unknown)), encoding="utf-8", newline="\n")
    module = (HERE / "references_module77.1s").read_text(encoding="utf-8")
    if module.count('Вариант77 = "R1";') != 1:
        raise SystemExit("the probe module has no single variant line")
    (out / "references_wrong_module77.1s").write_text(module.replace('Вариант77 = "R1";', 'Вариант77 = "R3";'),
                                                      encoding="utf-8", newline="\n")
    stand = args.stand.read_text(encoding="utf-8")
    if "launcher = " + cases.toml_string(HERE / "form_launcher77.py") not in stand:
        raise SystemExit("the stand profile does not use the form launcher")
    (out / "stand.toml").write_text(stand, encoding="utf-8", newline="\n")
    for case, (own, form, module_path, tests, checks) in CASES.items():
        lines = ["schema_version = 1", "", "[project]", f'id = "references-{case}"', "", "[build]",
                 "template = " + cases.toml_string(own or template), "source = " + cases.toml_string(module_path),
                 'encoding = "utf-8"', "form = " + cases.toml_string(form),
                 "", "[platform]", "", "[platform.parameters]", "actions = " + cases.toml_string(ACTIONS)]
        text = "\n".join(lines) + "\n\n" + tests + "\n" + (checks + "\n" if checks else "") + cases.DEADLINES
        (out / f"{case}.toml").write_text(text, encoding="utf-8", newline="\n")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}
    (out / "cases.json").write_text(json.dumps({"template_sha256": cases.FIO_SHA, "files": hashes},
                                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(hashes, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
