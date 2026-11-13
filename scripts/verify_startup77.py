"""091: independent starts, debugger-list A/B, pre-Initialize rejection and cancellation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib

import harness77
from harness77 import basecopy77
from harness77.config77 import load_stand
from harness77.doctor_windows77 import COM_KEYS, TITLES, WindowsInspector
from verify_doctor77 import digest, registry_tree
from verify_document_form77 import excluded, read

ROOT = Path(__file__).resolve().parents[1]


def write_toml(path, data):
    def value(item):
        if isinstance(item, dict):
            return '{ ' + ', '.join(json.dumps(k) + ' = ' + value(v) for k, v in item.items()) + ' }'
        if isinstance(item, list):
            return '[' + ', '.join(map(value, item)) + ']'
        return json.dumps(item, ensure_ascii=False, allow_nan=False)
    path.write_text('\n'.join(json.dumps(k) + ' = ' + value(v) for k, v in data.items()) + '\n', encoding='utf-8')


def startup_evidence(folder, initialized, *, expected_value='42', expected_status='passed'):
    report = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    platform = json.loads((folder / 'platform-result.json').read_text(encoding='utf-8'))
    record = excluded(folder)
    assert not record['issues'], record
    native = folder / 'native'
    trace_file = native / 'startup.json'
    stages = []
    if trace_file.exists():
        trace = json.loads(trace_file.read_text(encoding='utf-8'))
        assert trace['run_id'] == report['run_id'] == platform['run_id']
        assert trace == platform['open']['startup'], 'final startup trace differs'
        assert trace == next(s for s in report['stages'] if s['stage'] == 'platform_check')['open']['startup']
        stages = [e['stage'] for e in trace['events']]
        assert len(stages) == len(set(stages))
        times = [e['observed_s'] for e in trace['events']]
        assert times == sorted(times)
        record['startup'] = trace
    pair = [native / ('ert-initialize-' + state) for state in ('started', 'finished')]
    if initialized:
        expected = ['registration_acquired', 'debugger_created', 'server_owned', 'debugger_commands',
                    'observer_bound', 'factory_observed', 'activation_ready', 'client_created',
                    'proxy_verified', 'initialize_permitted', 'initialize_started', 'initialize_finished']
        assert stages == expected, stages
        assert all(p.exists() and read(p).strip() == report['run_id'] for p in pair)
        client = (native / 'client.vbs').read_text(encoding='utf-16')
        assert client.count('result = v.Initialize(') == 1
        owned = next(e for e in trace['events'] if e['stage'] == 'server_owned')
        assert owned['ownership_verified'] and owned['creation_filetime'] >= owned['debugger_creation_filetime']
        proxy = next(e for e in trace['events'] if e['stage'] == 'proxy_verified')
        assert proxy['pid'] == owned['pid']
        manifest = json.loads((native / 'shutdown-manifest.json').read_text(encoding='utf-8'))
        assert manifest['sources']['client.vbs'] == digest(native / 'client.vbs')
        assert trace['status'] == 'ready'
        assert platform['shutdown']['forced_cleanup'] is False
        assert '\nHARNESS77_FIRST_CHANCE_AV\n' not in (native / 'debugger.log').read_text(errors='replace')
        assert not (native / 'first-av.dmp').exists()
        commands = (native / 'debugger.txt').read_text(encoding='ascii')
        assert commands.count('.reload /s /f combase.dll') == 1
        if expected_value is not None:
            assert next(o for o in platform['operations'] if o['name'] == 'execute')['value'] == expected_value
        assert report['status'] == expected_status
    else:
        assert not any(p.exists() for p in pair)
        assert not (native / 'initialize-permit').exists()
        assert 'client_created' not in stages and 'initialize_started' not in stages
        assert not (native / 'client.log').exists()
    record.update(run_sha256=digest(folder / 'run.json'), platform_sha256=digest(folder / 'platform-result.json'))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--old-kit', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True, help='known headless execute=42 project')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=20)
    args = parser.parse_args()
    if os.name != 'nt' or sys.prefix == sys.base_prefix or os.environ.get('PYTHONPATH') or os.environ.get('PYTHONHOME'):
        parser.error('requires a clean installed Windows venv')
    if not Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        parser.error('harness77 must be installed in the venv')
    if not 1 <= args.count <= 100:
        parser.error('count must be 1..100')
    kit, old, output = args.kit.resolve(strict=True), args.old_kit.resolve(strict=True), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    profiles, working = output / 'profiles', output / 'working'
    profiles.mkdir()
    working.mkdir()
    stand = load_stand(kit / 'stand.toml')
    settings = tomllib.loads((kit / 'stand.toml').read_text(encoding='utf-8'))
    settings['stand']['launcher'] = (ROOT / 'research/platform77/startup_probe77.py').as_posix()
    for role in ('exe', 'cdb', 'helper', 'identity'):
        settings['stand']['paths'][role] = getattr(stand, role).as_posix()
    settings['stand']['base'].update(path=stand.base.as_posix(), copy_path=stand.copy_path.as_posix())
    write_toml(profiles / 'stand.toml', settings)
    source = args.project.resolve(strict=True)
    project = tomllib.loads(source.read_text(encoding='utf-8'))
    for role in ('template', 'source'):
        project['build'][role] = (source.parent / project['build'][role]).resolve(strict=True).as_posix()
    project['configuration']['modules'] = (source.parent / project['configuration']['modules']).resolve(strict=True).as_posix()
    project['platform']['tests'][0]['expect_value'] = '42'
    project['deadlines'].update(open_timeout_s=120, total_timeout_s=300)
    parameters = project['platform'].setdefault('parameters', {})
    inspector = WindowsInspector()
    lock = basecopy77.lock_path(stand.copy_path)
    guard = lock.with_name(lock.name + '.guard')
    manifest = json.loads((kit / 'kit.json').read_text(encoding='utf-8'))

    def snapshot():
        return {'source': basecopy77.listing(stand.base),
                'hashes': {n: digest(stand.base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                'registry': {key: registry_tree(key) for key in (TITLES, *COM_KEYS)}, 'processes': inspector.processes(),
                'copy': stand.copy_path.exists(), 'lock': lock.exists(), 'guard': digest(guard) if guard.exists() else None,
                'kit': {n: digest(kit / n) for n in manifest['files']}}

    before = snapshot()
    evidence = {'status': 'running', 'runs': [], 'environment': {'python': sys.executable, 'module': harness77.__file__},
                'kit_sha256': digest(kit / 'kit.json'), 'probe_sha256': digest(ROOT / 'research/platform77/startup_probe77.py')}
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')

    def save():
        (output / 'verified.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def execute(name, runtime, mode, outcome, *, cancel=False, short=False):
        parameters.update(startup_probe_runtime=runtime.as_posix(), startup_probe_mode=mode)
        project['deadlines']['open_timeout_s'] = 8 if short else 120
        profile = profiles / (name + '.toml')
        write_toml(profile, project)
        root = output / name
        log = output / (name + '.log')
        with log.open('wb') as stream:
            process = subprocess.Popen([sys.executable, '-B', '-m', 'harness77', 'run', '--project', str(profile),
                                       '--stand', str(profiles / 'stand.toml'), '--output-root', str(root)],
                                      cwd=working, env=env, stdout=stream, stderr=subprocess.STDOUT)
            if cancel:
                until = time.monotonic() + 70
                while time.monotonic() < until and process.poll() is None:
                    traces = list(root.glob('*/native/startup.json'))
                    if traces:
                        trace = json.loads(traces[0].read_text(encoding='utf-8'))
                        debug = traces[0].parent / 'debugger.log'
                        if trace['waiting_for'] == 'factory_registration' and debug.exists() and '\nHARNESS77_PROBE_FACTORY_HELD\n' in debug.read_text(errors='replace'):
                            (traces[0].parent.parent / 'cancel').write_text(trace['run_id'], encoding='ascii')
                            break
                    time.sleep(0.1)
                else:
                    # Ask this run to cancel through its public marker; no foreign process termination.
                    for trace_path in root.glob('*/native/startup.json'):
                        (trace_path.parent.parent / 'cancel').write_text(trace_path.parent.parent.name, encoding='ascii')
                    process.wait(timeout=100)
                    raise AssertionError('factory hold was not observed before cancellation')
            result = process.wait(timeout=400)
        assert result == (0 if outcome == 'passed' else 2), (name, result)
        folders = list(root.glob('*/run.json'))
        assert len(folders) == 1
        folder = folders[0].parent
        record = startup_evidence(folder, outcome == 'passed')
        actual = json.loads((folder / 'platform-result.json').read_text(encoding='utf-8'))
        assert actual['status'] == ('passed' if outcome == 'passed' else 'blocked'), (name, actual['status'], actual.get('reason'))
        if outcome in ('open_timeout', 'cancelled'):
            assert actual['reason'] == outcome, (name, actual.get('reason'))
        if mode == 'hold-factory':
            assert record['startup']['waiting_for'] == 'factory_registration'
            assert record['startup']['status'] == ('cancelled' if cancel else 'blocked')
            if not cancel:
                assert actual['timeout_phase'] == 'open' and actual['native_timeout_phase'] == 'factory-registration'
        if mode == 'unbound':
            assert record['startup']['waiting_for'] == 'observer_binding'
            assert actual['reason'] == 'ValueError: COM observer breakpoint is not enabled and resolved'
        record.update(case=name, mode=mode, profile_sha256=digest(profile))
        evidence['runs'].append(record)
        assert snapshot() == before, 'stand changed after ' + name
        save()
        print(name + ': ' + outcome, flush=True)

    try:
        assert not before['processes'] and not before['copy'] and not before['lock']
        assert before['kit'] == manifest['files'], 'export hashes differ'
        execute('old-loss', old, 'lost-module', 'open_timeout', short=True)
        execute('fixed-loss', kit, 'lost-module', 'passed')
        execute('unbound', kit, 'unbound', 'native_launcher_error')
        execute('timeout', kit, 'hold-factory', 'open_timeout', short=True)
        execute('cancel', kit, 'hold-factory', 'cancelled', cancel=True)
        for index in range(args.count):
            execute(f'start-{index + 1:02}', kit, 'normal', 'passed')
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
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
