"""Independently re-read 040 source/based-document identities, native UI, raw responses and cleanup."""
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
import journal_basis77 as basis

spec = importlib.util.spec_from_file_location('basis_example', ROOT / 'examples/journal-basis/prepare.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def initial(kind):
    return example.state()


def step_issues(records, kind, inspection, identity, descriptions=None):
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
    transitions = [r for r in records if r.get('kind') == 'journal_basis']
    require(len(transitions) == 1 and len(records) > 2 and records[2] is transitions[0], 'basis transition missing/repeated')
    if len(transitions) != 1:
        return issues
    action_record = transitions[0]
    before = action_record.get('before_basis', {})
    source = rows[-1]['round_trip'].get('journal_current') if rows else None
    try:
        journal77.checked_cursor(before, inspection)
    except RuntimeError as error:
        return issues + [str(error)]
    require(before.get('journal_current') == source and before.get('journal_value') == initial(kind)
            and before.get('journal_posted') == before.get('journal_deleted') == '0', 'basis source/state changed')
    menu, action = action_record.get('menu', {}), action_record.get('action', {})
    require(menu.get('command') == basis.BASIS_COMMAND and 'ввести на основании' in menu.get('caption', '').casefold()
            and menu.get('enabled') is True and not menu.get('flags', 3) & 3
            and menu.get('main') == inspection.get('chain', [{}])[-1].get('hwnd'), 'native basis menu missing/disabled/foreign')
    require(action.get('command') == basis.BASIS_COMMAND and action.get('hwnd') == inspection['chain'][1]['hwnd']
            and action.get('message') == 'WM_COMMAND' and action.get('requested') is True
            and action.get('identity_rechecked') is True, 'owned native basis command missing')
    window, selection = action_record.get('kind_window', {}), action_record.get('kind_selection', {})
    require(window.get('text') == 'Выбор вида документа' and window.get('class') == '#32770'
            and all(window.get(k) == identity[k] for k in ('pid', 'tid'))
            and all(all(c.get(k) == identity[k] for k in ('pid', 'tid')) for c in window.get('children', [])), 'foreign kind chooser')
    wanted = 'Прих.касс.орд. (Приходный кассовый ордер)'
    require(selection.get('names', []).count(wanted) == 1, 'permitted target kind missing/ambiguous')
    if kind == 'wrong-kind':
        require(action_record.get('status') == 'failed' and 'not unique' in str(action_record.get('issue'))
                and 'selected' not in selection and 'answer' not in selection and not action_record.get('new_form_verified')
                and not action_record.get('round_trip') and len(records) == 3, 'missing kind caused selection/creation')
        cleanup = action_record.get('unexpected_cleanup', {})
        require(cleanup.get('requested') is True and cleanup.get('button', {}).get('id') == 2, 'missing kind not cancelled')
        require(action_record.get('calls') == [dict(before, number=-108003)], 'missing kind calls differ')
        return issues
    require(action.get('posted') is True and action.get('returned') is True, 'basis command did not return')
    if kind == 'cancel-kind':
        import choice77
        after = action_record.get('after_cancel', {})
        require(selection.get('cancel') is True and selection.get('answer', {}).get('requested') is True
                and selection.get('answer', {}).get('button', {}).get('id') == 2
                and action_record.get('chooser_closed') is True and len(records) == 3
                and not action_record.get('new_form_verified') and not action_record.get('round_trip'), 'chooser cancellation did not stop creation')
        try:
            journal77.checked_cursor(after, inspection)
        except RuntimeError as error:
            issues.append(str(error))
        require(all(before.get(k) == after.get(k) for k in ('journal_current', 'journal_value', 'journal_posted', 'journal_deleted')), 'chooser cancellation altered source')
        require(action_record.get('calls') == [dict(before, number=-108003), dict(after, number=-108103)], 'cancellation calls differ')
        require(action_record.get('status') == 'passed' and not action_record.get('issue')
                and bool(action_record.get('after_windows'))
                and not choice77.new_frames(action_record['after_windows'], {w['hwnd'] for w in action_record.get('before_windows', [])}),
                'cancelled chooser left a new MDI form')
        return issues
    require(selection.get('caption') == wanted and isinstance(selection.get('selected'), int)
            and 0 <= selection['selected'] < len(selection.get('names', []))
            and selection['names'][selection['selected']] == wanted
            and selection.get('answer', {}).get('requested') is True
            and selection.get('answer', {}).get('button', {}).get('id') == 1, 'wrong/unconfirmed target kind')
    new = action_record.get('round_trip', {})
    try:
        basis.checked_new(new)
    except RuntimeError as error:
        return issues + [str(error)]
    require(new.get('journal_source') == new.get('journal_link') == source
            and new.get('journal_value') == initial(kind), 'new form changed/lost basis/neighbors/count')
    require(new.get('journal_comment', '').startswith('Введен на основании: '), 'basis comment missing')
    require(new.get('journal_date') == '2026:8:1', 'result did not inherit the basis date')
    require(action_record.get('calls') == [dict(before, number=-108003), dict(new, number=3)], 'basis/raw calls differ')
    chain = action_record.get('created_form', {}).get('chain', [])
    if descriptions:
        from form_window77 import judge_layout, judge_captions
        issues += judge_layout(descriptions[0], action_record.get('created_form'))
        issues += judge_captions(descriptions[0], action_record.get('created_form'))
    old = {str(w['hwnd']) for w in action_record.get('before_windows', [])}
    require(action_record.get('new_form_verified') is True and action_record.get('status') == 'passed'
            and str(new.get('journal_hwnd')) in {str(w['hwnd']) for w in chain[:2]}
            and str(new.get('journal_hwnd')) not in old and str(new.get('journal_hwnd')) not in handles, 'new form is missing/stale/foreign')
    inventory = {w['hwnd']: w for w in action_record.get('after_windows', [])}
    require(bool(chain) and all(all(inventory.get(w['hwnd'], {}).get(k) == identity[k]
            for k in ('pid', 'tid')) for w in chain), 'foreign result process/thread')
    require(any(r.get('kind') == 'value' and r.get('target') == 'Сумма'
                and r.get('round_trip', {}).get('value') == '50' for r in records), 'inherited amount not read')
    captures = [r for r in records if r.get('kind') == 'created']
    if kind == 'cancel':
        require(not captures and not any(r.get('kind') == 'reopen' for r in records), 'cancel saved/reopened result')
        dialogs = [r for r in records if r.get('kind') == 'dialog']
        require(len(dialogs) == 1 and dialogs[0].get('target') == 'Сохранить Документ?'
                and dialogs[0].get('button') == 'Нет' and dialogs[0].get('answer', {}).get('button', {}).get('id') == 7
                and dialogs[0].get('answer', {}).get('requested') is True and dialogs[0].get('form_open') is False,
                'cancel did not reject saving/close result')
        require(any(r.get('kind') == 'close_form' and r.get('action', {}).get('returned') is True for r in records), 'cancel did not close native frame')
    else:
        require(len(captures) == 1, 'saved result capture missing/repeated')
        if captures:
            capture = captures[0]
            saved = capture.get('round_trip', {})
            require(saved.get('journal_saved') == '1' and bool(saved.get('journal_reference'))
                    and saved.get('journal_reference') != source and saved.get('journal_source') == saved.get('journal_link') == source,
                    'saved result reused/lost source reference')
            require(saved.get('journal_date') == new.get('journal_date') and saved.get('journal_number') == new.get('journal_number')
                    and saved.get('journal_posted') == saved.get('journal_deleted') == '0', 'UI save altered date/number/flags')
            require(saved.get('journal_value') == example.state(True, posted=0), 'saved-but-unposted fields/entries/link differ')
        require([r.get('target') for r in records if r.get('kind') == 'click'] == ['Записать', 'ОК'], 'UI save/post missing or reordered')
        ok = next((r for r in records if r.get('kind') == 'click' and r.get('target') == 'ОК'), {})
        require(ok.get('closes') is True and ok.get('form_open') is False and ok.get('action', {}).get('returned') is True, 'native OK did not conduct/close result')
        returned = ok.get('action', {}).get('returned_journal', {})
        returned_trip = returned.get('round_trip', {})
        if descriptions:
            issues += judge_layout(descriptions[2], returned.get('inspection'))
            issues += judge_captions(descriptions[2], returned.get('inspection'))
        require(returned_trip.get('journal_return') == '1' and captures
                and returned_trip.get('journal_reference') == captures[0].get('round_trip', {}).get('journal_reference')
                and returned.get('frame', {}).get('text', '').startswith('Касса (')
                and str(returned_trip.get('journal_hwnd')) == str(returned.get('frame', {}).get('hwnd'))
                and returned.get('inspection', {}).get('found') is True
                and returned.get('inspection', {}).get('units', {}).get('consistent') is True
                and all(returned.get('frame', {}).get(k) == identity[k] for k in ('pid', 'tid')),
                'returned cash journal/saved reference/owned window differs')
        reopen = [r for r in records if r.get('kind') == 'reopen']
        require(len(reopen) == 1, 'reopen missing/repeated')
        if reopen:
            r = reopen[0]; trip = r.get('round_trip', {})
            if descriptions:
                issues += judge_layout(descriptions[1], r.get('reopened'))
                issues += judge_captions(descriptions[1], r.get('reopened'))
            linked = (r.get('calls') or [{}])[-1]
            require(r.get('closed_before_reopen') is True and r.get('before_reopen', {}).get('open') is False
                    and bool(r.get('before_reopen', {}).get('windows'))
                    and all(w.get('exists') is False for w in r['before_reopen']['windows']), 'old result windows not destroyed')
            require(trip.get('reopen_return') == trip.get('reopen_same') == '1' and not trip.get('reopen_error')
                    and not trip.get('journal_error') and linked.get('journal_link') == linked.get('journal_source') == source
                    and r.get('reopened', {}).get('found') is True, 'reopened saved reference/basis/window differs')
            later = [s for s in records if s.get('index', 0) > r['index']]
            require(any(s.get('kind') == 'check' and s.get('target') == 'Комментарий'
                        and s.get('state', {}).get('text', '').strip() == 'Harness77 основание 040' for s in later), 'reopened comment not read')
        require(captures and any(r.get('kind') == 'value' and r.get('target') == 'Комментарий'
                    and r.get('index', 0) < captures[0].get('index', 0)
                    and r.get('round_trip', {}).get('value') == 'Harness77 основание 040' for r in records), 'form comment attribute not read before save')
    require(all(r.get('status') == 'passed' and not r.get('issue') for r in records), 'unexpected scenario failure')
    for r in records:
        if r.get('kind') == 'input':
            a = r.get('action', {}); layouts = a.get('character_input_layouts', [])
            require(a.get('text_typed') == r.get('text') and [v.get('code') for v in layouts] ==
                    [c.encode('cp1251')[0] for c in r.get('text', '') if ord(c) >= 128], 'input text/layout evidence corrupted')
            require(all(v.get('pid') == identity['pid'] and v.get('tid') == identity['tid']
                    and str(v.get('desktop', '')).startswith('harness77_')
                    and v.get('caller_active') == v.get('server_active') == v.get('requested')
                    and v.get('requested', 0) & 0xffff == 0x419
                    and v.get('caller_restored') is True and v.get('server_restored') is True for v in layouts), 'foreign/unrestored input layouts')
    return issues


def check(folder, kind='success', expected_hash=None):
    from form_launcher77 import configuration_description
    from verify_document_form77 import BASE_MD_SHA256
    md = folder / 'configuration/1Cv7.MD'
    if digest(md) != BASE_MD_SHA256:
        raise ValueError('saved configuration bytes differ from pinned source')
    target = configuration_description(md, 'Документ.ПриходныйОрдер')[0]
    new_description = basis.runtime_description(target, dict(caption_control='ндСфетФактураУжеСформирована', caption_text='Не требуется'))
    returned = configuration_description(md, 'Журнал.Касса.ФормаСписка.ФормаСписка')[0]
    descriptions = (new_description, target, returned)
    inspection = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text(encoding='utf-8'))['identity']
    final = example.state(created=kind not in ('cancel', 'cancel-kind', 'wrong-limit', 'wrong-kind'))
    mapped = 'wrong-reopen' if kind in ('wrong-limit', 'wrong-kind') else kind
    result = document_check(folder, mapped, expected_hash, readback=final,
        step_validator=lambda records, _: step_issues(records, kind, inspection, identity, descriptions), allow_fixture_posting=True)
    result['kind'] = kind
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    checks = [e for e in events if e.get('kind') == 'ert' and e.get('name') == 'check']
    if len(checks) != 1 or checks[0]['value'].splitlines().count('fixture-initial:' + initial(kind)) != 1:
        result['issues'].append('independent initial basis/neighbors/entries differ')
    controller = (folder / 'native/ert-controller.1s').read_text(encoding='utf-8')
    outside_setup = controller.split('Функция Harness77ПодготовитьДанные()', 1)[1].split('КонецФункции', 1)[1]
    if any(s in outside_setup for s in ('.Копировать(', '.Новый(', '.Записать(', '.Удалить(', '.Провести(', '.ВводНаОсновании(', '.АктивизироватьОбъект(', 'УстановитьИнтервал(')):
        result['issues'].append('programmatic creation/basis/write/post/delete/navigation found')
    return result

