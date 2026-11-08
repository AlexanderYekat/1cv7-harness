"""Generate task 044 profiles and suites without starting 1C."""
import argparse
import json
from pathlib import Path
import re
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMMENT = 'Harness77 подчиненный 044 изменён'
CASES = ('success', 'cancel', 'wrong', 'no-copy')


def state(changed=False):
    sources = ''.join(f'0|0|Harness77 журнал 044 {n}|2|1:10:10;2:20:40;|1|0||1#' for n in range(1, 4))
    children = ''
    for n in range(1, 5):
        posted = int(n in (1, 3))
        amount = 75 if changed and n == 3 else 50
        comment = COMMENT if changed and n == 3 else 'Harness77 подчиненный 044'
        children += f'{posted}|0|{comment}|{amount}|0|0|1|1|1|{posted}|'
        children += (f'50.1>62.1:0:{amount};' if posted else '') + '|1#'
    return '0|0|0|' + sources + children + 'sub:1;5;0;sf-count:0;' + ('sf:0|0|Harness77 подчиненный 044|1|1:50:50:50:0:0;|1|1|0#' * 2)


def case_scenario(name):
    scenario = (HERE / 'scenario.toml').read_text('utf-8')
    scenario = scenario.replace('"BASELINE"', json.dumps(state(), ensure_ascii=False))
    scenario = scenario.replace('kinds = "ПриходныйОрдер,СчетФактура",',
        'kinds = "ПриходныйОрдер,СчетФактура", edit = true, expected_after = ' + json.dumps(state(name != 'cancel'), ensure_ascii=False) + ',')
    start = scenario.index('\n]', scenario.index('steps = ['))
    tail = [
        '{ value = "Сумма", text = "50" }',
        '{ input = "Сумма", text = "75" }',
        '{ value = "Сумма", text = "75" }',
        '{ input = "Комментарий", text = ' + json.dumps(COMMENT, ensure_ascii=False) + ' }',
        '{ value = "Комментарий", text = ' + json.dumps(COMMENT, ensure_ascii=False) + ' }',
    ]
    if name == 'cancel':
        tail += ['{ close_form = true }',
                 '{ dialog = "Сохранить Документ? (Документ будет перепроведен)", button = "Нет", closes = true }']
    else:
        tail += ['{ click = "Записать" }', '{ click = "ОК", closes = true }']
    tail += ['{ reopen = true }',
             '{ check = "Комментарий", text = ' + json.dumps('Harness77 подчиненный 044' if name == 'cancel' else COMMENT, ensure_ascii=False) + ' }',
             '{ value = "Комментарий", text = ' + json.dumps('Harness77 подчиненный 044' if name == 'cancel' else COMMENT, ensure_ascii=False) + ' }',
             '{ value = "Сумма", text = "' + ('50' if name == 'cancel' else '75') + '" }']
    scenario = scenario[:start] + '\n' + ''.join('    ' + line + ',\n' for line in tail) + scenario[start:]
    final = state(name != 'cancel')
    if name == 'wrong':
        final = final.replace(':0:75;', ':0:999;')
    return scenario[:scenario.rindex('expect_value = ')] + 'expect_value = ' + json.dumps(final, ensure_ascii=False) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stand', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    text = a.stand.resolve(strict=True).read_text('utf-8')
    stand = tomllib.loads(text)['stand']
    if not stand['base'].get('copy_path'):
        p.error('stand requires its registered copy_path')
    paths = [stand.get('launcher'), *stand.get('paths', {}).values(), stand['base']['path'], stand['base']['copy_path']]
    if any(value and not Path(value).is_absolute() for value in paths):
        p.error('stand paths must be absolute')
    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in CASES:
        folder = output / name
        modules = folder / 'configuration'
        modules.mkdir(parents=True)
        header = '\n'.join(['schema_version = 1', '', '[project]', f'id = "journal-children-edit-{name}"', '', '[build]',
            'template = ' + json.dumps((ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT').as_posix()),
            'source = ' + json.dumps((ROOT / 'research/forms/probe_module77.1s').as_posix()), 'encoding = "utf-8"', '',
            *([] if name == 'no-copy' else ['[configuration]', 'modules = ' + json.dumps(modules.as_posix()), '']),
            '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120', 'cancel_timeout_s = 15',
            'shutdown_timeout_s = 30', 'total_timeout_s = 600', '', ''])
        content = header + case_scenario(name)
        tomllib.loads(content)
        (folder / 'project.toml').write_text(content, encoding='utf-8', newline='\n')
    text, count = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps((ROOT / 'research/forms/form_launcher77.py').as_posix()), text)
    if count != 1:
        p.error('stand must have one launcher line')
    (output / 'stand.toml').write_text(text, encoding='utf-8', newline='\n')
    for name, ids in {'suite': ['success', 'repeat', 'cancel'], 'suite-failure': ['wrong', 'after-failure']}.items():
        lines = ['schema_version = 1', '', '[suite]', f'id = "journal-children-edit-{name}"', '']
        for id_ in ids:
            case = 'success' if id_ in ('repeat', 'after-failure') else id_
            lines += ['[[scenarios]]', f'id = "{id_}"', f'project = "{case}/project.toml"', '']
        (output / (name + '.toml')).write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps(dict(output=str(output), stand=str(output / 'stand.toml')), ensure_ascii=False))


if __name__ == '__main__':
    main()
