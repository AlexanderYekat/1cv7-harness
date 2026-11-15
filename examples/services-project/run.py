"""104: unchanged tests against a controlled form regression, through run/suite/MCP."""
import argparse
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

from audit_utils import digest, read, write, toml_value, registry_tree, md_difference
from mcp_client import Client

HERE = Path(__file__).resolve().parent
MODULE = 'Документ/ОказаниеУслуг/Форма.1s'
PHASES = ('baseline', 'regression', 'fixed', 'repeat-fixed')


def audit(folder, phase, plans, expected):
    report, platform = read(folder / 'run.json'), read(folder / 'platform-result.json')
    failed = phase == 'regression'
    assert report['status'] == ('failed' if failed else 'passed') and report['platform_checked']
    assert digest(folder / 'configuration/1Cv7.MD') == plans[phase]['md_sha256']
    assert not report['cancelled'] and platform['shutdown']['forced_cleanup'] is False
    tests = next(s for s in report['stages'] if s['stage'] == 'tests')['tests']
    assert next(t for t in tests if t['name'] == 'form-open')['expectation_met']
    assert next(t for t in tests if t['name'] == 'services-ui')['expectation_met'] == (not failed)
    structured = next(t for t in tests if t['name'] == 'persisted-services')['structured']
    actual = next(o for o in platform['operations'] if o['name'] == 'verify')
    assert actual['status'] == 'passed'
    wanted = json.loads(json.dumps(expected))
    differences = {}
    if failed:
        wanted['amount'] = wanted['total'] = '141'
        wanted['rows'][1]['amount'] = wanted['rows'][1]['total'] = '91'
        differences = {'/amount': ('140', '141'), '/total': ('140', '141'),
                       '/rows/1/amount': ('90', '91'), '/rows/1/total': ('90', '91')}
    assert json.loads(actual['value']) == wanted
    assert {d['path']: (d['expected'], d['actual']) for d in structured['differences']} == differences
    assert structured['difference_count'] == len(differences)
    result = structured['result']
    assert (folder / result['path']).read_bytes() == actual['value'].encode('utf-8')
    assert digest(folder / result['path']) == result['sha256']
    assert result['complete'] and result['sha256_matches']
    for key in ('fixture_files', 'json_files'):
        for item in report['inputs'][key]:
            snapshot, = [r for r in report['result_files'] if r.get('role') == item['role']
                         and r.get('test_index') == item.get('test_index')]
            assert digest(folder / snapshot['path']) == item['sha256'] == snapshot['sha256']
            assert snapshot['complete'] and snapshot['sha256_matches']
    steps = read(folder / 'form/form-window.json')['steps']
    save = next(s for s in steps if s['kind'] == 'click')
    assert save['target'] == 'КнопкаЗаписать' and save['status'] == 'passed'
    reopened = next(s for s in steps if s['kind'] == 'reopen')
    assert reopened['round_trip']['reopen_same'] == '1' and reopened['closed_before_reopen']
    if failed:
        bad = next(s for s in steps if s['kind'] == 'value' and s['target'] == 'Сумма' and s.get('status') != 'passed')
        assert bad['index'] > save['index'] and bad['round_trip']['value'] == '91'
    else:
        assert all(s['status'] == 'passed' for s in steps)
    return {'status': report['status'], 'differences': differences, 'raw': wanted}


