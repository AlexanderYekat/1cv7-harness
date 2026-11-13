"""096: structured business differences and invalid-result diagnostics on the real stand."""
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
POSTING = 'Документ/ГотоваяПродукция/МодульДокумента.1s'
CORRECT = 'Операция.Сумма = Сумма;'
REGRESSION = 'Операция.Сумма = Стоимость;'
GOOD = '1|Harness77 форма 033|2|3:10:30;2:20:40;|1|2|43>40:3:30;43>40:2:40;'
BAD = '1|Harness77 форма 033|2|3:10:30;2:20:40;|1|2|43>40:3:10;43>40:2:20;'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def toml_value(value):
    if isinstance(value, dict):
        return '{ ' + ', '.join(json.dumps(k) + ' = ' + toml_value(v) for k, v in value.items()) + ' }'
    if isinstance(value, list):
        return '[' + ', '.join(map(toml_value, value)) + ']'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


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


def md_difference(before, after, target_path, expected_source):
    """Independently compare every stream, not just md-build's reported flags."""
    from harness77.ert_module import CompoundFile, decompress_module
    from harness77.lint77 import cfb_paths
    old, new = CompoundFile(before.read_bytes()), CompoundFile(after.read_bytes())
    old_paths, new_paths = cfb_paths(old), cfb_paths(new)
    assert old_paths == new_paths and len(old.directory_entries) == len(new.directory_entries)
    changed = []
    for a, b in zip(old.directory_entries, new.directory_entries):
        end = 116 if a.object_type in (2, 5) else 128
        assert a.raw[:end] == b.raw[:end], 'directory metadata changed'
        if a.object_type != 2:
            continue
        if old.read_stream(a) != new.read_stream(b):
            changed.append(old_paths[a.entry_id])
        if old_paths.get(a.entry_id) == target_path:
            assert decompress_module(new.read_stream(b)) == expected_source.encode('cp1251')
    assert changed in ([], [target_path]), changed
    return {'changed_streams': changed, 'streams_checked': sum(e.object_type == 2 for e in old.directory_entries),
            'metadata_and_other_streams_unchanged': True}


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
    manifest, inputs, scenario = read(HERE / 'kit.json'), read(HERE / 'inputs.json'), read(HERE / 'inputs/scenario.json')
    assert all(digest(HERE / n) == sha for n, sha in manifest['files'].items())
    assert not (HERE / 'native').exists() and not (HERE / 'launcher.py').exists()
    sys.path[:0] = [str(HERE / 'verification'), str(runtime.HERE / '_native/forms')]
    from verify_document_form77 import check, excluded, step_issues
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    working, builds, snapshots = out / 'working', out / 'builds', out / 'sources'
    for folder in (working, builds, snapshots):
        folder.mkdir()
    base, copy = Path(inputs['base']), Path(inputs['copy_path'])
    source_md = base / '1Cv7.MD'
    lock = basecopy77.lock_path(copy)
    guard = lock.with_name(lock.name + '.guard')
    guard_before = guard.read_bytes() if guard.exists() else None
    inspector = WindowsInspector()

    def snapshot():
        return {'source': basecopy77.listing(base),
                'hashes': {n: digest(base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                'registry': {key: registry_tree(key) for key in (TITLES, *COM_KEYS)}, 'processes': inspector.processes(),
                'copy': copy.exists(), 'lock': lock.exists(), 'guard': digest(guard) if guard.exists() else None,
                'kit': {n: digest(HERE / n) for n in manifest['files']}, 'runtime': runtime.inspect_runtime('forms')}

    before = snapshot()
    evidence = {'status': 'running', 'controlled_regression': True, 'structured_checks': True,
                'environment': {'python': sys.executable, 'module': harness77.__file__, 'cwd': str(working)},
                'kit_sha256': digest(HERE / 'kit.json'), 'baseline_processes': before['processes'],
                'phases': [], 'preparation': []}
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')

    def save():
        write_json(out / 'verified.json', evidence)

    def execute(name, command, expected=0):
        response = subprocess.run([sys.executable, '-B', '-m', 'harness77', *map(str, command)],
                                  cwd=working, env=env, capture_output=True, timeout=1200)
        (out / (name + '.log')).write_bytes(response.stdout + response.stderr)
        assert response.returncode == expected, (name, response.returncode)
        return json.loads(response.stdout)

    try:
        assert not before['copy'] and not before['lock']
        assert all(before['registry'][key] is None for key in COM_KEYS)
        stand = out / 'stand.toml'
        command = ['stand-init', '--output', stand, '--name', 'structured096', '--runtime', 'forms', '--format', 'json',
                   '--exe', inputs['exe'], '--cdb', inputs['cdb'], '--helper', HERE / 'dependencies/helper.dll',
                   '--identity', HERE / 'dependencies/identity.dll', '--base', base, '--copy-path', copy, '--user', inputs['user']]
        for name in inputs['copy_exclude']:
            command += ['--copy-exclude', name]
        created = execute('stand-init', command)
        assert not created['launch_performed'] and snapshot() == before
        project_dir = out / 'project'
        initialized = execute('project-init', ['project-init', '--directory', project_dir, '--id', 'structured096',
                              '--template', HERE / 'inputs/template.ert', '--open-timeout-s', 240,
                              '--calculation-timeout-s', 120, '--cancel-timeout-s', 15, '--shutdown-timeout-s', 30,
                              '--total-timeout-s', 600, '--format', 'json'])
        assert not initialized['launch_performed'] and snapshot() == before
        evidence['preparation'] = [created, initialized]
        extracted = execute('md-extract', ['md-extract', source_md, '--output', out / 'extraction'])
        index = read(out / 'extraction/modules.json')
        entries = [m for m in index['modules'] if m['file'] == POSTING]
        assert len(entries) == 1
        target_path = entries[0]['path']
        original = (out / 'extraction' / POSTING).read_bytes().decode('utf-8')
        assert original.count(CORRECT) == 1 and REGRESSION not in original
        broken = original.replace(CORRECT, REGRESSION)
        fixed = broken.replace(REGRESSION, CORRECT)
        assert fixed == original
        for name, text in [('baseline', original), ('regression', broken), ('fixed', fixed)]:
            (snapshots / (name + '.1s')).write_bytes(text.encode('utf-8'))
        for name, a, b in [('regression.diff', original, broken), ('repair.diff', broken, fixed)]:
            delta = ''.join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), fromfile=POSTING, tofile=POSTING))
            (snapshots / name).write_bytes(delta.encode('utf-8'))
        evidence['module'] = {'file': POSTING, 'path': target_path, 'extracted_modules': len(index['modules']),
                              'baseline_sha256': digest(snapshots / 'baseline.1s'),
                              'regression_sha256': digest(snapshots / 'regression.1s'),
                              'fixed_sha256': digest(snapshots / 'fixed.1s'),
                              'source_md_sha256': digest(source_md)}
        target = project_dir / 'configuration' / POSTING
        target.parent.mkdir(parents=True)
        (project_dir / 'configuration/modules.json').write_bytes((out / 'extraction/modules.json').read_bytes())
        (project_dir / 'module.1s').write_bytes((HERE / 'inputs/form-module.1s').read_bytes())
        import tomllib
        project_file = project_dir / 'project.toml'
        project = tomllib.loads(project_file.read_text(encoding='utf-8'))
        project['schema_version'] = 2
        project['platform'] = scenario
        expected = read(HERE / 'expected.json')
        verify_spec = next(t for t in scenario['tests'] if t['command'] == 'verify')
        assert json.loads(verify_spec['expect_json']) == expected and 'expect_value' not in verify_spec
        assert 'fixture_post' not in scenario['parameters'] and '.Провести(' not in scenario['parameters']['fixture_setup']
        project_file.write_text('\n'.join(json.dumps(k) + ' = ' + toml_value(v) for k, v in project.items()) + '\n', encoding='utf-8')
        project = load_project(project_file)
        test_hashes = {'profile': digest(project_file), 'module': digest(project.source),
                       'template': digest(project.template), 'scenario': digest(HERE / 'inputs/scenario.json')}
        evidence['unchanged_test'] = test_hashes
        for name, source in [('baseline', original), ('regression', broken), ('fixed', fixed), ('repeat-fixed', fixed),
                             ('invalid-json', fixed), ('empty-json', fixed)]:
            target.write_bytes(source.encode('utf-8'))
            planned = builds / (name + '.MD')
            built = execute('build-' + name, ['md-build', '--template', source_md, '--modules', project.configuration, '--output', planned])
            assert built['status'] == 'passed' and all(built['verification'].values())
            assert built['changed_forms'] == []
            assert [m['file'] for m in built['changed']] == ([POSTING] if name == 'regression' else [])
            audit = md_difference(source_md, planned, target_path, source)
            assert bool(audit['changed_streams']) is (name == 'regression')
            assert snapshot() == before
            phase_project = project_file
            negative = name in ('invalid-json', 'empty-json')
            if negative:
                altered = tomllib.loads(project_file.read_text(encoding='utf-8'))
                altered['platform']['parameters']['fixture_verify'] = 'Возврат "{";' if name == 'invalid-json' else 'Возврат "";'
                phase_project = project_dir / (name + '.toml')
                phase_project.write_text('\n'.join(json.dumps(k) + ' = ' + toml_value(v) for k, v in altered.items()) + '\n', encoding='utf-8')
            future = out / ('run-' + name)
            doctor = execute('doctor-' + name, ['doctor', '--project', phase_project, '--stand', stand,
                                               '--output-root', future, '--format', 'json'])
            assert doctor['status'] == 'ready' and not doctor['launch_performed'] and not future.exists()
            assert snapshot() == before
            execute('run-' + name, ['run', '--project', phase_project, '--stand', stand, '--output-root', future],
                    expected=2 if negative else 1 if name == 'regression' else 0)
            reports = list(future.glob('*/run.json'))
            assert len(reports) == 1
            folder = reports[0].parent
            assert digest(folder / 'configuration/1Cv7.MD') == digest(planned)
            platform = read(folder / 'platform-result.json')
            run_report = read(reports[0])
            raw = next(op for op in platform['operations'] if op['name'] == 'verify')['value']
            if not negative:
                actual = json.loads(raw)
                wanted = json.loads(json.dumps(expected))
                if name == 'regression':
                    wanted['entries'][0]['amount'], wanted['entries'][1]['amount'] = '10', '20'
                assert actual == wanted, actual
                verified = check(folder, 'wrong' if name == 'regression' else 'success', digest(reports[0]),
                                 readback=raw, expected_md_hash=digest(planned))
            else:
                verified = excluded(folder)
                assert raw == ('{' if name == 'invalid-json' else '')
                assert run_report['status'] == 'blocked' and run_report['exit_code'] == 2
                inspection = read(folder / 'form/form-window.json')
                assert not step_issues(inspection['steps'])
            assert not verified['issues'], verified
            row = next(t for stage in run_report['stages'] if stage['stage'] == 'tests'
                       for t in stage['tests'] if t['name'] == 'persisted-document-and-entries')
            comparison = row['structured']
            expected_status = 'blocked' if negative else 'failed' if name == 'regression' else 'passed'
            assert comparison['status'] == expected_status
            assert comparison['result']['run_id'] == run_report['run_id']
            assert comparison['result']['operation'] == 'verify'
            captured = folder / comparison['result']['path']
            assert captured.read_bytes() == raw.encode('utf-8')
            assert digest(captured) == comparison['result']['sha256']
            assert comparison['result'] in run_report['result_files']
            if name == 'regression':
                differences = comparison['differences']
                assert comparison['difference_count'] == 2 and not comparison['differences_truncated']
                assert [(d['path'], d['expected'], d['actual']) for d in differences] == [
                    ('/entries/0/amount', '30', '10'), ('/entries/1/amount', '40', '20')]
                assert all(d['code'] == 'value_mismatch' and d['message'] in run_report['reason'] for d in differences)
            elif negative:
                code = 'json_result_invalid' if name == 'invalid-json' else 'json_result_missing'
                assert comparison['diagnostics'][0]['code'] == code
                assert comparison['difference_count'] == 0
            else:
                assert comparison['difference_count'] == 0 and comparison['diagnostics'] == []
            provenance = read(folder / 'launcher-environment.json')
            assert provenance['module'] == harness77.__file__ and provenance['prefix'] == sys.prefix
            assert provenance['runtime'] == runtime.inspect_runtime('forms')
            trace = read(folder / 'native/startup.json')
            assert trace == platform['open']['startup'] and trace['status'] == 'ready'
            assert not platform['shutdown']['forced_cleanup']
            assert [e['stage'] for e in trace['events']].count('initialize_finished') == 1
            assert (folder / 'native/client.vbs').read_text(encoding='utf-16').count('result = v.Initialize(') == 1
            assert test_hashes == {'profile': digest(project_file), 'module': digest(project.source),
                                   'template': digest(project.template), 'scenario': digest(HERE / 'inputs/scenario.json')}
            evidence['phases'].append({'case': name, 'module_sha256': digest(target), 'md_sha256': digest(planned),
                                       'build': built, 'stream_audit': audit, 'doctor': doctor,
                                       'run': verified, 'comparison': comparison, 'startup': trace, 'environment': provenance})
            if guard_before is None and not inspector.processes() and not copy.exists() and not lock.exists():
                guard.unlink(missing_ok=True)
            assert snapshot() == before
            save()
            print(name + ': ' + verified['status'], flush=True)
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
    return 0 if evidence['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
