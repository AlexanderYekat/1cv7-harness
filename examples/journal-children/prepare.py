"""Generate task 041 profiles and suites without starting 1C."""
import argparse
import json
from pathlib import Path
import re
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def state():
    sources = ''.join(f'0|0|Harness77 журнал 041 {n}|2|1:10:10;2:20:40;|1|0||1#' for n in range(1, 4))
    children = ''.join(f'{int(n == 1)}|0|Harness77 подчиненный 041 {n}|50|0|0|1|1|1|{int(n == 1)}|'
                       + ('50.1>62.1:0:50;' if n == 1 else '') + '|1#' for n in range(1, 3))
    return '0|0|0|' + sources + children + 'sub:1;1;0;'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stand', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    text = args.stand.resolve(strict=True).read_text('utf-8')
    stand = tomllib.loads(text)['stand']
    if not stand['base'].get('copy_path'):
        parser.error('stand requires its registered copy_path')
    paths = [stand.get('launcher'), *stand.get('paths', {}).values(), stand['base']['path'], stand['base']['copy_path']]
    if any(value and not Path(value).is_absolute() for value in paths):
        parser.error('stand paths must be absolute')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scenario = (HERE / 'scenario.toml').read_text('utf-8').replace('"BASELINE"', json.dumps(state(), ensure_ascii=False))
    cases = ('success', 'other', 'empty', 'cancel', 'wrong', 'wrong-reference', 'wrong-limit', 'no-copy')
    for name in cases:
        folder = output / name
        modules = folder / 'configuration'
        modules.mkdir(parents=True)
        content = scenario
        if name == 'other':
            content = content.replace('Возврат Объект77Подготовки.ПолучитьЗначение(2);', 'Возврат Объект77Подготовки.ПолучитьЗначение(1);')
            content = content.replace('reference = 16', 'reference = 15').replace('caption_text = "Не требуется"', 'caption_text = "Счет-факутра ещё не сформирована"')
        if name == 'empty':
            content = content.replace('Возврат Объект77Подготовки.ПолучитьЗначение(2);', 'Возврат Объект77Подготовки.ПолучитьЗначение(3);')
            content = content.replace('reference = 16', 'reference = 16, empty = true')
        if name == 'cancel':
            content = content.replace('reference = 16', 'reference = 16, cancel = true')
        if name == 'wrong-reference':
            content = content.replace('reference = 16', 'reference = 15')
        if name == 'wrong-limit':
            content = content.replace('limit = 100', 'limit = 1')
        final = state() if name != 'wrong' else state().replace(':0:50', ':0:999')
        content = content[:content.rindex('expect_value = ')] + 'expect_value = ' + json.dumps(final, ensure_ascii=False) + '\n'
        header = '\n'.join(['schema_version = 1', '', '[project]', f'id = "journal-children-{name}"', '', '[build]',
            'template = ' + json.dumps((ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT').as_posix()),
            'source = ' + json.dumps((ROOT / 'research/forms/probe_module77.1s').as_posix()), 'encoding = "utf-8"', '',
            *([] if name == 'no-copy' else ['[configuration]', 'modules = ' + json.dumps(modules.as_posix()), '']),
            '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120', 'cancel_timeout_s = 15',
            'shutdown_timeout_s = 30', 'total_timeout_s = 600', '', ''])
        tomllib.loads(header + content)
        (folder / 'project.toml').write_text(header + content, encoding='utf-8', newline='\n')
    text, count = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps((ROOT / 'research/forms/form_launcher77.py').as_posix()), text)
    if count != 1:
        parser.error('stand must have one launcher line')
    (output / 'stand.toml').write_text(text, encoding='utf-8', newline='\n')
    suites = {'suite': ['success', 'repeat', 'other', 'empty', 'cancel'],
              'suite-failure': ['wrong', 'after-failure'], 'suite-reference': ['wrong-reference', 'after-failure'],
              'suite-limit': ['wrong-limit', 'after-failure']}
    for name, ids in suites.items():
        lines = ['schema_version = 1', '', '[suite]', f'id = "journal-children-{name}"', '']
        for id_ in ids:
            case = 'success' if id_ in ('repeat', 'after-failure') else id_
            lines += ['[[scenarios]]', f'id = "{id_}"', f'project = "{case}/project.toml"', '']
        (output / (name + '.toml')).write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps(dict(output=str(output), stand=str(output / 'stand.toml')), ensure_ascii=False))


if __name__ == '__main__':
    main()
