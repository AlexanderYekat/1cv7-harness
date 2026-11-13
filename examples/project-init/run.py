"""094: stand-init → project-init → doctor → real 42 and wrong expectation."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LIMITS = {'open-timeout-s': 120, 'calculation-timeout-s': 60, 'cancel-timeout-s': 15,
          'shutdown-timeout-s': 30, 'total-timeout-s': 300}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def registry_tree(root):
    import winreg
    def content(key):
        subkeys, values, _ = winreg.QueryInfoKey(key)
        data = {'values': sorted([list(winreg.EnumValue(key, i)) for i in range(values)]), 'children': {}}
        for i in range(subkeys):
            name = winreg.EnumKey(key, i)
            with winreg.OpenKey(key, name, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as child:
                data['children'][name] = content(child)
        return data
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            return content(key)
    except FileNotFoundError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt' or sys.prefix == sys.base_prefix or os.environ.get('PYTHONPATH') or os.environ.get('PYTHONHOME'):
        parser.error('requires clean installed Windows venv')
    import harness77
    from harness77 import basecopy77, native_runtime77 as runtime
    from harness77.config77 import load_project
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    assert Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    assert sorted(d.metadata['Name'] for d in metadata.distributions()) == ['harness77']
    manifest, inputs = read(HERE / 'kit.json'), read(HERE / 'inputs.json')
    assert all(digest(HERE / n) == sha for n, sha in manifest['files'].items())
    assert not list(HERE.rglob('project.toml')) and not list(HERE.rglob('module.1s')) and not (HERE / 'native').exists()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    projects, controls, working = out / 'projects', out / 'controls', out / 'working'
    for folder in (projects, controls, working):
        folder.mkdir()
    info = runtime.inspect_runtime('headless')
    base, copy = Path(inputs['base']), Path(inputs['copy_path'])
    lock = basecopy77.lock_path(copy)
    guard = lock.with_name(lock.name + '.guard')
    guard_before = guard.read_bytes() if guard.exists() else None
    inspector = WindowsInspector()

    def snapshot():
        return {'source': basecopy77.listing(base),
                'hashes': {n: digest(base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                'registry': {key: registry_tree(key) for key in (TITLES, *COM_KEYS)}, 'processes': inspector.processes(),
                'copy': copy.exists(), 'lock': lock.exists(), 'guard': digest(guard) if guard.exists() else None,
                'kit': {n: digest(HERE / n) for n in manifest['files']}, 'runtime': runtime.inspect_runtime('headless')}

    before = snapshot()
    evidence = {'status': 'running', 'environment': {'python': sys.executable, 'module': harness77.__file__, 'cwd': str(working)},
                'runtime': info, 'kit_sha256': digest(HERE / 'kit.json'), 'project_init': [], 'doctors': [], 'runs': []}
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')

    def save():
        (out / 'verified.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def execute(name, command, expected):
        result = subprocess.run([sys.executable, '-B', '-m', 'harness77', *map(str, command)],
                                cwd=working, env=env, capture_output=True, timeout=900)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
        assert result.returncode == expected, (name, result.returncode)
        return result

    def create(name, directory, *, template=HERE / 'inputs/template.ert', changes=None, expected=0, format_='json'):
        values = {'id': name, 'template': template, **LIMITS}
        values.update(changes or {})
        command = ['project-init', '--directory', directory, '--format', format_]
        for key, value in values.items():
            command += ['--' + key, value]
        existing = {p.relative_to(directory).as_posix(): digest(p) for p in directory.rglob('*') if p.is_file()} if directory.exists() else None
        response = execute(name, command, expected)
        result = json.loads(response.stdout) if format_ == 'json' else {'status': 'created'}
        assert result['status'] == ('created' if expected == 0 else 'blocked')
        if format_ == 'json':
            assert not result['platform_checked'] and not result['launch_performed']
        if expected == 0:
            project = load_project(directory / 'project.toml')
            assert project.template == directory / 'template.ert' and project.source == directory / 'module.1s'
            assert project.configuration == directory / 'configuration' and list(project.configuration.iterdir()) == []
            assert project.tests[0]['expect_value'] == '42' and project.commands() == ['execute']
            assert project.deadlines_raw == {key.replace('-', '_'): value for key, value in LIMITS.items()}
            assert digest(project.template) == digest(HERE / 'inputs/template.ert')
        elif existing is not None:
            assert {p.relative_to(directory).as_posix(): digest(p) for p in directory.rglob('*') if p.is_file()} == existing
        else:
            assert not directory.exists()
        assert not list(projects.glob('.harness77-project-*'))
        assert snapshot() == before
        evidence['project_init'].append(dict(result, case=name, log_sha256=digest(out / (name + '.log'))))
        save()

    def native(name, project_path, expected):
        root = out / name
        execute(name, ['run', '--project', project_path, '--stand', out / 'stand.toml', '--output-root', root], expected)
        reports = list(root.glob('*/run.json'))
        assert len(reports) == 1
        folder = reports[0].parent
        report, platform = read(reports[0]), read(folder / 'platform-result.json')
        assert report['status'] == ('passed' if expected == 0 else 'failed') and report['platform_checked']
        assert platform['run_id'] == report['run_id'] == folder.name and platform['status'] == 'passed'
        assert next(o for o in platform['operations'] if o['name'] == 'execute')['value'] == '42'
        tests = next(s for s in report['stages'] if s['stage'] == 'tests')['tests']
        assert len(tests) == 1 and tests[0]['expectation_met'] is (expected == 0)
        stage = next(s for s in report['stages'] if s['stage'] == 'platform_check')
        copied, shutdown = stage['base_copy'], report['shutdown']
        assert copied['source_check']['unchanged'] and copied['removal']['removed'] and copied['lock']['released']
        assert shutdown['cleanup_verified'] and shutdown['others_preserved'] and not shutdown['forced_cleanup']
        assert stage['base_list']['unchanged']
        trace = read(folder / 'native/startup.json')
        assert trace == platform['open']['startup'] == stage['open']['startup'] and trace['status'] == 'ready'
        assert [e['stage'] for e in trace['events']].count('initialize_finished') == 1
        for state in ('started', 'finished'):
            raw = (folder / 'native' / ('ert-initialize-' + state)).read_bytes()
            assert raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'cp1251').strip() == report['run_id']
        client = folder / 'native/client.vbs'
        assert client.read_text(encoding='utf-16').count('result = v.Initialize(') == 1
        assert read(folder / 'native/shutdown-manifest.json')['sources']['client.vbs'] == digest(client)
        provenance = read(folder / 'launcher-environment.json')
        assert provenance['module'] == harness77.__file__ and provenance['prefix'] == sys.prefix and provenance['runtime'] == info
        evidence['runs'].append({'case': name, 'run_id': report['run_id'], 'status': report['status'], 'value': '42',
                                  'run_sha256': digest(reports[0]), 'startup': trace, 'environment': provenance})
        if guard_before is None and not inspector.processes() and not copy.exists() and not lock.exists():
            guard.unlink(missing_ok=True)
        assert snapshot() == before
        save()

    try:
        assert not before['processes'] and not before['copy'] and not before['lock']
        stand = ['stand-init', '--output', out / 'stand.toml', '--name', 'minimal94', '--runtime', 'headless', '--format', 'json',
                 '--exe', inputs['exe'], '--cdb', inputs['cdb'], '--helper', HERE / 'dependencies/helper.dll',
                 '--identity', HERE / 'dependencies/identity.dll', '--base', base, '--copy-path', copy, '--user', inputs['user']]
        for value in inputs['copy_exclude']:
            stand += ['--copy-exclude', value]
        created = json.loads(execute('stand-init', stand, 0).stdout)
        assert created['status'] == 'created' and not created['launch_performed'] and snapshot() == before
        evidence['stand_init'] = created
        good, wrong = projects / 'минимальный проект', projects / 'wrong'
        create('minimal94', good)
        create('wrong94', wrong, format_='text')
        create('existing', good, expected=2)
        empty = controls / 'empty'
        empty.mkdir()
        create('existing-empty', empty, expected=2)
        broken = controls / 'broken.ert'
        broken.write_bytes(b'not an ERT')
        create('bad-template', projects / 'bad-template', template=broken, expected=2)
        create('bad-deadlines', projects / 'bad-deadlines', changes={'total-timeout-s': 1}, expected=2)
        create('bad-id', projects / 'bad-id', changes={'id': '../escape'}, expected=2)
        create('missing-parent', out / 'absent-parent/project', expected=2)
        create('missing-template', projects / 'missing-template', template=controls / 'missing.ert', expected=2)
        wrong_file = wrong / 'project.toml'
        text = wrong_file.read_text(encoding='utf-8')
        assert text.count('expect_value = "42"') == 1
        wrong_file.write_text(text.replace('expect_value = "42"', 'expect_value = "999"'), encoding='utf-8', newline='\n')
        for name, directory in [('good', good), ('wrong', wrong)]:
            future = out / ('doctor-' + name + '-uncreated')
            result = json.loads(execute('doctor-' + name, ['doctor', '--project', directory / 'project.toml',
                                '--stand', out / 'stand.toml', '--output-root', future, '--format', 'json'], 0).stdout)
            assert result['status'] == 'ready' and not result['launch_performed'] and not future.exists()
            assert snapshot() == before
            evidence['doctors'].append(result)
        native('success', good / 'project.toml', 0)
        native('wrong', wrong_file, 1)
        native('after-failure', good / 'project.toml', 0)
        evidence['status'] = 'passed'
    except Exception as error:
        evidence.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        after = snapshot()
        evidence['unchanged'] = {key: value == after[key] for key, value in before.items()}
        if not all(evidence['unchanged'].values()):
            evidence['status'] = 'failed'
        save()
    print(out / 'verified.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
