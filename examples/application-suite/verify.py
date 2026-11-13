"""097: independent re-reading of native children, JSON, suite projections and JUnit."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'verification'))
from harness77.native_runtime77 import HERE as RUNTIME
sys.path.insert(0, str(RUNTIME / '_native/forms'))
from verify_document_form77 import check, excluded, step_issues
from verify_suite77 import verify as verify_suite


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def projection_issue(row, child, case):
    """Cross-check detailed suite/JUnit diagnostics against their child, including values."""
    stage = next(s for s in child['stages'] if s['stage'] == 'tests')
    unmet = [t for t in stage['tests'] if not t['expectation_met']]
    if unmet:
        assert len(unmet) == 1 and unmet[0]['name'] == 'persisted-document-and-entries'
        assert len(row['problems']) == 1 and row['problems'][0]['stage'] == 'tests'
        projected = row['problems'][0]['unmet_tests']
        assert len(projected) == 1 and projected[0]['name'] == unmet[0]['name']
        actual = unmet[0]['structured']
        assert projected[0]['structured'] == {key: actual[key] for key in
            ('status', 'difference_count', 'differences_truncated', 'result', 'diagnostics') if key in actual}
        tag = 'failure' if row['status'] == 'failed' else 'error'
        outcome = case.find(tag)
        assert outcome is not None and outcome.get('message') == row['reason']
        assert json.loads(outcome.text) == row['problems']
    else:
        assert not row['problems']
        assert case.find('failure') is None and case.find('error') is None


def verify(folder, plans, expected):
    verified = verify_suite(folder, native=True)
    assert not verified['issues'], verified
    suite = read(folder / 'suite.json')
    cases = ET.parse(folder / 'junit.xml').getroot().findall('testsuite/testcase')
    records = []
    for row, case in zip(suite['scenarios'], cases):
        name = row['id']
        plan = plans[name]
        run_file = folder / row['report']['path']
        child = read(run_file)
        run_dir = run_file.parent
        status = 'failed' if name == 'regression' else 'blocked' if name in ('invalid-json', 'empty-json') else 'passed'
        assert row['status'] == child['status'] == status
        assert child['exit_code'] == {'passed': 0, 'failed': 1, 'blocked': 2}[status]
        assert row['report']['size_bytes'] == run_file.stat().st_size
        assert digest(run_dir / 'configuration/1Cv7.MD') == plan['md_sha256']
        platform = read(run_dir / 'platform-result.json')
        operation = next(op for op in platform['operations'] if op['name'] == 'verify')
        assert operation['status'] == 'passed'
        raw = operation['value']
        result = (excluded(run_dir) if status == 'blocked' else
                  check(run_dir, 'wrong' if status == 'failed' else 'success', digest(run_file),
                        readback=raw, expected_md_hash=plan['md_sha256']))
        assert not result['issues'], result
        assert not step_issues(read(run_dir / 'form/form-window.json')['steps'])
        tests = next(s for s in child['stages'] if s['stage'] == 'tests')['tests']
        assert all(t['expectation_met'] for t in tests if t['name'] != 'persisted-document-and-entries')
        test = next(t for t in tests if t['name'] == 'persisted-document-and-entries')
        structured = test['structured']
        assert structured['status'] == status
        actual = structured['result']
        assert actual['run_id'] == child['run_id'] and actual['operation'] == 'verify'
        captured = run_dir / actual['path']
        assert captured.resolve().parent == (run_dir / 'structured').resolve()
        assert captured.read_bytes() == raw.encode('utf-8')
        assert digest(captured) == actual['sha256'] and captured.stat().st_size == actual['size_bytes']
        assert actual in child['result_files'] and actual['complete'] and actual['sha256_matches']
        if status == 'blocked':
            assert raw == ('{' if name == 'invalid-json' else '')
            code = 'json_result_invalid' if name == 'invalid-json' else 'json_result_missing'
            assert structured['diagnostics'][0]['code'] == code
            assert structured['difference_count'] == 0
        else:
            wanted = json.loads(json.dumps(expected))
            if status == 'failed':
                wanted['entries'][0]['amount'], wanted['entries'][1]['amount'] = '10', '20'
                differences = structured['differences']
                assert structured['difference_count'] == 2 and not structured['differences_truncated']
                assert [(d['path'], d['label'], d['expected'], d['actual']) for d in differences] == [
                    ('/entries/0/amount', 'Проводка 1, сумма', '30', '10'),
                    ('/entries/1/amount', 'Проводка 2, сумма', '40', '20')]
                assert all(d['code'] == 'value_mismatch' and d['expected_type'] == d['actual_type'] == 'string'
                           and d['message'] in row['reason'] for d in differences)
                assert structured['diagnostics'] == differences
            else:
                assert structured['difference_count'] == 0 and not structured['diagnostics']
            assert json.loads(raw) == wanted
        projection_issue(row, child, case)
        trace = read(run_dir / 'native/startup.json')
        assert trace == platform['open']['startup'] and trace['status'] == 'ready'
        assert [e['stage'] for e in trace['events']].count('initialize_finished') == 1
        assert (run_dir / 'native/client.vbs').read_text(encoding='utf-16').count('result = v.Initialize(') == 1
        assert platform['shutdown']['forced_cleanup'] is False
        records.append({'case': name, 'status': status, 'run_id': child['run_id'], 'report': str(run_file.resolve()),
                        'report_sha256': digest(run_file), 'md_sha256': plan['md_sha256'],
                        'raw_sha256': digest(captured), 'comparison': structured,
                        'run': result, 'startup': trace, 'environment': read(run_dir / 'launcher-environment.json')})
    return {'suite': verified, 'scenarios': records}


def normalized(result):
    return [{'case': row['case'], 'status': row['status'], 'md_sha256': row['md_sha256'], 'raw_sha256': row['raw_sha256'],
             'comparison': {k: v for k, v in row['comparison'].items() if k != 'result'}} for row in result['scenarios']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    record = read(out / 'verified.json')
    results = []
    for group in record['suites']:
        value = verify(Path(group['folder']), record['plans'], read(HERE / 'expected.json'))
        assert value == group['verification']
        results.append({'transport': group['transport'], 'manifest': group['manifest'], **value['suite']})
    print(json.dumps({'status': 'passed', 'suites': results}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
