"""Qualify both document examples against a single persisted field regression."""
import argparse
import difflib
from importlib.resources import files
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

PHASES = ('baseline', 'regression', 'fixed')


def change_on_save(original, anchor, statement):
    call = 'Процедура ПриЗаписи()'
    assert original.count(call) == original.count(anchor) == 1
    start = original.index(call)
    assert start < original.index(anchor) < original.index('КонецПроцедуры', start)
    newline = '\r\n' if '\r\n' in original else '\n'
    return original.replace(anchor, anchor + newline + '\t' + statement)


def audit(folder, phase, expected, inputs, names, regression_value):
    failed = phase == 'regression'
    report = read(folder / 'run.json')
    platform = read(folder / 'platform-result.json')
    assert report['status'] == ('failed' if failed else 'passed') and report['platform_checked']
    assert not report['cancelled'] and report['timeout_phase'] is None
    shutdown = platform['shutdown']
    assert shutdown['cleanup_verified'] and shutdown['others_preserved'] and not shutdown['forced_cleanup']
    tests = next(stage for stage in report['stages'] if stage['stage'] == 'tests')['tests']
    tests = {test['name']: test for test in tests}
    assert tests[names['open']]['expectation_met'] and tests[names['result']]['expectation_met']
    persisted = tests[names['verify']]
    assert persisted['expectation_met'] == (not failed)

    reader = next(row for row in platform['operations'] if row['name'] == 'verify')
    assert reader['status'] == 'passed'
    actual = json.loads(reader['value'])
    field, wrong_value = regression_value
    assert actual == (expected | {field: wrong_value} if failed else expected)
    structured = persisted['structured']
    differences = [(d['path'], d['expected'], d['actual']) for d in structured['differences']]
    assert structured['difference_count'] == int(failed)
    assert differences == ([(f'/{field}', expected[field], wrong_value)] if failed else [])
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
    return dict(status=report['status'], actual=actual, differences=differences, raw_sha256=result['sha256'],
                ui_steps=len(steps))


def run(*, project_id, kind, recipe, steps_file, expected_file, mutate, regression_value):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('project', 'stand', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--recipe', type=Path)
    args = parser.parse_args()
    project, stand, out = args.project.resolve(), args.stand.resolve(), args.output.resolve()
    stand_settings = tomllib.loads(stand.read_text(encoding='utf-8-sig'))['stand']
    assert stand_settings['runtime'] == 'forms'
    base = Path(stand_settings['base']['path']).resolve(strict=True)
    copy = Path(stand_settings['base']['copy_path']).resolve()
    assert not out.is_relative_to(base) and not out.is_relative_to(copy)
    common = tomllib.loads(project.read_text(encoding='utf-8-sig'))
    assert common['platform']['parameters']['form_object'] == f'Документ.{kind}'
    assert common['platform']['parameters']['fixture_mode'] == 'existing'
    tests = common['platform']['tests']
    assert [row['command'] for row in tests] == ['open', 'result', 'verify']
    names = {test['command']: test['name'] for test in tests}
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
        recipe_input = (args.recipe if args.recipe is not None else
                        files('harness77').joinpath('fixture_recipes', recipe))
        render_args = ['-m', 'harness77', 'fixture-render', '--kind', Path(recipe).stem,
                       '--output', sources, '--format', 'json']
        if args.recipe is not None:
            render_args.extend(['--recipe', args.recipe.resolve()])
        rendered = json.loads(execute('render', render_args))
        for name, source in {recipe: recipe_input, 'expected.json': expected_file, 'steps.json': steps_file}.items():
            (sources / name).write_bytes(source.read_bytes())
        inputs = {path.name: digest(path) for path in sources.iterdir()}
        assert rendered['recipe']['sha256'] == inputs[recipe]
        assert all(rendered['files'][name]['sha256'] == inputs[name] for name in ('fixture.1s', 'reader.1s'))
        record['inputs'] = inputs
        expected = read(sources / 'expected.json')
        field, wrong_value = regression_value
        assert expected['kind'] == kind and expected[field] != wrong_value
        for field in ('template', 'source'):
            common['build'][field] = str((project.parent / common['build'][field]).resolve(strict=True))
        common['project']['id'] = project_id
        for field, name in (('fixture_setup_file', 'fixture.1s'), ('fixture_verify_file', 'reader.1s'),
                            ('steps_file', 'steps.json')):
            common['platform']['parameters'][field] = str(sources / name)
        tests[-1]['expect_json_file'] = str(sources / 'expected.json')

        extraction = out / 'extraction'
        execute('extract', ['-m', 'harness77', 'md-extract', base / '1Cv7.MD', '--output', extraction])
        index = extraction / 'modules.json'
        module_path = f'Документ/{kind}/Форма.1s'
        target, = (item['path'] for item in read(index)['modules'] if item['file'] == module_path)
        original = (extraction / module_path).read_bytes().decode('utf-8')
        broken = mutate(original)
        (out / 'regression.diff').write_text(''.join(difflib.unified_diff(
            original.splitlines(keepends=True), broken.splitlines(keepends=True),
            fromfile=module_path, tofile=module_path)),
            encoding='utf-8', newline='')
        for phase in PHASES:
            source = broken if phase == 'regression' else original
            config = out / 'configurations' / phase
            module = config / module_path
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
            result = audit(folder, phase, expected, inputs, names, regression_value)
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
