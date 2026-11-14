"""102: real native edits without regeneration, negative inputs, and frozen snapshots."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib
import xml.etree.ElementTree as ET

from mcp_client import Client
from verify import read, write, digest, toml_value


def snapshot_check(folder, hashes):
    run = read(folder / 'run.json')
    assert {f['role']: f['sha256'] for f in run['inputs']['fixture_files']} == hashes
    for item in run['inputs']['fixture_files']:
        evidence = next(f for f in run['result_files'] if f.get('role') == item['role'])
        path = folder / evidence['path']
        assert digest(path) == evidence['sha256'] == item['sha256']
        assert evidence['sha256_matches'] and evidence['complete']
        assert path.stat().st_size == item['size_bytes'] == evidence['size_bytes']
        assert path.read_text(encoding='utf-8') == run['inputs']['parameters'][item['role']]


def edit_check(row, expected, md_hash):
    folder = Path(row['folder'])
    run, platform = read(folder / 'run.json'), read(folder / 'platform-result.json')
    failed = row['case'] != 'restored'
    assert run['status'] == ('failed' if failed else 'passed') and run['exit_code'] == int(failed)
    assert run['platform_checked'] and not platform['shutdown']['forced_cleanup']
    assert digest(folder / 'configuration/1Cv7.MD') == md_hash
    snapshot_check(folder, row['input_hashes'])
    wanted = json.loads(json.dumps(expected))
    if row['case'] == 'fixture-edit':
        wanted['comment_ok'] = 0
    elif row['case'] == 'reader-edit':
        wanted = {}
    raw = next(op['value'] for op in platform['operations'] if op['name'] == 'verify')
    assert json.loads(raw) == wanted
    tests = next(s for s in run['stages'] if s['stage'] == 'tests')['tests']
    assert all(t['expectation_met'] for t in tests if t['name'] != 'persisted-invoice')
    comparison = next(t for t in tests if t['name'] == 'persisted-invoice')['structured']
    assert comparison['status'] == ('failed' if failed else 'passed')
    if row['case'] == 'fixture-edit':
        assert [(d['path'], d['expected'], d['actual']) for d in comparison['differences']] == [('/comment_ok', 1, 0)]
    elif row['case'] == 'reader-edit':
        assert comparison['difference_count'] == len(expected)
        assert all(d['code'] == 'missing_field' for d in comparison['differences'])
    else:
        assert comparison['difference_count'] == 0
    if row.get('suite_folder'):
        suite = Path(row['suite_folder'])
        report = read(suite / 'suite.json')
        assert report['complete'] and report['status'] == run['status']
        child, = report['scenarios']
        assert digest(suite / child['report']['path']) == child['report']['sha256']
        case, = ET.parse(suite / 'junit.xml').getroot().findall('testsuite/testcase')
        assert (case.find('failure') is not None) == failed and case.find('error') is None
        if failed:
            assert json.loads(case.find('failure').text) == child['problems']
    return {'status': run['status'], 'differences': comparison['differences'],
            'raw_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest()}


def qualify_files(here, out, profile, record, execute, env, preserved, save):
    frozen_profile = digest(profile)
    baseline = tomllib.loads(profile.read_text(encoding='utf-8'))
    paths = {role: Path(baseline['platform']['parameters'][role + '_file'])
             for role in ('fixture_setup', 'fixture_verify')}
    assert all(p.resolve().parent == here and not p.is_symlink() for p in paths.values())
    original = {role: p.read_bytes() for role, p in paths.items()}
    client = Client(out, out / 'file-input-mcp-traffic.json', env,
                    command=[sys.executable, '-I', '-B', str(here / '.harness77/launch.py'), 'mcp'])
    record['file_negatives'], record['file_edits'] = [], []

    def manifest(name, selected):
        path = out / (name + '-suite.toml')
        path.write_text('schema_version=1\n[suite]\nid="file-probe"\n[[scenarios]]\nid="probe"\nproject=' +
                        json.dumps(selected.as_posix()) + '\n', encoding='utf-8')
        return path

    def call(transport, name, selected, code):
        root = out / name
        if transport == 'run':
            summary = execute(name, ['run', '--project', selected, '--output-root', root], code=code)
            return summary, None
        suite = manifest(name, selected)
        if transport == 'cli':
            summary = execute(name, ['suite', '--suite', suite, '--suite-id', 'probe', '--output-root', root], code=code)
        else:
            response, progress = client.suite({'suite': str(suite), 'stand': str(here / 'stand.toml'),
                'suite_id': 'probe', 'output_root': str(root)})
            write(out / (name + '-mcp.json'), {'response': response, 'progress': progress})
            assert response['structuredContent']['exit_code'] == code and response['isError'] == (code == 2)
            assert progress['ping_after']
            summary = response['structuredContent']['stdout']
        return summary, Path(summary['suite_dir'])

    try:
        for case in ('missing-file', 'inline-conflict', 'bad-encoding', 'unrepresentable', 'empty', 'old-schema', 'directory'):
            data = json.loads(json.dumps(baseline))
            params = data['platform']['parameters']
            if case == 'missing-file':
                params['fixture_verify_file'] = str(out / 'missing.1s')
            elif case == 'inline-conflict':
                params['fixture_verify'] = 'Возврат "{}";'
            elif case == 'old-schema':
                data['schema_version'] = 2
            elif case == 'directory':
                params['fixture_verify_file'] = str(out)
            else:
                payload = b'\xff' if case == 'bad-encoding' else '🙂'.encode('utf-8') if case == 'unrepresentable' else b'  \n'
                path = out / (case + '.1s')
                path.write_bytes(payload)
                params['fixture_verify_file'] = str(path)
            bad = out / (case + '.toml')
            bad.write_text('\n'.join(json.dumps(k) + '=' + toml_value(v) for k, v in data.items()) + '\n', encoding='utf-8')
            for transport in ('run', 'cli', 'mcp'):
                name = 'negative-' + transport + '-' + case
                summary, suite = call(transport, name, bad, 2)
                if suite:
                    report = read(suite / 'suite.json')
                    row, = report['scenarios']
                    assert report['complete'] and row['status'] == 'blocked' and row['report'] is None and not row['platform_checked']
                else:
                    assert not summary['platform_checked'] and not (out / name).exists()
                record['file_negatives'].append({'case': case, 'transport': transport, 'summary': summary, 'suite_folder': str(suite) if suite else None})
                preserved()
                save()
        expected = read(here / 'expected.json')
        for transport in ('run', 'cli', 'mcp'):
            for case in ('fixture-edit', 'reader-edit', 'restored'):
                for role, path in paths.items():
                    path.write_bytes(original[role])
                if case == 'fixture-edit':
                    text = original['fixture_setup'].decode('utf-8')
                    assert text.count('Harness77 счет-фактура 100') == 1
                    paths['fixture_setup'].write_bytes(text.replace('Harness77 счет-фактура 100', 'Правка файла 102').encode('utf-8'))
                elif case == 'reader-edit':
                    paths['fixture_verify'].write_bytes('Возврат "{}";\n'.encode('utf-8'))
                hashes = {role: digest(path) for role, path in paths.items()}
                try:
                    summary, suite = call(transport, 'edit-' + transport + '-' + case, profile, int(case != 'restored'))
                    folder = Path(summary['run_dir']) if suite is None else (suite / read(suite / 'suite.json')['scenarios'][0]['report']['path']).resolve().parent
                    row = {'transport': transport, 'case': case, 'folder': str(folder), 'suite_folder': str(suite) if suite else None, 'input_hashes': hashes}
                    row['verification'] = edit_check(row, expected, record['plans']['baseline']['md_sha256'])
                    record['file_edits'].append(row)
                    assert digest(profile) == frozen_profile
                finally:
                    for role, path in paths.items():
                        path.write_bytes(original[role])
                preserved()
                save()
                print(transport + ' ' + case + ': verified without regeneration', flush=True)
        record['file_input_mcp_exit_code'] = client.close()
        client = None
        assert record['file_input_mcp_exit_code'] == 0
    finally:
        for role, path in paths.items():
            path.write_bytes(original[role])
        if client is not None:
            client.close()


def verify_files(record, expected):
    assert len(record['file_negatives']) == 21 and len(record['file_edits']) == 9
    assert record['file_input_mcp_exit_code'] == 0
    for row in record['file_edits']:
        assert edit_check(row, expected, record['plans']['baseline']['md_sha256']) == row['verification']
    for row in record['file_negatives']:
        if row['suite_folder']:
            suite = read(Path(row['suite_folder']) / 'suite.json')
            child, = suite['scenarios']
            assert suite['status'] == 'blocked' and child['report'] is None and not child['platform_checked']
        else:
            assert row['summary']['status'] == 'blocked' and not row['summary']['platform_checked']
