"""Prepare task 033 UI document profiles and suites; does not start 1C."""
import argparse
import json
from pathlib import Path
import re
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATE = ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT'
SOURCE = ROOT / 'research/forms/probe_module77.1s'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stand', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new directory')
    args = parser.parse_args()
    text = args.stand.resolve(strict=True).read_text(encoding='utf-8')
    stand = tomllib.loads(text)['stand']
    if not stand['base'].get('copy_path'):
        parser.error('stand needs its registered copy_path')
    paths = [stand.get('launcher'), *stand.get('paths', {}).values(), stand['base']['path'], stand['base']['copy_path']]
    if any(value and not Path(value).is_absolute() for value in paths):
        parser.error('this example requires absolute paths in the stand')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scenario = (HERE / 'scenario.toml').read_text(encoding='utf-8')
    for name in ('success', 'wrong', 'wrong-reopen', 'no-copy'):
        folder = output / name
        modules = folder / 'configuration'
        modules.mkdir(parents=True)
        content = scenario
        if name == 'wrong':
            content = content.replace('|2|3:10:30;2:20:40;|', '|2|999:10:30;2:20:40;|')
        if name == 'wrong-reopen':
            content = content.replace('{ check = "Комментарий", text = "Harness77 форма 033" }',
                                      '{ check = "Комментарий", text = "Harness77 неверно 033" }')
        header = '\n'.join(['schema_version = 1', '', '[project]', f'id = "form-cycle-{name}"', '', '[build]',
                            f'template = {json.dumps(TEMPLATE.as_posix())}', f'source = {json.dumps(SOURCE.as_posix())}',
                            'encoding = "utf-8"', '', '[configuration]', f'modules = {json.dumps(modules.as_posix())}',
                            '', '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120',
                            'cancel_timeout_s = 15', 'shutdown_timeout_s = 30', 'total_timeout_s = 600', '', ''])
        if name == 'no-copy':
            header = header.replace('[configuration]\n' + f'modules = {json.dumps(modules.as_posix())}\n\n', '')
        tomllib.loads(header + content)
        (folder / 'project.toml').write_text(header + content, encoding='utf-8', newline='\n')
    text, count = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps(
        (ROOT / 'research/forms/form_launcher77.py').as_posix()), text)
    if count != 1:
        parser.error('stand must have one launcher line')
    (output / 'stand.toml').write_text(text, encoding='utf-8', newline='\n')
    for name, cases in [('suite', [('success', 'success'), ('repeat', 'success')]),
                        ('suite-failure', [('wrong', 'wrong'), ('after-failure', 'success')]),
                        ('suite-reopen-failure', [('wrong-reopen', 'wrong-reopen'), ('after-failure', 'success')])]:
        manifest = ['schema_version = 1', '', '[suite]', f'id = "document-form-{name}"', '']
        for id_, project in cases:
            manifest += ['[[scenarios]]', f'id = "{id_}"', f'project = "{project}/project.toml"', '']
        (output / (name + '.toml')).write_text('\n'.join(manifest), encoding='utf-8', newline='\n')
    print(json.dumps({'output': str(output), 'stand': str(output / 'stand.toml'),
                      'suite': str(output / 'suite.toml')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
