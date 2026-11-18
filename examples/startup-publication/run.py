"""109: old/new runtime and real held-reader probes, with native cleanup and recovery."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'examples/application-suite'))
from mcp_client import Client

CASES=('baseline','transient-pre','transient-owned','persistent-pre','persistent-owned','deadline','after-failure')
PASS={'baseline','transient-pre','transient-owned','after-failure','after-cancel'}


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def audit(folder,mode,old=False):
    report,platform=read(folder/'run.json'),read(folder/'platform-result.json')
    expected='blocked' if old or mode not in PASS else 'passed'
    assert report['status']==expected,(mode,report)
    fault=read(folder/'fault109.json') if (folder/'fault109.json').exists() else None
    if mode.startswith('transient') or mode.startswith('persistent') or mode in ('deadline','cancel'):
        assert fault['injected'] and fault['replacement_errors']
        assert all(e['winerror'] in ((5,) if old else (5,32,33)) for e in fault['replacement_errors'])
        if not old:
            assert not fault['temporary_files']
    if old:
        # The old unguarded finish can escape before the outer shutdown summary.
        # The driver separately checks processes/registry/base/copy after each run.
        assert not report['platform_checked'] and 'WinError 5' in report['reason']
        assert fault['prior_sha256']==fault['last_sha256_before_release']
        return dict(mode=mode,status='blocked',folder=str(folder),forced=None)
    assert platform['shutdown']['cleanup_verified'],(mode,platform['shutdown'])
    assert platform['shutdown']['others_preserved'],(mode,platform['shutdown'])
    if expected=='passed':
        assert report['platform_checked'] and not platform['shutdown']['forced_cleanup']
        assert all(s['status']=='passed' for s in read(folder/'form/form-window.json')['steps'])
        trace=read(folder/'native/startup.json')
        assert trace['status']=='ready'
        if mode.startswith('transient'):
            assert any(r['winerror'] in (5,32,33) and r['recovered'] and r['attempts']>1 for r in trace['write_retries'])
            assert fault['released_after_s']>=0.15
    elif not old:
        trace=platform['open']['startup']
        assert trace['status']=='blocked' or mode=='cancel' and trace['status']=='cancelled'
        if mode.startswith('persistent'):
            assert 'StartupWriteError' in report['reason']
            assert trace['write_failures'][0]['elapsed_ms']<1500
            assert trace['write_failures'][0]['attempts']<=26
            assert platform['open']['startup']['publication_error']
            assert fault['prior_sha256']==fault['last_sha256_before_release']
        if mode=='persistent-owned':
            assert platform['shutdown']['forced_cleanup']
            assert any(e['stage']=='server_owned' and e['ownership_verified'] for e in trace['events'])
        elif mode=='persistent-pre':
            assert not platform['shutdown']['forced_cleanup']
            assert not any(e['stage']=='debugger_created' for e in trace['events'])
        if mode=='deadline':
            assert report['timeout_phase']=='open'
            assert fault['released_after_s']<1
        if mode=='cancel':
            assert report['cancelled']
            assert fault['released_after_s']<1
    return dict(mode=mode,status=expected,folder=str(folder),forced=platform['shutdown']['forced_cleanup'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('project','stand','old-python','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--baseline',type=Path,help='prior verified.json: require the same initial stand snapshot')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=a.resume)
    project,stand=a.project.resolve(),a.stand.resolve()
    from harness77 import basecopy77,__version__
    from harness77.doctor_windows77 import WindowsInspector,TITLES,COM_KEYS
    helper_spec=importlib.util.spec_from_file_location('helper109',ROOT/'examples/structured-checks/run.py')
    helper=importlib.util.module_from_spec(helper_spec);helper_spec.loader.exec_module(helper)
    data=tomllib.loads(stand.read_text(encoding='utf-8-sig'))
    base=Path(data['stand']['base']['path']);copy=Path(data['stand']['base']['copy_path'])
    def snapshot():
        return dict(listing=basecopy77.listing(base),hashes={n:helper.digest(base/n) for n in ('1Cv7.MD','1Cv7.DD','1CPP.dll','FormEx.dll')},
            registry={k:helper.registry_tree(k) for k in (TITLES,*COM_KEYS)},processes=WindowsInspector().processes(),
            copy=copy.exists(),lock=basecopy77.lock_path(copy).exists())
    before=snapshot();assert not before['copy'] and not before['lock']
    if a.baseline:assert before==read(a.baseline)['before'],'stand differs from the retained baseline'
    original=tomllib.loads(project.read_text(encoding='utf-8'))
    profile={}
    for mode in (*CASES,'cancel','after-cancel'):
        folder=out/mode;folder.mkdir(exist_ok=a.resume);(folder/'configuration').mkdir(exist_ok=a.resume)
        for n in ('module.1s','form.json','steps.json'):(folder/n).write_bytes(project.with_name(n).read_bytes())
        body=json.loads(json.dumps(original))
        body['project']['id']='h109-'+mode
        if mode=='deadline':body['deadlines']['open_timeout_s']=0.15
        (folder/'project.toml').write_text('\n'.join(json.dumps(k)+'='+helper.toml_value(v) for k,v in body.items())+'\n',encoding='utf-8')
        profile[mode]=folder/'project.toml'
    custom=json.loads(json.dumps(data));custom['stand'].pop('runtime')
    custom['stand']['launcher']=str(Path(__file__).with_name('launch.py').resolve())
    wrapper=out/'stand-controls.toml'
    wrapper.write_text('\n'.join(json.dumps(k)+'='+helper.toml_value(v) for k,v in custom.items())+'\n',encoding='utf-8')
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME')}
    env.update(PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    record=dict(status='running',before=before,version=__version__,runs=[],suites=[],old_controls=[])
    if a.resume:
        record=read(out/'verified.json');assert record['before']==before and record['version']==__version__
    def save():(out/'verified.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    def preserved():assert snapshot()==before
    def execute(label,args,python=sys.executable):
        if (out/(label+'.stdout.json')).exists():
            return read(out/(label+'.stdout.json'))
        r=subprocess.run([str(python),'-I','-B','-m','harness77',*map(str,args)],cwd=out,env=env,capture_output=True,timeout=3600)
        (out/(label+'.stdout.json')).write_bytes(r.stdout);(out/(label+'.stderr.log')).write_bytes(r.stderr)
        summary=json.loads(r.stdout)
        assert summary['status'] in ('passed','blocked'),(label,r.stdout,r.stderr)
        return summary
    save()
    for mode in ('transient-pre','transient-owned'):
        if any(r['mode']==mode for r in record['old_controls']):continue
        summary=execute('old-'+mode,['run','--project',profile[mode],'--stand',wrapper,'--output-root',out/'old-runs'],a.old_python)
        row=audit(Path(summary['run_dir']),mode,old=True);record['old_controls'].append(row)
        preserved();save();print('old '+mode+': blocked as expected',flush=True)
    for mode in CASES:
        if any(r['mode']==mode for r in record['runs']):continue
        selected=stand if mode in ('baseline','after-failure') else wrapper
        summary=execute('new-'+mode,['run','--project',profile[mode],'--stand',selected,'--output-root',out/'runs'])
        row=audit(Path(summary['run_dir']),mode);record['runs'].append(row)
        preserved();save();print(mode+': '+row['status'],flush=True)
    suite=out/'suite.toml'
    suite.write_text('schema_version=1\n[suite]\nid="startup109"\n'+''.join(
        '\n[[scenarios]]\nid='+json.dumps(m)+'\nproject='+json.dumps(profile[m].as_posix())+'\n' for m in CASES),encoding='utf-8')
    for transport in ('cli','mcp'):
        if any(r['transport']==transport for r in record['suites']):continue
        if transport=='cli':
            summary=execute('suite-cli',['suite','--suite',suite,'--stand',wrapper,'--output-root',out/'cli-suite'])
        else:
            client=Client(out,out/'mcp-traffic.json',env)
            try:
                response,progress=client.suite(dict(suite=str(suite),stand=str(wrapper),suite_id='startup109',output_root=str(out/'mcp-suite')))
                assert progress['ping_during'] and progress['ping_after']
                summary=response['structuredContent']['stdout'];record['mcp_progress']=progress
            finally:
                record['mcp_exit_code']=client.close();assert record['mcp_exit_code']==0
        f=Path(summary['suite_dir']);s=read(f/'suite.json')
        assert s['complete'] and not s['cancelled'] and s['status']=='blocked'
        assert [r['id'] for r in s['scenarios']]==list(CASES)
        assert all(r['report'] is not None for r in s['scenarios']),s.get('reason')
        xml=ET.parse(f/'junit.xml').getroot().findall('testsuite/testcase')
        assert len(xml)==len(CASES)
        rows=[]
        for row,case in zip(s['scenarios'],xml):
            report=f/row['report']['path']
            assert helper.digest(report)==row['report']['sha256']
            rows.append(audit(report.parent,row['id']))
            assert (case.find('error') is not None)==(row['id'] not in PASS)
        record['suites'].append(dict(transport=transport,folder=str(f),runs=rows))
        preserved();save();print(transport+' suite verified',flush=True)
    for mode in ('cancel','after-cancel'):
        if any(r['mode']==mode for r in record['runs']):continue
        summary=execute(mode,['run','--project',profile[mode],'--stand',wrapper if mode=='cancel' else stand,'--output-root',out/'runs'])
        row=audit(Path(summary['run_dir']),mode);record['runs'].append(row)
        preserved();save();print(mode+': '+row['status'],flush=True)
    record.update(status='passed',after=snapshot());save()


if __name__=='__main__':main()
