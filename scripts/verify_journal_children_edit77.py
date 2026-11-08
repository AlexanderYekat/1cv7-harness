"""Independently verify task 044 UI editing, exact identities, raw calls and preservation."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tomllib

from verify_document_form77 import ROOT, BASE_MD_SHA256, digest, read, check as document_check
from verify_journal_children_mixed77 import layout_issues
from verify_suite77 import verify as verify_suite

sys.path.insert(0, str(ROOT / 'research/forms'))
import scenario77
from form_launcher77 import configuration_description
from harness77.metadata77 import Metadata

spec = importlib.util.spec_from_file_location('children_edit_example', ROOT / 'examples/journal-children-edit/prepare.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def step_issues(records, kind, inspection, identity, descriptions):
    issues = []
    def require(ok, message):
        if not ok:
            issues.append(message)
    baseline, final = example.state(), example.state(kind != 'cancel')
    canonical = scenario77.resolve(scenario77.steps(tomllib.loads(example.case_scenario(kind))['platform']['parameters']), descriptions[1])
    require(len(records) == len(canonical), 'scenario truncated/extended')
    for actual, declared in zip(records, canonical):
        require(all(actual.get(k) == v for k, v in declared.items()), 'declared step differs: ' + str(declared['index']))
        require(actual.get('status') == 'passed' and not actual.get('issue'), 'UI step failed')
    if len(records) < 3:
        return issues
    period, search, opened = records[:3]
    import journal77
    try:
        journal77.check_period(period, period)
    except (RuntimeError, KeyError, ValueError) as error:
        issues.append('period evidence differs: ' + str(error))
    require(period.get('action', {}).get('command') == 0x8071, 'native period command missing')
    handles = {str(w['hwnd']) for w in inspection['chain'][:2]}
    source_rows = search.get('search', [])
    require(search.get('cursor_verified') is True and search.get('open') is False
            and not search.get('action') and bool(source_rows) and len(source_rows) <= 100, 'source search/open differs')
    for i, row in enumerate(source_rows):
        key, trip = row.get('action', {}), row.get('round_trip', {})
        require(key.get('key') == ('End' if i == 0 else 'Up') and key.get('returned') is True
                and key.get('identity_rechecked') is True and key.get('id') == 4151, 'source search key differs')
        require(trip.get('returned') is True and trip.get('complete') is True and not trip.get('diagnostics')
                and not trip.get('journal_error') and str(trip.get('journal_hwnd')) in handles
                and trip.get('journal_match') == str(int(i == len(source_rows)-1)), 'source cursor response differs')
    require(search.get('calls') == [dict(row.get('round_trip', {}), number=-101000-i) for i, row in enumerate(source_rows)], 'source calls differ')
    before = opened.get('before_children', {})
    require(before.get('journal_id') and before.get('journal_current') == source_rows[-1]['round_trip'].get('journal_current')
            and before.get('journal_value') == baseline and before.get('journal_match') == '1'
            and str(before.get('journal_hwnd')) in handles, 'source changed before children command')
    menu, action = opened.get('menu', {}), opened.get('action', {})
    require(menu.get('command') == 0x806C and menu.get('enabled') is True
            and menu.get('caption') == 'Под&чиненные документы' and menu.get('main') == inspection['chain'][-1]['hwnd'], 'children menu differs')
    require(action.get('command') == 0x806C and action.get('message') == 'WM_COMMAND'
            and action.get('hwnd') == inspection['chain'][1]['hwnd'] and action.get('returned') is True
            and action.get('requested') is True and action.get('identity_rechecked') is True, 'children command differs')
    children, document = opened.get('children_form', {}), opened.get('opened_form', {})
    for description, measured in zip(descriptions[:2], (children, document)):
        require(measured.get('found') is True and not layout_issues(description, measured), 'owned form layout/caption differs')
    ch = {str(w['hwnd']) for w in children.get('chain', [])[:2]}
    dh = {str(w['hwnd']) for w in document.get('chain', [])[:2]}
    require(ch and dh and not ch & dh and not dh & handles, 'document reuses journal HWNDs')
    old = {w['hwnd'] for w in opened.get('before_windows', [])}
    mdi = inspection['chain'][2]['hwnd']
    for name in ('before_windows', 'children_windows', 'opened_windows'):
        require(all(w.get('pid') == identity['pid'] and w.get('tid') == identity['tid'] for w in opened.get(name, [])), 'foreign inventory PID/TID')
    frames = [w for w in opened.get('children_windows', []) if w.get('parent') == mdi and w['hwnd'] not in old and w.get('visible')]
    require(len(frames) == 1 and frames[0]['hwnd'] == children['chain'][1]['hwnd']
            and frames[0]['text'] == descriptions[0]['form']['caption'] + ' ' + before['journal_current'], 'children frame/caption differs')
    new_frames = [w for w in opened.get('opened_windows', []) if w.get('parent') == mdi
                  and w['hwnd'] not in {w['hwnd'] for w in opened.get('children_windows', [])} and w.get('visible')]
    require(len(new_frames) == 1 and new_frames[0]['hwnd'] == document['chain'][1]['hwnd'], 'opened document frame differs')
    scanned = opened.get('child_search', [])
    require(len(scanned) == 3 and opened.get('limit') == 100, 'mixed search length differs')
    require([r.get('round_trip', {}).get('journal_kind') for r in scanned] == ['ПриходныйОрдер','СчетФактура','ПриходныйОрдер'], 'mixed traversal differs')
    table = {c['hwnd'] for c in children.get('controls', []) if c.get('id') == 4151}
    selected = opened.get('selected_child', {})
    require(selected.get('journal_id') and selected.get('journal_id') == selected.get('journal_expected_id'), 'exact target missing')
    ids = []
    for i, row in enumerate(scanned):
        key, trip = row.get('action', {}), row.get('round_trip', {})
        require(key.get('key') == ('End' if i == 0 else 'Up') and key.get('hwnd') in table
                and key.get('returned') is True and key.get('identity_rechecked') is True and key.get('id') == 4151, 'child search key/window differs')
        require(str(trip.get('journal_hwnd')) in ch and trip.get('journal_match') == str(int(i == 2))
                and trip.get('journal_value') == baseline and trip.get('journal_source_id') == trip.get('journal_link_id') == before['journal_id']
                and trip.get('journal_link') == '1' and trip.get('journal_empty') == '0'
                and trip.get('journal_comment') == 'Harness77 подчиненный 044'
                and trip.get('journal_expected_id') == selected.get('journal_id'), 'mixed row identity/link/state differs')
        require(trip.get('returned') is True and trip.get('complete') is True and not trip.get('diagnostics') and not trip.get('journal_error'), 'mixed row response incomplete')
        try:
            values = json.loads('[' + trip['journal_id'][1:-1] + ']')
            require(values[0] == 'O' and int(values[3]) == descriptions[2].numbers['O',trip['journal_kind'].casefold()], 'typed reference differs from metadata')
        except (KeyError, ValueError, TypeError, IndexError):
            issues.append('invalid typed row reference')
        ids.append(trip.get('journal_id'))
    require(len(set(ids)) == 3 and selected == scanned[-1].get('round_trip'), 'selected row differs')
    recheck = opened.get('selection_recheck', {})
    require({k:v for k,v in recheck.items() if k.startswith('journal_')} == {k:v for k,v in selected.items() if k.startswith('journal_')}
            and recheck.get('returned') is True and recheck.get('complete') is True and not recheck.get('diagnostics'), 'fresh recheck differs')
    require(opened.get('open_action', {}).get('key') == 'Enter' and opened['open_action'].get('hwnd') in table
            and opened['open_action'].get('returned') is True and opened['open_action'].get('identity_rechecked') is True, 'Enter differs')
    require(opened.get('edit_handoff_verified') is True and opened.get('exact_selection_verified') is True
            and not opened.get('document_close') and not opened.get('children_close'), 'handoff closed form prematurely')
    def child_response(trip, windows, state, document_open=False):
        require(trip.get('returned') is True and trip.get('complete') is True and not trip.get('diagnostics') and not trip.get('journal_error')
                and trip.get('journal_id') == trip.get('journal_expected_id') == selected.get('journal_id')
                and trip.get('journal_source_id') == trip.get('journal_link_id') == before['journal_id']
                and trip.get('journal_link') == trip.get('journal_match') == '1' and trip.get('journal_value') == state
                and trip.get('journal_kind') == trip.get('journal_expected_kind') == 'ПриходныйОрдер'
                and str(trip.get('journal_hwnd')) in windows, 'opened/returned child identity/state differs')
        if document_open:
            require(trip.get('journal_opened') == '1', 'saved document context not verified')
    child_response(opened.get('opened_child', {}), dh, baseline, True)
    calls = [dict(before, number=-110001)] + [dict(r['round_trip'], number=-111001-i) for i,r in enumerate(scanned)]
    calls += [dict(recheck, number=-111900), dict(opened.get('opened_child', {}), number=-112001)]
    require(opened.get('calls') == calls, 'handoff raw-call sequence differs')
    reopening = [r for r in records if r.get('kind') == 'reopen']
    require(len(reopening) == 1, 'reopening missing/extra')
    if len(reopening) != 1:
        return issues
    reopened = reopening[0]
    require(reopened.get('closed_before_reopen') is True and all(w.get('exists') is False for w in reopened.get('before_reopen', {}).get('windows', []))
            and bool(reopened.get('before_reopen', {}).get('windows')), 'old document windows survived reopening')
    require(reopened.get('round_trip', {}).get('reopen_return') == reopened.get('round_trip', {}).get('reopen_same') == '1', 'reopened another reference')
    current = reopened.get('reopened', {})
    require(current.get('found') is True and not layout_issues(descriptions[1], current), 'reopened layout differs')
    rh = {str(w['hwnd']) for w in current.get('chain', [])[:2]}
    require(not rh & ch and not rh & handles, 'reopened form uses journal windows')
    inventory = opened.get('opened_windows', []) + opened.get('editing_return', {}).get('after_windows', [])
    for form_state in (children, document):
        for window in form_state.get('chain', [])[:2]:
            require(any(w['hwnd'] == window['hwnd'] and w.get('pid') == identity['pid'] and w.get('tid') == identity['tid'] for w in inventory), 'foreign inspected PID/TID')
    before_reopen = records[3:reopened['index']-1]
    require([r.get('target') for r in before_reopen if r.get('kind') == 'input'] == ['Сумма','Комментарий'], 'UI inputs missing/reordered')
    for r in before_reopen:
        if r.get('kind') in ('input','click'):
            from form_window77 import window_ids
            control_id = window_ids(descriptions[1])[r['record_id']]
            control = next(c for c in document['controls'] if c['id'] == control_id)
            require(r.get('action', {}).get('returned') is True and r['action'].get('identity_rechecked') is True, 'UI mutation not acknowledged')
            require(r['action'].get('control_id') == control_id and r['action'].get('requested') is True, 'UI mutation targets another control')
            if r['kind'] == 'click':
                require(r['action'].get('message') == 'BM_CLICK' and r['action'].get('button', {}).get('hwnd') == control['hwnd'], 'save/post targets another HWND')
            else:
                require(r['action'].get('message') == 'WM_CHAR' and r['action'].get('field', {}).get('hwnd') == control['hwnd']
                        and r['action'].get('text') == r['text'], 'input field/text differs')
    if kind == 'cancel':
        require([r.get('kind') for r in before_reopen[-2:]] == ['close_form','dialog'], 'cancel close chain differs')
        answer = before_reopen[-1].get('answer', {})
        require(answer.get('requested') is True and answer.get('identity_rechecked') is True
                and answer.get('button', {}).get('text', '').replace('&','') == 'Нет', 'cancellation saved or answered wrong button')
    else:
        require([r.get('target') for r in before_reopen if r.get('kind') == 'click'] == ['Записать','ОК'], 'UI save/post missing/reordered')
    after_reopen = records[reopened['index']:]
    comment = 'Harness77 подчиненный 044' if kind == 'cancel' else example.COMMENT
    for field, value in [('Сумма','50' if kind == 'cancel' else '75'), ('Комментарий',comment)]:
        matches = [r for r in after_reopen if r.get('kind') == 'value' and r.get('target') == field]
        require(len(matches) == 1 and matches[0].get('round_trip', {}).get('value') == value, 'reopened field differs: ' + field)
    checks = [r for r in after_reopen if r.get('kind') == 'check' and r.get('target') == 'Комментарий']
    require(len(checks) == 1 and checks[0].get('state', {}).get('text', '').strip() == comment, 'reopened comment window differs')
    returns = opened.get('editing_return', {})
    require(returns.get('return_verified') is True and not returns.get('issue'), 'return to source failed')
    require(all(w.get('pid') == identity['pid'] and w.get('tid') == identity['tid'] for w in returns.get('before_windows', []) + returns.get('after_windows', [])), 'foreign return inventory PID/TID')
    for window in current.get('chain', [])[:2]:
        require(any(w['hwnd'] == window['hwnd'] and w.get('pid') == identity['pid'] and w.get('tid') == identity['tid']
                    for w in returns.get('before_windows', [])), 'foreign reopened PID/TID')
    child_response(returns.get('before_close', {}), rh, final, True)
    child_response(returns.get('returned_child', {}), ch, final)
    for name, hwnd in [('document_close', current.get('chain',[{},{}])[1].get('hwnd')), ('children_close', children['chain'][1]['hwnd'])]:
        close = returns.get(name, {})
        require(close.get('hwnd') == hwnd and close.get('message') == 'WM_CLOSE' and close.get('requested') is True
                and close.get('returned') is True and close.get('destroyed') is True and close.get('identity_rechecked') is True, 'return closed wrong window')
        require(not close.get('answer') or close['answer'].get('button', {}).get('id') == 7, 'automatic return saved changes')
    after = returns.get('after_children', {})
    require(all(after.get(k) == before.get(k) for k in ('journal_id','journal_current','journal_hwnd','journal_posted','journal_deleted'))
            and after.get('journal_value') == final and after.get('returned') is True and after.get('complete') is True, 'source return identity/state differs')
    require(not any(w.get('parent') == mdi and w['hwnd'] not in old for w in returns.get('after_windows', [])), 'extra MDI frame left')
    require(returns.get('calls') == [dict(returns.get(name, {}), number=number) for name,number in
            [('before_close',-112002),('returned_child',-111902),('after_children',-113002)]], 'return raw calls differ')
    return issues


def check(folder, kind='success', expected_hash=None):
    md = folder / 'configuration/1Cv7.MD'
    if digest(md) != BASE_MD_SHA256:
        raise ValueError('configuration differs from pinned source')
    inspection = json.loads((folder / 'form/form-window.json').read_text('utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text('utf-8'))['identity']
    descriptions = [configuration_description(md, name)[0] for name in ('Журнал.Общий.ФормаСписка.ФормаСписка','Документ.ПриходныйОрдер')]
    descriptions.append(Metadata(md.read_bytes()))
    final = example.state(kind != 'cancel')
    result = document_check(folder, 'wrong' if kind == 'wrong' else 'success', expected_hash,
        readback=final, allow_fixture_posting=True,
        step_validator=lambda records, _: step_issues(records, kind, inspection, identity, descriptions))
    result['kind'] = kind
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    checks = [e for e in events if e.get('kind') == 'ert' and e.get('name') == 'check']
    if len(checks) != 1 or checks[0]['value'].splitlines().count('fixture-initial:' + example.state()) != 1:
        result['issues'].append('initial saved data/entries differ')
    for trip in inspection['steps'][2].get('editing_return', {}).get('calls', []):
        n = trip['number']
        raw = scenario77.answer(read(folder / 'native' / f'form-step-{n}-done'))
        messages, complete = scenario77.messages(read(folder / 'native/Протоколы проверки' / f'step-{n}.txt'), f'{result["run_id"]}:step:{n}')
        phase = [e for e in events if e.get('kind') == 'phase' and e.get('name') == f'step-{n}' and e.get('value') == 'ok']
        if (len(phase) != 1 or not complete or messages != trip.get('messages')
                or {k:v for k,v in trip.items() if k.startswith('journal_')} != raw):
            result['issues'].append('raw return response/protocol differs: ' + str(n))
    controller = (folder / 'native/ert-controller.1s').read_text('utf-8')
    canonical = tomllib.loads(example.case_scenario(kind))['platform']['parameters']
    for function, body in [('Harness77ПодготовитьДанные()',canonical['fixture_setup']),('Harness77ПроверитьДанные(Объект77)',canonical['fixture_verify'])]:
        marker = 'Функция ' + function + '\n'
        if controller.count(marker) != 1 or controller.split(marker,1)[1].split('КонецФункции',1)[0].strip() != body.strip():
            result['issues'].append('fixture code differs: ' + function)
    outside = controller.split('Функция Harness77ПодготовитьДанные()',1)[1].split('КонецФункции',1)[1]
    for forbidden in ('.Новый(','.Записать(','.Провести(','.Удалить(','.ПодчинениеДокументу(','.АктивизироватьОбъект('):
        if forbidden in outside:
            result['issues'].append('programmatic mutation: ' + forbidden)
    if 'ОткрытьФорму(Объект77Подготовки.ПолучитьЗначение(17), Контекст77, 0)' not in controller:
        result['issues'].append('controller reopens a different target')
    report = json.loads((folder / 'run.json').read_text('utf-8'))
    if report.get('shutdown', {}).get('forced_cleanup') is not False:
        result['issues'].append('forced cleanup in accepted run')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--blocked-run', type=Path)
    for name in ('test-log','regression-report','control-report','support-report'):
        p.add_argument('--'+name,type=Path,action='append',default=[])
    a = p.parse_args()
    suites, runs = [], []
    for folder in a.suite:
        folder = folder.resolve()
        suites.append(verify_suite(folder, native=True))
        for row in json.loads((folder / 'suite.json').read_text('utf-8'))['scenarios']:
            kind = row['id'] if row['id'] in ('wrong','cancel') else 'success'
            runs.append(check((folder / row['report']['path']).parent, kind, row['report']['sha256']))
    issues = [i for row in suites + runs for i in row['issues']]
    blocked = None
    if a.blocked_run:
        blocked = json.loads((a.blocked_run/'run.json').read_text('utf-8'))
        if (blocked.get('status') != 'blocked' or blocked.get('platform_checked') is not False
                or 'verified base copy' not in str(blocked.get('reason'))
                or (a.blocked_run/'native/ert-events.jsonl').exists()):
            issues.append('no-copy guard failed')
        if sorted(r['kind'] for r in runs) != sorted(['success']*3+['cancel','wrong']):
            issues.append('required five acceptance runs missing')
    for path in a.test_log:
        content = path.read_text('utf-8')
        if '\nRan ' not in content or not content.rstrip().endswith(('OK','OK (skipped=3)')):
            issues.append(str(path)+': test log failed')
    for path in a.regression_report+a.control_report+a.support_report:
        value=json.loads(path.read_text('utf-8'))
        if value.get('status')!='passed' or value.get('issues'):
            issues.append(str(path)+': supporting verification failed')
        if path in a.control_report and (value.get('verifier_sha256')!=digest(Path(__file__))
                or value.get('baseline_run') not in [r['run_id'] for r in runs]
                or not value.get('controls') or not all(c.get('rejected') for c in value['controls'])):
            issues.append(str(path)+': invalid controls')
    sources=['research/forms/'+f for f in ('journal_children77.py','scenario77.py','form_launcher77.py','fixture77.py','form_window77.py','journal77.py','journal_basis77.py','tests/test_journal_children_edit77.py')]
    sources += ['examples/journal-children-edit/'+f for f in ('prepare.py','scenario.toml')]
    sources += ['scripts/verify_journal_children_edit77.py','scripts/verify_journal_children_edit_controls77.py','scripts/verify_journal_children_mixed77.py','scripts/verify_document_form77.py']
    result = dict(status='failed' if issues else 'passed', issues=issues, suites=suites, runs=runs,
                  verifier_sha256=digest(Path(__file__)), sources={s:digest(ROOT/s) for s in sources},
                  blocked_run=dict(run_id=blocked['run_id'],sha256=digest(a.blocked_run/'run.json')) if blocked else None,
                  test_logs={str(p):digest(p) for p in a.test_log},
                  regressions={str(p):digest(p) for p in a.regression_report},
                  controls={str(p):digest(p) for p in a.control_report},
                  supporting_evidence={str(p):digest(p) for p in a.support_report})
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(status=result['status'], issues=issues, runs=len(runs)), ensure_ascii=False))
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
