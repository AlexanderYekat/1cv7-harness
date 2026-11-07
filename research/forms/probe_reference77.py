"""Native choice probes (task 028), one harness77 run on a verified copy per case.

python research/forms/probe_reference77.py --stand .local/stage21-native/stand.toml
    --work .local/stage28-native/s1 --evidence .artifacts/stage28-choice-20261107-1.json
"""
import argparse
import copy
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_table77 as table

base, scenario = table.base, table.scenario
SCOPE = 'task 028: catalog references through the choice form'
TARGET = 'Harness77 выбор 028'
NEW_PRODUCT = f'''Спр77 = СоздатьОбъект("Справочник.Номенклатура");
Спр77.Новый();
Спр77.Наименование = "{TARGET}";
Спр77.Записать();
'''
SETUP = table.DOCUMENT.replace('Док77 = СоздатьОбъект', NEW_PRODUCT + 'Док77 = СоздатьОбъект', 1)
# NEW_PRODUCT changes Спр77, so restore the original product for the prepared document.
SETUP = SETUP.replace('Док77.Товар = Спр77.ТекущийЭлемент();',
                     f'Спр77.НайтиПоНаименованию("{table.PRODUCT}", 0, 1);\nДок77.Товар = Спр77.ТекущийЭлемент();')
VERIFY = f'''Док77 = СоздатьОбъект("Документ.ГотоваяПродукция");
Если Док77.НайтиДокумент(Объект77) <> 1 Тогда Возврат "not found"; КонецЕсли;
Док77.ВыбратьСтроки();
Если Док77.ПолучитьСтроку() <> 1 Тогда Возврат "no row"; КонецЕсли;
Спр77 = СоздатьОбъект("Справочник.Номенклатура");
Если Спр77.НайтиПоНаименованию("{TARGET}", 0, 1) <> 1 Тогда Возврат "no product"; КонецЕсли;
Если Док77.Товар <> Спр77.ТекущийЭлемент() Тогда Возврат "wrong reference"; КонецЕсли;
Возврат "1|" + СокрЛП(Строка(Док77.Товар)) + "|" + Строка(Док77.Количество) + "|" + Строка(Док77.Сумма);'''


def case(name, steps, setup=SETUP, **fields):
    value = table.existing(name, steps, **fields)
    value['parameters']['fixture_setup'] = setup
    return value


CASES = [
    case('q-select', [
        {'choose': 'Товар', 'text': TARGET}, {'value': 'Товар', 'text': TARGET},
        {'value': 'Стоимость', 'text': '0'}, {'value': 'Сумма', 'text': '0'},
        {'cell': 'Стоимость', 'text': '10'}, {'cell': 'Количество', 'text': '3'},
        {'value': 'Сумма', 'text': '30'}, {'click': 'Записать'}, {'click': 'Закрыть', 'closes': True},
    ], verify=VERIFY, verify_value=f'1|{TARGET}|3|30'),
    case('q-cancel', [
        {'choose': 'Товар', 'cancel': True}, {'value': 'Товар', 'text': table.PRODUCT},
        {'value': 'Сумма', 'text': '10'},
    ]),
    case('q-missing', [{'choose': 'Товар', 'text': 'Harness77 отсутствует 028'}, {'rows': 1}],
         result='failed', issue="step 1 (choose 'Товар'): RuntimeError: choice needs one catalog element, found 0", stopped_at=1),
]

WARNING = 'Harness77 выбор: проверка окна'
WARN_REPLACE = [(table.HEADER, 'Процедура Пересчет(Подбор=0)\n'
                 f'    Предупреждение("{WARNING}");\n\tЕсли Товар.Выбран() = 1 Тогда')]
CASES += [
    case('q-new', [{'add_row': True}, {'choose': 'Товар', 'text': TARGET},
                   {'value': 'Товар', 'text': TARGET}, {'value': 'Товар', 'row': 2, 'text': TARGET},
                   {'value': 'Товар', 'row': 1, 'text': table.PRODUCT},
                   {'value': 'Количество', 'text': '1'}, {'rows': 2}]),
    case('q-cancel-new', [{'add_row': True}, {'choose': 'Товар', 'cancel': True},
                          {'value': 'Товар', 'text': ''}, {'value': 'Товар', 'row': 2, 'text': ''}, {'rows': 2}]),
    case('q-repeat', [{'choose': 'Товар', 'text': TARGET}, {'choose': 'Товар', 'text': table.PRODUCT},
                      {'value': 'Товар', 'text': table.PRODUCT}]),
    case('q-duplicate', [{'choose': 'Товар', 'text': TARGET}, {'rows': 1}],
         setup=SETUP.replace('Док77 = СоздатьОбъект', NEW_PRODUCT + 'Док77 = СоздатьОбъект', 1),
         result='failed', issue="step 1 (choose 'Товар'): RuntimeError: choice needs one catalog element, found 2", stopped_at=1),
    case('q-dialog', [{'choose': 'Товар', 'text': TARGET}, {'dialog': WARNING, 'button': 'ОК'},
                      {'value': 'Товар', 'text': TARGET}, {'value': 'Сумма', 'text': '0'}], replace=WARN_REPLACE),
    case('q-unexpected', [{'choose': 'Товар', 'text': TARGET}, {'rows': 1}], replace=WARN_REPLACE,
         result='failed', issue="step 1 (choose 'Товар'): an unexpected modal window", stopped_at=1),
    table.production('q-empty', [{'choose': 'Товар', 'text': TARGET}, {'rows': 0}],
                     result='failed', issue="step 1 (choose 'Товар'): the table has no row", stopped_at=1),
    case('q-number', [{'choose': 'Количество', 'text': TARGET}], blocked='choose needs a column of a named catalog reference'),
    case('q-invalid', [{'choose': 'Товар', 'text': TARGET, 'cancel': True}], blocked='either non-empty text or cancel = true'),
    case('q-unexpected-choice', [{'choose': 'Товар', 'cancel': True}, {'key': 'F4'}, {'rows': 1}],
         result='failed', issue="step 2 (key 'F4'): an unexpected nested form opened", stopped_at=2),
    case('q-unexpected-insert', [{'add_row': True}, {'rows': 2}],
         result='failed', issue="step 1 (add_row): an unexpected nested form opened", stopped_at=1),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stand', required=True, type=Path)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--output-root', type=Path, default=base.ROOT / '.artifacts/runs')
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    args.baselines = None
    if os.path.lexists(args.evidence):
        parser.error('evidence already exists')
    if set(args.case) - {c['id'] for c in CASES}:
        parser.error('unknown case')
    cases = [copy.deepcopy(c) for c in CASES if not args.case or c['id'] in args.case]
    return table.dry_run(cases, args) if args.dry_run else base.run_series(
        cases, args, SCOPE, prepare_case=table.prepare, judge_case=scenario.judge)


if __name__ == '__main__':
    raise SystemExit(main())
