"""Generate the direct Invoice fixture and persisted reader from invoice.toml."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'document-fixture'))
from render_fixture import (catalog, document_header, document_reader, document_rows, finish_setup,
                            parties, render_cli, validate_fixture)

KIND = 'СчетФактура'


def setup(fixture):
    validate_fixture(fixture, 'product')
    lines = ['// Generated from the Invoice recipe. Runs in the verified database copy.']
    lines += catalog('Товар77', 'Номенклатура', fixture['product'])
    lines += parties(fixture)
    lines += document_header(fixture, KIND)
    lines += document_rows(fixture['rows'], 'Товар', 'Товар77', assign_catalog_type=True)
    return finish_setup(lines)


def reader(fixture, fields):
    return document_reader(fixture, fields, kind=KIND, item='product', column='Товар', label='Invoice')


if __name__ == '__main__':
    render_cli(HERE / 'invoice.toml', setup, reader)
