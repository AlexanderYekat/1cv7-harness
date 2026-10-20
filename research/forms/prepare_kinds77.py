"""Local profiles for the native probes K1–K5 of task 013 (kinds checked by name).

Writes into a new local directory (machine paths stay out of Git):

- ``k-unchanged.json`` — ``form-extract`` of the pinned Договор_Оргтехники.ert:
  «Тариф» (4154) Справочник.Тарифы, 25507 in the ERT's copy, 26051 in the base;
  «ВыбранДоговор» (4157) Справочник.Договоры;
- ``k-kept.json`` — the form 320×210 plus ``Выписка77`` Документ.Выписка (4160),
  a kind the copy has;
- ``k-replaced.json`` — plus ``ТипЦен77`` Справочник.ТипыЦен (4161) as well, a
  kind the copy lacks: the copy is replaced and «Тариф» renumbered;
- ``k-unchanged.1s``, ``k-kept.1s``, ``k-replaced.1s`` — the probe module with the
  fields of each case;
- ``dogovor-basecopy.ert`` — the template whose own copy of the metadata is the
  stand base's ``Main MetaData Stream``, the dialog untouched: «Тариф» keeps
  25507, which that copy lacks (K5, built without a description);
- ``stand.toml`` — the given stand profile (it must use the form launcher);
- ``k1-unchanged.toml``, ``k2-kept.toml``, ``k3-replaced.toml``,
  ``k4-foreign.toml`` (K3 with ``[build] metadata`` of another configuration),
  ``k5-stale.toml``, ``k5b-stale-assign.toml`` (K5 whose module first assigns an
  element of Справочник.Сотрудники to «Тариф»: it reads the base's data, with
  ``k-stale-assign.1s``); ``cases.json`` with the hashes.

    python -B research/forms/prepare_kinds77.py --stand .local/stage12-native/series/stand.toml \
        --foreign C:/…/test-base-surgut/1Cv7.MD --output .local/stage13-native/series
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
TEMPLATE_SHA = "f5aacf9d8fd2e99784aeb72c2c9f72e133c9a9abb3aad2cfb49da80d02ef5102"  # Договор_Оргтехники.ert
STAND_MD = "931b26eb2e388ba3000196ab024351e65cb324e02e885dc4cef5be68059ecfa1"
FOREIGN_MD = "82d8d1df"  # Торговля+Склад, редакция 9.2 (task 012, the owner's check); prefix only
HEIGHT = 210
MARK = "    // harness77: поля"
OLD = (("Тариф", "Справочник|Тарифы"), ("ВыбранДоговор", "Справочник|Договоры"))
NEW = ({"id": 4160, "class": "BMASKED", "caption": "", "identifier": "Выписка77", "x": 110, "y": 170, "width": 120,
        "height": 13, "formula": "", "layer": "Основной", "type": {"kind": "reference", "object": "Документ.Выписка"}},
       {"id": 4161, "class": "BMASKED", "caption": "", "identifier": "ТипЦен77", "x": 110, "y": 186, "width": 120,
        "height": 13, "formula": "", "layer": "Основной", "type": {"kind": "reference", "object": "Справочник.ТипыЦен"}})
SEEN = {"Выписка77": "Документ|Выписка", "ТипЦен77": "Справочник|ТипыЦен"}
# description, added fields; the module reports the old fields and the added ones.
FORMS = {"k-unchanged": 0, "k-kept": 1, "k-replaced": 2}
# K5b, added after K5 (task 013): does the field without a kind hold an element of another catalog?
ASSIGN = """    Спр77 = СоздатьОбъект("Справочник.Сотрудники");
    Спр77.ВыбратьЭлементы(0);
    Пока Спр77.ПолучитьЭлемент() = 1 Цикл
        Если Спр77.ЭтоГруппа() = 0 Тогда
            Тариф = Спр77.ТекущийЭлемент();
            Прервать;
        КонецЕсли;
    КонецЦикла;
