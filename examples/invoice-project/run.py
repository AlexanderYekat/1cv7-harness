"""Tasks 100/101: native invoice baseline, controlled defect, repair and repeat."""
import argparse
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

from verify import digest, read, write, toml_value, registry_tree, md_difference, verify_run, verify_suite, verify_caption_control
from mcp_client import Client

HERE = Path(__file__).resolve().parent
MODULE = 'Документ/СчетФактура/Форма.1s'
PHASES = ('baseline', 'regression', 'fixed', 'repeat-fixed')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    import harness77
    from harness77 import basecopy77, native_runtime77 as runtime
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    assert not os.environ.get('PYTHONPATH') and not os.environ.get('PYTHONHOME')
    assert Path(harness77.__file__).resolve().is_relative_to(HERE / '.harness77')
    assert (HERE / 'harness77.txt').read_bytes() == b''
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stand = tomllib.loads((HERE / 'stand.toml').read_text(encoding='utf-8'))['stand']
    base, copy = Path(stand['base']['path']), Path(stand['base']['copy_path'])
    lock = basecopy77.lock_path(copy)
    guard = lock.with_name(lock.name + '.guard')
    inspector = WindowsInspector()
    frozen = {str(p): digest(p) for p in HERE.iterdir() if p.is_file()}
    for directory in ('configuration', 'dependencies'):
        frozen.update({str(p): digest(p) for p in (HERE / directory).rglob('*') if p.is_file()})
    def snapshot():
        return {'source_listing': basecopy77.listing(base),
                'source_hashes': {n: digest(base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                'registry': {key: registry_tree(key) for key in (TITLES, *COM_KEYS)},
                'processes': inspector.processes(), 'copy': copy.exists(), 'lock': lock.exists(),
                'guard': digest(guard) if guard.exists() else None}
    before = snapshot()
    assert not before['copy'] and not before['lock']
    record = {'status': 'running', 'environment': {'python': sys.executable, 'module': harness77.__file__,
              'cwd': str(out)}, 'before': before, 'inputs': frozen, 'commands': [], 'plans': {}, 'runs': [], 'suites': []}
    launcher = HERE / '.harness77/launch.py'
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    def save():
        write(out / 'verified.json', record)
    def execute(name, args, code=0):
        argv = [sys.executable, '-I', '-B', str(launcher), *map(str, args)]
        r = subprocess.run(argv, cwd=out, env=env, capture_output=True, timeout=1800)
        (out / (name + '.stdout.json')).write_bytes(r.stdout)
        (out / (name + '.stderr.log')).write_bytes(r.stderr)
        record['commands'].append({'name': name, 'argv': argv, 'exit_code': r.returncode})
        save()
        assert r.returncode == code, (name, r.returncode, r.stdout[-3000:], r.stderr[-3000:])
        return json.loads(r.stdout if r.stdout.strip() else r.stderr)
    def preserved():
        # Remove only our newly created empty guard, once the runtime has released its lock.
        if before['guard'] is None and not copy.exists() and not lock.exists() and not inspector.processes():
            guard.unlink(missing_ok=True)
        assert snapshot() == before, 'source, registry, foreign sessions or copy cleanup changed'
        assert all(digest(Path(n)) == h for n, h in frozen.items()), 'project input changed'
    client = None
    try:
        record['status_before'] = execute('status', ['status', '--format', 'json'])
        record['doctor'] = execute('doctor', ['doctor', '--output-root', out / 'future', '--format', 'json'])
        assert record['doctor']['status'] == 'ready' and not record['doctor']['launch_performed']
        preserved()
        execute('extract', ['md-extract', base / '1Cv7.MD', '--output', out / 'extraction'])
        index = read(out / 'extraction/modules.json')
        target, = [m['path'] for m in index['modules'] if m['file'] == MODULE]
        original = (out / 'extraction' / MODULE).read_bytes().decode('utf-8')
        correct = 'ИначеЕсли (ИмяРеквизита = "Количество") или (ИмяРеквизита = "Цена") Тогда\n\t\tСумма = Окр(?(Количество=0,1,Количество)*Цена,2,1);'
        if '\r\n' in original:
            correct = correct.replace('\n', '\r\n')
        broken_line = correct.replace('*Цена,2,1);', '*Цена,2,1) + 1;')
        assert original.count(correct) == 1
        broken = original.replace(correct, broken_line)
        fixed = broken.replace(broken_line, correct)
        assert fixed == original
        sources = out / 'sources'
        sources.mkdir()
        for phase, text in [('baseline', original), ('regression', broken), ('fixed', fixed)]:
            (sources / (phase + '.1s')).write_bytes(text.encode('utf-8'))
        for name, old, new in [('regression', original, broken), ('repair', broken, fixed)]:
            (sources / (name + '.diff')).write_bytes(''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                fromfile=MODULE, tofile=MODULE)).encode('utf-8'))
        common = tomllib.loads((HERE / 'project.toml').read_text(encoding='utf-8'))
        file_mode = 'fixture_setup_file' in common['platform']['parameters']
        json_mode = 'steps_file' in common['platform']['parameters']
        for role in ('fixture_setup', 'fixture_verify'):
            key = role + '_file'
            if key in common['platform']['parameters']:
                common['platform']['parameters'][key] = str((HERE / common['platform']['parameters'][key]).resolve())
        if json_mode:
            common['platform']['parameters']['steps_file'] = str((HERE / common['platform']['parameters']['steps_file']).resolve())
            for test in common['platform']['tests']:
                if 'expect_json_file' in test:
                    test['expect_json_file'] = str((HERE / test['expect_json_file']).resolve())
        phases = (*PHASES, 'inline101', 'files102') if json_mode else (*PHASES, 'inline101') if file_mode else PHASES
        for field in ('template', 'source'):
            common['build'][field] = str(HERE / common['build'][field])
        profiles = {}
        for phase in phases:
            configuration = out / 'configurations' / phase
            module = configuration / MODULE
            module.parent.mkdir(parents=True)
            source = broken if phase == 'regression' else original
            module.write_bytes(source.encode('utf-8'))
            (configuration / 'modules.json').write_bytes((out / 'extraction/modules.json').read_bytes())
            profile = json.loads(json.dumps(common))
            if phase == 'inline101':
                profile['schema_version'] = 2
                for role in ('fixture_setup', 'fixture_verify'):
                    path = Path(profile['platform']['parameters'].pop(role + '_file'))
                    profile['platform']['parameters'][role] = path.read_text(encoding='utf-8')
            if json_mode and phase in ('inline101', 'files102'):
                profile['schema_version'] = 2 if phase == 'inline101' else 3
                params = profile['platform']['parameters']
                params['steps'] = read(Path(params.pop('steps_file')))
                for test in profile['platform']['tests']:
                    if 'expect_json_file' in test:
                        test['expect_json'] = Path(test.pop('expect_json_file')).read_text(encoding='utf-8')
            profile['configuration']['modules'] = str(configuration)
            path = out / (phase + '.toml')
            path.write_text('\n'.join(json.dumps(k) + '=' + toml_value(v) for k, v in profile.items()) + '\n', encoding='utf-8')
            profiles[phase] = path
            planned = out / (phase + '.MD')
            build = execute('build-' + phase, ['md-build', '--template', base / '1Cv7.MD', '--modules', configuration, '--output', planned])
            assert all(build['verification'].values()) and not build['changed_forms']
            audit = md_difference(base / '1Cv7.MD', planned, target, source)
            assert bool(audit['changed_streams']) == (phase == 'regression')
            record['plans'][phase] = {'project': str(path), 'project_sha256': digest(path), 'md_sha256': digest(planned), 'audit': audit}
        record['tests_sha256'] = digest(HERE / 'scenario.json')
        tests = [tomllib.loads(profiles[phase].read_text(encoding='utf-8'))['platform'] for phase in PHASES]
        assert all(t == common['platform'] for t in tests)
        if file_mode:
            from harness77.config77 import load_project
            assert load_project(profiles['baseline']).parameters == load_project(profiles['inline101']).parameters
            assert load_project(profiles['baseline']).tests == load_project(profiles['inline101']).tests
            if json_mode:
                assert load_project(profiles['baseline']).parameters == load_project(profiles['files102']).parameters
                assert load_project(profiles['baseline']).tests == load_project(profiles['files102']).tests
        save()
        for phase in phases:
            summary = execute('run-' + phase, ['run', '--project', profiles[phase], '--output-root', out / ('run-' + phase)],
                              code=1 if phase == 'regression' else 0)
            row = {'case': phase, 'folder': summary['run_dir'], 'summary': summary}
            row['verification'] = verify_run(Path(row['folder']), phase, record['plans'], read(HERE / 'expected.json'))
            record['runs'].append(row)
            preserved()
            save()
            print('run ' + phase + ': ' + summary['status'], flush=True)
        suite = out / 'cycle.toml'
        suite.write_text('schema_version=1\n[suite]\nid=' + json.dumps(common['project']['id'] + '-cycle') + '\n' + ''.join(
            '\n[[scenarios]]\nid=' + json.dumps(phase) + '\nproject=' + json.dumps(profiles[phase].as_posix()) + '\n'
            for phase in phases), encoding='utf-8')
        for transport in ('cli', 'mcp'):
            root = out / (transport + '-suite')
            if transport == 'cli':
                summary = execute('suite-cli', ['suite', '--suite', suite, '--suite-id', 'cycle', '--output-root', root], code=1)
            else:
                client = Client(out, out / 'mcp-traffic.json', env, command=[sys.executable, '-I', '-B', str(launcher), 'mcp'])
                response, progress = client.suite({'suite': str(suite), 'stand': str(HERE / 'stand.toml'),
                                                 'suite_id': 'cycle', 'output_root': str(root)})
                write(out / 'mcp-response.json', {'response': response, 'progress': progress})
                assert not response['isError'] and response['structuredContent']['exit_code'] == 1
                assert progress['ping_during'] and progress['ping_after']
                summary = response['structuredContent']['stdout']
            row = {'transport': transport, 'folder': summary['suite_dir'], 'summary': summary}
            row['verification'] = verify_suite(Path(row['folder']), record['plans'], read(HERE / 'expected.json'))
            record['suites'].append(row)
            preserved()
            save()
            print(transport + ' suite: verified expected regression', flush=True)
        record['mcp_exit_code'] = client.close()
        client = None
        assert record['mcp_exit_code'] == 0
        assert record['suites'][0]['verification'] == record['suites'][1]['verification']
        if common['platform']['parameters'].get('fixture_mode') == 'existing':
            record['caption_controls'] = []
            for case in ('wrong-open-caption', 'wrong-reopen-caption'):
                control = tomllib.loads(profiles['baseline'].read_text(encoding='utf-8'))
                parameters = control['platform']['parameters']
                if json_mode and case == 'wrong-reopen-caption':
                    steps = read(Path(parameters['steps_file']))
                    next(s for s in steps if 'reopen' in s)['caption_text'] = 'Нет такой подписи 101'
                    steps_path = out / 'wrong-reopen-steps.json'
                    write(steps_path, steps)
                    parameters['steps_file'] = str(steps_path)
                    # The separate control changes its own file, never the project's steps.
                    target = parameters
                else:
                    target = parameters if case == 'wrong-open-caption' else next(s for s in parameters['steps'] if 'reopen' in s)
                if not (json_mode and case == 'wrong-reopen-caption'):
                    target['caption_text'] = 'Нет такой подписи 101'
                profile = out / (case + '.toml')
                profile.write_text('\n'.join(json.dumps(k) + '=' + toml_value(v) for k, v in control.items()) + '\n', encoding='utf-8')
                summary = execute(case, ['run', '--project', profile, '--output-root', out / case], code=1)
                row = {'case': case, 'folder': summary['run_dir'], 'summary': summary}
                row['verification'] = verify_caption_control(Path(row['folder']), case, read(HERE / 'expected.json'))
                record['caption_controls'].append(row)
                preserved()
                save()
                print(case + ': verified failure', flush=True)
        if file_mode:
            from file_checks import qualify_files
            qualify_files(HERE, out, profiles['baseline'], record, execute, env, preserved, save)
        if json_mode:
            from json_checks import qualify_json
            qualify_json(HERE, out, profiles['baseline'], record, execute, env, preserved, save)
        preserved()
        record['after'] = snapshot()
        record['unchanged_tests'] = True
        record['status'] = 'passed'
        save()
    except BaseException as e:
        record['status'] = 'error'
        record['error'] = repr(e)
        save()
        raise
    finally:
        if client is not None:
            client.close()


if __name__ == '__main__':
    main()
