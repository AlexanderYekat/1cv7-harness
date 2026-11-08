"""Adversarial controls for task 044's independent evidence verifier."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import tempfile

from verify_journal_children_edit77 import check, step_issues, configuration_description, Metadata, digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--kind', choices=['success','cancel'], default='success')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    folder = a.run.resolve()
    baseline = check(folder, a.kind)
    if baseline['issues']:
        raise SystemExit('invalid baseline: ' + repr(baseline['issues']))
    inspection = json.loads((folder / 'form/form-window.json').read_text('utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text('utf-8'))['identity']
    md = folder / 'configuration/1Cv7.MD'
    descriptions = [configuration_description(md,name)[0] for name in ('Журнал.Общий.ФормаСписка.ФормаСписка','Документ.ПриходныйОрдер')]
    descriptions.append(Metadata(md.read_bytes()))
    controls = []
    def run(name, mutate):
        records = copy.deepcopy(inspection['steps'])
        mutate(records)
        try:
            issues = step_issues(records, a.kind, inspection, identity, descriptions)
        except (KeyError, ValueError, TypeError, IndexError) as error:
            issues = ['invalid evidence: ' + str(error)]
        controls.append(dict(name=name, rejected=bool(issues), issues=issues))
    changes = [
        ('command',lambda r:r[2]['action'].update(command=1)),
        ('command-owner',lambda r:r[2]['action'].update(hwnd=1)),
        ('menu-disabled',lambda r:r[2]['menu'].update(enabled=False)),
        ('source-value',lambda r:r[2]['before_children'].update(journal_value='other')),
        ('source-id',lambda r:r[2]['before_children'].update(journal_id='other')),
        ('source-opened',lambda r:r[1].update(open=True)),
        ('source-key',lambda r:r[1]['search'][0]['action'].update(key='Home')),
        ('mixed-key',lambda r:r[2]['child_search'][1]['action'].update(key='Down')),
        ('mixed-kind',lambda r:r[2]['child_search'][1]['round_trip'].update(journal_kind='ПриходныйОрдер')),
        ('mixed-source',lambda r:r[2]['child_search'][0]['round_trip'].update(journal_source_id='other')),
        ('mixed-limit',lambda r:r[2].update(limit=1)),
        ('mixed-missing',lambda r:r[2]['child_search'].pop()),
        ('selected-id',lambda r:r[2]['selected_child'].update(journal_id='other')),
        ('selected-kind',lambda r:r[2]['selected_child'].update(journal_expected_kind='СчетФактура')),
        ('recheck-id',lambda r:r[2]['selection_recheck'].update(journal_id='other')),
        ('recheck-incomplete',lambda r:r[2]['selection_recheck'].update(complete=False)),
        ('enter-window',lambda r:r[2]['open_action'].update(hwnd=1)),
        ('opened-id',lambda r:r[2]['opened_child'].update(journal_id='other')),
        ('opened-link',lambda r:r[2]['opened_child'].update(journal_link_id='other')),
        ('handoff',lambda r:r[2].update(edit_handoff_verified=False)),
        ('premature-close',lambda r:r[2].update(document_close=dict(destroyed=True))),
        ('no-input',lambda r:r[4].update(kind='check')),
        ('input-failed',lambda r:r[4]['action'].update(returned=False)),
        ('wrong-input',lambda r:r[4].update(text='999')),
        ('wrong-comment',lambda r:r[6].update(text='other')),
        ('no-reopen',lambda r:r[10].update(kind='check')),
        ('reopen-wrong-reference',lambda r:r[10]['round_trip'].update(reopen_same='0')),
        ('old-windows-survived',lambda r:r[10].update(closed_before_reopen=False)),
        ('reopened-layout',lambda r:r[10]['reopened']['controls'][0].update(rect=[9000,9000,1,1])),
        ('reopened-value',lambda r:r[-1]['round_trip'].update(value='999')),
        ('return-reference',lambda r:r[2]['editing_return']['before_close'].update(journal_id='other')),
        ('return-kind',lambda r:r[2]['editing_return']['before_close'].update(journal_kind='СчетФактура')),
        ('return-state',lambda r:r[2]['editing_return']['before_close'].update(journal_value='other')),
        ('return-child-link',lambda r:r[2]['editing_return']['returned_child'].update(journal_link='0')),
        ('return-source',lambda r:r[2]['editing_return']['after_children'].update(journal_id='other')),
        ('return-close-window',lambda r:r[2]['editing_return']['document_close'].update(hwnd=1)),
        ('return-not-destroyed',lambda r:r[2]['editing_return']['document_close'].update(destroyed=False)),
        ('return-extra-frame',lambda r:r[2]['editing_return']['after_windows'].append(dict(hwnd=1,parent=inspection['chain'][2]['hwnd']))),
        ('return-raw-sequence',lambda r:r[2]['editing_return']['calls'].pop()),
        ('return-unverified',lambda r:r[2]['editing_return'].update(return_verified=False)),
        ('return-foreign-process',lambda r:r[2]['editing_return']['before_windows'][0].update(pid=1)),
    ]
    if a.kind == 'cancel':
        changes += [('cancel-saves',lambda r:r[9]['answer']['button'].update(text='Да'))]
    else:
        changes += [('no-save',lambda r:r[8].update(target='Закрыть')),('no-post',lambda r:r[9].update(target='Закрыть'))]
    for name, change in changes:
        run(name, change)
    # Tamper only with a separate temporary copy, leaving native evidence intact.
    with tempfile.TemporaryDirectory(prefix='h77-044-controls-') as temp:
        copied = Path(temp) / folder.name
        shutil.copytree(folder, copied)
        target = copied / 'native/form-step--112002-done'
        raw = target.read_text('utf-16')
        target.write_text(raw.replace('journal-match:1','journal-match:0'), encoding='utf-16')
        issues = check(copied, a.kind)['issues']
        controls.append(dict(name='physical-utf16-return-response',rejected=bool(issues),issues=issues))
    issues = [r['name'] + ': accepted tampering' for r in controls if not r['rejected']]
    result = dict(status='failed' if issues else 'passed', issues=issues, baseline_run=baseline['run_id'],
                  verifier_sha256=digest(Path(__file__).with_name('verify_journal_children_edit77.py')), controls=controls)
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(status=result['status'], issues=issues, controls=len(controls))))
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
