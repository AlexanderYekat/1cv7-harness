"""Generate task 031 profiles and suites on the pinned stand, without starting 1C."""
import argparse
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / 'examples/document-posting'
INITIAL = '1|2|1|43>40:3:30;43>40:2:40;'
CHANGED = '1|2|1|43>40:5:50;43>40:2:40;'
EMPTY = '0|0|1|'
CHANGE = '''Док77Проведения.ПолучитьСтрокуПоНомеру(1);
Док77Проведения.Количество = 5;
Док77Проведения.Сумма = 50;
Док77Проведения.Записать();'''
OPERATIONS = [('initial', 'post', '', INITIAL), ('repeat', 'post', '', INITIAL),
              ('changed', 'post', CHANGE, CHANGED), ('cancel', 'unpost', '', EMPTY),
              ('restored', 'post', '', CHANGED)]


def profile(name):
    parameters = (OLD / 'scenario.toml').read_text(encoding='utf-8').split('[[platform.tests]]')[0]
    parameters = parameters.replace('fixture_post = true\n', '')
    operations = []
    expected = []
    for id_, action, before, value in OPERATIONS:
        if name == 'error' and id_ == 'repeat':
            before = 'Делитель77 = 0; Х77 = 1 / Делитель77;'
        operations.append('{ id = ' + json.dumps(id_) + ', action = ' + json.dumps(action)
                          + (", before = '''" + before + "'''" if before else '') + ' }')
        expected += [(action + '-' + id_, 'failed' if name == 'error' and id_ == 'repeat' else 'passed',
                      None if name == 'error' and id_ == 'repeat' else ('1|0' if action == 'unpost' else '1|1')),
                     ('verify-' + id_, 'passed', value.replace(':5:50;', ':999:50;')
                      if name == 'wrong' and id_ == 'changed' else value)]
    parameters = parameters.replace('steps = [', 'fixture_operations = [\n' + ',\n'.join(operations) + '\n]\nsteps = [')
    tests = [('open', 'passed', '1'), ('result', 'passed', None)] + expected + [('verify', 'passed', CHANGED)]
    for command, status, value in tests:
        parameters += '\n[[platform.tests]]\nname = ' + json.dumps(command) + '\ncommand = ' + json.dumps(command)
        parameters += '\nexpect = ' + json.dumps(status) + '\n'
        if value is not None:
            parameters += 'expect_value = ' + json.dumps(value) + '\n'
    return parameters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stand', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    text = args.stand.resolve(strict=True).read_text(encoding='utf-8')
    stand = tomllib.loads(text)['stand']
    paths = [stand['base']['path'], stand['base'].get('copy_path'), stand.get('launcher'),
             *stand.get('paths', {}).values()]
    if any(not p or not Path(p).is_absolute() for p in paths):
        parser.error('requires absolute stand paths and registered copy_path')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in ('lifecycle', 'wrong', 'error'):
        folder = output / name
        modules = folder / 'configuration'
        modules.mkdir(parents=True)
        header = '\n'.join(['schema_version = 1', '', '[project]', f'id = "lifecycle-{name}"', '', '[build]',
                            'template = ' + json.dumps((ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT').as_posix()),
                            'source = ' + json.dumps((ROOT / 'research/forms/probe_module77.1s').as_posix()),
                            'encoding = "utf-8"', '', '[configuration]', 'modules = ' + json.dumps(modules.as_posix()),
                            '', '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120',
                            'cancel_timeout_s = 15', 'shutdown_timeout_s = 30', 'total_timeout_s = 600', '', ''])
        content = header + profile(name)
        tomllib.loads(content)
        (folder / 'project.toml').write_text(content, encoding='utf-8', newline='\n')
    text, count = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps(
        (ROOT / 'research/forms/form_launcher77.py').as_posix()), text)
    if count != 1:
        parser.error('stand must have one launcher')
    (output / 'stand.toml').write_text(text, encoding='utf-8', newline='\n')
    for name, cases in [('suite', [('lifecycle', 'lifecycle'), ('error', 'error'), ('repeat', 'lifecycle')]),
                        ('suite-failure', [('wrong', 'wrong'), ('after-failure', 'lifecycle')])]:
        manifest = ['schema_version = 1', '', '[suite]', f'id = "document-lifecycle-{name}"', '']
        for id_, project in cases:
            manifest += ['[[scenarios]]', f'id = "{id_}"', f'project = "{project}/project.toml"', '']
        (output / (name + '.toml')).write_text('\n'.join(manifest), encoding='utf-8', newline='\n')
    print(json.dumps({'output': str(output), 'stand': str(output / 'stand.toml')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
