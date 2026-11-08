"""Independently verify task 038 cursor, UI toggle, raw protocols, data and cleanup."""
import argparse
from datetime import date
import importlib.util
import json
from pathlib import Path
import sys

from verify_document_form77 import ROOT, digest, read, check as document_check
from verify_journal_unpost77 import excluded_attempt
from verify_suite77 import verify as verify_suite

sys.path.insert(0, str(ROOT / 'research/forms'))
import journal77
import journal_deletion77 as deletion
import scenario77

spec = importlib.util.spec_from_file_location('deletion_example', ROOT / 'examples/journal-deletion/prepare.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)
state = example.state


def step_issues(records, kind, inspection, identity):
    issues = []
    def require(ok, message):
        if not ok:
            issues.append(message)
    require([r.get('kind') for r in records[:2]] == ['journal_period', 'find_document'], 'period/search prefix missing')
    if len(records) < 2:
        return issues
    handles = {str(w['hwnd']) for w in inspection.get('chain', [])[:2]}
    main = inspection.get('chain', [{}])[-1].get('hwnd')
    for record in records:
        for key in ('period_window', 'edited_window', 'confirmation'):
            window = record.get(key)
            if window:
                require(all(window.get(k) == identity[k] for k in ('pid', 'tid')) and all(
                    all(c.get(k) == identity[k] for k in ('pid', 'tid')) for c in window.get('children', [])),
                    'dialog/field belongs to another process/thread')
    period, search = records[:2]
    try:
        journal77.check_period(period, period)
        before, after = (journal77.read_period(period[k]) for k in ('before_period', 'after_period'))
        require(not before[0] <= date(2026, 8, 1) <= before[1] and after == (date(2026, 7, 31), date(2026, 8, 1)),
                'period/target inclusion differs')
        require([f['text'] for f in journal77.period_fields(period['edited_window'])] == ['31.07.26', '01.08.26'],
                'native period input differs')
        require(not period.get('cancel') and period.get('answer', {}).get('button', {}).get('id') == 1,
                'period was not confirmed')
        require(len(period.get('inputs', [])) == 2 and all(i.get('typed') is True for i in period['inputs']),
                'period input missing')
        require(period.get('calls') == [dict(period[k], number=n) for k, n in
                (('before_period', -102002), ('after_period', -102003))], 'period/raw calls differ')
    except (KeyError, ValueError, RuntimeError) as error:
        issues.append('period: ' + str(error))
    require(period.get('status') == 'passed' and period.get('action', {}).get('posted') is True
            and period['action'].get('command') == 0x8071, 'native period command missing/failed')
    rows = search.get('search', [])
    require(search.get('open') is False and not search.get('action') and not search.get('opened_form'),
            'search opened a document')
    require(search.get('calls') == [dict(r.get('round_trip', {}), number=-101000-i) for i, r in enumerate(rows)],
            'cursor/raw calls differ')
    require(bool(rows) and len(rows) <= search.get('limit', 100), 'search missing or unbounded')
    for i, row in enumerate(rows):
        action, trip = row.get('action', {}), row.get('round_trip', {})
        require(action.get('key') == ('End' if i == 0 else 'Up') and action.get('id') == 4151
                and action.get('returned') is True and action.get('identity_rechecked') is True, 'cursor key is not owned/verified')
        require(trip.get('returned') is True and trip.get('complete') is True and not trip.get('diagnostics')
                and not trip.get('journal_error') and str(trip.get('journal_hwnd')) in handles and bool(trip.get('journal_current')),
                'cursor response incomplete/foreign')
        require(trip.get('journal_match') == ('1' if i == len(rows)-1 and kind != 'wrong-limit' else '0'), 'wrong cursor reference')
    if kind == 'wrong-limit':
        require(len(records) == 2 and len(rows) == 1 and search.get('status') == 'failed'
                and 'search limit' in str(search.get('issue')), 'limited search did not stop before command')
        return issues
    require(len(rows) == 2 and search.get('cursor_verified') is True and search.get('status') == 'passed'
            and search.get('round_trip') == rows[-1].get('round_trip'), 'selected cursor proof missing')
    reference = rows[-1].get('round_trip', {}).get('journal_current') if rows else None
    actions = records[2:]
    directions = [True] if kind == 'cancel-mark' else [True, False]
    require(len(actions) == len(directions), 'mark/unmark step count differs')
    previous_value = state(0 if kind == 'unposted' else 1, 0)
    for i, (record, deleted) in enumerate(zip(actions, directions)):
        cancel = (kind == 'cancel-mark') or (kind == 'cancel-unmark' and i == 1)
        require(record.get('kind') == 'journal_deletion' and record.get('status') == 'passed'
                and record.get('deleted') is deleted and bool(record.get('cancel')) is cancel, 'toggle direction/status/cancel differs')
        expected = previous_value if cancel else state(0, int(deleted))
        try:
            before, after = (record[k] for k in ('before_deletion', 'after_deletion'))
            for trip in (before, after):
                deletion.checked_state(trip, inspection)
                require(trip['journal_current'] == reference, 'target reference changed')
            require(before['journal_deleted'] == str(int(not deleted)) and after['journal_deleted'] ==
                    (before['journal_deleted'] if cancel else str(int(deleted))), 'saved deletion mark differs')
            require(before['journal_posted'] == ('1' if i == 0 and kind != 'unposted' else '0')
                    and after['journal_posted'] == ('1' if kind == 'cancel-mark' else '0'), 'saved posting flag differs')
            require(before['journal_value'] == previous_value and after['journal_value'] == expected
                    and record.get('expected') == expected, 'data/entries/neighbors/headers/count differ')
            calls = record.get('calls', [])
            number = -107000 - 2 * record['index']
            require(len(calls) >= 2 and calls[0] == dict(before, number=number) and calls[-1] == dict(after, number=number-1),
                    'saved state/raw calls differ')
        except (KeyError, RuntimeError) as error:
            issues.append('deletion: ' + str(error))
        menu, action = record.get('menu', {}), record.get('action', {})
        require(menu.get('command') == deletion.DELETE_COMMAND and 'удал' in menu.get('caption', '').casefold()
                and menu.get('enabled') is True and menu.get('flags', 3) & 3 == 0 and menu.get('main') == main,
                'native menu identity/state differs')
        require(action.get('command') == deletion.DELETE_COMMAND and action.get('message') == 'WM_COMMAND'
                and action.get('requested') is True and action.get('returned') is True
                and action.get('identity_rechecked') is True and action.get('hwnd') == inspection['chain'][1]['hwnd'],
                'native command missing/foreign')
        try:
            window = record['confirmation']
            button = deletion.answer(window, deleted, cancel)
            answer = record['answer']
            require(answer.get('button') == {k: button[k] for k in ('hwnd', 'id', 'text')}
                    and answer.get('requested') is True and answer.get('identity_rechecked') is True,
                    'confirmation answer differs')
            require(window.get('owner') == main and window.get('owner_enabled') is False
                    and window.get('visible') is True and not record.get('dismissed'), 'confirmation is not modal/owned or was dismissed')
        except (KeyError, RuntimeError, AttributeError) as error:
            issues.append('confirmation: ' + str(error))
        previous_value = expected
    return issues


def check(folder, kind='success', expected_hash=None):
    inspection = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text(encoding='utf-8'))['identity']
    final = state(1, 0) if kind in ('cancel-mark', 'wrong-limit') else state(0, int(kind == 'cancel-unmark'))
    result = document_check(folder, 'wrong-reopen' if kind == 'wrong-limit' else kind, expected_hash,
        readback=final, step_validator=lambda records, _: step_issues(records, kind, inspection, identity), allow_fixture_posting=True)
    result['kind'] = kind
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    checks = [e for e in events if e.get('kind') == 'ert' and e.get('name') == 'check']
    initial = state(0 if kind == 'unposted' else 1, 0)
    if len(checks) != 1 or checks[0]['value'].splitlines().count('fixture-initial:' + initial) != 1:
        result['issues'].append('independent initial data/entries/marks differ')
    controller = (folder / 'native/ert-controller.1s').read_text(encoding='utf-8')
    forbidden = ('.Удалить(', '.СнятьПометкуУдаления(', '.УстановитьПометкуУдаления(',
                 'ОткрытьФорму(Объект77Данных,', '.АктивизироватьОбъект(', 'УстановитьИнтервал(')
    if any(s in controller for s in forbidden):
        result['issues'].append('programmatic deletion/target opening/cursor positioning/period change')
    return result


