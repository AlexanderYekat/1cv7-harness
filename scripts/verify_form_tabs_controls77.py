"""Reproduce task-046 evidence substitutions without modifying accepted run files."""
import argparse
import copy
import json
from pathlib import Path

import verify_form_tabs77 as verifier
from verify_document_form77 import digest, read
from form_launcher77 import configuration_description
from harness77.metadata77 import Metadata


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); folder=a.run.resolve()
    baseline=verifier.check(folder)
    if baseline['issues']: raise ValueError(baseline['issues'])
    inspection=json.loads((folder/'form/form-window.json').read_text('utf-8'))
    records=inspection['steps']
    identity=json.loads((folder/'native/proxy-verified.json').read_text('utf-8'))['identity']
    events=[json.loads(l) for l in read(folder/'native/ert-events.jsonl').splitlines()]
    md=folder/'configuration/1Cv7.MD'
    target=configuration_description(md,'Документ.СчетФактура')[0]
    next(c for c in target['controls'] if c.get('identifier')=='кнПечать')['caption']='Печать'
    target['browser']['expected_visible']=False
    descriptions=(configuration_description(md,'Журнал.Общий.ФормаСписка.ФормаСписка')[0],target,Metadata(md.read_bytes()))
    cases=[]
    def change(name,path,value): cases.append((name,path,value))
    for name,path,value in [
        ('tab-caption',[3,'tabs_before','items'],['Шапка','Другая','Корр. счет и номер ГТД']),
        ('before-selection',[3,'tabs_before','selected'],1),
        ('after-selection',[3,'tabs_after','selected'],0),
        ('target-caption',[3,'target'],'Шапка'),
        ('foreign-pid',[3,'tabs_before','window','pid'],-1),
        ('foreign-tid',[3,'tabs_before','window','tid'],-1),
        ('wrong-parent',[3,'tabs_before','window','parent'],-1),
        ('wrong-class',[3,'tabs_before','window','class'],'Button'),
        ('hidden-tabs',[3,'tabs_before','window','visible'],False),
        ('disabled-tabs',[3,'tabs_before','window','enabled'],False),
        ('no-tab-identity',[3,'tabs_before','identity_rechecked'],False),
        ('lost-keys',[3,'tab_keys'],[]),
        ('wrong-key',[3,'tab_keys',0,'action','key'],'Enter'),
        ('wrong-key-window',[3,'tab_keys',0,'action','hwnd'],-1),
        ('key-not-returned',[3,'tab_keys',0,'action','returned'],False),
        ('key-not-owned',[3,'tab_keys',0,'action','identity_rechecked'],False),
        ('wrong-focus',[3,'tab_keys',0,'focus','hwnd'],-1),
        ('unchanged-selection',[3,'tab_keys',0,'tabs','selected'],0),
        ('unverified-selection',[3,'tab_verified'],False),
        ('lost-key-call',[3,'calls'],[]),
        ('wrong-dialog',[3,'tab_form','chain',0,'hwnd'],-1),
        ('wrong-frame',[3,'tab_form','chain',1,'hwnd'],-1),
        ('table-hidden',[3,'tab_form','controls',0,'visible'],False),
        ('wrong-row-count',[4,'round_trip','rows'],2),
        ('wrong-value',[5,'round_trip','value'],'9'),
        ('wrong-total',[11,'round_trip','total'],'99'),
        ('header-not-selected',[12,'tabs_after','selected'],1),
        ('handoff-not-owned',[2,'browse_handoff_verified'],False),
        ('return-wrong-link',[2,'viewing_return','before_close','journal_link'],'0'),
        ('return-wrong-reference',[2,'viewing_return','before_close','journal_id'],'foreign'),
        ('changed-sibling',[2,'viewing_return','before_close','journal_value'],'changed'),
        ('source-changed',[2,'viewing_return','after_children','journal_id'],'foreign'),
        ('return-calls-lost',[2,'viewing_return','calls'],[]),
        ('document-left-open',[2,'viewing_return','document_close','destroyed'],False),
        ('list-left-open',[2,'viewing_return','children_close','destroyed'],False),
    ]: change(name,path,value)
    controls=[]
    for name,path,value in cases:
        altered=copy.deepcopy(records); parent=altered
        for part in path[:-1]: parent=parent[part]
        parent[path[-1]]=value
        issues=verifier.step_issues(altered,'success',inspection,identity,descriptions,folder,events)
        controls.append(dict(name=name,rejected=bool(issues),issues=issues))
    issues=[c['name']+' accepted' for c in controls if not c['rejected']]
    result=dict(status='failed' if issues else 'passed',issues=issues,baseline_run=baseline['run_id'],
                verifier_sha256=digest(Path(verifier.__file__)),controls=controls)
    with a.output.open('x',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(dict(status=result['status'],issues=issues,controls=len(controls))))
    return int(bool(issues))


if __name__=='__main__': raise SystemExit(main())
