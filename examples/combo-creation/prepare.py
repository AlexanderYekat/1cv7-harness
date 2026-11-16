"""Prepare task 107 on the qualified FIO.ERT template; does not launch 1C."""
import argparse
import json
from pathlib import Path
from harness77 import ert_module, form77


def prepare(template, stand, output):
    output.mkdir(parents=True, exist_ok=False)
    description = form77.describe(ert_module.extract_dialog(template))
    description["form"]["height"] = 215
    description["controls"].append({"class": "COMBOBOX", "identifier": "Список77",
        "formula": "Выбор77()", "x": 10, "y": 130, "width": 180, "height": 75})
    (output / "form.json").write_text(form77.dumps(description), encoding="utf-8")
    source = Path(__file__).with_name("module.1s").read_text(encoding="utf-8")
    (output / "module.1s").write_text(source, encoding="utf-8")
    (output / "configuration").mkdir()
    (output / "stand.toml").write_bytes(stand.read_bytes())
    q = lambda p: json.dumps(str(p.resolve()).replace("\\", "/"), ensure_ascii=False)
    steps = [
        {"inspect_combo": "Список77"},
        {"no_message": "combo107:1:1"},
        {"select": "Список77", "text": "Первый"},
        {"no_message": "combo107:1:1"},
        {"select": "Список77", "text": ""},
        {"message": "combo107:1:3"},
        {"inspect_combo": "Список77"},
    ]
    (output / "steps.json").write_text(json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    profile = f'''schema_version = 4
[project]
id = "combo-creation-107"
[build]
template = {q(template)}
source = "module.1s"
encoding = "utf-8"
form = "form.json"
[configuration]
modules = "configuration"
[platform.parameters]
steps_file = "steps.json"
[[platform.tests]]
name = "form-open"
command = "open"
expect = "passed"
expect_value = "1"
[[platform.tests]]
name = "scenario"
command = "result"
expect = "passed"
[deadlines]
open_timeout_s = 120
calculation_timeout_s = 120
cancel_timeout_s = 15
shutdown_timeout_s = 30
total_timeout_s = 600
'''
    (output / "project.toml").write_text(profile, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("template", "stand", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    prepare(args.template.resolve(), args.stand.resolve(), args.output.resolve())
