"""Prepare task 038 profiles and suites; never starts 1C or mutates a base."""
import argparse
import json
from pathlib import Path
import re
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def state(posted=1, deleted=0):
    parts = []
    for n in range(1, 4):
        p, d = (posted, deleted) if n == 2 else (1, 0)
        entries = '43>40:1:10;43>40:2:40;' if p else ''
        parts.append(f'{p}|{d}|Harness77 журнал 038 {n}|2|1:10:10;2:20:40;|1|{2 if p else 0}|{entries}|1#')
    return '0|' + ''.join(parts)


def action(deleted, posted=0, cancel=False):
    return dict(journal_deletion=True, deleted=deleted, **({'cancel': True} if cancel else {}),
                expected=state(posted, int(not deleted) if cancel else int(deleted)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stand', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    stand_text = args.stand.resolve(strict=True).read_text(encoding='utf-8')
    stand = tomllib.loads(stand_text)['stand']
    if not stand['base'].get('copy_path'):
        parser.error('stand needs its registered copy_path')
    paths = [stand.get('launcher'), *stand.get('paths', {}).values(), stand['base']['path'], stand['base']['copy_path']]
    if any(v and not Path(v).is_absolute() for v in paths):
        parser.error('this example requires absolute paths in the stand')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scenario = (HERE / 'scenario.toml').read_text(encoding='utf-8')
    for name in ('success', 'unposted', 'wrong', 'wrong-limit', 'cancel-mark', 'cancel-unmark', 'no-copy'):
        modules = output / name / 'configuration'
        modules.mkdir(parents=True)
        content = scenario
        final = state(0, 0)
        steps = [action(True), action(False)]
        if name == 'unposted':
            content = content.replace('Если Док77.Провести(1) <> 1 Тогда Возврат "fixture posting failed"; КонецЕсли;',
                                      'Если Номер77 <> 2 Тогда\n        Если Док77.Провести(1) <> 1 Тогда Возврат "fixture posting failed"; КонецЕсли;\n    КонецЕсли;')
        if name == 'cancel-mark':
            steps, final = [action(True, posted=1, cancel=True)], state(1, 0)
        if name == 'cancel-unmark':
            steps, final = [action(True), action(False, cancel=True)], state(0, 1)
        if name == 'wrong-limit':
            content = content.replace('limit = 100', 'limit = 1')
            final = state(1, 0)
        start = content.index('    { journal_deletion =')
        end = content.index('\n]', start)
        content = content[:start] + '\n'.join('    { ' + ', '.join(
            f'{k} = {json.dumps(v, ensure_ascii=False)}' for k, v in s.items()) + ' },' for s in steps) + content[end:]
        content = content[:content.rindex('expect_value = ')] + 'expect_value = ' + json.dumps(
            state(1, 0) if name == 'wrong' else final, ensure_ascii=False) + '\n'
        header = '\n'.join(['schema_version = 1', '', '[project]', f'id = "journal-deletion-{name}"', '', '[build]',
            'template = ' + json.dumps((ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT').as_posix()),
            'source = ' + json.dumps((ROOT / 'research/forms/probe_module77.1s').as_posix()), 'encoding = "utf-8"', '',
            '[configuration]', 'modules = ' + json.dumps(modules.as_posix()), '', '[deadlines]',
            'open_timeout_s = 240', 'calculation_timeout_s = 120', 'cancel_timeout_s = 15',
            'shutdown_timeout_s = 30', 'total_timeout_s = 600', '', ''])
        if name == 'no-copy':
            header = header.replace('[configuration]\nmodules = ' + json.dumps(modules.as_posix()) + '\n\n', '')
        tomllib.loads(header + content)
        (output / name / 'project.toml').write_text(header + content, encoding='utf-8', newline='\n')
    stand_text, count = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps(
        (ROOT / 'research/forms/form_launcher77.py').as_posix()), stand_text)
    if count != 1:
        parser.error('stand must have one launcher line')
    (output / 'stand.toml').write_text(stand_text, encoding='utf-8', newline='\n')
    suites = [('suite', [('success', 'success'), ('repeat', 'success'), ('unposted', 'unposted'),
                          ('cancel-mark', 'cancel-mark'), ('cancel-unmark', 'cancel-unmark')]),
              ('suite-failure', [('wrong', 'wrong'), ('after-failure', 'success')]),
              ('suite-limit-failure', [('wrong-limit', 'wrong-limit'), ('after-failure', 'success')])]
    for name, cases in suites:
        lines = ['schema_version = 1', '', '[suite]', f'id = "journal-deletion-{name}"', '']
        for id_, project in cases:
            lines += ['[[scenarios]]', f'id = "{id_}"', f'project = "{project}/project.toml"', '']
        (output / (name + '.toml')).write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps(dict(output=str(output), suite=str(output / 'suite.toml')), ensure_ascii=False))


if __name__ == '__main__':
    main()
