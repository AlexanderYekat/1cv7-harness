"""105: native missing/duplicate items and the selection formula's modal dialog."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--cycle', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    project, cycle, out = a.project.resolve(), a.cycle.resolve(), a.output.resolve()
    sys.path.insert(0, str(project))
    from audit_utils import digest, read, write, toml_value, registry_tree
    from run import MODULE
    from harness77 import basecopy77
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    assert not os.environ.get('PYTHONPATH') and not os.environ.get('PYTHONHOME')
    out.mkdir(parents=True, exist_ok=False)
    completed = read(cycle / 'verified.json')
    assert completed['status'] == 'passed'
    stand = tomllib.loads((project / 'stand.toml').read_text(encoding='utf-8'))['stand']
    base, copy = Path(stand['base']['path']), Path(stand['base']['copy_path'])
    def snapshot():
        return dict(listing=basecopy77.listing(base),
                    hashes={n: digest(base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                    registry={k: registry_tree(k) for k in (TITLES, *COM_KEYS)},
                    processes=WindowsInspector().processes(), copy=copy.exists(),
                    lock=basecopy77.lock_path(copy).exists())
    before = snapshot()
    assert before == completed['after']
    original = (cycle / 'sources/baseline.1s').read_text(encoding='utf-8')
    common = tomllib.loads((cycle / 'baseline.toml').read_text(encoding='utf-8'))
    results = []
    for name in ('missing', 'duplicate', 'modal'):
        directory = out / name
        directory.mkdir()
        source = original
        steps = read(project / 'steps.json')
        expected = read(project / 'expected.json')
        if name == 'missing':
            steps = [{'select': 'СписокТиповУслуг', 'text': 'Оказание посредн.'}]
        elif name == 'duplicate':
            line = 'СписокТиповУслуг.ТекущаяСтрока(ТипУслуги);'
            assert source.count(line) == 1
            source = source.replace(line, 'СписокТиповУслуг.ДобавитьЗначение(3, "Оказание посредн. услуг в торговле");\n\t' + line)
            steps = [{'select': 'СписокТиповУслуг', 'text': 'Оказание посредн. услуг в торговле'}]
        else:
            line = 'ТипУслуги = СписокТиповУслуг.ТекущаяСтрока();'
            assert source.count(line) == 1
            source = source.replace(line, line + '\n\t\tПредупреждение("COMBO105 выбран");')
            steps.insert(3, {'dialog': 'COMBO105 выбран', 'button': 'ОК'})
        if name != 'modal':
            expected['service_type'] = 1
        module = directory / 'configuration' / MODULE
        module.parent.mkdir(parents=True)
        module.write_text(source, encoding='utf-8')
        (directory / 'configuration/modules.json').write_bytes((cycle / 'extraction/modules.json').read_bytes())
        write(directory / 'steps.json', steps)
        write(directory / 'expected.json', expected)
        profile = json.loads(json.dumps(common))
        profile['configuration']['modules'] = str(directory / 'configuration')
        profile['platform']['parameters']['steps_file'] = str(directory / 'steps.json')
        profile['platform']['tests'][-1]['expect_json_file'] = str(directory / 'expected.json')
        path = directory / 'project.toml'
        path.write_text('\n'.join(json.dumps(k) + '=' + toml_value(v) for k, v in profile.items()) + '\n', encoding='utf-8')
        r = subprocess.run([sys.executable, '-I', '-B', str(project / '.harness77/launch.py'), 'run',
                            '--project', str(path), '--output-root', str(directory / 'results')],
                           cwd=out, capture_output=True, timeout=1800)
        (directory / 'stdout.json').write_bytes(r.stdout)
        (directory / 'stderr.log').write_bytes(r.stderr)
        assert r.returncode == (0 if name == 'modal' else 1), (name, r.stdout, r.stderr)
        summary = json.loads(r.stdout)
        folder = Path(summary['run_dir'])
        report, platform = read(folder / 'run.json'), read(folder / 'platform-result.json')
        tests = next(s for s in report['stages'] if s['stage'] == 'tests')['tests']
        assert tests[0]['expectation_met'] and tests[-1]['expectation_met']
        assert not platform['shutdown']['forced_cleanup']
        executed = read(folder / 'form/form-window.json')['steps']
        if name == 'modal':
            assert all(s['status'] == 'passed' for s in executed)
            action = executed[2]['action']
            assert action['selection_verified'] and action['notification_sent']
            assert executed[3]['kind'] == 'dialog' and executed[3]['answer']['requested']
        else:
            assert len(executed) == 1 and executed[0]['status'] == 'failed'
            action = executed[0]['action']
            assert ('0 matching items' if name == 'missing' else '2 matching items') in action['refused']
            assert action['before']['index'] == 0 and not action['requested']
        assert snapshot() == before
        results.append(dict(case=name, status=summary['status'], folder=str(folder)))
        write(out / 'verified.json', dict(status='running', results=results))
        print(name + ': verified', flush=True)
    assert all(digest(Path(n)) == h for n, h in completed['inputs'].items())
    write(out / 'verified.json', dict(status='passed', results=results, before=before, after=snapshot()))


if __name__ == '__main__':
    main()
