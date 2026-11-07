"""Prepare task 030 profiles and suites for the pinned stand, without starting 1C."""
import argparse
import json
from pathlib import Path
import re
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATE = ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT'
SOURCE = ROOT / 'research/forms/probe_module77.1s'
POSTING = 'Документ/ГотоваяПродукция/МодульДокумента.1s'
HEADER = 'Процедура ОбработкаПроведения()'
REFUSAL = '\n    Сообщить("Harness77 отказ 030");\n    СтатусВозврата(0);\n    Возврат;\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stand', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new directory')
    args = parser.parse_args()
    text = args.stand.resolve(strict=True).read_text(encoding='utf-8')
    stand = tomllib.loads(text)['stand']
    if not stand['base'].get('copy_path'):
        parser.error('stand needs its registered copy_path')
    paths = [stand.get('launcher'), *stand.get('paths', {}).values(), stand['base']['path'], stand['base']['copy_path']]
    if any(value and not Path(value).is_absolute() for value in paths):
        parser.error('this example requires absolute paths in the stand')
    from harness77.ert_module import CompoundFile
    from harness77.md77 import read_modules
    from harness77.metadata77 import Metadata
    data = (Path(stand['base']['path']) / '1Cv7.MD').read_bytes()
    original = next(m.raw.decode('cp1251') for m in read_modules(CompoundFile(data), Metadata(data)) if m.file == POSTING)
    if original.count(HEADER) != 1:
        parser.error('unexpected posting module of the pinned stand')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scenario = (HERE / 'scenario.toml').read_text(encoding='utf-8')
    for name in ('success', 'refused', 'wrong'):
        folder = output / name
        modules = folder / 'configuration'
        modules.mkdir(parents=True)
        content = scenario
        if name == 'refused':
            target = modules / POSTING
            target.parent.mkdir(parents=True)
            target.write_text(original.replace(HEADER, HEADER + REFUSAL), encoding='utf-8', newline='\n')
            content = content.replace('name = "document-post"\ncommand = "post"\nexpect = "passed"\nexpect_value = "1|1"',
                                      'name = "document-post"\ncommand = "post"\nexpect = "failed"\nexpect_value = "0|0"')
            content = content.replace('expect_value = "1|2|1|43>40:3:30;43>40:2:40;"', 'expect_value = "0|0|1|"')
        if name == 'wrong':
            content = content.replace('43>40:3:30;', '43>40:999:30;')
        header = '\n'.join(['schema_version = 1', '', '[project]', f'id = "posting-{name}"', '', '[build]',
                            f'template = {json.dumps(TEMPLATE.as_posix())}', f'source = {json.dumps(SOURCE.as_posix())}',
                            'encoding = "utf-8"', '', '[configuration]', f'modules = {json.dumps(modules.as_posix())}',
                            '', '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120',
                            'cancel_timeout_s = 15', 'shutdown_timeout_s = 30', 'total_timeout_s = 600', '', ''])
        tomllib.loads(header + content)
        (folder / 'project.toml').write_text(header + content, encoding='utf-8', newline='\n')
    text, count = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps(
        (ROOT / 'research/forms/form_launcher77.py').as_posix()), text)
    if count != 1:
        parser.error('stand must have one launcher line')
    (output / 'stand.toml').write_text(text, encoding='utf-8', newline='\n')
    for name, cases in [('suite', [('success', 'success'), ('refused', 'refused'), ('repeat', 'success')]),
                        ('suite-failure', [('wrong', 'wrong'), ('after-failure', 'success')])]:
        manifest = ['schema_version = 1', '', '[suite]', f'id = "document-posting-{name}"', '']
        for id_, project in cases:
            manifest += ['[[scenarios]]', f'id = "{id_}"', f'project = "{project}/project.toml"', '']
        (output / (name + '.toml')).write_text('\n'.join(manifest), encoding='utf-8', newline='\n')
    print(json.dumps({'output': str(output), 'stand': str(output / 'stand.toml'),
                      'suite': str(output / 'suite.toml')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