def disabled_guard(folder):
    """The rejected first candidate provides a real disabled-menu observation."""
    import scenario77
    from verify_journal_copy77 import example as copy_example
    result = attempt(folder)
    issues = result['issues']
    report = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    platform = json.loads((folder / 'platform-result.json').read_text(encoding='utf-8'))
    inspection = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    records = inspection['steps']
    expected = '0|' + copy_example.state().replace('039', '040')
    ops = {o['name']: o for o in platform['operations']}
    if report['status'] != 'failed' or report['platform_checked'] is not True or ops['verify'].get('value') != expected:
        issues.append('disabled candidate outcome/persisted sources differ')
    if len(records) != 3 or [r['kind'] for r in records] != ['journal_period', 'find_document', 'journal_basis']:
        issues.append('disabled candidate did not stop at basis command')
        return result
    record = records[-1]
    before = record.get('before_basis', {})
    try:
        journal77.checked_cursor(before, inspection)
    except RuntimeError as error:
        issues.append(str(error))
    menu = record.get('menu', {})
    if not (before.get('journal_value') == expected and before.get('journal_current') == records[1].get('round_trip', {}).get('journal_current')
            and menu.get('command') == basis.BASIS_COMMAND and menu.get('enabled') is False and menu.get('flags', 0) & 3
            and 'ввести на основании' in menu.get('caption', '').casefold()
            and menu.get('main') == inspection['chain'][-1]['hwnd'] and not record.get('action')
            and not record.get('kind_window') and not record.get('round_trip') and 'disabled' in str(record.get('issue'))
            and record.get('calls') == [dict(before, number=-108003)]):
        issues.append('disabled menu did not prevent dispatch/creation')
    raw = scenario77.answer(read(folder / 'native/form-step--108003-done'))
    if any(before.get(k) != v for k, v in raw.items()):
        issues.append('disabled candidate raw cursor/state response differs')
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    for name, marker in (('check', 'fixture-initial:'), ('verify', 'fixture-value:')):
        answers = [e for e in events if e.get('kind') == 'ert' and e.get('name') == name]
        if len(answers) != 1 or answers[0]['value'].splitlines().count(marker + expected) != 1:
            issues.append('disabled candidate raw ' + name + ' state differs')
    for item in report.get('result_files', []):
        if item.get('sha256') and digest(folder / item['path']) != item['sha256']:
            issues.append('disabled candidate result file differs: ' + item['path'])
    result.update(guard_verified=not issues, menu=menu)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('suite', 'excluded-run', 'test-log', 'regression-report', 'control-report'):
        parser.add_argument('--' + name, type=Path, action='append', default=[])
    parser.add_argument('--blocked-run', type=Path, required=True)
    parser.add_argument('--disabled-run', type=Path, required=True)
    parser.add_argument('--excluded-test-log', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    issues, runs, suites = [], [], []
    for folder in args.suite:
        suites.append(verify_suite(folder.resolve(), native=True))
        for row in json.loads((folder / 'suite.json').read_text(encoding='utf-8'))['scenarios']:
            kind = row['id'] if row['id'] in ('cancel-kind', 'cancel', 'wrong', 'wrong-limit', 'wrong-kind') else 'success'
            runs.append(check((folder / row['report']['path']).parent.resolve(), kind, row['report']['sha256']))
    if sorted(r['kind'] for r in runs) != sorted(['success'] * 5 + ['cancel-kind', 'cancel', 'wrong', 'wrong-limit', 'wrong-kind']):
        issues.append('required ten runs missing')
    blocked = json.loads((args.blocked_run / 'run.json').read_text(encoding='utf-8'))
    if not (blocked.get('status') == 'blocked' and blocked.get('platform_checked') is False
            and 'verified base copy' in str(blocked.get('reason')) and not (args.blocked_run / 'native/ert-events.jsonl').exists()):
        issues.append('no-copy guard not confirmed')
    attempts = [attempt(p) for p in args.excluded_run]
    disabled = disabled_guard(args.disabled_run.resolve())
    issues.extend(disabled['issues'])
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
    sources = ['research/forms/journal77.py', 'research/forms/journal_basis77.py', 'research/forms/journal_copy77.py', 'research/forms/scenario77.py',
        'research/forms/form_launcher77.py', 'research/forms/fixture77.py', 'research/forms/form_window77.py',
        'research/forms/tests/test_journal_basis77.py', 'examples/journal-basis/scenario.toml',
        'examples/journal-basis/prepare.py', 'scripts/verify_journal_basis77.py', 'scripts/verify_journal_unpost77.py',
        'scripts/verify_document_form77.py', 'scripts/verify_suite77.py', 'scripts/verify_journal_document77.py',
        'scripts/verify_journal_deletion77.py', 'scripts/verify_journal_basis_controls77.py']
    result = dict(status='failed' if issues else 'passed', issues=issues, runs=runs, suites=suites, excluded_attempts=attempts,
        blocked_run=dict(run_id=blocked['run_id'], sha256=digest(args.blocked_run / 'run.json')),
        disabled_guard=disabled,
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
