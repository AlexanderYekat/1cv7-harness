"""092: shipped payload integrity without importing Windows code or activating COM."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from harness77 import __version__, native_runtime77 as runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        names = json.loads((runtime.HERE / 'native_catalog77.json').read_text(encoding='utf-8'))['files']
        hashes = {}
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'qualified source')
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest = {'schema_version': 1, 'runtime_version': __version__, 'platform_version': '7.70.027', 'files': hashes}
        self.save()

    def save(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def inspect(self):
        return runtime.inspect_runtime('forms', root=self.root)

    def test_inspection_is_read_only_and_does_not_import_controller(self):
        before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        modules = set(sys.modules)
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('launch')):
            result = self.inspect()
        self.assertEqual(result['files_checked'], 33)
        self.assertEqual(result['runtime_version'], __version__)
        self.assertEqual(set(sys.modules), modules)
        self.assertEqual(before, {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.rglob('*') if p.is_file()})

    def test_missing_modified_and_unexpected_runtime_sources_are_refused(self):
        source = self.root / 'platform77/session77.py'
        source.unlink()
        with self.assertRaisesRegex(runtime.RuntimeUnavailable, 'missing or unexpected'):
            self.inspect()
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(runtime.RuntimeUnavailable, 'hash mismatch: platform77/session77.py'):
            self.inspect()
        source.write_bytes(b'qualified source')
        (self.root / 'forms/unshipped.py').write_bytes(b'extra')
        with self.assertRaisesRegex(runtime.RuntimeUnavailable, 'unexpected'):
            self.inspect()

    def test_manifest_version_schema_and_catalog_cannot_silently_change(self):
        for field, value in (('runtime_version', 'old'), ('schema_version', 77), ('platform_version', 'other'), ('files', {})):
            with self.subTest(field=field):
                original = self.manifest[field]
                self.manifest[field] = value
                self.save()
                with self.assertRaises(runtime.RuntimeUnavailable):
                    self.inspect()
                self.manifest[field] = original
        (self.root / 'manifest.json').write_text('[]', encoding='utf-8')
        with self.assertRaises(runtime.RuntimeUnavailable):
            self.inspect()

    def test_manifest_path_escape_and_malformed_hash_are_refused(self):
        self.manifest['files']['../outside.py'] = '0' * 64
        self.save()
        with self.assertRaisesRegex(runtime.RuntimeUnavailable, 'catalog'):
            self.inspect()
        del self.manifest['files']['../outside.py']
        self.manifest['files']['platform77/session77.py'] = True
        self.save()
        with self.assertRaisesRegex(runtime.RuntimeUnavailable, 'invalid native runtime hash'):
            self.inspect()

    def test_installer_bytecode_does_not_change_shipped_source_set(self):
        cache = self.root / 'forms/__pycache__'
        cache.mkdir()
        (cache / 'fixture77.cpython-313.pyc').write_bytes(b'installer generated')
        self.assertEqual(self.inspect()['files_checked'], 33)

    def test_launcher_selection_preserves_explicit_launcher_arguments(self):
        stand = types.SimpleNamespace(extra={'launcher': 'C:/custom/launcher.py'})
        self.assertEqual(runtime.launch_prefix(stand), [sys.executable, '-B', 'C:/custom/launcher.py'])
        stand.extra = {'runtime': 'forms'}
        self.assertEqual(runtime.launch_prefix(stand), [sys.executable, '-B', '-m', 'harness77.native_runtime77', '--adapter', 'forms'])


if __name__ == '__main__':
    unittest.main()
