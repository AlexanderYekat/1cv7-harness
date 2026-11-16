"""Independently re-read the 18 discovery/control reports of a completed 106 run."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from audit_utils import digest, read, write
from run import CASES, COUNTER, SERVICE, ADVANCE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    record = read(out/'verified.json')
    assert record['status']=='passed' and record['before']==record['after']
    assert [r['case'] for r in record['runs']]==list(CASES)
    assert [s['transport'] for s in record['suites']]==['cli','mcp']
    folders=[(r['case'],Path(r['folder'])) for r in record['runs']]
    for transport in record['suites']:
        directory=Path(transport['folder'])
        suite=read(directory/'suite.json')
        assert suite['complete'] and suite['status']=='failed' and not suite['cancelled']
        assert digest(directory/suite['junit']['path'])==suite['junit']['sha256']
        cases=ET.parse(directory/'junit.xml').getroot().findall('testsuite/testcase')
        assert [r['id'] for r in suite['scenarios']]==list(CASES) and len(cases)==6
        for row,case in zip(suite['scenarios'],cases):
            report=directory/row['report']['path']
            assert digest(report)==row['report']['sha256']
            assert (case.find('failure') is not None)==(row['id']=='overflow')
            assert case.find('error') is None and case.find('skipped') is None
            folders.append((row['id'],report.resolve().parent))
    canonical, artifacts, inputs = {}, 0, 0
    for name,folder in folders:
        report,platform=read(folder/'run.json'),read(folder/'platform-result.json')
        failed=name=='overflow'
        assert report['status']==('failed' if failed else 'passed') and report['platform_checked']
        assert not report['cancelled'] and not platform['shutdown']['forced_cleanup']
        assert digest(folder/'configuration/1Cv7.MD')==record['plans'][name]['md_sha256']
        for key in ('fixture_files','json_files'):
            for item in report['inputs'][key]:
                entry,=[f for f in report['result_files'] if f.get('role')==item['role'] and f.get('test_index')==item.get('test_index')]
                assert digest(folder/entry['path'])==entry['sha256']==item['sha256']
                assert entry['complete'] and entry['sha256_matches']
                inputs+=1
        steps=read(folder/'form/form-window.json')['steps']
        probes=[s for s in steps if s['kind']=='inspect_combo']
        data=[]
        if failed:
            assert len(probes)==1 and probes[0]['status']=='failed'
            assert 'item count exceeds 1000' in probes[0]['issue']
            assert 'inspection_file' not in probes[0] and 'combo_inspection' not in probes[0]
            assert not list((folder/'form').glob('combo-step-*.json'))
        else:
            assert all(s['status']=='passed' for s in steps) and len(probes)==2
            counts=[line for s in steps for line in s['round_trip'].get('messages',[]) if line.startswith(COUNTER)]
            assert counts==([COUNTER+'1'] if name=='counter-positive' else [])
            for step in probes:
                ref=step['inspection_file']
                payload=read(folder/ref['path'])
                entry,=[f for f in report['result_files'] if f['path']==ref['path']]
                assert digest(folder/ref['path'])==ref['sha256']==entry['sha256']
                assert entry['complete'] and entry['sha256_matches'] and ref['complete']
                assert payload['schema_version']==1 and payload['kind']=='combobox_inspection'
                assert payload['step_index']==step['index'] and payload['target']==step['target']
                assert payload['read_only_verified'] and step['combo_inspection']['focus_before']==step['combo_inspection']['focus_after']
                data.append(payload)
                artifacts+=1
            assert [p['target'] for p in data]==[SERVICE,ADVANCE]
            if name=='duplicates-empty-text':
                assert data[0]['items']==['','Дубль','Дубль'] and data[0]['selected_text']==''
                assert data[0]['selected_index']==0 and not data[0]['visible']
            elif name=='empty-list':
                assert data[0]['items']==[] and data[0]['selected_index'] is None and data[0]['selected_text'] is None
        tests=next(s for s in report['stages'] if s['stage']=='tests')['tests']
        assert tests[0]['expectation_met'] and tests[-1]['expectation_met']
        actual=next(o for o in platform['operations'] if o['name']=='verify')
        assert json.loads(actual['value'])==read(out/name/'expected.json')
        projection=dict(status=report['status'],reason=report['reason'],inspections=data,
            tests=[(t['name'],t['status'],t['expectation_met']) for t in tests])
        assert name not in canonical or canonical[name]==projection
        canonical[name]=projection
    assert len(folders)==18 and artifacts==30 and inputs==72
    write(out/'read-verification.json',dict(status='passed',reports=18,artifacts=artifacts,inputs=inputs,
        transport_results_equal=True,handler_counter_verified=True))
    print('106: 18 reports, 30 snapshots and 72 input snapshots independently verified')


if __name__=='__main__':
    main()