def attempt(folder):
    report = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    if report.get('platform_checked') is False and 'configuration_error:' in str(report.get('reason')):
        native_absent = not (folder / 'native').exists()
        return dict(run_id=report['run_id'], status=report['status'], run_sha256=digest(folder / 'run.json'),
                    native_not_started=native_absent, reason=report['reason'],
                    issues=[] if native_absent else ['configuration failure has native evidence'])
    return excluded_attempt(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('suite', 'excluded-run', 'test-log', 'regression-report', 'control-report'):
        parser.add_argument('--' + name, type=Path, action='append', default=[])
    parser.add_argument('--blocked-run', type=Path, required=True)
    parser.add_argument('--excluded-test-log', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    issues, runs, suites = [], [], []
    for folder in args.suite:
        suites.append(verify_suite(folder.resolve(), native=True))
        for row in json.loads((folder / 'suite.json').read_text(encoding='utf-8'))['scenarios']:
            kind = row['id'] if row['id'] in ('unposted', 'cancel-mark', 'cancel-unmark', 'wrong', 'wrong-limit') else 'success'
            runs.append(check((folder / row['report']['path']).parent.resolve(), kind, row['report']['sha256']))
    if sorted(r['kind'] for r in runs) != sorted(['success'] * 4 + ['unposted', 'cancel-mark', 'cancel-unmark', 'wrong', 'wrong-limit']):
        issues.append('required nine runs missing')
    blocked = json.loads((args.blocked_run / 'run.json').read_text(encoding='utf-8'))
    if not (blocked.get('status') == 'blocked' and blocked.get('platform_checked') is False
            and 'verified base copy' in str(blocked.get('reason')) and not (args.blocked_run / 'native/ert-events.jsonl').exists()):
        issues.append('no-copy guard not confirmed')
    attempts = [attempt(p) for p in args.excluded_run]
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
    for p in args.control_report:
        report = json.loads(p.read_text(encoding='utf-8'))
        if (report.get('status') != 'passed' or not report.get('controls')
                or not all(c.get('rejected') is True for c in report['controls'])
                or report.get('verifier_sha256') != digest(Path(__file__))
                or report.get('baseline_run') not in [r['run_id'] for r in runs]):
            issues.append(str(p) + ': verifier controls failed')
    sources = ['research/forms/journal77.py', 'research/forms/journal_deletion77.py', 'research/forms/scenario77.py',
        'research/forms/form_launcher77.py', 'research/forms/fixture77.py', 'research/forms/form_window77.py',
        'research/forms/tests/test_journal_deletion77.py', 'examples/journal-deletion/scenario.toml',
        'examples/journal-deletion/prepare.py', 'scripts/verify_journal_deletion77.py', 'scripts/verify_journal_unpost77.py',
        'scripts/verify_document_form77.py', 'scripts/verify_suite77.py', 'scripts/verify_journal_document77.py']
    result = dict(status='failed' if issues else 'passed', issues=issues, runs=runs, suites=suites, excluded_attempts=attempts,
        blocked_run=dict(run_id=blocked['run_id'], sha256=digest(args.blocked_run / 'run.json')),
        test_logs={str(p): digest(p) for p in args.test_log}, regressions={str(p): digest(p) for p in args.regression_report},
        controls={str(p): digest(p) for p in args.control_report},
        excluded_test_logs={str(p): digest(p) for p in args.excluded_test_log},
        sources={p: digest(ROOT / p) for p in sources})
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(status=result['status'], issues=issues), ensure_ascii=False))
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
