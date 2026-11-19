"""Qualify the TOML recipe for Services on the Windows 1C 7.7 stand."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'document-fixture'))
from cycle import change_on_save, run


def regression_source(original):
    return change_on_save(original, '\tОперация.Содержание = "Оказание услуг";', 'ТипУслуги = 2;')


if __name__ == '__main__':
    run(example=HERE, project_id='services110', kind='ОказаниеУслуг', recipe='services.toml',
        steps_file=HERE.parent / 'services-project/steps.json', expected_file=HERE / 'expected.json',
        mutate=regression_source, regression_value=('service_type', 2))
