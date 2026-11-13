"""097: structured application outcomes through real CLI and stdio MCP suites."""

import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from stage4_fixtures import base_scenario, write_project, write_sim_stand
from test_mcp77 import Client, cli
from harness77.config77 import load_project


EXPECTED = {'entries': [{'amount': '30'}, {'amount': '40'}]}
LABELS = {'/entries/0/amount': 'Проводка 1, сумма', '/entries/1/amount': 'Проводка 2, сумма'}


class ApplicationSuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='h77-app-suite-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        operations = [{'name': name, 'status': 'passed', 'value': value} for name, value in (
            ('good', json.dumps(EXPECTED)),
            ('regression', '{"entries":[{"amount":"10"},{"amount":"20"}]}'),
            ('invalid', '{'), ('empty', ''))]
        self.stand = write_sim_stand(self.root, base_scenario(operations=operations))
        self.client = Client(self.root)
        self.addCleanup(self.client.close)
        self.client.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                          'clientInfo': {'name': 'application-suite-tests', 'version': '1'}})
        self.client.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def manifest(self, names):
        manifest = self.root / 'suite.toml'
        text = 'schema_version=1\n[suite]\nid="application"\n'
        for index, name in enumerate(names):
            project = write_project(self.root / str(index), tests=[])
            with project.open('a', encoding='utf-8') as stream:
                stream.write('\n[[platform.tests]]\nname="persisted-document-and-entries"\n'
                             'expect="passed"\ncommand=' + json.dumps(name) + '\nexpect_json=\'\'\'' +
                             json.dumps(EXPECTED) + '\'\'\'\njson_labels={' + ','.join(
                                 json.dumps(k) + '=' + json.dumps(v) for k, v in LABELS.items()) + '}\n')
            project.write_text(project.read_text(encoding='utf-8').replace('schema_version = 1',
                                                                         'schema_version = 2'), encoding='utf-8')
            text += '\n[[scenarios]]\nid=' + json.dumps(str(index) + '-' + name) + '\nproject=' + json.dumps(str(project)) + '\n'
        manifest.write_text(text, encoding='utf-8')
        return manifest

    def both(self, names, code):
        manifest = self.manifest(names)
        results = []
        for transport in ('cli', 'mcp'):
            arguments = {'suite': str(manifest), 'stand': str(self.stand),
                         'suite_id': transport, 'output_root': str(self.root / transport)}
            if transport == 'cli':
                actual, summary, _ = cli(['suite', '--suite', arguments['suite'], '--stand', arguments['stand'],
                                          '--suite-id', transport, '--output-root', arguments['output_root']], self.root)
                self.assertEqual(actual, code)
            else:
                response = self.client.call('suite', arguments)
                self.assertEqual(response['isError'], code == 2, response)
                self.assertEqual(response['structuredContent']['exit_code'], code)
                summary = response['structuredContent']['stdout']
                self.assertEqual(self.client.request('ping')['result'], {})
            folder = Path(summary['suite_dir'])
            report = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))
            self.assertTrue(report['complete'])
            self.assertFalse(report['cancelled'])
            results.append((report, ET.parse(folder / 'junit.xml').getroot().findall('testsuite/testcase')))
        return results

    def comparison(self, report, index):
        row = report['scenarios'][index]
        path = Path(report['suite_dir']) / row['report']['path']
        child = json.loads(path.read_text(encoding='utf-8'))
        test = next(s for s in child['stages'] if s['stage'] == 'tests')['tests'][0]
        result = test['structured']
        captured = result['result']
        self.assertEqual(captured['run_id'], row['run_id'])
        self.assertEqual(captured['size_bytes'], (path.parent / captured['path']).stat().st_size)
        if row['status'] != 'passed':
            projected = row['problems'][0]['unmet_tests'][0]['structured']
            self.assertEqual(projected['diagnostics'], result['diagnostics'])
            self.assertEqual(projected['result'], captured)
        return result

    def test_forms_project_init_consumed_unchanged_by_run_suite_and_mcp(self):
        from test_run77_configuration import fake_base
        base = fake_base(self.root / 'base')
        stand = write_sim_stand(self.root, base_scenario(operations=[
            {'name': command, 'status': 'passed', 'value': json.dumps(value)}
            for command, value in [('good', EXPECTED), ('regression', {'entries': [{'amount': '10'}, {'amount': '20'}]})]]),
            base=base.as_posix())
        with stand.open('a', encoding='utf-8') as stream:
            stream.write('copy_path=' + json.dumps((self.root / 'copy').as_posix()) + '\n')
        seed = load_project(write_project(self.root / 'seed', tests=[]))
        manifest = self.root / 'created-suite.toml'
        text = 'schema_version=1\n[suite]\nid="created-forms"\n'
        frozen = {}
        profiles = []
        for index, command in enumerate(('good', 'regression', 'good')):
            scenario = self.root / f'scenario-{index}.json'
            scenario.write_text(json.dumps({'parameters': {'steps': [{'check': 'Комментарий', 'text': 'пример'}]},
                'tests': [{'name': 'persisted-document-and-entries', 'command': command, 'expect': 'passed',
                           'expect_json': json.dumps(EXPECTED), 'json_labels': LABELS}]}, ensure_ascii=False), encoding='utf-8')
            directory = self.root / f'created-{index}'
            args = ['project-init', '--directory', str(directory), '--id', f'forms-{index}', '--runtime', 'forms',
                    '--template', str(seed.template), '--source', str(seed.source), '--scenario', str(scenario), '--format', 'json']
            for key, value in dict(open_timeout_s=10, calculation_timeout_s=20, cancel_timeout_s=3,
                                   shutdown_timeout_s=4, total_timeout_s=50).items():
                args += ['--' + key.replace('_', '-'), str(value)]
            code, report, _ = cli(args, self.root)
            self.assertEqual(code, 0, report)
            profile = directory / 'project.toml'
            profiles.append(profile)
            frozen.update({p: p.read_bytes() for p in directory.rglob('*') if p.is_file()})
            text += '\n[[scenarios]]\nid=' + json.dumps(str(index) + '-' + command) + '\nproject=' + json.dumps(str(profile)) + '\n'
        manifest.write_text(text, encoding='utf-8')
        code, summary, _ = cli(['run', '--project', str(profiles[0]), '--stand', str(stand),
                           '--output-root', str(self.root / 'direct')], self.root)
        self.assertEqual(code, 0, summary)
        for transport in ('cli', 'mcp'):
            arguments = {'suite': str(manifest), 'stand': str(stand), 'suite_id': transport,
                         'output_root': str(self.root / ('created-' + transport))}
            if transport == 'cli':
                code, summary, _ = cli(['suite', '--suite', str(manifest), '--stand', str(stand),
                                       '--suite-id', transport, '--output-root', arguments['output_root']], self.root)
                self.assertEqual(code, 1)
            else:
                response = self.client.call('suite', arguments)
                self.assertFalse(response['isError'])
                self.assertEqual(response['structuredContent']['exit_code'], 1)
                summary = response['structuredContent']['stdout']
            report = json.loads((Path(summary['suite_dir']) / 'suite.json').read_text(encoding='utf-8'))
            self.assertEqual([r['status'] for r in report['scenarios']], ['passed', 'failed', 'passed'])
            self.assertEqual(self.comparison(report, 1)['difference_count'], 2)
        self.assertTrue(all(p.read_bytes() == data for p, data in frozen.items()))

    def test_regression_keeps_two_exact_differences_and_continues_after_failure(self):
        for report, cases in self.both(['good', 'regression', 'good', 'good'], 1):
            self.assertEqual([r['status'] for r in report['scenarios']], ['passed', 'failed', 'passed', 'passed'])
            self.assertEqual(report['counts'], {'passed': 3, 'failed': 1, 'blocked': 0, 'skipped': 0})
            result = self.comparison(report, 1)
            self.assertEqual(result['difference_count'], 2)
            self.assertEqual([(d['path'], d['label'], d['expected'], d['actual']) for d in result['diagnostics']],
                             [('/entries/0/amount', LABELS['/entries/0/amount'], '30', '10'),
                              ('/entries/1/amount', LABELS['/entries/1/amount'], '40', '20')])
            self.assertEqual(json.loads(cases[1].findtext('failure')), report['scenarios'][1]['problems'])
            self.assertTrue(all(c.find('error') is None for c in cases))

    def test_invalid_and_empty_json_are_errors_and_cleaned_suite_continues(self):
        for report, cases in self.both(['invalid', 'empty', 'good'], 2):
            self.assertEqual([r['status'] for r in report['scenarios']], ['blocked', 'blocked', 'passed'])
            for index, code in enumerate(('json_result_invalid', 'json_result_missing')):
                result = self.comparison(report, index)
                self.assertEqual(result['diagnostics'][0]['code'], code)
                self.assertEqual(json.loads(cases[index].findtext('error')), report['scenarios'][index]['problems'])
            self.assertIsNone(cases[2].find('error'))
        # Same live MCP server accepts another suite after isError=true.
        manifest = self.manifest(['good'])
        response = self.client.call('suite', {'suite': str(manifest), 'stand': str(self.stand),
                                               'suite_id': 'after-error', 'output_root': str(self.root / 'after')})
        self.assertFalse(response['isError'], response)
        self.assertEqual(response['structuredContent']['exit_code'], 0)


if __name__ == '__main__':
    unittest.main()