def audit_suite(folder, plans, expected):
    suite = read(folder / 'suite.json')
    assert suite['status'] == 'failed' and suite['exit_code'] == 1 and suite['complete'] and not suite['cancelled']
    cases = ET.parse(folder / 'junit.xml').getroot().findall('testsuite/testcase')
    assert [r['id'] for r in suite['scenarios']] == list(PHASES) and len(cases) == len(PHASES)
    assert digest(folder / suite['junit']['path']) == suite['junit']['sha256']
    checked = []
    for row, case in zip(suite['scenarios'], cases):
        report = (folder / row['report']['path']).resolve()
        assert digest(report) == row['report']['sha256'] and report.stat().st_size == row['report']['size_bytes']
        result = audit(report.parent, row['id'], plans, expected)
        assert row['status'] == result['status'] and row['platform_checked']
        assert case.get('name') == row['id'] and case.find('error') is None and case.find('skipped') is None
        failure = case.find('failure')
        if row['id'] == 'regression':
            assert failure is not None and failure.get('message') == row['reason'] == read(report)['reason']
            assert json.loads(failure.text) == row['problems']
            projected = next(t for problem in row['problems'] for t in problem.get('unmet_tests', []) if t['name'] == 'persisted-services')
            child_tests = next(s for s in read(report)['stages'] if s['stage'] == 'tests')['tests']
            assert projected['structured']['diagnostics'] == next(t for t in child_tests if t['name'] == 'persisted-services')['structured']['diagnostics']
        else:
            assert failure is None and not row['problems']
        checked.append(result)
    return checked


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
    lock = basecopy77.lock_path(copy)
    inspector = WindowsInspector()
    frozen = {str(p): digest(p) for p in HERE.rglob('*') if p.is_file() and '.harness77' not in p.parts and '__pycache__' not in p.parts}
    def snapshot():
        return {'listing': basecopy77.listing(base),
            'hashes': {n: digest(base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
            'registry': {key: registry_tree(key) for key in (TITLES, *COM_KEYS)},
            'processes': inspector.processes(), 'copy': copy.exists(), 'lock': lock.exists()}
    before = snapshot()
    assert not before['copy'] and not before['lock']
    record = {'status': 'running', 'before': before, 'inputs': frozen, 'plans': {}, 'runs': [], 'suites': [],
              'environment': {'python': sys.executable, 'module': harness77.__file__, 'version': harness77.__version__}}
    def save():
        write(out / 'verified.json', record)
    def preserved():
        assert snapshot() == before, 'stand preservation failed'
        assert all(digest(Path(n)) == h for n, h in frozen.items()), 'test input changed'
    launcher = HERE / '.harness77/launch.py'
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    def execute(name, args, code=0):
        r = subprocess.run([sys.executable, '-I', '-B', str(launcher), *map(str, args)],
                           cwd=out, env=env, capture_output=True, timeout=1800)
        (out / (name + '.stdout.json')).write_bytes(r.stdout)
        (out / (name + '.stderr.log')).write_bytes(r.stderr)
        assert r.returncode == code, (name, r.returncode, r.stdout[-3000:], r.stderr[-3000:])
        return json.loads(r.stdout)
    client = None
    try:
        record['doctor'] = execute('doctor', ['doctor', '--output-root', out / 'future', '--format', 'json'])
        assert record['doctor']['status'] == 'ready'
        execute('extract', ['md-extract', base / '1Cv7.MD', '--output', out / 'extraction'])
        index = read(out / 'extraction/modules.json')
        target, = [m['path'] for m in index['modules'] if m['file'] == MODULE]
        original = (out / 'extraction' / MODULE).read_bytes().decode('utf-8')
        correct = 'ИначеЕсли (ИмяРеквизита = "Количество") Тогда\n\t\t\tСумма = Цена*Количество;'
        if '\r\n' in original:
            correct = correct.replace('\n', '\r\n')
        assert original.count(correct) == 1
        broken = original.replace(correct, correct.replace('Цена*Количество;', 'Цена*Количество + 1;'))
        sources = out / 'sources'
        sources.mkdir()
        for name, value in [('baseline', original), ('regression', broken), ('fixed', original)]:
            (sources / (name + '.1s')).write_bytes(value.encode('utf-8'))
        (sources / 'regression.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True), broken.splitlines(True), fromfile=MODULE, tofile=MODULE)), encoding='utf-8')
        common = tomllib.loads((HERE / 'project.toml').read_text(encoding='utf-8'))
        for field in ('template', 'source'):
            common['build'][field] = str(HERE / common['build'][field])
        for field in ('fixture_setup_file', 'fixture_verify_file', 'steps_file'):
            common['platform']['parameters'][field] = str(HERE / common['platform']['parameters'][field])
        common['platform']['tests'][-1]['expect_json_file'] = str(HERE / common['platform']['tests'][-1]['expect_json_file'])
        profiles = {}
        for phase in PHASES:
            configuration = out / 'configurations' / phase
            module = configuration / MODULE
            module.parent.mkdir(parents=True)
            source = broken if phase == 'regression' else original
            module.write_bytes(source.encode('utf-8'))
            (configuration / 'modules.json').write_bytes((out / 'extraction/modules.json').read_bytes())
            profile = json.loads(json.dumps(common))
            profile['configuration']['modules'] = str(configuration)
            path = out / (phase + '.toml')
            path.write_text('\n'.join(json.dumps(k) + '=' + toml_value(v) for k, v in profile.items()) + '\n', encoding='utf-8')
            profiles[phase] = path
            planned = out / (phase + '.MD')
            execute('build-' + phase, ['md-build', '--template', base / '1Cv7.MD', '--modules', configuration, '--output', planned])
            checked = md_difference(base / '1Cv7.MD', planned, target, source)
            assert bool(checked['changed_streams']) == (phase == 'regression')
            record['plans'][phase] = {'project': str(path), 'project_sha256': digest(path), 'md_sha256': digest(planned), 'audit': checked}
        save()
        expected = read(HERE / 'expected.json')
        for phase in PHASES:
            summary = execute('run-' + phase, ['run', '--project', profiles[phase], '--output-root', out / ('run-' + phase)], code=int(phase == 'regression'))
            checked = audit(Path(summary['run_dir']), phase, record['plans'], expected)
            record['runs'].append({'case': phase, 'folder': summary['run_dir'], 'verification': checked})
            preserved()
            save()
            print(phase + ': ' + summary['status'], flush=True)
        suite = out / 'cycle.toml'
        suite.write_text('schema_version=1\n[suite]\nid="services104-cycle"\n' + ''.join(
            '\n[[scenarios]]\nid=' + json.dumps(phase) + '\nproject=' + json.dumps(profiles[phase].as_posix()) + '\n' for phase in PHASES), encoding='utf-8')
        for transport in ('cli', 'mcp'):
            if transport == 'cli':
                summary = execute('suite-cli', ['suite', '--suite', suite, '--suite-id', 'cycle', '--output-root', out / 'cli-suite'], code=1)
            else:
                client = Client(out, out / 'mcp-traffic.json', env, command=[sys.executable, '-I', '-B', str(launcher), 'mcp'])
                response, progress = client.suite({'suite': str(suite), 'stand': str(HERE / 'stand.toml'), 'suite_id': 'cycle', 'output_root': str(out / 'mcp-suite')})
                write(out / 'mcp-response.json', {'response': response, 'progress': progress})
                assert not response['isError'] and response['structuredContent']['exit_code'] == 1
                assert progress['ping_during'] and progress['ping_after']
                summary = response['structuredContent']['stdout']
            folder = Path(summary['suite_dir'])
            checks = audit_suite(folder, record['plans'], expected)
            record['suites'].append({'transport': transport, 'folder': str(folder), 'verification': checks})
            preserved()
            save()
            print(transport + ' suite: verified', flush=True)
        record['mcp_exit_code'] = client.close()
        assert record['mcp_exit_code'] == 0
        client = None
        record['after'] = snapshot()
        record['unchanged_tests'] = True
        record['status'] = 'passed'
        save()
    except BaseException as error:
        record['status'] = 'failed'
        record['error'] = repr(error)
        record['after'] = snapshot()
        save()
        raise
    finally:
        if client:
            client.close()


if __name__ == '__main__':
    main()
