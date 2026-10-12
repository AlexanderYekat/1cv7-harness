import contextlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from harness77 import lint77


def analyze(text, globals_=(), **kwargs):
    return lint77.analyze([lint77.Source('test.1s', '', text)], globals_, **kwargs)


def compressed(text):
    obj = zlib.compressobj(wbits=-15)
    return obj.compress(text.encode('cp1251')) + obj.flush()


def make_ert(text):
    """Small actual CFB fixture: one regular-sector module, no external packages."""
    raw = compressed(text)
    # A regular stream must be >=4096. Trailing bytes are ignored by DEFLATE.
    payload = raw.ljust(4096, b'\0')
    if len(payload) != 4096:
        raise ValueError('Fixture too large')
    header = bytearray(512)
    header[:8] = bytes.fromhex('D0CF11E0A1B11AE1')
    struct.pack_into('<HHHH', header, 24, 0x3e, 3, 0xfffe, 9)
    struct.pack_into('<H', header, 32, 6)
    struct.pack_into('<I', header, 44, 1)  # FAT sectors
    struct.pack_into('<I', header, 48, 0)  # directory sector
    struct.pack_into('<I', header, 56, 4096)
    struct.pack_into('<I', header, 60, 0xfffffffe)
    struct.pack_into('<I', header, 68, 0xfffffffe)
    struct.pack_into('<109I', header, 76, 9, *([0xffffffff]*108))

    def entry(name, kind, sector, size, child=0xffffffff):
        data = bytearray(128)
        encoded = (name + '\0').encode('utf-16le')
        data[:len(encoded)] = encoded
        struct.pack_into('<H', data, 64, len(encoded))
        data[66], data[67] = kind, 1
        struct.pack_into('<III', data, 68, 0xffffffff, 0xffffffff, child)
        struct.pack_into('<I', data, 116, sector)
        struct.pack_into('<Q', data, 120, size)
        return data

    directory = entry('Root Entry', 5, 0xfffffffe, 0, 1)
    directory += entry('MD Programm text', 2, 1, len(payload))
    directory += bytes(256)
    fat = [0xfffffffe] + list(range(2, 9)) + [0xfffffffe, 0xfffffffd]
    fat += [0xffffffff] * (128-len(fat))
    return bytes(header) + directory + payload + struct.pack('<128I', *fat)


