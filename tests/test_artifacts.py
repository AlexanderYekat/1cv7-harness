import contextlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness77 import artifacts as api, ert_module as ert, lint77
from test_ert_dialog import make_ert, DIALOG, CONTENTS


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = self.root / "шаблон формы.ert"
        self.source = self.root / "новый модуль.1s"
        self.output = self.root / "результат.ert"
        self.template.write_bytes(make_ert(ert.encode_dialog(DIALOG)))
        self.source.write_text("Сообщить(42);\n", encoding="utf-8", newline="\n")
        self.original = self.template.read_bytes()

    def build(self, **kwargs):
        return api.build(self.template, self.source, self.output, **kwargs)

    def assert_unpublished(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(self.template.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob(".harness77-*")), [])

    def test_build_readback_hashes_and_repeatability(self):
        report = self.build()
        self.assertEqual(ert.extract_text(self.output), "Сообщить(42);\r\n")
        self.assertEqual(report["output"]["sha256"], api.sha256(self.output.read_bytes()))
        self.assertEqual(report["source"]["sha256"], api.sha256(self.source.read_bytes()))
        self.assertEqual(report["template"]["sha256"], api.sha256(self.original))
        self.assertFalse(report["platform_checked"])
        self.assertTrue(all(report["verification"].values()))
        self.assertEqual(len(report["preserved_streams"]), 2)
        compound = ert.CompoundFile(self.output.read_bytes())
        self.assertEqual(compound.read_stream(compound.find_stream(ert.DIALOG_STREAM)), ert.encode_dialog(DIALOG))
        self.assertEqual(compound.read_stream(compound.find_stream("Container.Contents")), CONTENTS)
        second = self.root / "second.ert"
        api.build(self.template, self.source, second)
        self.assertEqual(second.read_bytes(), self.output.read_bytes())
        self.assertEqual(self.template.read_bytes(), self.original)
        self.assertEqual(self.source.read_text(encoding="utf-8"), "Сообщить(42);\n")

    def test_regular_and_mini_stream_sizes(self):
        rng = random.Random(17)
        text = "//" + "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=20000)) + "\n"
        self.source.write_text(text, encoding="utf-8")
        self.build()
        compound = ert.CompoundFile(self.output.read_bytes())
        self.assertGreater(compound.find_stream(ert.MODULE_STREAM).size, 4096)
        self.assertEqual(ert.extract_text(self.output), ert.normalize_newlines(text))
        restored = self.root / "small.ert"
        self.source.write_text("Сообщить(1);", encoding="utf-8")
        api.build(self.output, self.source, restored)
        self.assertEqual(ert.extract_text(restored), "Сообщить(1);")

    def test_extract_utf8_preserves_line_endings_and_input(self):
        text_path = self.root / "извлечение.txt"
        report = api.extract(self.template, text_path)
        self.assertEqual(text_path.read_bytes(), ert.extract_text(self.template).encode("utf-8"))
        self.assertEqual(report["output"]["sha256"], api.sha256(text_path.read_bytes()))
        self.assertEqual(self.template.read_bytes(), self.original)

    def test_source_encodings(self):
        text = "Сообщить(42);\r\n"
        for encoding in ("utf-8", "utf-8-sig", "cp1251", "utf-16"):
            with self.subTest(encoding=encoding):
                self.source.write_bytes(text.encode(encoding))
                output = self.root / f"{encoding}.ert"
                report = api.build(self.template, self.source, output)
                self.assertEqual(report["source"]["encoding"], encoding)
                self.assertEqual(ert.extract_text(output), text)

    def test_strict_encoding_and_explicit_legacy_normalization(self):
        self.source.write_text('// →\nСообщить("—");', encoding="utf-8")
        with self.assertRaises(UnicodeEncodeError):
            self.build()
        self.assert_unpublished()
        report = self.build(legacy_normalize=True)
        self.assertEqual(ert.extract_text(self.output), '// ->\r\nСообщить("-");')
        self.assertEqual(len(report["normalizations"]), 2)

    def test_representable_punctuation_preserved_by_default(self):
        self.source.write_text('// — “x”', encoding="utf-8")
        report = self.build()
        self.assertEqual(ert.extract_text(self.output), '// — “x”')
        self.assertEqual(report["normalizations"], [])

    def test_bad_encoding_and_nul_rejected(self):
        for raw, encoding in [(b"\x98", "cp1251"), (b"\xff", "utf-8"), (b"x\0y", "auto")]:
            with self.subTest(raw=raw):
                self.source.write_bytes(raw)
                with self.assertRaises((ValueError, ert.ErtError)):
                    self.build(encoding=encoding)
                self.assert_unpublished()

    def test_existing_output_and_input_aliases_refused(self):
        for output in (self.template, self.source):
            with self.subTest(output=output), self.assertRaises(ert.ErtError):
                api.build(self.template, self.source, output)
        os.link(self.template, self.output)
        with self.assertRaises(ert.ErtError):
            self.build()
        self.assertEqual(self.output.read_bytes(), self.original)

    def test_lint_report_hardlink_preserves_source(self):
        os.link(self.source, self.output)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(lint77.main([str(self.source), "--output", str(self.output)]), 2)
        self.assertEqual(self.source.read_bytes(), "Сообщить(42);\n".encode())

    def test_broken_and_ambiguous_template_refused(self):
        self.template.write_bytes(b"not CFB")
        with self.assertRaises(ert.ErtError):
            self.build()
        self.assertFalse(self.output.exists())
        compound = ert.CompoundFile(self.original)
        extra = compound.directory_entries[2]
        name = (ert.MODULE_STREAM + "\0").encode("utf-16le")
        extra.raw[:64] = name.ljust(64, b"\0")
        import struct
        struct.pack_into("<H", extra.raw, 64, len(name))
        self.template.write_bytes(compound.rebuild({}))
        with self.assertRaisesRegex(ert.ErtError, "ровно с одним"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_changed_unrelated_stream_and_directory_rejected(self):
        compound = ert.CompoundFile(self.original)
        data = compound.rebuild({3: b"changed contents"})
        with self.assertRaisesRegex(ert.ErtError, "посторонний поток"):
            api._verify_build(compound, 1, ert.extract_text(self.template).encode("cp1251"), data)
        compound.directory_entries[2].raw[80] ^= 1
        with self.assertRaisesRegex(ert.ErtError, "запись каталога"):
            api._verify_build(compound, 1, ert.extract_text(self.template).encode("cp1251"), self.original)

    def test_write_verify_and_publish_failures_leave_no_output(self):
        for target in ("os.fsync", "os.link", "harness77.artifacts._verify_build"):
            with self.subTest(target=target):
                with mock.patch(target, side_effect=OSError("injected failure")):
                    with self.assertRaises(OSError):
                        self.build()
                self.assert_unpublished()

    def test_disk_corruption_is_not_published(self):
        original_read = Path.read_bytes
        def read(path):
            data = original_read(path)
            return data + b"corruption" if path.name.startswith(".harness77-") else data
        with mock.patch.object(Path, "read_bytes", read):
            with self.assertRaisesRegex(ert.ErtError, "байты отличаются"):
                self.build()
        self.assert_unpublished()

    def test_changed_input_and_concurrent_destination_refused(self):
        original_unchanged = api._unchanged
        def change(inputs):
            self.source.write_text("changed", encoding="utf-8")
            original_unchanged(inputs)
        with mock.patch.object(api, "_unchanged", change):
            with self.assertRaisesRegex(ert.ErtError, "Вход изменился"):
                self.build()
        self.assert_unpublished()
        def race(inputs):
            original_unchanged(inputs)
            self.output.write_bytes(b"somebody else's output")
        with mock.patch.object(api, "_unchanged", race):
            with self.assertRaises(FileExistsError):
                self.build()
        self.assertEqual(self.output.read_bytes(), b"somebody else's output")

    def test_cleanup_failure_reports_path(self):
        with mock.patch.object(Path, "unlink", side_effect=PermissionError("cleanup denied")):
            with self.assertRaisesRegex(ert.ErtError, "Не удалён временный файл"):
                self.build()
        self.assertEqual(len(list(self.root.glob(".harness77-*"))), 1)

    def test_cli_foreign_cwd_success_and_failure(self):
        command = [sys.executable, "-m", "harness77", "build", "--template", str(self.template),
                   "--source", str(self.source), "--output", str(self.output)]
        result = subprocess.run(command, cwd=self.root, capture_output=True, timeout=30)
        self.assertEqual((result.returncode, result.stderr), (0, b""))
        self.assertEqual(json.loads(result.stdout)["status"], "passed")
        result = subprocess.run(command, cwd=self.root, capture_output=True, timeout=30)
        self.assertEqual((result.returncode, result.stdout), (2, b""))
        self.assertEqual(json.loads(result.stderr)["status"], "blocked")
