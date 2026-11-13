"""094: complete new projects, intact inputs and no-replace directory publication."""
import contextlib
import ctypes
import errno
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from harness77 import artifacts, cli, ert_module as ert, project_init77 as init
from harness77.config77 import load_project
from test_ert_dialog import make_ert, DIALOG

LIMITS = dict(open_timeout_s=10, calculation_timeout_s=20, cancel_timeout_s=3,
              shutdown_timeout_s=4, total_timeout_s=50)


class ProjectInitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='h77-project-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.template = self.root / 'исходный шаблон.ert'
        self.original = make_ert(ert.encode_dialog(DIALOG))
        self.template.write_bytes(self.original)
        self.output = self.root / 'новый проект'

    def call(self, **overrides):
        options = dict(directory=self.output, project_id='hello-42', template=self.template, **LIMITS)
        options.update(overrides)
        return init.initialize(**options)

    def unpublished(self):
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob(init.PREFIX + '*')))

    def test_complete_project_round_trip_and_build_without_touching_template(self):
        before = (self.template.stat().st_mtime_ns, self.template.read_bytes())
        result = self.call()
        self.assertEqual(result['status'], 'created')
        self.assertFalse(result['launch_performed'])
        self.assertFalse(result['platform_checked'])
        self.assertEqual(set(p.name for p in self.output.iterdir()), {'project.toml', 'module.1s', 'template.ert', 'configuration'})
        self.assertEqual(list((self.output / 'configuration').iterdir()), [])
        project = load_project(self.output / 'project.toml')
        self.assertEqual(project.project_id, 'hello-42')
        self.assertEqual(project.template, self.output / 'template.ert')
        self.assertEqual(project.source, self.output / 'module.1s')
        self.assertEqual(project.configuration, self.output / 'configuration')
        self.assertEqual(project.deadlines_raw, LIMITS)
        self.assertEqual(project.commands(), ['execute'])
        self.assertEqual(project.tests[0]['expect_value'], '42')
        for name, evidence in result['files'].items():
            self.assertEqual(artifacts.sha256((self.output / name).read_bytes()), evidence['sha256'])
        built = artifacts.build(project.template, project.source, self.root / 'built.ert', encoding=project.encoding)
        self.assertTrue(built['verification']['other_streams'])
        self.assertEqual((self.output / 'template.ert').read_bytes(), self.original)
        self.assertEqual(before, (self.template.stat().st_mtime_ns, self.template.read_bytes()))
        self.assertFalse(list(self.root.glob(init.PREFIX + '*')))

    def test_existing_empty_or_nonempty_directory_and_file_are_preserved(self):
        self.output.mkdir()
        with self.assertRaises(init.ErtError):
            self.call()
        self.assertEqual(list(self.output.iterdir()), [])
        (self.output / 'foreign').write_bytes(b'preserve')
        with self.assertRaises(init.ErtError):
            self.call()
        self.assertEqual((self.output / 'foreign').read_bytes(), b'preserve')
        target = self.root / 'foreign-file'
        target.write_bytes(b'file')
        with self.assertRaises(init.ErtError):
            self.call(directory=target)
        self.assertEqual(target.read_bytes(), b'file')

    def test_late_race_with_an_empty_destination_is_not_overwritten(self):
        rename = init._rename_new
        def compete(source, destination):
            Path(destination).mkdir()
            return rename(source, destination)
        with patch.object(init, '_rename_new', side_effect=compete), self.assertRaises(FileExistsError):
            self.call()
        self.assertTrue(self.output.is_dir())
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertFalse(list(self.root.glob(init.PREFIX + '*')))

    def test_write_failure_cleans_only_our_staging_directory(self):
        write = init._write
        def fail(path, data):
            if path.name == 'module.1s':
                raise OSError('controlled write failure')
            return write(path, data)
        with patch.object(init, '_write', side_effect=fail), self.assertRaises(OSError):
            self.call()
        self.unpublished()
        self.assertEqual(self.template.read_bytes(), self.original)

    def test_disk_readback_corruption_is_refused_before_publication(self):
        write = init._write
        def corrupt(path, data):
            write(path, data)
            if path.name == 'module.1s':
                path.write_bytes(b'corrupt')
        with patch.object(init, '_write', side_effect=corrupt), self.assertRaisesRegex(init.ErtError, 'Перечитанные'):
            self.call()
        self.unpublished()

    def test_source_change_before_publication_is_refused(self):
        load = init.load_project
        def changed(path):
            project = load(path)
            self.template.write_bytes(b'concurrent change')
            return project
        with patch.object(init, 'load_project', side_effect=changed), self.assertRaisesRegex(init.ErtError, 'Шаблон изменился'):
            self.call()
        self.unpublished()

    def test_invalid_or_broken_compressed_template_creates_nothing(self):
        for contents in (b'not an ERT', self.original[:512],
                         ert.CompoundFile(self.original).rebuild({1: b'broken compressed module'})):
            self.template.write_bytes(contents)
            with self.subTest(size=len(contents)), self.assertRaises(init.ErtError):
                self.call()
            self.unpublished()

    def test_deadlines_must_be_explicit_finite_positive_and_consistent(self):
        for changes in ({'open_timeout_s': 0}, {'calculation_timeout_s': float('nan')},
                        {'total_timeout_s': 1}, {'cancel_timeout_s': True}, {'shutdown_timeout_s': float('inf')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call(**changes)
            self.unpublished()

    def test_project_id_cannot_escape_build_directory_or_use_device_names(self):
        for value in ('../other', 'C:/other', 'CON', 'aux.anything', 'id.', 'русский', '', 'x' * 65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.call(project_id=value)
            self.unpublished()

    def test_no_fallback_copy_when_atomic_rename_is_unavailable(self):
        with patch.object(init, '_rename_new', side_effect=OSError('unsupported')), self.assertRaises(OSError):
            self.call()
        self.unpublished()

    def test_cli_json_text_and_required_deadlines(self):
        command = ['project-init', '--directory', str(self.output), '--id', 'cli', '--template', str(self.template)]
        for key, value in LIMITS.items():
            command += ['--' + key.replace('_', '-'), str(value)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(init, '_rename_new', wraps=init._rename_new) as rename:
            self.assertEqual(cli.main([*command, '--format', 'json']), 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'created')
        rename.assert_called_once()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main([*command, '--format', 'json']), 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'blocked')
        command[2] = str(self.root / 'text-project')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(command), 0)
        self.assertIn('project-init: создан', output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cli.main(command[:-2])
        self.assertEqual(raised.exception.code, 2)

    def test_linux_publication_uses_noreplace_and_propagates_errno(self):
        function = Mock(return_value=0)
        library = types.SimpleNamespace(renameat2=function)
        with patch.object(init.os, 'name', 'posix'), patch.object(init.sys, 'platform', 'linux'), \
                patch.object(init.ctypes, 'CDLL', return_value=library):
            init._rename_new('source', 'destination')
            function.assert_called_once_with(-100, os.fsencode('source'), -100, os.fsencode('destination'), 1)
            ctypes.set_errno(errno.EEXIST)
            function.return_value = -1
            with self.assertRaises(OSError) as raised:
                init._rename_new('source', 'destination')
            self.assertEqual(raised.exception.errno, errno.EEXIST)

    def forms(self, **overrides):
        source = self.root / 'форма.1s'
        source.write_text('// Прикладной модуль\n', encoding='utf-8')
        scenario = self.root / 'сценарий.json'
        platform = {'parameters': {'form_object': 'Документ.ГотоваяПродукция',
                                   'steps': [{'cell': 'Количество', 'text': '3', 'row': 1}],
                                   'fixture_verify': 'Возврат "{}";'},
                    'tests': [{'name': 'данные', 'command': 'verify', 'expect': 'passed',
                               'expect_json': '{"amount":"30"}', 'json_labels': {'/amount': 'Сумма'}}]}
        scenario.write_text(json.dumps(platform, ensure_ascii=False), encoding='utf-8')
        options = dict(runtime='forms', source=source, scenario=scenario)
        options.update(overrides)
        return options, platform

    def test_forms_preserves_inputs_and_structured_contract_without_profile_edits(self):
        options, platform = self.forms()
        originals = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.template, options['source'], options['scenario'])}
        result = self.call(**options)
        self.assertEqual(result['runtime'], 'forms')
        self.assertFalse(result['launch_performed'])
        self.assertEqual(set(result['files']), {'project.toml', 'module.1s', 'template.ert', 'scenario.json'})
        profile = self.output / 'project.toml'
        self.assertEqual(init.tomllib.loads(profile.read_text(encoding='utf-8'))['platform'], platform)
        project = load_project(profile)
        self.assertEqual(project.parameters, platform['parameters'])
        self.assertEqual(project.tests[0]['expect_json'], platform['tests'][0]['expect_json'])
        self.assertEqual(project.tests[0]['json_labels'], {'/amount': 'Сумма'})
        self.assertEqual(project.commands(), ['verify'])
        self.assertEqual(project.deadlines_raw, LIMITS)
        self.assertEqual((self.output / 'module.1s').read_bytes(), options['source'].read_bytes())
        self.assertEqual((self.output / 'scenario.json').read_bytes(), options['scenario'].read_bytes())
        built = artifacts.build(project.template, project.source, self.root / 'forms.ert', encoding=project.encoding)
        self.assertTrue(built['verification']['other_streams'])
        for path, before in originals.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual({row['path'] for row in result['inputs']}, {str(p) for p in originals})

    def test_forms_rejects_ambiguous_or_lossy_scenarios_and_cleans_staging(self):
        options, platform = self.forms()
        invalid = [b'{', b'[]', b'{"parameters":{},"tests":[]}',
                   b'{"parameters":{},"parameters":{},"tests":[]}',
                   b'{"parameters":{"x":NaN},"tests":[]}',
                   json.dumps(dict(platform, extra=True)).encode(),
                   json.dumps(dict(platform, parameters={'x': None})).encode()]
        for patch_test in ({'expect_json': '{'}, {'expect_value': '30'}, {'expect': 'unknown'},
                           {'unexpected': True}, {'name': 123}, {'expect_value': 30}):
            changed = json.loads(json.dumps(platform))
            changed['tests'][0].update(patch_test)
            invalid.append(json.dumps(changed).encode())
        changed = json.loads(json.dumps(platform))
        changed['tests'] *= 2
        invalid.append(json.dumps(changed).encode())
        for raw in invalid:
            options['scenario'].write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.call(**options)
            self.unpublished()

    def test_forms_arguments_encoding_and_input_changes_fail_without_publication(self):
        options, _ = self.forms()
        for changes in ({'source': None}, {'scenario': None}, {'runtime': 'headless'}, {'runtime': 'other'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call(**dict(options, **changes))
            self.unpublished()
        for raw in (b'', b'\xff', '// emoji 😀'.encode('utf-8')):
            options['source'].write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.call(**options)
            self.unpublished()
        options, _ = self.forms()
        load = init.load_project
        for role in ('source', 'scenario'):
            options, _ = self.forms()
            def changed(path):
                project = load(path)
                options[role].write_bytes(b'concurrent change')
                return project
            with patch.object(init, 'load_project', side_effect=changed), self.assertRaisesRegex(init.ErtError, 'вход изменился'):
                self.call(**options)
            self.unpublished()

    def test_forms_cli_json_and_text_use_supplied_module_and_scenario(self):
        options, _ = self.forms()
        command = ['project-init', '--directory', str(self.output), '--id', 'forms', '--runtime', 'forms',
                   '--template', str(self.template), '--source', str(options['source']), '--scenario', str(options['scenario'])]
        for key, value in LIMITS.items():
            command += ['--' + key.replace('_', '-'), str(value)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main([*command, '--format', 'json']), 0)
        self.assertEqual(json.loads(output.getvalue())['runtime'], 'forms')
        command[2] = str(self.root / 'text-forms')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(command), 0)
        self.assertIn('forms-сценарий', output.getvalue())


if __name__ == '__main__':
    unittest.main()
