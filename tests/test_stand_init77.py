"""093: qualification, read-only inputs and atomic, non-overwriting profiles."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from harness77 import artifacts, cli, stand_init77 as init
from harness77.config77 import load_stand


def pe(machine=0x14c, suffix=b''):
    header = bytearray(64)
    header[:2] = b'MZ'
    header[60:64] = (64).to_bytes(4, 'little')
    return bytes(header) + b'PE\0\0' + machine.to_bytes(2, 'little') + suffix


class StandInitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='h77-init-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.base = self.root / 'исходная база'
        self.base.mkdir()
        self.target = self.root / 'copy'
        self.output = self.root / 'новый профиль.toml'
        self.paths = {}
        for role in ('exe', 'cdb', 'helper', 'identity'):
            path = self.root / (role + '.bin')
            path.write_bytes(pe(suffix=role.encode()))
            self.paths[role] = path
        for name in ('1Cv7.MD', '1Cv7.DD', '1SUSERS.DBF', '1SJOURN.DBF'):
            (self.base / name).write_bytes(b'database')
        for name in ('1CPP.dll', 'FormEx.dll'):
            (self.base / name).write_bytes(pe(suffix=name.encode()))
        (self.base / 'Временные').mkdir()
        self.policy = {role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in self.paths.items() if role != 'cdb'}
        self.policy.update({name: hashlib.sha256((self.base / name).read_bytes()).hexdigest()
                            for name in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')})
        self.info = {'adapter': 'headless', 'runtime_version': 'test', 'platform_version': '7.70.027'}
        self.observer = Mock()
        self.observer.registered.return_value = True
        for item in (patch.object(init.runtime, 'inspect_runtime', return_value=self.info),
                     patch.object(init, '_qualification', return_value=self.policy)):
            item.start()
            self.addCleanup(item.stop)

    def call(self, **overrides):
        kwargs = dict(output=self.output, name='Тест "#"', adapter='headless', base=self.base,
                      copy_path=self.target, user='ВВВ "#"', windows=self.observer, **self.paths)
        kwargs.update(overrides)
        return init.initialize(**kwargs)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes())
                for p in self.root.rglob('*') if p.is_file()}

    def test_profile_round_trip_absolute_paths_and_observation_only(self):
        guard = self.target.with_name(self.target.name + '.lock.guard')
        guard.write_bytes(b'idle guard')
        before = self.snapshot()
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no launch')):
            result = self.call(copy_exclude=['Временные', 'Временные'])
        self.assertEqual(result['status'], 'created')
        self.assertFalse(result['launch_performed'])
        self.assertFalse(result['platform_checked'])
        stand = load_stand(self.output)
        self.assertEqual(stand.name, 'Тест "#"')
        self.assertEqual(stand.user, 'ВВВ "#"')
        self.assertEqual(stand.base, self.base)
        self.assertEqual(stand.copy_path, self.target)
        self.assertEqual(stand.extra, {'runtime': 'headless'})
        self.assertEqual(stand.copy_exclude, ('Временные',))
        self.assertEqual(stand.tool_hashes['identity'], self.policy['identity'])
        self.assertEqual(stand.tool_hashes['cdb'], hashlib.sha256(self.paths['cdb'].read_bytes()).hexdigest())
        self.assertEqual(result['profile']['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertNotIn(b'\r', self.output.read_bytes())
        after = self.snapshot()
        after.pop(self.output.name)
        self.assertEqual(before, after)
        self.assertEqual(len(self.observer.registered.call_args_list), 2)

    def test_existing_profile_file_and_directory_are_never_replaced(self):
        self.output.write_bytes(b'owned by someone else')
        before = self.snapshot()
        with self.assertRaisesRegex(init.ErtError, 'существует'):
            self.call()
        self.assertEqual(before, self.snapshot())
        self.output.unlink()
        self.output.mkdir()
        with self.assertRaises(init.ErtError):
            self.call()
        self.assertTrue(self.output.is_dir())

    def test_wrong_pe_and_nonqualified_hash_leave_no_profile(self):
        for role in ('cdb', 'helper', 'identity', 'exe'):
            path = self.paths[role]
            original = path.read_bytes()
            path.write_bytes(pe(machine=0x8664))
            with self.subTest(role=role), self.assertRaisesRegex(init.StandInitError, 'PE x86'):
                self.call()
            self.assertFalse(self.output.exists())
            path.write_bytes(original)
        self.paths['helper'].write_bytes(pe(suffix=b'other valid x86'))
        with self.assertRaisesRegex(init.StandInitError, 'helper: SHA-256'):
            self.call()
        self.assertFalse(self.output.exists())

    def test_changed_configuration_is_not_silently_blessed(self):
        (self.base / '1Cv7.MD').write_bytes(b'not qualified')
        with self.assertRaisesRegex(init.StandInitError, '1Cv7.MD: SHA-256'):
            self.call()
        self.assertFalse(self.output.exists())

    def test_unregistered_occupied_and_locked_copy_paths_are_preserved(self):
        self.observer.registered.return_value = False
        with self.assertRaisesRegex(init.StandInitError, 'не зарегистрирован'):
            self.call()
        self.observer.registered.return_value = True
        self.target.mkdir()
        with self.assertRaisesRegex(init.StandInitError, 'уже существуют'):
            self.call()
        self.target.rmdir()
        lock = self.target.with_name(self.target.name + '.lock')
        lock.write_bytes(b'foreign lock')
        before = self.snapshot()
        with self.assertRaisesRegex(init.StandInitError, 'замок'):
            self.call()
        self.assertEqual(before, self.snapshot())

    def test_overlaps_bad_excludes_and_missing_input_create_nothing(self):
        for kwargs in ({'copy_path': self.base / 'copy'}, {'output': self.base / 'stand.toml'},
                       {'output': self.target / 'stand.toml'}, {'copy_exclude': ['../x']},
                       {'copy_exclude': ['1Cv7.MD']}, {'helper': self.root / 'absent.dll'}):
            with self.subTest(kwargs=kwargs), self.assertRaises((OSError, ValueError)):
                self.call(**kwargs)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.target.exists())

    def test_late_destination_race_does_not_overwrite_foreign_file(self):
        link = os.link
        def competing_writer(source, destination):
            Path(destination).write_bytes(b'concurrent writer')
            return link(source, destination)
        with patch.object(artifacts.os, 'link', side_effect=competing_writer), self.assertRaises(FileExistsError):
            self.call()
        self.assertEqual(self.output.read_bytes(), b'concurrent writer')
        self.assertFalse(list(self.root.glob('.harness77-*')))

    def test_source_change_during_staging_is_refused_and_temporary_is_removed(self):
        publish = init._publish
        def changed(*args):
            self.paths['cdb'].write_bytes(pe(suffix=b'changed during creation'))
            return publish(*args)
        with patch.object(init, '_publish', side_effect=changed), self.assertRaisesRegex(init.StandInitError, 'cdb: файл изменился'):
            self.call()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.harness77-*')))

    def test_no_copy_fallback_when_atomic_publication_is_not_supported(self):
        with patch.object(artifacts.os, 'link', side_effect=OSError('not supported')), self.assertRaises(OSError):
            self.call()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.harness77-*')))

    def test_runtime_damage_and_registry_denial_create_no_profile(self):
        with patch.object(init.runtime, 'inspect_runtime', side_effect=ValueError('runtime damaged')), self.assertRaises(ValueError):
            self.call()
        self.observer.registered.side_effect = PermissionError('registry denied')
        with self.assertRaises(PermissionError):
            self.call()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.harness77-*')))

    def test_runtime_update_during_staging_is_refused(self):
        with patch.object(init.runtime, 'inspect_runtime', side_effect=[self.info, {**self.info, 'runtime_version': 'changed'}]), \
                self.assertRaisesRegex(init.StandInitError, 'Runtime изменился'):
            self.call()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.harness77-*')))

    def test_cli_dispatch_json_success_and_blocked_result(self):
        args = ['stand-init', '--output', str(self.output), '--name', 'test', '--runtime', 'forms',
                '--base', str(self.base), '--copy-path', str(self.target), '--user', 'ВВВ', '--format', 'json']
        for role, path in self.paths.items():
            args += ['--' + role, str(path)]
        stdout = io.StringIO()
        with patch.object(init, '_inspector', return_value=self.observer), contextlib.redirect_stdout(stdout):
            result = cli.main(args)
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'created')
        self.assertEqual(load_stand(self.output).extra['runtime'], 'forms')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = cli.main(args)
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'blocked')

    def test_static_policy_reader_never_executes_native_module(self):
        path = self.root / 'policy.py'
        path.write_text('PINNED = {"exe": "hash"}\nraise RuntimeError("must not execute")\n', encoding='utf-8')
        self.assertEqual(init._literal(path, 'PINNED'), {'exe': 'hash'})
        path.write_text('PINNED = missing_function()\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            init._literal(path, 'PINNED')


if __name__ == '__main__':
    unittest.main()
