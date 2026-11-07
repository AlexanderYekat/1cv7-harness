"""Independent task 036 verifier: native interval UI, raw calls, search and persisted state."""
import argparse
from datetime import date
import json
import re
from pathlib import Path
import sys
import tomllib

from verify_document_form77 import ROOT, digest, read, check as document_check
from verify_journal_document77 import excluded
from verify_journal_existing77 import step_issues as existing_steps
from verify_suite77 import verify as verify_suite

sys.path.insert(0, str(ROOT / 'research/forms'))
import journal77


def expectations():
    data = tomllib.loads((ROOT / 'examples/journal-period/scenario.toml').read_text(encoding='utf-8'))
    changed = data['platform']['tests'][-1]['expect_value']
    initial = changed.replace('Harness77 журнал 036 изменён|2|3:10:30;2:20:40;|1|2|43>40:3:30;',
                              'Harness77 журнал 036 2|2|1:10:10;2:20:40;|1|2|43>40:1:10;')
    return initial, changed


def step_issues(records, kind):
    issues = []
    def require(ok, message):
        if not ok:
            issues.append(message)
    period = records[0] if records else {}
    require(period.get('kind') == 'journal_period' and period.get('status') == 'passed', 'native period step missing/failed')
    try:
        journal77.check_period(period, period)
        fields = journal77.period_fields(period['period_window'])
        before, after = (journal77.read_period(period[k]) for k in ('before_period', 'after_period'))
        target = date(2026, 8, 1)
        require(not before[0] <= target <= before[1], 'target already in original journal interval')
        require((after[0] <= target <= after[1]) == (kind not in ('wrong-limit', 'wrong-cancel')),
                'target inclusion differs from prescribed period case')
        require(period.get('start') == '2026-07-31' and period.get('end') == ('2026-07-31' if kind == 'wrong-limit' else '2026-08-01'),
                'period dates differ from task expectations')
        require(bool(period.get('cancel')) == (kind == 'wrong-cancel'), 'wrong cancel case')
        calls = period.get('calls', [])
        require(len(calls) == 2 and [c.get('number') for c in calls] == [-102002, -102003]
                and all({k: v for k, v in c.items() if k != 'number'} == period[key]
                        for c, key in zip(calls, ('before_period', 'after_period'))), 'period readback/calls differ')
        require(period.get('action', {}).get('posted') is True and period['action'].get('command') == 0x8071,
                'native Interval command missing')
        answer = period.get('answer', {})
        require(answer.get('identity_rechecked') is True and answer.get('button', {}).get('id') == (2 if kind == 'wrong-cancel' else 1),
                'native OK/Cancel answer differs')
        inputs = period.get('inputs', [])
        require(len(inputs) == 2 and [i.get('boundary') for i in inputs] == ['start', 'end']
                and all(i.get('typed') is True for i in inputs), 'both period boundaries were not typed')
        edited = journal77.period_fields(period['edited_window'])
        require([f['hwnd'] for f in fields] == [f['hwnd'] for f in edited], 'period fields changed identity')
        require([f['text'] for f in edited] == [date.fromisoformat(period[k]).strftime('%d.%m.%y') for k in ('start', 'end')],
                'edited date fields differ from prescribed input')
    except (KeyError, ValueError, RuntimeError, TypeError) as error:
        issues.append('period evidence: ' + str(error))
    rest = records[1:]
    if kind in ('wrong-limit', 'wrong-cancel'):
        require(len(rest) == 1, 'failed search continued into document actions')
        search = rest[0] if rest else {}
        rows = search.get('search') or []
        require(search.get('kind') == 'find_document' and search.get('status') == 'failed'
                and 'search limit' in (search.get('issue') or '') and not search.get('action')
                and len(rows) == 3 and search.get('limit') == 3, 'excluded target was opened or search not bounded')
        require(search.get('calls') == [dict(r.get('round_trip', {}), number=-101000 - n) for n, r in enumerate(rows)],
                'failed search calls differ')
        for n, row in enumerate(rows):
            action, trip = row.get('action', {}), row.get('round_trip', {})
            require(action.get('key') == ('End' if n == 0 else 'Up') and action.get('id') == 4151
                    and action.get('identity_rechecked') is True and action.get('returned') is True
                    and trip.get('returned') is True and trip.get('complete') is True
                    and not trip.get('diagnostics') and not trip.get('journal_error')
                    and trip.get('journal_match') == '0', 'failed search cursor/key not verified')
    else:
        issues += existing_steps(rest, 'success')
    return issues


