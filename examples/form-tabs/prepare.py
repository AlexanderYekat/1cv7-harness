"""Generate tasks 046–050 profiles using the accepted 043 fixture, without starting 1C."""
import argparse
import importlib.util
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mixed043', ROOT / 'examples/journal-children-mixed/prepare.py')
mixed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mixed)
CASES = ('success', 'second', 'missing', 'wrong-rows', 'no-copy')
EDIT_CASES = ('save', 'cancel')
APPEND_CASES = (*EDIT_CASES, 'wrong-catalog')
INVOICE_ROWS = ('1:50:50:50:0:0;', '1:30:30:30:0:0;', '2:30:60:60:0:0;')


def case_scenario(name):
    text = mixed.case_scenario('invoice-near' if name == 'second' else 'invoice-far')
    marker = ', browser_visible = false }'
    assert text.count(marker) == 1
    text = text.replace(marker, ', browser_visible = false, browse = true }')
    tail = '''    { tab = "Табличная часть", browser_visible = true },
    { rows = 1 },
    { value = "Количество", row = 1, text = "1" },
    { value = "Цена", row = 1, text = "50" },
    { value = "Сумма", row = 1, text = "50" },
    { value = "Всего", row = 1, text = "50" },
    { value = "НДС", row = 1, text = "0" },
    { value = "НП", row = 1, text = "0" },
    { total = "Сумма", text = "50" },
    { tab = "Шапка", browser_visible = false },
    { value = "Комментарий", text = "Harness77 подчиненный 043" },
'''
    if name == 'missing':
        tail = tail.replace('tab = "Табличная часть"', 'tab = "Несуществующая вкладка 046"', 1)
    if name == 'wrong-rows':
        tail = tail.replace('{ rows = 1 }', '{ rows = 2 }')
    return text.replace('\n]\n', '\n' + tail + ']\n')


def extra_rows_fixture(text, row_count):
    marker = '        Фактура77.Записать();'
    if text.count(marker) != 1:
        raise ValueError('expected one invoice write in fixture setup')
    row = '''        Если Номер77 = 2 Тогда
            Фактура77.НоваяСтрока();
            Фактура77.НазначитьТип("Товар", "Справочник.Номенклатура");
            Фактура77.Товар = Спр77.ТекущийЭлемент();
            Фактура77.Количество = 1; Фактура77.Цена = 30;
            Фактура77.Сумма = 30; Фактура77.Всего = 30;
'''
    if row_count == 3:
        row += '''            Фактура77.НоваяСтрока();
            Фактура77.НазначитьТип("Товар", "Справочник.Номенклатура");
            Фактура77.Товар = Спр77.ТекущийЭлемент();
            Фактура77.Количество = 2; Фактура77.Цена = 30;
            Фактура77.Сумма = 60; Фактура77.Всего = 60;
'''
    return text.replace(marker, row + '        КонецЕсли;\n' + marker)


def invoice_fixture(row_count=1):
    text = mixed.case_scenario('invoice-far')
    baseline = mixed.state()
    if row_count > 1:
        text = extra_rows_fixture(text, row_count)
        original = baseline
        rows = ''.join(INVOICE_ROWS[:row_count])
        baseline = baseline.replace(f'|1|{INVOICE_ROWS[0]}', f'|{row_count}|{rows}', 1)
        text = text.replace(json.dumps(original, ensure_ascii=False), json.dumps(baseline, ensure_ascii=False))
    return text, baseline


def expect_edit(text, final):
    expected = json.dumps(final, ensure_ascii=False)
    text = text.replace(
        ', browser_visible = false }',
        ', browser_visible = false, edit = true, expected_after = ' + expected + ' }')
    return text[:text.rindex('expect_value = ')] + 'expect_value = ' + expected + '\n'


