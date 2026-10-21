"""Build a synthetic form from a verified layout, never execute the template.

Replaces the entire module, labels, test button formula and edit-field formula.
All other compound-file streams must stay byte-for-byte identical.
The Dialog Stream length prefix is recalculated: fixtures built before
this fix kept the template length 2427 for 2452 bytes of text.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from harness77 import ert_module as ert


def build(template, output):
    raw = template.read_bytes()
    compound = ert.CompoundFile(raw)
    module = compound.find_stream(ert.MODULE_STREAM)
    dialog = compound.find_stream(ert.DIALOG_STREAM)
    layout = ert.decode_dialog(compound.read_stream(dialog))
    changes = {
        'Фамилия, Имя, Отчество': 'Harness77: FormEx',
        '"4154","","Выполнить()#Закрыть"': '"4154","Harness77Apply","Выполнить()"',
        '"4159","","","Фамилия"': '"4159","","Harness77Changed()","Фамилия"',
        'Фамилия:': 'Input:', 'Имя:': 'Result:', 'Отчество:': 'Change events:',
    }
    for old, new in changes.items():
        if layout.count(old) != 1:
            raise ValueError("Unexpected template layout: " + old)
        layout = layout.replace(old, new)
    dialog_payload = ert.encode_dialog(layout)
    source = ert.normalize_newlines(Path(__file__).with_name("formex_fixture.1s").read_text(encoding="utf-8"))
    source = source.replace("__RESULT__", str((output / "form-result.txt").resolve()))
    replacement = {module.entry_id: ert.compress_module(source.encode("cp1251")), dialog.entry_id: dialog_payload}
    result = compound.rebuild(replacement)
    checked = ert.CompoundFile(result)
    hashes = []
    for entry in compound.directory_entries:
        if entry.object_type != 2:
            continue
        before = compound.read_stream(entry)
        after = checked.read_stream(checked.find_stream(entry.name))
        assert after == replacement.get(entry.entry_id, before), entry.name
        hashes.append({"stream": entry.name, "changed": before != after,
                       "before": hashlib.sha256(before).hexdigest(), "after": hashlib.sha256(after).hexdigest()})
    output.mkdir(parents=True, exist_ok=False)
    target = output / "formex-fixture.ert"
    target.write_bytes(result)
    assert ert.extract_text(target) == source
    assert ert.extract_dialog(target) == layout
    manifest = {"template": str(template.resolve()), "template_sha256": hashlib.sha256(raw).hexdigest(),
                "synthetic_sha256": hashlib.sha256(result).hexdigest(), "streams": hashes,
                "original_module_executed": False, "business_data_access": False}
    (output / "fixture-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.template, args.output)