def check(folder, kind, expected_hash):
    initial, changed = expectations()
    negative = kind in ('wrong-limit', 'wrong-cancel')
    result = document_check(folder, 'wrong-reopen' if negative else kind, expected_hash,
                            readback=initial if negative else changed,
                            step_validator=lambda records, _: step_issues(records, kind), allow_fixture_posting=True)
    result['kind'] = kind
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    checks = [e for e in events if e.get('kind') == 'ert' and e.get('name') == 'check']
    if len(checks) != 1 or checks[0]['value'].splitlines().count('fixture-initial:' + initial) != 1:
        result['issues'].append('independent pre-UI data/entries differ')
    controller = (folder / 'native/ert-controller.1s').read_text(encoding='utf-8')
    if 'УстановитьИнтервал(' in controller or '.АктивизироватьОбъект(' in controller:
        result['issues'].append('programmatic interval change/cursor positioning')
    if len(re.findall(r'ОткрытьФорму\(Объект77Данных,', controller)) != 1:
        result['issues'].append('unexpected direct document opening outside the declared reopen')
    if "Док77.ДатаДок = '01.08.2026';" not in controller or "Док77.ДатаДок = '31.07.2026';" not in controller:
        result['issues'].append('prepared document dates differ')
    inspection = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text(encoding='utf-8'))
    expected_owner = identity['identity']
    period = inspection['steps'][0]
    for key in ('period_window', 'edited_window'):
        window = period.get(key, {})
        if any(window.get(k) != expected_owner[k] for k in ('pid', 'tid')) or any(
                any(c.get(k) != expected_owner[k] for k in ('pid', 'tid')) for c in window.get('children', [])):
            result['issues'].append('period dialog/field belongs to another process or thread')
    handles = {str(w['hwnd']) for w in inspection['chain'][:2]}
    for record in inspection.get('steps', []):
        for row in record.get('search', []):
            if str(row.get('round_trip', {}).get('journal_hwnd')) not in handles:
                result['issues'].append('cursor belongs to another journal')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('suite', 'excluded-run', 'test-log', 'regression-report'):
        parser.add_argument('--' + key, type=Path, action='append', default=[])
    parser.add_argument('--blocked-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    issues, runs, suites = [], [], []
    for folder in args.suite:
        suites.append(verify_suite(folder.resolve(), native=True))
        for row in json.loads((folder / 'suite.json').read_text(encoding='utf-8'))['scenarios']:
            kind = row['id'] if row['id'].startswith('wrong') else 'success'
            runs.append(check((folder / row['report']['path']).parent.resolve(), kind, row['report']['sha256']))
    blocked = json.loads((args.blocked_run / 'run.json').read_text(encoding='utf-8'))
    if not (blocked.get('status') == 'blocked' and blocked.get('platform_checked') is False
            and 'verified base copy' in str(blocked.get('reason'))
            and not (args.blocked_run / 'native/ert-events.jsonl').exists()):
        issues.append('no-copy guard not verified')
    attempts = [excluded(p) for p in args.excluded_run]
    for item in runs + suites + attempts:
        issues.extend(item['issues'])
    if sorted(r['kind'] for r in runs) != ['success'] * 5 + ['wrong', 'wrong-cancel', 'wrong-limit']:
        issues.append('required eight runs (five successes, three negative controls) missing')
    for p in args.test_log:
        text = p.read_text(encoding='utf-8')
        if '\nRan ' not in text or not text.rstrip().endswith(('OK', 'OK (skipped=3)')):
            issues.append(str(p) + ': tests failed')
    for p in args.regression_report:
        value = json.loads(p.read_text(encoding='utf-8'))
        if value.get('status') != 'passed' or value.get('issues'):
            issues.append(str(p) + ': regression failed')
    sources = ['research/forms/journal77.py', 'research/forms/scenario77.py', 'research/forms/form_launcher77.py',
               'research/forms/tests/test_journal_period77.py', 'examples/journal-period/scenario.toml',
               'examples/journal-period/prepare.py', 'scripts/verify_journal_period77.py',
               'scripts/verify_document_form77.py', 'scripts/verify_journal_existing77.py',
               'scripts/verify_journal_document77.py', 'scripts/verify_suite77.py',
               'research/forms/fixture77.py', 'research/forms/form_window77.py']
    result = dict(status='failed' if issues else 'passed', issues=issues, runs=runs, suites=suites,
                  excluded_attempts=attempts, blocked_run=dict(run_id=blocked['run_id'], sha256=digest(args.blocked_run / 'run.json')),
                  test_logs={str(p): digest(p) for p in args.test_log}, regressions={str(p): digest(p) for p in args.regression_report},
                  sources={p: digest(ROOT / p) for p in sources})
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(status=result['status'], issues=issues), ensure_ascii=False))
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