def edit_scenario(name, *, second_row=False):
    text, baseline = invoice_fixture(2 if second_row else 1)
    row, price, quantity, amount, total, old_total = 1, 50, 2, 100, 100, 50
    row_check = ''
    first_row = ''
    if second_row:
        row, price, quantity, amount, total, old_total = 2, 30, 3, 90, 140, 80
        row_check = ', row = 2'
        first_row = '''    { value = "Количество", row = 1, text = "1" },
    { value = "Цена", row = 1, text = "50" },
    { value = "Сумма", row = 1, text = "50" },
    { value = "Всего", row = 1, text = "50" },
'''
    final = baseline
    if name == 'save':
        final = baseline.replace(f'1:{price}:{price}:{price}:0:0;', f'{quantity}:{price}:{amount}:{amount}:0:0;', 1)
    text = expect_edit(text, final)
    cursor = 1 if name == 'wrong-row' else row
    initial_total = f'    {{ total = "Сумма", text = "{old_total}" }},\n' if second_row else ''
    tail = f'''    {{ tab = "Табличная часть", browser_visible = true }},
    {{ rows = {row} }},
{first_row}    {{ value = "Количество", row = {row}, text = "1" }},
    {{ value = "Сумма", row = {row}, text = "{price}" }},
{initial_total}    {{ row = {cursor} }},
    {{ cell = "Количество", text = "{quantity}"{row_check} }},
{first_row}    {{ value = "Количество", row = {row}, text = "{quantity}" }},
    {{ value = "Цена", row = {row}, text = "{price}" }},
    {{ value = "Сумма", row = {row}, text = "{amount}" }},
    {{ value = "Всего", row = {row}, text = "{amount}" }},
    {{ total = "Сумма", text = "{total}" }},
    {{ tab = "Шапка", browser_visible = false }},
'''
    if name == 'save':
        tail += '''    { click = "КнопкаЗаписать" },
    { close_form = true, closes = true },
'''
    else:
        tail += '''    { close_form = true },
    { dialog = "Сохранить Документ?", button = "Нет", closes = true },
'''
        quantity, amount, total = 1, price, old_total
    tail += f'''    {{ reopen = true }},
    {{ tab = "Табличная часть", browser_visible = true }},
    {{ rows = {row} }},
{first_row}    {{ value = "Количество", row = {row}, text = "{quantity}" }},
    {{ value = "Сумма", row = {row}, text = "{amount}" }},
    {{ value = "Всего", row = {row}, text = "{amount}" }},
    {{ total = "Сумма", text = "{total}" }},
    {{ tab = "Шапка", browser_visible = false }},
'''
    if name == 'wrong-row':
        text = text.replace('command = "result"\nexpect = "passed"', 'command = "result"\nexpect = "failed"')
    return text.replace('\n]\n', '\n' + tail + ']\n')


def append_scenario(name):
    text, baseline = invoice_fixture(2)
    final = baseline
    if name == 'save':
        final = baseline.replace('|2|' + ''.join(INVOICE_ROWS[:2]), '|3|' + ''.join(INVOICE_ROWS), 1)
    text = expect_edit(text, final)
    original_checks = '''    { value = "Количество", row = 1, text = "1" },
    { value = "Цена", row = 1, text = "50" },
    { value = "Сумма", row = 1, text = "50" },
    { value = "Количество", row = 2, text = "1" },
    { value = "Цена", row = 2, text = "30" },
    { value = "Сумма", row = 2, text = "30" },
'''
    new_checks = '''    { value = "Товар", row = 3, text = "Harness77 продукция 043" },
    { value = "Количество", row = 3, text = "2" },
    { value = "Цена", row = 3, text = "30" },
    { value = "Сумма", row = 3, text = "60" },
    { value = "Всего", row = 3, text = "60" },
'''
    caption = 'Нет такого типа 049' if name == 'wrong-catalog' else 'Номенклатура'
    tail = f'''    {{ tab = "Табличная часть", browser_visible = true }},
    {{ rows = 2 }},
{original_checks}    {{ total = "Сумма", text = "80" }},
    {{ row = 2 }},
    {{ add_row = true }},
    {{ choose = "Товар", text = "Harness77 продукция 043", catalog = "Номенклатура", catalog_caption = "{caption}" }},
    {{ cell = "Количество", row = 3, text = "2" }},
    {{ cell = "Цена", row = 3, text = "30" }},
    {{ rows = 3 }},
{original_checks}{new_checks}    {{ total = "Сумма", text = "140" }},
    {{ tab = "Шапка", browser_visible = false }},
'''
    if name == 'save':
        tail += '''    { click = "КнопкаЗаписать" },
    { close_form = true, closes = true },
'''
        count, readback, total = 3, new_checks, 140
    else:
        tail += '''    { close_form = true },
    { dialog = "Сохранить Документ?", button = "Нет", closes = true },
'''
        count, readback, total = 2, '', 80
    tail += f'''    {{ reopen = true }},
    {{ tab = "Табличная часть", browser_visible = true }},
    {{ rows = {count} }},
{original_checks}{readback}    {{ total = "Сумма", text = "{total}" }},
    {{ tab = "Шапка", browser_visible = false }},
'''
    if name == 'wrong-catalog':
        text = text.replace('command = "result"\nexpect = "passed"', 'command = "result"\nexpect = "failed"')
    return text.replace('\n]\n', '\n' + tail + ']\n')


def invoice_row_checks(row, quantity, price):
    fields = (('Количество', quantity), ('Цена', price), ('Сумма', quantity * price), ('Всего', quantity * price))
    return ''.join(f'    {{ value = "{field}", row = {row}, text = "{value}" }},\n' for field, value in fields)


