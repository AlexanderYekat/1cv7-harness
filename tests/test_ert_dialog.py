import contextlib
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from harness77 import ert_module as ert


def control(caption, kind, control_id, formula, identifier):
    fields = [caption, kind, '1342177291', '70', '142', '54', '14', '0', '0', control_id, '',
              formula, identifier, '-1', 'U'] + ['0'] * 5 + ['', '', '', '0', '-11'] + ['0'] * 12
    fields += ['MS Sans Serif', '-1', '-1', '0', 'Основной', '{"0","0"}']
    return '{' + ','.join('"' + x.replace('"', '""') + '"' for x in fields) + '}'


# Разметка повторяет форму обработки 1С 7.7: CRLF, "" внутри строк, два пробела в конце.
DIALOG = (
    '{"Dialogs",\r\n{"Frame",\r\n{"-11","0","0","0","400","0","0","0","204","1","2","1","34",'
    '"MS Sans Serif","320","165"," ","","","0","","1","1","6","34","-1","0","0",\r\n'
    '{"0",\r\n{"Основной","1"}},"1","1"}},\r\n{"Controls",\r\n'
    + control('Закрыть', 'BUTTON', '4152', '#Закрыть', '') + ',\r\n'
    + control('&Набор Э0.2', 'BUTTON', '4153', 'ВыгрузкаЭ02()', '') + ',\r\n'
    + control('Дата "с"', 'BMASKED', '4154', '', 'выбДатаНач')
    + '},\r\n{"Cnt_Ver","10001"}}  '
)
SMALL_DIALOG = '{"Dialogs",{"Controls"}}'
MODULE = 'Процедура ВыгрузкаЭ02()\r\nКонецПроцедуры\r\n'
CONTENTS = b'\x01\x02\x03container'


def base_container():
    """CFB v3: module and dialog as regular streams, empty third stream."""
    header = bytearray(512)
    header[:8] = bytes.fromhex('D0CF11E0A1B11AE1')
    struct.pack_into('<HHHH', header, 24, 0x3e, 3, 0xfffe, 9)
    struct.pack_into('<H', header, 32, 6)
    struct.pack_into('<I', header, 44, 1)  # FAT sectors
    struct.pack_into('<I', header, 48, 0)  # directory sector
    struct.pack_into('<I', header, 56, 4096)
    struct.pack_into('<I', header, 60, 0xfffffffe)
    struct.pack_into('<I', header, 68, 0xfffffffe)
    struct.pack_into('<109I', header, 76, 17, *([0xffffffff] * 108))

    def entry(name, kind, sector, size, right=0xffffffff, child=0xffffffff):
        data = bytearray(128)
        encoded = (name + '\0').encode('utf-16le')
        data[:len(encoded)] = encoded
        struct.pack_into('<H', data, 64, len(encoded))
        data[66], data[67] = kind, 1
        struct.pack_into('<III', data, 68, 0xffffffff, right, child)
        struct.pack_into('<I', data, 116, sector)
        struct.pack_into('<Q', data, 120, size)
        return data

    directory = entry('Root Entry', 5, 0xfffffffe, 0, child=1)
    directory += entry(ert.MODULE_STREAM, 2, 1, 4096, right=2)
    directory += entry(ert.DIALOG_STREAM, 2, 9, 4096, right=3)
    directory += entry('Container.Contents', 2, 0xfffffffe, 0)
    fat = [0xfffffffe] + list(range(2, 9)) + [0xfffffffe] + list(range(10, 17))
    fat += [0xfffffffe, 0xfffffffd]
    fat += [0xffffffff] * (128 - len(fat))
    return bytes(header) + directory + bytes(8192) + struct.pack('<128I', *fat)


def make_ert(dialog_payload, module=MODULE):
    """Small streams end up in the mini stream, as in real ERT files."""
    compound = ert.CompoundFile(base_container())
    return compound.rebuild({1: ert.compress_module(module.encode('cp1251')),
                             2: dialog_payload, 3: CONTENTS})


def streams(path):
    compound = ert.CompoundFile(Path(path).read_bytes())
    return {e.name: compound.read_stream(e) for e in compound.directory_entries if e.object_type == 2}


