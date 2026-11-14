"""Independent tasks-100/101 audit of saved MD, native operations, JSON and JUnit."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib
import xml.etree.ElementTree as ET


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def toml_value(value):
    if isinstance(value, dict):
        return '{' + ', '.join(json.dumps(k) + '=' + toml_value(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ', '.join(map(toml_value, value)) + ']'
    return json.dumps(value, ensure_ascii=False)


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
    from harness77.ert_module import CompoundFile, decompress_module
    from harness77.lint77 import cfb_paths
    old, new = CompoundFile(before.read_bytes()), CompoundFile(after.read_bytes())
    paths = cfb_paths(old)
    assert paths == cfb_paths(new) and len(old.directory_entries) == len(new.directory_entries)
    changed = []
    for a, b in zip(old.directory_entries, new.directory_entries):
        end = 116 if a.object_type in (2, 5) else 128
        assert a.raw[:end] == b.raw[:end]
        if a.object_type != 2:
            continue
        if old.read_stream(a) != new.read_stream(b):
            changed.append(paths[a.entry_id])
        if paths.get(a.entry_id) == target_path:
            assert decompress_module(new.read_stream(b)) == expected_source.encode('cp1251')
    assert changed in ([], [target_path]), changed
    return {'changed_streams': changed, 'streams_checked': sum(e.object_type == 2 for e in old.directory_entries),
            'metadata_and_other_streams_unchanged': True}


def verify_run(folder, phase, plans, expected):
    run, platform = read(folder / 'run.json'), read(folder / 'platform-result.json')
    failed = phase == 'regression'
    status = 'failed' if failed else 'passed'
    assert run['status'] == status and run['exit_code'] == int(failed) and run['platform_checked']
    assert digest(folder / 'configuration/1Cv7.MD') == plans[phase]['md_sha256']
    assert digest(Path(plans[phase]['project'])) == plans[phase]['project_sha256']
    for item in run['inputs'].get('fixture_files', []):
        snapshot = next(f for f in run['result_files'] if f.get('role') == item['role'])
        assert snapshot['sha256'] == item['sha256'] and snapshot['sha256_matches'] and snapshot['complete']
        assert snapshot['size_bytes'] == item['size_bytes']
        assert digest(folder / snapshot['path']) == item['sha256']
        text = (folder / snapshot['path']).read_text(encoding='utf-8')
        assert run['inputs']['parameters'][item['role']] == text
    for item in run['inputs'].get('json_files', []):
        snapshot = next(f for f in run['result_files'] if f.get('role') == item['role'] and f.get('test_index') == item.get('test_index'))
        assert snapshot['complete'] and snapshot['sha256_matches'] and snapshot['sha256'] == item['sha256']
        assert digest(folder / snapshot['path']) == item['sha256']
        text = (folder / snapshot['path']).read_text(encoding='utf-8')
        if item['role'] == 'steps':
            assert json.loads(text) == run['inputs']['parameters']['steps']
        else:
            assert text == run['inputs']['tests'][item['test_index']]['expect_json']
    assert not run['cancelled'] and run['finished_at']
    tests = next(s for s in run['stages'] if s['stage'] == 'tests')['tests']
    assert next(t for t in tests if t['name'] == 'form-open')['expectation_met']
    ui = next(t for t in tests if t['name'] == 'invoice-ui')
    assert ui['expectation_met'] == (not failed)
    comparison = next(t for t in tests if t['name'] == 'persisted-invoice')['structured']
    operation = next(o for o in platform['operations'] if o['name'] == 'verify')
    assert operation['status'] == 'passed'
    raw = operation['value']
    wanted = json.loads(json.dumps(expected))
    if failed:
        wanted['amount'] = wanted['total'] = '141'
        wanted['rows'][1]['amount'] = wanted['rows'][1]['total'] = '91'
        assert comparison['difference_count'] == 4
        assert {d['path']: (d['expected'], d['actual']) for d in comparison['differences']} == {
            '/amount': ('140', '141'), '/total': ('140', '141'),
            '/rows/1/amount': ('90', '91'), '/rows/1/total': ('90', '91')}
        assert comparison['diagnostics'] == comparison['differences']
        # The concise reason contains the first two differences; the full four stay in diagnostics.
        assert run['reason'] == '; '.join(d['message'] for d in comparison['differences'][:2])
    else:
        assert comparison['difference_count'] == 0 and not comparison['diagnostics']
    assert json.loads(raw) == wanted
    result = comparison['result']
    captured = folder / result['path']
    assert captured.resolve().parent == (folder / 'structured').resolve()
    assert captured.read_bytes() == raw.encode('utf-8')
    assert digest(captured) == result['sha256'] and captured.stat().st_size == result['size_bytes']
    assert result['run_id'] == run['run_id'] and result['operation'] == 'verify'
    assert result in run['result_files'] and result['complete'] and result['sha256_matches']
    startup = read(folder / 'native/startup.json')
    assert startup == platform['open']['startup'] and startup['status'] == 'ready'
    assert [e['stage'] for e in startup['events']].count('initialize_finished') == 1
    assert platform['shutdown']['forced_cleanup'] is False
    # The save must precede amount assertions; persisted state is read by a fresh reader object.
    form = read(folder / 'form/form-window.json')
    steps = form['steps']
    assert steps and not form.get('error')
    saved = next(s for s in steps if s['kind'] == 'click')
    assert saved['status'] == 'passed' and saved['target'] == 'КнопкаЗаписать'
    parameters = tomllib.loads(Path(plans[phase]['project']).read_text(encoding='utf-8'))['platform']['parameters']
    direct = parameters.get('fixture_mode') == 'existing'
    if direct:
        assert 'journal_form' not in parameters
        assert not any(s['kind'].startswith('journal_') or s['kind'] == 'find_document' for s in steps)
        assert read(folder / 'form/form-source.json')['runtime_caption_expectations'] == {'кнПечать': 'Печать'}
        description = read(folder / 'form/description.json')
        button, = [c for c in description['controls'] if c.get('identifier') == 'кнПечать']
        assert button['class'] == 'BUTTON' and button['caption'] == 'Печать'
        checks = [s for s in steps if s['kind'] == 'check' and s['target'] == 'кнПечать']
        assert len(checks) == 2 and all(s['status'] == 'passed' and s['state']['text'] == 'Печать' for s in checks)
    else:
        opened = next(s for s in steps if s['kind'] == 'journal_children')
        assert opened['status'] == 'passed'
    if not failed:
        reopened = next(s for s in steps if s['kind'] == 'reopen')
        assert reopened['round_trip']['reopen_same'] == '1' and reopened['closed_before_reopen']
        if direct:
            assert reopened['runtime_caption_expectations'] == {'кнПечать': 'Печать'}
    issues = [s for s in steps if s.get('issue') or s.get('status') != 'passed']
    if failed:
        bad_value = next(s for s in issues if s['kind'] == 'value' and s['target'] == 'Сумма')
        assert bad_value['index'] > saved['index']
        assert bad_value['round_trip']['value'] == '91', issues
    else:
        assert not issues and len(steps) == (25 if direct else 26), issues
    return {'case': phase, 'status': status, 'raw_sha256': digest(captured),
            'md_sha256': plans[phase]['md_sha256'], 'differences': comparison.get('differences', [])}


def verify_caption_control(folder, case, expected):
    run, platform = read(folder / 'run.json'), read(folder / 'platform-result.json')
    assert run['status'] == 'failed' and run['exit_code'] == 1 and run['platform_checked'] and not run['cancelled']
    assert not platform['shutdown']['forced_cleanup']
    tests = next(s for s in run['stages'] if s['stage'] == 'tests')['tests']
    assert {t['name'] for t in tests if not t['expectation_met']} == ({'form-open'} if case == 'wrong-open-caption' else {'invoice-ui'})
    raw = next(o['value'] for o in platform['operations'] if o['name'] == 'verify')
    assert json.loads(raw) == expected
    if case == 'wrong-open-caption':
        issues = next(o['form_issues'] for o in platform['operations'] if o['name'] == 'open')
        assert len(issues) == 1 and "shows 'Печать'" in issues[0] and 'Нет такой подписи 101' in issues[0]
    else:
        steps = read(folder / 'form/form-window.json')['steps']
        assert steps[-1]['kind'] == 'reopen' and steps[-1]['status'] == 'failed'
        assert "shows 'Печать'" in steps[-1]['issue'] and 'Нет такой подписи 101' in steps[-1]['issue']
        assert all(s['status'] == 'passed' for s in steps[:-1])
    return {'case': case, 'status': 'failed', 'reason': 'exact caption mismatch detected',
            'raw_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest()}


def verify_suite(folder, plans, expected):
    suite = read(folder / 'suite.json')
    assert suite['status'] == 'failed' and suite['exit_code'] == 1 and suite['complete'] and not suite['cancelled']
    cases = ET.parse(folder / 'junit.xml').getroot().findall('testsuite/testcase')
    phases = ['baseline', 'regression', 'fixed', 'repeat-fixed'] + (['inline101'] if 'inline101' in plans else []) + (['files102'] if 'files102' in plans else [])
    assert len(cases) == len(suite['scenarios']) == len(phases)
    results = []
    for row, case in zip(suite['scenarios'], cases):
        report = folder / row['report']['path']
        assert digest(report) == row['report']['sha256'] and report.stat().st_size == row['report']['size_bytes']
        child = read(report)
        result = verify_run(report.parent, row['id'], plans, expected)
        assert row['status'] == result['status'] and row['platform_checked']
        unmet = [t for t in next(s for s in child['stages'] if s['stage'] == 'tests')['tests'] if not t['expectation_met']]
        if row['id'] == 'regression':
            assert {t['name'] for t in unmet} == {'invoice-ui', 'persisted-invoice'}
            failure = case.find('failure')
            assert failure is not None and case.find('error') is None
            assert failure.get('message') == row['reason'] == child['reason']
            assert json.loads(failure.text) == row['problems']
            projected = next(t for problem in row['problems'] for t in problem.get('unmet_tests', []) if t['name'] == 'persisted-invoice')
            assert projected['structured']['diagnostics'] == next(t for t in unmet if t['name'] == 'persisted-invoice')['structured']['diagnostics']
        else:
            assert not unmet and not row['problems'] and case.find('failure') is None and case.find('error') is None
        results.append(result)
    assert [r['case'] for r in results] == phases
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    record = read(a.output / 'verified.json')
    assert record['status'] == 'passed' and record['unchanged_tests'] and record['before'] == record['after']
    assert record['mcp_exit_code'] == 0
    assert all(digest(Path(n)) == h for n, h in record['inputs'].items())
    expected = read(Path(__file__).with_name('expected.json'))
    assert len(record['runs']) == (6 if 'files102' in record['plans'] else 5 if 'inline101' in record['plans'] else 4) and len(record['suites']) == 2
    for row in record['runs']:
        assert verify_run(Path(row['folder']), row['case'], record['plans'], expected) == row['verification']
    for row in record['suites']:
        assert verify_suite(Path(row['folder']), record['plans'], expected) == row['verification']
    for row in record.get('caption_controls', []):
        assert verify_caption_control(Path(row['folder']), row['case'], expected) == row['verification']
    if 'file_edits' in record:
        from file_checks import verify_files
        verify_files(record, expected)
    if 'json_edits' in record:
        from json_checks import verify_json
        verify_json(record, expected)
    assert record['suites'][0]['verification'] == record['suites'][1]['verification']
    print(json.dumps({'status': 'passed', 'native_runs': len(record['runs']) + sum(len(s['verification']) for s in record['suites']) + len(record.get('caption_controls', [])) + len(record.get('file_edits', [])) + len(record.get('json_edits', [])), 'unchanged_tests': True,
                      'source_registry_and_foreign_sessions_preserved': True}, indent=2))


if __name__ == '__main__':
    main()