"""
ASSIGNED = "value:Тариф=Справочник|Сотрудники;value:ВыбранДоговор=Справочник|Договоры"
CASES = {  # profile: (template or None for the pinned one, description, module, [build] metadata, value)
    "k1-unchanged": (None, "k-unchanged.json", "k-unchanged.1s", None, 0),
    "k2-kept": (None, "k-kept.json", "k-kept.1s", None, 1),
    "k3-replaced": (None, "k-replaced.json", "k-replaced.1s", None, 2),
    "k4-foreign": (None, "k-replaced.json", "k-replaced.1s", "foreign", 2),
    "k5-stale": ("dogovor-basecopy.ert", None, "k-unchanged.1s", None, 0),
    "k5b-stale-assign": ("dogovor-basecopy.ert", None, "k-stale-assign.1s", None, ASSIGNED),
}
# The first K1 (62be9163) declared cases.OPEN: the launcher's layout check found no single
# mapping for this template (2.32 px over 2 px on its BMASKED windows), unrelated to the
# kinds, so the probes declare the load check instead (task 013).
LOAD = """[[platform.tests]]
name = "form-load"
command = "check"
expect = "passed"
expect_value = "1"
description = "1С создала отчёт, форма открыта и закрыта"
"""
RESULT = """[[platform.tests]]
name = "form-kinds"
command = "result"
expect = "passed"
expect_value = {value}
description = "Модуль при открытии получил тип и вид каждого поля вида"
"""


def fields(added):
    return list(OLD) + [(item["identifier"], SEEN[item["identifier"]]) for item in NEW[:added]]


def value(added):
    if isinstance(added, str):
        return added
    return ";".join(f"value:{name}={seen}" for name, seen in fields(added))


def module(text, added, before=""):
    if text.count(MARK) != 1:
        raise SystemExit("the probe module has no single field mark")
    calls = "\n".join(f'    Harness77Поле("{name}", {name});' for name, _ in fields(added))
    return text.replace(MARK, before + calls)


def with_copy(template, md):
    """The template whose Main MetaData Stream is the base's, with the NUL byte of an ERT copy."""
    from harness77 import ert_module as ert
    from harness77.metadata77 import STREAM, Metadata
    compound = ert.CompoundFile(template.read_bytes())
    entry = next(e for e in compound.directory_entries if e.object_type == 2 and e.name == STREAM)
    payload = Metadata(md.read_bytes(), md).ert_stream()
    data = compound.rebuild({entry.entry_id: payload})
    built = ert.CompoundFile(data)
    for old in (e for e in compound.directory_entries if e.object_type == 2):
        new = next(e for e in built.directory_entries if e.object_type == 2 and e.name == old.name)
        expected = payload if old.name == STREAM else compound.read_stream(old)
        if built.read_stream(new) != expected:
            raise SystemExit(f"stream {old.name} differs after the copy")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stand", type=Path, required=True, help="accepted native stand profile")
    parser.add_argument("--template", type=Path,
                        default=cases.ROOT / ".local/bases/base-for-test/ExtForms/Договор_Оргтехники.ert")
    parser.add_argument("--foreign", type=Path, required=True,
                        help="1Cv7.MD of another configuration (read only), the target of K4")
    parser.add_argument("--output", type=Path, required=True, help="new local directory")
    args = parser.parse_args(argv)
    template = args.template.resolve()
    if hashlib.sha256(template.read_bytes()).hexdigest() != TEMPLATE_SHA:
        raise SystemExit("Договор_Оргтехники.ert is not the pinned template")
    stand = args.stand.read_text(encoding="utf-8")
    if "launcher = " + cases.toml_string(HERE / "form_launcher77.py") not in stand:
        raise SystemExit("the stand profile does not use the form launcher")
    stand_md = cases.ROOT / ".local/bases/base-for-test/1Cv7.MD"
    if hashlib.sha256(stand_md.read_bytes()).hexdigest() != STAND_MD:
        raise SystemExit("the stand base's 1Cv7.MD is not the pinned one")
    foreign = args.foreign.resolve()
    if not hashlib.sha256(foreign.read_bytes()).hexdigest().startswith(FOREIGN_MD):
        raise SystemExit("the foreign 1Cv7.MD is not the owner's Торговля+Склад 9.2")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "stand.toml").write_text(stand, encoding="utf-8", newline="\n")
    (out / "dogovor-basecopy.ert").write_bytes(with_copy(template, stand_md))
    form77.extract(template, out / "k-unchanged.json")
    description = form77.loads((out / "k-unchanged.json").read_bytes())
    text = (HERE / "kinds_module77.1s").read_text(encoding="utf-8")
    for name, added in FORMS.items():
        if added:
            changed = copy.deepcopy(description)
            changed["form"]["height"] = HEIGHT
            changed["controls"] += copy.deepcopy(list(NEW[:added]))
            (out / f"{name}.json").write_text(form77.dumps(changed), encoding="utf-8", newline="\n")
        (out / f"{name}.1s").write_text(module(text, added), encoding="utf-8", newline="\n")
    (out / "k-stale-assign.1s").write_text(module(text, 0, ASSIGN), encoding="utf-8", newline="\n")
    for case, (own, form, source, metadata, added) in CASES.items():
        lines = ["schema_version = 1", "", "[project]", f'id = "kinds-{case}"', "", "[build]",
                 "template = " + cases.toml_string(own or template), "source = " + cases.toml_string(source),
                 'encoding = "utf-8"']
        if form:
            lines.append("form = " + cases.toml_string(form))
        if metadata:
            lines.append("metadata = " + cases.toml_string(foreign))
        lines += ["", "[platform]", "", "[platform.parameters]"]
        tests = LOAD + "\n" + RESULT.format(value=cases.toml_string(value(added)))
        text_case = "\n".join(lines) + "\n\n" + tests + "\n" + cases.DEADLINES
        (out / f"{case}.toml").write_text(text_case, encoding="utf-8", newline="\n")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}
    (out / "cases.json").write_text(json.dumps({"template_sha256": TEMPLATE_SHA, "stand_md_sha256": STAND_MD,
                                                "files": hashes}, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")
    print(json.dumps(hashes, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
