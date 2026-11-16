"""108: exact native list assertions across run, CLI suite and stdio MCP."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import tomllib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'examples/application-suite'))
from mcp_client import Client

ITEMS = ['Первый', '', 'Дубль', 'Дубль', ' а ']
CASES = {
    'baseline': (ITEMS, None),
    'remove': (ITEMS[:-1], 4),
    'add': (ITEMS+['Хвост'], 5),
    'rename': (ITEMS[:3]+['Другой', ITEMS[4]], 3),
    'reorder': (ITEMS[:3]+[ITEMS[4], ITEMS[3]], 3),
    'case': (ITEMS[:4]+[' А '], 4),
    'spaces': (ITEMS[:4]+['а'], 4),
    'fixed': (ITEMS, None),
    'repeat-fixed': (ITEMS, None),
    'empty': ([], None),
}


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def audit(folder, name):
    actual, index = CASES[name]
    expected = [] if name == 'empty' else ITEMS
    status = 'passed' if index is None else 'failed'
    report, platform = read(folder/'run.json'), read(folder/'platform-result.json')
    assert report['status'] == status and report['platform_checked'] and not report['cancelled']
    assert platform['shutdown']['cleanup_verified'] and not platform['shutdown']['forced_cleanup']
    opened = next(o for o in platform['operations'] if o['name'] == 'open')
    assert opened['form']['units']['consistent'] and opened['form']['units']['max_residual_px'] <= 2
    records = read(folder/'form/form-window.json')['steps']
    checks = [s for s in records if s['kind'] == 'check_combo']
    assert len(checks) == (1 if index is not None or name == 'empty' else 3)
    snapshots, comparisons = [], []
    for step in checks:
        assert step['items'] == expected
        comparison = step['combo_comparison']
        assert comparison['expected_count'] == len(expected) and comparison['actual_count'] == len(actual)
        assert comparison['matches'] is (index is None)
        if index is None:
            assert comparison['first_difference'] is None
        else:
            wanted, shown = expected[index] if index < len(expected) else None, actual[index] if index < len(actual) else None
            assert comparison['first_difference'] == dict(index=index, path=f'/items/{index}',
                expected=wanted, actual=shown, expected_present=index < len(expected), actual_present=index < len(actual))
            assert f'items[{index}]' in step['issue']
            assert len(records) == 1 and records[0]['status'] == 'failed'
        ref = step['inspection_file']
        path = folder/ref['path']
        assert ref['complete'] and digest(path) == ref['sha256'] and path.stat().st_size == ref['size']
        exported, = [f for f in report['result_files'] if f.get('path') == ref['path']]
        assert exported['sha256_matches'] and exported['sha256'] == ref['sha256']
        snapshot = read(path)
        assert snapshot['items'] == actual and snapshot['read_only_verified']
        assert step['combo_inspection']['focus_before'] == step['combo_inspection']['focus_after']
        wanted_index = None if name == 'empty' else (1 if len(snapshots) == 2 else 0)
        assert snapshot['selected_index'] == wanted_index
        assert snapshot['selected_text'] == (actual[wanted_index] if wanted_index is not None else None)
        snapshots.append(snapshot)
        comparisons.append(comparison)
    if index is None:
        assert all(s['status'] == 'passed' for s in records)
        if name != 'empty':
            selections = [s['action'] for s in records if s['kind'] == 'select']
            assert selections[0]['unchanged'] and not selections[0]['notification_sent']
            assert selections[1]['notification_sent'] and selections[1]['selection_verified']
            assert any(s['kind'] == 'message' and s['target'] == 'handler108:1:2' for s in records)
    for item in report['inputs']['json_files']:
        ref, = [f for f in report['result_files'] if f.get('role') == item['role'] and f.get('test_index') == item.get('test_index')]
        assert digest(folder/ref['path']) == item['sha256'] == ref['sha256']
    return dict(status=status, reason=report['reason'], comparisons=comparisons, snapshots=snapshots,
                geometry_residual_px=opened['form']['units']['max_residual_px'])


def audit_suite(folder):
    data = read(folder/'suite.json')
    assert data['complete'] and data['status'] == 'failed' and not data['cancelled']
    assert [r['id'] for r in data['scenarios']] == list(CASES)
    assert digest(folder/'junit.xml') == data['junit']['sha256']
    cases = ET.parse(folder/'junit.xml').getroot().findall('testsuite/testcase')
    assert len(cases) == len(CASES)
    result = {}
    for row, case in zip(data['scenarios'], cases):
        assert case.get('name') == row['id']
        path = folder/row['report']['path']
        assert digest(path) == row['report']['sha256']
        result[row['id']] = audit(path.parent, row['id'])
        assert case.find('error') is None and case.find('skipped') is None
        assert (case.find('failure') is not None) is (CASES[row['id']][1] is not None)
        failure = case.find('failure')
        if failure is not None:
            assert failure.get('message') == row['reason']
            assert json.loads(failure.text) == row['problems']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('project', 'stand', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--resume', action='store_true', help='resume after inspecting a retained infrastructure failure')
    args = parser.parse_args()
    project, stand, out = args.project.resolve(), args.stand.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=args.resume)
    from harness77 import basecopy77, __version__
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    spec = importlib.util.spec_from_file_location('audit108', ROOT/'examples/structured-checks/run.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    base = tomllib.loads(stand.read_text(encoding='utf-8-sig'))['stand']['base']
    def snapshot():
        return dict(listing=basecopy77.listing(Path(base['path'])),
            hashes={n: digest(Path(base['path'])/n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
            registry={key: helper.registry_tree(key) for key in (TITLES, *COM_KEYS)},
            processes=WindowsInspector().processes(), copy=Path(base['copy_path']).exists(),
            lock=basecopy77.lock_path(Path(base['copy_path'])).exists())
    before = snapshot()
    assert not before['copy'] and not before['lock']
    original = project.with_name('module.1s').read_bytes()
    frozen = {n: digest(project.with_name(n)) for n in ('module.1s', 'form.json', 'steps.json')}
    record = dict(status='running', before=before, inputs=frozen, runs=[], suites=[], version=__version__,
                  module=__import__('harness77').__file__)
    if args.resume:
        record = read(out/'verified.json')
        assert record['before'] == before and record['inputs'] == frozen and record['version'] == __version__
    def save():
        (out/'verified.json').write_text(json.dumps(record,ensure_ascii=False,indent=2), encoding='utf-8')
    def preserved():
        assert snapshot() == before
        assert all(digest(project.with_name(n)) == sha for n,sha in frozen.items())
    env = {k:v for k,v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    def execute(label, arguments, code):
        if (out/(label+'.stdout.json')).exists():
            label += '-attempt-'+uuid.uuid4().hex[:8]
        r = subprocess.run([sys.executable,'-I','-B','-m','harness77',*map(str,arguments)],
            cwd=out,env=env,capture_output=True,timeout=7200)
        (out/(label+'.stdout.json')).write_bytes(r.stdout)
        (out/(label+'.stderr.log')).write_bytes(r.stderr)
        record.setdefault('attempts',[]).append(dict(label=label,exit_code=r.returncode,
            expected_exit_code=code,summary=json.loads(r.stdout)))
        save()
        assert r.returncode == code,(label,r.stdout.decode('utf-8'),r.stderr.decode('utf-8'))
        return json.loads(r.stdout)
    profiles = {}
    for name,(items,index) in CASES.items():
        folder = out/name
        folder.mkdir(exist_ok=args.resume)
        (folder/'configuration').mkdir(exist_ok=args.resume)
        planned = {n: project.with_name(n).read_bytes() for n in ('form.json','steps.json','project.toml')}
        source = original
        if index is not None or name == 'empty':
            text = original.decode('utf-8')
            start = text.index('    // ITEMS108-BEGIN')
            end = text.index('    // ITEMS108-END',start)
            block = '    // ITEMS108-BEGIN\n' + ''.join(
                f'    Список77.ДобавитьЗначение({json.dumps(item,ensure_ascii=False)}, {json.dumps(item,ensure_ascii=False)});\n'
                for item in items)
            if items:
                block += '    Список77.ТекущаяСтрока(1);\n'
            source = (text[:start]+block+text[end:]).encode('utf-8')
        planned['module.1s'] = source
        if name == 'empty':
            planned['steps.json'] = json.dumps([{'check_combo':'Список77','items':[]},
                {'no_message':'handler108'}],ensure_ascii=False).encode('utf-8')
        for n,data in planned.items():
            if (folder/n).exists():
                assert (folder/n).read_bytes() == data, 'scenario changed before resume: '+str(folder/n)
            else:
                (folder/n).write_bytes(data)
        profiles[name] = folder/'project.toml'
    save()
    canonical = {}
    for name,profile in profiles.items():
        previous = next((r for r in record['runs'] if r['case'] == name),None)
        if previous:
            canonical[name] = audit(Path(previous['folder']),name)
            continue
        summary = execute('run-'+name,['run','--project',profile,'--stand',stand,'--output-root',out/'runs'], int(CASES[name][1] is not None))
        folder = Path(summary['run_dir'])
        canonical[name] = audit(folder,name)
        record['runs'].append(dict(case=name,folder=str(folder)))
        preserved();save()
        print(name+': '+canonical[name]['status'],flush=True)
    suite = out/'suite.toml'
    suite.write_text('schema_version=1\n[suite]\nid="combo108"\n'+''.join(
        '\n[[scenarios]]\nid='+json.dumps(n)+'\nproject='+json.dumps(p.as_posix())+'\n'
        for n,p in profiles.items()),encoding='utf-8')
    for transport in ('cli','mcp'):
        previous = next((r for r in record['suites'] if r['transport'] == transport),None)
        if previous:
            assert audit_suite(Path(previous['folder'])) == canonical
            continue
        if transport == 'cli':
            summary = execute('suite-cli',['suite','--suite',suite,'--stand',stand,'--output-root',out/'cli-suite'],1)
        else:
            client = Client(out,out/'mcp-traffic.json',env)
            try:
                response,progress = client.suite(dict(suite=str(suite),stand=str(stand),suite_id='combo108',output_root=str(out/'mcp-suite')))
                assert not response['isError'] and response['structuredContent']['exit_code'] == 1
                assert progress['ping_during'] and progress['ping_after']
                summary = response['structuredContent']['stdout']
                record['mcp_progress'] = progress
            finally:
                record['mcp_exit_code'] = client.close()
                assert record['mcp_exit_code'] == 0
        folder = Path(summary['suite_dir'])
        assert audit_suite(folder) == canonical
        record['suites'].append(dict(transport=transport,folder=str(folder)))
        preserved();save()
        print(transport+' suite verified',flush=True)
    record.update(status='passed',after=snapshot(),canonical=canonical)
    save()


if __name__ == '__main__':
    main()
