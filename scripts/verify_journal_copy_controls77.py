"""Exercise 039 verifier with deliberately corrupted evidence; never modify the baseline."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import tempfile

from verify_journal_copy77 import check, step_issues, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folder = args.run.resolve()
    baseline = check(folder)
    if baseline['issues']:
        raise RuntimeError('baseline must pass before controls: ' + str(baseline['issues']))
    inspection = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    identity = json.loads((folder / 'native/proxy-verified.json').read_text(encoding='utf-8'))['identity']
    controls = []
    changes = [
        ('search-enter', lambda r: r[1].update(action={'key': 'Enter'})),
        ('search-reference', lambda r: r[1]['search'][-1]['round_trip'].update(journal_match='0')),
        ('copy-source', lambda r: r[2]['round_trip'].update(journal_source='foreign')),
        ('copy-already-saved', lambda r: r[2]['round_trip'].update(journal_new='0')),
        ('copy-posted', lambda r: r[2]['round_trip'].update(journal_posted='1')),
        ('copy-deleted', lambda r: r[2]['round_trip'].update(journal_deleted='1')),
        ('copy-number', lambda r: r[2]['round_trip'].update(journal_number='000000000002')),
        ('copy-date', lambda r: r[2]['round_trip'].update(journal_date='2026:8:1')),
        ('neighbor-data', lambda r: r[2]['round_trip'].update(journal_value='changed neighbors')),
        ('stale-window', lambda r: r[2]['round_trip'].update(journal_hwnd=r[2]['before_copy']['journal_hwnd'])),
        ('foreign-process', lambda r: r[2]['after_windows'][0].update(pid=0)),
        ('command-id', lambda r: r[2]['action'].update(command=0x8011)),
        ('command-target', lambda r: r[2]['action'].update(hwnd=1)),
        ('command-not-sent', lambda r: r[2]['action'].update(posted=False)),
        ('disabled-menu', lambda r: r[2]['menu'].update(flags=3, enabled=False)),
        ('saved-source-reference', lambda r: next(s for s in r if s['kind'] == 'created')['round_trip'].update(
            journal_reference=r[2]['round_trip']['journal_source'])),
        ('saved-entries', lambda r: next(s for s in r if s['kind'] == 'created')['round_trip'].update(journal_value='missing copy')),
        ('copied-row', lambda r: next(s for s in r if s['kind'] == 'value')['round_trip'].update(value='999')),
        ('input-layout-not-restored', lambda r: next(s for s in r if s['kind'] == 'input')['action']['character_input_layouts'][0].update(server_restored=False)),
        ('input-layout-foreign-thread', lambda r: next(s for s in r if s['kind'] == 'input')['action']['character_input_layouts'][0].update(tid=0)),
    ]
    for name, mutate in changes:
        records = copy.deepcopy(inspection['steps'])
        if name == 'foreign-process':
            hwnd = records[2]['created_form']['chain'][0]['hwnd']
            next(w for w in records[2]['after_windows'] if w['hwnd'] == hwnd)['pid'] = 0
        else:
            mutate(records)
        issues = step_issues(records, 'success', inspection, identity)
        controls.append(dict(name=name, rejected=bool(issues), issues=issues))
    with tempfile.TemporaryDirectory(prefix='journal-copy-controls-') as temporary:
        clone = Path(temporary) / folder.name
        shutil.copytree(folder, clone)
        raw = clone / 'native/form-step-3-done'
        original = raw.read_bytes()
        encoding = 'utf-16' if original.startswith(b'\xff\xfe') else 'cp1251'
        decoded = original.decode(encoding)
        changed = decoded.replace('journal-copy:1', 'journal-copy:0')
        if changed == decoded:
            raise RuntimeError('raw copy response marker missing')
        raw.write_bytes(changed.encode(encoding))
        issues = check(clone)['issues']
        controls.append(dict(name='raw-response-file', rejected=bool(issues), issues=issues))
    result = dict(status='passed' if all(c['rejected'] for c in controls) else 'failed',
                  baseline_run=baseline['run_id'], verifier_sha256=digest(Path(__file__).with_name('verify_journal_copy77.py')),
                  controls=controls)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(status=result['status'], controls=len(controls)), ensure_ascii=False))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
