"""103: editable JSON inputs, execution snapshots, refusals and compatibility."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness77 import project_init77, run77
from harness77.config77 import JsonFileError, load_project, load_stand, resolve_deadlines
from harness77.deadlines77 import ManualClock
from stage4_fixtures import write_project, write_sim_stand, base_scenario, DEFAULT_DEADLINES
from test_mcp77 import Client, cli


def toml(value):
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + '=' + toml(v) for k,v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(map(toml,value)) + ']'
    return json.dumps(value, ensure_ascii=False)


class JsonFilesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='h77-json-files-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.profile = write_project(self.root / 'проект с пробелами')
        self.prefix = self.profile.read_text(encoding='utf-8').split('[platform]')[0]
        self.steps = self.profile.parent / 'шаги.json'
        self.expected = self.profile.parent / 'ожидания.json'
        self.steps.write_bytes('[\r\n  {"check":"ОК","text":"да"}\r\n]\r\n'.encode('utf-8'))
        self.expected.write_bytes(b'42\r\n')
        self.configure()
        self.stand = write_sim_stand(self.root, base_scenario())

    def configure(self, *, parameters=None, tests=None, version=4):
        parameters = {'steps_file': self.steps.name} if parameters is None else parameters
        tests = [{'name':'control-42','expect':'passed','expect_json_file':self.expected.name}] if tests is None else tests
        self.profile.write_text(self.prefix.replace('schema_version = 1', 'schema_version = '+str(version)) +
            '\n[platform]\nparameters='+toml(parameters)+'\ntests='+toml(tests)+'\n[deadlines]\n'+
            '\n'.join(k+'='+str(v) for k,v in DEFAULT_DEADLINES.items())+'\n',encoding='utf-8')

    def execute(self, project=None, name='run'):
        project = project or load_project(self.profile)
        stand = load_stand(self.stand)
        return run77.execute(project,stand,resolve_deadlines(project,stand),output_root=self.root/name,clock=ManualClock())

    def test_relative_paths_unicode_foreign_cwd_and_exact_bytes(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            p = load_project(self.profile)
        finally:
            os.chdir(previous)
        self.assertEqual(p.parameters, {'steps':[{'check':'ОК','text':'да'}]})
        self.assertEqual(p.tests[0]['expect_json'],'42\n')
        self.assertNotIn('expect_json_file',p.tests[0])
        self.assertEqual([f.content for f in p.json_files],[self.steps.read_bytes(),self.expected.read_bytes()])
        self.assertEqual(p.json_files[1].public()['test_index'],0)

    def test_schema_guard_and_conflicts(self):
        for version in (1,2,3):
            self.configure(version=version)
            with self.subTest(version=version),self.assertRaisesRegex(JsonFileError,'schema_version = 4'):
                load_project(self.profile)
        self.configure(parameters={'steps_file':self.steps.name,'steps':[]})
        with self.assertRaisesRegex(JsonFileError,'одновременно'):
            load_project(self.profile)
        for extra in ({'expect_json':'42'},{'expect_value':'42'},{'expect':'failed'}):
            test={'name':'control-42','expect':'passed','expect_json_file':self.expected.name,**extra}
            self.configure(tests=[test])
            with self.subTest(extra=extra),self.assertRaises(JsonFileError):
                load_project(self.profile)

    def test_bad_paths_encodings_json_and_steps_structure(self):
        for path in ('missing.json','.', '',42):
            self.configure(parameters={'steps_file':path})
            with self.subTest(path=path),self.assertRaises(JsonFileError):
                load_project(self.profile)
        self.configure()
        payloads=[b'\xff',b'\xef\xbb\xbf[]',b'',b'\0',b'{',b'[]',b'{}',b'[1]',b'[{}]',
                  b'[{"x":{"nested":1}}]',b'[{"x":NaN}]',b'[{"x":1,"x":2}]',b'[{"x":1e400}]',b' '*(1048577)]
        for payload in payloads:
            self.steps.write_bytes(payload)
            with self.subTest(payload=payload[:80]),self.assertRaises(JsonFileError):
                load_project(self.profile)

    def test_bad_expected_json_labels_and_unicode(self):
        for payload in (b'{',b'{"x":1,"x":2}',b'NaN',b'"\\ud800"',b'\xef\xbb\xbf42',b'\xff'):
            self.expected.write_bytes(payload)
            with self.subTest(payload=payload),self.assertRaises(JsonFileError):
                load_project(self.profile)
        self.expected.write_bytes(b'42')
        self.configure(tests=[{'name':'control-42','expect':'passed','expect_json_file':self.expected.name,'json_labels':{'/missing':'x'}}])
        with self.assertRaises(JsonFileError):
            load_project(self.profile)
        self.expected.write_bytes('"🙂"'.encode('utf-8'))
        self.configure()
        self.assertEqual(load_project(self.profile).tests[0]['expect_json'],'"🙂"')

    def test_retained_profile_rereads_both_files_and_keeps_old_snapshots(self):
        p=load_project(self.profile)
        frozen=self.profile.read_bytes()
        first=self.execute(p,'first')
        self.steps.write_bytes(b'[{"check":"new","text":"edit"}]')
        self.expected.write_bytes(b'43')
        second=self.execute(p,'second')
        self.expected.write_bytes(b'42')
        third=self.execute(p,'third')
        self.assertEqual([r['status'] for r in (first,second,third)],['passed','failed','passed'])
        self.assertEqual(second['inputs']['parameters']['steps'][0]['check'],'new')
        self.assertEqual(self.profile.read_bytes(),frozen)
        for report in (first,second,third):
            for item in report['inputs']['json_files']:
                evidence=next(f for f in report['result_files'] if f.get('role')==item['role'])
                raw=(Path(report['run_dir'])/evidence['path']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),item['sha256'])
                self.assertEqual(len(raw),item['size_bytes'])
                self.assertTrue(evidence['complete'] and evidence['sha256_matches'])
        self.assertEqual((Path(first['run_dir'])/'input-files/test-0001.expected.json').read_bytes(),b'42\r\n')

    def test_removed_file_after_load_is_refused_without_platform_or_output(self):
        p=load_project(self.profile)
        self.expected.unlink()
        with patch.object(run77,'_platform_stage') as platform,self.assertRaises(JsonFileError):
            self.execute(p,'absent')
        platform.assert_not_called()
        self.assertFalse((self.root/'absent').exists())

    def test_later_disk_change_does_not_change_captured_expectation(self):
        original=run77._platform_stage
        def change(*args,**kwargs):
            self.expected.write_bytes(b'43')
            return original(*args,**kwargs)
        with patch.object(run77,'_platform_stage',side_effect=change):
            report=self.execute(name='snapshot')
        self.assertEqual(report['status'],'passed')
        self.assertEqual((Path(report['run_dir'])/'input-files/test-0001.expected.json').read_bytes(),b'42\r\n')
        self.assertEqual(self.execute(name='next')['status'],'failed')

    def test_live_mcp_cli_errors_and_recovery_without_profile_regeneration(self):
        client=Client(self.root)
        self.addCleanup(client.close)
        client.request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'json-files','version':'1'}})
        frozen=self.profile.read_bytes()
        for index,(payload,code) in enumerate([(b'{',2),(b'43',1),(b'42',0)]):
            self.expected.write_bytes(payload)
            out=self.root/('request-'+str(index))
            response=client.call('run',{'project':str(self.profile),'stand':str(self.stand),'output_root':str(out)})
            self.assertEqual(response['structuredContent']['exit_code'],code,response)
            self.assertEqual(response['isError'],code==2)
            self.assertEqual(client.request('ping')['result'],{})
        code,summary,_=cli(['run','--project',str(self.profile),'--stand',str(self.stand),'--output-root',str(self.root/'cli')],self.root)
        self.assertEqual(code,0,summary)
        self.assertEqual(self.profile.read_bytes(),frozen)

    def test_project_init_copies_all_four_files_and_survives_source_removal(self):
        setup=self.root/'fixture.1s'; reader=self.root/'reader.1s'
        setup.write_bytes(b'return setup'); reader.write_bytes(b'return reader')
        scenario=self.root/'scenario-input.json'
        scenario.write_text(json.dumps({'parameters':{'steps_file':str(self.steps),'fixture_setup_file':str(setup),'fixture_verify_file':str(reader)},
            'tests':[{'name':'a','command':'execute','expect':'passed','expect_json_file':str(self.expected)}]}),encoding='utf-8')
        p=load_project(self.profile)
        target=self.root/'created'
        report=project_init77.initialize(directory=target,project_id='files103',template=p.template,runtime='forms',source=p.source,
            scenario=scenario,open_timeout_s=10,calculation_timeout_s=20,cancel_timeout_s=3,shutdown_timeout_s=4,total_timeout_s=50)
        self.assertEqual(set(report['files']),{'project.toml','module.1s','template.ert','scenario.json','steps.json','expected.json','fixture.1s','reader.1s'})
        for old,name in [(setup,'fixture.1s'),(reader,'reader.1s'),(self.steps,'steps.json'),(self.expected,'expected.json')]:
            self.assertEqual((target/name).read_bytes(),old.read_bytes())
            old.unlink()
        loaded=load_project(target/'project.toml')
        self.assertEqual((len(loaded.fixture_files),len(loaded.json_files)),(2,2))
        self.assertIn('schema_version = 4',(target/'project.toml').read_text(encoding='utf-8'))

    def test_project_init_multiple_expectations_and_invalid_source_no_partial_output(self):
        p=load_project(self.profile)
        scenario=self.root/'scenario-input.json'
        data={'parameters':{},'tests':[{'name':str(i),'command':'execute','expect':'passed','expect_json_file':str(self.expected)} for i in range(2)]}
        scenario.write_text(json.dumps(data),encoding='utf-8')
        options=dict(project_id='files103',template=p.template,runtime='forms',source=p.source,scenario=scenario,
                     open_timeout_s=10,calculation_timeout_s=20,cancel_timeout_s=3,shutdown_timeout_s=4,total_timeout_s=50)
        target=self.root/'multiple'
        project_init77.initialize(directory=target,**options)
        self.assertTrue((target/'expected-0001.json').exists() and (target/'expected-0002.json').exists())
        self.expected.write_bytes(b'{')
        with self.assertRaises(JsonFileError):
            project_init77.initialize(directory=self.root/'refused',**options)
        self.assertFalse((self.root/'refused').exists())
        self.assertFalse(list(self.root.glob('.harness77-project-*')))


if __name__=='__main__':
    unittest.main()
