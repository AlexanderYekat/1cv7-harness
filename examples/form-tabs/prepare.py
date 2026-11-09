"""Generate tasks 046 and 047 profiles using the accepted 043 fixture, without starting 1C."""
import argparse
import importlib.util
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mixed043', ROOT / 'examples/journal-children-mixed/prepare.py')
mixed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mixed)
CASES = ('success', 'second', 'missing', 'wrong-rows', 'no-copy')
EDIT_CASES = ('save', 'cancel')


def case_scenario(name):
    text = mixed.case_scenario('invoice-near' if name == 'second' else 'invoice-far')
    marker = ', browser_visible = false }'
    assert text.count(marker) == 1
    text = text.replace(marker, ', browser_visible = false, browse = true }')
    tail = '''    { tab = "Табличная часть", browser_visible = true },
    { rows = 1 },
    { value = "Количество", row = 1, text = "1" },
    { value = "Цена", row = 1, text = "50" },
    { value = "Сумма", row = 1, text = "50" },
    { value = "Всего", row = 1, text = "50" },
    { value = "НДС", row = 1, text = "0" },
    { value = "НП", row = 1, text = "0" },
    { total = "Сумма", text = "50" },
    { tab = "Шапка", browser_visible = false },
    { value = "Комментарий", text = "Harness77 подчиненный 043" },
'''
    if name == 'missing':
        tail = tail.replace('tab = "Табличная часть"', 'tab = "Несуществующая вкладка 046"', 1)
    if name == 'wrong-rows':
        tail = tail.replace('{ rows = 1 }', '{ rows = 2 }')
    return text.replace('\n]\n', '\n' + tail + ']\n')


def edit_scenario(name):
    baseline = mixed.state()
    final = baseline.replace('1:50:50:50:0:0;', '2:50:100:100:0:0;', 1) if name == 'save' else baseline
    text = mixed.case_scenario('invoice-far').replace(
        ', browser_visible = false }',
        ', browser_visible = false, edit = true, expected_after = ' + json.dumps(final, ensure_ascii=False) + ' }')
    text = text[:text.rindex('expect_value = ')] + 'expect_value = ' + json.dumps(final, ensure_ascii=False) + '\n'
    tail = '''    { tab = "Табличная часть", browser_visible = true },
    { rows = 1 },
    { value = "Количество", row = 1, text = "1" },
    { value = "Сумма", row = 1, text = "50" },
    { row = 1 },
    { cell = "Количество", text = "2" },
    { value = "Количество", row = 1, text = "2" },
    { value = "Цена", row = 1, text = "50" },
    { value = "Сумма", row = 1, text = "100" },
    { value = "Всего", row = 1, text = "100" },
    { total = "Сумма", text = "100" },
    { tab = "Шапка", browser_visible = false },
'''
    if name == 'save':
        tail += '''    { click = "КнопкаЗаписать" },
    { close_form = true, closes = true },
'''
        quantity, amount = '2', '100'
    else:
        tail += '''    { close_form = true },
    { dialog = "Сохранить Документ?", button = "Нет", closes = true },
'''
        quantity, amount = '1', '50'
    tail += f'''    {{ reopen = true }},
    {{ tab = "Табличная часть", browser_visible = true }},
    {{ rows = 1 }},
    {{ value = "Количество", row = 1, text = "{quantity}" }},
    {{ value = "Сумма", row = 1, text = "{amount}" }},
    {{ value = "Всего", row = 1, text = "{amount}" }},
    {{ total = "Сумма", text = "{amount}" }},
    {{ tab = "Шапка", browser_visible = false }},
'''
    return text.replace('\n]\n', '\n' + tail + ']\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stand', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--edit', action='store_true', help='generate the save and cancel cases of task 047')
    a = p.parse_args()
    stand_text = a.stand.resolve(strict=True).read_text('utf-8')
    stand = tomllib.loads(stand_text)['stand']
    if not stand['base'].get('copy_path'):
        p.error('stand requires registered copy_path')
    paths = [stand.get('launcher'), *stand.get('paths', {}).values(), stand['base']['path'], stand['base']['copy_path']]
    if any(v and not Path(v).is_absolute() for v in paths):
        p.error('stand paths must be absolute')
    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in EDIT_CASES if a.edit else CASES:
        folder = output / name
        (folder / 'configuration').mkdir(parents=True)
        header = '\n'.join(['schema_version = 1', '[project]', f'id = "form-tabs-{name}"', '[build]',
            'template = ' + json.dumps((ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT').as_posix()),
            'source = ' + json.dumps((ROOT / 'research/forms/probe_module77.1s').as_posix()), 'encoding = "utf-8"',
            *([] if name == 'no-copy' else ['[configuration]', 'modules = ' + json.dumps((folder / 'configuration').as_posix())]),
            '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120', 'cancel_timeout_s = 15',
            'shutdown_timeout_s = 30', 'total_timeout_s = 600', ''])
        content = header + (edit_scenario(name) if a.edit else case_scenario(name))
        tomllib.loads(content)
        (folder / 'project.toml').write_text(content, 'utf-8', newline='\n')
    import re
    stand_text, n = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps((ROOT / 'research/forms/form_launcher77.py').as_posix()), stand_text)
    if n != 1:
        p.error('stand requires one launcher line')
    (output / 'stand.toml').write_text(stand_text, 'utf-8', newline='\n')
    suites = {'suite': EDIT_CASES} if a.edit else {
        'suite': ['success', 'second', 'repeat'],
        'suite-missing': ['missing', 'after-failure'],
        'suite-rows': ['wrong-rows', 'after-failure'],
    }
    for name, ids in suites.items():
        lines = ['schema_version = 1', '[suite]', f'id = "form-tabs-{name}"']
        for id_ in ids:
            case = 'success' if id_ in ('repeat', 'after-failure') else id_
            lines += ['[[scenarios]]', f'id = "{id_}"', f'project = "{case}/project.toml"']
        (output / (name + '.toml')).write_text('\n'.join(lines)+'\n', 'utf-8', newline='\n')
    print(json.dumps(dict(output=str(output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
