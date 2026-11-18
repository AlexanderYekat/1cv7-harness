"""Read-only independent audit of a completed 109 qualification and wheel."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def digest(data):return hashlib.sha256(data).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native',type=Path,required=True)
    p.add_argument('--package',type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[2]
    record=read(a.native/'verified.json');package=read(a.package/'summary.json')
    assert record['status']==package['status']=='passed'
    assert record['before']==record['after']
    wheel,=list((a.package/'dist').glob('*.whl'))
    installed=Path(package['python']).parents[1]/'Lib/site-packages'
    with zipfile.ZipFile(wheel) as archive:
        files=[n for n in archive.namelist() if n.startswith('harness77/')]
        for name in files:assert (installed/name).read_bytes()==archive.read(name),name
        manifest=read(installed/'harness77/_native/manifest.json')
        for name,sha in manifest['files'].items():
            assert digest((root/'research'/name).read_bytes())==sha,name
    rows=record['runs']+[r for s in record['suites'] for r in s['runs']]
    assert len(rows)==23 and Counter(r['status'] for r in rows)=={'passed':13,'blocked':10}
    assert len(record['old_controls'])==2
    assert record['mcp_exit_code']==0
    assert record['mcp_progress']['ping_during'] and record['mcp_progress']['ping_after']
    for suite in record['suites']:
        folder=Path(suite['folder']);summary=read(folder/'suite.json')
        cases=ET.parse(folder/'junit.xml').getroot().findall('testsuite/testcase')
        assert summary['complete'] and not summary['cancelled'] and summary['status']=='blocked'
        assert len(cases)==len(summary['scenarios'])==7
        assert summary['scenarios'][-1]['id']=='after-failure' and summary['scenarios'][-1]['status']=='passed'
        for scenario,case in zip(summary['scenarios'],cases):
            report=folder/scenario['report']['path']
            assert digest(report.read_bytes())==scenario['report']['sha256']
            assert (case.find('error') is not None)==(scenario['status']=='blocked')
    retries=[];failures=[];old_checked=set()
    for row in [*record['old_controls'],*rows]:
        folder=Path(row['folder']);report=read(folder/'run.json');platform=read(folder/'platform-result.json')
        assert report['status']==row['status']
        # inputs.*.sha256 identifies the source path for privacy; content hashes
        # belong to the build stage and the loaded JSON evidence instead.
        build=next(s for s in report['stages'] if s['stage']=='build')
        for name in ('module.1s','form.json','steps.json'):
            assert (a.native/row['mode']/name).read_bytes()==(root/'.artifacts/s108-native-project'/name).read_bytes()
        assert build['source_sha256']==digest((root/'.artifacts/s108-native-project/module.1s').read_bytes())
        assert build['form']['sha256']==digest((root/'.artifacts/s108-native-project/form.json').read_bytes())
        steps=next(x for x in report['inputs']['json_files'] if x['role']=='steps')
        assert steps['sha256']==digest((root/'.artifacts/s108-native-project/steps.json').read_bytes())
        fault=read(folder/'fault109.json') if (folder/'fault109.json').exists() else None
        old=row in record['old_controls']
        if fault:
            assert fault['runtime']['files_checked']==33
            if not old:
                assert fault['runtime']['manifest_sha256']==digest((installed/'harness77/_native/manifest.json').read_bytes())
                assert not fault['temporary_files']
            if fault['injected']:
                assert fault['replacement_errors']
                assert all(e['winerror'] in ((5,) if old else (5,32,33)) for e in fault['replacement_errors'])
                if row['status']=='blocked':assert fault['prior_sha256']==fault['last_sha256_before_release']
        if old:
            old_module=Path(fault['package'])
            if old_module not in old_checked:
                old_wheel,=list((old_module.parents[4]/'dist').glob('*.whl'))
                with zipfile.ZipFile(old_wheel) as archive:
                    for name in archive.namelist():
                        if name.startswith('harness77/'):
                            assert (old_module.parents[1]/name).read_bytes()==archive.read(name),name
                old_checked.add(old_module)
            continue
        assert platform['shutdown']['cleanup_verified']
        assert platform['shutdown']['others_preserved']
        trace=platform['open']['startup']
        if row['status']=='passed':
            assert report['platform_checked'] and not platform['shutdown']['forced_cleanup']
            window=read(folder/'form/form-window.json')
            assert len(window['steps'])==8 and all(s['status']=='passed' for s in window['steps'])
        if row['mode'].startswith('transient'):
            recovered=[r for r in trace['write_retries'] if r['recovered']]
            assert recovered and all(r['attempts']>1 for r in recovered)
            retries.extend(recovered)
        if row['mode'].startswith('persistent'):
            failure=trace['write_failures'][0]
            assert failure['attempts']<=26 and failure['elapsed_ms']<1500
            failures.append(failure)
        if row['mode']=='deadline':assert report['timeout_phase']=='open' and fault['released_after_s']<1
        if row['mode']=='cancel':assert report['cancelled'] and fault['released_after_s']<1
    result=dict(status='passed',native_runs=len(rows),old_controls=2,outcomes=dict(Counter(r['status'] for r in rows)),
                installed_files=len(files),native_sources=len(manifest['files']),wheel_sha256=digest(wheel.read_bytes()),
                recovered_publications=len(retries),persistent_publications=len(failures),
                max_persistent_ms=max(f['elapsed_ms'] for f in failures),stand_preserved=True)
    (a.native/'independent.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
