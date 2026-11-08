"""Adversarial controls for the independent task-043 verifier."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import shutil

from verify_journal_children_mixed77 import check, step_issues, configuration_description, digest, BASE_MD_SHA256


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--kind', choices=['middle', 'invoice-far'], default='middle')
    a = p.parse_args()
    folder = a.run.resolve()
    baseline = check(folder, a.kind)
    if baseline['issues']:
        raise SystemExit('baseline invalid: ' + repr(baseline['issues']))
    inspection = json.loads((folder / 'form/form-window.json').read_text('utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text('utf-8'))['identity']
    descriptions = [configuration_description(folder / 'configuration/1Cv7.MD', name)[0] for name in
                    ('Журнал.Общий.ФормаСписка.ФормаСписка', 'Документ.' + ('СчетФактура' if a.kind == 'invoice-far' else 'ПриходныйОрдер'))]
    for c in descriptions[1]['controls']:
        if c.get('identifier') == 'ндСфетФактураУжеСформирована':
            c['caption'] = 'Счет-факутра ещё не сформирована'
        if a.kind == 'invoice-far' and c.get('identifier') == 'кнПечать':
            c['caption'] = 'Печать'
    if a.kind == 'invoice-far':
        descriptions[1]['browser']['expected_visible'] = False
    from harness77.metadata77 import Metadata
    descriptions.append(Metadata((folder / 'configuration/1Cv7.MD').read_bytes()))
    controls = []
    def run(name, mutate):
        records = copy.deepcopy(inspection['steps'])
        mutate(records)
        try:
            issues = step_issues(records, a.kind, inspection, identity, descriptions)
        except (KeyError, ValueError, IndexError, TypeError) as e:
            issues = ['invalid evidence structure: ' + str(e)]
        controls.append(dict(name=name, rejected=bool(issues), issues=issues))
    mutations = [
        ('command-target', lambda r: r[2]['action'].update(hwnd=1)),
        ('disabled-command', lambda r: r[2]['menu'].update(enabled=False)),
        ('foreign-menu-owner', lambda r: r[2]['menu'].update(main=1)),
        ('source-snapshot', lambda r: r[2]['before_children'].update(journal_value='changed')),
        ('source-internal-id', lambda r: r[2]['before_children'].update(journal_id='neighbor')),
        ('selected-internal-id', lambda r: r[2]['selected_child'].update(journal_id='neighbor')),
        ('selected-expected-id', lambda r: r[2]['selected_child'].update(journal_expected_id='neighbor')),
        ('selected-exact-match', lambda r: r[2]['selected_child'].update(journal_match='0')),
        ('selected-parent-id', lambda r: r[2]['selected_child'].update(journal_source_id='neighbor')),
        ('selected-link-id', lambda r: r[2]['selected_child'].update(journal_link_id='neighbor')),
        ('selected-empty', lambda r: r[2]['selected_child'].update(journal_empty='1')),
        ('selected-other-window', lambda r: r[2]['selected_child'].update(journal_hwnd=r[2]['before_children']['journal_hwnd'])),
        ('selected-snapshot', lambda r: r[2]['selected_child'].update(journal_value='changed')),
        ('search-row-other-child', lambda r: r[2]['child_search'][0]['round_trip'].update(journal_id='child')),
        ('missing-search-row', lambda r: r[2]['child_search'].pop(0)),
        ('search-limit', lambda r: r[2].update(limit=1)),
        ('search-reversed-keys', lambda r: r[2]['child_search'][1]['action'].update(key='Down')),
        ('search-first-key', lambda r: r[2]['child_search'][0]['action'].update(key='Home')),
        ('search-stale-target', lambda r: r[2]['child_search'][0]['round_trip'].update(journal_expected_id='other')),
        ('search-other-source', lambda r: r[2]['child_search'][0]['round_trip'].update(journal_source_id='other')),
        ('search-other-link', lambda r: r[2]['child_search'][0]['round_trip'].update(journal_link_id='other')),
        ('search-other-window', lambda r: r[2]['child_search'][0]['round_trip'].update(journal_hwnd='1')),
        ('search-changed-state', lambda r: r[2]['child_search'][0]['round_trip'].update(journal_value='changed')),
        ('search-incomplete', lambda r: r[2]['child_search'][0]['round_trip'].update(complete=False)),
        ('missing-recheck', lambda r: r[2].pop('selection_recheck')),
        ('changed-recheck', lambda r: r[2]['selection_recheck'].update(journal_id='other')),
        ('incomplete-recheck', lambda r: r[2]['selection_recheck'].update(complete=False)),
        ('missing-enter', lambda r: r[2].pop('open_action')),
        ('enter-other-list', lambda r: r[2]['open_action'].update(hwnd=1)),
        ('selection-other-list', lambda r: r[2]['child_search'][0]['action'].update(hwnd=1)),
        ('second-row-other-list', lambda r: r[2]['child_search'][1]['action'].update(hwnd=1)),
        ('opened-internal-id', lambda r: r[2]['opened_child'].update(journal_id='neighbor')),
        ('opened-unsaved', lambda r: r[2]['opened_child'].update(journal_opened='0')),
        ('opened-parent-id', lambda r: r[2]['opened_child'].update(journal_source_id='neighbor')),
        ('opened-link-id', lambda r: r[2]['opened_child'].update(journal_link_id='neighbor')),
        ('opened-window', lambda r: r[2]['opened_child'].update(journal_hwnd='1')),
        ('opened-snapshot', lambda r: r[2]['opened_child'].update(journal_value='changed')),
        ('document-not-closed', lambda r: r[2]['document_close'].update(destroyed=False)),
        ('document-close-other-frame', lambda r: r[2]['document_close'].update(hwnd=1)),
        ('journal-not-closed', lambda r: r[2]['children_close'].update(destroyed=False)),
        ('returned-wrong-child', lambda r: r[2]['returned_child'].update(journal_id='neighbor')),
        ('returned-wrong-source', lambda r: r[2]['after_children'].update(journal_id='neighbor')),
        ('returned-data-changed', lambda r: r[2]['after_children'].update(journal_value='changed')),
        ('missing-raw-call', lambda r: r[2]['calls'].pop()),
        ('foreign-process', lambda r: r[2]['children_windows'][0].update(pid=1)),
        ('foreign-thread', lambda r: r[2]['opened_windows'][0].update(tid=1)),
        ('document-layout', lambda r: r[2]['opened_form']['controls'][0].update(rect=[999,999,1,1])),
        ('journal-layout', lambda r: r[2]['children_form']['controls'][0].update(rect=[999,999,1,1])),
        ('journal-static-layout', lambda r: next(c for c in r[2]['children_form']['controls'] if c['id'] == 4159).update(rect=[999,999,1,1])),
        ('extra-frame', lambda r: r[2]['after_windows'].append(dict(hwnd=1,parent=inspection['chain'][2]['hwnd'],pid=identity['pid'],tid=identity['tid']))),
    ]
    mutations += [
        ('search-forged-kind', lambda r: r[2]['child_search'][0]['round_trip'].update(journal_kind='СчетФактура')),
        ('search-unknown-kind', lambda r: r[2]['child_search'][1]['round_trip'].update(journal_kind='Другой')),
        ('search-wrong-target-kind', lambda r: r[2]['child_search'][1]['round_trip'].update(journal_expected_kind='Другой')),
        ('selected-wrong-kind', lambda r: r[2]['selected_child'].update(journal_kind='Другой')),
        ('recheck-wrong-kind', lambda r: r[2]['selection_recheck'].update(journal_kind='Другой')),
        ('opened-wrong-kind', lambda r: r[2]['opened_child'].update(journal_kind='Другой')),
        ('opened-wrong-target-kind', lambda r: r[2]['opened_child'].update(journal_expected_kind='Другой')),
        ('profile-missing-kind', lambda r: r[2].update(kinds=['ПриходныйОрдер'])),
        ('profile-target-kind', lambda r: r[2].update(target_kind='Другой')),
        ('returned-wrong-kind', lambda r: r[2]['returned_child'].update(journal_kind='Другой')),
    ]
    if a.kind == 'invoice-far':
        mutations += [
            ('invoice-browser-visible', lambda r: next(c for c in r[2]['opened_form']['controls'] if c['id'] == 4151).update(visible=True)),
            ('invoice-print-caption', lambda r: next(c for c in r[2]['opened_form']['controls'] if c['id'] == 4215).update(text='Other')),
        ]
    for name, mutate in mutations:
        run(name, mutate)
    # Read the physical UTF-16 answer from an isolated evidence copy, not cached JSON.
    with tempfile.TemporaryDirectory(prefix='h77-043-control-') as temporary:
        clone = Path(temporary) / folder.name
        shutil.copytree(folder, clone)
        response = clone / ('native/form-step--111004-done' if a.kind == 'invoice-far' else 'native/form-step--111003-done')
        original = response.read_bytes()
        text = original.decode('utf-16')
        response.write_text(text.replace('journal-match:1', 'journal-match:0'), encoding='utf-16')
        controls.append(dict(name='raw-utf16-answer', rejected=bool(check(clone, a.kind)['issues'])))
    issues = [c['name'] + ': corruption accepted' for c in controls if not c['rejected']]
    result = dict(status='failed' if issues else 'passed', issues=issues, baseline_run=baseline['run_id'],
                  verifier_sha256=digest(Path(__file__).with_name('verify_journal_children_mixed77.py')), controls=controls)
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(status=result['status'], issues=issues, controls=len(controls)), ensure_ascii=False))
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
