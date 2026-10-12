import codecs
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness77.compiler_protocol77 import parse_protocol
from harness77 import compiler_protocol77


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures/compiler_protocol77"
END = "При проверке модуля обнаружены синтаксические ошибки!"
SOURCE = "ОбработкаПрерыванияПользователя<<?>>();"
HEADER = r"{C:\project\report.ert(423)}: Процедура не обнаружена (ОбработкаПрерыванияПользователя)"
SAMPLE = (SOURCE + "\n" + HEADER + "\n" + END + "\n").encode("utf-8")
SAMPLE_DIAGNOSTIC = {
    "file": r"C:\project\report.ert", "line": 423, "column": 32,
    "message": "Процедура не обнаружена (ОбработкаПрерыванияПользователя)",
    "source_line": "ОбработкаПрерыванияПользователя();", "protocol_line": 2,
}
TOP_KEYS = ["schema_version", "tool", "scope", "status", "protocol_sha256",
            "input_encoding", "diagnostics", "unparsed_lines", "issues"]


def encoded(*lines):
    return "\n".join(lines).encode("utf-8")


class ProtocolTests(unittest.TestCase):
    def parse(self, data, **kwargs):
        report = parse_protocol(data, **kwargs)
        self.assertEqual(list(report), TOP_KEYS)
        self.assertEqual(report["schema_version"], 1)
        self.assertIs(type(report["schema_version"]), int)
        self.assertEqual(report["tool"], "compiler-protocol77")
        self.assertEqual(report["scope"], "imported_platform_protocol")
        self.assertIn(report["status"], ("failed", "blocked"))
        self.assertEqual(report["protocol_sha256"], hashlib.sha256(data).hexdigest())
        self.assertIn(report["input_encoding"], (None, "utf-8", "utf-8-sig", "cp1251"))
        for name in ("diagnostics", "unparsed_lines", "issues"):
            self.assertIsInstance(report[name], list)
        for diagnostic in report["diagnostics"]:
            self.assertEqual(list(diagnostic), list(SAMPLE_DIAGNOSTIC))
            self.assertIsInstance(diagnostic["file"], str)
            self.assertIsInstance(diagnostic["message"], str)
            for key in ("line", "protocol_line"):
                self.assertIs(type(diagnostic[key]), int)
                self.assertGreater(diagnostic[key], 0)
            if diagnostic["column"] is None:
                self.assertIsNone(diagnostic["source_line"])
            else:
                self.assertIs(type(diagnostic["column"]), int)
                self.assertGreater(diagnostic["column"], 0)
                self.assertIsInstance(diagnostic["source_line"], str)
        for item in report["unparsed_lines"]:
            self.assertEqual(list(item), ["protocol_line", "text"])
            self.assertIsInstance(item["text"], str)
            self.assertIs(type(item["protocol_line"]), int)
            self.assertGreater(item["protocol_line"], 0)
        pairs = []
        for item in report["issues"]:
            self.assertEqual(list(item), ["code", "message", "protocol_line"])
            self.assertIsInstance(item["code"], str)
            self.assertIsInstance(item["message"], str)
            self.assertTrue(item["message"])
            if item["protocol_line"] is not None:
                self.assertIs(type(item["protocol_line"]), int)
                self.assertGreater(item["protocol_line"], 0)
            pairs.append((item["code"], item["protocol_line"]))
        self.assertEqual(len(pairs), len(set(pairs)))
        local = [pair for pair in pairs if pair[1] is not None]
        self.assertEqual(local, sorted(local, key=lambda pair: (pair[1], pair[0])))
        unknown = [item["protocol_line"] for item in report["unparsed_lines"]]
        self.assertEqual(unknown, sorted(set(unknown)))
        self.assertEqual(unknown, [line for code, line in pairs if code == "unparsed_line"])
        if report["status"] == "failed":
            self.assertTrue(report["diagnostics"])
            self.assertEqual(report["issues"], [])
            self.assertEqual(report["unparsed_lines"], [])
        else:
            self.assertTrue(report["issues"])
        self.assertEqual(json.loads(json.dumps(report, ensure_ascii=False, allow_nan=False)), report)
        return report

    def issues(self, report, expected):
        self.assertEqual([(i["code"], i["protocol_line"]) for i in report["issues"]], expected)

    def test_a01_determinism_and_independent_results(self):
        for data in (SAMPLE, b"?", b"\x98"):
            with self.subTest(data=data):
                first, second = self.parse(data), self.parse(data)
                self.assertEqual(first, second)
                for key in ("diagnostics", "unparsed_lines", "issues"):
                    if first[key]:
                        first[key][0]["sentinel"] = True
                    first[key].append({"sentinel": True})
                self.assertEqual(second, self.parse(data))

    def test_a02_argument_errors(self):
        for value in ("text", bytearray(), memoryview(b""), None, Path("x"), 1):
            with self.subTest(value=value), self.assertRaises(TypeError):
                parse_protocol(value)
        for encoding in ("UTF-8", "utf-8-sig", "latin1", "", None, []):
            with self.subTest(encoding=encoding), self.assertRaises(ValueError):
                parse_protocol(b"", encoding=encoding)
        with self.assertRaises(ValueError):
            parse_protocol(None, encoding="invalid")

    def test_a02_empty_report(self):
        self.assertEqual(self.parse(b""), {
            "schema_version": 1, "tool": "compiler-protocol77",
            "scope": "imported_platform_protocol", "status": "blocked",
            "protocol_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "input_encoding": "utf-8", "diagnostics": [], "unparsed_lines": [],
            "issues": [
                {"code": "empty_protocol", "message": "Протокол не содержит значимых строк.", "protocol_line": None},
                {"code": "no_diagnostics", "message": "Диагностики не найдены.", "protocol_line": None},
                {"code": "missing_terminator", "message": "Завершающий маркер отсутствует.", "protocol_line": None},
            ],
        })

    def test_a03_encodings_and_hashes(self):
        hashes = set()
        for codec in ("utf-8", "utf-8-sig", "cp1251"):
            data = SAMPLE.decode("utf-8").encode(codec)
            hashes.add(hashlib.sha256(data).hexdigest())
            for mode in ("auto", "utf-8" if codec == "utf-8-sig" else codec):
                with self.subTest(codec=codec, mode=mode):
                    report = self.parse(data, encoding=mode)
                    self.assertEqual(report["input_encoding"], codec)
                    self.assertEqual(report["diagnostics"], [SAMPLE_DIAGNOSTIC])
                    self.assertEqual(report["status"], "failed")
        self.assertEqual(len(hashes), 3)

    def test_a04_auto_and_explicit_decoders(self):
        for data in (b"", b"ASCII", "Я".encode("utf-8")):
            with self.subTest(data=data):
                self.assertEqual(self.parse(data)["input_encoding"], "utf-8")
                explicit = self.parse(data, encoding="cp1251")
                self.assertEqual(explicit["input_encoding"], "cp1251")
                if data:
                    self.assertEqual(explicit["unparsed_lines"][0]["text"], data.decode("cp1251"))
        report = self.parse(b"\xff", encoding="utf-8")
        self.issues(report, [("decode_error", None)])
        self.assertEqual(self.parse(b"\xff")["input_encoding"], "cp1251")

    def test_a05_unsupported_boms(self):
        for bom, name in ((codecs.BOM_UTF32_LE, "UTF-32 LE"), (codecs.BOM_UTF32_BE, "UTF-32 BE"),
                          (codecs.BOM_UTF16_LE, "UTF-16 LE"), (codecs.BOM_UTF16_BE, "UTF-16 BE"),
                          (codecs.BOM_UTF8, "UTF-8")):
            for mode in ("auto", "utf-8", "cp1251"):
                if bom == codecs.BOM_UTF8 and mode != "cp1251":
                    continue
                with self.subTest(name=name, mode=mode):
                    report = self.parse(bom + b"abc", encoding=mode)
                    self.issues(report, [("unsupported_encoding", None)])
                    self.assertIn(name, report["issues"][0]["message"])
                    self.assertIn(mode, report["issues"][0]["message"])
                    self.assertIsNone(report["input_encoding"])
                    self.assertEqual(report["diagnostics"], [])
                    self.assertEqual(report["unparsed_lines"], [])

    def test_a05_a06_strict_decode_failures(self):
        cases = [(b"\x98", "auto", ["utf-8", "cp1251"], 0),
                 (b"\x98", "cp1251", ["cp1251"], 0),
                 (codecs.BOM_UTF8 + b"a\xff", "auto", ["utf-8-sig"], 4),
                 (codecs.BOM_UTF8 + b"a\xff", "utf-8", ["utf-8-sig"], 4)]
        for data, mode, decoders, offset in cases:
            with self.subTest(data=data, mode=mode):
                report = self.parse(data, encoding=mode)
                self.issues(report, [("decode_error", None)])
                self.assertIsNone(report["input_encoding"])
                self.assertEqual(report["diagnostics"], [])
                self.assertEqual(report["unparsed_lines"], [])
                for decoder in decoders:
                    self.assertIn(decoder, report["issues"][0]["message"])
                self.assertIn(f"смещение {offset}", report["issues"][0]["message"])
                if data.startswith(codecs.BOM_UTF8):
                    self.assertNotIn("cp1251", report["issues"][0]["message"])

    def test_a07_physical_lines_and_newline_hashes(self):
        variants = [SAMPLE, SAMPLE.replace(b"\n", b"\r\n"), SAMPLE[:-1],
                    SAMPLE.replace(b"\n", b"\r\n", 1)]
        hashes = set()
        for data in variants:
            with self.subTest(data=data):
                report = self.parse(data)
                self.assertEqual(report["diagnostics"], [SAMPLE_DIAGNOSTIC])
                self.assertEqual(report["status"], "failed")
                hashes.add(report["protocol_sha256"])
        self.assertEqual(len(hashes), len(variants))
        report = self.parse(b"\n \t\r\n" + SAMPLE + b"\n\t\n")
        self.assertEqual(report["diagnostics"], [{**SAMPLE_DIAGNOSTIC, "protocol_line": 4}])
        self.assertEqual(report["status"], "failed")
        for data in (b"a\n", b"a\n\n"):
            self.assertEqual(self.parse(data)["unparsed_lines"], [{"protocol_line": 1, "text": "a"}])

    def test_a07_lone_cr_cannot_be_source_or_terminator(self):
        for source in (SOURCE + "\r", SOURCE + "\r\r"):
            report = self.parse(encoded(source, HEADER, END))
            if source.endswith("\r\r"):
                self.assertEqual(report["unparsed_lines"], [{"protocol_line": 1, "text": SOURCE + "\r"}])
                self.assertIsNone(report["diagnostics"][0]["column"])
            else:  # A CR immediately before LF is a valid CRLF.
                self.assertEqual(report["status"], "failed")
        report = self.parse(encoded(HEADER, END + "\r"))
        self.issues(report, [("missing_terminator", None), ("unparsed_line", 2)])
        for line in (SOURCE + "\rX", HEADER + "\r", "\r"):
            report = self.parse(encoded(line + "\r", HEADER, END))
            self.assertIsNone(report["diagnostics"][0]["source_line"])
            self.assertEqual(report["unparsed_lines"][0]["text"], line)

    def test_a07_unicode_separators_and_embedded_bom_are_preserved(self):
        for char in ("\u0085", "\u2028", "\u2029", "\ufeff", "\v", "\f"):
            report = self.parse(encoded("{x(1)}: before" + char + "after", END))
            self.assertEqual(report["diagnostics"][0]["message"], "before" + char + "after")
            self.assertEqual(report["diagnostics"][0]["protocol_line"], 1)
            self.assertEqual(report["status"], "failed")
        report = self.parse(codecs.BOM_UTF8 + encoded("\ufeff", HEADER, END))
        self.assertEqual(report["unparsed_lines"], [{"protocol_line": 1, "text": "\ufeff"}])

    def test_b01_exact_spec_example(self):
        self.assertEqual(len(SAMPLE), 312)
        report = self.parse(SAMPLE)
        self.assertEqual(report["protocol_sha256"], "2534e75173bc427f7136809fb628f3f29eb1e2158a7ff6a2346bcfe0243b676b")
        self.assertEqual(report["diagnostics"], [SAMPLE_DIAGNOSTIC])
        self.assertEqual(report["status"], "failed")

    def test_b02_path_and_message_are_opaque(self):
        path = r" C:\несуществующий каталог (копия)\%ENV%\file.any "
        message = "  Ошибка: (x) (12)}: хвост \t"
        report = self.parse(encoded("{" + path + "(0007)}: " + message, END))
        self.assertEqual(report["diagnostics"][0], {
            "file": path, "line": 7, "column": None, "message": message,
            "source_line": None, "protocol_line": 1,
        })
        report = self.parse(encoded("{first(2)}: second(3)}: last", END))
        self.assertEqual(report["diagnostics"][0]["file"], "first")
        self.assertEqual(report["diagnostics"][0]["message"], "second(3)}: last")

    def test_b03_codepoint_columns_and_exact_source(self):
        for source, column, plain in [("<<?>>abc", 1, "abc"), ("abc<<?>>", 4, "abc"),
                                      ("<<?>>", 1, ""), ("\tЯ😀<<?>>  ", 4, "\tЯ😀  ")]:
            with self.subTest(source=source):
                diagnostic = self.parse(encoded(source, HEADER, END))["diagnostics"][0]
                self.assertEqual(diagnostic["column"], column)
                self.assertEqual(diagnostic["source_line"], plain)

    def test_b04_diagnostic_without_source(self):
        report = self.parse(encoded(HEADER, END))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["diagnostics"], [{**SAMPLE_DIAGNOSTIC, "column": None, "source_line": None, "protocol_line": 1}])
        report = self.parse(encoded("unmarked", HEADER, END))
        self.issues(report, [("unparsed_line", 1)])
        self.assertIsNone(report["diagnostics"][0]["column"])

    def test_b05_pair_boundaries(self):
        cases = [("a<<?>>b<<?>>", [1], None, None),
                 ("orphan<<?>>\n", [1], None, None),
                 ("first<<?>>\nsecond<<?>>", [1], 7, "second")]
        for prefix, unknown, column, source in cases:
            with self.subTest(prefix=prefix):
                report = self.parse(encoded(prefix, HEADER, END))
                self.assertEqual([i["protocol_line"] for i in report["unparsed_lines"]], unknown)
                self.assertEqual(report["diagnostics"][0]["column"], column)
                self.assertEqual(report["diagnostics"][0]["source_line"], source)
        report = self.parse(encoded(HEADER, "orphan<<?>>", END))
        self.issues(report, [("unparsed_line", 2)])

    def test_b06_invalid_headers(self):
        invalid = ["{x(0)}: err", "{x(000)}: err", "{x(-1)}: err", "{x(+1)}: err",
                   "{x(1.5)}: err", "{x(no)}: err", "{x(١)}: err", "{x(１)}: err",
                   "{(1)}: err", "{ \t(1)}: err", "{x(1)}: ", "{x(1)}: \t ",
                   "{x(1)}:err", "{x(1)}:\terr", "prefix{x(1)}: err", " {x(1)}: err"]
        for header in invalid:
            with self.subTest(header=header):
                report = self.parse(encoded(header, HEADER, END))
                self.assertEqual(len(report["diagnostics"]), 1)
                self.assertEqual(report["unparsed_lines"], [{"protocol_line": 1, "text": header}])
        report = self.parse(encoded("{x(" + "0" * 5000 + "7)}: err", END))
        self.assertEqual(report["diagnostics"][0]["line"], 7)

    def test_b07_diagnostic_priority_and_duplicates(self):
        header = "{x(2)}: message<<?>>"
        report = self.parse(encoded(header, header, END))
        self.assertEqual(len(report["diagnostics"]), 2)
        for item in report["diagnostics"]:
            self.assertIsNone(item["column"])
            self.assertIsNone(item["source_line"])
            self.assertEqual(item["message"], "message<<?>>")
        report = self.parse(encoded("{x(9)}: err", "{x(2)}: err", "{x(9)}: err", END))
        self.assertEqual([d["line"] for d in report["diagnostics"]], [9, 2, 9])

    def test_b06_line_numbers_remain_json_compatible_at_any_python_limit(self):
        old_limit = sys.get_int_max_str_digits()
        self.addCleanup(sys.set_int_max_str_digits, old_limit)
        for limit in (640, 4300, 0):
            sys.set_int_max_str_digits(limit)
            for digits in ("9" * 640, "0" * 5000 + "9" * 640, "0" * 5000 + "7"):
                with self.subTest(limit=limit, digits=len(digits)):
                    report = self.parse(encoded("{x(" + digits + ")}: err", END))
                    self.assertEqual(report["status"], "failed")
                    self.assertEqual(str(report["diagnostics"][0]["line"]), digits.lstrip("0"))
            for count in (641, 4301, 400000):
                with self.subTest(limit=limit, digits=count):
                    header = "{x(" + "9" * count + ")}: err<<?>>"
                    report = self.parse(encoded(header, HEADER, END))
                    self.issues(report, [("unparsed_line", 1)])
                    self.assertEqual(report["unparsed_lines"], [{"protocol_line": 1, "text": header}])
                    self.assertEqual(len(report["diagnostics"]), 1)
                    self.assertIsNone(report["diagnostics"][0]["source_line"])
            self.assertEqual(sys.get_int_max_str_digits(), limit)

    def test_c01_empty_arbitrary_and_terminator_only(self):
        for data in (b"", b" \t\n\r\n\t"):
            self.issues(self.parse(data), [("empty_protocol", None), ("no_diagnostics", None), ("missing_terminator", None)])
        self.issues(self.parse(b"arbitrary"), [("no_diagnostics", None), ("missing_terminator", None), ("unparsed_line", 1)])
        self.issues(self.parse(encoded(END)), [("no_diagnostics", None), ("invalid_terminator", 1)])

    def test_c02_terminator_positions(self):
        cases = [([HEADER], [("missing_terminator", None)]),
                 ([END, HEADER], [("invalid_terminator", 1)]),
                 ([HEADER, END, END], [("invalid_terminator", 2), ("invalid_terminator", 3)]),
                 ([HEADER, END, "tail"], [("invalid_terminator", 2), ("unparsed_line", 3)]),
                 ([HEADER, END, "", " \t"], [])]
        for lines, issues in cases:
            with self.subTest(lines=lines):
                report = self.parse(encoded(*lines))
                self.issues(report, issues)
                self.assertEqual(len(report["diagnostics"]), 1)

    def test_c03_c04_partial_results_keep_later_diagnostics(self):
        report = self.parse(encoded(SOURCE, HEADER, "НЕИЗВЕСТНО"))
        self.assertEqual(report["diagnostics"], [SAMPLE_DIAGNOSTIC])
        self.issues(report, [("missing_terminator", None), ("unparsed_line", 3)])
        self.assertEqual(report["unparsed_lines"], [{"protocol_line": 3, "text": "НЕИЗВЕСТНО"}])
        report = self.parse(encoded(SOURCE, HEADER, END, "broken", SOURCE, HEADER))
        self.assertEqual(report["diagnostics"], [SAMPLE_DIAGNOSTIC, {**SAMPLE_DIAGNOSTIC, "protocol_line": 6}])
        self.issues(report, [("invalid_terminator", 3), ("unparsed_line", 4)])
        report = self.parse(encoded(SOURCE, HEADER, "broken", SOURCE, HEADER, END))
        self.assertEqual(len(report["diagnostics"]), 2)
        self.issues(report, [("unparsed_line", 3)])

    def test_e01_e02_manifest_and_complete_golden_reports(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual([case["id"] for case in manifest["cases"]], ["p1", "p2"])
        for case in manifest["cases"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(set(("id", "kind", "protocol_file", "expected_file", "sha256", "encoding", "diagnostic_count", "origin", "transformations")) <= case.keys())
                self.assertIn(case["kind"], ("sanitized", "synthetic"))
                self.assertTrue(case["origin"])
                self.assertTrue(case["transformations"])
                if case["kind"] == "sanitized":
                    self.assertRegex(case["original_sha256"], r"^[0-9a-f]{64}$")
                data = (FIXTURES / case["protocol_file"]).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), case["sha256"])
                self.assertFalse(data.startswith(codecs.BOM_UTF8))
                self.assertNotIn(b"\r", data)
                self.assertTrue(data.endswith(b"\n"))
                expected = json.loads((FIXTURES / case["expected_file"]).read_text(encoding="utf-8"))
                report = self.parse(data)
                self.assertEqual(report, expected)
                self.assertEqual(report["input_encoding"], case["encoding"])
                self.assertEqual(len(report["diagnostics"]), case["diagnostic_count"])
                numbers = [d["line"] for d in report["diagnostics"]]
                columns = [d["column"] for d in report["diagnostics"]]
                if case["id"] == "p1":
                    self.assertEqual(numbers, [63, 64, 66, 101, 107, 304, 306, 307, 309] + [311] * 51)
                    self.assertEqual(columns, [38, 1, 40, 32, 63, 46, 9, 9, 9, 16] + [28] * 50)
                else:
                    self.assertEqual(numbers, [423, 428, 1012, 1045, 1229, 1443, 2393])
                    self.assertEqual(columns, [32] * 7)
                self.assertEqual([d["protocol_line"] for d in report["diagnostics"]], list(range(2, len(numbers) * 2 + 1, 2)))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="compiler77-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.input = self.directory / "протокол с пробелами.txt"
        self.output = self.directory / "результат с пробелами.json"
        self.input.write_bytes(SAMPLE)

    def run_cli(self, *args, env=None, input_data=None):
        return subprocess.run([sys.executable, "-B", "-m", "harness77", "compiler-protocol", *map(str, args)],
                              cwd=self.directory, env=env or {**os.environ, "PYTHONIOENCODING": "utf-8"}, input=input_data,
                              capture_output=True, shell=False, timeout=20)

    def call_main(self, args=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = compiler_protocol77.main(args if args is not None else [str(self.input), "--output", str(self.output)])
        self.assertEqual(stdout.getvalue(), "")
        return code, stderr.getvalue()

    def assert_file_error(self, code, stderr, *, old=b"old result", residual=False):
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith("compiler-protocol77:"))
        self.assertIn("Новый результат не записан; существующий выходной файл не подтверждает этот запуск", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(self.input.read_bytes(), SAMPLE)
        self.assertEqual(self.output.read_bytes(), old)
        if not residual:
            self.assertEqual(sorted(p.name for p in self.directory.iterdir()), sorted([self.input.name, self.output.name]))

    def test_a01_import_has_no_cli_side_effects(self):
        code = "import sys; from harness77 import compiler_protocol77"
        result = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT)],
                                cwd=self.directory, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

    def test_d01_statuses_help_and_arguments(self):
        for data, status, code in ((SAMPLE, "failed", 1), (b"", "blocked", 2),
                                   (b"\x98", "blocked", 2), (encoded(HEADER), "blocked", 2)):
            with self.subTest(data=data):
                self.input.write_bytes(data)
                result = self.run_cli(self.input)
                self.assertEqual(result.returncode, code)
                self.assertEqual(result.stderr, b"")
                self.assertEqual(json.loads(result.stdout)["status"], status)
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn(b"usage:", help_result.stdout)
        self.assertEqual(help_result.stderr, b"")
        for args in ([], [self.input, "--encoding", "latin1"], [self.input, "--format", "xml"],
                     [self.input, "--unknown"], [self.input, self.input], ["--output"],
                     [self.input, "--out", self.output], [self.input, "--enc", "utf-8"],
                     [self.input, "--for", "json"]):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"usage:", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)
        for args, expected in ((["--help"], 0), ([], 2)):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(compiler_protocol77.main(args), expected)

    def test_d01_oversized_line_number_produces_blocked_json(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONINTMAXSTRDIGITS": "640"}
        for count, expected_code in ((640, 1), (641, 2), (4301, 2), (400000, 2)):
            with self.subTest(digits=count):
                header = "{x(" + "9" * count + ")}: err"
                self.input.write_bytes(encoded(header, END))
                result = self.run_cli(self.input, env=env)
                self.assertEqual(result.returncode, expected_code)
                self.assertEqual(result.stderr, b"")
                report = json.loads(result.stdout)
                if count == 640:
                    self.assertEqual(report["status"], "failed")
                else:
                    self.assertEqual(report["status"], "blocked")
                    self.assertEqual(report["unparsed_lines"], [{"protocol_line": 1, "text": header}])

    def test_d02_d03_utf8_bytes_foreign_cwd_and_relative_paths(self):
        env = {**os.environ, "PYTHONIOENCODING": "cp1251"}
        result = self.run_cli(self.input.name, "--format", "json", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        expected = (json.dumps(parse_protocol(SAMPLE), ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        self.assertEqual(result.stdout, expected)
        self.assertFalse(result.stdout.startswith(codecs.BOM_UTF8))
        self.assertTrue(result.stdout.endswith(b"}\n"))
        self.assertNotIn(b"\r", result.stdout)
        written = self.run_cli(self.input.name, "--output", self.output.name, env=env)
        self.assertEqual((written.returncode, written.stdout, written.stderr), (1, b"", b""))
        self.assertEqual(self.output.read_bytes(), result.stdout)

    def test_d01_explicit_encoding(self):
        self.input.write_bytes(SAMPLE.decode("utf-8").encode("cp1251"))
        result = self.run_cli(self.input, "--encoding", "cp1251")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout)["diagnostics"], [SAMPLE_DIAGNOSTIC])
        result = self.run_cli(self.input, "--encoding", "utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout)["issues"][0]["code"], "decode_error")

    def test_d04_invalid_file_paths(self):
        parent_file = self.directory / "ordinary.txt"
        parent_file.write_bytes(b"ordinary")
        cases = [(self.directory / "missing", []), (self.directory, []),
                 (self.input, ["--output", self.directory / "missing/out.json"]),
                 (self.input, ["--output", self.directory]),
                 (self.input, ["--output", parent_file / "out.json"])]
        for input_path, args in cases:
            with self.subTest(input_path=input_path, args=args):
                result = self.run_cli(input_path, *args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertTrue(result.stderr.startswith(b"compiler-protocol77:"))
                self.assertNotIn(b".. ", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)
                self.assertEqual(self.input.read_bytes(), SAMPLE)
                self.assertFalse(self.output.exists())
        self.assertFalse((self.directory / "missing").exists())

    def test_d04_dash_is_a_literal_path(self):
        result = self.run_cli("-", input_data=SAMPLE)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        (self.directory / "-").write_bytes(SAMPLE)
        result = self.run_cli("-", "--output", self.output)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, b"", b""))
        result = self.run_cli(self.input, "--output", "-")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, b"", b""))
        self.assertEqual(json.loads((self.directory / "-").read_bytes())["status"], "failed")

    def test_d05_same_file_spellings(self):
        child = self.directory / "child"
        child.mkdir()
        for output in (self.input, self.input.name, child / ".." / self.input.name):
            with self.subTest(output=output):
                result = self.run_cli(self.input, "--output", output)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertTrue(result.stderr.startswith(b"compiler-protocol77:"))
                self.assertEqual(self.input.read_bytes(), SAMPLE)
                self.assertFalse(list(self.directory.glob(".compiler-protocol77-*")))

    def test_d05_hard_link_identity(self):
        # Hard links are mandatory on the target Windows filesystem: no skip.
        os.link(self.input, self.output)
        self.assertTrue(os.path.samefile(self.input, self.output))
        result = self.run_cli(self.input, "--output", self.output)
        self.assertEqual(result.stdout, b"")
        self.assert_file_error(result.returncode, result.stderr.decode("utf-8"), old=SAMPLE)

    @unittest.skipUnless(os.name == "nt", "Windows-only case-insensitive path check")
    def test_d05_windows_case(self):
        result = self.run_cli(self.input, "--output", str(self.input).swapcase())
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(self.input.read_bytes(), SAMPLE)
        self.assertEqual(list(self.directory.iterdir()), [self.input])

    def make_symlink(self, path, target):
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")

    @unittest.skipUnless(os.name == "nt", "Windows-only directory junction check")
    def test_d05_directory_junction_identity_and_publication(self):
        junction = self.directory / "directory junction"
        # Pass paths as environment data, never interpolate them into shell code.
        command = ("$ErrorActionPreference = 'Stop'; New-Item -ItemType Junction "
                   "-Path $env:COMPILER77_JUNCTION -Target $env:COMPILER77_TARGET | Out-Null")
        created = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                 env={**os.environ, "COMPILER77_JUNCTION": str(junction),
                                      "COMPILER77_TARGET": str(self.directory)},
                                 capture_output=True, timeout=20)
        if junction.exists():
            # Remove only the junction, non-recursively, before temp cleanup.
            self.assertEqual(junction.parent.resolve(), self.directory)
            self.addCleanup(junction.rmdir)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(junction.resolve(), self.directory)
        for alias in (junction / self.input.name, Path(str(junction / self.input.name).swapcase())):
            with self.subTest(alias=alias):
                result = self.run_cli(self.input, "--output", alias)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertTrue(result.stderr.startswith(b"compiler-protocol77:"))
                self.assertNotIn(b".. ", result.stderr)
                self.assertEqual(self.input.read_bytes(), SAMPLE)
                self.assertFalse(list(self.directory.glob(".compiler-protocol77-*")))
        result = self.run_cli(junction / self.input.name, "--output", junction / self.output.name)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, b"", b""))
        self.assertEqual(json.loads(self.output.read_bytes())["status"], "failed")
        self.assertEqual(self.input.read_bytes(), SAMPLE)

    def test_d05_symlink_to_input_is_rejected(self):
        self.make_symlink(self.output, self.input)
        result = self.run_cli(self.input, "--output", self.output)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(self.input.read_bytes(), SAMPLE)
        self.assertTrue(self.output.is_symlink())
        self.assertFalse(list(self.directory.glob(".compiler-protocol77-*")))

    def test_d05_input_symlink_and_resolved_output_target(self):
        input_link = self.directory / "input-link"
        output_link = self.directory / "output-link"
        self.make_symlink(input_link, self.input)
        self.output.write_bytes(b"old")
        self.make_symlink(output_link, self.output)
        result = self.run_cli(input_link, "--output", output_link)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, b"", b""))
        self.assertTrue(output_link.is_symlink())
        self.assertEqual(json.loads(self.output.read_bytes())["status"], "failed")
        self.assertEqual(self.input.read_bytes(), SAMPLE)

    def test_d05_symlink_loop_fails_closed(self):
        self.make_symlink(self.output, self.output)
        result = self.run_cli(self.input, "--output", self.output)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"Traceback", result.stderr)
        self.assertEqual(self.input.read_bytes(), SAMPLE)

    def test_d06_replace_existing_including_blocked(self):
        for data, code, status in ((SAMPLE, 1, "failed"), (b"broken", 2, "blocked")):
            with self.subTest(status=status):
                self.input.write_bytes(data)
                self.output.write_bytes(b"old result")
                result = self.run_cli(self.input, "--output", self.output)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (code, b"", b""))
                self.assertEqual(json.loads(self.output.read_bytes())["status"], status)
                self.assertFalse(list(self.directory.glob(".compiler-protocol77-*")))
                self.assertEqual(self.input.read_bytes(), data)

    def test_d04_d06_creation_read_serialization_and_replace_failures(self):
        self.output.write_bytes(b"old result")
        for target, error in (("pathlib.Path.read_bytes", PermissionError("read denied")),
                              ("tempfile.NamedTemporaryFile", PermissionError("create denied")),
                              ("json.dumps", ValueError("serialization denied")),
                              ("os.replace", PermissionError("replace denied"))):
            with self.subTest(target=target):
                with mock.patch(target, side_effect=error):
                    code, stderr = self.call_main()
                self.assertIn(str(error), stderr)
                self.assert_file_error(code, stderr)

    def test_d06_temporary_write_and_flush_failures(self):
        self.output.write_bytes(b"old result")
        real_factory = tempfile.NamedTemporaryFile
        for operation in ("write", "flush", "short_write"):
            with self.subTest(operation=operation):
                @contextlib.contextmanager
                def faulty_file(*args, **kwargs):
                    with real_factory(*args, **kwargs) as stream:
                        proxy = mock.Mock(wraps=stream)
                        proxy.name = stream.name
                        if operation == "short_write":
                            proxy.write.return_value = 0
                        else:
                            getattr(proxy, operation).side_effect = OSError(operation + " denied")
                        yield proxy
                with mock.patch("tempfile.NamedTemporaryFile", faulty_file):
                    code, stderr = self.call_main()
                self.assert_file_error(code, stderr)

    def test_d07_first_and_repeated_identity_check_failures(self):
        self.output.write_bytes(b"old result")
        for effects, expected_calls in (([PermissionError("identity denied")], 1),
                                         ([False, PermissionError("identity denied")], 2),
                                         ([False, True], 2)):
            with self.subTest(effects=effects):
                with mock.patch("os.path.samefile", side_effect=effects) as identity:
                    code, stderr = self.call_main()
                    self.assertEqual(identity.call_count, expected_calls)
                self.assert_file_error(code, stderr)

    def test_d07_parent_permission_error(self):
        self.output.write_bytes(b"old result")
        original_stat = Path.stat
        def failing_stat(path, *args, **kwargs):
            if path == self.directory:
                raise PermissionError("parent denied")
            return original_stat(path, *args, **kwargs)
        with mock.patch.object(Path, "stat", failing_stat):
            code, stderr = self.call_main()
        self.assertIn("parent denied", stderr)
        self.assert_file_error(code, stderr)

    def test_d07_cleanup_failure_keeps_original_error_and_reports_residue(self):
        self.output.write_bytes(b"old result")
        with mock.patch("os.replace", side_effect=PermissionError("replace denied")), \
                mock.patch.object(Path, "unlink", side_effect=PermissionError("cleanup denied")):
            code, stderr = self.call_main()
        self.assert_file_error(code, stderr, residual=True)
        residue = list(self.directory.glob(".compiler-protocol77-*"))
        self.assertEqual(len(residue), 1)
        self.assertIn(str(residue[0]), stderr)
        self.assertIn("replace denied", stderr)
        self.assertIn("cleanup denied", stderr)
        self.assertEqual(json.loads(residue[0].read_bytes())["status"], "failed")

    def test_d08_stdout_write_and_flush_errors_at_process_exit(self):
        # Inject at the stream boundary in a real child, including Python shutdown.
        code = '''
import io, sys
from harness77 import compiler_protocol77
class Faulty(io.BytesIO):
    def write(self, value):
        if sys.argv[3] == "write":
            raise BrokenPipeError("write denied")
        if sys.argv[3] == "short":
            return 0
        return super().write(value)
    def flush(self):
        raise OSError("flush denied")
sys.stdout = io.TextIOWrapper(Faulty(), encoding="utf-8")
raise SystemExit(compiler_protocol77.main([sys.argv[2]]))
'''
        for operation in ("write", "flush", "short"):
            with self.subTest(operation=operation):
                result = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT), str(self.input), operation],
                                        capture_output=True, cwd=self.directory, timeout=20)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertTrue(result.stderr.startswith(b"compiler-protocol77:"), result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)
                self.assertNotIn(b"Exception ignored", result.stderr)

    def test_d08_real_closed_pipe(self):
        # A large report guarantees a write against the closed pipe, not merely
        # a race where the whole payload fitted in its buffer before closure.
        self.input.write_bytes(encoded(*([HEADER] * 5000), END))
        process = subprocess.Popen([sys.executable, "-B", "-m", "harness77", "compiler-protocol", str(self.input)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.directory)
        try:
            process.stdout.close()
            process.stdout = None
            _, stderr = process.communicate(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        self.assertEqual(process.returncode, 2)
        self.assertTrue(stderr.startswith(b"compiler-protocol77:"))
        self.assertNotIn(b"Traceback", stderr)
        self.assertNotIn(b"Exception ignored", stderr)

    def test_e01_fixture_cli_reports(self):
        for name in ("p1", "p2"):
            with self.subTest(name=name):
                result = self.run_cli(FIXTURES / f"{name}.txt")
                self.assertEqual((result.returncode, result.stderr), (1, b""))
                self.assertEqual(result.stdout, (FIXTURES / f"{name}.expected.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
