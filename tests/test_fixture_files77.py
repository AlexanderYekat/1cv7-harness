"""102: current file inputs, immutable execution snapshots and inline compatibility."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness77.config77 import ConfigError, FixtureFileError, load_project, load_stand, resolve_deadlines
from harness77 import project_init77, run77
from stage4_fixtures import write_project, write_sim_stand, base_scenario
from test_mcp77 import Client, cli


class FixtureFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='h77-file-fixtures-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.profile = write_project(self.root / 'проект с пробелами')
        self.setup = self.profile.parent / 'подготовка.1s'
        self.reader = self.profile.parent / 'чтение.1s'
        self.setup.write_bytes('Возврат "подготовлено";\r\n'.encode('utf-8'))
        self.reader.write_bytes('Возврат "проверено";\n'.encode('utf-8'))
        self.original = self.profile.read_text(encoding='utf-8').replace('schema_version = 1', 'schema_version = 3')
        self.parameters()
        self.stand = write_sim_stand(self.root, base_scenario())

    def parameters(self, **changes):
        params = {'fixture_setup_file': self.setup.name, 'fixture_verify_file': self.reader.name}
        params.update(changes)
        self.profile.write_text(self.original + '\n[platform.parameters]\n' + '\n'.join(
            key + '=' + json.dumps(value, ensure_ascii=False) for key, value in params.items()) + '\n', encoding='utf-8')

    def test_relative_paths_ignore_cwd_and_capture_exact_bytes(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            p = load_project(self.profile)
        finally:
            os.chdir(previous)
        self.assertEqual(p.parameters['fixture_setup'], 'Возврат "подготовлено";\n')
        self.assertNotIn('fixture_setup_file', p.parameters)
        self.assertEqual([f.path for f in p.fixture_files], [self.setup, self.reader])
        self.assertEqual(p.fixture_files[0].content, self.setup.read_bytes())
        self.assertEqual(p.public()['fixture_files'][0]['sha256'], hashlib.sha256(self.setup.read_bytes()).hexdigest())

    def test_inline_and_file_are_exclusive_per_role(self):
        for role in ('fixture_setup', 'fixture_verify'):
            self.parameters(**{role: 'Возврат 1;'})
            with self.subTest(role=role), self.assertRaisesRegex(FixtureFileError, 'одновременно'):
                load_project(self.profile)

    def test_schema_guard_prevents_silent_execution_by_an_old_harness(self):
        self.profile.write_text(self.profile.read_text(encoding='utf-8').replace('schema_version = 3', 'schema_version = 2'), encoding='utf-8')
        with self.assertRaisesRegex(FixtureFileError, 'schema_version = 3'):
            load_project(self.profile)

    def test_missing_directory_bad_path_and_unsupported_encodings_are_blocked(self):
        for value in ('missing.1s', '.', '', 42):
            self.parameters(fixture_setup_file=value)
            with self.subTest(path=value), self.assertRaises(ConfigError):
                load_project(self.profile)
        self.parameters()
        for content in (b'\xff', b'\xff\xfea\0', b'\xef\xbb\xbftext', b'\0', b'  \r\n', 'Возврат "🙂";'.encode('utf-8')):
            self.setup.write_bytes(content)
            with self.subTest(content=content), self.assertRaises(FixtureFileError):
                load_project(self.profile)

    def test_retained_profile_rereads_edits_and_keeps_old_run_snapshot(self):
        project, stand = load_project(self.profile), load_stand(self.stand)
        deadlines = resolve_deadlines(project, stand)
        profile_bytes = self.profile.read_bytes()
        first = run77.execute(project, stand, deadlines, output_root=self.root / 'runs', run_id='first')
        self.setup.write_text('Возврат "изменено";\n', encoding='utf-8')
        second = run77.execute(project, stand, deadlines, output_root=self.root / 'runs', run_id='second')
        self.assertEqual(first['status'], 'passed')
        self.assertEqual(second['status'], 'passed')
        self.assertEqual(self.profile.read_bytes(), profile_bytes)
        self.assertNotEqual(first['inputs']['fixture_files'][0]['sha256'], second['inputs']['fixture_files'][0]['sha256'])
        self.assertEqual(second['inputs']['parameters']['fixture_setup'], self.setup.read_text(encoding='utf-8'))
        for report in (first, second):
            for item in report['inputs']['fixture_files']:
                evidence = next(f for f in report['result_files'] if f.get('role') == item['role'])
                data = (Path(report['run_dir']) / evidence['path']).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
                self.assertTrue(evidence['complete'] and evidence['sha256_matches'])
        self.assertIn('подготовлено', (self.root / 'runs/first/fixture-inputs/fixture_setup.1s').read_text(encoding='utf-8'))

    def test_file_removed_after_load_never_reaches_platform(self):
        project, stand = load_project(self.profile), load_stand(self.stand)
        self.reader.unlink()
        with patch.object(run77, '_platform_stage') as platform, self.assertRaises(FixtureFileError):
            run77.execute(project, stand, resolve_deadlines(project, stand), output_root=self.root / 'not-created')
        platform.assert_not_called()
        self.assertFalse((self.root / 'not-created').exists())

    def test_cli_and_live_mcp_reread_the_same_profile_without_regeneration(self):
        manifest = self.root / 'suite.toml'
        manifest.write_text('schema_version=1\n[suite]\nid="files"\n[[scenarios]]\nid="one"\nproject=' +
                            json.dumps(self.profile.as_posix()) + '\n', encoding='utf-8')
        client = Client(self.root)
        self.addCleanup(client.close)
        client.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'files', 'version': '1'}})
        frozen = self.profile.read_bytes()
        for index, transport in enumerate(('cli', 'mcp', 'mcp')):
            text = f'Возврат "edit-{index}";\n'
            self.reader.write_text(text, encoding='utf-8')
            output = self.root / ('suite-' + str(index))
            args = {'suite': str(manifest), 'stand': str(self.stand), 'suite_id': 'suite', 'output_root': str(output)}
            if transport == 'cli':
                code, summary, _ = cli(['suite', '--suite', str(manifest), '--stand', str(self.stand),
                                        '--suite-id', 'suite', '--output-root', str(output)], self.root)
                self.assertEqual(code, 0)
            else:
                response = client.call('suite', args)
                self.assertFalse(response['isError'], response)
                summary = response['structuredContent']['stdout']
            suite = json.loads((Path(summary['suite_dir']) / 'suite.json').read_text(encoding='utf-8'))
            run = json.loads((Path(summary['suite_dir']) / suite['scenarios'][0]['report']['path']).read_text(encoding='utf-8'))
            self.assertEqual(run['inputs']['parameters']['fixture_verify'], text)
            self.assertEqual(self.profile.read_bytes(), frozen)
        self.assertEqual(client.request('ping')['result'], {})

    def test_project_init_copies_inputs_and_normalizes_references(self):
        seed = load_project(self.profile)
        scenario = self.root / 'scenario.json'
        scenario.write_text(json.dumps({'parameters': {'fixture_setup_file': str(self.setup),
            'fixture_verify_file': str(self.reader)}, 'tests': [{'name': 'control', 'command': 'execute', 'expect': 'passed'}]}), encoding='utf-8')
        target = self.root / 'created'
        report = project_init77.initialize(directory=target, project_id='files', template=seed.template,
            runtime='forms', source=seed.source, scenario=scenario, open_timeout_s=10,
            calculation_timeout_s=20, cancel_timeout_s=3, shutdown_timeout_s=4, total_timeout_s=50)
        self.assertEqual(set(report['files']), {'project.toml', 'module.1s', 'template.ert', 'scenario.json', 'fixture.1s', 'reader.1s'})
        for filename, source in [('fixture.1s', self.setup), ('reader.1s', self.reader)]:
            self.assertEqual((target / filename).read_bytes(), source.read_bytes())
        data = json.loads((target / 'scenario.json').read_text(encoding='utf-8'))
        self.assertEqual(data['parameters'], {'fixture_setup_file': 'fixture.1s', 'fixture_verify_file': 'reader.1s'})
        self.setup.unlink(); self.reader.unlink()
        loaded = load_project(target / 'project.toml')
        self.assertEqual(len(loaded.fixture_files), 2)
        self.assertIn('schema_version = 3', (target / 'project.toml').read_text(encoding='utf-8'))

    def test_bad_project_init_input_leaves_no_partial_project(self):
        seed = load_project(self.profile)
        scenario = self.root / 'bad.json'
        scenario.write_text(json.dumps({'parameters': {'fixture_setup_file': 'missing.1s'},
            'tests': [{'name': 'test', 'command': 'open', 'expect': 'passed'}]}), encoding='utf-8')
        target = self.root / 'refused'
        with self.assertRaises(FixtureFileError):
            project_init77.initialize(directory=target, project_id='files', template=seed.template,
                runtime='forms', source=seed.source, scenario=scenario, open_timeout_s=10,
                calculation_timeout_s=20, cancel_timeout_s=3, shutdown_timeout_s=4, total_timeout_s=50)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.harness77-project-*')))

    def test_negative_cli_and_mcp_requests_block_and_the_same_server_recovers(self):
        client = Client(self.root)
        self.addCleanup(client.close)
        client.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'negative-files', 'version': '1'}})
        for index, change in enumerate(('missing', 'encoding', 'conflict')):
            self.parameters()
            self.reader.write_bytes(b'\xff' if change == 'encoding' else b'valid reader')
            if change == 'missing':
                self.parameters(fixture_verify_file='missing.1s')
            elif change == 'conflict':
                self.parameters(fixture_verify='inline reader')
            out = self.root / ('negative-' + str(index))
            code, report, stderr = cli(['run', '--project', str(self.profile), '--stand', str(self.stand),
                                    '--output-root', str(out)], self.root)
            self.assertEqual(code, 2)
            if report is None:
                report = stderr
            self.assertFalse(report['platform_checked'])
            self.assertFalse(out.exists())
            response = client.call('run', {'project': str(self.profile), 'stand': str(self.stand), 'output_root': str(out)})
            self.assertTrue(response['isError'], response)
            self.assertEqual(response['structuredContent']['exit_code'], 2)
            self.assertFalse(out.exists())
        self.parameters()
        response = client.call('run', {'project': str(self.profile), 'stand': str(self.stand), 'output_root': str(self.root / 'recovered')})
        self.assertFalse(response['isError'], response)
        self.assertEqual(response['structuredContent']['exit_code'], 0)


if __name__ == '__main__':
    unittest.main()
