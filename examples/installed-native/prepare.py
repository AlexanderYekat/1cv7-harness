"""092: example inputs and external dependencies; native runtime comes only from the wheel."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def table(value):
    if isinstance(value, dict):
        return '{ ' + ', '.join(json.dumps(k) + ' = ' + table(v) for k, v in value.items()) + ' }'
    if isinstance(value, list):
        return '[' + ', '.join(map(table, value)) + ']'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def write(path, data):
    path.write_text('\n'.join(json.dumps(k) + ' = ' + table(v) for k, v in data.items()) + '\n', encoding='utf-8')


def prepare(args):
    from harness77.config77 import load_stand
    stand = load_stand(args.stand)
    settings = tomllib.loads(args.stand.read_text(encoding='utf-8'))
    settings['stand'].pop('launcher', None)
    settings['stand']['runtime'] = 'forms'
    if stand.backend != 'native' or stand.copy_path is None:
        raise ValueError('requires a native stand with a registered copy_path')
    settings['stand']['base'].update(path=stand.base.resolve().as_posix(), copy_path=stand.copy_path.resolve().as_posix())
    for role in ('exe', 'cdb'):
        settings['stand']['paths'][role] = getattr(stand, role).resolve(strict=True).as_posix()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)

    def copy(source, name):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    with zipfile.ZipFile(args.wheel) as wheel:
        assert 'harness77/_native/manifest.json' in wheel.namelist(), 'wheel has no installed native runtime'
    copy(args.wheel, args.wheel.name)
    copy(args.template, 'inputs/template.ert')
    copy(ROOT / 'research/forms/probe_module77.1s', 'inputs/module.1s')
    copy(ROOT / 'examples/full-cycle/module.1s', 'inputs/headless.1s')
    wait = (out / 'inputs/headless.1s').read_text(encoding='utf-8').replace('Возврат 6 * 7;', 'Пока 1 = 1 Цикл\n    КонецЦикла;\n    Возврат 42;')
    (out / 'inputs/wait.1s').write_text(wait, encoding='utf-8')
    for role in ('helper', 'identity'):
        copy(getattr(stand, role), 'dependencies/' + role + '.dll')
        settings['stand']['paths'][role] = 'dependencies/' + role + '.dll'
    write(out / 'stand.toml', settings)
    settings['stand']['runtime'] = 'headless'
    write(out / 'stand-headless.toml', settings)
    scenario = (ROOT / 'examples/document-form-cycle/scenario.toml').read_text(encoding='utf-8')
    for name in ('success', 'wrong'):
        folder = out / name
        (folder / 'configuration').mkdir(parents=True)
        header = ('schema_version=1\n[project]\nid="installed-' + name + '"\n[build]\n'
                  'template="../inputs/template.ert"\nsource="../inputs/module.1s"\nencoding="utf-8"\n'
                  '[configuration]\nmodules="configuration"\n[deadlines]\nopen_timeout_s=240\n'
                  'calculation_timeout_s=120\ncancel_timeout_s=15\nshutdown_timeout_s=30\ntotal_timeout_s=600\n')
        body = scenario
        if name == 'wrong':
            assert body.count('|2|3:10:30;2:20:40;|') == 1
            body = body.replace('|2|3:10:30;2:20:40;|', '|2|999:10:30;2:20:40;|')
        (folder / 'project.toml').write_text(header + body, encoding='utf-8')
    for name, cases in (('suite', [('success', 'success'), ('repeat', 'success')]),
                        ('suite-failure', [('wrong', 'wrong'), ('after-failure', 'success')])):
        write(out / (name + '.toml'), {'schema_version': 1, 'suite': {'id': 'installed-document'},
                                     'scenarios': [{'id': case, 'project': project + '/project.toml'} for case, project in cases]})
    for name, source in (('headless', 'headless.1s'), ('cancel', 'wait.1s')):
        folder = out / name
        (folder / 'configuration').mkdir(parents=True)
        write(folder / 'project.toml', {'schema_version': 1, 'project': {'id': name},
            'build': {'template': '../inputs/template.ert', 'source': '../inputs/' + source, 'encoding': 'utf-8'},
            'configuration': {'modules': 'configuration'},
            'platform': {'tests': [{'name': 'answer', 'command': 'execute', 'expect': 'passed', 'expect_value': '42'}]},
            'deadlines': {'open_timeout_s': 120, 'calculation_timeout_s': 120, 'cancel_timeout_s': 15,
                          'shutdown_timeout_s': 30, 'total_timeout_s': 300}})
    copy(Path(__file__).with_name('run.py'), 'run.py')
    copy(Path(__file__).with_name('README.md'), 'README.md')
    for name in ('verify_document_form77.py', 'verify_suite77.py'):
        copy(ROOT / 'scripts' / name, 'verification/' + name)
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'kit.json').write_text(json.dumps({'schema_version': 1, 'wheel': args.wheel.name, 'files': files}, indent=2) + '\n', encoding='utf-8')
    print(out / 'kit.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stand', 'template', 'wheel', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    prepare(parser.parse_args())
