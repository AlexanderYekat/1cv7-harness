"""098: generated forms projects through installed run, suite and stdio MCP."""
import argparse
import difflib
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'verification'))
from support96 import read, digest, write_json, registry_tree, md_difference, POSTING, CORRECT, REGRESSION
from mcp_client import Client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--local-activation', action='store_true', help='099: doctor/run/suite/MCP via project-local launcher')
    args = parser.parse_args()
    if os.name != 'nt' or sys.prefix == sys.base_prefix or os.environ.get('PYTHONPATH') or os.environ.get('PYTHONHOME'):
        parser.error('requires clean installed Windows venv')
    import harness77
    from harness77 import basecopy77, native_runtime77 as runtime
    from harness77.config77 import load_project
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    assert Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    assert sorted(d.metadata['Name'] for d in metadata.distributions()) == ['harness77']
    sys.path.insert(0, str(runtime.HERE / '_native/forms'))
    from suite_verify import verify, normalized
    from verify import creation, direct_run

    manifest, inputs, scenario = read(HERE / 'kit.json'), read(HERE / 'inputs.json'), read(HERE / 'inputs/scenario.json')
    assert all(digest(HERE / n) == sha for n, sha in manifest['files'].items())
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    working, builds, sources = out / 'working', out / 'builds', out / 'sources'
    projects = out / 'projects'
    for path in (working, builds, sources, projects):
        path.mkdir()
    base, copy = Path(inputs['base']), Path(inputs['copy_path'])
    source_md = base / '1Cv7.MD'
    lock = basecopy77.lock_path(copy)
    guard = lock.with_name(lock.name + '.guard')
    inspector = WindowsInspector()

    def snapshot():
        return {'source': basecopy77.listing(base),
                'hashes': {n: digest(base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                'registry': {key: registry_tree(key) for key in (TITLES, *COM_KEYS)}, 'processes': inspector.processes(),
                'copy': copy.exists(), 'lock': lock.exists(), 'guard': digest(guard) if guard.exists() else None,
                'kit': {n: digest(HERE / n) for n in manifest['files']}, 'runtime': runtime.inspect_runtime('forms')}

    before = snapshot()
    evidence = {'status': 'running', 'controlled_regression': True,
                'environment': {'python': sys.executable, 'module': harness77.__file__, 'cwd': str(working)},
                'kit_sha256': digest(HERE / 'kit.json'), 'baseline': before,
                'plans': {}, 'suites': [], 'commands': [], 'created': [], 'runs': [], 'refusals': []}
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    client = None
    activation = None

    def save():
        write_json(out / 'verified.json', evidence)

    def execute(name, command, expected=0):
        argv = [sys.executable, '-B', '-m', 'harness77', *map(str, command)]
        if activation is not None and command[0] in ('doctor', 'run', 'suite'):
            argv = [sys.executable, '-I', '-B', str(activation), *map(str, command)]
        response = subprocess.run(argv, cwd=working, env=env, capture_output=True, timeout=1800)
        (out / (name + '.log')).write_bytes(response.stdout + response.stderr)
        evidence['commands'].append({'name': name, 'argv': argv, 'exit_code': response.returncode})
        save()
        assert response.returncode == expected, (name, response.returncode, expected)
        return json.loads(response.stdout)

    def preserved():
        if before['guard'] is None and not inspector.processes() and not copy.exists() and not lock.exists():
            guard.unlink(missing_ok=True)
        assert snapshot() == before, 'stand changed'

    try:
        assert not before['copy'] and not before['lock']
        assert all(before['registry'][key] is None for key in COM_KEYS)
        stand = out / 'stand.toml'
        command = ['stand-init', '--output', stand, '--name', 'application098', '--runtime', 'forms', '--format', 'json',
                   '--exe', inputs['exe'], '--cdb', inputs['cdb'], '--helper', HERE / 'dependencies/helper.dll',
                   '--identity', HERE / 'dependencies/identity.dll', '--base', base, '--copy-path', copy, '--user', inputs['user']]
        for name in inputs['copy_exclude']:
            command += ['--copy-exclude', name]
        execute('stand-init', command)
        preserved()
        execute('md-extract', ['md-extract', source_md, '--output', out / 'extraction'])
        index = read(out / 'extraction/modules.json')
        target_path, = [m['path'] for m in index['modules'] if m['file'] == POSTING]
        original = (out / 'extraction' / POSTING).read_bytes().decode('utf-8')
        assert original.count(CORRECT) == 1 and REGRESSION not in original
        broken = original.replace(CORRECT, REGRESSION)
        fixed = broken.replace(REGRESSION, CORRECT)
        assert original == fixed
        for name, text in [('baseline', original), ('regression', broken), ('fixed', fixed)]:
            (sources / (name + '.1s')).write_bytes(text.encode('utf-8'))
        for name, a, b in [('regression.diff', original, broken), ('repair.diff', broken, fixed)]:
            (sources / name).write_bytes(''.join(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
                                         fromfile=POSTING, tofile=POSTING)).encode('utf-8'))
        expected = read(HERE / 'expected.json')
        verify_test = next(t for t in scenario['tests'] if t['command'] == 'verify')
        assert json.loads(verify_test['expect_json']) == expected
        assert '.Провести(' not in scenario['parameters']['fixture_setup'] and 'fixture_post' not in scenario['parameters']
        platform_hash = hashlib.sha256(json.dumps(scenario, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        evidence['unchanged_test'] = {'platform_sha256': platform_hash, 'module': digest(HERE / 'inputs/form-module.1s'),
                                      'template': digest(HERE / 'inputs/template.ert'), 'expected': digest(HERE / 'expected.json')}
        phases = ('baseline', 'regression', 'fixed', 'repeat-fixed', 'invalid-json', 'empty-json', 'recovered')
        profiles = {}
        for name in phases:
            project_dir = projects / ('прикладной проект' if name == 'baseline' else name)
            scenario_file = HERE / 'inputs/scenario.json'
            if name in ('invalid-json', 'empty-json'):
                altered = json.loads(json.dumps(scenario))
                altered['parameters']['fixture_verify'] = 'Возврат "{";' if name == 'invalid-json' else 'Возврат "";'
                scenario_file = sources / (name + '.json')
                write_json(scenario_file, altered)
            arguments = ['project-init', '--runtime', 'forms', '--directory', project_dir, '--id', 'application098-' + name,
                         '--template', HERE / 'inputs/template.ert', '--source', HERE / 'inputs/form-module.1s',
                         '--scenario', scenario_file, '--open-timeout-s', 240, '--calculation-timeout-s', 120,
                         '--cancel-timeout-s', 15, '--shutdown-timeout-s', 30, '--total-timeout-s', 600, '--format', 'json']
            initialized = execute('project-init-' + name, arguments)
            created = {'case': name, 'report': initialized, 'scenario': str(scenario_file)}
            creation(created)
            evidence['created'].append(created)
            preserved()
            source = broken if name == 'regression' else fixed
            configuration = project_dir / 'configuration'
            target = configuration / POSTING
            target.parent.mkdir(parents=True)
            target.write_bytes(source.encode('utf-8'))
            (configuration / 'modules.json').write_bytes((out / 'extraction/modules.json').read_bytes())
            profile = project_dir / 'project.toml'
            profiles[name] = profile
            loaded = load_project(profile)
            planned = builds / (name + '.MD')
            built = execute('build-' + name, ['md-build', '--template', source_md, '--modules', loaded.configuration, '--output', planned])
            assert all(built['verification'].values()) and not built['changed_forms']
            audit = md_difference(source_md, planned, target_path, source)
            assert bool(audit['changed_streams']) == (name == 'regression')
            evidence['plans'][name] = {'project': str(profile), 'project_sha256': digest(profile),
                                       'md': str(planned), 'md_sha256': digest(planned),
                                       'module_sha256': digest(target), 'build': built, 'audit': audit}
            if args.local_activation and activation is None:
                execute('connect-local', ['connect', '--directory', working, '--external-python', sys.executable,
                                          '--project', profile, '--stand', stand, '--format', 'json'])
                activation = working / '.harness77/launch.py'
                evidence['activation'] = {'launcher': str(activation), 'config_sha256': digest(activation.with_name('config.json'))}
            doctor = execute('doctor-' + name, ['doctor', '--project', profile, '--stand', stand,
                                                '--output-root', out / 'future', '--format', 'json'])
            assert doctor['status'] == 'ready' and not doctor['launch_performed'] and not (out / 'future').exists()
            preserved()

        # Initialization refusals must leave both generated projects and the stand intact.
        bad_scenario = sources / 'bad-scenario.json'
        write_json(bad_scenario, {'parameters': {}, 'tests': [{'name': 'bad', 'command': 'verify',
                    'expect': 'passed', 'expect_json': '{'}]})
        bad_source = sources / 'bad-source.1s'
        bad_source.write_text('// 😀', encoding='utf-8')
        empty = projects / 'existing-empty'
        empty.mkdir()
        for name, changes in [('existing-project', {'--directory': profiles['baseline'].parent}),
                              ('existing-empty', {'--directory': empty}),
                              ('bad-scenario', {'--scenario': bad_scenario}),
                              ('bad-source', {'--source': bad_source}),
                              ('missing-source', {'--source': sources / 'missing.1s'}),
                              ('wrong-runtime', {'--runtime': 'headless'}),
                              ('bad-deadline', {'--total-timeout-s': 1})]:
            command = list(arguments)
            command[command.index('--directory') + 1] = projects / ('refused-' + name)
            for key, value in changes.items():
                command[command.index(key) + 1] = value
            report = execute('refusal-' + name, command, expected=2)
            assert report['status'] == 'blocked' and not report['launch_performed'] and not report['platform_checked']
            assert not list(projects.glob('.harness77-project-*'))
            if not name.startswith('existing'):
                assert not (projects / ('refused-' + name)).exists()
            assert not list(empty.iterdir())
            evidence['refusals'].append({'case': name, 'report': report})
            for row in evidence['created']:
                creation(row)
            preserved()

        for name in ('baseline', 'regression', 'fixed'):
            future = out / ('run-' + name)
            summary = execute('run-' + name, ['run', '--project', profiles[name], '--stand', stand,
                                              '--output-root', future], expected=1 if name == 'regression' else 0)
            row = {'case': name, 'folder': summary['run_dir'], 'summary': summary}
            row['verification'] = direct_run(row, evidence['plans'], expected)
            evidence['runs'].append(row)
            preserved()
            for created in evidence['created']:
                creation(created)
            save()
            print('run ' + name + ': verified ' + summary['status'], flush=True)

        manifests = {}
        for name, cases in [('regression', phases[:4]), ('invalid-results', phases[4:]), ('success', ('fixed',))]:
            path = out / (name + '.toml')
            text = 'schema_version=1\n[suite]\nid="application098-' + name + '"\n'
            for case in cases:
                text += '\n[[scenarios]]\nid=' + json.dumps(case) + '\nproject=' + json.dumps(profiles[case].as_posix()) + '\n'
            path.write_text(text, encoding='utf-8')
            manifests[name] = path
        frozen = {str(p): digest(p) for p in (*projects.rglob('*'), *manifests.values()) if p.is_file()}
        for transport in ('cli', 'mcp'):
            if transport == 'mcp':
                client = Client(working, out / 'mcp-traffic.json', env,
                                command=[sys.executable, '-I', '-B', str(activation), 'mcp'] if activation else None)
                evidence['mcp_pid'] = client.process.pid
            for name in ('regression', 'invalid-results', 'success'):
                if transport == 'cli' and name == 'success':
                    continue
                code = {'regression': 1, 'invalid-results': 2, 'success': 0}[name]
                root = out / (transport + '-' + name)
                arguments = {'suite': str(manifests[name]), 'stand': str(stand), 'suite_id': 'suite', 'output_root': str(root)}
                response = progress = None
                if transport == 'cli':
                    summary = execute('suite-' + name, ['suite', '--suite', manifests[name], '--stand', stand,
                                                      '--suite-id', 'suite', '--output-root', root], expected=code)
                else:
                    response, progress = client.suite(arguments)
                    write_json(out / ('mcp-' + name + '.json'), {'response': response, 'progress': progress})
                    assert response['isError'] == (code == 2), response
                    assert response['structuredContent']['exit_code'] == code
                    assert progress['ping_during'] and progress['ping_after']
                    summary = response['structuredContent']['stdout']
                assert summary['exit_code'] == code and summary['complete'] and not summary['cancelled']
                folder = root / 'suite'
                verified = verify(folder, evidence['plans'], expected)
                if progress is not None:
                    rows = read(folder / 'suite.json')['scenarios']
                    messages = [e['message'] for e in progress['events']]
                    for index, row in enumerate(rows, 1):
                        assert any(f'сценарий {index}/{len(rows)} «{row["id"]}»' in msg for msg in messages)
                    amounts = [e['progress'] for e in progress['events']]
                    assert all(a < b for a, b in zip(amounts, amounts[1:]))
                    assert all(e['progressToken'] == 'suite' for e in progress['events'])
                for row in verified['scenarios']:
                    provenance = row['environment']
                    assert provenance['module'] == harness77.__file__ and provenance['prefix'] == sys.prefix
                    assert provenance['runtime'] == runtime.inspect_runtime('forms')
                preserved()
                assert all(digest(Path(p)) == sha for p, sha in frozen.items())
                evidence['suites'].append({'transport': transport, 'manifest': name, 'folder': str(folder),
                                           'manifest_sha256': digest(manifests[name]), 'summary': summary,
                                           'response': response, 'progress': progress, 'verification': verified})
                save()
                print(transport + ' ' + name + ': verified ' + summary['status'], flush=True)
        if activation is not None:
            marker = working / 'harness77.txt'
            marker.unlink()
            disabled, _ = client.request('tools/call', {'name': 'suite', 'arguments': {}})
            assert disabled['result']['isError'] and 'disabled' in disabled['result']['content'][0]['text']
            ping, _ = client.request('ping')
            assert ping['result'] == {}
            evidence['mcp_disabled_after_marker_removal'] = disabled
            marker.touch()
        assert client.close() == 0
        client = None
        evidence['mcp_exit_code'] = 0
        for name in ('regression', 'invalid-results'):
            a, b = [s['verification'] for s in evidence['suites'] if s['manifest'] == name]
            assert normalized(a) == normalized(b)
        evidence['cli_mcp_equal'] = True
        evidence['status'] = 'passed'
    except Exception as error:
        evidence.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        if client is not None:
            evidence['mcp_exit_code'] = client.close()
        after = snapshot()
        evidence['unchanged'] = {key: value == after[key] for key, value in before.items()}
        if not all(evidence['unchanged'].values()):
            evidence['status'] = 'failed'
        save()
    print(out / 'verified.json')
    return 0 if evidence['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
