"""Verify the compact Services fixture and reader on the qualified 1C 7.7 stand."""
import argparse
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

from harness77 import basecopy77
from harness77.doctor_windows77 import COM_KEYS, TITLES, WindowsInspector
from harness77.native_runtime77 import inspect_runtime

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'invoice-project'))
from verify import digest, md_difference, read, registry_tree, toml_value, write

MODULE = 'Документ/ОказаниеУслуг/Форма.1s'
PHASES = ('baseline', 'regression', 'fixed')


def regression_source(original):
    call = 'Процедура ПриЗаписи()'
    anchor = '\tОперация.Содержание = "Оказание услуг";'
    assert original.count(call) == original.count(anchor) == 1
    start = original.index(call)
    assert start < original.index(anchor) < original.index('КонецПроцедуры', start)
    newline = '\r\n' if '\r\n' in original else '\n'
    return original.replace(anchor, anchor + newline + '\tТипУслуги = 2;')


def audit(folder, phase, expected, inputs):
    failed = phase == 'regression'
    report = read(folder / 'run.json')
    platform = read(folder / 'platform-result.json')
    assert report['status'] == ('failed' if failed else 'passed') and report['platform_checked']
    assert not report['cancelled'] and report['timeout_phase'] is None
    shutdown = platform['shutdown']
    assert shutdown['cleanup_verified'] and shutdown['others_preserved'] and not shutdown['forced_cleanup']
    tests = next(stage for stage in report['stages'] if stage['stage'] == 'tests')['tests']
    tests = {test['name']: test for test in tests}
    assert tests['form-open']['expectation_met'] and tests['services-ui']['expectation_met']
    assert tests['persisted-services']['expectation_met'] is not failed

    reader = next(row for row in platform['operations'] if row['name'] == 'verify')
    assert reader['status'] == 'passed'
    actual = json.loads(reader['value'])
    assert actual == dict(expected, service_type=2 if failed else 1)
    structured = tests['persisted-services']['structured']
    differences = [(d['path'], d['expected'], d['actual']) for d in structured['differences']]
    assert structured['difference_count'] == int(failed)
    assert differences == ([('/service_type', 1, 2)] if failed else [])
    result = structured['result']
    raw = folder / result['path']
    assert result['complete'] and result['sha256_matches'] and digest(raw) == result['sha256']
    assert raw.read_bytes() == reader['value'].encode('utf-8')

    roles = {'fixture_setup': 'fixture.1s', 'fixture_verify': 'reader.1s',
             'steps': 'steps.json', 'expect_json': 'expected.json'}
    for role, name in roles.items():
        ref, = [file for file in report['result_files'] if file.get('role') == role]
        assert ref['complete'] and ref['sha256_matches'] and ref['sha256'] == inputs[name]
        assert digest(folder / ref['path']) == inputs[name]
    steps = read(folder / 'form/form-window.json')['steps']
    assert all(step['status'] == 'passed' for step in steps)
    assert any(step['kind'] == 'click' and step['target'] == 'КнопкаЗаписать' for step in steps)
    reopened = next(step for step in steps if step['kind'] == 'reopen')
    assert reopened['closed_before_reopen'] and reopened['round_trip']['reopen_same'] == '1'
    assert read(folder / 'launcher-environment.json')['runtime'] == inspect_runtime('forms')
    return dict(status=report['status'], actual=actual, differences=differences, raw_sha256=result['sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('project', 'stand', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--recipe', type=Path, default=HERE / 'services.toml')
    args = parser.parse_args()
    project, stand, out = args.project.resolve(), args.stand.resolve(), args.output.resolve()
    stand_settings = tomllib.loads(stand.read_text(encoding='utf-8-sig'))['stand']
    assert stand_settings['runtime'] == 'forms'
    base = Path(stand_settings['base']['path']).resolve(strict=True)
    copy = Path(stand_settings['base']['copy_path']).resolve()
    assert not out.is_relative_to(base) and not out.is_relative_to(copy)
    common = tomllib.loads(project.read_text(encoding='utf-8-sig'))
    assert common['platform']['parameters']['form_object'] == 'Документ.ОказаниеУслуг'
    assert common['platform']['parameters']['fixture_mode'] == 'existing'
    assert [row['name'] for row in common['platform']['tests']] == ['form-open', 'services-ui', 'persisted-services']
    out.mkdir(parents=True, exist_ok=False)
    env = {key: value for key, value in os.environ.items() if key not in ('PYTHONPATH', 'PYTHONHOME')}
    env['PYTHONIOENCODING'] = 'utf-8'

    def execute(name, command, expected_code=0):
        result = subprocess.run([sys.executable, '-I', '-B', *map(str, command)], cwd=out, env=env,
                                capture_output=True, timeout=1800)
        (out / (name + '.stdout.log')).write_bytes(result.stdout)
        (out / (name + '.stderr.log')).write_bytes(result.stderr)
        if result.returncode != expected_code:
            raise RuntimeError(f'{name}: exit {result.returncode}, expected {expected_code}. See {out}.')
        return result.stdout

    def snapshot():
        return dict(listing=basecopy77.listing(base), hashes={name: digest(base / name) for name in
                    ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')}, processes=WindowsInspector().processes(),
                    registry={key: registry_tree(key) for key in (TITLES, *COM_KEYS)}, copy=copy.exists(),
                    lock=basecopy77.lock_path(copy).exists())

    before = snapshot()
    assert not before['copy'] and not before['lock']
    record = dict(status='running', before=before, python=sys.executable, runtime=inspect_runtime('forms'), runs=[])
    try:
        sources = out / 'inputs'
        execute('render', [HERE / 'render.py', '--recipe', args.recipe.resolve(), '--output', sources])
        for name, source in {'services.toml': args.recipe, 'expected.json': HERE / 'expected.json',
                             'steps.json': HERE.parent / 'services-project/steps.json'}.items():
            (sources / name).write_bytes(source.read_bytes())
        inputs = {path.name: digest(path) for path in sources.iterdir()}
        record['inputs'] = inputs
        expected = read(sources / 'expected.json')
        assert expected == dict(read(HERE.parent / 'services-project/expected.json'), service_type=1)
        for field in ('template', 'source'):
            common['build'][field] = str((project.parent / common['build'][field]).resolve(strict=True))
        common['project']['id'] = 'services110'
        for field, name in (('fixture_setup_file', 'fixture.1s'), ('fixture_verify_file', 'reader.1s'),
                            ('steps_file', 'steps.json')):
            common['platform']['parameters'][field] = str(sources / name)
        common['platform']['tests'][-1]['expect_json_file'] = str(sources / 'expected.json')

        extraction = out / 'extraction'
        execute('extract', ['-m', 'harness77', 'md-extract', base / '1Cv7.MD', '--output', extraction])
        index = extraction / 'modules.json'
        target, = (item['path'] for item in read(index)['modules'] if item['file'] == MODULE)
        original = (extraction / MODULE).read_bytes().decode('utf-8')
        broken = regression_source(original)
        (out / 'regression.diff').write_text(''.join(difflib.unified_diff(
            original.splitlines(keepends=True), broken.splitlines(keepends=True), fromfile=MODULE, tofile=MODULE)),
            encoding='utf-8', newline='')
        for phase in PHASES:
            source = broken if phase == 'regression' else original
            config = out / 'configurations' / phase
            module = config / MODULE
            module.parent.mkdir(parents=True)
            module.write_bytes(source.encode('utf-8'))
            (config / 'modules.json').write_bytes(index.read_bytes())
            common['configuration']['modules'] = str(config)
            profile = out / (phase + '.toml')
            profile.write_text('\n'.join(json.dumps(key) + '=' + toml_value(value)
                                         for key, value in common.items()) + '\n', encoding='utf-8')
            summary = json.loads(execute(phase, ['-m', 'harness77', 'run', '--project', profile,
                                                 '--stand', stand, '--output-root', out / 'runs'],
                                         expected_code=int(phase == 'regression')))
            folder = Path(summary['run_dir'])
            result = audit(folder, phase, expected, inputs)
            md = md_difference(base / '1Cv7.MD', folder / 'configuration/1Cv7.MD', target, source)
            assert bool(md['changed_streams']) == (phase == 'regression')
            assert snapshot() == before and all(digest(sources / name) == sha for name, sha in inputs.items())
            record['runs'].append(dict(phase=phase, folder=str(folder), module_sha256=digest(module),
                                       configuration=md, **result))
            write(out / 'verified.json', record)
            print(phase, result['status'], result['differences'], flush=True)
        assert record['runs'][0]['module_sha256'] == record['runs'][2]['module_sha256']
        record['status'] = 'passed'
    except Exception as error:
        record.update(status='blocked', error=repr(error))
        raise
    finally:
        record['after'] = snapshot()
        write(out / 'verified.json', record)


if __name__ == '__main__':
    main()
