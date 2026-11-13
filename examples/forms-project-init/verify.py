"""098: independently re-read generated projects and every native run/suite."""
import argparse
import json
from pathlib import Path
import tomllib

from suite_verify import read, digest, verify, normalized, check
from harness77.config77 import load_project

HERE = Path(__file__).resolve().parent
LIMITS = dict(open_timeout_s=240, calculation_timeout_s=120, cancel_timeout_s=15,
              shutdown_timeout_s=30, total_timeout_s=600)


def creation(row):
    report = row['report']
    assert report['status'] == 'created' and report['exit_code'] == 0 and report['runtime'] == 'forms'
    assert report['platform_checked'] is False and report['launch_performed'] is False
    folder = Path(report['directory'])
    assert Path(report['project']) == folder / 'project.toml'
    assert set(report['files']) == {'project.toml', 'template.ert', 'module.1s', 'scenario.json'}
    assert report['directories'] == ['configuration'] and (folder / 'configuration').is_dir()
    for name, evidence in report['files'].items():
        path = folder / name
        assert digest(path) == evidence['sha256'] and path.stat().st_size == evidence['size_bytes']
    inputs = {str(HERE / 'inputs/template.ert'), str(HERE / 'inputs/form-module.1s'), row['scenario']}
    assert {item['path'] for item in report['inputs']} == inputs
    for item in report['inputs']:
        path = Path(item['path'])
        assert digest(path) == item['sha256'] and path.stat().st_size == item['size_bytes']
    assert report['template']['sha256'] == digest(HERE / 'inputs/template.ert')
    assert (folder / 'template.ert').read_bytes() == (HERE / 'inputs/template.ert').read_bytes()
    assert (folder / 'module.1s').read_bytes() == (HERE / 'inputs/form-module.1s').read_bytes()
    assert (folder / 'scenario.json').read_bytes() == Path(row['scenario']).read_bytes()
    data = tomllib.loads((folder / 'project.toml').read_text(encoding='utf-8'))
    assert data['schema_version'] == 2
    assert data['project']['id'] == 'application098-' + row['case']
    assert data['build'] == {'template': 'template.ert', 'source': 'module.1s', 'encoding': 'utf-8'}
    assert data['configuration'] == {'modules': 'configuration'} and data['deadlines'] == LIMITS
    scenario = read(Path(row['scenario']))
    assert data['platform'] == scenario
    original = read(HERE / 'inputs/scenario.json')
    if row['case'] in ('invalid-json', 'empty-json'):
        original['parameters']['fixture_verify'] = 'Возврат "{";' if row['case'] == 'invalid-json' else 'Возврат "";'
    assert scenario == original
    loaded = load_project(folder / 'project.toml')
    assert loaded.configuration == folder / 'configuration' and loaded.parameters == scenario['parameters']
    return {'case': row['case'], 'project_sha256': digest(folder / 'project.toml'), 'unchanged': True}


def direct_run(row, plans, expected):
    name = row['case']
    folder = Path(row['folder'])
    run_file = folder / 'run.json'
    child, platform = read(run_file), read(folder / 'platform-result.json')
    status = 'failed' if name == 'regression' else 'passed'
    assert child['status'] == row['summary']['status'] == status and child['platform_checked']
    assert child['exit_code'] == row['summary']['exit_code'] == (1 if name == 'regression' else 0)
    assert child['run_id'] == row['summary']['run_id'] == folder.name
    assert digest(folder / 'configuration/1Cv7.MD') == plans[name]['md_sha256']
    raw = next(op['value'] for op in platform['operations'] if op['name'] == 'verify')
    audit = check(folder, 'wrong' if name == 'regression' else 'success', digest(run_file),
                  readback=raw, expected_md_hash=plans[name]['md_sha256'])
    assert not audit['issues'], audit
    tests = next(s for s in child['stages'] if s['stage'] == 'tests')['tests']
    assert all(t['expectation_met'] for t in tests if t['name'] != 'persisted-document-and-entries')
    test = next(t for t in tests if t['name'] == 'persisted-document-and-entries')
    comparison = test['structured']
    assert comparison['status'] == status
    captured = comparison['result']
    assert captured['run_id'] == child['run_id'] and captured['operation'] == 'verify'
    path = folder / captured['path']
    assert path.resolve().parent == (folder / 'structured').resolve()
    assert path.read_bytes() == raw.encode('utf-8') and digest(path) == captured['sha256']
    assert path.stat().st_size == captured['size_bytes'] and captured in child['result_files']
    wanted = json.loads(json.dumps(expected))
    if name == 'regression':
        wanted['entries'][0]['amount'], wanted['entries'][1]['amount'] = '10', '20'
        assert comparison['difference_count'] == 2 and not comparison['differences_truncated']
        assert [(d['path'], d['label'], d['expected'], d['actual'], d['expected_type'], d['actual_type'])
                for d in comparison['differences']] == [
                    ('/entries/0/amount', 'Проводка 1, сумма', '30', '10', 'string', 'string'),
                    ('/entries/1/amount', 'Проводка 2, сумма', '40', '20', 'string', 'string')]
        assert comparison['diagnostics'] == comparison['differences']
        assert all(d['message'] in child['reason'] for d in comparison['differences'])
    else:
        assert comparison['difference_count'] == 0 and comparison['diagnostics'] == []
    assert json.loads(raw) == wanted
    startup = read(folder / 'native/startup.json')
    assert startup == platform['open']['startup'] and startup['status'] == 'ready'
    assert [e['stage'] for e in startup['events']].count('initialize_finished') == 1
    assert (folder / 'native/client.vbs').read_text(encoding='utf-16').count('result = v.Initialize(') == 1
    assert platform['shutdown']['forced_cleanup'] is False
    return {'case': name, 'status': status, 'report_sha256': digest(run_file), 'raw_sha256': digest(path), 'audit': audit}


def verify_output(out):
    record = read(out / 'verified.json')
    assert record['status'] == 'passed' and all(record['unchanged'].values())
    assert record['mcp_exit_code'] == 0 and record['cli_mcp_equal']
    expected = read(HERE / 'expected.json')
    manifest = read(HERE / 'kit.json')
    assert digest(HERE / 'kit.json') == record['kit_sha256']
    assert all(digest(HERE / n) == sha for n, sha in manifest['files'].items())
    assert len(record['created']) == 7 and len(record['runs']) == 3 and len(record['suites']) == 5
    created = [creation(row) for row in record['created']]
    runs = []
    for row in record['runs']:
        result = direct_run(row, record['plans'], expected)
        assert result == row['verification']
        runs.append(result)
    suites = []
    for group in record['suites']:
        result = verify(Path(group['folder']), record['plans'], expected)
        assert result == group['verification']
        suites.append(result)
    for name in ('regression', 'invalid-results'):
        a, b = [result for group, result in zip(record['suites'], suites) if group['manifest'] == name]
        assert normalized(a) == normalized(b)
    return {'status': 'passed', 'created': created, 'runs': len(runs),
            'suites': len(suites), 'native_runs': len(runs) + sum(len(s['scenarios']) for s in suites)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_output(args.output.resolve()), ensure_ascii=False, indent=2))
