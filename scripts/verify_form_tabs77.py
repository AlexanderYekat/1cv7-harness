"""046: verify raw calls, native tab keys/windows, exact journal return and saved data."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tomllib

from verify_document_form77 import ROOT, BASE_MD_SHA256, digest, read, check as document_check
from verify_journal_children_mixed77 import step_issues as journal_issues, layout_issues
from verify_suite77 import verify as verify_suite

sys.path.insert(0, str(ROOT / 'research/forms'))
import scenario77
from form_launcher77 import configuration_description
from form_window77 import expected_geometry, fit_units, edged_ids
from harness77.metadata77 import Metadata

spec=importlib.util.spec_from_file_location('tabs_example', ROOT/'examples/form-tabs/prepare.py')
example=importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)
CAPTIONS=['Шапка','Табличная часть','Корр. счет и номер ГТД']


def raw_issues(folder, trip, number, run_id, events):
    issues=[]
    answer=scenario77.answer(read(folder/'native'/f'form-step-{number}-done'))
    if not all(trip.get(k)==v for k,v in answer.items()):
        issues.append(f'raw answer differs at {number}')
    protocol=read(folder/'native'/'Протоколы проверки'/f'step-{number}.txt')
    messages,complete=scenario77.messages(protocol,f'{run_id}:step:{number}')
    if not complete or messages!=trip.get('messages'):
        issues.append(f'raw protocol differs at {number}')
    found=[e for e in events if e.get('run_id')==run_id and e.get('kind')=='phase'
           and e.get('name')==f'step-{number}' and e.get('value')=='ok']
    if len(found)!=1 or not trip.get('returned') or not trip.get('complete') or trip.get('diagnostics'):
        issues.append(f'raw call incomplete/duplicate at {number}')
    return issues


def step_issues(records, case, inspection, identity, descriptions, folder, events):
    issues=[]
    def require(ok,why):
        if not ok: issues.append(why)
    parameters=tomllib.loads(example.case_scenario(case))['platform']['parameters']
    declared=scenario77.resolve(scenario77.steps(parameters),descriptions[1])
    count=4 if case=='missing' else 5 if case=='wrong-rows' else len(declared)
    require(len(records)==count,'scenario truncated/extended')
    for actual,wanted in zip(records,declared):
        require(all(actual.get(k)==v for k,v in wanted.items()),'declared step differs: '+str(wanted['index']))
        failed=(case in ('missing','wrong-rows') and actual is records[-1])
        require(actual.get('status')==('failed' if failed else 'passed') and bool(actual.get('issue'))==failed,
                'step outcome differs: '+str(wanted['index']))
    if len(records)<3: return issues
    opening=records[2]
    returned=opening.get('viewing_return',{})
    require(opening.get('browse_handoff_verified') is True and not opening.get('edit'), 'read-only handoff missing')
    require(not opening.get('document_close') and not opening.get('children_close'), 'handoff closed forms early')
    issues+=journal_issues(records[:3], 'invoice-near' if case=='second' else 'invoice-far',
                           inspection,identity,descriptions,viewing=True)
    run_id=inspection['run_id']
    for trip in returned.get('calls',[]):
        issues+=raw_issues(folder,trip,trip['number'],run_id,events)
    before_close=returned.get('before_close',{})
    require(before_close.get('journal_kind')==before_close.get('journal_expected_kind')=='СчетФактура',
            'return changed document kind')
    document=opening.get('opened_form',{})
    frame=document.get('chain',[{},{}])[1].get('hwnd')
    dialog=document.get('chain',[{}])[0].get('hwnd')
    selected=0
    native_window=None
    for record in records[3:]:
        if record['kind']=='tab':
            before=record.get('tabs_before',{})
            window=before.get('window',{})
            require(before.get('items')==CAPTIONS and before.get('selected')==selected
                    and before.get('caption')==CAPTIONS[selected] and before.get('frame')==frame,
                    'native tab names/entry selection/frame differ')
            require(window.get('class')=='SysTabControl32' and window.get('parent')==frame
                    and window.get('visible') is True and window.get('enabled') is True
                    and window.get('pid')==identity['pid'] and window.get('tid')==identity['tid']
                    and before.get('identity_rechecked') is True, 'foreign/hidden tab window')
            if native_window is None: native_window=window
            require(window==native_window,'native tab HWND changed')
            keys=record.get('tab_keys',[])
            if case=='missing':
                require(record.get('target') not in CAPTIONS and not keys and not record.get('calls')
                        and not record.get('tabs_after') and 'found 0' in str(record.get('issue')),
                        'missing tab sent a key or did not fail explicitly')
                continue
            wanted=CAPTIONS.index(record['target'])
            require(len(keys)==abs(wanted-selected),'wrong tab navigation length')
            for i,row in enumerate(keys,1):
                direction=1 if wanted>selected else -1
                action=row.get('action',{})
                require(action.get('hwnd')==window.get('hwnd') and action.get('id')==window.get('id')
                        and action.get('key')==('Right' if direction==1 else 'Left')
                        and action.get('message')=='WM_KEYDOWN/WM_KEYUP' and action.get('returned') is True
                        and action.get('identity_rechecked') is True and row.get('focus',{}).get('hwnd')==window.get('hwnd'),
                        'tab keyboard action/focus differs')
                selected+=direction
                state=row.get('tabs',{})
                require(state.get('selected')==selected and state.get('caption')==CAPTIONS[selected]
                        and state.get('items')==CAPTIONS and state.get('window')==window
                        and state.get('frame')==frame and state.get('identity_rechecked') is True,
                        'tab did not move exactly one native position')
                issues+=raw_issues(folder,row.get('round_trip',{}),scenario77.trip_number(record['index'],i),run_id,events)
            after=record.get('tabs_after',{})
            require(after.get('selected')==wanted==selected and after.get('caption')==record['target']
                    and after.get('items')==CAPTIONS and after.get('window')==window
                    and record.get('tab_verified') is True,'tab selection unverified')
            require(record.get('calls')==[dict(r.get('round_trip',{}),number=scenario77.trip_number(record['index'],i))
                    for i,r in enumerate(keys,1)]+[dict(record.get('round_trip',{}),number=record['index'])],
                    'tab raw call sequence differs')
            measured=copy.deepcopy(record.get('tab_form',{}))
            require(measured.get('found') is True and measured.get('chain',[{}])[0].get('hwnd')==dialog
                    and measured.get('chain',[{},{}])[1].get('hwnd')==frame,'tab inspected another document')
            description=copy.deepcopy(descriptions[1])
            description['browser']['expected_visible']=record['browser_visible']
            measured['units']=fit_units(expected_geometry(description),{c['id']:tuple(c['rect']) for c in measured.get('controls',[])},
                                       edged=edged_ids(description))
            require(not layout_issues(description,measured),'tab layout/caption/table visibility differs')
        else:
            trip=record.get('round_trip',{})
            require(selected==1 or record['index']==len(declared),'table read outside requested tab')
            require(not scenario77.judge(record,record,[],True) if record.get('status')=='passed'
                    else bool(scenario77.judge(record,record,[],True)),'independent value/row check differs')
            if record['kind']=='rows':
                require(trip.get('rows')==1 and trip.get('row')==1,'native row state differs')
                require(record.get('state',{}).get('visible') is True,'table hidden during row check')
    if case not in ('missing','wrong-rows'):
        require(selected==0,'did not return to header tab')
    return issues


def check(folder,case='success',expected_hash=None):
    folder=folder.resolve()
    md=folder/'configuration/1Cv7.MD'
    if digest(md)!=BASE_MD_SHA256: raise ValueError('source MD changed')
    parameters=tomllib.loads(example.case_scenario(case))['platform']['parameters']
    children=configuration_description(md,'Журнал.Общий.ФормаСписка.ФормаСписка')[0]
    target=configuration_description(md,'Документ.СчетФактура')[0]
    target=copy.deepcopy(target)
    next(c for c in target['controls'] if c.get('identifier')=='кнПечать')['caption']='Печать'
    target['browser']['expected_visible']=False
    descriptions=(children,target,Metadata(md.read_bytes()))
    inspection=json.loads((folder/'form/form-window.json').read_text('utf-8'))
    identity=json.loads((folder/'native/proxy-verified.json').read_text('utf-8'))['identity']
    events=[json.loads(l) for l in read(folder/'native/ert-events.jsonl').splitlines()]
    result=document_check(folder,'wrong-reopen' if case in ('missing','wrong-rows') else 'success',expected_hash,
        readback=example.mixed.state(),allow_fixture_posting=True,
        step_validator=lambda records,_:step_issues(records,case,inspection,identity,descriptions,folder,events))
    result['case']=case
    controller=(folder/'native/ert-controller.1s').read_text('utf-8')
    slot=parameters['steps'][2]['reference']
    if controller.count(f'Ожидаемая77Ссылка = Объект77Подготовки.ПолучитьЗначение({slot});')!=1:
        result['issues'].append('controller expected reference slot differs')
    for name in ('fixture_setup','fixture_verify'):
        marker='Функция '+('Harness77ПодготовитьДанные()' if name=='fixture_setup' else 'Harness77ПроверитьДанные(Объект77)')+'\n'
        if controller.count(marker)!=1 or controller.split(marker,1)[1].split('КонецФункции',1)[0].strip()!=parameters[name].strip():
            result['issues'].append('fixture source differs: '+name)
    outside=controller.split('Функция Harness77ПодготовитьДанные()',1)[1].split('КонецФункции',1)[1]
    for forbidden in ('.Новый(','.Записать(','.Провести(','.Удалить(','.ВводНаОсновании(','.ПодчинениеДокументу(','.ИспользоватьСлой(','.ТекущаяСтрока('):
        if forbidden in outside: result['issues'].append('programmatic mutation/navigation: '+forbidden)
    report=json.loads((folder/'run.json').read_text('utf-8'))
    if report.get('shutdown',{}).get('forced_cleanup') is not False: result['issues'].append('forced native cleanup')
    checks=[e for e in events if e.get('kind')=='ert' and e.get('name')=='check']
    if len(checks)!=1 or checks[0]['value'].splitlines().count('fixture-initial:'+example.mixed.state())!=1:
        result['issues'].append('independent initial data differ')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--blocked-run',type=Path)
    for name in ('test-log','regression-report','control-report','support-report'):
        p.add_argument('--'+name,type=Path,action='append',default=[])
    a=p.parse_args(); suites=[]; runs=[]; issues=[]
    for folder in a.suite:
        folder=folder.resolve(); suites.append(verify_suite(folder,native=True))
        for row in json.loads((folder/'suite.json').read_text('utf-8'))['scenarios']:
            case=row['id'] if row['id'] in ('success','second','missing','wrong-rows') else 'success'
            runs.append(check((folder/row['report']['path']).parent,case,row['report']['sha256']))
    for r in suites+runs: issues+=r['issues']
    blocked=None
    if a.blocked_run:
        blocked=json.loads((a.blocked_run/'run.json').read_text('utf-8'))
        if (blocked.get('status')!='blocked' or blocked.get('platform_checked') is not False
                or 'verified base copy' not in str(blocked.get('reason'))
                or (a.blocked_run/'native/ert-events.jsonl').exists()):
            issues.append('no-copy guard failed')
        if sorted(r['case'] for r in runs)!=sorted(['success']*4+['second','missing','wrong-rows']):
            issues.append('required seven native cases missing')
    for path in a.test_log:
        content=path.read_text('utf-8')
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
    sources=['research/forms/'+f for f in ('tabs77.py','journal_children77.py','scenario77.py','form_launcher77.py',
        'fixture77.py','form_window77.py','journal77.py','journal_basis77.py','tests/test_tabs77.py')]
    sources+=['examples/form-tabs/prepare.py','examples/journal-children-mixed/prepare.py','examples/journal-children-mixed/scenario.toml',
        'scripts/verify_form_tabs77.py','scripts/verify_form_tabs_controls77.py','scripts/verify_journal_children_mixed77.py',
        'scripts/verify_document_form77.py']
    result=dict(status='failed' if issues else 'passed',issues=issues,suites=suites,runs=runs,
        verifier_sha256=digest(Path(__file__)),sources={s:digest(ROOT/s) for s in sources},
        blocked_run=dict(run_id=blocked['run_id'],sha256=digest(a.blocked_run/'run.json')) if blocked else None,
        test_logs={str(p):digest(p) for p in a.test_log},regressions={str(p):digest(p) for p in a.regression_report},
        controls={str(p):digest(p) for p in a.control_report},supporting_evidence={str(p):digest(p) for p in a.support_report})
    with a.output.open('x',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(dict(status=result['status'],issues=issues),ensure_ascii=False))
    return int(bool(issues))


if __name__=='__main__': raise SystemExit(main())