class AnalysisTests(unittest.TestCase):
    def rules(self, text, **kwargs):
        return [d['rule'] for d in analyze(text, **kwargs)['diagnostics']]

    def test_screenshot_regression(self):
        lines = [379, 384, 968, 1001, 1185, 1399]
        source = ['// filler'] * 1400
        for line in lines:
            source[line-1] = '\tОбработкаПрерыванияПользователя();'
        report = analyze('\n'.join(source))
        self.assertEqual([d['line'] for d in report['diagnostics']], lines)
        self.assertEqual(report['errors'], 6)
        self.assertTrue(all(d['rule'] == 'L7706' for d in report['diagnostics']))

    def test_comments_strings_and_doubled_quotes(self):
        text = '// Bad();\nСообщить("Bad(\"\"text\"\"); // НеКод()");'
        self.assertEqual(self.rules(text), [])

    def test_multiline_blank_lines(self):
        self.assertEqual(self.rules('А="Пока\n|НеФункция()\n\n \t\n|Если";'), [])

    def test_comment_between_string_continuations(self):
        self.assertEqual(self.rules('А="SELECT\n//| Bad() \";\n| WHERE X=1\n| END";'), [])

    def test_unterminated_string_recovers_position(self):
        report = analyze('А="bad\nНеизвестно();')
        self.assertEqual([d['rule'] for d in report['diagnostics']], ['L7701', 'L7704'])
        self.assertEqual(report['diagnostics'][1]['line'], 2)

    def test_brackets_in_strings_ignored(self):
        self.assertEqual(self.rules('Сообщить("(]");'), [])
        self.assertIn('L7702', self.rules('Сообщить((1);'))

    def test_casefold_and_forward(self):
        self.assertEqual(self.rules('функция Ф(Знач А) далее\n'
                                   'Сообщить(ф(1));\nФУНКЦИЯ ф(А)\nВозврат А;\nКОНЕЦФУНКЦИИ'), [])

    def test_duplicate_and_missing_implementation(self):
        self.assertIn('L7703', self.rules('Процедура А() далее'))
        self.assertIn('L7703', self.rules('Процедура А()\nКонецПроцедуры\n'
                                        'Процедура а()\nКонецПроцедуры'))

    def test_forward_kind_mismatch(self):
        self.assertIn('L7703', self.rules('Процедура А() Далее\nФункция А()\nКонецФункции'))

    def test_balanced_blocks_and_empty_parameter_slots(self):
        text = ('Процедура П(А, Б)\nЕсли А=1 Тогда\nПока Б=1 Цикл\n'
                'Попытка\nПрервать;\nИсключение\nПродолжить;\nКонецПопытки;\n'
                'КонецЦикла;\nИначеЕсли А=2 Тогда\nИначе\nКонецЕсли;\nКонецПроцедуры\nП(,2);')
        self.assertEqual(self.rules(text), [])

    def test_mismatched_blocks(self):
        self.assertIn('L7703', self.rules('Если 1=1 Тогда\nКонецЦикла;'))
        self.assertIn('L7703', self.rules('Продолжить;'))

    def test_optional_and_nested_arguments(self):
        text = 'Функция Ф(А,Б=0)\nВозврат А;\nКонецФункции\nФ(Мин(1,2));\nФ(1,);'
        self.assertEqual(self.rules(text), [])
        self.assertEqual(self.rules(text + '\nФ();\nФ(1,2,3);').count('L7705'), 2)

    def test_unknown_call_warns_or_fails_explicit_strict(self):
        self.assertEqual(analyze('Несуществующая();')['errors'], 0)
        self.assertEqual(analyze('Несуществующая();')['warnings'], 1)
        self.assertEqual(analyze('Несуществующая();', strict=True)['errors'], 1)
        self.assertEqual(self.rules('Несуществующая();', allow=['НЕСУЩЕСТВУЮЩАЯ']), [])

    def test_method_not_a_global_call_but_arguments_checked(self):
        self.assertEqual(self.rules('Объект.НеизвестныйМетод(Мин(1,2));'), [])
        self.assertEqual(self.rules('Объект.НеизвестныйМетод(Опечатка());'), ['L7704'])

    def test_local_compatibility_wrapper_wins_over_known8(self):
        text = ('Процедура ОбработкаПрерыванияПользователя()\nКонецПроцедуры\n'
                'ОбработкаПрерыванияПользователя();')
        self.assertEqual(self.rules(text), [])

    def test_only_exported_global_symbols_visible(self):
        global_ = lint77.Source('global.1s', '',
                                'Процедура Есть(А) Экспорт\nКонецПроцедуры\n'
                                'Процедура Закрытая()\nКонецПроцедуры')
        report = analyze('Есть(1); Закрытая();', [global_])
        self.assertEqual([d['rule'] for d in report['diagnostics']], ['L7704'])

    def test_exports_do_not_leak_between_local_modules(self):
        report = lint77.analyze([lint77.Source('a.1s', '', 'Процедура А() Экспорт\nКонецПроцедуры'),
                                 lint77.Source('b.1s', '', 'А();')])
        self.assertEqual(report['warnings'], 1)

    def test_md_global_flag_supplies_context(self):
        report = lint77.analyze([lint77.Source('x.md', 'global', 'Процедура А() Экспорт\nКонецПроцедуры', True),
                                 lint77.Source('x.md', 'form', 'А();')])
        self.assertEqual(report['diagnostics'], [])

    def test_globals_do_not_leak_between_infobases(self):
        report = lint77.analyze([lint77.Source('a.md', 'global', 'Процедура А() Экспорт\nКонецПроцедуры', True),
                                 lint77.Source('b.md', 'form', 'А();')])
        self.assertEqual(report['warnings'], 1)

    def test_new_is_legal_77_identifier(self):
        self.assertEqual(self.rules('Новый = 1; Если Новый = 1 Тогда\nКонецЕсли;'), [])
        self.assertEqual(self.rules('А = Новый Структура;'), ['L7707'])

    def test_date_functions_are_77_not_8(self):
        self.assertEqual(self.rules('ДатаГод(ТекущаяДата()); GetYear(CurrentDate());'), [])
        self.assertEqual(self.rules('Год(ТекущаяДата()); Year(CurrentDate()); ЧислоПрописью(1);'),
                         ['L7706', 'L7706', 'L7706'])

    def test_english_and_crlf_positions(self):
        report = analyze('Procedure Run()\r\n UserInterruptProcessing();\r\nEndProcedure')
        self.assertEqual(report['errors'], 1)
        self.assertEqual(report['diagnostics'][0]['line'], 2)
        self.assertEqual(report['diagnostics'][0]['column'], 2)

    def test_directives_are_not_silently_accepted(self):
        self.assertIn('L7707', self.rules('#Если Сервер Тогда\n#КонецЕсли'))


