"""Re-read the completed 105 series, including native combo rectangles and strict negative controls."""
import argparse
import copy
from pathlib import Path
import sys

import harness77

sys.path.insert(0, str(Path(harness77.__file__).parent / '_native/forms'))
from form_window77 import expected_geometry, edged_ids, fit_units, measured_geometry

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('--project', type=Path, default=HERE)
    a = p.parse_args()
    sys.path.insert(0, str(a.project.resolve()))
    from audit_utils import digest, read, write
    from run import audit, audit_suite, PHASES
    record = read(a.output / 'verified.json')
    assert record['status'] == 'passed' and record['unchanged_tests']
    assert record['before'] == record['after']
    assert all(digest(Path(name)) == sha for name, sha in record['inputs'].items())
    assert [r['case'] for r in record['runs']] == list(PHASES)
    assert [s['transport'] for s in record['suites']] == ['cli', 'mcp']
    expected = read(a.project / 'expected.json')
    folders = [(Path(r['folder']), r['case']) for r in record['runs']]
    for suite in record['suites']:
        folder = Path(suite['folder'])
        assert audit_suite(folder, record['plans'], expected)
        rows = read(folder / 'suite.json')['scenarios']
        assert [r['id'] for r in rows] == list(PHASES)
        folders += [((folder / r['report']['path']).resolve().parent, r['id']) for r in rows]
    assert len(folders) == 12
    geometry = []
    canonical = {}
    for folder, phase in folders:
        checked = audit(folder, phase, record['plans'], expected)
        report = read(folder / 'run.json')
        tests = next(s for s in report['stages'] if s['stage'] == 'tests')['tests']
        projection = {'status': report['status'], 'reason': report['reason'], 'tests': [
            {'name': t['name'], 'status': t['status'], 'expectation_met': t['expectation_met'],
             'structured': {k: t['structured'][k] for k in ('difference_count', 'differences', 'diagnostics')} if 'structured' in t else None} for t in tests]}
        assert phase not in canonical or canonical[phase] == projection
        canonical[phase] = projection
        files = {'fixture_setup': 'fixture.1s', 'fixture_verify': 'reader.1s', 'steps': 'steps.json', 'expect_json': 'expected.json'}
        for key in ('fixture_files', 'json_files'):
            for item in report['inputs'][key]:
                snapshot, = [r for r in report['result_files'] if r.get('role') == item['role'] and r.get('test_index') == item.get('test_index')]
                assert (folder / snapshot['path']).read_bytes() == (a.project / files[item['role']]).read_bytes()
        description = read(folder / 'form/description.json')
        expected_rects = expected_geometry(description)
        form = read(folder / 'form/form-window.json')
        inspections = [form, next(s for s in form['steps'] if s['kind'] == 'reopen')['reopened']]
        for inspection in inspections:
            fit = fit_units(expected_rects, measured_geometry(inspection), edged=edged_ids(description))
            assert fit['consistent'] and fit['tolerance_px'] == 2
            combos = [c for c in inspection['controls'] if c.get('layout_rect_source') == 'CB_GETDROPPEDCONTROLRECT']
            assert len(combos) == 2
            assert all(c['layout_rect'][3] > c['rect'][3] for c in combos)
            assert all(0 < c['combo_item_height'] <= 4096 and 0 < c['combo_default_item_height'] <= 4096 for c in combos)
            legacy = fit_units(expected_rects, {c['id']: tuple(c['rect']) for c in inspection['controls']}, edged=edged_ids(description))
            assert not legacy['consistent']
            negatives = 0
            for combo in combos:
                for component in range(4):
                    bad = copy.deepcopy(inspection)
                    next(c for c in bad['controls'] if c['id'] == combo['id'])['layout_rect'][component] += 15
                    assert not fit_units(expected_rects, measured_geometry(bad), edged=edged_ids(description))['consistent']
                    negatives += 1
            bad = copy.deepcopy(inspection)
            next(c for c in bad['controls'] if c['class'].casefold() == 'button')['rect'][0] += 15
            assert not fit_units(expected_rects, measured_geometry(bad), edged=edged_ids(description))['consistent']
            geometry.append({'folder': str(folder), 'phase': phase, 'max_residual_px': fit['max_residual_px'],
                'legacy_residual_px': legacy['max_residual_px'], 'negative_controls': negatives + 1,
                'combos': [{k: c[k] for k in ('id', 'rect', 'layout_rect', 'layout_rect_source',
                    'combo_item_height', 'combo_default_item_height')} for c in combos]})
    mcp = read(a.output / 'mcp-response.json')
    assert record['mcp_exit_code'] == 0 and mcp['progress']['ping_during'] and mcp['progress']['ping_after']
    write(a.output / 'independent.json', {'status': 'passed', 'runs': len(folders), 'geometry_checks': len(geometry),
        'negative_geometry_controls': sum(g['negative_controls'] for g in geometry),
        'source_registry_processes_preserved': True, 'transport_diagnostics_equal': True,
        'snapshots_match_project_bytes': True, 'suite_junit_matches_json': True, 'geometry': geometry})
    print('105 independently verified: 12 runs, 24 geometry checks, 216 negative geometry controls')


if __name__ == '__main__':
    main()
