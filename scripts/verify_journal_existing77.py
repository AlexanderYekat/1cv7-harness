"""Independently verify task 035 keyboard search, exact references and three persisted documents."""
import argparse
import json
from pathlib import Path
import re
import tomllib

from verify_document_form77 import ROOT, digest, read, check as document_check
from verify_journal_document77 import excluded
from verify_suite77 import verify as verify_suite


def expected_values():
    # Expectations are fixed in the versioned scenario, never inferred from a run.
    data = tomllib.loads((ROOT / 'examples/journal-existing/scenario.toml').read_text(encoding='utf-8'))
    changed = data['platform']['tests'][-1]['expect_value']
    initial = changed.replace('Harness77 журнал 035 изменён|2|3:10:30;2:20:40;|1|2|43>40:3:30;',
                              'Harness77 журнал 035 2|2|1:10:10;2:20:40;|1|2|43>40:1:10;')
    return initial, changed


def step_issues(records, kind):
    issues = []
    def require(ok, message):
        if not ok:
            issues.append(message)
    searches = [r for r in records if r.get('kind') == 'find_document']
    require(len(searches) == 1 and records[0] is searches[0], 'search must start in journal exactly once')
    if len(searches) != 1:
        return issues
    search = searches[0]
    rows = search.get('search') or []
    calls = search.get('calls') or []
    expected_calls = len(rows) + (0 if kind == 'wrong-limit' else 1)
    require(len(calls) == expected_calls, 'search calls do not match its navigation/opening')
    require(bool(rows) and len(rows) <= search.get('limit', 100), 'search is empty or exceeds its bound')
    for index, row in enumerate(rows):
        action, trip = row.get('action', {}), row.get('round_trip', {})
        call = calls[index] if index < len(calls) else {}
        require(call.get('number') == -101000 - index
                and {k: v for k, v in call.items() if k != 'number'} == trip,
                'cursor inspection differs from the independently checked raw call')
        require(action.get('key') == ('End' if index == 0 else 'Up') and action.get('id') == 4151
                and action.get('returned') is True and action.get('identity_rechecked') is True,
                'search lacks owned keyboard navigation')
        require(trip.get('returned') is True and trip.get('complete') is True and not trip.get('diagnostics')
                and not trip.get('journal_error') and 'journal_current' in trip, 'search cursor was not read')
        require(trip.get('journal_match') == ('1' if index == len(rows) - 1 and kind != 'wrong-limit' else '0'),
                'opened without the first exact reference match')
    if kind == 'wrong-limit':
        require(len(rows) == 1 and not search.get('action') and search.get('status') == 'failed'
                and 'search limit' in (search.get('issue') or '') and len(records) == 1,
                'bounded failed search opened/changed a document')
        return issues
    require(len(rows) >= 2, 'no neighboring document was skipped')
    trip = search.get('round_trip', {})
    require(bool(calls) and calls[-1].get('number') == search['index']
            and {k: v for k, v in calls[-1].items() if k != 'number'} == trip,
            'opened context differs from the independently checked raw call')
    opened = search.get('opened_form', {})
    matched = rows[-1] if rows else {}
    require(search.get('status') == 'passed' and search.get('existing_form_verified') is True
            and trip.get('journal_opened') == trip.get('journal_match') == '1'
            and bool(trip.get('journal_reference')) and not trip.get('journal_error')
            and trip.get('journal_reference') == matched.get('round_trip', {}).get('journal_current')
            and str(trip.get('journal_hwnd')) in [str(w['hwnd']) for w in opened.get('chain', [])[:2]],
            'opened saved reference/window not independently matched')
    action = search.get('action', {})
    require(action.get('key') == 'Enter' and action.get('id') == 4151 and action.get('returned') is True
            and action.get('identity_rechecked') is True, 'document not opened with owned journal Enter')
    require(all(r.get('status') == 'passed' for r in records), 'scenario step failed')
    clicks = [r.get('target') for r in records if r.get('kind') == 'click']
    dialogs = [r for r in records if r.get('kind') == 'dialog']
    if kind == 'cancel':
        closing = [r for r in records if r.get('kind') == 'close_form']
        opened_chain = opened.get('chain') or []
        frame = opened_chain[1] if len(opened_chain) > 1 else {}
        require(not clicks and len(closing) == 1 and closing[0].get('action', {}).get('message') == 'WM_CLOSE'
                and closing[0].get('action', {}).get('identity_rechecked') is True
                and closing[0].get('action', {}).get('hwnd') == frame.get('hwnd')
                and len(dialogs) == 1
                and dialogs[0].get('target') == 'Сохранить Документ? (Документ будет перепроведен)' and dialogs[0].get('button') == 'Нет'
                and dialogs[0].get('closes') is True and dialogs[0].get('form_open') is False
                and dialogs[0].get('answer', {}).get('requested') is True,
                'cancel did not close through the native no-save answer')
    else:
        require(clicks == ['Записать', 'ОК'] and not dialogs, 'UI save/post order differs')
        saved = next((r for r in records if r.get('kind') == 'click' and r.get('target') == 'Записать'), {})
        require(any('проведен.' in message for message in saved.get('round_trip', {}).get('messages', [])),
                'UI save did not report reposting')
        reopen = [r for r in records if r.get('kind') == 'reopen']
        require(len(reopen) == 1 and reopen[0].get('closed_before_reopen') is True
                and reopen[0].get('round_trip', {}).get('reopen_same') == '1'
                and all(w.get('exists') is False for w in reopen[0].get('before_reopen', {}).get('windows', [])),
                'same-reference reopening/old window destruction missing')
        require(any(r.get('kind') == 'total' and r.get('text') == '70' and r['index'] > reopen[0]['index']
                    for r in records) if reopen else False, 'no total verification in reopened form')
    return issues


