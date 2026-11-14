"""103: actual file edits, strict JSON refusals, snapshots and live MCP recovery."""
import json
from pathlib import Path
import sys
import tomllib
import xml.etree.ElementTree as ET

from mcp_client import Client
from verify import digest, read, write, toml_value


def json_check(row, expected, md_hash):
    folder=Path(row['folder'])
    run,platform=read(folder/'run.json'),read(folder/'platform-result.json')
    failed=row['case']!='restored'
    assert run['status']==('failed' if failed else 'passed') and run['exit_code']==int(failed)
    assert run['platform_checked'] and not platform['shutdown']['forced_cleanup']
    assert digest(folder/'configuration/1Cv7.MD')==md_hash
    assert {f['role']:f['sha256'] for f in run['inputs']['json_files']}==row['input_hashes']
    for item in run['inputs']['json_files']:
        evidence=next(f for f in run['result_files'] if f.get('role')==item['role'] and f.get('test_index')==item.get('test_index'))
        captured=folder/evidence['path']
        assert digest(captured)==item['sha256']==evidence['sha256']
        assert captured.stat().st_size==item['size_bytes']==evidence['size_bytes']
        assert evidence['complete'] and evidence['sha256_matches']
        value=read(captured)
        effective=run['inputs']['parameters']['steps'] if item['role']=='steps' else json.loads(run['inputs']['tests'][item['test_index']]['expect_json'])
        assert value==effective
    wanted=json.loads(json.dumps(expected))
    if row['case']=='steps-edit':
        wanted['amount']=wanted['total']='170'
        wanted['rows'][1].update(quantity='4',amount='120',total='120')
        cell=next(s for s in run['inputs']['parameters']['steps'] if s.get('cell')=='Количество')
        assert cell['text']=='4'
    raw=next(op['value'] for op in platform['operations'] if op['name']=='verify')
    assert json.loads(raw)==wanted
    tests=next(s for s in run['stages'] if s['stage']=='tests')['tests']
    assert all(t['expectation_met'] for t in tests if t['name']!='persisted-invoice')
    comparison=next(t for t in tests if t['name']=='persisted-invoice')['structured']
    assert comparison['status']==('failed' if failed else 'passed')
    differences={d['path']:(d['expected'],d['actual']) for d in comparison['differences']}
    if row['case']=='steps-edit':
        assert differences=={'/amount':('140','170'),'/total':('140','170'),'/rows/1/quantity':('3','4'),'/rows/1/amount':('90','120'),'/rows/1/total':('90','120')}
    elif row['case']=='expected-edit':
        assert differences=={'/total':('141','140')}
    else:
        assert not differences
    steps=read(folder/'form/form-window.json')['steps']
    assert len(steps)==25 and all(s['status']=='passed' for s in steps)
    reopened=next(s for s in steps if s['kind']=='reopen')
    assert reopened['closed_before_reopen'] and reopened['round_trip']['reopen_same']=='1'
    checks=[s for s in steps if s['kind']=='check' and s['target']=='кнПечать']
    assert len(checks)==2 and all(s['state']['text']=='Печать' for s in checks)
    if row.get('suite_folder'):
        suite=Path(row['suite_folder'])
        report=read(suite/'suite.json')
        child,=report['scenarios']
        assert report['complete'] and child['status']==run['status']
        assert digest(suite/child['report']['path'])==child['report']['sha256']
        case,=ET.parse(suite/'junit.xml').getroot().findall('testsuite/testcase')
        assert (case.find('failure') is not None)==failed and case.find('error') is None
        if failed:
            assert json.loads(case.find('failure').text)==child['problems']
    return {'status':run['status'],'differences':comparison['differences'],'raw_sha256':digest(folder/'structured/test-0003.actual.json')}


