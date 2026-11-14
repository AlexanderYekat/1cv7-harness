"""Create task 100, or direct task 101 from a wheel or a pinned release URL."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
URL = 'https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.7.0/harness77-0.7.0-py3-none-any.whl'
SHA = '7f0f81e8ead500ba97920bbb37c316d4680ecc6e0b064bd97fa4ad405ab57d6f'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('installed-python', 'base', 'copy-path', 'exe', 'cdb', 'helper', 'identity', 'template', 'controller', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--user', required=True)
    p.add_argument('--copy-exclude', action='append', default=[])
    p.add_argument('--direct', action='store_true', help='101: direct document open/reopen with an explicit print caption')
    p.add_argument('--file-fixtures', action='store_true', help='102: copy fixture/reader and reference their files')
    p.add_argument('--json-files', action='store_true', help='103: read steps and expected JSON files on every run')
    p.add_argument('--wheel', type=Path, help='101: newly built wheel, bundled in the standalone project')
    p.add_argument('--url', help='101: published wheel URL, without a local wheel or bundle')
    p.add_argument('--version', help='101: pinned version for --url')
    p.add_argument('--sha256', help='101: trusted SHA-256 for --url')
    a = p.parse_args()
    out = a.output.resolve()
    assert not out.exists(), out
    remote = (a.url, a.version, a.sha256)
    if any(remote) and not all(remote):
        p.error('--url, --version and --sha256 are required together')
    if a.wheel and any(remote):
        p.error('choose --wheel or the pinned --url source')
    if a.direct and not (a.wheel or all(remote)):
        p.error('--direct requires --wheel or --url/--version/--sha256')
    if not a.direct and (a.wheel or any(remote)):
        p.error('explicit package options require --direct; the default task 100 pins its published 0.7.0')
    if a.file_fixtures and not a.direct:
        p.error('--file-fixtures requires --direct')
    if a.json_files and not (a.direct and a.file_fixtures):
        p.error('--json-files requires --direct --file-fixtures')
    expected = json.loads((HERE / 'expected.json').read_text(encoding='utf-8'))
    initial = json.loads(json.dumps(expected))
    initial['amount'] = initial['total'] = '80'
    initial['rows'][1].update(quantity='1', amount='30', total='30')
    prefix = 'direct-' if a.direct else ''
    steps = json.loads((HERE / (prefix + 'steps.json')).read_text(encoding='utf-8'))
    if not a.direct:
        child = next(s for s in steps if 'journal_children' in s)
        child['expected'] = json.dumps(initial, ensure_ascii=False, separators=(',', ':'))
        child['expected_after'] = json.dumps(expected, ensure_ascii=False, separators=(',', ':'))
    scenario = {'parameters': {'form_object': 'Документ.СчетФактура',
        'fixture_setup': (HERE / (prefix + 'fixture.1s')).read_text(encoding='utf-8'),
        'fixture_verify': (HERE / (prefix + 'reader.1s')).read_text(encoding='utf-8'),
        'steps': steps},
        'tests': [{'name': 'form-open', 'command': 'open', 'expect': 'passed', 'expect_value': '1'},
                  {'name': 'invoice-ui', 'command': 'result', 'expect': 'passed'},
                  {'name': 'persisted-invoice', 'command': 'verify', 'expect': 'passed',
                   'expect_json': (HERE / 'expected.json').read_text(encoding='utf-8'),
                   'json_labels': {'/rows/1/amount': 'Строка 2, сумма', '/rows/1/total': 'Строка 2, всего',
                                   '/amount': 'Документ, сумма', '/total': 'Документ, всего'}}]}
    if a.direct:
        scenario['parameters'].update(fixture_mode='existing', caption_control='кнПечать', caption_text='Печать')
    else:
        scenario['parameters'].update(fixture_mode='journal_existing', journal_form='Журнал.Товары.ФормаСписка.ФормаСписка')
    if a.file_fixtures:
        for role, name in [('fixture_setup', 'fixture.1s'), ('fixture_verify', 'reader.1s')]:
            scenario['parameters'].pop(role)
            scenario['parameters'][role + '_file'] = str((HERE / ('direct-' + name)).resolve())
    if a.json_files:
        scenario['parameters'].pop('steps')
        scenario['parameters']['steps_file'] = str((HERE / 'direct-steps.json').resolve())
        scenario['tests'][-1].pop('expect_json')
        scenario['tests'][-1]['expect_json_file'] = str((HERE / 'expected.json').resolve())
    task = '103' if a.json_files else '102' if a.file_fixtures else '101' if a.direct else '100'
    # Reserve an exclusive temporary input; never replace an adjacent user's file.
    with tempfile.NamedTemporaryFile(dir=out.parent, prefix='.invoice100-', suffix='.json',
                                     mode='w', encoding='utf-8', delete=False) as temporary:
        temporary.write(json.dumps(scenario, ensure_ascii=False, indent=2) + '\n')
        scenario_path = Path(temporary.name)
    def execute(args):
        r = subprocess.run([str(a.installed_python.resolve()), '-I', '-B', '-m', 'harness77', *map(str, args)],
                           capture_output=True, timeout=300)
        if r.returncode:
            raise RuntimeError(r.stdout.decode('utf-8') + r.stderr.decode('utf-8'))
        return json.loads(r.stdout)
    try:
        created = execute(['project-init', '--runtime', 'forms', '--directory', out, '--id', 'invoice' + task,
            '--template', a.template.resolve(), '--source', a.controller.resolve(), '--scenario', scenario_path,
            '--open-timeout-s', 240, '--calculation-timeout-s', 120, '--cancel-timeout-s', 15,
            '--shutdown-timeout-s', 30, '--total-timeout-s', 600, '--format', 'json'])
    finally:
        scenario_path.unlink(missing_ok=True)
    extraction = out / '.input-extraction'
    execute(['md-extract', a.base.resolve() / '1Cv7.MD', '--output', extraction])
    module_name = 'Документ/СчетФактура/Форма.1s'
    target = out / 'configuration' / module_name
    target.parent.mkdir(parents=True)
    shutil.copy2(extraction / module_name, target)
    shutil.copy2(extraction / 'modules.json', out / 'configuration/modules.json')
    assert extraction.resolve().parent == out
    shutil.rmtree(extraction)
    dependencies = out / 'dependencies'
    dependencies.mkdir()
    for name in ('helper', 'identity'):
        shutil.copy2(getattr(a, name), dependencies / (name + '.dll'))
    stand_args = ['stand-init', '--output', out / 'stand.toml', '--name', 'invoice' + task, '--runtime', 'forms',
        '--exe', a.exe.resolve(), '--cdb', a.cdb.resolve(), '--base', a.base.resolve(), '--copy-path', a.copy_path.resolve(),
        '--helper', dependencies / 'helper.dll', '--identity', dependencies / 'identity.dll', '--user', a.user, '--format', 'json']
    for name in a.copy_exclude:
        stand_args += ['--copy-exclude', name]
    stand = execute(stand_args)
    (out / 'suite.toml').write_text('schema_version=1\n[suite]\nid="invoice' + task + '"\n\n[[scenarios]]\nid="baseline"\nproject="project.toml"\n', encoding='utf-8')
    for name in ('fixture.1s', 'reader.1s', 'steps.json', 'expected.json', 'run.py', 'verify.py', 'README.md'):
        shutil.copy2(HERE / name, out / name)
    if a.file_fixtures:
        shutil.copy2(HERE / 'file_checks.py', out / 'file_checks.py')
    if a.json_files:
        shutil.copy2(HERE / 'json_checks.py', out / 'json_checks.py')
    if a.direct:
        for name in ('fixture.1s', 'reader.1s', 'steps.json'):
            shutil.copy2(HERE / ('direct-' + name), out / name)
    (out / '.gitignore').write_text('__pycache__/\n*.py[cod]\n.results/\n', encoding='utf-8')
    # Transport helper only; neither runtime nor old application inputs are copied.
    shutil.copy2(HERE.parent / 'application-suite/mcp_client.py', out / 'mcp_client.py')
    (out / 'AGENTS.md').write_text('Проект счёта-фактуры ' + task + '. Тесты fixture.1s, reader.1s, steps.json и expected.json не менять при исправлении модуля формы.\n', encoding='utf-8')
    if a.direct:
        package = (['--wheel', a.wheel.resolve(), '--bundle'] if a.wheel else
                   ['--version', a.version, '--url', a.url, '--sha256', a.sha256])
    else:
        package = ['--version', '0.7.0', '--url', URL, '--sha256', SHA]
    connected = execute(['connect', '--directory', out, '--project', out / 'project.toml', '--stand', out / 'stand.toml',
        '--suite', out / 'suite.toml', *package, '--format', 'json'])
    (out / 'initialization.json').write_text(json.dumps({'project': created, 'stand': stand, 'connect': connected},
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    r = subprocess.run([sys.executable, '-I', '-B', str(out / '.harness77/launch.py'), 'prepare', '--format', 'json'],
                       capture_output=True, timeout=600)
    (out / 'acquisition.json').write_bytes(r.stdout)
    (out / 'acquisition.stderr.log').write_bytes(r.stderr)
    assert r.returncode == 0, r.stderr.decode('utf-8')
    print(r.stdout.decode('utf-8'))


if __name__ == '__main__':
    main()
