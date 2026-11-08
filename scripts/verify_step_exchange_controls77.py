"""Adversarial controls for task 045 on isolated copies of Windows exchange evidence."""
import argparse
from pathlib import Path
import copy
import json
import shutil
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'scripts'))
from verify_step_exchange77 import controlled,digest
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--controlled',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
source=args.controlled.resolve(strict=True)
baseline=controlled(source)
assert not baseline['issues']
rows=[]
def write(path,value,encoding='utf-8'):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding=encoding)
def change_context(folder):
    path=folder/'request-open-persistent'
    value=json.loads((path/'form-step-error.json').read_text('utf-16'))
    value['controller_may_have_executed']=True
    events=[json.loads(line) for line in (path/'ert-events.jsonl').read_text('utf-16').splitlines()]
    events[-1]['value']=json.dumps(value,ensure_ascii=False)
    (path/'ert-events.jsonl').write_text('\n'.join(json.dumps(e,ensure_ascii=False) for e in events),encoding='utf-16')
    write(path/'form-step-error.json',value,'utf-16')
    report=json.loads((path/'summary.json').read_text('utf-8'))
    report['events'],report['failure']=events,value
    write(path/'summary.json',report)
def count_replay(folder):
    path=folder/'answer-publish'
    (path/'controller-calls.txt').write_text('2',encoding='ascii')
    report=json.loads((path/'summary.json').read_text('utf-8'));report['calls']=2
    write(path/'summary.json',report)
def read_context(folder):
    path=folder/'python-answer-read-persistent/summary.json'
    report=json.loads(path.read_text('utf-8'));report['failure']['controller_may_have_executed']=False
    write(path,report)
def unsafe_retry(folder):
    path=folder/'request-open-persistent'
    events=[json.loads(line) for line in (path/'ert-events.jsonl').read_text('utf-16').splitlines()]
    value=json.loads(events[0]['value']);value['operation']='controller-call';value['controller_may_have_executed']=True
    events[0]['value']=json.dumps(value,ensure_ascii=False)
    (path/'ert-events.jsonl').write_text('\n'.join(json.dumps(e,ensure_ascii=False) for e in events),encoding='utf-16')
    report=json.loads((path/'summary.json').read_text('utf-8'));report['events']=events
    write(path/'summary.json',report)
mutations=[('controller-replayed',count_replay),('before-call-context-forged',change_context),
    ('old-answer-overwritten',lambda f:(f/'duplicate-step/form-step--1-done').write_text('value:-1',encoding='utf-16')),
    ('after-call-context-lost',read_context),('unsafe-retry',unsafe_retry)]
with tempfile.TemporaryDirectory(prefix='h77-045-controls-',dir=root/'.artifacts') as temp:
    target=Path(temp).resolve()
    assert target.is_relative_to((root/'.artifacts').resolve()) and target.name.startswith('h77-045-controls-')
    for name,mutate in mutations:
        folder=target/name
        shutil.copytree(source,folder)
        mutate(folder)
        result=controlled(folder)
        rows.append(dict(name=name,rejected=bool(result['issues']),issues=result['issues']))
issues=[r['name'] for r in rows if not r['rejected']]
result=dict(status='failed' if issues else 'passed',issues=issues,controls=rows,
    verifier_sha256=digest(root/'scripts/verify_step_exchange77.py'))
with args.output.open('x',encoding='utf-8') as out:
    json.dump(result,out,ensure_ascii=False,indent=2)
print(json.dumps(dict(status=result['status'],issues=issues,controls=len(rows))))
