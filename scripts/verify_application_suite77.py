"""097: reject altered application evidence on private copies of the native suites.

Run with the kit's installed Python, --kit and --native pointing at the accepted
inputs/results. No original result, database, registry or live process is changed.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    kit, native, out = args.kit.resolve(), args.native.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(kit))  # Standalone forms kits expose the inherited suite verifier here.
    specification = importlib.util.spec_from_file_location('application_verifier097', kit / 'verify.py')
    verifier = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(verifier)
    record = read(native / 'verified.json')
    expected = read(kit / 'expected.json')
    results = []

    def perform(folder):
        result = verifier.verify(folder, record['plans'], expected)
        # The inherited 033 verifier expects a failed application test. For a JSON
        # infrastructure error only that aggregate outcome differs; every raw UI
        # round trip, native response, file hash and cleanup check must still pass.
        suite = read(folder / 'suite.json')
        for row in suite['scenarios']:
            if row['status'] != 'blocked':
                continue
            run_file = folder / row['report']['path']
            platform = read(run_file.parent / 'platform-result.json')
            raw = next(op['value'] for op in platform['operations'] if op['name'] == 'verify')
            audit = verifier.check(run_file.parent, 'wrong', verifier.digest(run_file), readback=raw,
                                   expected_md_hash=record['plans'][row['id']]['md_sha256'])
            assert audit['issues'] == ['wrong run outcome'], audit
        return result

    for manifest, target_case in [('regression', 'regression'), ('invalid-results', 'invalid-json')]:
        original = next(s for s in record['suites'] if s['transport'] == 'mcp' and s['manifest'] == manifest)
        clone = out / manifest
        assert clone.resolve().is_relative_to(out)
        shutil.copytree(Path(original['folder']).parent, clone)
        folder = clone / 'suite'
        suite_path = folder / 'suite.json'
        suite = read(suite_path)
        suite['runs_dir'] = str(clone / 'runs')
        suite['suite_dir'] = str(folder)
        write(suite_path, suite)
        perform(folder)
        row = next(r for r in suite['scenarios'] if r['id'] == target_case)
        child_path = (folder / row['report']['path']).resolve()
        child = read(child_path)
        test = next(t for s in child['stages'] if s['stage'] == 'tests' for t in s['tests']
                    if t['name'] == 'persisted-document-and-entries')
        actual_path = child_path.parent / test['structured']['result']['path']
        xml_path = folder / 'junit.xml'
        events_path = child_path.parent / 'native/ert-events.jsonl'
        inspection_path = child_path.parent / 'form/form-window.json'
        files = [suite_path, child_path, actual_path, xml_path, events_path, inspection_path]
        assert all(p.resolve().is_relative_to(clone) for p in files)
        baseline = {p: p.read_bytes() for p in files}

        def check(name, mutation):
            for path, data in baseline.items():
                path.write_bytes(data)
            current, changed = read(suite_path), read(child_path)
            scenario = next(r for r in current['scenarios'] if r['id'] == target_case)
            comparison = next(t for s in changed['stages'] if s['stage'] == 'tests' for t in s['tests']
                              if t['name'] == 'persisted-document-and-entries')['structured']
            xml = ET.parse(xml_path)
            case = next(c for c in xml.getroot().findall('testsuite/testcase') if c.get('name') == target_case)
            mutation(current, scenario, changed, comparison, case)
            write(child_path, changed)
            data = child_path.read_bytes()
            scenario['report'].update(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
            # Refresh linkage and hashes: altered details must fail beyond hash checking.
            case.find('system-out').text = json.dumps({k: scenario.get(k) for k in
                                                       ('run_id', 'report', 'platform_checked', 'cancelled', 'timeout_phase')})
            xml.write(xml_path, encoding='utf-8', xml_declaration=True)
            data = xml_path.read_bytes()
            current['junit'].update(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
            write(suite_path, current)
            try:
                perform(folder)
            except (AssertionError, ValueError, KeyError, OSError) as error:
                results.append({'manifest': manifest, 'control': name, 'rejected': True, 'error': type(error).__name__})
            else:
                results.append({'manifest': manifest, 'control': name, 'rejected': False})

        def projected(key, value):
            return lambda suite, row, child, comparison, case: row['problems'][0]['unmet_tests'][0]['structured'].__setitem__(key, value)

        check('projected-count', projected('difference_count', 999))
        check('projected-diagnostics-absent', projected('diagnostics', []))
        check('projected-foreign-result', projected('result', {'run_id': 'foreign', 'path': 'foreign.json'}))
        check('junit-detailed-body', lambda s, r, c, d, x: setattr(x.find('failure') if manifest == 'regression' else x.find('error'), 'text', '[]'))
        check('junit-reason', lambda s, r, c, d, x: (x.find('failure') if manifest == 'regression' else x.find('error')).set('message', 'foreign'))
        check('child-foreign-run-id', lambda s, r, c, d, x: c.__setitem__('run_id', 'foreign'))
        check('actual-bytes', lambda s, r, c, d, x: actual_path.write_bytes(b'{}'))
        check('actual-size', lambda s, r, c, d, x: d['result'].__setitem__('size_bytes', 9000))
        check('actual-foreign-run-id', lambda s, r, c, d, x: d['result'].__setitem__('run_id', 'foreign'))
        check('actual-path', lambda s, r, c, d, x: d['result'].__setitem__('path', 'structured/foreign.json'))
        check('incomplete-suite', lambda s, r, c, d, x: s.__setitem__('complete', False))
        check('raw-native-events-absent', lambda s, r, c, d, x: events_path.write_bytes(b''))
        check('ui-evidence-absent', lambda s, r, c, d, x: write(inspection_path, {'steps': []}))
        if manifest == 'regression':
            for key, value in [('path', '/entries/9/amount'), ('label', 'foreign'), ('expected', '300'),
                               ('actual', '100'), ('expected_type', 'number'), ('code', 'foreign')]:
                def common_mode(s, r, c, d, x, key=key, value=value):
                    d['differences'][0][key] = value
                    d['diagnostics'][0][key] = value
                    r['problems'][0]['unmet_tests'][0]['structured']['diagnostics'] = copy.deepcopy(d['diagnostics'])
                    x.find('failure').text = json.dumps(r['problems'], ensure_ascii=False)
                check('common-mode-' + key, common_mode)
        else:
            check('wrong-invalid-code', lambda s, r, c, d, x: d['diagnostics'][0].__setitem__('code', 'json_result_missing'))
        for path, data in baseline.items():
            path.write_bytes(data)
        perform(folder)
    result = {'status': 'passed' if all(c['rejected'] for c in results) else 'failed',
              'controls': results, 'count': len(results), 'original_unchanged': True,
              'native_runs': 0, 'baseline_identities': [], 'suites': []}
    # Every original suite is re-read after the controls; compare with initial verification.
    for group in record['suites']:
        assert perform(Path(group['folder'])) == group['verification']
        result['suites'].append({'transport': group['transport'], 'manifest': group['manifest'],
                                 **group['verification']['suite']})
        for row in group['verification']['scenarios']:
            owner = read(Path(row['report']).parent / 'native/owner.json')
            if result['baseline_identities']:
                assert owner['baseline_identity'] == result['baseline_identities']
            else:
                result['baseline_identities'] = owner['baseline_identity']
            assert owner['server']['ownership_verified'] and owner['forced_cleanup'] is False
            result['native_runs'] += 1
    assert record['status'] == 'passed' and all(record['unchanged'].values())
    assert record['cli_mcp_equal'] and record['mcp_exit_code'] == 0 and result['native_runs'] == 15
    write(out / 'controls.json', result)
    print(json.dumps({'status': result['status'], 'controls': result['count']}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
