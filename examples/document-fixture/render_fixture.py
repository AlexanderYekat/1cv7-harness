"""Shared 1C 7.7 generation for the Services and Invoice examples."""
import argparse
from datetime import date
import re
from pathlib import Path
import tomllib


def literal(value):
    return '"' + value.replace('"', '""') + '"'


def table(value, keys, label):
    if not isinstance(value, dict) or value.keys() != set(keys):
        raise ValueError(f'{label}: expected {", ".join(keys)}')
    return value


def catalog(alias, kind, name, *, code=False, owner=None, fields=()):
    result = [f'{alias} = СоздатьОбъект("Справочник.{kind}");']
    if owner is not None:
        result.append(f'{alias}.ИспользоватьВладельца({owner}.ТекущийЭлемент());')
    result.append(f'{alias}.Новый();')
    if code:
        result.append(f'{alias}.УстановитьНовыйКод("77");')
    result.append(f'{alias}.Наименование = {literal(name)};')
    result.extend(f'{alias}.{field} = {value};' for field, value in fields)
    result.append(f'{alias}.Записать();')
    return result


def validate_fixture(fixture, item, extra=()):
    names = (item, 'customer', 'contract', 'department', 'comment')
    table(fixture, (*names, 'date', 'rows', *extra), 'fixture')
    for key in names:
        value = fixture[key]
        if not isinstance(value, str) or not value.strip() or not value.isprintable():
            raise ValueError(f'fixture.{key}: expected non-empty single-line text')
    if type(fixture['date']) is not date:
        raise ValueError('fixture.date: expected a TOML date')
    rows = fixture['rows']
    if not isinstance(rows, list) or not rows:
        raise ValueError('fixture.rows: expected a non-empty array of rows')
    for index, row in enumerate(rows):
        label = f'fixture.rows[{index}]'
        table(row, ('quantity', 'price'), label)
        if (type(row['quantity']) is not int or row['quantity'] <= 0
                or type(row['price']) is not int or row['price'] < 0):
            raise ValueError(f'{label}: expected positive integer quantity and nonnegative integer price')


def parties(fixture):
    lines = catalog('Контрагент77', 'Контрагенты', fixture['customer'], code=True, fields=(
        ('ПолнНаименование', literal(fixture['customer'])),))
    lines += catalog('Договор77', 'Договоры', fixture['contract'], code=True, owner='Контрагент77',
                     fields=(('ОплатаДоговора', '1'),))
    lines += catalog('Отдел77', 'Подразделения', fixture['department'], code=True)
    return lines


def document_header(fixture, kind, fields=()):
    return [f'Док77 = СоздатьОбъект("Документ.{kind}");', 'Док77.Новый();',
            f"Док77.ДатаДок = '{fixture['date']:%d.%m.%Y}';",
            'Док77.Контрагент = Контрагент77.ТекущийЭлемент();',
            'Док77.Договор = Договор77.ТекущийЭлемент();',
            'Док77.Подразделение2 = Отдел77.ТекущийЭлемент();',
            *(f'Док77.{field} = {value};' for field, value in fields),
            'Док77.ВерсияОбъекта = Константа.НомерРелиза;',
            f"Док77.Комментарий = {literal(fixture['comment'])};"]


def document_rows(rows, column, catalog_alias, *, assign_catalog_type=False):
    lines = []
    for row in rows:
        lines.append('Док77.НоваяСтрока();')
        if assign_catalog_type:
            lines.append(f'Док77.НазначитьТип({literal(column)}, "Справочник.Номенклатура");')
        lines += [f'Док77.{column} = {catalog_alias}.ТекущийЭлемент();',
                  f"Док77.Количество = {row['quantity']};", f"Док77.Цена = {row['price']};",
                  'Док77.Сумма = Док77.Количество * Док77.Цена;', 'Док77.Всего = Док77.Сумма;']
    return lines


def finish_setup(lines):
    return '\n'.join([*lines, 'Док77.Записать();', 'Возврат Док77.ТекущийДокумент();', ''])


