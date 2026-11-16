"""Independently reread task-108 reports, input snapshots and ERT containers."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from harness77 import ert_module as ert, form77
from harness77.lint77 import cfb_paths


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify(output, project, template):
    spec = importlib.util.spec_from_file_location('checks108',Path(__file__).with_name('run.py'))
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    record = read(output/'verified.json')
    assert record['status'] == 'passed' and record['before'] == record['after']
    assert not record['after']['copy'] and not record['after']['lock']
    assert record['mcp_exit_code'] == 0 and record['mcp_progress']['ping_during'] and record['mcp_progress']['ping_after']
    assert all(sha(project/n) == h for n,h in record['inputs'].items())
    assert [r['case'] for r in record['runs']] == list(checks.CASES)
    folders = [(r['case'],Path(r['folder'])) for r in record['runs']]
    for suite in record['suites']:
        f = Path(suite['folder'])
        assert checks.audit_suite(f) == record['canonical']
        for row in read(f/'suite.json')['scenarios']:
            report = f/row['report']['path']
            assert sha(report) == row['report']['sha256']
            folders.append((row['id'],report.resolve().parent))
    assert len(folders) == 30 and len({f for _,f in folders}) == 30
    original = ert.CompoundFile(template.read_bytes())
    paths = cfb_paths(original)
    controls = form77._structure(ert.extract_dialog(template))[2][1:]
    snapshots, passed, failed, residuals = 0, 0, 0, []
    for name,folder in folders:
        result = checks.audit(folder,name)
        assert result == record['canonical'][name]
        passed += result['status'] == 'passed'
        failed += result['status'] == 'failed'
        snapshots += len(result['snapshots'])
        residuals.append(result['geometry_residual_px'])
        built, = (folder/'build').glob('*.ert')
        current = ert.CompoundFile(built.read_bytes())
        assert cfb_paths(current) == paths
        assert len(current.directory_entries) == len(original.directory_entries)
        for a,b in zip(original.directory_entries,current.directory_entries):
            end = 116 if a.object_type in (2,5) else 128
            assert a.raw[:end] == b.raw[:end]
            if a.object_type == 2 and paths[a.entry_id] not in (ert.MODULE_STREAM,ert.DIALOG_STREAM):
                assert original.read_stream(a) == current.read_stream(b)
        actual = form77._structure(ert.extract_dialog(built))[2][1:]
        assert actual[:-1] == controls and actual[-1][form77.CLASS] == 'COMBOBOX'
        report = read(folder/'run.json')
        source = (output/name/'module.1s').read_text(encoding='utf-8')
        assert ert.extract_text(built).replace('\r\n','\n') == source.replace('\r\n','\n')
        source_steps = output/name/'steps.json'
        item, = [i for i in report['inputs']['json_files'] if i['role'] == 'steps']
        assert item['sha256'] == sha(source_steps)
    for name in checks.CASES:
        assert (output/name/'form.json').read_bytes() == (project/'form.json').read_bytes()
        if name != 'empty':
            assert (output/name/'steps.json').read_bytes() == (project/'steps.json').read_bytes()
    for name in ('baseline','fixed','repeat-fixed'):
        assert (output/name/'module.1s').read_bytes() == (project/'module.1s').read_bytes()
    assert (passed,failed,snapshots) == (12,18,48)
    result = dict(status='passed',reports=30,passed=passed,expected_failed=failed,combo_snapshots=snapshots,
        exact_expectations_preserved=True,transport_diagnostics_equal=True,
        non_target_streams_preserved=True,max_geometry_residual_px=max(residuals))
    (output/'independent.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('output','project','template'):
        p.add_argument('--'+key,type=Path,required=True)
    a = p.parse_args()
    verify(a.output.resolve(),a.project.resolve(),a.template.resolve())
