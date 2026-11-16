"""Prepare an editable task-108 ERT scenario without starting 1C."""
import argparse
import json
from pathlib import Path
from harness77 import ert_module, form77

ITEMS = ['Первый', '', 'Дубль', 'Дубль', ' а ']
STEPS = [
    {'check_combo': 'Список77', 'items': ITEMS},
    {'no_message': 'handler108'},
    {'check_combo': 'Список77', 'items': ITEMS},
    {'select': 'Список77', 'text': 'Первый'},
    {'no_message': 'handler108'},
    {'select': 'Список77', 'text': ''},
    {'message': 'handler108:1:2'},
    {'check_combo': 'Список77', 'items': ITEMS},
]


def prepare(template, stand, output):
    output.mkdir(parents=True, exist_ok=False)
    description = form77.describe(ert_module.extract_dialog(template))
    description['form']['height'] = 215
    description['controls'].append(dict(identifier='Список77', formula='Выбор77()',
        x=10, y=130, width=180, height=75, **{'class': 'COMBOBOX'}))
    (output/'form.json').write_text(form77.dumps(description), encoding='utf-8')
    (output/'module.1s').write_bytes(Path(__file__).with_name('module.1s').read_bytes())
    (output/'steps.json').write_text(json.dumps(STEPS, ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'stand.toml').write_bytes(stand.read_bytes())
    (output/'configuration').mkdir()
    q = json.dumps(template.resolve().as_posix(), ensure_ascii=False)
    (output/'project.toml').write_text(f'''schema_version = 4
[project]
id = "combo-check-108"
[build]
template = {q}
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
''', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('template', 'stand', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    args = parser.parse_args()
    prepare(args.template, args.stand, args.output)
