"""Verify the installed runtime and complete application from a checkout-free kit."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def registry_tree(root):
    import winreg
    def children(key):
        subkeys, values, _ = winreg.QueryInfoKey(key)
        result = {'values': sorted([list(winreg.EnumValue(key, i)) for i in range(values)]), 'children': {}}
        for i in range(subkeys):
            name = winreg.EnumKey(key, i)
            with winreg.OpenKey(key, name, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as child:
                result['children'][name] = children(child)
        return result
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            return children(key)
    except FileNotFoundError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt' or sys.prefix == sys.base_prefix or os.environ.get('PYTHONPATH') or os.environ.get('PYTHONHOME'):
        parser.error('requires a clean Windows venv without PYTHONPATH/PYTHONHOME')
    import harness77
    from harness77 import basecopy77, native_runtime77 as runtime
    from harness77.config77 import load_stand
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    if not Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        parser.error('harness77 must be installed in this venv')
    if sorted(d.metadata['Name'] for d in metadata.distributions()) != ['harness77']:
        parser.error('venv must contain only harness77')
    manifest = read(HERE / 'kit.json')
    assert not (HERE / 'native').exists() and not (HERE / 'launcher.py').exists()
    assert all(digest(HERE / n) == h for n, h in manifest['files'].items())
    info = runtime.inspect_runtime('forms')
    sys.path[:0] = [str(HERE / 'verification'), str(runtime.HERE / '_native/forms')]
    from verify_document_form77 import check, excluded
    from verify_suite77 import verify
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    foreign = out / 'working'
    foreign.mkdir()
    stand = load_stand(HERE / 'stand.toml')
    inspector = WindowsInspector()
    lock = basecopy77.lock_path(stand.copy_path)
    guard = lock.with_name(lock.name + '.guard')
    guard_before = guard.read_bytes() if guard.exists() else None

    def snapshot():
        return {'source': basecopy77.listing(stand.base),
                'hashes': {n: digest(stand.base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                'registry': {key: registry_tree(key) for key in (TITLES, *COM_KEYS)}, 'processes': inspector.processes(),
                'copy': stand.copy_path.exists(), 'lock': lock.exists(), 'guard': digest(guard) if guard.exists() else None,
                'kit': {n: digest(HERE / n) for n in manifest['files']}, 'runtime': runtime.inspect_runtime('forms')}

    before = snapshot()
    evidence = {'status': 'running', 'environment': {'python': sys.executable, 'prefix': sys.prefix,
                'module': harness77.__file__, 'cwd': str(foreign)}, 'runtime': info,
                'kit_sha256': digest(HERE / 'kit.json'), 'runs': [], 'suites': [], 'doctors': []}
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')

    def save():
        (out / 'verified.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def unchanged_after_run():
        if guard_before is None and not inspector.processes() and not stand.copy_path.exists() and not lock.exists():
            guard.unlink(missing_ok=True)
        assert snapshot() == before

    def execute(name, command, expected):
        result = subprocess.run([sys.executable, '-B', '-m', 'harness77', *map(str, command)],
                                cwd=foreign, env=env, capture_output=True, timeout=1500)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
        assert result.returncode == expected, (name, result.returncode)
        return result

    def doctor(name):
        target = out / (name + '-uncreated')
        result = execute(name, ['doctor', '--project', HERE / 'success/project.toml', '--stand', HERE / 'stand.toml',
                                '--output-root', target, '--format', 'json'], 0)
        report = json.loads(result.stdout)
        assert report['status'] == 'ready' and not report['launch_performed'] and not report['platform_checked']
        assert next(r for r in report['checks'] if r['id'] == 'stand.runtime')['details'] == info
        assert not target.exists() and snapshot() == before
        evidence['doctors'].append(report)

    def startup(folder, adapter, initialized=True):
        report, platform = read(folder / 'run.json'), read(folder / 'platform-result.json')
        record = excluded(folder)
        assert not record['issues'], record
        provenance = read(folder / 'launcher-environment.json')
        assert provenance['module'] == harness77.__file__ and provenance['prefix'] == sys.prefix
        assert provenance['runtime'] == runtime.inspect_runtime(adapter)
        assert Path(provenance['payload']).is_relative_to(Path(sys.prefix))
        trace = read(folder / 'native/startup.json')
        assert trace == platform['open']['startup'] == next(s for s in report['stages'] if s['stage'] == 'platform_check')['open']['startup']
        stages = [e['stage'] for e in trace['events']]
        assert stages == ['registration_acquired', 'debugger_created', 'server_owned', 'debugger_commands',
                          'observer_bound', 'factory_observed', 'activation_ready', 'client_created',
                          'proxy_verified', 'initialize_permitted', 'initialize_started', 'initialize_finished']
        for state in ('started', 'finished'):
            raw = (folder / 'native' / ('ert-initialize-' + state)).read_bytes()
            data = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'cp1251').strip()
            assert data == report['run_id']
        client = folder / 'native/client.vbs'
        assert client.read_text(encoding='utf-16').count('result = v.Initialize(') == 1
        assert read(folder / 'native/shutdown-manifest.json')['sources']['client.vbs'] == digest(client)
        if initialized:
            assert trace['status'] == 'ready' and platform['shutdown']['forced_cleanup'] is False
        record.update(startup=trace, launcher_environment=provenance)
        return record

    def headless(name, cancel=False):
        target = out / name
        command = ['run', '--project', HERE / ('cancel' if cancel else 'headless') / 'project.toml',
                   '--stand', HERE / 'stand-headless.toml', '--output-root', target]
        if cancel:
            cancel_file = out / 'cancel-request'
            command += ['--cancel-file', cancel_file]
            with (out / (name + '.log')).open('wb') as stream:
                process = subprocess.Popen([sys.executable, '-B', '-m', 'harness77', *map(str, command)],
                                           cwd=foreign, env=env, stdout=stream, stderr=subprocess.STDOUT)
                triggered = False
                until = time.monotonic() + 180
                while time.monotonic() < until and process.poll() is None:
                    markers = list(target.glob('*/native/ert-execute-started'))
                    if markers:
                        cancel_file.write_text(markers[0].parent.parent.name, encoding='ascii')
                        triggered = True
                        break
                    time.sleep(0.1)
                if not triggered:
                    cancel_file.write_text('cancel', encoding='ascii')
                result = process.wait(timeout=100)
                assert triggered and result == 2, 'cancellation failed; see log'
        else:
            execute(name, command, 0)
        paths = list(target.glob('*/run.json'))
        assert len(paths) == 1
        folder = paths[0].parent
        report = read(paths[0])
        record = startup(folder, 'headless', initialized=not cancel)
        if cancel:
            assert report['cancelled'] and report['reason'] == 'cancelled'
        else:
            assert report['status'] == 'passed' and report['platform_checked']
            platform = read(folder / 'platform-result.json')
            assert next(o for o in platform['operations'] if o['name'] == 'execute')['value'] == '42'
        evidence['runs'].append(dict(record, case=name))
        unchanged_after_run()
        save()

    try:
        assert not before['processes'] and not before['copy'] and not before['lock']
        assert all(before['registry'][key] is None for key in COM_KEYS)
        doctor('doctor-before')
        headless('headless')
        for name, expected in (('suite', 0), ('suite-failure', 1)):
            execute(name, ['suite', '--suite', HERE / (name + '.toml'), '--stand', HERE / 'stand.toml',
                           '--output-root', out / 'results', '--suite-id', name], expected)
            folder = out / 'results' / name
            result = verify(folder, native=True)
            assert not result['issues'], result
            evidence['suites'].append(result)
            for row in read(folder / 'suite.json')['scenarios']:
                run = (folder / row['report']['path']).parent
                checked = check(run, 'wrong' if row['id'] == 'wrong' else 'success', row['report']['sha256'])
                assert not checked['issues'], checked
                evidence['runs'].append(dict(startup(run, 'forms'), application=checked, case=row['id']))
            unchanged_after_run()
            save()
        headless('cancel', cancel=True)
        headless('after-cancel')
        doctor('doctor-after')
        evidence['status'] = 'passed'
    except Exception as error:
        evidence.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        # Preserve an existing idle guard. Restore absence only after all sessions ended.
        if guard_before is None and not inspector.processes() and not stand.copy_path.exists() and not lock.exists():
            guard.unlink(missing_ok=True)
        after = snapshot()
        evidence['unchanged'] = {key: value == after[key] for key, value in before.items()}
        if not all(evidence['unchanged'].values()):
            evidence['status'] = 'failed'
        save()
    print(out / 'verified.json')
    return 0 if evidence['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
