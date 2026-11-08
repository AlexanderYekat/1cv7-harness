"""Independently re-read 039 source/copy identities, native UI, raw responses and cleanup."""
import argparse
from datetime import date
import importlib.util
import json
from pathlib import Path
import sys

from verify_document_form77 import ROOT, digest, read, check as document_check, step_issues as document_steps
from verify_journal_deletion77 import attempt
from verify_suite77 import verify as verify_suite

sys.path.insert(0, str(ROOT / 'research/forms'))
import journal77
import journal_copy77 as copying

spec = importlib.util.spec_from_file_location('copy_example', ROOT / 'examples/journal-copy/prepare.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def initial(kind):
    return example.state(posted=0 if kind in ('unposted', 'deleted') else 1, deleted=int(kind == 'deleted'))


def step_issues(records, kind, inspection, identity):
    issues = []
    def require(ok, reason):
        if not ok:
            issues.append(reason)
    require([r.get('kind') for r in records[:2]] == ['journal_period', 'find_document'], 'period/search prefix missing')
    if len(records) < 2:
        return issues
    handles = {str(w['hwnd']) for w in inspection.get('chain', [])[:2]}
    period, search = records[:2]
    try:
        journal77.check_period(period, period)
        require(journal77.read_period(period['after_period']) == (date(2026, 7, 31), date(2026, 8, 1)),
                'wrong journal period')
        require([f['text'] for f in journal77.period_fields(period['edited_window'])] == ['31.07.26', '01.08.26'],
                'period input differs')
        require(period.get('calls') == [dict(period[k], number=n) for k, n in
                (('before_period', -102002), ('after_period', -102003))], 'period/raw calls differ')
        require(period.get('action', {}).get('command') == 0x8071 and period['action'].get('posted') is True
                and period.get('answer', {}).get('button', {}).get('id') == 1 and not period.get('cancel')
                and period.get('status') == 'passed', 'period command/confirmation missing')
        for key in ('period_window', 'edited_window'):
            w = period[key]
            require(all(w.get(k) == identity[k] for k in ('pid', 'tid')) and all(
                all(c.get(k) == identity[k] for k in ('pid', 'tid')) for c in w.get('children', [])), 'foreign period dialog')
    except (KeyError, ValueError, RuntimeError) as error:
        issues.append('period: ' + str(error))
    rows = search.get('search', [])
    require(search.get('open') is False and not search.get('action') and not search.get('opened_form'), 'search opened a document')
    require(search.get('calls') == [dict(r.get('round_trip', {}), number=-101000-i) for i, r in enumerate(rows)],
            'search/raw calls differ')
    require(bool(rows) and len(rows) <= search.get('limit', 100), 'missing/unbounded search')
    for i, row in enumerate(rows):
        action, trip = row.get('action', {}), row.get('round_trip', {})
        require(action.get('key') == ('End' if i == 0 else 'Up') and action.get('id') == 4151
                and action.get('returned') is True and action.get('identity_rechecked') is True, 'unverified journal key')
        require(trip.get('returned') is True and trip.get('complete') is True and not trip.get('diagnostics')
                and not trip.get('journal_error') and str(trip.get('journal_hwnd')) in handles
                and bool(trip.get('journal_current')), 'incomplete/foreign cursor response')
        require(trip.get('journal_match') == ('1' if i == len(rows)-1 and kind != 'wrong-limit' else '0'), 'wrong cursor match')
    if kind == 'wrong-limit':
        require(len(records) == 2 and len(rows) == 1 and search.get('status') == 'failed'
                and 'search limit' in str(search.get('issue')), 'limited search did not stop before copy')
        return issues
    require(len(rows) == 2 and search.get('cursor_verified') is True and search.get('status') == 'passed'
            and search.get('round_trip') == rows[-1].get('round_trip'), 'exact cursor selection missing')
    copies = [r for r in records if r.get('kind') == 'journal_copy']
    require(len(copies) == 1 and len(records) > 2 and records[2] is copies[0], 'copy transition missing/repeated')
    if len(copies) != 1:
        return issues
    copy = copies[0]
    require(copy.get('index') == 3, 'copy transition index differs')
    if copy.get('index') != 3:
        return issues
    before, new = copy.get('before_copy', {}), copy.get('round_trip', {})
    try:
        journal77.checked_cursor(before, inspection)
        copying.checked_new(new)
    except RuntimeError as error:
        issues.append(str(error))
        return issues
    source = rows[-1]['round_trip'].get('journal_current') if rows else None
    require(before.get('journal_current') == new.get('journal_source') == source, 'copy source changed')
    require(before.get('journal_value') == new.get('journal_value') == initial(kind), 'copy changed source/neighbors/count')
    require(before.get('journal_posted') == ('0' if kind in ('unposted', 'deleted') else '1')
            and before.get('journal_deleted') == str(int(kind == 'deleted')), 'saved source flags differ')
    require(copy.get('calls') == [dict(before, number=-108000-copy['index']), dict(new, number=copy['index'])], 'copy/raw calls differ')
    menu, action = copy.get('menu', {}), copy.get('action', {})
    require(menu.get('command') == copying.COPY_COMMAND and 'копировать' in menu.get('caption', '').casefold()
            and menu.get('enabled') is True and not menu.get('flags', 3) & 3
            and menu.get('main') == inspection.get('chain', [{}])[-1].get('hwnd'), 'native Copy menu missing/disabled/foreign')
    require(action.get('command') == copying.COPY_COMMAND and action.get('hwnd') == inspection['chain'][1]['hwnd']
            and action.get('message') == 'WM_COMMAND' and action.get('requested') is True
            and action.get('posted') is True and action.get('returned') is True and action.get('identity_rechecked') is True,
            'owned native Copy command missing')
    chain = copy.get('created_form', {}).get('chain', [])
    old = {str(w['hwnd']) for w in copy.get('before_windows', [])}
    require(copy.get('new_form_verified') is True and copy.get('status') == 'passed'
            and str(new.get('journal_hwnd')) in {str(w['hwnd']) for w in chain[:2]}
            and str(new.get('journal_hwnd')) not in old and str(new.get('journal_hwnd')) not in handles,
            'new unsaved copy window is missing/stale/foreign')
    inventory = {w['hwnd']: w for w in copy.get('after_windows', [])}
    require(bool(chain) and all(all(inventory.get(w['hwnd'], {}).get(k) == identity[k]
            for k in ('pid', 'tid')) for w in chain), 'foreign copy window process/thread')
    require(new.get('journal_date') == '2026:11:8' and new.get('journal_number') == '000000000004', 'native new date/number differs')
    values = {(r.get('target'), r.get('row')): r.get('round_trip', {}).get('value') for r in records[3:12] if r.get('kind') == 'value'}
    require(values == {('Количество', 1): '1', ('Стоимость', 1): '10', ('Сумма', 1): '10',
                       ('Количество', 2): '2', ('Стоимость', 2): '20', ('Сумма', 2): '40'}, 'copied table fields differ')
    require(any(r.get('kind') == 'check' and r.get('target') == 'Комментарий'
                and r.get('state', {}).get('text', '').strip() == 'Harness77 журнал 039 2' for r in records[3:12]), 'copied comment missing')
    require(any(r.get('kind') == 'rows' and r.get('round_trip', {}).get('rows') == 2 for r in records[3:12])
            and any(r.get('kind') == 'total' and r.get('round_trip', {}).get('total') == '50' for r in records[3:12]), 'copied rows/total missing')
    captures = [r for r in records if r.get('kind') == 'created']
    if kind == 'cancel':
        require(not captures and not any(r.get('kind') == 'reopen' for r in records), 'cancel saved/reopened a copy')
        dialogs = [r for r in records if r.get('kind') == 'dialog']
        require(len(dialogs) == 1 and dialogs[0].get('target') == 'Сохранить Документ?'
                and dialogs[0].get('button') == 'Нет' and dialogs[0].get('answer', {}).get('button', {}).get('id') == 7
                and dialogs[0].get('answer', {}).get('requested') is True and dialogs[0].get('form_open') is False,
                'cancel did not reject saving/close copy')
        require(any(r.get('kind') == 'close_form' and r.get('action', {}).get('returned') is True for r in records), 'cancel did not close native frame')
    else:
        require(len(captures) == 1, 'saved-copy capture missing/repeated')
        if captures:
            capture = captures[0]
            saved = capture.get('round_trip', {})
            require(saved.get('journal_saved') == '1' and bool(saved.get('journal_reference'))
                    and saved.get('journal_reference') != source and saved.get('journal_source') == source,
                    'saved copy reused/lost source reference')
            require(saved.get('journal_date') == new.get('journal_date') and saved.get('journal_number') == new.get('journal_number')
                    and saved.get('journal_posted') == saved.get('journal_deleted') == '0', 'UI save altered copy date/number/flags')
            require(saved.get('journal_value') == example.state(True, posted=0 if kind in ('unposted', 'deleted') else 1,
                    deleted=int(kind == 'deleted'), saved_posted=0), 'independent saved-but-unposted copy/source state differs')
            require(capture.get('index', 0) < next((r['index'] for r in records if r['kind'] == 'reopen'), 0), 'capture did not precede reopen')
            require(any(r.get('kind') == 'value' and r.get('target') == 'Комментарий'
                        and r.get('index', 0) < capture.get('index', 0)
                        and r.get('round_trip', {}).get('value') == 'Harness77 копия 039' for r in records),
                    'form comment attribute not checked before saving')
        issues += document_steps(records, comment='Harness77 копия 039')
    require(all(r.get('status') == 'passed' and not r.get('issue') for r in records), 'unexpected step failure')
    for r in records:
        if r.get('kind') == 'input':
            a = r.get('action', {})
            require(a.get('text_typed') == r.get('text'), 'input text was corrupted before leaving field')
            layouts = a.get('character_input_layouts', [])
            require([v.get('code') for v in layouts] == [c.encode('cp1251')[0] for c in r.get('text', '') if ord(c) >= 128],
                    'non-ASCII character input layout evidence missing')
            require(all(v.get('pid') == identity['pid'] and v.get('tid') == identity['tid']
                    and str(v.get('desktop', '')).startswith('harness77_')
                    and v.get('caller_active') == v.get('server_active') == v.get('requested')
                    and v.get('requested', 0) & 0xffff == 0x419
                    and v.get('caller_restored') is True and v.get('server_restored') is True for v in layouts),
                    'input layouts foreign/unverified/not restored')
    return issues


def check(folder, kind='success', expected_hash=None):
    inspection = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text(encoding='utf-8'))['identity']
    final = example.state(copied=kind not in ('cancel', 'wrong-limit'),
                          posted=0 if kind in ('unposted', 'deleted') else 1, deleted=int(kind == 'deleted'))
    result = document_check(folder, 'wrong-reopen' if kind == 'wrong-limit' else kind, expected_hash, readback=final,
        step_validator=lambda records, _: step_issues(records, kind, inspection, identity), allow_fixture_posting=True)
    result['kind'] = kind
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    checks = [e for e in events if e.get('kind') == 'ert' and e.get('name') == 'check']
    if len(checks) != 1 or checks[0]['value'].splitlines().count('fixture-initial:' + initial(kind)) != 1:
        result['issues'].append('independent initial source/neighbors/entries differ')
    controller = (folder / 'native/ert-controller.1s').read_text(encoding='utf-8')
    outside_setup = controller.split('Функция Harness77ПодготовитьДанные()', 1)[1].split('КонецФункции', 1)[1]
    if any(s in outside_setup for s in ('.Копировать(', '.Новый(', '.Записать(', '.Удалить(', '.Провести(', '.АктивизироватьОбъект(', 'УстановитьИнтервал(')):
        result['issues'].append('programmatic creation/copy/write/post/delete/navigation found')
    return result


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
            kind = row['id'] if row['id'] in ('unposted', 'deleted', 'cancel', 'wrong', 'wrong-limit') else 'success'
            runs.append(check((folder / row['report']['path']).parent.resolve(), kind, row['report']['sha256']))
    if sorted(r['kind'] for r in runs) != sorted(['success'] * 4 + ['unposted', 'deleted', 'cancel', 'wrong', 'wrong-limit']):
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
    sources = ['research/forms/journal77.py', 'research/forms/journal_copy77.py', 'research/forms/scenario77.py',
        'research/forms/form_launcher77.py', 'research/forms/fixture77.py', 'research/forms/form_window77.py',
        'research/forms/tests/test_journal_copy77.py', 'examples/journal-copy/scenario.toml',
        'examples/journal-copy/prepare.py', 'scripts/verify_journal_copy77.py', 'scripts/verify_journal_unpost77.py',
        'scripts/verify_document_form77.py', 'scripts/verify_suite77.py', 'scripts/verify_journal_document77.py',
        'scripts/verify_journal_deletion77.py', 'scripts/verify_journal_copy_controls77.py']
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