def delete_scenario(name):
    text, baseline = invoice_fixture(3)
    final = baseline
    if name == 'save':
        final = baseline.replace('|3|' + ''.join(INVOICE_ROWS), '|2|' + INVOICE_ROWS[0] + INVOICE_ROWS[2], 1)
    text = expect_edit(text, final)
    first_row = invoice_row_checks(1, 1, 50)
    original = first_row + invoice_row_checks(2, 1, 30) + invoice_row_checks(3, 2, 30)
    remaining = first_row + invoice_row_checks(2, 2, 30)
    cursor = 1 if name == 'wrong-row' else 2
    tail = f'''    {{ tab = "Табличная часть", browser_visible = true }},
    {{ rows = 3 }},
{original}    {{ total = "Сумма", text = "140" }},
    {{ row = {cursor} }},
    {{ delete_row = true, row = 2 }},
    {{ rows = 2 }},
{remaining}    {{ total = "Сумма", text = "110" }},
    {{ tab = "Шапка", browser_visible = false }},
'''
    if name == 'save':
        tail += '''    { click = "КнопкаЗаписать" },
    { close_form = true, closes = true },
'''
        count, readback, total = 2, remaining, 110
    else:
        tail += '''    { close_form = true },
    { dialog = "Сохранить Документ?", button = "Нет", closes = true },
'''
        count, readback, total = 3, original, 140
    tail += f'''    {{ reopen = true }},
    {{ tab = "Табличная часть", browser_visible = true }},
    {{ rows = {count} }},
{readback}    {{ total = "Сумма", text = "{total}" }},
    {{ tab = "Шапка", browser_visible = false }},
'''
    if name == 'wrong-row':
        text = text.replace('command = "result"\nexpect = "passed"', 'command = "result"\nexpect = "failed"')
    return text.replace('\n]\n', '\n' + tail + ']\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stand', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--edit', action='store_true', help='generate the save and cancel cases of task 047')
    mode.add_argument('--edit-second-row', action='store_true', help='generate task 048 cases with two invoice rows')
    mode.add_argument('--append-row', action='store_true', help='generate task 049 cases for appending an invoice row')
    mode.add_argument('--delete-middle-row', action='store_true', help='generate task 050 cases for deleting the middle row')
    a = p.parse_args()
    stand_text = a.stand.resolve(strict=True).read_text('utf-8')
    stand = tomllib.loads(stand_text)['stand']
    if not stand['base'].get('copy_path'):
        p.error('stand requires registered copy_path')
    paths = [stand.get('launcher'), *stand.get('paths', {}).values(), stand['base']['path'], stand['base']['copy_path']]
    if any(v and not Path(v).is_absolute() for v in paths):
        p.error('stand paths must be absolute')
    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    edit = a.edit or a.edit_second_row or a.delete_middle_row
    cases = EDIT_CASES if edit else CASES
    if a.edit_second_row or a.delete_middle_row:
        cases += ('wrong-row',)
    if a.append_row:
        cases = APPEND_CASES
    for name in cases:
        folder = output / name
        (folder / 'configuration').mkdir(parents=True)
        header = '\n'.join(['schema_version = 1', '[project]', f'id = "form-tabs-{name}"', '[build]',
            'template = ' + json.dumps((ROOT / '.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT').as_posix()),
            'source = ' + json.dumps((ROOT / 'research/forms/probe_module77.1s').as_posix()), 'encoding = "utf-8"',
            *([] if name == 'no-copy' else ['[configuration]', 'modules = ' + json.dumps((folder / 'configuration').as_posix())]),
            '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120', 'cancel_timeout_s = 15',
            'shutdown_timeout_s = 30', 'total_timeout_s = 600', ''])
        if a.append_row:
            scenario = append_scenario(name)
        elif a.delete_middle_row:
            scenario = delete_scenario(name)
        elif edit:
            scenario = edit_scenario(name, second_row=a.edit_second_row)
        else:
            scenario = case_scenario(name)
        content = header + scenario
        tomllib.loads(content)
        (folder / 'project.toml').write_text(content, 'utf-8', newline='\n')
    import re
    stand_text, n = re.subn(r'(?m)^launcher = .*$', 'launcher = ' + json.dumps((ROOT / 'research/forms/form_launcher77.py').as_posix()), stand_text)
    if n != 1:
        p.error('stand requires one launcher line')
    (output / 'stand.toml').write_text(stand_text, 'utf-8', newline='\n')
    suites = {'suite': EDIT_CASES} if edit else {
        'suite': ['success', 'second', 'repeat'],
        'suite-missing': ['missing', 'after-failure'],
        'suite-rows': ['wrong-rows', 'after-failure'],
    }
    if a.edit_second_row or a.delete_middle_row:
        suites['suite-row-guard'] = ('wrong-row',)
    if a.append_row:
        suites = {'suite': APPEND_CASES}
    for name, ids in suites.items():
        lines = ['schema_version = 1', '[suite]', f'id = "form-tabs-{name}"']
        for id_ in ids:
            case = 'success' if id_ in ('repeat', 'after-failure') else id_
            lines += ['[[scenarios]]', f'id = "{id_}"', f'project = "{case}/project.toml"']
        (output / (name + '.toml')).write_text('\n'.join(lines)+'\n', 'utf-8', newline='\n')
    print(json.dumps(dict(output=str(output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
