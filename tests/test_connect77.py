"""099: project-only activation, fail-closed selection and preparation boundaries."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from harness77 import __version__, connect77 as connect, local_launcher77 as launch, mcp77


class ConnectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='h77-connect-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'прикладной проект'
        self.project.mkdir()
        (self.project / 'project.toml').write_text('[project]\nid="application"\n', encoding='utf-8')
        (self.project / 'stand.toml').write_text('[stand]\nbackend="simulation"\n[stand.base]\npath="base"\n', encoding='utf-8')
        self.wheel = self.root / f'harness77-{__version__}-py3-none-any.whl'
        with zipfile.ZipFile(self.wheel, 'w') as wheel:
            wheel.writestr('harness77/__init__.py', f'__version__="{__version__}"\n')
            wheel.writestr(f'harness77-{__version__}.dist-info/METADATA',
                           f'Metadata-Version: 2.1\r\nName: harness77\r\nVersion: {__version__}\r\n')

    def attach(self, **options):
        return connect.connect(self.project, wheel=self.wheel, **options)

    def local(self):
        return launch.Local(self.project / '.harness77/config.json')

    def config(self, **changes):
        path = self.project / '.harness77/config.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data.update(changes)
        path.write_text(json.dumps(data), encoding='utf-8')

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes()
                for p in self.project.rglob('*') if p.is_file()}

    def test_connect_preserves_agents_profiles_marker_and_repeat_is_exact(self):
        (self.project / 'AGENTS.md').write_bytes(b'# Existing\r\nKeep instructions.\r\n')
        (self.project / 'harness77.txt').write_bytes(b'not executable content')
        original = self.snapshot()
        self.assertTrue(self.attach(bundle=True)['changed'])
        for name, content in original.items():
            if name == 'AGENTS.md':
                self.assertTrue((self.project / name).read_bytes().startswith(content))
            else:
                self.assertEqual((self.project / name).read_bytes(), content)
        before = self.snapshot()
        self.assertFalse(self.attach(bundle=True)['changed'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual((self.project / 'AGENTS.md').read_text(encoding='utf-8').count(connect.START), 1)

    def test_conflicting_files_fail_before_any_write(self):
        home = self.project / '.harness77'
        home.mkdir()
        (home / 'config.json').write_bytes(b'foreign')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.attach()
        self.assertEqual(before, self.snapshot())

    def test_edited_rule_and_configuration_are_never_overwritten(self):
        self.attach()
        self.config(user_setting='keep')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.attach()
        self.assertEqual(before, self.snapshot())
        (self.project / 'AGENTS.md').write_text(connect.START + '\ncustom\n' + connect.END, encoding='utf-8')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.attach()
        self.assertEqual(before, self.snapshot())

    def test_publish_error_rolls_back_every_owned_file(self):
        agents = self.project / 'AGENTS.md'
        agents.write_bytes(b'# original\r\n')
        before = self.snapshot()
        with patch('harness77.project_init77._rename_new', side_effect=OSError('injected')), self.assertRaises(OSError):
            self.attach(bundle=True)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.project.glob('.harness77*')))

    def test_agents_replace_error_preserves_original_bytes(self):
        (self.project / 'AGENTS.md').write_bytes(b'original instructions')
        before = self.snapshot()
        with patch.object(connect.os, 'replace', side_effect=OSError('injected atomic replace')), self.assertRaises(OSError):
            self.attach()
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.project.glob('.harness77*')))

    def test_download_errors_are_specific_and_do_not_echo_secrets(self):
        for stderr, reason in [(b'THESE PACKAGES DO NOT MATCH THE HASHES secret', 'SHA-256'),
                               (b'network error secret', 'Cannot download pinned wheel')]:
            response = subprocess.CompletedProcess([], 1, stdout=b'', stderr=stderr)
            with patch.object(launch.subprocess, 'run', return_value=response):
                with self.assertRaisesRegex(launch.ActivationError, reason) as caught:
                    launch.command([sys.executable, '-m', 'pip', 'download', 'https://example.org/file.whl'])
            self.assertNotIn('secret', str(caught.exception))

    def test_metadata_version_mismatch_and_supplied_bad_hash(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.attach(sha256='0' * 64)
        with zipfile.ZipFile(self.wheel, 'w') as wheel:
            wheel.writestr('harness77/__init__.py', '')
            wheel.writestr(f'harness77-{__version__}.dist-info/METADATA', 'Name: harness77\nVersion: 9.9.9\n')
        with self.assertRaisesRegex(ValueError, 'version differs'):
            self.attach()
        self.assertFalse((self.project / '.harness77').exists())

    def test_missing_and_ambiguous_profiles_refuse_without_writes(self):
        (self.project / 'other.toml').write_text('[stand]\nbackend="native"', encoding='utf-8')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Ambiguous stand'):
            self.attach()
        self.assertEqual(before, self.snapshot())
        self.attach(stand=self.project / 'stand.toml')

    def test_standalone_disabled_from_foreign_cwd_without_config_or_package(self):
        self.attach()
        (self.project / 'harness77.txt').unlink()
        (self.project / '.harness77/config.json').unlink()
        script = self.project / '.harness77/launch.py'
        for operation, code in [('status', 0), ('prepare', 0), ('run', 2), ('mcp', 2)]:
            response = subprocess.run([sys.executable, '-I', script, operation, '--format', 'json'],
                                      cwd=self.root, capture_output=True, timeout=30)
            self.assertEqual(response.returncode, code, response.stderr)
            self.assertEqual(json.loads(response.stdout)['status'], 'disabled')
        self.assertFalse((self.project / '.harness77/cache').exists())

    def test_status_does_not_prepare_and_paths_resolve_from_config(self):
        self.attach(bundle=True)
        local = self.local()
        with patch.object(local, 'prepare', side_effect=AssertionError('must not install')):
            result = local.status()
        self.assertEqual(result['status'], 'unprepared')
        self.assertEqual(result['source'], 'bundled-wheel')
        self.assertEqual(result['base'], str(self.project / 'base'))
        self.assertFalse(local.cache.exists())

    def test_missing_explicit_wheel_does_not_fall_back(self):
        self.attach()
        self.config(url='https://example.org/' + self.wheel.name)
        self.wheel.unlink()
        with self.assertRaisesRegex(ValueError, 'Explicit wheel path'):
            self.local().status(prepare=True)

    def test_corrupt_wheel_and_wrong_version_do_not_fall_back(self):
        self.attach()
        self.wheel.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.local().status(prepare=True)
        self.config(sha256=launch.digest(self.wheel))
        with self.assertRaises(zipfile.BadZipFile):
            self.local().status()

    def test_version_mismatch_before_writing(self):
        with self.assertRaisesRegex(ValueError, 'Expected wheel|version'):
            connect.connect(self.project, wheel=self.wheel, version='9.9.9')
        self.assertFalse((self.project / '.harness77').exists())

    def test_pip_output_may_use_windows_code_page(self):
        response = subprocess.CompletedProcess([], 0, stdout=b'pip: \xff', stderr=b'')
        with patch.object(launch.subprocess, 'run', return_value=response):
            self.assertIn('pip:', launch.command([sys.executable, '-m', 'pip', '--version']))

    def test_corrupt_cache_receipt_is_not_ready(self):
        self.attach()
        local = self.local()
        local.load()
        local.cache.mkdir(parents=True)
        (local.cache / 'ready.json').write_bytes(b'broken json')
        with self.assertRaisesRegex(ValueError, 'Damaged cache receipt'):
            local.cached({})

    def test_optional_bundle_missing_allows_download_but_corruption_refuses(self):
        self.attach(bundle=True, url='https://example.org/' + self.wheel.name)
        local = self.local()
        local.load()
        bundle = local.path(local.data['bundled_wheel'])
        bundle.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            local.select()
        bundle.unlink()
        self.assertEqual(local.status()['source'], 'download')

    def test_partial_cache_and_parallel_prepare_cannot_be_ready(self):
        self.attach()
        local = self.local()
        local.load()
        local.cache.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'Incomplete cache'):
            local.status(prepare=True)
        local.cache.rmdir()
        lock = local.cache.parent / (local.cache.name + '.lock')
        lock.write_bytes(b'competing process')
        with patch.object(launch, 'command', side_effect=AssertionError('must not install')):
            with self.assertRaisesRegex(ValueError, 'Preparation in progress'):
                local.prepare(self.wheel)
        self.assertEqual(lock.read_bytes(), b'competing process')
        self.assertFalse(local.cache.exists())

    def test_failed_install_removes_only_its_partial_cache_and_lock(self):
        self.attach()
        local = self.local()
        local.load()
        other = local.cache.parent / 'foreign'
        other.mkdir(parents=True)
        (other / 'keep').write_bytes(b'keep')
        def fail(argv, **kwargs):
            if 'venv' in argv:
                raise launch.ActivationError('injected venv failure')
            return ''
        with patch.object(launch, 'command', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'injected'):
                local.status(prepare=True)
        self.assertFalse(local.cache.exists())
        self.assertFalse(list(local.cache.parent.glob('*.lock')))
        self.assertEqual((other / 'keep').read_bytes(), b'keep')

    def test_external_install_integrity_and_version_are_checked(self):
        self.attach()
        for field, changed in [('version', '0.0.0'), ('files', {'malicious.py': 'bad'})]:
            installed = {'version': __version__, 'files': {'a.py': 'hash'}}
            installed[field] = changed
            with patch.object(launch, 'inspect', return_value=installed):
                with self.assertRaises(launch.ActivationError):
                    launch.validate_install(sys.executable, __version__, {'a.py': 'hash'})

    def test_mcp_live_marker_gate_preserves_service_protocol(self):
        self.attach()
        writer = io.BytesIO()
        with patch.dict(os.environ, HARNESS77_LOCAL_CONFIG=str(self.local().config_path)):
            server = mcp77.Server(io.BytesIO(), writer, cwd=self.project, log=io.StringIO())
        marker = self.project / 'harness77.txt'
        marker.unlink()
        with patch('harness77.mcp77.subprocess.Popen', side_effect=AssertionError('no harness child')):
            for identifier, method, params in [(1, 'initialize', {}), (2, 'ping', {}),
                (3, 'tools/list', {}), (4, 'tools/call', {'name': 'suite', 'arguments': {}})]:
                server._handle(json.dumps({'id': identifier, 'method': method, 'params': params}).encode())
        replies = [json.loads(line) for line in writer.getvalue().splitlines()]
        self.assertEqual(replies[1]['result'], {})
        self.assertTrue(replies[2]['result']['tools'])
        self.assertTrue(replies[3]['result']['isError'])
        self.assertIn('disabled', replies[3]['result']['content'][0]['text'])
        marker.touch()
        with patch.object(server, '_run') as run:
            server._handle(json.dumps({'id': 5, 'method': 'tools/call', 'params': {'name': 'run'}}).encode())
            for worker in server.workers:
                worker.join(timeout=10)
        call = run.call_args.args[0]
        self.assertEqual(call.arguments['project'], str(self.project / 'project.toml'))
        self.assertEqual(call.arguments['stand'], str(self.project / 'stand.toml'))


if __name__ == '__main__':
    unittest.main()
