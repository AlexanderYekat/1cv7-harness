"""Task 030: post a saved document, then independently read its accounting entries.

Each native case uses run's verified copy. Expectations are recorded before launch
in docs/tasks/030-document-posting.md. No changes to the stand's source base.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_table77 as table

base, scenario = table.base, table.scenario
ROOT = base.ROOT
PROFILE = tomllib.loads((ROOT / 'examples/document-posting/scenario.toml').read_text(encoding='utf-8'))
POSTING = 'Документ/ГотоваяПродукция/МодульДокумента.1s'
HEADER = 'Процедура ОбработкаПроведения()'
REFUSAL = 'Harness77 отказ 030'
REFUSED = f'\n    Сообщить("{REFUSAL}");\n    СтатусВозврата(0);\n    Возврат;\n'
ERROR = '\n    Делитель77 = 0;\n    Х77 = 1 / Делитель77;\n'


def case(name, **changes):
    parameters = copy.deepcopy(PROFILE['platform']['parameters'])
    parameters.pop('form_object')
    return dict(id=name, form=table.PRODUCTION, object='Документ.ГотоваяПродукция', value=None,
                open='passed', result='passed', parameters=parameters,
                post='passed', post_value='1|1', verify_value=PROFILE['platform']['tests'][-1]['expect_value'], **changes)


CASES = [case('post-ok'), case('post-repeat')]
for name, injection in [('post-refused', REFUSED), ('post-error', ERROR)]:
    item = case(name)
    item.update(injection=injection, post='failed', post_value='0|0', verify_value='0|0|1|')
    CASES.append(item)
item = case('post-wrong')
item.update(verify_value='1|2|1|43>40:999:30;43>40:2:40;', wrong=True)
CASES.append(item)


def prepare(case, extraction, folder, baselines=None):
    project = scenario.prepare(case, extraction, folder, baselines)
    if case.get('injection'):
        original = (extraction / POSTING).read_text(encoding='utf-8')
        if original.count(HEADER) != 1:
            raise ValueError('unexpected document module')
        target = folder / 'configuration' / POSTING
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original.replace(HEADER, HEADER + case['injection']), encoding='utf-8', newline='\n')
    text = project.read_text(encoding='utf-8')
    marker = '[[platform.tests]]\nname = "data-verify"'
    post = ('[[platform.tests]]\nname = "document-post"\ncommand = "post"\n'
            f'expect = "{case["post"]}"\nexpect_value = "{case["post_value"]}"\n\n')
    if text.count(marker) != 1:
        raise ValueError('verification test not found')
    project.write_text(text.replace(marker, post + marker), encoding='utf-8', newline='\n')
    tomllib.loads(project.read_text(encoding='utf-8'))
    return project


def judge(case, observed):
    tests = observed['tests']
    passed = observed['run_status'] == ('failed' if case.get('wrong') else 'passed') and len(tests) == 4
    for test in tests:
        expected = not (case.get('wrong') and test['name'] in ('data-verify', 'persisted-entries'))
        passed = passed and test['expectation_met'] is expected
    operations = observed['operations']
    passed = passed and operations.get('post', {}).get('status') == case['post']
    passed = passed and operations.get('post', {}).get('value') == case['post_value']
    passed = passed and operations.get('verify', {}).get('value') == (
        PROFILE['platform']['tests'][-1]['expect_value'] if case.get('wrong') else case['verify_value'])
    return 'confirmed' if passed else 'contradicted'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stand', required=True, type=Path)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--output-root', type=Path, default=ROOT / '.artifacts/runs')
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    args.baselines = None
    if os.path.lexists(args.evidence):
        parser.error('evidence already exists')
    if set(args.case) - {c['id'] for c in CASES}:
        parser.error('unknown case')
    cases = [copy.deepcopy(c) for c in CASES if not args.case or c['id'] in args.case]
    if args.dry_run:
        stand = base.load_stand(args.stand)
        args.work.mkdir(parents=True, exist_ok=False)
        base.md77.extract(Path(stand.base) / '1Cv7.MD', args.work / 'extraction')
        for item in cases:
            folder = args.work / 'cases' / item['id']
            folder.mkdir(parents=True)
            prepare(item, args.work / 'extraction', folder)
            base.md77.build(Path(stand.base) / '1Cv7.MD', folder / 'configuration', folder / '1Cv7.MD')
        return 0
    return base.run_series(cases, args, 'task 030: document posting and persisted entries',
                           prepare_case=prepare, judge_case=judge)


if __name__ == '__main__':
    raise SystemExit(main())
