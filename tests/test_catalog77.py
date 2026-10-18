"""Platform catalog: syntax helper, PE string resources, packaged catalog."""

import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from harness77 import catalog77

BIN = Path(os.environ.get("HARNESS77_1C_BIN", r"C:\Program Files (x86)\1Cv77\BIN"))

ALS = '''{"Shell",
 {"Folder","AST","Системные","",
  {"Folder","AST","Функции/процедуры","",
   {"Folder","AST","Строковые","",
    {"Item","AST","Сред","Mid","Сред(<?>,)","Mid(<?>,)","@Синтаксис:
Сред(<Строка>,<НачальнаяПозиция>,<Количество>)
@Назначение:
текст, который не попадает в каталог"}},
   {"Folder","AST","Математические","",
    {"Item","AST","Мин","Min","Мин(<?>)","Min(<?>)","@Синтаксис:
Мин(<Знач1>, ..., <ЗначN>)"}}},
  {"Folder","AST","Константы","",
   {"Item","AST","РазделительСтрок","LineBreak","РазделительСтрок","LineBreak",""}}},
 {"Folder","AST","Конструкции языка","",
  {"Folder","AST","Структурные","",
   {"Item","AST","Если Тогда","If Then","Если <?> Тогда","If <?> Then",""}}},
 {"Folder","AST","Контекст формы","",
  {"Folder","AST","Объект ''Форма''","",
   {"Item","AST","ПанельИнструментов","ToolBar","Форма.ПанельИнструментов(<?>);","Form.ToolBar(<?>);","@Синтаксис:
Форма.ПанельИнструментов(<Режим>)"},
   {"Item","AST","<ЭлементДиалога>","<Attribute>","Форма.<?>","Form.<?>",""},
   {"Item","AST","ПриОткрытии","OnOpen","Процедура ПриОткрытии()
КонецПроцедуры","Procedure OnOpen()
EndProcedure",""}}},
 {"Folder","A","Операции и проводки","",
  {"Item","A","ПолучитьПроводку","SelectEntry","ПолучитьПроводку()","SelectEntry()",""},
  {"Item","A","ВидСчета","AccountKind","ВидСчета","AccountKind",""}}
}
'''


