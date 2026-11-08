"""Independently verify 041 native commands, exact links, raw responses and preservation."""
import argparse
import json
from pathlib import Path
import sys
import tomllib

from verify_document_form77 import ROOT, BASE_MD_SHA256, digest, read, check as document_check
from verify_journal_deletion77 import attempt
from verify_suite77 import verify as verify_suite

sys.path.insert(0, str(ROOT / 'research/forms'))
import scenario77
from form_launcher77 import configuration_description
from form_window77 import judge_layout, judge_captions, expected_geometry, edged_ids, fit_units, inside

import importlib.util
spec = importlib.util.spec_from_file_location('children_example', ROOT / 'examples/journal-children/prepare.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def layout_issues(description, inspection):
    """Recompute geometry from measured rectangles instead of trusting saved fit flags."""
    import copy
    actual = copy.deepcopy(inspection)
    measured = {c['id']: tuple(c['rect']) for c in actual.get('controls', [])}
    actual['units'] = fit_units(expected_geometry(description), measured, edged=edged_ids(description))
    issues = []
    if json.loads(json.dumps(actual['units'])) != inspection.get('units'):
        issues.append('saved geometry fit differs from measured rectangles')
    client = actual.get('chain', [{}])[0].get('client_size', [0, 0])
    for control in actual.get('controls', []):
        control['inside_client'] = inside(tuple(control['rect']), client)
    if description.get('browser'):
        tables = [c for c in actual.get('controls', []) if c.get('id') == 4151]
        if (len(tables) != 1 or tables[0].get('class', '').casefold() != 'browse'
                or not tables[0].get('visible') or not tables[0].get('enabled')
                or not tables[0]['inside_client'] or any(v <= 0 for v in tables[0]['rect'][2:])):
            issues.append('journal browse rectangle/class/state is invalid')
    return issues + judge_layout(description, actual) + judge_captions(description, actual)


def step_issues(records, kind, inspection, identity, descriptions):
    issues = []
    def require(ok, message):
        if not ok:
            issues.append(message)
    baseline = example.state()
    require([r.get('kind') for r in records[:2]] == ['journal_period', 'find_document'], 'period/search prefix missing')
    if len(records) < 2:
        return issues
    period, search = records[:2]
    try:
        import journal77
        journal77.check_period(period, period)
    except (RuntimeError, KeyError, ValueError) as error:
        issues.append('period evidence differs: ' + str(error))
    require(period.get('status') == 'passed' and period.get('start') == '2026-07-31'
            and period.get('end') == '2026-08-01' and period.get('action', {}).get('command') == 0x8071,
            'native period action missing')
    rows = search.get('search', [])
    handles = {str(w['hwnd']) for w in inspection.get('chain', [])[:2]}
    require(search.get('open') is False and not search.get('action') and not search.get('opened_form'), 'source search opened a form')
    require(search.get('calls') == [dict(r.get('round_trip', {}), number=-101000-i) for i, r in enumerate(rows)], 'cursor calls differ')
    require(bool(rows) and len(rows) <= search.get('limit', 100), 'source search unbounded/missing')
    for i, row in enumerate(rows):
        a, t = row.get('action', {}), row.get('round_trip', {})
        require(a.get('key') == ('End' if i == 0 else 'Up') and a.get('id') == 4151
                and a.get('returned') is True and a.get('identity_rechecked') is True, 'cursor key differs')
        require(t.get('returned') is True and t.get('complete') is True and not t.get('diagnostics')
                and not t.get('journal_error') and str(t.get('journal_hwnd')) in handles,
                'source cursor response invalid/foreign')
        require(t.get('journal_match') == ('1' if i == len(rows)-1 and kind != 'wrong-limit' else '0'), 'source cursor match differs')
    if kind == 'wrong-limit':
        require(len(records) == 2 and len(rows) == 1 and search.get('status') == 'failed'
                and 'search limit' in str(search.get('issue')), 'limited source search sent Enter/command')
        return issues
    require(search.get('cursor_verified') is True and search.get('status') == 'passed', 'source selection unverified')
    require(len(records) == 3 and records[-1].get('kind') == 'journal_children', 'subordinate step missing/extra')
    if len(records) != 3:
        return issues
    r = records[2]
    before, selected, after = (r.get(k, {}) for k in ('before_children', 'selected_child', 'after_children'))
    require(before.get('journal_current') == rows[-1]['round_trip'].get('journal_current')
            and before.get('journal_match') == '1' and before.get('journal_id')
            and str(before.get('journal_hwnd')) in handles and before.get('journal_value') == baseline,
            'source changed before command')
    menu, action = r.get('menu', {}), r.get('action', {})
    require(menu.get('enabled') is True and menu.get('command') == 0x806C
            and menu.get('caption') == 'Под&чиненные документы'
            and menu.get('main') == inspection['chain'][-1]['hwnd'], 'native subordinate menu differs')
    require(action.get('requested') is True and action.get('returned') is True
            and action.get('identity_rechecked') is True and action.get('command') == 0x806C
            and action.get('message') == 'WM_COMMAND' and action.get('hwnd') == inspection['chain'][1]['hwnd'],
            'native subordinate command target differs')
    inventories = [r.get(k, []) for k in ('before_windows', 'children_windows', 'opened_windows', 'after_windows')]
    for windows in inventories:
        require(all(w.get('pid') == identity['pid'] and w.get('tid') == identity['tid'] for w in windows), 'foreign process/thread in inventory')
    old = {w['hwnd'] for w in inventories[0]}
    mdi = inspection['chain'][2]['hwnd']
    frames = [w for w in inventories[1] if w.get('parent') == mdi and w['hwnd'] not in old and w.get('visible')]
    require(len(frames) == 1 and frames[0].get('text') == descriptions[0]['form']['caption'] + ' ' + before.get('journal_current', ''),
            'subordinate caption/new frame differs')
    children = r.get('children_form', {})
    require(children.get('found') is True and children.get('units', {}).get('consistent') is True
            and not layout_issues(descriptions[0], children), 'subordinate journal layout differs')
    child_handles = {str(w['hwnd']) for w in children.get('chain', [])[:2]}
    require(len(frames) == 1 and len(children.get('chain', [])) >= 2 and children['chain'][1]['hwnd'] == frames[0]['hwnd'],
            'subordinate frame inspection differs')
    require(r.get('selection_key', {}).get('key') == 'End' and r['selection_key'].get('id') == 4151
            and r['selection_key'].get('returned') is True and r['selection_key'].get('identity_rechecked') is True,
            'subordinate cursor key differs')
    table_handles = {c['hwnd'] for c in children.get('controls', []) if c.get('id') == 4151}
    require(r.get('selection_key', {}).get('hwnd') in table_handles, 'selection key targets another list')
    require(selected.get('journal_value') == baseline and selected.get('journal_source_id') == before.get('journal_id')
            and str(selected.get('journal_hwnd')) in child_handles and selected.get('journal_expected_id'), 'selected child source/window/state differs')
    require(selected.get('journal_empty') == ('1' if kind == 'empty' else '0'), 'empty journal outcome differs')
    expected_match = '0' if kind in ('empty', 'wrong-reference') else '1'
    require(selected.get('journal_match') == expected_match, 'exact child match differs')
    if kind != 'empty':
        require(selected.get('journal_link') == '1' and selected.get('journal_link_id') == before.get('journal_id'), 'selected child belongs to another source')
        require(selected.get('journal_comment') == 'Harness77 подчиненный 041 ' + ('1' if kind == 'other' else '2'), 'selected child comment differs')
    if kind == 'wrong-reference':
        require(selected.get('journal_id') != selected.get('journal_expected_id') and not r.get('open_action')
                and not r.get('opened_child') and r.get('status') == 'failed'
                and 'exact saved child reference' in str(r.get('issue'))
                and r.get('children_cleanup', {}).get('destroyed') is True, 'foreign expected child was opened or not cleaned up')
        require([t.get('number') for t in r.get('calls', [])] == [-110001, -111001], 'wrong-reference calls differ')
        return issues
    require(r.get('exact_selection_verified') is True and r.get('return_verified') is True
            and r.get('status') == 'passed' and not r.get('issue'), 'subordinate selection/return failed')
    boundary = r.get('boundary_child', {})
    require(r.get('boundary_key', {}).get('key') == 'Up' and r['boundary_key'].get('returned') is True
            and r['boundary_key'].get('identity_rechecked') is True and r['boundary_key'].get('id') == 4151,
            'single-child boundary key missing')
    require(r.get('boundary_key', {}).get('hwnd') in table_handles, 'boundary key targets another list')
    require(boundary.get('journal_id') == selected.get('journal_id') and boundary.get('journal_match') == expected_match
            and boundary.get('journal_source_id') == before.get('journal_id')
            and boundary.get('journal_empty') == selected.get('journal_empty')
            and boundary.get('journal_value') == baseline and str(boundary.get('journal_hwnd')) in child_handles,
            'subordinate list has another row or changed its source/state')
    require(r.get('children_close', {}).get('destroyed') is True and r['children_close'].get('message') == 'WM_CLOSE'
            and r['children_close'].get('returned') is True and r['children_close'].get('identity_rechecked') is True,
            'subordinate journal not closed through UI')
    require(len(children.get('chain', [])) >= 2 and r['children_close'].get('hwnd') == children['chain'][1]['hwnd'], 'closed another subordinate frame')
    for name in ('document_close', 'children_close'):
        closing = r.get(name)
        if not closing:
            continue
        require(closing.get('requested') is True and closing.get('identity_rechecked') is True, 'close identity not checked')
        question, answer = closing.get('question'), closing.get('answer')
        if question:
            require(question.get('class') == '#32770' and scenario77.dialog_text(question).startswith('Сохранить Документ?')
                    and question.get('pid') == identity['pid'] and question.get('tid') == identity['tid']
                    and answer and answer.get('requested') is True and answer.get('identity_rechecked') is True
                    and answer.get('button', {}).get('id') == 7
                    and answer.get('button', {}).get('text', '').replace('&', '').strip() == 'Нет',
                    'read-only close saved or answered an unrelated question')
        else:
            require(not answer, 'answer without a save question')
    for key in ('journal_current', 'journal_id', 'journal_hwnd', 'journal_value', 'journal_posted', 'journal_deleted'):
        require(after.get(key) == before.get(key), 'source return differs: ' + key)
    require(r.get('round_trip') == after, 'final round trip differs')
    require(not any(w.get('parent') == mdi and w['hwnd'] not in old for w in inventories[3]), 'extra MDI frame left after return')
    if kind in ('cancel', 'empty'):
        require(not r.get('open_action') and not r.get('opened_child') and not r.get('opened_form'), 'cancel/empty opened a child')
        numbers = [-110001, -111001, -111003, -113001]
    else:
        require(selected.get('journal_id') == selected.get('journal_expected_id'), 'selected exact internal id differs')
        opened, document = r.get('opened_child', {}), r.get('opened_form', {})
        require(r.get('open_action', {}).get('key') == 'Enter' and r['open_action'].get('returned') is True
                and r['open_action'].get('identity_rechecked') is True, 'child Enter missing')
        require(r.get('open_action', {}).get('hwnd') in table_handles and r['open_action'].get('id') == 4151,
                'Enter targets another list')
        require(opened.get('journal_opened') == '1' and opened.get('journal_match') == '1'
                and opened.get('journal_id') == selected.get('journal_id') == opened.get('journal_expected_id')
                and opened.get('journal_source_id') == opened.get('journal_link_id') == before.get('journal_id')
                and opened.get('journal_link') == '1' and opened.get('journal_value') == baseline,
                'opened saved child/source/link differs')
        require(document.get('found') is True and document.get('units', {}).get('consistent') is True
                and not layout_issues(descriptions[1], document), 'opened document layout/captions differ')
        dh = {str(w['hwnd']) for w in document.get('chain', [])[:2]}
        require(str(opened.get('journal_hwnd')) in dh and not dh & child_handles and not dh & {str(h) for h in old}, 'opened document HWND reused/foreign')
        require(r.get('document_close', {}).get('destroyed') is True and r['document_close'].get('message') == 'WM_CLOSE'
                and r['document_close'].get('returned') is True, 'opened document not closed without save')
        require(len(document.get('chain', [])) >= 2 and r['document_close'].get('hwnd') == document['chain'][1]['hwnd'],
                'closed another document frame')
        returned = r.get('returned_child', {})
        require(returned.get('journal_id') == selected.get('journal_id') and returned.get('journal_match') == '1'
                and str(returned.get('journal_hwnd')) in child_handles and returned.get('journal_value') == baseline,
                'return to subordinate journal differs')
        numbers = [-110001, -111001, -111003, -112001, -111002, -113001]
    require([t.get('number') for t in r.get('calls', [])] == numbers, 'subordinate raw-call sequence differs')
    expected_trips = [before, selected, boundary] + ([] if kind in ('cancel', 'empty') else [r.get('opened_child'), r.get('returned_child')]) + [after]
    require(r.get('calls') == [dict(t or {}, number=n) for t, n in zip(expected_trips, numbers)], 'semantic/raw call evidence differs')
    return issues


def check(folder, kind='success', expected_hash=None):
    md = folder / 'configuration/1Cv7.MD'
    if digest(md) != BASE_MD_SHA256:
        raise ValueError('configuration differs from pinned source')
    children = configuration_description(md, 'Журнал.Общий.ФормаСписка.ФормаСписка')[0]
    target = configuration_description(md, 'Документ.ПриходныйОрдер')[0]
    # Only this explicitly declared static caption changes in the original opening handler.
    import copy
    target = copy.deepcopy(target)
    if kind != 'other':
        matches = [c for c in target['controls'] if c.get('identifier') == 'ндСфетФактураУжеСформирована']
        if len(matches) != 1 or matches[0]['class'] != 'STATIC':
            raise ValueError('runtime label contract differs')
        matches[0]['caption'] = 'Не требуется'
    inspection = json.loads((folder / 'form/form-window.json').read_text('utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text('utf-8'))['identity']
    mapped = 'wrong-reopen' if kind in ('wrong-limit', 'wrong-reference') else 'wrong' if kind == 'wrong' else 'success'
    result = document_check(folder, mapped, expected_hash, readback=example.state(), allow_fixture_posting=True,
        step_validator=lambda records, _: step_issues(records, kind, inspection, identity, (children, target)))
    result['kind'] = kind
    report = json.loads((folder / 'run.json').read_text('utf-8'))
    if report.get('shutdown', {}).get('forced_cleanup') is not False:
        result['issues'].append('accepted run required forced cleanup')
    events = [json.loads(line) for line in read(folder / 'native/ert-events.jsonl').splitlines()]
    checks = [e for e in events if e.get('kind') == 'ert' and e.get('name') == 'check']
    if len(checks) != 1 or checks[0]['value'].splitlines().count('fixture-initial:' + example.state()) != 1:
        result['issues'].append('independent initial documents/entries differ')
    controller = (folder / 'native/ert-controller.1s').read_text('utf-8')
    canonical = tomllib.loads((ROOT / 'examples/journal-children/scenario.toml').read_text('utf-8'))['platform']['parameters']
    setup = canonical['fixture_setup']
    if kind in ('other', 'empty'):
        setup = setup.replace('Возврат Объект77Подготовки.ПолучитьЗначение(2);',
                              'Возврат Объект77Подготовки.ПолучитьЗначение(' + ('1' if kind == 'other' else '3') + ');')
    for name, expected in (('Harness77ПодготовитьДанные()', setup), ('Harness77ПроверитьДанные(Объект77)', canonical['fixture_verify'])):
        marker = 'Функция ' + name + '\n'
        if controller.count(marker) != 1 or controller.split(marker, 1)[1].split('КонецФункции', 1)[0].strip() != expected.strip():
            result['issues'].append('fixture source differs from canonical example: ' + name)
    outside = controller.split('Функция Harness77ПодготовитьДанные()', 1)[1].split('КонецФункции', 1)[1]
    for forbidden in ('.Новый(', '.Записать(', '.Провести(', '.Удалить(', '.ВводНаОсновании(', '.ПодчинениеДокументу(', '.АктивизироватьОбъект(', 'УстановитьИнтервал('):
        if forbidden in outside:
            result['issues'].append('programmatic mutation/navigation: ' + forbidden)
    # Compare saved descriptions with the original MD, independently of the runner.
    if json.loads((folder / 'form/children-description.json').read_text('utf-8')) != children:
        result['issues'].append('saved subordinate description differs from MD')
    source = json.loads((folder / 'form/children-source.json').read_text('utf-8'))
    if source.get('md_sha256') != BASE_MD_SHA256 or source.get('form_object') != 'Журнал.Общий.ФормаСписка.ФормаСписка':
        result['issues'].append('subordinate description provenance differs')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('suite', 'test-log', 'regression-report', 'control-report', 'excluded-run'):
        p.add_argument('--' + name, type=Path, action='append', default=[])
    p.add_argument('--blocked-run', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    suites, runs, issues = [], [], []
    for folder in a.suite:
        folder = folder.resolve()
        suites.append(verify_suite(folder, native=True))
        for row in json.loads((folder / 'suite.json').read_text('utf-8'))['scenarios']:
            kind = row['id'] if row['id'] in ('other', 'empty', 'cancel', 'wrong', 'wrong-reference', 'wrong-limit') else 'success'
            runs.append(check((folder / row['report']['path']).parent, kind, row['report']['sha256']))
    if sorted(r['kind'] for r in runs) != sorted(['success'] * 5 + ['other', 'empty', 'cancel', 'wrong', 'wrong-reference', 'wrong-limit']):
        issues.append('required eleven runs missing')
    blocked = json.loads((a.blocked_run / 'run.json').read_text('utf-8'))
    if not (blocked.get('status') == 'blocked' and blocked.get('platform_checked') is False
            and 'verified base copy' in str(blocked.get('reason')) and not (a.blocked_run / 'native/ert-events.jsonl').exists()):
        issues.append('no-copy guard failed')
    attempts = [attempt(folder) for folder in a.excluded_run]
    for r in suites + runs + attempts:
        issues += r['issues']
    for path in a.test_log:
        text = path.read_text('utf-8')
        if '\nRan ' not in text or not text.rstrip().endswith(('OK', 'OK (skipped=3)')):
            issues.append(str(path) + ': tests failed')
    for path in a.regression_report + a.control_report:
        r = json.loads(path.read_text('utf-8'))
        if r.get('status') != 'passed' or r.get('issues'):
            issues.append(str(path) + ': verification failed')
        if path in a.control_report and (r.get('verifier_sha256') != digest(Path(__file__))
                or not r.get('controls') or not all(c.get('rejected') for c in r['controls'])
                or r.get('baseline_run') not in [v['run_id'] for v in runs]):
            issues.append(str(path) + ': invalid controls')
    sources = ['research/forms/' + f for f in ('journal_children77.py', 'journal77.py', 'scenario77.py', 'fixture77.py', 'form_launcher77.py', 'form_window77.py')]
    sources += ['examples/journal-children/' + f for f in ('prepare.py', 'scenario.toml')]
    sources += ['scripts/verify_journal_children77.py', 'scripts/verify_journal_children_controls77.py', 'research/forms/tests/test_journal_children77.py']
    result = dict(status='failed' if issues else 'passed', issues=issues, runs=runs, suites=suites, excluded_attempts=attempts,
                  blocked_run=dict(run_id=blocked['run_id'], sha256=digest(a.blocked_run / 'run.json')),
                  sources={s: digest(ROOT / s) for s in sources},
                  test_logs={str(v): digest(v) for v in a.test_log},
                  regressions={str(v): digest(v) for v in a.regression_report}, controls={str(v): digest(v) for v in a.control_report})
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(status=result['status'], issues=issues), ensure_ascii=False))
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