class DialogFormatTests(unittest.TestCase):
    def test_prefix_forms_and_round_trip(self):
        cases = [(0, 1), (254, 1), (255, 3), (1207, 3), (0xFFFD, 3), (0xFFFE, 7), (70000, 7)]
        for length, prefix in cases:
            with self.subTest(length=length):
                text = 'ж' * length
                payload = ert.encode_dialog(text)
                self.assertEqual(len(payload), length + prefix)
                self.assertEqual(ert.decode_dialog(payload), text)
        self.assertEqual(ert.encode_dialog('x' * 1207)[:3], b'\xff\xb7\x04')
        self.assertEqual(ert.encode_dialog('x' * 70000)[:7], b'\xff\xff\xff' + struct.pack('<I', 70000))

    def test_stale_length_rejected(self):
        # Так выглядели синтетические формы harness77: текст длиннее заголовка.
        payload = b'\xff' + struct.pack('<H', 2427) + b'x' * 2452
        with self.assertRaisesRegex(ert.ErtError, '2427.*2452'):
            ert.decode_dialog(payload)

    def test_broken_headers_rejected(self):
        for payload in (b'', b'\xff\x01', b'\xff\xfe\xff\x01', b'\xff\xff\xff\x01'):
            with self.subTest(payload=payload), self.assertRaises(ert.ErtError):
                ert.decode_dialog(payload)

    def test_non_cp1251_rejected(self):
        with self.assertRaisesRegex(ert.ErtError, 'Windows-1251'):
            ert.encode_dialog('✓')


class DialogParseTests(unittest.TestCase):
    def test_controls(self):
        controls = ert.dialog_controls(DIALOG)
        self.assertEqual([(c.control_id, c.kind, c.caption, c.formula, c.identifier) for c in controls], [
            ('4152', 'BUTTON', 'Закрыть', '#Закрыть', ''),
            ('4153', 'BUTTON', '&Набор Э0.2', 'ВыгрузкаЭ02()', ''),
            ('4154', 'BMASKED', 'Дата "с"', '', 'выбДатаНач'),
        ])

    def test_nested_quoted_list_stays_a_string(self):
        root = ert.parse_dialog(DIALOG)
        self.assertEqual(root[2][1][-1], '{"0","0"}')

    def test_parse_errors_have_line(self):
        cases = [DIALOG[:-4], DIALOG.replace('"Закрыть",', '"Закрыть', 1), DIALOG + '}', '"Dialogs"']
        for text in cases:
            with self.subTest(text=text[-20:]), self.assertRaisesRegex(ert.ErtError, 'строка \\d+'):
                ert.parse_dialog(text)

    def test_unknown_structure(self):
        with self.assertRaises(ert.ErtError):
            ert.dialog_controls('{"Other"}')
        with self.assertRaisesRegex(ert.ErtError, '№ 1'):
            ert.dialog_controls('{"Dialogs",{"Controls",{"short","BUTTON"}}}')


class DialogReplaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.form = self.dir / 'form.ert'
        self.form.write_bytes(make_ert(ert.encode_dialog(DIALOG)))
        self.out = self.dir / 'out.ert'

    def tearDown(self):
        self.tmp.cleanup()

    def test_rename_button_recalculates_length(self):
        source = self.form.read_bytes()
        pairs = [('"&Набор Э0.2"', '"&Набор Э0.3 — полный"'), ('"ВыгрузкаЭ02()"', '"ВыгрузкаЭ03()"')]
        with contextlib.redirect_stderr(io.StringIO()) as err:
            ert.replace_dialog_strings(self.form, pairs, self.out)
        self.assertIn('U+2014', err.getvalue())
        self.assertEqual(self.form.read_bytes(), source)
        before, after = streams(self.form), streams(self.out)
        payload = after[ert.DIALOG_STREAM]
        self.assertEqual(struct.unpack('<H', payload[1:3])[0], len(payload) - 3)
        self.assertNotEqual(len(payload), len(before[ert.DIALOG_STREAM]))
        self.assertEqual(after[ert.MODULE_STREAM], before[ert.MODULE_STREAM])
        self.assertEqual(after['Container.Contents'], CONTENTS)
        button = ert.dialog_controls(ert.extract_dialog(self.out))[1]
        self.assertEqual((button.caption, button.formula), ('&Набор Э0.3 - полный', 'ВыгрузкаЭ03()'))

    def test_in_place_update(self):
        ert.replace_dialog_strings(self.form, [('"ВыгрузкаЭ02()"', '"ВыгрузкаЭ03()"')], self.form)
        self.assertEqual(ert.dialog_controls(ert.extract_dialog(self.form))[1].formula, 'ВыгрузкаЭ03()')

    def test_fragment_must_occur_once(self):
        for old in ('"НетТакой()"', '"BUTTON"'):
            with self.subTest(old=old), self.assertRaisesRegex(ert.ErtError, 'ровно 1'):
                ert.replace_dialog_strings(self.form, [(old, '"X"')], self.out)
        self.assertFalse(self.out.exists())

    def test_invalid_text_not_written(self):
        with self.assertRaises(ert.ErtError):
            ert.replace_dialog_text(self.form, DIALOG[:-4], self.out)
        self.assertFalse(self.out.exists())

    def test_prefix_kind_change_refused(self):
        self.form.write_bytes(make_ert(ert.encode_dialog(SMALL_DIALOG)))
        with self.assertRaisesRegex(ert.ErtError, 'не проверен'):
            ert.replace_dialog_text(self.form, DIALOG, self.out)
        self.assertFalse(self.out.exists())

    def test_stale_source_rejected(self):
        body = DIALOG.encode('cp1251')
        self.form.write_bytes(make_ert(b'\xff' + struct.pack('<H', len(body) - 25) + body))
        with self.assertRaisesRegex(ert.ErtError, 'без пересчёта'):
            ert.extract_dialog(self.form)
        with self.assertRaisesRegex(ert.ErtError, 'без пересчёта'):
            ert.replace_dialog_text(self.form, DIALOG, self.out)
        self.assertFalse(self.out.exists())

    def test_lf_stored_as_crlf(self):
        ert.replace_dialog_text(self.form, DIALOG.replace('\r\n', '\n'), self.out)
        self.assertEqual(streams(self.out)[ert.DIALOG_STREAM], ert.encode_dialog(DIALOG))


class DialogCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.form = self.dir / 'form.ert'
        self.form.write_bytes(make_ert(ert.encode_dialog(DIALOG)))

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ert.main([str(x) for x in args])
        return code, out.getvalue(), err.getvalue()

    def test_extract_replace_round_trip(self):
        text, result = self.dir / 'dialog.txt', self.dir / 'out.ert'
        self.assertEqual(self.run_main('dialog-extract', self.form, text)[0], 0)
        self.assertEqual(self.run_main('dialog-replace', self.form, text, result)[0], 0)
        self.assertEqual(streams(result)[ert.DIALOG_STREAM], streams(self.form)[ert.DIALOG_STREAM])

    def test_controls_table(self):
        code, out, _ = self.run_main('dialog-controls', self.form)
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], 'id\tclass\tcaption\tformula\tidentifier')
        self.assertEqual(lines[2], '4153\tBUTTON\t&Набор Э0.2\tВыгрузкаЭ02()\t')
        self.assertEqual(len(lines), 4)

    def test_same_output_refused(self):
        text = self.dir / 'dialog.txt'
        self.run_main('dialog-extract', self.form, text)
        code, _, err = self.run_main('dialog-replace', self.form, text, self.form)
        self.assertEqual(code, 1)
        self.assertIn('отличаться', err)

    def test_stale_dialog_reported(self):
        body = DIALOG.encode('cp1251')
        self.form.write_bytes(make_ert(b'\xff' + struct.pack('<H', 100) + body))
        code, _, err = self.run_main('dialog-show', self.form)
        self.assertEqual(code, 1)
        self.assertIn(f'100 байт, фактически {len(body)}', err)


if __name__ == '__main__':
    unittest.main()
