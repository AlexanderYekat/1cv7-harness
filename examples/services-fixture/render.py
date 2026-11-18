"""Render the Services example's setup and persisted reader as 1C 7.7 function bodies."""
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


def setup(fixture):
    names = ('service', 'customer', 'contract', 'department', 'comment')
    table(fixture, (*names, 'date', 'service_type', 'rows'), 'fixture')
    for key in names:
        value = fixture[key]
        if not isinstance(value, str) or not value.strip() or not value.isprintable():
            raise ValueError(f'fixture.{key}: expected non-empty single-line text')
    if type(fixture['date']) is not date:
        raise ValueError('fixture.date: expected a TOML date')
    if type(fixture['service_type']) is not int or fixture['service_type'] not in (1, 2):
        raise ValueError('fixture.service_type: expected 1 or 2')
    rows = fixture['rows']
    if not isinstance(rows, list) or not rows:
        raise ValueError('fixture.rows: expected a non-empty array of rows')
    for index, row in enumerate(rows):
        label = f'fixture.rows[{index}]'
        table(row, ('quantity', 'price'), label)
        if (type(row['quantity']) is not int or row['quantity'] <= 0
                or type(row['price']) is not int or row['price'] < 0):
            raise ValueError(f'{label}: expected positive integer quantity and nonnegative integer price')

    lines = ['// Generated from the Services recipe. Runs in the verified database copy.']
    lines += catalog('Услуга77', 'Номенклатура', fixture['service'], fields=(
        ('ТипНоменклатуры', 'Перечисление.ТипыНоменклатуры.Услуга'),))
    lines += catalog('Контрагент77', 'Контрагенты', fixture['customer'], code=True, fields=(
        ('ПолнНаименование', literal(fixture['customer'])),))
    lines += catalog('Договор77', 'Договоры', fixture['contract'], code=True, owner='Контрагент77',
                     fields=(('ОплатаДоговора', '1'),))
    lines += catalog('Отдел77', 'Подразделения', fixture['department'], code=True)
    lines += catalog('НДС77', 'СтавкиНДС', 'Harness77 ноль 110', fields=(('Ставка', '0'),))
    lines += catalog('НП77', 'СтавкиНП', 'Harness77 ноль 110', fields=(('Ставка', '0'),))
    lines += catalog('Налоги77', 'ВариантыРасчетаНалогов', 'Harness77 без налогов 110', fields=(
        ('СтавкаНДС', 'НДС77.ТекущийЭлемент()'), ('СтавкаНП', 'НП77.ТекущийЭлемент()'),
        ('СуммаВключаетНДС', '0'), ('СуммаВключаетНП', '0')))
    lines += ['Док77 = СоздатьОбъект("Документ.ОказаниеУслуг");', 'Док77.Новый();',
              f"Док77.ДатаДок = '{fixture['date']:%d.%m.%Y}';",
              'Док77.Контрагент = Контрагент77.ТекущийЭлемент();',
              'Док77.Договор = Договор77.ТекущийЭлемент();',
              'Док77.Подразделение2 = Отдел77.ТекущийЭлемент();',
              f"Док77.ТипУслуги = {fixture['service_type']};",
              'Док77.ВариантРасчетаНалогов = Налоги77.ТекущийЭлемент();',
              'Док77.ВерсияОбъекта = Константа.НомерРелиза;',
              f"Док77.Комментарий = {literal(fixture['comment'])};"]
    for row in rows:
        lines += ['Док77.НоваяСтрока();', 'Док77.Услуга = Услуга77.ТекущийЭлемент();',
                  f"Док77.Количество = {row['quantity']};", f"Док77.Цена = {row['price']};",
                  'Док77.Сумма = Док77.Количество * Док77.Цена;', 'Док77.Всего = Док77.Сумма;']
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


def reader(fixture, fields):
    table(fields, ('integers', 'totals', 'rows'), 'reader')
    integers, totals, rows = (projection(fields[key], key) for key in ('integers', 'totals', 'rows'))
    fixed_keys = {'kind', 'posted', 'row_count', 'product_links', 'comment_ok', 'rows'}
    if fixed_keys & (integers.keys() | totals.keys()) or integers.keys() & totals.keys() or not rows:
        raise ValueError('reader: duplicate header key or empty rows mapping')
    header = {
        'kind': literal('"ОказаниеУслуг"'), 'posted': number('Док77.Проведен()'),
        'row_count': number('Док77.КоличествоСтрок()'), 'product_links': number('Ссылки77'),
        'comment_ok': number('Комментарий77'),
        **{key: number(f'Док77.{field}') for key, field in integers.items()},
        **{key: decimal_text(f'Док77.Итог({literal(field)})') for key, field in totals.items()},
        'rows': '"[" + Строки77 + "]"',
    }
    row = json_object({key: decimal_text(f'Док77.{field}') for key, field in rows.items()})
    return f'''// Generated from the Services recipe. Open a fresh object by the fixture reference.
Док77 = СоздатьОбъект("Документ.ОказаниеУслуг");
Если Док77.НайтиДокумент(Объект77) <> 1 Тогда Возврат "{{}}"; КонецЕсли;
Спр77 = СоздатьОбъект("Справочник.Номенклатура");
Если Спр77.НайтиПоНаименованию({literal(fixture['service'])}, 0, 1) <> 1 Тогда Возврат "{{}}"; КонецЕсли;
Ссылки77 = 1;
Строки77 = "";
Док77.ВыбратьСтроки();
Пока Док77.ПолучитьСтроку() = 1 Цикл
    Если Док77.Услуга <> Спр77.ТекущийЭлемент() Тогда Ссылки77 = 0; КонецЕсли;
    Если Строки77 <> "" Тогда Строки77 = Строки77 + ","; КонецЕсли;
    Строки77 = Строки77 + {row};
КонецЦикла;
Комментарий77 = ?(СокрЛП(Док77.Комментарий) = {literal(fixture['comment'])}, 1, 0);
Возврат {json_object(header)};
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', type=Path, default=Path(__file__).with_name('services.toml'))
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


if __name__ == '__main__':
    main()