class IOTests(unittest.TestCase):
    def test_encodings(self):
        with tempfile.TemporaryDirectory() as temp:
            for encoding in ('utf-8', 'utf-8-sig', 'cp1251', 'utf-16'):
                path = Path(temp) / 'test.1s'
                path.write_bytes('Сообщить("Привет");'.encode(encoding))
                self.assertEqual(lint77.analyze(lint77.load_sources(path))['diagnostics'], [])

    def test_real_cfb_ert_extraction_and_input_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.ert'
            raw = make_ert('Процедура П()\nОбработкаПрерыванияПользователя();\nКонецПроцедуры')
            path.write_bytes(raw)
            report = lint77.analyze(lint77.load_sources(path))
            self.assertEqual(report['errors'], 1)
            self.assertEqual(report['diagnostics'][0]['line'], 2)
            self.assertEqual(report['diagnostics'][0]['module'], 'MD Programm text')
            self.assertEqual(path.read_bytes(), raw)

    def test_bad_input_is_fatal(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.ert'
            path.write_bytes(b'broken')
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(lint77.main([str(path), '--format', 'json']), 2)
            self.assertIn('fatal_error', json.loads(stderr.getvalue()))

    def test_output_cannot_replace_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.1s'
            path.write_text('Сообщить(1);', encoding='utf-8')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(lint77.main([str(path), '--output', str(path)]), 2)
            self.assertEqual(path.read_text(encoding='utf-8'), 'Сообщить(1);')

    def test_cli_json_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.1s'
            for text, expected in [('Сообщить(1);', 0), ('Опечатка();', 0),
                                   ('ОбработкаПрерыванияПользователя();', 1)]:
                path.write_text(text, encoding='utf-8')
                proc = subprocess.run([sys.executable, '-m', 'harness77', 'lint', str(path), '--format', 'json'],
                                      capture_output=True, encoding='utf-8')
                self.assertEqual(proc.returncode, expected, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)['modules'], 1)

    def test_utf16_cli_json_not_polluted_by_encoding_note(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.1s'
            path.write_bytes('Сообщить(1);'.encode('utf-16'))
            proc = subprocess.run([sys.executable, '-m', 'harness77', 'lint', str(path), '--format', 'json'],
                                  capture_output=True, encoding='utf-8')
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout)['errors'], 0)

    def test_globals_file_and_report_written_without_changing_input(self):
        with tempfile.TemporaryDirectory() as temp:
            source, context, output = [Path(temp) / name for name in ('m.1s', 'global.1s', 'report.json')]
            source.write_text('глПомощник(1);', encoding='utf-8')
            context.write_text('Процедура глПомощник(А) Экспорт\nКонецПроцедуры', encoding='utf-8')
            self.assertEqual(lint77.main([str(source), '--globals', str(context), '--format', 'json',
                                          '--output', str(output)]), 0)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['errors'], 0)
            self.assertEqual(source.read_text(encoding='utf-8'), 'глПомощник(1);')

    def test_empty_directory_is_not_clean_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(lint77.main([temp]), 2)


if __name__ == '__main__':
    unittest.main()
