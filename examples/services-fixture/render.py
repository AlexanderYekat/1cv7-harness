"""Generate the Services fixture and persisted reader from services.toml."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'document-fixture'))
from render_fixture import (catalog, document_header, document_reader, document_rows, finish_setup,
                            parties, render_cli, validate_fixture)

KIND = 'ОказаниеУслуг'


def setup(fixture):
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
    lines += document_header(fixture, KIND, fields=(
        ('ТипУслуги', fixture['service_type']), ('ВариантРасчетаНалогов', 'Налоги77.ТекущийЭлемент()')))
    lines += document_rows(fixture['rows'], 'Услуга', 'Услуга77')
    return finish_setup(lines)


def reader(fixture, fields):
    return document_reader(fixture, fields, kind=KIND, item='service', column='Услуга', label='Services')


if __name__ == '__main__':
    render_cli(HERE / 'services.toml', setup, reader)
