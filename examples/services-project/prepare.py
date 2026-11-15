"""Create a task-104 project with explicit stand inputs and a pinned release wheel."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SHA = '24ba9a9b5ef2fc3957a417f56aaf19e683329b11c57c02ec7924766764a84aa2'
MODULE = 'Документ/ОказаниеУслуг/Форма.1s'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('base', 'copy-path', 'exe', 'cdb', 'helper', 'identity', 'template', 'controller', 'wheel', 'output'):
        p.add_argument('--' + key, type=Path, required=True)
    p.add_argument('--user', required=True)
    p.add_argument('--sha256', default=SHA, help='trusted SHA-256 of the selected wheel; defaults to published 0.10.0')
    p.add_argument('--installer-python', type=Path, default=Path(sys.executable),
                   help='Python with pip --python support, for local launcher prepare')
    p.add_argument('--copy-exclude', action='append', default=[])
    p.add_argument('--open-timeout-s', type=float, default=240)
    p.add_argument('--calculation-timeout-s', type=float, default=120)
    p.add_argument('--shutdown-timeout-s', type=float, default=30)
    p.add_argument('--total-timeout-s', type=float, default=600)
    a = p.parse_args()
    out = a.output.resolve()
    if out.exists():
        p.error('output must not exist')
    if hashlib.sha256(a.wheel.read_bytes()).hexdigest() != a.sha256:
        p.error('wheel does not match the explicit trusted SHA-256')
    def execute(args):
        r = subprocess.run([sys.executable, '-I', '-B', '-m', 'harness77', *map(str, args)], capture_output=True, timeout=600)
        if r.returncode:
            raise RuntimeError(r.stdout.decode('utf-8') + r.stderr.decode('utf-8'))
        return json.loads(r.stdout)
    scenario = {'parameters': {'form_object': 'Документ.ОказаниеУслуг', 'fixture_mode': 'existing',
        'fixture_setup_file': str(HERE / 'fixture.1s'), 'fixture_verify_file': str(HERE / 'reader.1s'),
        'steps_file': str(HERE / 'steps.json')}, 'tests': [
        {'name': 'form-open', 'command': 'open', 'expect': 'passed', 'expect_value': '1'},
        {'name': 'services-ui', 'command': 'result', 'expect': 'passed'},
        {'name': 'persisted-services', 'command': 'verify', 'expect': 'passed',
         'expect_json_file': str(HERE / 'expected.json')}]}
    with tempfile.NamedTemporaryFile(dir=out.parent, prefix='.services104-', suffix='.json',
                                    mode='w', encoding='utf-8', delete=False) as f:
        json.dump(scenario, f, ensure_ascii=False)
        scenario_path = Path(f.name)
    try:
        created = execute(['project-init', '--runtime', 'forms', '--directory', out, '--id', 'services104',
            '--template', a.template.resolve(), '--source', a.controller.resolve(), '--scenario', scenario_path,
            '--open-timeout-s', a.open_timeout_s, '--calculation-timeout-s', a.calculation_timeout_s, '--cancel-timeout-s', 15,
            '--shutdown-timeout-s', a.shutdown_timeout_s, '--total-timeout-s', a.total_timeout_s, '--format', 'json'])
    finally:
        scenario_path.unlink(missing_ok=True)
    extraction = out / '.input-extraction'
    execute(['md-extract', a.base.resolve() / '1Cv7.MD', '--output', extraction])
    target = out / 'configuration' / MODULE
    target.parent.mkdir(parents=True)
    shutil.copy2(extraction / MODULE, target)
    shutil.copy2(extraction / 'modules.json', out / 'configuration/modules.json')
    # The directory is exclusively created by md-extract below our new project.
    assert extraction.resolve().parent == out
    shutil.rmtree(extraction)
    (out / 'dependencies').mkdir()
    for key in ('helper', 'identity'):
        shutil.copy2(getattr(a, key), out / 'dependencies' / (key + '.dll'))
    stand_args = ['stand-init', '--output', out / 'stand.toml', '--name', 'services104', '--runtime', 'forms',
        '--exe', a.exe.resolve(), '--cdb', a.cdb.resolve(), '--base', a.base.resolve(), '--copy-path', a.copy_path.resolve(),
        '--helper', out / 'dependencies/helper.dll', '--identity', out / 'dependencies/identity.dll', '--user', a.user, '--format', 'json']
    for value in a.copy_exclude:
        stand_args += ['--copy-exclude', value]
    stand = execute(stand_args)
    (out / 'suite.toml').write_text('schema_version=1\n[suite]\nid="services104"\n\n[[scenarios]]\nid="baseline"\nproject="project.toml"\n', encoding='utf-8')
    for name in ('fixture.1s', 'reader.1s', 'steps.json', 'expected.json', 'run.py', 'verify.py', 'README.md'):
        shutil.copy2(HERE / name, out / name)
    # Reuse only transport and container-audit utilities, not application expectations.
    shutil.copy2(HERE.parent / 'application-suite/mcp_client.py', out / 'mcp_client.py')
    shutil.copy2(HERE.parent / 'invoice-project/verify.py', out / 'audit_utils.py')
    (out / 'AGENTS.md').write_text('Тест 104: fixture.1s, reader.1s, steps.json и expected.json неизменны при исправлении модуля.\n', encoding='utf-8')
    (out / '.gitignore').write_text('__pycache__/\n*.py[cod]\n.results/\n', encoding='utf-8')
    connected = execute(['connect', '--directory', out, '--project', out / 'project.toml', '--stand', out / 'stand.toml',
        '--suite', out / 'suite.toml', '--wheel', a.wheel.resolve(), '--bundle', '--format', 'json'])
    (out / 'initialization.json').write_text(json.dumps({'project': created, 'stand': stand, 'connect': connected},
        ensure_ascii=False, indent=2), encoding='utf-8')
    r = subprocess.run([str(a.installer_python.resolve()), '-I', '-B', str(out / '.harness77/launch.py'), 'prepare', '--format', 'json'], capture_output=True, timeout=600)
    (out / 'acquisition.json').write_bytes(r.stdout)
    (out / 'acquisition.stderr.log').write_bytes(r.stderr)
    if r.returncode:
        raise RuntimeError(r.stdout.decode('utf-8') + r.stderr.decode('utf-8'))
    print(r.stdout.decode('utf-8'))


if __name__ == '__main__':
    main()