def projection(mapping, label):
    if not isinstance(mapping, dict):
        raise ValueError(f'reader.{label}: expected a field mapping')
    for key, field in mapping.items():
        if (not re.fullmatch(r'[a-z][a-z0-9_]*', key) or not isinstance(field, str)
                or not re.fullmatch(r'[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*', field)):
            raise ValueError(f'reader.{label}.{key}: expected a JSON key and a 1C field name')
    return mapping


def json_object(fields):
    """Build a 1C expression from already formatted JSON values."""
    parts = []
    for index, (key, value) in enumerate(fields.items()):
        prefix = ('{' if index == 0 else ',') + f'"{key}":'
        parts.append(f'{literal(prefix)} + {value}')
    return '\n        + '.join(parts) + ' + "}"'


def number(expression):
    return f'СокрЛП(Строка({expression}))'


def decimal_text(expression):
    # Values are numeric 1C fields. Text preserves the previous example's decimal format.
    quote = literal('"')
    return f'{quote} + {number(expression)} + {quote}'


def document_reader(fixture, fields, *, kind, item, column, label):
    table(fields, ('integers', 'totals', 'rows'), 'reader')
    integers, totals, rows = (projection(fields[key], key) for key in ('integers', 'totals', 'rows'))
    fixed_keys = {'kind', 'posted', 'row_count', 'product_links', 'comment_ok', 'rows'}
    if fixed_keys & (integers.keys() | totals.keys()) or integers.keys() & totals.keys() or not rows:
        raise ValueError('reader: duplicate header key or empty rows mapping')
    header = {
        'kind': literal(f'"{kind}"'), 'posted': number('Док77.Проведен()'),
        'row_count': number('Док77.КоличествоСтрок()'), 'product_links': number('Ссылки77'),
        'comment_ok': number('Комментарий77'),
        **{key: number(f'Док77.{field}') for key, field in integers.items()},
        **{key: decimal_text(f'Док77.Итог({literal(field)})') for key, field in totals.items()},
        'rows': '"[" + Строки77 + "]"',
    }
    row = json_object({key: decimal_text(f'Док77.{field}') for key, field in rows.items()})
    return f'''// Generated from the {label} recipe. Open a fresh object by the fixture reference.
Док77 = СоздатьОбъект("Документ.{kind}");
Если Док77.НайтиДокумент(Объект77) <> 1 Тогда Возврат "{{}}"; КонецЕсли;
Спр77 = СоздатьОбъект("Справочник.Номенклатура");
Если Спр77.НайтиПоНаименованию({literal(fixture[item])}, 0, 1) <> 1 Тогда Возврат "{{}}"; КонецЕсли;
Ссылки77 = 1;
Строки77 = "";
Док77.ВыбратьСтроки();
Пока Док77.ПолучитьСтроку() = 1 Цикл
    Если Док77.{column} <> Спр77.ТекущийЭлемент() Тогда Ссылки77 = 0; КонецЕсли;
    Если Строки77 <> "" Тогда Строки77 = Строки77 + ","; КонецЕсли;
    Строки77 = Строки77 + {row};
КонецЦикла;
Комментарий77 = ?(СокрЛП(Док77.Комментарий) = {literal(fixture['comment'])}, 1, 0);
Возврат {json_object(header)};
'''


def render_cli(default_recipe, setup, reader):
    parser = argparse.ArgumentParser(description='Render fixture and reader as 1C 7.7 function bodies.')
    parser.add_argument('--recipe', type=Path, default=default_recipe)
    parser.add_argument('--output', type=Path, required=True, help='new directory for fixture.1s and reader.1s')
    args = parser.parse_args()
    try:
        data = table(tomllib.loads(args.recipe.read_text(encoding='utf-8')), ('fixture', 'reader'), 'recipe')
        bodies = dict(fixture=setup(data['fixture']), reader=reader(data['fixture'], data['reader']))
        for body in bodies.values():
            body.encode('cp1251')  # same encoding required by the native forms adapter
        args.output.mkdir(parents=True, exist_ok=False)
        for name, body in bodies.items():
            (args.output / (name + '.1s')).write_bytes(body.encode('utf-8'))
    except (OSError, ValueError) as error:
        parser.error(str(error))
