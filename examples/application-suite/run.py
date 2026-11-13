"""097: the accepted application regression through CLI suite and installed stdio MCP."""
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
from support96 import read, digest, write_json, toml_value, registry_tree, md_difference, POSTING, CORRECT, REGRESSION
from mcp_client import Client


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
    sys.path.insert(0, str(runtime.HERE / '_native/forms'))
    from verify import verify, normalized
    import tomllib

    manifest, inputs, scenario = read(HERE / 'kit.json'), read(HERE / 'inputs.json'), read(HERE / 'inputs/scenario.json')
    assert all(digest(HERE / n) == sha for n, sha in manifest['files'].items())
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    working, builds, sources = out / 'working', out / 'builds', out / 'sources'
    for path in (working, builds, sources):
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
                'plans': {}, 'suites': [], 'commands': []}
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    client = None

    def save():
        write_json(out / 'verified.json', evidence)

    def execute(name, command, expected=0):
        argv = [sys.executable, '-B', '-m', 'harness77', *map(str, command)]
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
        command = ['stand-init', '--output', stand, '--name', 'application097', '--runtime', 'forms', '--format', 'json',
                   '--exe', inputs['exe'], '--cdb', inputs['cdb'], '--helper', HERE / 'dependencies/helper.dll',
                   '--identity', HERE / 'dependencies/identity.dll', '--base', base, '--copy-path', copy, '--user', inputs['user']]
        for name in inputs['copy_exclude']:
            command += ['--copy-exclude', name]
        execute('stand-init', command)
        project_dir = out / 'project'
        execute('project-init', ['project-init', '--directory', project_dir, '--id', 'application097',
                                '--template', HERE / 'inputs/template.ert', '--open-timeout-s', 240,
                                '--calculation-timeout-s', 120, '--cancel-timeout-s', 15,
                                '--shutdown-timeout-s', 30, '--total-timeout-s', 600, '--format', 'json'])
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
        (project_dir / 'module.1s').write_bytes((HERE / 'inputs/form-module.1s').read_bytes())
        common = tomllib.loads((project_dir / 'project.toml').read_text(encoding='utf-8'))
        common['schema_version'] = 2
        common['platform'] = scenario
        expected = read(HERE / 'expected.json')
        verify_test = next(t for t in scenario['tests'] if t['command'] == 'verify')
        assert json.loads(verify_test['expect_json']) == expected
        assert '.Провести(' not in scenario['parameters']['fixture_setup'] and 'fixture_post' not in scenario['parameters']
        platform_hash = hashlib.sha256(json.dumps(scenario, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        evidence['unchanged_test'] = {'platform_sha256': platform_hash, 'module': digest(project_dir / 'module.1s'),
                                      'template': digest(project_dir / 'template.ert'), 'expected': digest(HERE / 'expected.json')}
        phases = ('baseline', 'regression', 'fixed', 'repeat-fixed', 'invalid-json', 'empty-json', 'recovered')
        profiles = {}
        for name in phases:
            source = broken if name == 'regression' else fixed
            configuration = project_dir / ('configuration-' + name)
            target = configuration / POSTING
            target.parent.mkdir(parents=True)
            target.write_bytes(source.encode('utf-8'))
            (configuration / 'modules.json').write_bytes((out / 'extraction/modules.json').read_bytes())
            project = json.loads(json.dumps(common))
            project['configuration']['modules'] = configuration.as_posix()
            if name in ('invalid-json', 'empty-json'):
                project['platform']['parameters']['fixture_verify'] = 'Возврат "{";' if name == 'invalid-json' else 'Возврат "";'
            else:
                assert project['platform'] == scenario
            profile = project_dir / (name + '.toml')
            profile.write_text('\n'.join(json.dumps(k) + ' = ' + toml_value(v) for k, v in project.items()) + '\n', encoding='utf-8')
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
            doctor = execute('doctor-' + name, ['doctor', '--project', profile, '--stand', stand,
                                                '--output-root', out / 'future', '--format', 'json'])
            assert doctor['status'] == 'ready' and not doctor['launch_performed'] and not (out / 'future').exists()
            preserved()

        manifests = {}
        for name, cases in [('regression', phases[:4]), ('invalid-results', phases[4:]), ('success', ('fixed',))]:
            path = out / (name + '.toml')
            text = 'schema_version=1\n[suite]\nid="application097-' + name + '"\n'
            for case in cases:
                text += '\n[[scenarios]]\nid=' + json.dumps(case) + '\nproject=' + json.dumps(profiles[case].as_posix()) + '\n'
            path.write_text(text, encoding='utf-8')
            manifests[name] = path
        frozen = {str(p): digest(p) for p in (*profiles.values(), *manifests.values(), project_dir / 'module.1s', project_dir / 'template.ert')}
        for transport in ('cli', 'mcp'):
            if transport == 'mcp':
                client = Client(working, out / 'mcp-traffic.json', env)
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