def qualify_json(here,out,profile,record,execute,env,preserved,save):
    baseline=tomllib.loads(profile.read_text(encoding='utf-8'))
    frozen=digest(profile)
    paths={'steps':Path(baseline['platform']['parameters']['steps_file']),
           'expect_json':Path(baseline['platform']['tests'][-1]['expect_json_file'])}
    assert all(p.resolve().parent==here for p in paths.values())
    original={role:p.read_bytes() for role,p in paths.items()}
    client=Client(out,out/'json-input-mcp-traffic.json',env,command=[sys.executable,'-I','-B',str(here/'.harness77/launch.py'),'mcp'])
    record['json_negatives'],record['json_edits']=[],[]

    def call(transport,name,selected,code):
        root=out/name
        if transport=='run':
            return execute(name,['run','--project',selected,'--output-root',root],code=code),None
        manifest=out/(name+'-suite.toml')
        manifest.write_text('schema_version=1\n[suite]\nid="json-files"\n[[scenarios]]\nid="probe"\nproject='+json.dumps(selected.as_posix())+'\n',encoding='utf-8')
        if transport=='cli':
            summary=execute(name,['suite','--suite',manifest,'--suite-id','probe','--output-root',root],code=code)
        else:
            response,progress=client.suite({'suite':str(manifest),'stand':str(here/'stand.toml'),'suite_id':'probe','output_root':str(root)})
            write(out/(name+'-mcp.json'),{'response':response,'progress':progress})
            assert response['structuredContent']['exit_code']==code and response['isError']==(code==2)
            assert progress['ping_after']
            summary=response['structuredContent']['stdout']
        return summary,Path(summary['suite_dir'])

    try:
        cases=('missing-steps','missing-expected','malformed-steps','malformed-expected','steps-structure',
               'steps-conflict','expected-conflict','old-schema','bad-encoding','empty','directory')
        for case in cases:
            data=json.loads(json.dumps(baseline))
            params=data['platform']['parameters']; test=data['platform']['tests'][-1]
            if case.startswith('missing-'):
                target,key=(params,'steps_file') if case=='missing-steps' else (test,'expect_json_file')
                target[key]=str(out/'missing-json-input.json')
            elif case=='steps-conflict':
                params['steps']=read(paths['steps'])
            elif case=='expected-conflict':
                test['expect_json']=paths['expect_json'].read_text(encoding='utf-8')
            elif case=='old-schema':
                data['schema_version']=3
            elif case=='directory':
                test['expect_json_file']=str(out)
            else:
                payload=b'[1]' if case=='steps-structure' else b'\xff' if case=='bad-encoding' else b'' if case=='empty' else b'{'
                path=out/(case+'.json'); path.write_bytes(payload)
                if case in ('malformed-steps','steps-structure'):
                    params['steps_file']=str(path)
                else:
                    test['expect_json_file']=str(path)
            bad=out/('json-'+case+'.toml')
            bad.write_text('\n'.join(json.dumps(k)+'='+toml_value(v) for k,v in data.items())+'\n',encoding='utf-8')
            for transport in ('run','cli','mcp'):
                name='json-negative-'+transport+'-'+case
                summary,suite=call(transport,name,bad,2)
                if suite:
                    report=read(suite/'suite.json'); child,=report['scenarios']
                    assert report['complete'] and child['status']=='blocked' and child['report'] is None and not child['platform_checked']
                else:
                    assert not summary['platform_checked'] and not (out/name).exists()
                record['json_negatives'].append({'case':case,'transport':transport,'summary':summary,'suite_folder':str(suite) if suite else None})
                preserved(); save()
        print('JSON negatives: 33 refused before 1C; MCP alive',flush=True)
        expected=read(here/'expected.json')
        for transport in ('run','cli','mcp'):
            for case in ('steps-edit','expected-edit','restored'):
                for role,path in paths.items():
                    path.write_bytes(original[role])
                if case=='steps-edit':
                    steps=json.loads(original['steps'])
                    next(s for s in steps if s.get('cell')=='Количество')['text']='4'
                    reopened=False
                    for step in steps:
                        if 'reopen' in step:
                            reopened=True
                        if reopened and step.get('row')==2 and step.get('value')=='Количество':
                            step['text']='4'
                        if reopened and step.get('row')==2 and step.get('value') in ('Сумма','Всего'):
                            step['text']='120'
                        if reopened and step.get('total')=='Сумма':
                            step['text']='170'
                    write(paths['steps'],steps)
                elif case=='expected-edit':
                    changed=json.loads(original['expect_json']); changed['total']='141'
                    write(paths['expect_json'],changed)
                try:
                    hashes={role:digest(p) for role,p in paths.items()}
                    summary,suite=call(transport,'json-edit-'+transport+'-'+case,profile,int(case!='restored'))
                    folder=Path(summary['run_dir']) if suite is None else (suite/read(suite/'suite.json')['scenarios'][0]['report']['path']).resolve().parent
                    row={'transport':transport,'case':case,'folder':str(folder),'suite_folder':str(suite) if suite else None,'input_hashes':hashes}
                    row['verification']=json_check(row,expected,record['plans']['baseline']['md_sha256'])
                    record['json_edits'].append(row)
                    assert digest(profile)==frozen
                finally:
                    for role,path in paths.items():
                        path.write_bytes(original[role])
                preserved(); save()
                print(transport+' '+case+': verified without regeneration',flush=True)
        record['json_input_mcp_exit_code']=client.close(); client=None
        assert record['json_input_mcp_exit_code']==0
    finally:
        for role,path in paths.items():
            path.write_bytes(original[role])
        if client is not None:
            client.close()


def verify_json(record,expected):
    assert len(record['json_negatives'])==33 and len(record['json_edits'])==9
    assert record['json_input_mcp_exit_code']==0
    for row in record['json_edits']:
        assert json_check(row,expected,record['plans']['baseline']['md_sha256'])==row['verification']
    for row in record['json_negatives']:
        if row['suite_folder']:
            suite=read(Path(row['suite_folder'])/'suite.json'); child,=suite['scenarios']
            assert suite['status']=='blocked' and child['report'] is None and not child['platform_checked']
        else:
            assert row['summary']['status']=='blocked' and not row['summary']['platform_checked']
