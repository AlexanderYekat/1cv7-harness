"""Independently check task 037 UI command, cursor, raw calls and all persisted entries."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys
import tomllib

from verify_document_form77 import ROOT, digest, read, check as document_check
from verify_journal_document77 import excluded
from verify_suite77 import verify as verify_suite

sys.path.insert(0, str(ROOT / 'research/forms'))
import journal77
import scenario77


def expectations():
    data = tomllib.loads((ROOT / 'examples/journal-unpost/scenario.toml').read_text(encoding='utf-8'))
    unposted = data['platform']['tests'][-1]['expect_value']
    parts = unposted.split('#')
    parts[1] = parts[1].replace('0|Harness77', '1|Harness77', 1).replace('|1|0|', '|1|2|43>40:1:10;43>40:2:40;')
    return '#'.join(parts), unposted


def step_issues(records, kind, inspection, identity):
    issues = []
    def require(ok, message):
        if not ok:
            issues.append(message)
    initial, unposted = expectations()
    require([r.get('kind') for r in records[:2]] == ['journal_period', 'find_document'], 'period/search prefix missing')
    if len(records) < 2:
        return issues
    period, search = records[:2]
    for record in records:
        for key in ('period_window', 'edited_window', 'confirmation'):
            window = record.get(key)
            if window and (any(window.get(k) != identity[k] for k in ('pid', 'tid')) or any(
                    any(c.get(k) != identity[k] for k in ('pid', 'tid')) for c in window.get('children', []))):
                issues.append('dialog/field belongs to another process/thread')
    try:
        journal77.check_period(period, period)
        before, after = (journal77.read_period(period[key]) for key in ('before_period', 'after_period'))
        require(not before[0] <= date(2026, 8, 1) <= before[1] and after == (date(2026, 7, 31), date(2026, 8, 1)),
                'target inclusion/original period differs')
        fields = journal77.period_fields(period['edited_window'])
        require([f['text'] for f in fields] == ['31.07.26', '01.08.26'] and not period.get('cancel'), 'period dates were not entered')
        require(period.get('answer', {}).get('button', {}).get('id') == 1, 'period not confirmed with OK')
        require(len(period.get('inputs', [])) == 2 and all(i.get('typed') is True for i in period['inputs']), 'period input missing')
        calls = period.get('calls', [])
        require([c.get('number') for c in calls] == [-102002, -102003]
                and all({k: v for k, v in c.items() if k != 'number'} == period[key]
                        for c, key in zip(calls, ('before_period', 'after_period'))), 'period calls/readback differ')
    except (KeyError, ValueError, RuntimeError) as error:
        issues.append('period: ' + str(error))
    require(period.get('status') == 'passed', 'period step failed')
    require(period.get('action', {}).get('posted') is True and period['action'].get('command') == 0x8071, 'native period command missing')
    rows, calls = search.get('search', []), search.get('calls', [])
    require(search.get('open') is False and not search.get('action') and not search.get('opened_form'), 'search opened a document')
    require(calls == [dict(row.get('round_trip', {}), number=-101000 - i) for i, row in enumerate(rows)], 'cursor/raw calls differ')
    require(bool(rows) and len(rows) <= search.get('limit', 100), 'search missing or unbounded')
    handles = {str(w['hwnd']) for w in inspection.get('chain', [])[:2]}
    for i, row in enumerate(rows):
        action, trip = row.get('action', {}), row.get('round_trip', {})
        require(action.get('key') == ('End' if i == 0 else 'Up') and action.get('id') == 4151
                and action.get('returned') is True and action.get('identity_rechecked') is True, 'cursor key not owned/verified')
        require(trip.get('returned') is True and trip.get('complete') is True and not trip.get('diagnostics')
                and not trip.get('journal_error') and str(trip.get('journal_hwnd')) in handles and 'journal_current' in trip,
                'cursor response is incomplete or belongs to another journal')
        require(trip.get('journal_match') == ('1' if i == len(rows)-1 and kind != 'wrong-limit' else '0'), 'wrong selected reference')
    if kind == 'wrong-limit':
        require(len(records) == 2 and len(rows) == 1 and search.get('status') == 'failed'
                and 'search limit' in str(search.get('issue')), 'limited search sent a command or did not fail')
        return issues
    require(search.get('cursor_verified') is True and search.get('status') == 'passed' and len(rows) == 2
            and search.get('round_trip') == rows[-1].get('round_trip'), 'selected cursor proof missing')
    reference = rows[-1].get('round_trip', {}).get('journal_current') if rows else None
    actions = records[2:]
    require(len(actions) == (1 if kind == 'cancel' else 2), 'unpost/repeat step count differs')
    for i, record in enumerate(actions):
        require(record.get('kind') == 'journal_unpost' and record.get('status') == 'passed', 'unpost step failed/missing')
        before_value = initial if i == 0 else unposted
        after_value = initial if kind == 'cancel' else unposted
        try:
            before, after = record['before_unpost'], record['after_unpost']
            journal77.checked_cursor(before, inspection)
            journal77.checked_cursor(after, inspection)
            require(before['journal_current'] == after['journal_current'] == reference, 'command acted on another reference')
            require(before['journal_posted'] == ('1' if i == 0 else '0') and after['journal_posted'] == ('1' if kind == 'cancel' else '0'),
                    'independent posting flag differs')
            require(before['journal_value'] == before_value and after['journal_value'] == after_value
                    and record.get('expected') == after_value, 'data/entries/neighbors/count changed unexpectedly')
            calls = record.get('calls', [])
            first_number = -105000 - 2 * record['index']
            require(len(calls) >= 2 and calls[0] == dict(before, number=first_number)
                    and calls[-1] == dict(after, number=first_number-1), 'unpost state differs from raw calls')
        except (KeyError, RuntimeError) as error:
            issues.append('unpost: ' + str(error))
        menu, action = record.get('menu', {}), record.get('action', {})
        require(menu.get('command') == 0x806E and 'не проведенным' in menu.get('caption', '')
                and menu.get('enabled') is (i == 0) and bool(menu.get('flags', 3) & 3) == (i > 0), 'native menu command/state differs')
        if i == 0:
            require(action.get('command') == 0x806E and action.get('message') == 'WM_COMMAND'
                    and action.get('requested') is True and action.get('returned') is True
                    and action.get('identity_rechecked') is True and str(action.get('hwnd')) in handles, 'native command missing/foreign')
            window = record.get('confirmation', {})
            require(scenario77.dialog_text(window) == 'Подтвердите отмену проведения документа !', 'wrong confirmation text')
            answer = record.get('answer', {})
            require(answer.get('button', {}).get('id') == (7 if kind == 'cancel' else 6)
                    and answer.get('requested') is True and answer.get('identity_rechecked') is True, 'wrong confirmation answer')
        else:
            require(action.get('requested') is False and not record.get('confirmation') and not record.get('answer')
                    and len(record.get('calls', [])) == 2, 'disabled repeat sent a command')
    return issues


def check(folder, kind='success', expected_hash=None):
    initial, unposted = expectations()
    inspection = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text(encoding='utf-8'))['identity']
    result = document_check(folder, 'wrong-reopen' if kind == 'wrong-limit' else kind, expected_hash,
                            readback=initial if kind in ('cancel', 'wrong-limit') else unposted,
                            step_validator=lambda records, _: step_issues(records, kind, inspection, identity), allow_fixture_posting=True)
    result['kind'] = kind
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    checks = [e for e in events if e.get('kind') == 'ert' and e.get('name') == 'check']
    if len(checks) != 1 or checks[0]['value'].splitlines().count('fixture-initial:' + initial) != 1:
        result['issues'].append('independent initial data/entries differ')
    controller = (folder / 'native/ert-controller.1s').read_text(encoding='utf-8')
    if 'ОткрытьФорму(Объект77Данных,' in controller or '.АктивизироватьОбъект(' in controller or 'УстановитьИнтервал(' in controller:
        result['issues'].append('direct target opening/cursor positioning/period change')
    return result


def excluded_attempt(folder):
    report = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    stage = next(s for s in report['stages'] if s['stage'] == 'platform_check')
    native_absent = all(not (folder / 'native' / name).exists()
                        for name in ('ert-events.jsonl', 'ert-manifest.json', 'owner.json'))
    if report.get('platform_checked') is False and stage.get('shutdown') is None and native_absent:
        copy = stage.get('base_copy', {})
        valid = (copy.get('source_check', {}).get('unchanged') is True
                 and copy.get('removal', {}).get('removed') is True and copy.get('lock', {}).get('released') is True)
        return dict(run_id=report['run_id'], status=report['status'], reason=report['reason'],
                    run_sha256=digest(folder / 'run.json'), native_not_started=True, cleanup_verified=valid,
                    issues=[] if valid else ['prelaunch copy cleanup not confirmed'])
    return excluded(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('suite', 'excluded-run', 'test-log', 'regression-report'):
        parser.add_argument('--' + name, type=Path, action='append', default=[])
    parser.add_argument('--blocked-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    issues, runs, suites = [], [], []
    for folder in args.suite:
        suites.append(verify_suite(folder.resolve(), native=True))
        for row in json.loads((folder / 'suite.json').read_text(encoding='utf-8'))['scenarios']:
            kind = row['id'] if row['id'].startswith('wrong') or row['id'] == 'cancel' else 'success'
            runs.append(check((folder / row['report']['path']).parent.resolve(), kind, row['report']['sha256']))
    if sorted(r['kind'] for r in runs) != ['cancel'] + ['success'] * 4 + ['wrong', 'wrong-limit']:
        issues.append('required seven runs missing')
    blocked = json.loads((args.blocked_run / 'run.json').read_text(encoding='utf-8'))
    if not (blocked.get('status') == 'blocked' and blocked.get('platform_checked') is False
            and 'verified base copy' in str(blocked.get('reason')) and not (args.blocked_run / 'native/ert-events.jsonl').exists()):
        issues.append('no-copy guard not confirmed')
    attempts = [excluded_attempt(p) for p in args.excluded_run]
    for item in runs + suites + attempts:
        issues.extend(item['issues'])
    for p in args.test_log:
        text = p.read_text(encoding='utf-8')
        if '\nRan ' not in text or not text.rstrip().endswith(('OK', 'OK (skipped=3)')):
            issues.append(str(p) + ': tests failed')
    for p in args.regression_report:
        report = json.loads(p.read_text(encoding='utf-8'))
        if report.get('status') != 'passed' or report.get('issues'):
            issues.append(str(p) + ': regression failed')
    sources = ['research/forms/journal77.py', 'research/forms/scenario77.py', 'research/forms/form_launcher77.py',
               'research/forms/fixture77.py', 'research/forms/form_window77.py', 'research/forms/tests/test_journal_unpost77.py',
               'examples/journal-unpost/scenario.toml', 'examples/journal-unpost/prepare.py', 'scripts/verify_journal_unpost77.py',
               'scripts/verify_document_form77.py', 'scripts/verify_suite77.py', 'scripts/verify_journal_document77.py']
    result = dict(status='failed' if issues else 'passed', issues=issues, runs=runs, suites=suites, excluded_attempts=attempts,
                  blocked_run=dict(run_id=blocked['run_id'], sha256=digest(args.blocked_run / 'run.json')),
                  test_logs={str(p): digest(p) for p in args.test_log}, regressions={str(p): digest(p) for p in args.regression_report},
                  sources={p: digest(ROOT / p) for p in sources})
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(status=result['status'], issues=issues), ensure_ascii=False))
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
