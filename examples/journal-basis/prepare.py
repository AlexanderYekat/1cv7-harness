"""Prepare task 040 existing journal document profiles and suites; does not start 1C."""
import argparse
import json
from pathlib import Path
import re
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATE = ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT'
SOURCE = ROOT / 'research/forms/probe_module77.1s'


def state(created=False, posted=1):
    parts = [f'0|0|Harness77 журнал 040 {n}|2|1:10:10;2:20:40;|1|0||1#' for n in range(1, 4)]
    if created:
        entries = '50.1>62.1:0:50;' if posted else ''
        parts.append(f'{posted}|0|Harness77 основание 040|50|0|0|1|1|1|{1 if posted else 0}|{entries}|1#')
    return str(int(created)) + '|0|' + str(int(created)) + '|' + ''.join(parts)


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
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scenario = (HERE / 'scenario.toml').read_text(encoding='utf-8')
    for name in ('success', 'wrong', 'wrong-limit', 'cancel', 'cancel-kind', 'wrong-kind', 'no-copy'):
        folder = output / name
        modules = folder / 'configuration'
        modules.mkdir(parents=True)
        content = scenario
        final = state(created=True)
        if name == 'wrong':
            final = final.replace(':0:50', ':0:999')
        if name == 'wrong-limit':
            content = content.replace('limit = 100', 'limit = 1')
            final = state()
        if name == 'wrong-kind':
            content = content.replace('journal_basis = "Прих.касс.орд. (Приходный кассовый ордер)"', 'journal_basis = "Harness77 отсутствующий вид 040"')
            final = state()
        if name == 'cancel-kind':
            content = content.replace('link = "ДокументОснование",', 'link = "ДокументОснование", cancel = true,')
            start = content.index('    { value = "Сумма"')
            content = content[:start] + content[content.index('\n]', start):]
            final = state()
        if name == 'cancel':
            start = content.index('    { click = "Записать"')
            end = content.index('\n]', start)
            content = content[:start] + '\n'.join([
                '    { close_form = true },',
                '    { dialog = "Сохранить Документ?", button = "Нет", closes = true },',
            ]) + content[end:]
            final = state()
        content = content[:content.rindex('expect_value = ')] + 'expect_value = ' + json.dumps(final, ensure_ascii=False) + '\n'
        header = '\n'.join(['schema_version = 1', '', '[project]', f'id = "journal-basis-{name}"', '', '[build]',
                            f'template = {json.dumps(TEMPLATE.as_posix())}', f'source = {json.dumps(SOURCE.as_posix())}',
                            'encoding = "utf-8"', '', '[configuration]', f'modules = {json.dumps(modules.as_posix())}',
                            '', '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120',
                            'cancel_timeout_s = 15', 'shutdown_timeout_s = 30', 'total_timeout_s = 600', '', ''])
        if name == 'no-copy':
            header = header.replace('[configuration]\n' + f'modules = {json.dumps(modules.as_posix())}\n\n', '')
        tomllib.loads(header + content)
        (folder / 'project.toml').write_text(header + content, encoding='utf-8', newline='\n')
    text, count = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps(
        (ROOT / 'research/forms/form_launcher77.py').as_posix()), text)
    if count != 1:
        parser.error('stand must have one launcher line')
    (output / 'stand.toml').write_text(text, encoding='utf-8', newline='\n')
    for name, cases in [('suite', [('success', 'success'), ('repeat', 'success'), ('cancel-kind', 'cancel-kind'), ('cancel', 'cancel')]),
                        ('suite-failure', [('wrong', 'wrong'), ('after-failure', 'success')]),
                        ('suite-kind-failure', [('wrong-kind', 'wrong-kind'), ('after-failure', 'success')]),
                        ('suite-limit-failure', [('wrong-limit', 'wrong-limit'), ('after-failure', 'success')])]:
        manifest = ['schema_version = 1', '', '[suite]', f'id = "journal-basis-{name}"', '']
        for id_, project in cases:
            manifest += ['[[scenarios]]', f'id = "{id_}"', f'project = "{project}/project.toml"', '']
        (output / (name + '.toml')).write_text('\n'.join(manifest), encoding='utf-8', newline='\n')
    print(json.dumps({'output': str(output), 'stand': str(output / 'stand.toml'),
                      'suite': str(output / 'suite.toml')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
