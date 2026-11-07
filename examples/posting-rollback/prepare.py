"""Prepare task 032 rollback scenarios on the pinned stand without starting 1C."""
import argparse
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]
POSTING = 'Документ/ГотоваяПродукция/МодульДокумента.1s'
ANCHOR = 'Операция.НомерЖурнала = "ТВ";'
MARKER = 'HARNESS77-032-PARTIAL:'
INITIAL = '1|2|1|43>40:3:30;43>40:2:40;|source:3:30'
ROLLED_BACK = '1|2|1|43>40:3:30;43>40:2:40;|source:5:50'
CHANGED = '1|2|1|43>40:5:50;43>40:2:40;|source:5:50'
EMPTY = '0|0|1||source:3:30'

INJECTION = '''
        Если (НомерСтроки = 1) И ((Комментарий = "Harness77 runtime 032") ИЛИ
            (Комментарий = "Harness77 refusal 032")) Тогда
            Операция.Записать();
            Контроль77 = СоздатьОбъект("Операция");
            Число77 = 0; Кол77 = 0; Сум77 = 0;
            Если Контроль77.НайтиОперацию(ТекущийДокумент()) = 1 Тогда
                Контроль77.ВыбратьПроводки();
                Пока Контроль77.ПолучитьПроводку() = 1 Цикл
                    Число77 = Число77 + 1;
                    Кол77 = Контроль77.Количество; Сум77 = Контроль77.Сумма;
                КонецЦикла;
            КонецЕсли;
            Сообщить("HARNESS77-032-PARTIAL:" + СокрЛП(Комментарий) + ":"
                + Строка(Число77) + ":" + Строка(Кол77) + ":" + Строка(Сум77));
            Если Комментарий = "Harness77 runtime 032" Тогда
                Делитель77 = 0;
                Ошибка77 = 1 / Делитель77;
            Иначе
                Сообщить("HARNESS77-032-REFUSAL");
                СтатусВозврата(0);
                Возврат;
            КонецЕсли;
        КонецЕсли;
'''


def posting_module(original):
    if original.count(ANCHOR) != 1 or original.count('Процедура ОбработкаПроведения()') != 1:
        raise ValueError('unexpected posting module of the pinned stand')
    return original.replace(ANCHOR, ANCHOR + INJECTION)


def before(mode, change=False):
    code = f'Док77Проведения.Комментарий = "{("Harness77 " + mode + " 032") if mode else ""}";\n'
    if change:
        code += ('Док77Проведения.ПолучитьСтрокуПоНомеру(1);\n'
                 'Док77Проведения.Количество = 5;\nДок77Проведения.Сумма = 50;\n')
    return code + 'Док77Проведения.Записать();'


def profile(mode, wrong=False):
    text = (ROOT / 'examples/document-posting/scenario.toml').read_text(encoding='utf-8')
    text = text.split('[[platform.tests]]')[0].replace('fixture_post = true\n', '')
    text = text.replace('Harness77 продукция 030', 'Harness77 продукция 032')
    # Read the saved input independently, in addition to every saved accounting entry.
    text = text.replace('Опер77 = СоздатьОбъект("Операция");',
                        'Док77.ПолучитьСтрокуПоНомеру(1);\n'
                        'Источник77 = "|source:" + Строка(Док77.Количество) + ":" + Строка(Док77.Сумма);\n'
                        'Опер77 = СоздатьОбъект("Операция");')
    text = text.replace('+ "|" + Проводки77;', '+ "|" + Проводки77 + Источник77;')
    steps = [('first', before(mode), 'failed', EMPTY),
             ('recover', before(''), 'passed', INITIAL),
             ('repost', before(mode, change=True), 'failed', ROLLED_BACK),
             ('final', before(''), 'passed', CHANGED)]
    operations = ['{ id = ' + json.dumps(id_) + ', action = "post", before = ' + "'''" + code + "''' }"
                  for id_, code, _, _ in steps]
    text = text.replace('steps = [', 'fixture_operations = [\n' + ',\n'.join(operations) + '\n]\nsteps = [')
    tests = [('open', 'passed', '1'), ('result', 'passed', None)]
    for id_, _, status, value in steps:
        tests += [('post-' + id_, status, '1|1' if status == 'passed' else None),
                  ('verify-' + id_, 'passed', value.replace(':3:30;', ':999:30;')
                   if wrong and id_ == 'repost' else value)]
    tests += [('verify', 'passed', CHANGED)]
    for command, status, value in tests:
        text += '\n[[platform.tests]]\nname = ' + json.dumps(command) + '\ncommand = ' + json.dumps(command)
        text += '\nexpect = ' + json.dumps(status) + '\n'
        if value is not None:
            text += 'expect_value = ' + json.dumps(value) + '\n'
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stand', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new directory')
    args = parser.parse_args()
    text = args.stand.resolve(strict=True).read_text(encoding='utf-8')
    stand = tomllib.loads(text)['stand']
    paths = [stand['base']['path'], stand['base'].get('copy_path'), stand.get('launcher'),
             *stand.get('paths', {}).values()]
    if any(not p or not Path(p).is_absolute() for p in paths):
        parser.error('requires absolute stand paths and registered copy_path')
    from harness77.ert_module import CompoundFile
    from harness77.md77 import read_modules
    from harness77.metadata77 import Metadata
    data = (Path(stand['base']['path']) / '1Cv7.MD').read_bytes()
    original = next(m.raw.decode('cp1251') for m in read_modules(CompoundFile(data), Metadata(data)) if m.file == POSTING)
    modified = posting_module(original)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name, mode in [('runtime', 'runtime'), ('refusal', 'refusal'), ('wrong', 'runtime')]:
        folder = output / name
        modules = folder / 'configuration'
        target = modules / POSTING
        target.parent.mkdir(parents=True)
        target.write_text(modified, encoding='utf-8', newline='\n')
        header = '\n'.join(['schema_version = 1', '', '[project]', f'id = "rollback-{name}"', '', '[build]',
                            'template = ' + json.dumps((ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT').as_posix()),
                            'source = ' + json.dumps((ROOT / 'research/forms/probe_module77.1s').as_posix()),
                            'encoding = "utf-8"', '', '[configuration]', 'modules = ' + json.dumps(modules.as_posix()),
                            '', '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120',
                            'cancel_timeout_s = 15', 'shutdown_timeout_s = 30', 'total_timeout_s = 600', '', ''])
        content = header + profile(mode, wrong=name == 'wrong')
        tomllib.loads(content)
        (folder / 'project.toml').write_text(content, encoding='utf-8', newline='\n')
    text, count = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps(
        (ROOT / 'research/forms/form_launcher77.py').as_posix()), text)
    if count != 1:
        parser.error('stand must have one launcher')
    (output / 'stand.toml').write_text(text, encoding='utf-8', newline='\n')
    for name, cases in [('suite', [('runtime', 'runtime'), ('refusal', 'refusal'), ('repeat', 'runtime')]),
                        ('suite-failure', [('wrong', 'wrong'), ('after-failure', 'runtime')])]:
        manifest = ['schema_version = 1', '', '[suite]', f'id = "posting-rollback-{name}"', '']
        for id_, project in cases:
            manifest += ['[[scenarios]]', f'id = "{id_}"', f'project = "{project}/project.toml"', '']
        (output / (name + '.toml')).write_text('\n'.join(manifest), encoding='utf-8', newline='\n')
    print(json.dumps({'output': str(output), 'stand': str(output / 'stand.toml')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
