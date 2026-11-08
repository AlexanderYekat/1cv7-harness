"""Independently re-read task 045 raw calls, failures, retries and native regressions."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, encoding='utf-8'):
    return json.loads(path.read_text(encoding))


def events(folder):
    return [json.loads(line) for line in (folder/'ert-events.jsonl').read_text('utf-16').splitlines()]


def stress(folder, count=5000):
    issues = []
    def require(ok, text):
        if not ok: issues.append(text)
    report = load(folder/'summary.json')
    raw = events(folder)
    require(report.get('exit_code') == 0 and report.get('calls') == count, 'stress host/controller count differs')
    require(int((folder/'controller-calls.txt').read_text('ascii')) == count, 'raw controller count differs')
    require(report.get('events') == raw, 'saved/raw stress events differ')
    require(len(report.get('rows',[])) == count, 'stress response count differs')
    require(not (folder/'form-step-error.json').exists(), 'stress has a fatal diagnostic')
    phases = [e for e in raw if e['kind']=='phase' and e['name'].startswith('step-')]
    require([e['name'] for e in phases] == [f'step-{-111000-i}' for i in range(count)], 'duplicate/missing/reordered calls')
    require(all(e['value']=='ok' and e['run_id']=='probe45' for e in phases), 'foreign/failed step event')
    require(not any(e['kind']=='blocked' for e in raw), 'stress contains blocked event')
    manifest = {}
    python_retries = 0
    for index,row in enumerate(report.get('rows',[])):
        number = -111000-index
        done = folder/f'form-step-{number}-done'
        protocol = folder/'Протоколы проверки'/f'step-{number}.txt'
        require(row.get('number')==number and row.get('returned') is True and row.get('complete') is True
                and row.get('value')==str(number) and not row.get('diagnostics'), 'stress response incomplete/foreign')
        require(done.read_text('utf-16')=='value:'+str(number), 'raw answer differs')
        require(protocol.read_text('utf-16')=='HARNESS77-STEP:probe45:step:'+str(number), 'raw protocol differs')
        for path in (done,protocol): manifest[path.relative_to(folder).as_posix()]=digest(path)
        for retry in row.get('exchange_retries',[]):
            python_retries += 1
            require(retry.get('operation')=='answer-read' and retry.get('run_id')=='probe45'
                    and retry.get('step')==number and retry.get('path')==str(done)
                    and retry.get('error_source')=='PermissionError'
                    and retry.get('controller_may_have_executed') is True and 1 <= retry.get('attempts',0) <= 25,
                    'unsafe/foreign Python retry')
    vbs_retries = [e for e in raw if e['kind']=='step-exchange-retry']
    for event in vbs_retries:
        detail = json.loads(event['value'])
        require(event['run_id']=='probe45' and detail.get('run_id')=='probe45'
                and detail.get('operation') in ('request-open','request-delete')
                and detail.get('error_number')==70 and detail.get('controller_may_have_executed') is False
                and detail.get('path')==str(folder/'form-step-request') and 1 <= detail.get('attempts',0) <= 25,
                'unsafe/foreign VBScript retry')
    require(len(list(folder.glob('form-step-*-done')))==count, 'unexpected extra answers')
    return dict(status='failed' if issues else 'passed',issues=issues,count=count,
                vbs_retries=len(vbs_retries),python_retries=python_retries,
                responses_sha256=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest(),
                summary_sha256=digest(folder/'summary.json'),client_sha256=digest(folder/'client.vbs'))


CONTROLS = {
    'request-open-transient':('request-open',1,0), 'request-open-persistent':('request-open',0,2),
    'request-delete-transient':('request-delete',1,0), 'request-delete-persistent':('request-delete',0,2),
    'request-open-missing':('request-open',0,2), 'request-read-empty':('request-read',0,2),
    'answer-create':('answer-create',1,2), 'answer-publish':('answer-publish',1,2),
    'foreign-request':('request-run-id',0,2), 'duplicate-step':('duplicate-step',0,2),
}


def controlled(folder):
    issues, rows = [], []
    for name,(operation,calls,exit_code) in CONTROLS.items():
        path = folder/name
        report = load(path/'summary.json')
        raw = events(path)
        own = []
        def require(ok,text):
            if not ok: own.append(text)
        actual_calls = int((path/'controller-calls.txt').read_text('ascii')) if (path/'controller-calls.txt').exists() else 0
        require(actual_calls==calls and report.get('calls')==calls, 'controller replay/count mismatch')
        require(report.get('exit_code')==exit_code and report.get('events')==raw, 'host/raw events differ')
        protocol = path/'Протоколы проверки/step--1.txt'
        require(protocol.exists()==bool(calls), 'unexpected/missing controller protocol')
        if calls: require(protocol.read_text('utf-16')=='HARNESS77-STEP:probe45:step:-1', 'wrong controller marker')
        retries = [json.loads(e['value']) for e in raw if e['kind']=='step-exchange-retry']
        require(all(r.get('operation')==operation and r.get('error_number')==70
                    and r.get('controller_may_have_executed') is False for r in retries), 'unsafe retries')
        blocked = [e for e in raw if e['kind']=='blocked']
        if exit_code==0:
            require(bool(retries) and not blocked and not (path/'form-step-error.json').exists(), 'transient recovery not proved')
            require((path/'form-step--1-done').read_text('utf-16')=='value:-1','recovered answer differs')
        else:
            detail = load(path/'form-step-error.json','utf-16')
            require(len(blocked)==1 and json.loads(blocked[0]['value'])==detail, 'raw fatal diagnostic differs')
            require(detail.get('run_id')=='probe45' and detail.get('operation')==operation
                    and detail.get('controller_may_have_executed') is name.startswith('answer-'), 'failure lost execution context')
            expected_error = {'request-open-persistent':70,'request-delete-persistent':70,'request-open-missing':53,
                              'request-read-empty':62,'answer-create':70,'answer-publish':70,'foreign-request':0,'duplicate-step':0}[name]
            require(detail.get('error_number')==expected_error, 'wrong original error number')
            if name.endswith('persistent'):
                require(detail.get('error_number')==70 and 1 <= detail.get('attempts',0) <= 26
                        and detail.get('elapsed_ms',99999) < 5000,'request access denial not bounded')
            else: require(not retries,'non-request operation retried')
            if name=='duplicate-step':
                require((path/'form-step--1-done').read_text('utf-16')=='value:old','old answer overwritten')
            else: require(not (path/'form-step--1-done').exists(),'failed operation published success')
        rows.append(dict(mode=name,issues=own,summary_sha256=digest(path/'summary.json')))
        issues += [name+': '+i for i in own]
    for name in ('python-answer-read-transient','python-answer-read-persistent'):
        path = folder/name
        report = load(path/'summary.json')
        own=[]
        if not report.get('retries') or report.get('calls')!=0 or (path/'form-step-request').exists():
            own.append('Python read did not observe denial or replayed request')
        if (path/'form-step--1-done').read_text('utf-16')!='value:-1': own.append('Python read modified answer')
        if name.endswith('transient'):
            if report.get('failure') or report.get('answer')!='value:-1': own.append('transient read did not recover')
        elif (report.get('answer') is not None or not report.get('failure')
              or report['failure'].get('controller_may_have_executed') is not True
              or not 1 <= report['failure'].get('attempts',0) <= 26):
            own.append('persistent read denial lost uncertain execution')
        rows.append(dict(mode=name,issues=own,summary_sha256=digest(path/'summary.json')))
        issues += [name+': '+i for i in own]
    return dict(status='failed' if issues else 'passed',issues=issues,cases=rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stress',type=Path,required=True)
    parser.add_argument('--controlled',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--rename-race',type=Path,required=True)
    parser.add_argument('--native-report',type=Path,action='append',default=[])
    parser.add_argument('--test-log',type=Path,required=True)
    parser.add_argument('--preservation',type=Path,required=True)
    parser.add_argument('--blocked-run',type=Path,required=True)
    parser.add_argument('--verifier-controls',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    a,b=stress(args.stress.resolve()),controlled(args.controlled.resolve())
    issues=a['issues']+b['issues']
    baseline=load(args.baseline/'summary.json')
    baseline_events=events(args.baseline)
    if (baseline.get('exit_code')!=2 or not baseline_events or baseline_events[-1].get('name')!='request-open'
            or not baseline_events[-1].get('value','').startswith('70|')
            or not (args.baseline/'form-step-request').exists()):
        issues.append('baseline FSO request-open 70 not reproduced')
    race=load(args.rename_race/'summary.json')
    observations=(args.rename_race/'observations.txt').read_text('utf-16')
    if race.get('exit_code')!=0 or 'open|70|' not in observations or not race.get('publisher_errors'):
        issues.append('concurrent rename/open failure not reproduced')
    native=[]
    for path in args.native_report:
        report=load(path)
        if report.get('status')!='passed' or report.get('issues'): issues.append(str(path)+': native verification failed')
        native.append(dict(path=str(path),sha256=digest(path),runs=len(report.get('runs',[]))))
    if len(native)!=4 or sum(row['runs'] for row in native)!=9: issues.append('required nine native cases missing')
    blocked=load(args.blocked_run/'run.json')
    if (blocked.get('status')!='blocked' or blocked.get('platform_checked') is not False
            or 'verified base copy' not in str(blocked.get('reason'))
            or (args.blocked_run/'native/ert-events.jsonl').exists()):
        issues.append('verified-copy guard failed')
    log=args.test_log.read_text('utf-8')
    if '\nRan ' not in log or not log.rstrip().endswith('OK'): issues.append('form tests did not pass')
    preservation=load(args.preservation)
    if preservation.get('status')!='passed' or preservation.get('issues'): issues.append('native preservation failed')
    controls=load(args.verifier_controls)
    if (controls.get('status')!='passed' or controls.get('issues') or len(controls.get('controls',[]))!=5
            or not all(c.get('rejected') for c in controls['controls'])
            or controls.get('verifier_sha256')!=digest(Path(__file__))):
        issues.append('independent verifier controls failed')
    sources=['research/forms/'+f for f in ('step_exchange77.py','scenario77.py','form_launcher77.py',
             'probe_step_exchange77.py','tests/test_step_exchange77.py')]+['scripts/verify_step_exchange77.py']
    result=dict(status='failed' if issues else 'passed',issues=issues,stress=a,controlled=b,
        baseline=dict(summary_sha256=digest(args.baseline/'summary.json'),failed_request=baseline['rows'][-1]['number']),
        rename_race=dict(summary_sha256=digest(args.rename_race/'summary.json'),observations_sha256=digest(args.rename_race/'observations.txt')),
        native=native,test_log_sha256=digest(args.test_log),preservation_sha256=digest(args.preservation),
        blocked_run=dict(run_id=blocked['run_id'],sha256=digest(args.blocked_run/'run.json')),
        verifier_controls_sha256=digest(args.verifier_controls),
        sources={p:digest(ROOT/p) for p in sources})
    with args.output.open('x',encoding='utf-8') as out:json.dump(result,out,ensure_ascii=False,indent=2)
    print(json.dumps(dict(status=result['status'],issues=issues,vbs_retries=a['vbs_retries'],python_retries=a['python_retries'])),flush=True)
    return int(bool(issues))


if __name__=='__main__':
    raise SystemExit(main())
