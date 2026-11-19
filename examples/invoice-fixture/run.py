"""Qualify the TOML recipe for Invoice on the Windows 1C 7.7 stand."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'document-fixture'))
from cycle import change_on_save, run


def regression_source(original):
    return change_on_save(original, '\tОперация.Содержание = "Сч.-факт. покупателю: "+Контрагент;',
                          'Комментарий = "Harness77 неверный комментарий 111";')


if __name__ == '__main__':
    invoice = HERE.parent / 'invoice-project'
    run(example=HERE, project_id='invoice111', kind='СчетФактура', recipe='invoice.toml',
        steps_file=invoice / 'direct-steps.json', expected_file=invoice / 'expected.json',
        mutate=regression_source, regression_value=('comment_ok', 0))
