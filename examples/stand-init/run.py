"""093: generate profiles, reject invalid inputs, doctor and run without checkout."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


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
    from harness77.config77 import load_stand
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    assert Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    assert sorted(d.metadata['Name'] for d in metadata.distributions()) == ['harness77']
    manifest, inputs = read(HERE / 'kit.json'), read(HERE / 'inputs.json')
    assert all(digest(HERE / n) == h for n, h in manifest['files'].items())
    assert not list(HERE.glob('stand*.toml')) and not (HERE / 'native').exists()
    info = runtime.inspect_runtime('headless')
    sys.path[:0] = [str(HERE / 'verification'), str(runtime.HERE / '_native/forms')]
    from verify_document_form77 import check, excluded, read as marker
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    profiles, controls, working = out / 'profiles', out / 'controls', out / 'working'
    for directory in (profiles, controls, working):
        directory.mkdir()
    base, target = Path(inputs['base']), Path(inputs['copy_path'])
    lock = basecopy77.lock_path(target)
    guard = lock.with_name(lock.name + '.guard')
    guard_before = guard.read_bytes() if guard.exists() else None
    inspector = WindowsInspector()

    def snapshot():
        return {'source': basecopy77.listing(base),
                'hashes': {n: digest(base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                'registry': {key: registry_tree(key) for key in (TITLES, *COM_KEYS)}, 'processes': inspector.processes(),
                'copy': target.exists(), 'lock': lock.exists(), 'guard': digest(guard) if guard.exists() else None,
                'kit': {n: digest(HERE / n) for n in manifest['files']}, 'runtime': runtime.inspect_runtime('headless')}

    before = snapshot()
    evidence = {'status': 'running', 'environment': {'python': sys.executable, 'module': harness77.__file__, 'cwd': str(working)},
                'kit_sha256': digest(HERE / 'kit.json'), 'runtime': info, 'init': [], 'doctors': [], 'runs': []}
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')

    def execute(name, command, expected):
        result = subprocess.run([sys.executable, '-B', '-m', 'harness77', *map(str, command)],
                                cwd=working, env=env, capture_output=True, timeout=900)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
        assert result.returncode == expected, (name, result.returncode)
        return result

    def create(name, adapter='headless', *, changes=None, output=None, expected=0, format_='json'):
        destination = output or profiles / (name + '.toml')
        options = {'name': name, 'runtime': adapter, 'exe': inputs['exe'], 'cdb': inputs['cdb'],
                   'helper': HERE / 'dependencies/helper.dll', 'identity': HERE / 'dependencies/identity.dll',
                   'base': base, 'copy-path': target, 'user': inputs['user']}
        options.update(changes or {})
        command = ['stand-init', '--output', destination, '--format', format_]
        for key, value in options.items():
            command += ['--' + key, value]
        for name_ in inputs['copy_exclude']:
            command += ['--copy-exclude', name_]
        previous = destination.read_bytes() if destination.exists() else None
        result = execute(name, command, expected)
        report = json.loads(result.stdout) if format_ == 'json' else {'status': 'created'}
        assert report['status'] == ('created' if expected == 0 else 'blocked')
        if format_ == 'json':
            assert not report['platform_checked'] and not report['launch_performed']
        if expected == 0:
            stand = load_stand(destination)
            assert stand.extra == {'runtime': adapter} and stand.base == base and stand.copy_path == target
            assert stand.user == inputs['user'] and list(stand.copy_exclude) == inputs['copy_exclude']
            assert stand.tool_hashes['helper'] == digest(HERE / 'dependencies/helper.dll')
            if format_ == 'json':
                assert report['profile']['sha256'] == digest(destination)
        elif previous is not None:
            assert destination.read_bytes() == previous
        else:
            assert not destination.exists()
        assert not list(profiles.glob('.harness77-*'))
        assert snapshot() == before
        evidence['init'].append(dict(report, case=name, log_sha256=digest(out / (name + '.log'))))
        return destination

    try:
        assert not before['processes'] and not before['copy'] and not before['lock']
        headless = create('стенд headless')
        forms = create('стенд forms', 'forms', format_='text')
        create('existing-profile', output=headless, expected=2)
        create('missing-helper', changes={'helper': controls / 'missing.dll'}, expected=2)
        header = bytearray(64)
        header[:2], header[60:64] = b'MZ', (64).to_bytes(4, 'little')
        bad_cdb = controls / 'cdb-x64.exe'
        bad_cdb.write_bytes(header + b'PE\0\0\x64\x86')
        create('wrong-pe', changes={'cdb': bad_cdb}, expected=2)
        bad_helper = controls / 'changed-helper.dll'
        bad_helper.write_bytes((HERE / 'dependencies/helper.dll').read_bytes() + b'controlled changed copy')
        create('wrong-hash', changes={'helper': bad_helper}, expected=2)
        create('overlap', changes={'copy-path': base / 'nested-copy'}, expected=2)
        create('unregistered', changes={'copy-path': controls / 'unregistered-copy'}, expected=2)
        occupied = controls / 'occupied-copy'
        occupied.mkdir()
        (occupied / 'foreign.txt').write_bytes(b'preserve')
        create('occupied', changes={'copy-path': occupied}, expected=2)
        assert (occupied / 'foreign.txt').read_bytes() == b'preserve'
        for name, profile, project, adapter in [('headless', headless, HERE / 'headless/project.toml', 'headless'),
                                                 ('forms', forms, HERE / 'success/project.toml', 'forms')]:
            future = out / ('doctor-' + name + '-uncreated')
            response = execute('doctor-' + name, ['doctor', '--project', project, '--stand', profile,
                               '--output-root', future, '--format', 'json'], 0)
            doctor = json.loads(response.stdout)
            assert doctor['status'] == 'ready' and not doctor['launch_performed'] and not future.exists()
            assert snapshot() == before
            evidence['doctors'].append(doctor)
            root = out / ('run-' + name)
            execute('run-' + name, ['run', '--project', project, '--stand', profile, '--output-root', root], 0)
            reports = list(root.glob('*/run.json'))
            assert len(reports) == 1
            folder = reports[0].parent
            report = read(reports[0])
            record = excluded(folder)
            assert not record['issues'] and report['status'] == 'passed' and report['platform_checked']
            platform = read(folder / 'platform-result.json')
            trace = read(folder / 'native/startup.json')
            assert trace['status'] == 'ready' and trace == platform['open']['startup']
            assert [e['stage'] for e in trace['events']].count('initialize_finished') == 1
            for state in ('started', 'finished'):
                assert marker(folder / 'native' / ('ert-initialize-' + state)).strip() == report['run_id']
            assert (folder / 'native/client.vbs').read_text(encoding='utf-16').count('result = v.Initialize(') == 1
            provenance = read(folder / 'launcher-environment.json')
            assert provenance['module'] == harness77.__file__ and provenance['prefix'] == sys.prefix
            assert provenance['runtime'] == runtime.inspect_runtime(adapter)
            if name == 'headless':
                assert next(o for o in platform['operations'] if o['name'] == 'execute')['value'] == '42'
            else:
                checked = check(folder, 'success', digest(reports[0]))
                assert not checked['issues'], checked
                record['application'] = checked
            record.update(case=name, startup=trace, environment=provenance)
            evidence['runs'].append(record)
            if guard_before is None and not inspector.processes() and not target.exists() and not lock.exists():
                guard.unlink(missing_ok=True)
            assert snapshot() == before
        evidence['status'] = 'passed'
    except Exception as error:
        evidence.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        after = snapshot()
        evidence['unchanged'] = {key: value == after[key] for key, value in before.items()}
        if not all(evidence['unchanged'].values()):
            evidence['status'] = 'failed'
        (out / 'verified.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(out / 'verified.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
