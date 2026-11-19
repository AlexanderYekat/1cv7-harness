"""Refresh generated fixtures, protect edits and keep readers consistent."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness77 import cli, ert_module as ert, fixture_refresh77 as refresh, project_init77
from harness77.config77 import FixtureFileError, load_project
from harness77.fixture_render77 import render
from test_ert_dialog import DIALOG, make_ert


class FixtureRefreshTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fixture114-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.directory = self.root / 'fixture project'
        self.profile = self.directory / 'project.toml'
        template = self.root / 'template.ert'
        template.write_bytes(make_ert(ert.encode_dialog(DIALOG)))
        source = self.root / 'source.1s'
        source.write_text('Процедура ПриОткрытии()\nКонецПроцедуры\n', encoding='utf-8')
        scenario = self.root / 'scenario.json'
        (self.root / 'steps.json').write_text('[{"rows":2}]', encoding='utf-8')
        (self.root / 'expected.json').write_text('{"service_type":1}', encoding='utf-8')
        scenario.write_text(json.dumps({'parameters': {'form_object': 'Документ.ОказаниеУслуг',
                                                       'steps_file': 'steps.json'}, 'tests': [
            {'name': 'verify test', 'command': 'verify', 'expect': 'passed', 'expect_json_file': 'expected.json'}
        ]}, ensure_ascii=False), encoding='utf-8')
        project_init77.initialize(directory=self.directory, project_id='fixture114', template=template,
            runtime='forms', source=source, scenario=scenario, fixture_kind='services',
            open_timeout_s=20, calculation_timeout_s=10, cancel_timeout_s=4, shutdown_timeout_s=5, total_timeout_s=45)
        self.snapshot = self.directory / refresh.FIXTURE_RECIPE_FILE
        self.original = self.snapshot.read_bytes()
        self.external = self.root / 'new.toml'
        self.external.write_bytes(self.original.replace(b'service_type = 1', b'service_type = 2').replace(
            'Harness77 услуга 110'.encode(), 'Harness77 новая услуга'.encode()))
        self.baseline = self.bytes_by_name()
        self.lock = self.directory / refresh.FIXTURE_REFRESH_LOCK

    def bytes_by_name(self):
        return {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}

    def invoke(self):
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(['fixture-refresh', '--project', str(self.profile), '--recipe', str(self.external), '--format', 'json'])
        return code, json.loads(out.getvalue())

    def test_updates_both_generated_bodies_preserving_profile_and_expected_bytes(self):
        code, report = self.invoke()
        self.assertEqual((code, report['status']), (0, 'updated'))
        self.assertEqual(report['changed'], list(refresh.FILES))
        now = self.bytes_by_name()
        self.assertEqual(set(now), set(self.baseline))
        self.assertEqual(now[refresh.FIXTURE_RECIPE_FILE], self.external.read_bytes())
        for name, payload in render('services', self.external.read_bytes()).items():
            self.assertEqual(now[name], payload)
        for name in set(now) - set(refresh.FILES):
            self.assertEqual(now[name], self.baseline[name])
        self.assertEqual(self.invoke()[1]['status'], 'unchanged')
        self.assertEqual(self.bytes_by_name(), now)
        self.assertFalse(self.lock.exists())

    def test_manual_edit_of_each_body_leaves_all_files_intact(self):
        for name in ('fixture.1s', 'reader.1s'):
            with self.subTest(file=name):
                target = self.directory / name
                target.write_bytes(self.baseline[name] + b'\n// manual')
                previous = self.bytes_by_name()
                code, report = self.invoke()
                self.assertEqual((code, report['status'], report['conflicts']), (2, 'blocked', [name]))
                self.assertEqual(self.bytes_by_name(), previous)
                self.assertFalse(self.lock.exists())
                target.write_bytes(self.baseline[name])

    def test_failure_replacing_second_body_rolls_back_first_one(self):
        replace = Path.replace

        def broken(src, dst):
            if src.name == 'new-reader.1s':
                raise OSError('reader is held')
            return replace(src, dst)

        with patch.object(Path, 'replace', broken):
            code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn('reader is held', report['reason'])
        self.assertEqual(self.bytes_by_name(), self.baseline)
        self.assertFalse(self.lock.exists())

    def test_unrecoverable_rollback_preserves_backup_and_blocks_run(self):
        replace = Path.replace

        def broken(src, dst):
            if src.name in ('new-reader.1s', 'old-fixture.1s'):
                raise OSError('target is held')
            return replace(src, dst)

        with patch.object(Path, 'replace', broken):
            code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn('Не удалось откатить', report['reason'])
        self.assertEqual((self.lock / 'old-fixture.1s').read_bytes(), self.baseline['fixture.1s'])
        with self.assertRaisesRegex(FixtureFileError, 'не завершено'):
            load_project(self.profile)

    def test_loader_refuses_a_refresh_completed_between_two_fixture_reads(self):
        read = Path.read_bytes
        refreshed = False

        def read_then_refresh(path):
            nonlocal refreshed
            previous = read(path)
            if path == self.directory / 'fixture.1s' and not refreshed:
                refreshed = True
                refresh.refresh(project=self.profile, recipe=self.external)
            return previous

        with patch.object(Path, 'read_bytes', read_then_refresh):
            with self.assertRaisesRegex(FixtureFileError, 'изменился во время чтения'):
                load_project(self.profile)
        self.assertTrue(refreshed)
        self.assertFalse(self.lock.exists())
        self.assertEqual(len(load_project(self.profile).fixture_files), 2)

    def test_snapshot_is_not_a_new_recipe_source_and_bad_recipe_preserves_files(self):
        with self.assertRaisesRegex(ValueError, 'нужен отдельный файл'):
            refresh.refresh(project=self.profile, recipe=self.snapshot)
        self.external.write_bytes(b'[broken')
        self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(self.bytes_by_name(), self.baseline)
        self.assertFalse(self.lock.exists())


if __name__ == '__main__':
    unittest.main()
