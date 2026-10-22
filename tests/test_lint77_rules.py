"""Stage-5 rules L7708-L7711: negative, positive and boundary cases.

Expected outcomes follow the native probes on 1C 7.7.027 (docs/tasks/005-kudir-rules-acceptance.md).
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness77 import ert_module as ert
from harness77 import lint77

from test_ert_dialog import DIALOG, make_ert

NEW_RULES = ('L7708', 'L7709', 'L7710', 'L7711')


def analyze(text, *, dialog=None, globals_text=None, strict=False):
    source = lint77.Source('test.1s', '', text, dialog=frozenset(dialog) if dialog is not None else None)
    external = [lint77.Source('global.1s', '', globals_text, True)] if globals_text else []
    return lint77.analyze([source], external, strict=strict)


def found(text, rule, **kwargs):
    return [(d['line'], d['severity']) for d in analyze(text, **kwargs)['diagnostics'] if d['rule'] == rule]


def procedure(*lines):
    return 'Процедура П()\n' + '\n'.join(lines) + '\nКонецПроцедуры\n'


class ReservedNameTests(unittest.TestCase):
    """L7708: 7.7 rejected all 162 reserved names as parameter, Перем and assignment target."""

    def test_reserved_names_in_every_declaring_position(self):
        cases = {
            'Процедура П(Знач Строка)\nКонецПроцедуры': 1,
            'Процедура П(Число) Далее\nПроцедура П(Число)\nКонецПроцедуры': 1,
            'Перем Дата;\nПроцедура П()\nКонецПроцедуры': 1,
            procedure('Перем А, Мин;'): 2,
            procedure('Мин = 1;'): 2,
            procedure('Для Макс = 1 По 2 Цикл КонецЦикла;'): 2,
            procedure('String = 1;'): 2,
            procedure('СТРОКА = 1;'): 2,
            procedure('Если 1 = 1 Тогда Строка = 2; КонецЕсли;'): 2,
        }
        for text, line in cases.items():
            with self.subTest(text=text):
                self.assertIn((line, 'error'), found(text, 'L7708'))

    def test_every_reserved_name_in_every_surveyed_position(self):
        # b-survey: 7.7 rejected each of the 162 names as parameter, assignment target and Перем,
        # including keywords (Не = 1;, Возврат = 1;, Перем Экспорт;, Знач Знач).
        from harness77.catalog77 import load_packaged
        positions = {'параметр': ('Процедура П(Знач {})\nКонецПроцедуры', 1),
                     'присваивание': ('Процедура П()\n{} = 1;\nКонецПроцедуры', 2),
                     'Перем': ('Перем {};\nПроцедура П()\nКонецПроцедуры', 1),
                     'счётчик': ('Процедура П()\nДля {} = 1 По 2 Цикл КонецЦикла;\nКонецПроцедуры', 2)}
        names = load_packaged()['reserved']['names']
        self.assertEqual(len(names), 162)
        for position, (template, line) in positions.items():
            missed = [name for name in names if (line, 'error') not in found(template.format(name), 'L7708')]
            self.assertEqual(missed, [], position)

    def test_export_after_a_name_is_a_flag_not_a_variable(self):
        self.assertEqual(found('Перем А Экспорт, Б[2] Экспорт;\nПроцедура П() Экспорт\nКонецПроцедуры', 'L7708'), [])

    def test_forward_declaration_and_definition_both_reported(self):
        text = 'Процедура П(Знач Строка) Далее\nПроцедура П(Знач Строка)\nКонецПроцедуры'
        self.assertEqual(found(text, 'L7708'), [(1, 'error'), (2, 'error')])

    def test_accepted_names_and_non_declarations(self):
        for text in (procedure('Сообщить = 1;'),                 # 7.7 accepted it
                     procedure('ПолучитьПроводку = 1;'),         # method names are not reserved
                     'Процедура П(Знач Строка1)\nКонецПроцедуры',
                     procedure('А = Строка(1);'),                # call
                     procedure('Если Мин(1, 2) = 1 Тогда КонецЕсли;'),
                     procedure('Т = 1;', 'Т.Строка = 1;'),       # member, not a variable
                     procedure('А = "Строка = 1";'),             # string literal
                     procedure('// Строка = 1;')):
            with self.subTest(text=text):
                self.assertEqual(found(text, 'L7708'), [])

    def test_comparison_after_keyword_is_not_a_declaration(self):
        self.assertEqual(found(procedure('А = 1;', 'Если А = 1 Тогда КонецЕсли;',
                                         'Пока А = 2 Цикл КонецЦикла;'), 'L7708'), [])


class MethodArityTests(unittest.TestCase):
    """L7709: Операция.ПолучитьПроводку(1) failed at run time in 7.7; the compiler accepted it."""

    def test_more_arguments_than_any_signature(self):
        text = procedure('Опер = СоздатьОбъект("Операция");', 'Опер.ПолучитьПроводку(н);')
        self.assertEqual(found(text, 'L7709'), [(3, 'warning')])
        self.assertEqual(found(text, 'L7709', strict=True), [(3, 'error')])

    def test_within_limits_or_unknown(self):
        for line in ('Пока Опер.ПолучитьПроводку() = 1 Цикл КонецЦикла;',
                     'А = т.ПолучитьЗначение(1, "a,b");',              # comma inside a literal
                     'А = т.ПолучитьЗначение(Ф(1, 2), 3);',            # nested call is one argument
                     'Л = Локатор.ConnectServer(".", "root\\cimv2");',  # COM, not in the catalog
                     'Т.Write(1, 2, 3);',                              # English names are not checked
                     'А = 1; // Опер.ПолучитьПроводку(н);',
                     'Р.СводныеОстатки(1, 2, 3, 4, 5, 6);'):           # variadic signature
            with self.subTest(line=line):
                self.assertEqual(found(procedure(line), 'L7709'), [])

    def test_boundary_at_the_limit(self):
        # Сред: template 2, @Синтаксис 3 parameters; as a method name "Найти" has at most 2? Use a
        # method with a fixed limit: ВыбратьПроводки() takes none, one argument is over.
        self.assertEqual(found(procedure('Опер.ВыбратьПроводки();'), 'L7709'), [])
        self.assertEqual(found(procedure('Опер.ВыбратьПроводки(1);'), 'L7709'), [(2, 'warning')])
        self.assertEqual(found(procedure('Опер.ВыбратьПроводки(,);'), 'L7709'), [(2, 'warning')])


class LineLengthTests(unittest.TestCase):
    """L7710: the Configurator refused 590 characters; Enterprise accepted 5000 (warning only)."""

    def test_boundary_and_what_is_counted(self):
        self.assertEqual(found('А = "' + 'ж' * 493 + '";', 'L7710'), [])           # 500
        self.assertEqual(found('А = "' + 'ж' * 494 + '";', 'L7710'), [(1, 'warning')])  # 501
        self.assertEqual(found('// ' + 'к' * 600, 'L7710'), [(1, 'warning')])      # comments count
        self.assertEqual(found('\ufeff' + 'к' * 500 + '\r\n' + 'к' * 500 + '\r\n', 'L7710'), [])

    def test_position_reports_the_guard(self):
        diagnostic = next(d for d in analyze('А = 1;\n' + 'к' * 590)['diagnostics'] if d['rule'] == 'L7710')
        self.assertEqual((diagnostic['line'], diagnostic['column']), (2, 501))
        self.assertIn('590', diagnostic['message'])


class DeclarationTests(unittest.TestCase):
    """L7711 follows the probed 7.7 semantics: a local exists from its first assignment."""

    DIALOG = {'фамилия', 'выбдатанач'}

    def reported(self, text, **kwargs):
        kwargs.setdefault('dialog', self.DIALOG)
        return found(text, 'L7711', **kwargs)

    def test_not_checked_without_form_context(self):
        self.assertEqual(found(procedure('Сообщить(Неизвестная);'), 'L7711'), [])

    def test_undeclared_reads(self):
        cases = {
            procedure('Сообщить(Неизвестная);'): 2,
            procedure('А = Б;', 'Б = 1;'): 2,                                # read before assignment
            'Процедура Задать()\nХ = 1;\nКонецПроцедуры\n' + procedure('Сообщить(Х);'): 5,
            procedure('Сообщить(М);') + 'М = 1;\n': 2,                         # module body comes later
            procedure('Т = 1;', 'Т.ПолучитьПараметрыКолонки(1, Тип1);'): 3,  # out-parameter too
            procedure('Если Х = 1 Тогда КонецЕсли;'): 2,                       # comparison reads
            procedure('Сообщить(Фамилия2);'): 2,
            procedure('Х.Метод();'): 2,
        }
        for text, line in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.reported(text), [(line, 'warning')])

    def test_declared_names(self):
        for text in (procedure('А = 1;', 'Сообщить(А);'),
                     'Процедура П(Знач А, Б = 1)\nСообщить(А + Б);\nКонецПроцедуры',
                     procedure('Перем Л;', 'Сообщить(Л);'),
                     'Перем М Экспорт, Н[10];\n' + procedure('Сообщить(М); Сообщить(Н[1]);'),
                     procedure('Для Н = 1 По 2 Цикл Сообщить(Н); КонецЦикла;'),
                     procedure('Сообщить(Фамилия); Сообщить(ВЫБДАТАНАЧ);'),
                     procedure('Г = Константа; Г = Форма; Г = РазделительСтрок; Г = ФС;'),
                     procedure('Перейти ~Метка;', '~Метка: А = 1;'),
                     procedure('ОткрытьФорму("Отчет", Контекст);'),               # keyword, readable
                     procedure('Т = СоздатьОбъект("ТаблицаЗначений");', 'Т.Колонка = Т.Количество;'),
                     'Функция Ф()\nВозврат 1;\nКонецФункции\n' + procedure('Если Ф() = 1 Тогда КонецЕсли;'),
                     procedure('Если 1 = 1 Тогда А = 1; Иначе А = 2; КонецЕсли;', 'Сообщить(А);')):
            with self.subTest(text=text):
                self.assertEqual(self.reported(text), [])

    def test_one_report_per_name_and_procedure(self):
        text = procedure('Сообщить(Х);', 'Сообщить(Х);') + procedure('Сообщить(Х);').replace('П()', 'П2()')
        self.assertEqual(self.reported(text), [(2, 'warning'), (6, 'warning')])

    def test_platform_names_are_not_all_readable(self):
        # The probe found 35 readable platform names; Тип and Длина are method words, not globals.
        self.assertEqual(self.reported(procedure('Сообщить(Тип);', 'Сообщить(Длина);')),
                         [(2, 'warning'), (3, 'warning')])
        self.assertEqual(self.reported(procedure('Г = Да; Г = Метаданные; Г = Регистр; Г = СтрокаДействийФормы;')), [])

    def test_global_context_variables_allow_and_severity(self):
        text = procedure('Сообщить(глВерсия);', 'Сообщить(глСкрытая);')
        self.assertEqual(self.reported(text), [(2, 'warning'), (3, 'warning')])
        # Exported variables of the supplied global module are visible, private ones are not. It is the
        # configuration's global module: the context is complete, and 1C does not compile the read (task 022).
        self.assertEqual(self.reported(text, globals_text='Перем глВерсия Экспорт;\nПерем глСкрытая;'),
                         [(3, 'error')])
        # A text of other global names (not a configuration's global module) leaves the context open.
        source = lint77.Source('test.1s', '', text, dialog=frozenset(self.DIALOG))
        other = lint77.Source('names.1s', '', 'Перем глВерсия Экспорт;\nПерем глСкрытая;')
        self.assertEqual([(d['line'], d['severity']) for d in lint77.analyze([source], [other])['diagnostics']
                          if d['rule'] == 'L7711'], [(3, 'warning')])
        self.assertEqual(self.reported(text, strict=True), [(2, 'error'), (3, 'error')])
        source = lint77.Source('test.1s', '', text, dialog=frozenset(self.DIALOG))
        report = lint77.analyze([source], allow=['глВерсия', 'глСкрытая'])
        self.assertEqual([d for d in report['diagnostics'] if d['rule'] == 'L7711'], [])


class FormContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='harness77-rules-')
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def cli(self, *args):
        result = subprocess.run([sys.executable, '-m', 'harness77', 'lint', *map(str, args), '--format', 'json'],
                                capture_output=True, text=True, encoding='utf-8')
        return result.returncode, (json.loads(result.stdout) if result.stdout else json.loads(result.stderr))

    def test_ert_dialog_is_the_context_of_its_module(self):
        module = 'Процедура ВыгрузкаЭ02()\r\nСообщить(выбДатаНач);\r\nСообщить(выбДатаКон);\r\nКонецПроцедуры\r\n'
        form = self.dir / 'form.ert'
        form.write_bytes(make_ert(ert.encode_dialog(DIALOG), module))
        code, report = self.cli(form)
        self.assertEqual(code, 0)
        self.assertEqual(report['form_context_modules'], 1)
        self.assertEqual([(d['rule'], d['line']) for d in report['diagnostics']], [('L7711', 3)])

    def test_dialog_option_for_text_modules(self):
        form = self.dir / 'form.ert'
        form.write_bytes(make_ert(ert.encode_dialog(DIALOG)))
        module = self.dir / 'module.1s'
        module.write_text(procedure('Сообщить(выбДатаНач);', 'Сообщить(выбУровеньЛога);'), encoding='utf-8')
        self.assertEqual(self.cli(module)[1]['diagnostics'], [])
        code, report = self.cli(module, '--dialog', form)
        self.assertEqual([(d['rule'], d['line']) for d in report['diagnostics']], [('L7711', 3)])
        self.assertEqual(self.cli(module, '--dialog', module)[0], 2)  # not an ERT

    def test_dialog_input_is_never_the_report(self):
        form = self.dir / 'form.ert'
        form.write_bytes(make_ert(ert.encode_dialog(DIALOG)))
        original = form.read_bytes()
        module = self.dir / 'module.1s'
        module.write_text(procedure('Сообщить(выбДатаНач);'), encoding='utf-8')
        link = self.dir / 'link.ert'
        os.link(form, link)
        for output in (form, link):
            with self.subTest(output=output.name):
                code, report = self.cli(module, '--dialog', form, '--output', output)
                self.assertEqual(code, 2)
                self.assertIn('fatal_error', report)
                self.assertEqual(form.read_bytes(), original)

    def test_report_names_the_catalog(self):
        report = analyze('А = 1;')
        self.assertEqual(report['catalog']['platform_version'], '7.70.027')
        self.assertEqual(report['version'], '0.6.0')


class RunStaticContextTests(unittest.TestCase):
    """`run` checks the text module in the form context of its build template."""

    def test_template_dialog_reaches_the_static_stage(self):
        from stage4_fixtures import base_scenario, run, write_project, write_sim_stand
        with tempfile.TemporaryDirectory(prefix='harness77-rules-run-') as temp:
            root = Path(temp)
            source = procedure('Сообщить(выбДатаНач);', 'Сообщить(выбУровеньЛога);')
            project = write_project(root, source_text=source)
            report = run(project, write_sim_stand(root, base_scenario()), root / 'runs')
            static = next(s for s in report['stages'] if s['stage'] == 'static')
            self.assertEqual([(d['rule'], d['line'], d['severity']) for d in static['diagnostics']],
                             [('L7711', 3, 'warning')])
            self.assertEqual(static['status'], 'passed')  # a warning does not fail the stage


if __name__ == '__main__':
    unittest.main()