def check(folder, kind='success', expected_hash=None):
    initial, changed = expected_values()
    mapped = 'wrong-reopen' if kind == 'wrong-limit' else kind
    result = document_check(folder, mapped, expected_hash,
                            readback=initial if kind in ('cancel', 'wrong-limit') else changed,
                            step_validator=lambda records, _: step_issues(records, kind), allow_fixture_posting=True)
    result['kind'] = kind
    text = (folder / 'native/ert-controller.1s').read_text(encoding='utf-8')
    before, setup = text.split('Функция Harness77ПодготовитьДанные()', 1)
    remainder = before + setup.split('КонецФункции', 1)[1]
    if '.АктивизироватьОбъект(' in text or len(re.findall(r'ОткрытьФорму\(Объект77Данных,', remainder)) != (0 if kind in ('cancel',) else 1):
        result['issues'].append('journal cursor positioned or document opened directly before search')
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    checks = [e for e in events if e.get('kind') == 'ert' and e.get('name') == 'check']
    if len(checks) != 1 or checks[0]['value'].splitlines().count('fixture-initial:' + initial) != 1:
        result['issues'].append('independent pre-UI state of all three documents/entries differs')
    form = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    handles = [str(w['hwnd']) for w in form.get('chain', [])[:2]]
    for row in (form.get('steps') or [{}])[0].get('search', []):
        if str(row.get('round_trip', {}).get('journal_hwnd')) not in handles:
            result['issues'].append('search cursor belongs to another journal window')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, action='append', required=True)
    parser.add_argument('--blocked-run', type=Path)
    parser.add_argument('--excluded-run', type=Path, action='append', default=[])
    parser.add_argument('--test-log', type=Path, action='append', default=[])
    parser.add_argument('--excluded-test-log', type=Path, action='append', default=[])
    parser.add_argument('--regression-report', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows, suites, issues = [], [], []
    for folder in args.suite:
        suites.append(verify_suite(folder.resolve(), native=True))
        report = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))
        for row in report['scenarios']:
            kind = row['id'] if row['id'].startswith('wrong') or row['id'] == 'cancel' else 'success'
            rows.append(check((folder / row['report']['path']).parent, kind, row['report']['sha256']))
    blocked = None
    if args.blocked_run:
        path = args.blocked_run / 'run.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        valid = (report['status'] == 'blocked' and report['platform_checked'] is False
                 and 'verified base copy' in str(report['reason'])
                 and not (args.blocked_run / 'native/ert-events.jsonl').exists())
        if not valid:
            issues.append('no-copy guard not confirmed before 1C')
        blocked = {'run_id': report['run_id'], 'sha256': digest(path), 'verified': valid}
    attempts = [excluded(folder) for folder in args.excluded_run]
    logs, regressions = [], []
    for path in args.test_log:
        value = path.read_text(encoding='utf-8', errors='replace')
        if not value.rstrip().endswith(('OK', 'OK (skipped=3)')) or '\nRan ' not in value:
            issues.append(str(path) + ': tests did not pass')
        logs.append({'path': str(path), 'sha256': digest(path)})
    for path in args.regression_report:
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('status') != 'passed' or value.get('issues'):
            issues.append(str(path) + ': regression did not pass')
        regressions.append({'path': str(path), 'sha256': digest(path)})
    for item in rows + suites + attempts:
        issues += [str(item.get('run_id', item.get('suite_id'))) + ': ' + issue for issue in item['issues']]
    sources = ['research/forms/fixture77.py', 'research/forms/scenario77.py', 'research/forms/journal77.py',
               'research/forms/form_launcher77.py', 'research/forms/tests/test_journal_existing77.py',
               'examples/journal-existing/scenario.toml', 'examples/journal-existing/prepare.py',
               'scripts/verify_document_form77.py', 'scripts/verify_journal_existing77.py']
    result = {'schema_version': 1, 'status': 'failed' if issues else 'passed', 'issues': issues,
              'runs': rows, 'suites': suites, 'blocked_run': blocked, 'excluded_attempts': attempts,
              'test_logs': logs, 'regressions': regressions,
              'excluded_test_logs': [{'path': str(p), 'sha256': digest(p)} for p in args.excluded_test_log],
              'sources': {f: digest(ROOT / f) for f in sources}}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'status': result['status'], 'runs': len(rows), 'issues': issues}, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