def string_blocks(strings):
    """RT_STRING blocks: 16 length-prefixed UTF-16 strings each, id = (block-1)*16+index."""
    blocks = {}
    for string_id, text in strings.items():
        blocks.setdefault(string_id // 16 + 1, [""] * 16)[string_id % 16] = text
    return {block: b"".join(struct.pack("<H", len(t)) + t.encode("utf-16-le") for t in texts)
            for block, texts in blocks.items()}


def make_pe(strings, version=(7, 70, 0, 27)):
    """Minimal PE32 with one .rsrc section: RT_STRING blocks and an RT_VERSION."""
    version_data = struct.pack("<4xIIIII", 0xFEEF04BD, 0, (version[0] << 16) | version[1],
                               (version[2] << 16) | version[3], 0)
    resources = {6: string_blocks(strings), 16: {1: version_data}}
    # Layout: directories first, then data entries, then data. Offsets are section-relative.
    directories, data_entries, payloads = bytearray(), [], []

    def directory(entries):
        return struct.pack("<12xHH", 0, len(entries)) + b"".join(
            struct.pack("<II", ident, target) for ident, target in entries)

    type_dir_size = 16 + 8 * len(resources)
    name_dirs = {t: 16 + 8 * len(names) for t, names in resources.items()}
    offset = type_dir_size + sum(name_dirs.values()) + sum(24 * len(n) for n in resources.values())
    entry_offset = offset
    data_offset = entry_offset + 16 * sum(len(n) for n in resources.values())
    type_entries, name_blobs, lang_blobs = [], [], []
    cursor = type_dir_size
    lang_cursor = type_dir_size + sum(name_dirs.values())
    for type_id, names in resources.items():
        type_entries.append((type_id, 0x80000000 | cursor))
        entries = []
        for name_id, payload in names.items():
            entries.append((name_id, 0x80000000 | lang_cursor))
            lang_blobs.append(directory([(1049, entry_offset)]))
            data_entries.append((data_offset, len(payload)))
            payloads.append(payload)
            entry_offset += 16
            data_offset += len(payload)
            lang_cursor += 24
        name_blobs.append(directory(entries))
        cursor += name_dirs[type_id]
    directories += directory(type_entries) + b"".join(name_blobs) + b"".join(lang_blobs)
    section_rva = 0x1000
    body = bytes(directories) + b"".join(struct.pack("<IIII", section_rva + off, size, 0, 0)
                                         for off, size in data_entries) + b"".join(payloads)
    pe_offset, optional_size = 0x40, 224
    headers = bytearray(0x200)
    headers[:2] = b"MZ"
    struct.pack_into("<I", headers, 0x3C, pe_offset)
    headers[pe_offset:pe_offset + 4] = b"PE\0\0"
    struct.pack_into("<HH12xHH", headers, pe_offset + 4, 0x14C, 1, optional_size, 0x2102)
    optional = pe_offset + 24
    struct.pack_into("<H", headers, optional, 0x10B)
    struct.pack_into("<II", headers, optional + 96 + 2 * 8, section_rva, len(body))
    section = optional + optional_size
    headers[section:section + 8] = b".rsrc\0\0\0"
    struct.pack_into("<IIII", headers, section + 8, len(body), section_rva, len(body), 0x200)
    return bytes(headers) + body


PE_STRINGS = {
    1440: "Ошибок не обнаружено", 1441: "Нераспознанная синтаксическая ошибка",
    1488: "Ожидается имя формального параметра", 1500: "Function %s(%s)",
    1600: "Индексное выражение должно иметь целочисленный тип", 1611: "Деление на 0",
    1621: "Сообщение, не пара",
    1640: "If,Если", 1641: "Then,Тогда", 1642: "String,Строка", 1643: "CreateObject,СоздатьОбъект",
    1650: "Message,Сообщить", 1651: "Accs,Счета,Account,Счет", 1652: "Name,Name",
    1653: "GroupValue, ЗначениеГруппировки",
}


class SyntaxHelperTests(unittest.TestCase):
    def setUp(self):
        self.items = {(i["kind"], i["title_ru"]): i for i in catalog77.parse_als(ALS)}

    def test_kinds_names_and_folders(self):
        mid = self.items[("global_function", "Сред")]
        self.assertEqual((mid["name_ru"], mid["name_en"], mid["components"]), ("Сред", "Mid", "AST"))
        self.assertEqual(mid["folder"], "Системные/Функции/процедуры/Строковые")
        self.assertEqual(self.items[("global_constant", "РазделительСтрок")]["name_en"], "LineBreak")
        self.assertEqual(self.items[("keyword", "Если Тогда")]["name_ru"], "Если")
        self.assertEqual(self.items[("predefined_procedure", "ПриОткрытии")]["name_ru"], "ПриОткрытии")
        self.assertEqual(self.items[("attribute", "ВидСчета")]["name_ru"], "ВидСчета")

    def test_arity_takes_template_and_syntax(self):
        # Template says 2, the @Синтаксис line 3: both are kept, the maximum is 3.
        mid = self.items[("global_function", "Сред")]
        self.assertEqual((mid["params"], mid["max_params"]), ([2, 3], 3))
        self.assertEqual(self.items[("method", "ПолучитьПроводку")]["max_params"], 0)

    def test_variadic_signature_has_no_limit(self):
        self.assertIsNone(self.items[("global_function", "Мин")]["max_params"])

    def test_prefixed_method_and_placeholder(self):
        toolbar = self.items[("method", "ПанельИнструментов")]
        self.assertEqual((toolbar["name_ru"], toolbar["max_params"]), ("ПанельИнструментов", 1))
        self.assertIsNone(self.items[("attribute", "<ЭлементДиалога>")]["name_ru"])

    def test_descriptions_and_templates_are_not_copied(self):
        text = json.dumps(catalog77.parse_als(ALS), ensure_ascii=False)
        self.assertNotIn("Назначение", text)
        self.assertNotIn("<?>", text)

    def test_malformed_helper_is_rejected(self):
        for broken in ('{"Shell",{"Item","AST","А"}', '{"Shell"}}', '{"Shell",{"Item","AST","А","B","А()","B()"}}',
                       '{"Shell"} x', '{"Shell"}'):
            with self.subTest(broken=broken), self.assertRaises(catalog77.CatalogError):
                catalog77.parse_als(broken)


class StringResourceTests(unittest.TestCase):
    def test_string_ids_and_version(self):
        data = make_pe(PE_STRINGS)
        table = {i: t for i, _lang, t in catalog77.string_table(data)}
        self.assertEqual(table, PE_STRINGS)
        self.assertEqual(catalog77.file_version(data), "7.70.0.27")

    def test_pairs_keep_two_part_cyrillic_names_only(self):
        pairs = [(p["id"], p["en"], p["ru"]) for p in catalog77.name_pairs(make_pe(PE_STRINGS))]
        self.assertIn((1653, "GroupValue", "ЗначениеГруппировки"), pairs)
        self.assertNotIn(1651, [p[0] for p in pairs])  # four parts
        self.assertNotIn(1652, [p[0] for p in pairs])  # no Cyrillic name

    def test_reserved_block_is_bounded_by_empty_ids(self):
        block = catalog77.reserved_block(make_pe(PE_STRINGS))
        self.assertEqual((block["first_id"], block["last_id"]), (1640, 1643))
        self.assertEqual(block["names"], ["If", "Если", "Then", "Тогда", "String", "Строка",
                                          "CreateObject", "СоздатьОбъект"])

    def test_messages_are_split_into_compile_and_runtime_blocks(self):
        messages = catalog77.compiler_messages(make_pe(PE_STRINGS))
        self.assertEqual([(m["id"], m["block"]) for m in messages],
                         [(1440, "compile"), (1441, "compile"), (1488, "compile"),
                          (1600, "runtime"), (1611, "runtime"), (1621, "runtime")])
        self.assertNotIn(1500, [m["id"] for m in messages])  # a text template, not a message

    def test_unknown_message_layout_is_rejected(self):
        without_runtime = {k: v for k, v in PE_STRINGS.items() if k != 1600}
        swapped = {**PE_STRINGS, 1440: "Индексное выражение должно иметь целочисленный тип",
                   1600: "Ошибок не обнаружено"}
        doubled = {**PE_STRINGS, 1442: "Ошибок не обнаружено"}
        for strings in (without_runtime, swapped, doubled):
            with self.subTest(strings=sorted(set(strings.items()) ^ set(PE_STRINGS.items()))),                     self.assertRaises(catalog77.CatalogError):
                catalog77.compiler_messages(make_pe(strings))

    def test_missing_keyword_table_and_bad_pe(self):
        with self.assertRaises(catalog77.CatalogError):
            catalog77.reserved_block(make_pe({1650: "Message,Сообщить"}))
        for data in (b"", b"MZ" + bytes(100), make_pe(PE_STRINGS)[:0x150]):
            with self.subTest(size=len(data)), self.assertRaises(catalog77.CatalogError):
                catalog77.string_table(data)


class CatalogFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-catalog-")
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        (self.dir / "1cv7Lang.als").write_bytes(ALS.encode("cp1251"))
        (self.dir / "1crcrus.dll").write_bytes(make_pe(PE_STRINGS))

    def cli(self, output):
        return subprocess.run([sys.executable, "-m", "harness77", "catalog", "--als", str(self.dir / "1cv7Lang.als"),
                               "--strings", str(self.dir / "1crcrus.dll"), "--output", str(output)],
                              capture_output=True, text=True, encoding="utf-8")

    def test_same_input_same_bytes_and_provenance(self):
        first, second = self.cli(self.dir / "a.json"), self.cli(self.dir / "b.json")
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr)
        self.assertEqual((self.dir / "a.json").read_bytes(), (self.dir / "b.json").read_bytes())
        catalog = json.loads((self.dir / "a.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["platform_version"], "7.70.027")
        self.assertEqual([s["name"] for s in catalog["sources"]], ["1cv7Lang.als", "1crcrus.dll"])
        self.assertEqual(json.loads(first.stdout)["output"]["sha256"],
                         __import__("hashlib").sha256((self.dir / "a.json").read_bytes()).hexdigest())

    def test_existing_output_is_never_replaced(self):
        target = self.dir / "existing.json"
        target.write_text("keep", encoding="utf-8")
        result = self.cli(target)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["status"], "blocked")
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")
        self.assertEqual(self.cli(self.dir / "missing" / "x.json").returncode, 2)


class PackagedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog77.load_packaged()

    def test_reserved_names_match_the_native_survey(self):
        # Survey 2026-10-15 on 7.70.027: these names were rejected, Сообщить accepted.
        reserved = {n.casefold() for n in self.catalog["reserved"]["names"]}
        for name in ("Строка", "String", "Число", "Дата", "Мин", "Макс", "СоздатьОбъект", "ОписаниеОшибки",
                     "Если", "ВызватьИсключение"):
            self.assertIn(name.casefold(), reserved)
        for name in ("Сообщить", "Шаблон", "РабочаяДата", "ЗначениеВСтрокуВнутр", "Форма"):
            self.assertNotIn(name.casefold(), reserved)
        self.assertEqual(len(reserved), 162)

    def test_counts_and_known_signatures(self):
        self.assertEqual(self.catalog["counts"], {"items": 1133, "pairs": 1322, "messages": 95})
        methods = {i["name_ru"]: i for i in self.catalog["items"] if i["kind"] == "method"}
        self.assertEqual(methods["ПолучитьПроводку"]["max_params"], 0)

    def test_messages_seen_from_the_native_compiler(self):
        # Native probes of task 009 (7.70.027) produced these messages at load.
        messages = {m["id"]: m for m in self.catalog["messages"]}
        self.assertEqual(sum(m["block"] == "compile" for m in messages.values()), 72)
        for string_id, text in ((1475, "Обнаружено логическое завершение исходного текста модуля"),
                                (1488, "Ожидается имя формального параметра"), (1531, "Процедура не обнаружена"),
                                (1539, "Слишком много фактических параметров"), (1535, "Переменная не определена")):
            self.assertEqual((messages[string_id]["text"], messages[string_id]["block"]), (text, "compile"))
        self.assertEqual(messages[1611]["block"], "runtime")

    @unittest.skipUnless((BIN / "1cv7Lang.als").is_file() and (BIN / "1crcrus.dll").is_file(),
                         "installed 1C 7.7 BIN not available")
    def test_packaged_catalog_matches_installed_platform(self):
        catalog = catalog77.build_catalog(BIN / "1cv7Lang.als", BIN / "1crcrus.dll")
        packaged = Path(catalog77.__file__).with_name(catalog77.PACKAGED).read_text(encoding="utf-8")
        self.assertEqual(catalog77.dumps(catalog), packaged)


if __name__ == "__main__":
    unittest.main()
