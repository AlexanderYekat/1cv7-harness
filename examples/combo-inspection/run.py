"""106: discover, prove no mutation, then select discovered text through all transports."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

from audit_utils import digest, read, write, toml_value, registry_tree, md_difference
from mcp_client import Client
from cycle import MODULE

HERE = Path(__file__).resolve().parent
SERVICE, ADVANCE = 'СписокТиповУслуг', 'ВариантЗачетаАванса'
COUNTER = 'handler106-count:'
CASES = ('read-only', 'duplicates-empty-text', 'empty-list', 'overflow', 'after-failure', 'counter-positive')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    import harness77
    from harness77 import basecopy77
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    assert Path(harness77.__file__).resolve().is_relative_to(HERE / '.harness77')
    assert not os.environ.get('PYTHONPATH') and not os.environ.get('PYTHONHOME')
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stand = tomllib.loads((HERE / 'stand.toml').read_text(encoding='utf-8'))['stand']
    base, copy = Path(stand['base']['path']), Path(stand['base']['copy_path'])
    def snapshot():
        return dict(listing=basecopy77.listing(base),
            hashes={n: digest(base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
            registry={k: registry_tree(k) for k in (TITLES, *COM_KEYS)},
            processes=WindowsInspector().processes(), copy=copy.exists(), lock=basecopy77.lock_path(copy).exists())
    before = snapshot()
    assert not before['copy'] and not before['lock']
    frozen = {n: digest(HERE / n) for n in ('fixture.1s', 'reader.1s')}
    record = dict(status='running', before=before, runs=[], suites=[], plans={}, runtime=harness77.__version__)
    def save(): write(out / 'verified.json', record)
    def preserved():
        assert snapshot() == before
        assert all(digest(HERE / n) == h for n,h in frozen.items())
    launcher = HERE / '.harness77/launch.py'
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    def execute(name, args, code=0):
        r = subprocess.run([sys.executable, '-I', '-B', str(launcher), *map(str,args)],
                           cwd=out, env=env, capture_output=True, timeout=1800)
        (out / (name + '.stdout.json')).write_bytes(r.stdout)
        (out / (name + '.stderr.log')).write_bytes(r.stderr)
        assert r.returncode == code, (name, r.returncode, r.stdout[-3000:], r.stderr[-1000:])
        return json.loads(r.stdout)
    execute('extract', ['md-extract', base / '1Cv7.MD', '--output', out / 'extraction'])
    index = read(out / 'extraction/modules.json')
    target, = [m['path'] for m in index['modules'] if m['file'] == MODULE]
    original = (out / 'extraction' / MODULE).read_text(encoding='utf-8')
    instrumented = 'Перем Счетчик106 Экспорт;\n' + original
    instrumented = instrumented.replace('Процедура ПриОткрытии()\n', 'Процедура ПриОткрытии()\n\tСчетчик106 = 0;\n')
    for heading in ('Процедура ПриВыбореТипаУслуги() ', 'Процедура ПриВыбореВариантаЗачетаАванса()'):
        assert instrumented.count(heading + '\n') == 1
        instrumented = instrumented.replace(heading + '\n', heading + '\n\tСчетчик106 = Счетчик106 + 1;\n\tСообщить("handler106");\n\tСообщить("handler106-count:" + СокрЛП(Строка(Счетчик106)));\n')
    ending = 'КонецПроцедуры // ПриОткрытии()'
    assert instrumented.count(ending) == 1
    common = tomllib.loads((HERE / 'project.toml').read_text(encoding='utf-8'))
    for field in ('template', 'source'):
        common['build'][field] = str(HERE / common['build'][field])
    for field in ('fixture_setup_file', 'fixture_verify_file'):
        common['platform']['parameters'][field] = str(HERE / common['platform']['parameters'][field])
    profiles, observed, canonical = {}, None, {}

    def audit(folder, name):
        report, platform = read(folder / 'run.json'), read(folder / 'platform-result.json')
        failed = name == 'overflow'
        assert report['status'] == ('failed' if failed else 'passed') and report['platform_checked']
        assert not platform['shutdown']['forced_cleanup']
        assert digest(folder / 'configuration/1Cv7.MD') == record['plans'][name]['md_sha256']
        tests = next(s for s in report['stages'] if s['stage'] == 'tests')['tests']
        assert tests[0]['expectation_met'] and tests[-1]['expectation_met']
        steps = read(folder / 'form/form-window.json')['steps']
        entries = [s for s in steps if s['kind'] == 'inspect_combo']
        data = []
        for s in entries:
            if s['status'] == 'failed':
                assert failed and 'item count exceeds 1000' in s['issue']
                assert 'inspection_file' not in s and 'combo_inspection' not in s
                assert not list((folder / 'form').glob('combo-step-*.json'))
                continue
            ref = s['inspection_file']
            item = read(folder / ref['path'])
            result, = [r for r in report['result_files'] if r['path'] == ref['path']]
            assert digest(folder / ref['path']) == ref['sha256'] == result['sha256']
            assert result['sha256_matches'] and result['complete'] and ref['complete']
            assert item['schema_version'] == 1 and item['step_index'] == s['index'] and item['target'] == s['target']
            assert item['read_only_verified'] and s['combo_inspection']['focus_before'] == s['combo_inspection']['focus_after']
            data.append(item)
        if not failed:
            assert all(s['status'] == 'passed' for s in steps)
            assert len(data) == 2
            counts = [line for s in steps for line in s['round_trip'].get('messages', []) if line.startswith(COUNTER)]
            assert counts == ([COUNTER+'1'] if name == 'counter-positive' else [])
            if name == 'duplicates-empty-text':
                assert data[0]['items'] == ['', 'Дубль', 'Дубль'] and data[0]['selected_index'] == 0 and data[0]['selected_text'] == ''
                assert not data[0]['visible'] and isinstance(data[0]['enabled'], bool)
            elif name == 'empty-list':
                assert data[0]['items'] == [] and data[0]['selected_index'] is None and data[0]['selected_text'] is None
            else:
                assert len(data[0]['items']) == 2 and data[0]['selected_index'] == 0
            assert len(data[1]['items']) == 3
        projection = dict(status=report['status'], reason=report['reason'], inspections=data,
                          tests=[(t['name'],t['status'],t['expectation_met']) for t in tests])
        assert name not in canonical or canonical[name] == projection
        canonical[name] = projection
        return data

    for name in CASES:
        directory = out / name
        directory.mkdir()
        setup = ''
        if name == 'duplicates-empty-text':
            setup = 'СписокТиповУслуг.УдалитьВсе();\nСписокТиповУслуг.ДобавитьЗначение("", "");\nСписокТиповУслуг.ДобавитьЗначение(2, "Дубль");\nСписокТиповУслуг.ДобавитьЗначение(3, "Дубль");\nСписокТиповУслуг.ТекущаяСтрока(1);\n'
            setup += 'Форма.СписокТиповУслуг.Видимость(0);\n'
        elif name == 'empty-list':
            setup = 'СписокТиповУслуг.УдалитьВсе();\n'
        elif name == 'overflow':
            setup = 'Для Номер106 = 3 По 1001 Цикл\nСписокТиповУслуг.ДобавитьЗначение(Номер106, "Пункт " + Строка(Номер106));\nКонецЦикла;\n'
        source = instrumented.replace(ending, setup + 'Счетчик106 = 0;\n' + ending).replace('\n', '\r\n')
        module = directory / 'configuration' / MODULE
        module.parent.mkdir(parents=True)
        module.write_bytes(source.encode('utf-8'))
        (directory / 'configuration/modules.json').write_bytes((out / 'extraction/modules.json').read_bytes())
        steps = [{'inspect_combo':SERVICE},{'no_message':'handler106'},
                 {'inspect_combo':ADVANCE},{'no_message':'handler106'}]
        expected = read(HERE / 'expected.json')
        expected['service_type'] = 1
        if name == 'counter-positive':
            assert observed is not None
            steps += [{'select':SERVICE,'text':observed[SERVICE]['items'][1]},
                      {'message':COUNTER+'1'}, {'click':'КнопкаЗаписать'}]
            expected['service_type'] = 2
        write(directory / 'steps.json', steps)
        write(directory / 'expected.json', expected)
        profile = json.loads(json.dumps(common))
        profile['configuration']['modules'] = str(directory / 'configuration')
        profile['platform']['parameters']['steps_file'] = str(directory / 'steps.json')
        profile['platform']['tests'][-1]['expect_json_file'] = str(directory / 'expected.json')
        path = directory / 'project.toml'
        path.write_text('\n'.join(json.dumps(k)+'='+toml_value(v) for k,v in profile.items())+'\n',encoding='utf-8')
        profiles[name] = path
        planned = directory / 'planned.MD'
        execute('build-'+name,['md-build','--template',base/'1Cv7.MD','--modules',directory/'configuration','--output',planned])
        checked = md_difference(base/'1Cv7.MD',planned,target,source)
        record['plans'][name] = dict(md_sha256=digest(planned),audit=checked)
        save()
        summary = execute('run-'+name,['run','--project',path,'--output-root',directory/'results'],code=int(name=='overflow'))
        data = audit(Path(summary['run_dir']),name)
        if name == 'read-only':
            observed = {d['target']:d for d in data}
            write(HERE/'discovery.json',observed)
        record['runs'].append(dict(case=name,folder=summary['run_dir']))
        preserved()
        save()
        print(name+': verified',flush=True)
    suite = out / 'probe-suite.toml'
    suite.write_text('schema_version=1\n[suite]\nid="inspect106"\n'+''.join(
        '\n[[scenarios]]\nid='+json.dumps(n)+'\nproject='+json.dumps(profiles[n].as_posix())+'\n' for n in CASES),encoding='utf-8')
    for transport in ('cli','mcp'):
        client = None
        try:
            if transport == 'cli':
                summary = execute('suite-cli',['suite','--suite',suite,'--suite-id','probes','--output-root',out/'cli'],code=1)
            else:
                client = Client(out,out/'mcp-traffic.json',env,command=[sys.executable,'-I','-B',str(launcher),'mcp'])
                response,progress = client.suite(dict(suite=str(suite),stand=str(HERE/'stand.toml'),suite_id='probes',output_root=str(out/'mcp')))
                write(out/'mcp-response.json',dict(response=response,progress=progress))
                assert not response['isError'] and response['structuredContent']['exit_code'] == 1
                assert progress['ping_during'] and progress['ping_after']
                summary = response['structuredContent']['stdout']
            folder = Path(summary['suite_dir'])
            result = read(folder/'suite.json')
            assert result['complete'] and result['status']=='failed' and not result['cancelled']
            cases = ET.parse(folder/'junit.xml').getroot().findall('testsuite/testcase')
            assert len(cases)==len(CASES) and [r['id'] for r in result['scenarios']]==list(CASES)
            for row,case in zip(result['scenarios'],cases):
                report = folder/row['report']['path']
                assert digest(report)==row['report']['sha256']
                audit(report.resolve().parent,row['id'])
                failure = case.find('failure')
                assert case.find('error') is None and case.find('skipped') is None
                assert (failure is not None)==(row['id']=='overflow')
                if failure is not None:
                    assert failure.get('message')==row['reason'] and json.loads(failure.text)==row['problems']
            if client:
                assert client.close()==0
                client=None
            record['suites'].append(dict(transport=transport,folder=str(folder)))
            preserved()
            save()
            print(transport+' probe suite: verified',flush=True)
        finally:
            if client: client.close()
    # Author the select text from the actual discovery, then freeze all inputs for the main cycle.
    initial, chosen = observed[SERVICE]['items']
    steps = [{'inspect_combo':SERVICE},{'inspect_combo':ADVANCE},
             {'check':SERVICE,'text':initial},{'select':SERVICE,'text':initial},
             {'select':SERVICE,'text':chosen},{'inspect_combo':SERVICE},
             {'check':SERVICE,'text':chosen},{'click':'КнопкаЗаписать'},
             {'close_form':True,'closes':True},{'reopen':True},{'inspect_combo':SERVICE},
             {'value':'ТипУслуги','text':'2'},{'check':SERVICE,'text':chosen},
             {'rows':2},{'total':'Сумма','text':'80'}]
    write(HERE/'steps.json',steps)
    subprocess.run([sys.executable,'-B',str(HERE/'cycle.py'),'--output',str(out/'cycle')],env=env,cwd=out,check=True,timeout=7200)
    subprocess.run([sys.executable,'-B',str(HERE/'verify.py'),str(out/'cycle')],env=env,cwd=out,check=True,timeout=180)
    preserved()
    record.update(status='passed',after=snapshot(),canonical=canonical,cycle=str(out/'cycle'))
    save()
    print('106: discovery, read-only proof and full cycle verified',flush=True)


if __name__=='__main__':
    main()
