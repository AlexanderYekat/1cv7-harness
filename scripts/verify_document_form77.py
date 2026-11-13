"""Independently verify task 033 UI actions, saved data, raw step evidence and cleanup."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'research/forms'))
import scenario77
from verify_suite77 import verify as verify_suite

READBACK = '1|Harness77 форма 033|2|3:10:30;2:20:40;|1|2|43>40:3:30;43>40:2:40;'
BASE_MD_SHA256 = '931b26eb2e388ba3000196ab024351e65cb324e02e885dc4cef5be68059ecfa1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    data = path.read_bytes()
    return data.decode('utf-16' if data.startswith(b'\xff\xfe') else 'cp1251')


def step_issues(records, wrong_reopen=False, comment='Harness77 форма 033'):
    """Require actual UI save/post, a new owned inspection, field readbacks and final closing."""
    issues = []
    def require(condition, reason):
        if not condition:
            issues.append(reason)
    kinds = [r.get('kind') for r in records]
    reopen = [i for i, kind in enumerate(kinds) if kind == 'reopen']
    require(len(reopen) == 1, 'exactly one reopening required')
    if len(reopen) != 1:
        return issues
    index = reopen[0]
    prior, later = records[:index], records[index + 1:]
    require([r.get('target') for r in prior if r.get('kind') == 'click'] == ['Записать', 'ОК'],
            'save/OK actions missing or reordered')
    questions = [r for r in prior if r.get('kind') == 'dialog']
    require(len(questions) == 1 and questions[0].get('target') == 'Провести документ?'
            and questions[0].get('button') == 'Да' and questions[0].get('answer', {}).get('requested') is True,
            'posting confirmation not answered')
    opening = records[index]
    require(opening.get('closed_before_reopen') is True and opening.get('before_reopen', {}).get('open') is False,
            'first form not closed before reopening')
    require(bool(opening.get('before_reopen', {}).get('windows')) and all(
        w.get('exists') is False for w in opening.get('before_reopen', {}).get('windows', [])),
        'old form HWNDs were not destroyed')
    trip = opening.get('round_trip') or {}
    require(trip.get('reopen_return') == trip.get('reopen_same') == '1' and not trip.get('reopen_error'),
            'saved reference not confirmed on reopening')
    require(opening.get('form_open') is True and opening.get('reopened', {}).get('found') is True
            and opening.get('reopened', {}).get('units', {}).get('consistent') is True,
            'no matching owned form after reopening')
    require(all(r.get('status') == 'passed' and not r.get('issue') for r in records[:index + 1]),
            'an action before/during reopening failed')
    if wrong_reopen:
        require(len(later) == 1 and later[0].get('kind') == 'check' and later[0].get('status') == 'failed'
                and later[0].get('state', {}).get('text', '').strip() == comment,
                'negative reopened field check not demonstrated')
        return issues
    require(all(r.get('status') == 'passed' and not r.get('issue') for r in later), 'reopened checks failed')
    require(any(r.get('kind') == 'check' and r.get('target') == 'Комментарий'
                and r.get('state', {}).get('text', '').strip() == comment for r in later),
            'comment window not read after reopening')
    expected = {('Количество', 1): '3', ('Стоимость', 1): '10', ('Сумма', 1): '30',
                ('Количество', 2): '2', ('Стоимость', 2): '20', ('Сумма', 2): '40'}
    for (field, row), value in expected.items():
        matches = [r for r in later if r.get('kind') == 'value' and r.get('target') == field and r.get('row') == row]
        require(len(matches) == 1 and matches[0].get('round_trip', {}).get('value') == value,
                f'reopened row {row} {field} differs')
    require(any(r.get('kind') == 'rows' and r.get('round_trip', {}).get('rows') == 2 for r in later),
            'reopened row count not read')
    require(any(r.get('kind') == 'total' and r.get('round_trip', {}).get('total') == '70' for r in later),
            'reopened total not read')
    return issues


def check(folder, kind='success', expected_hash=None, readback=READBACK, step_validator=None, allow_fixture_posting=False,
          expected_md_hash=BASE_MD_SHA256):
    issues = []
    def require(condition, reason):
        if not condition:
            issues.append(reason)
    report = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    platform = json.loads((folder / 'platform-result.json').read_text(encoding='utf-8'))
    run_id = report['run_id']
    require(folder.name == run_id == platform['run_id'], 'foreign run identity')
    require(report['status'] == ('failed' if kind.startswith('wrong') else 'passed'), 'wrong run outcome')
    require(report['platform_checked'] is True, 'no native check')
    require(report.get('configuration', {}).get('sha256') == expected_md_hash, 'configuration hash differs from expected build')
    controller = (folder / 'native/ert-controller.1s').read_text(encoding='utf-8')
    checked_controller = controller
    if allow_fixture_posting:
        before, setup = controller.split('Функция Harness77ПодготовитьДанные()', 1)
        checked_controller = before + setup.split('КонецФункции', 1)[1]
    require('.Провести(' not in checked_controller and '.СделатьНеПроведенным(' not in checked_controller,
            'programmatic posting found in controller')
    if expected_hash:
        require(digest(folder / 'run.json') == expected_hash, 'run report changed')
    stage = next(s for s in report['stages'] if s['stage'] == 'platform_check')
    copy = stage.get('base_copy') or {}
    require(copy.get('source_check', {}).get('unchanged') is True, 'source preservation not confirmed')
    require(copy.get('removal', {}).get('removed') is True, 'copy removal not confirmed')
    require(copy.get('lock', {}).get('released') is True, 'copy lock not released')
    require(platform.get('base_list', {}).get('unchanged') is True, 'base list preservation not confirmed')
    shutdown = report.get('shutdown') or {}
    require(shutdown.get('cleanup_verified') is True and shutdown.get('others_preserved') is True,
            'session cleanup not confirmed')
    for item in report.get('result_files') or []:
        path = folder / item['path']
        if item.get('sha256'):
            require(path.is_file() and digest(path) == item['sha256'], 'result file differs: ' + item['path'])
    manifest = json.loads((folder / 'native/ert-manifest.json').read_text(encoding='utf-8'))
    require(manifest['commands'] == ['check', 'open', 'result', 'verify'], 'wrong operation order or programmatic posting')
    operations = platform['operations']
    require([o['name'] for o in operations] == manifest['commands'], 'operation list differs')
    ops = {o['name']: o for o in operations}
    require(all(ops.get(name, {}).get('status') == 'passed' for name in ('check', 'open', 'verify')), 'open/read failed')
    require(ops.get('result', {}).get('status') == ('failed' if kind == 'wrong-reopen' else 'passed'), 'wrong step outcome')
    require(ops.get('verify', {}).get('value') == readback, 'saved document/entries differ')
    inspection = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    require(inspection.get('run_id') == run_id, 'foreign form inspection')
    records = inspection.get('steps') or []
    require(records == ops.get('result', {}).get('steps'), 'watcher/result steps differ')
    issues += (step_validator(records, kind) if step_validator else step_issues(records, kind == 'wrong-reopen'))
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    responses = {number: [] for number in range(1, len(records) + 1)}
    for event in events:
        require(event.get('run_id') == run_id, 'foreign controller event')
        if event.get('kind') == 'ert':
            name = event['name']
            values = [e for e in events if e.get('kind') == 'ert' and e['name'] == name]
            require(len(values) == 1, name + ': duplicate controller response')
            protocol = read(folder / 'native' / manifest['protocol_paths'][name]).splitlines()
            require(protocol[:1] == ['HARNESS77-BEGIN:' + run_id + ':' + name]
                    and protocol[-1:] == ['HARNESS77-END:' + run_id + ':' + name], name + ': invalid protocol markers')
            if name == 'verify':
                require([v[len('fixture-value:'):] for v in event['value'].splitlines() if v.startswith('fixture-value:')]
                        == [readback], 'verify response differs')
            if name == 'result' and kind != 'cancel':
                require(event['value'].splitlines().count('closed:1') == 1, 'final controller closing not confirmed')
        elif event.get('kind') == 'phase' and event.get('name', '').startswith('step-') and event.get('value') == 'ok':
            number = int(event['name'][5:])
            responses.setdefault(number, []).append(event)
    for record in records:
        trips = record.get('calls') or record.get('round_trip', {}).get('calls')
        if not record.get('calls') and not record.get('round_trip'):
            continue  # an action pending in a modal dialog: its final dialog owns the calls
        if not isinstance(trips, list):
            trips = [dict(record.get('round_trip') or {}, number=record['index'])]
        for trip in trips:
            number = trip['number']
            require(len(responses.get(number, [])) == 1, f'step {number}: response event missing/duplicate')
            protocol = read(folder / 'native' / 'Протоколы проверки' / f'step-{number}.txt')
            messages, complete = scenario77.messages(protocol, f'{run_id}:step:{number}')
            require(complete and messages == trip.get('messages'), f'step {number}: protocol differs')
            answer = scenario77.answer(read(folder / 'native' / f'form-step-{number}-done'))
            require(all(trip.get(key) == value for key, value in answer.items()), f'step {number}: response differs')
            if record.get('kind') == 'reopen':
                if number == record['index']:
                    require(answer.get('reopen_close') == '1', 'raw closing response differs')
                else:
                    require(answer.get('reopen_return') == answer.get('reopen_same') == '1', 'raw reopening response differs')
    tests = next(s for s in report['stages'] if s['stage'] == 'tests')['tests']
    failed = [t['name'] for t in tests if not t['expectation_met']]
    require(failed == ({'wrong': ['persisted-document-and-entries'], 'wrong-reopen': ['scenario']}.get(kind, [])),
            'unexpected failed tests')
    return {'run_id': run_id, 'status': report['status'], 'kind': kind, 'steps': len(records),
            'readback': ops.get('verify', {}).get('value'), 'run_sha256': digest(folder / 'run.json'), 'issues': issues}


def excluded(folder):
    report = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    stage = next(s for s in report['stages'] if s['stage'] == 'platform_check')
    copy = stage.get('base_copy') or {}
    shutdown = report.get('shutdown') or {}
    verified = (copy.get('source_check', {}).get('unchanged') is True
                and copy.get('removal', {}).get('removed') is True
                and copy.get('lock', {}).get('released') is True
                and shutdown.get('cleanup_verified') is True and shutdown.get('others_preserved') is True
                and stage.get('base_list', {}).get('unchanged') is True)
    return {'run_id': report['run_id'], 'status': report['status'], 'reason': report['reason'],
            'run_sha256': digest(folder / 'run.json'), 'cleanup_verified': verified,
            'issues': [] if verified else ['excluded attempt cleanup not confirmed']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, action='append', required=True)
    parser.add_argument('--test-log', type=Path, action='append', default=[])
    parser.add_argument('--excluded-test-log', type=Path, action='append', default=[])
    parser.add_argument('--blocked-run', type=Path)
    parser.add_argument('--excluded-run', type=Path, action='append', default=[])
    parser.add_argument('--regression-report', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows, suites, issues, logs, regressions = [], [], [], [], []
    for folder in args.suite:
        suites.append(verify_suite(folder.resolve(), native=True))
        report = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))
        for row in report['scenarios']:
            kind = row['id'] if row['id'].startswith('wrong') else 'success'
            rows.append(check((folder / row['report']['path']).parent, kind, row['report']['sha256']))
    for path in args.test_log:
        value = path.read_text(encoding='utf-8', errors='replace')
        if not value.rstrip().endswith(('OK', 'OK (skipped=3)')) or '\nRan ' not in value:
            issues.append(str(path) + ': tests did not pass')
        logs.append({'path': str(path), 'sha256': digest(path)})
    attempts = [excluded(folder) for folder in args.excluded_run]
    blocked = None
    if args.blocked_run:
        path = args.blocked_run / 'run.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        valid = (report['status'] == 'blocked' and report['platform_checked'] is False
                 and 'verified base copy' in str(report['reason'])
                 and not (args.blocked_run / 'native/ert-events.jsonl').exists())
        if not valid:
            issues.append('no-copy guard not confirmed before native session')
        blocked = {'run_id': report['run_id'], 'sha256': digest(path), 'verified': valid}
    for path in args.regression_report:
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('status') != 'passed' or value.get('issues'):
            issues.append(str(path) + ': regression did not pass')
        regressions.append({'path': str(path), 'sha256': digest(path)})
    issues += [r['run_id'] + ': ' + i for r in rows for i in r['issues']]
    issues += [s['suite_id'] + ': ' + i for s in suites for i in s['issues']]
    issues += [r['run_id'] + ': ' + i for r in attempts for i in r['issues']]
    sources = ['research/forms/scenario77.py', 'research/forms/form_launcher77.py', 'research/forms/form_window77.py',
               'research/forms/tests/test_reopen77.py', 'examples/document-form-cycle/scenario.toml',
               'examples/document-form-cycle/prepare.py', 'scripts/verify_document_form77.py']
    result = {'schema_version': 1, 'status': 'failed' if issues else 'passed', 'issues': issues,
              'runs': rows, 'suites': suites, 'test_logs': logs, 'excluded_attempts': attempts,
              'excluded_test_logs': [{'path': str(p), 'sha256': digest(p)} for p in args.excluded_test_log],
              'blocked_run': blocked, 'regressions': regressions, 'sources': {f: digest(ROOT / f) for f in sources}}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'status': result['status'], 'runs': len(rows), 'issues': issues}, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
