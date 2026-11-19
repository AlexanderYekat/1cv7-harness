"""Render one of two qualified 1C 7.7 document fixture recipes."""
import argparse
from datetime import date
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib

from .artifacts import _destination, _input, _unchanged
from .ert_module import ErtError
from .project_init77 import _rename_new, _write
from .report77 import sha256_bytes

DOCUMENTS = {'services': 'ОказаниеУслуг', 'invoice': 'СчетФактура'}
KINDS = tuple(DOCUMENTS)
PREFIX = '.harness77-fixture-'


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


def services_setup(fixture):
    validate_fixture(fixture, 'service', extra=('service_type',))
    if type(fixture['service_type']) is not int or fixture['service_type'] not in (1, 2):
        raise ValueError('fixture.service_type: expected 1 or 2')

    lines = ['// Generated from the Services recipe. Runs in the verified database copy.']
    lines += catalog('Услуга77', 'Номенклатура', fixture['service'], fields=(
        ('ТипНоменклатуры', 'Перечисление.ТипыНоменклатуры.Услуга'),))
    lines += parties(fixture)
    lines += catalog('НДС77', 'СтавкиНДС', 'Harness77 ноль 110', fields=(('Ставка', '0'),))
    lines += catalog('НП77', 'СтавкиНП', 'Harness77 ноль 110', fields=(('Ставка', '0'),))
    lines += catalog('Налоги77', 'ВариантыРасчетаНалогов', 'Harness77 без налогов 110', fields=(
        ('СтавкаНДС', 'НДС77.ТекущийЭлемент()'), ('СтавкаНП', 'НП77.ТекущийЭлемент()'),
        ('СуммаВключаетНДС', '0'), ('СуммаВключаетНП', '0')))
    lines += document_header(fixture, 'ОказаниеУслуг', fields=(
        ('ТипУслуги', fixture['service_type']), ('ВариантРасчетаНалогов', 'Налоги77.ТекущийЭлемент()')))
    lines += document_rows(fixture['rows'], 'Услуга', 'Услуга77')
    return finish_setup(lines)


def invoice_setup(fixture):
    validate_fixture(fixture, 'product')
    lines = ['// Generated from the Invoice recipe. Runs in the verified database copy.']
    lines += catalog('Товар77', 'Номенклатура', fixture['product'])
    lines += parties(fixture)
    lines += document_header(fixture, 'СчетФактура')
    lines += document_rows(fixture['rows'], 'Товар', 'Товар77', assign_catalog_type=True)
    return finish_setup(lines)


def render(kind, recipe):
    """Return both bodies as UTF-8 bytes; verify 1C can encode them in CP1251."""
    if kind not in KINDS:
        raise ValueError('kind: expected services or invoice')
    data = table(tomllib.loads(recipe.decode('utf-8-sig')), ('fixture', 'reader'), 'recipe')
    fixture, fields = data['fixture'], data['reader']
    if kind == 'services':
        setup = services_setup(fixture)
        reader = document_reader(fixture, fields, kind='ОказаниеУслуг', item='service',
                                 column='Услуга', label='Services')
    else:
        setup = invoice_setup(fixture)
        reader = document_reader(fixture, fields, kind='СчетФактура', item='product',
                                 column='Товар', label='Invoice')
    setup.encode('cp1251')
    reader.encode('cp1251')
    return {'fixture.1s': setup.encode('utf-8'), 'reader.1s': reader.encode('utf-8')}


def read_recipe(kind, recipe=None):
    """Load a recipe, returning its bytes, input path (if external) and evidence."""
    if kind not in KINDS:
        raise ValueError('kind: expected services or invoice')
    if recipe is None:
        name = kind + '.toml'
        source = {'source': 'bundled', 'name': name}
        raw = files('harness77').joinpath('fixture_recipes', name).read_bytes()
        path = None
    else:
        path, raw = _input(recipe)
        source = {'source': 'file', 'path': str(path)}
    return raw, path, {**source, 'sha256': sha256_bytes(raw), 'size_bytes': len(raw)}


def render_to_directory(*, kind, output, recipe=None):
    destination = _destination(output)
    raw, path, source = read_recipe(kind, recipe)
    bodies = render(kind, raw)
    stage = Path(tempfile.mkdtemp(prefix=PREFIX, dir=destination.parent))
    published = False
    try:
        for name, payload in bodies.items():
            _write(stage / name, payload)
            if (stage / name).read_bytes() != payload:
                raise OSError('Generated file differs after readback: ' + name)
        if path is not None:
            _unchanged([(path, raw)])
        _rename_new(stage, destination)
        published = True
    finally:
        if not published:
            if not stage.is_symlink() and stage.resolve().parent == destination.parent:
                for name in bodies:
                    (stage / name).unlink(missing_ok=True)
                stage.rmdir()
    return {'status': 'created', 'exit_code': 0, 'platform_checked': False, 'launch_performed': False,
            'kind': kind, 'directory': str(destination),
            'recipe': source,
            'files': {name: {'path': str(destination / name), 'sha256': sha256_bytes(payload),
                             'size_bytes': len(payload)} for name, payload in bodies.items()},
            'reason': None}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='harness77 fixture-render', allow_abbrev=False, description=__doc__)
    parser.add_argument('--kind', choices=KINDS, required=True)
    parser.add_argument('--recipe', type=Path, help='UTF-8 TOML, defaults to the bundled recipe for --kind')
    parser.add_argument('--output', type=Path, required=True, help='new directory for fixture.1s and reader.1s')
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    args = parser.parse_args(argv)
    try:
        report = render_to_directory(kind=args.kind, recipe=args.recipe, output=args.output)
    except (OSError, ValueError, ErtError) as error:
        report = {'status': 'blocked', 'exit_code': 2, 'platform_checked': False, 'launch_performed': False,
                  'kind': args.kind, 'reason': f'{type(error).__name__}: {error}'}
    if args.format == 'json':
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif report['status'] == 'created':
        print('fixture-render: созданы fixture.1s и reader.1s в ' + report['directory'])
    else:
        print('fixture-render: blocked: ' + report['reason'], file=sys.stderr)
    return report['exit_code']
