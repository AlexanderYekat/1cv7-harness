"""Independently re-read task 030 run reports, operation protocols, cleanup and JUnit.

python scripts/verify_posting77.py --evidence .artifacts/stage30-posting-....json
    --suite .artifacts/suites/SUITE --output .artifacts/stage30-acceptance-....json
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'research/forms'))
import probe_posting77 as probes
from verify_suite77 import verify as verify_suite


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(folder, expected_hash=None, case=None, refusal=False):
    issues = []
    def require(condition, reason):
        if not condition:
            issues.append(reason)
    report = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    platform = json.loads((folder / 'platform-result.json').read_text(encoding='utf-8'))
    stage = next(s for s in report['stages'] if s['stage'] == 'platform_check')
    require(report['run_id'] == folder.name == platform['run_id'], 'foreign run identity')
    require(report['platform_checked'] is True, 'no native check')
    if expected_hash:
        require(digest(folder / 'run.json') == expected_hash, 'run report changed')
    copy = stage.get('base_copy') or {}
    require(copy.get('source_check', {}).get('unchanged') is True, 'source preservation not confirmed')
    require(copy.get('removal', {}).get('removed') is True, 'copy removal not confirmed')
    require(copy.get('lock', {}).get('released') is True, 'copy lock not released')
    require(platform.get('base_list', {}).get('unchanged') is True, 'base list preservation not confirmed')
    shutdown = report.get('shutdown') or {}
    require(shutdown.get('cleanup_verified') is True and shutdown.get('others_preserved') is True,
            'session cleanup not confirmed')
    operations = {op['name']: op for op in platform['operations']}
    post, verify = operations.get('post', {}), operations.get('verify', {})
    require('posting' in post, 'no structured posting result')
    require(verify.get('status') == 'passed', 'persisted entries not read successfully')
    if case:
        require(probes.judge(case, probes.base.observe(folder)) == 'confirmed', 'declared case expectations not met')
        if case['id'] == 'post-error':
            require(bool(post.get('diagnostics') or post.get('posting', {}).get('errors')), 'runtime error diagnostic missing')
    if not post or not verify:
        return {'run_id': report['run_id'], 'status': report['status'], 'post': post,
                'persisted_entries': verify.get('value'), 'run_sha256': digest(folder / 'run.json'), 'issues': issues}
    manifest = json.loads((folder / 'native/ert-manifest.json').read_text(encoding='utf-8'))
    require(manifest['commands'] == ['check', 'open', 'result', 'post', 'verify'], 'wrong operation order')
    events = [json.loads(line) for line in (folder / 'native/ert-events.jsonl').read_text(encoding='utf-16').splitlines()]
    for command in ('post', 'verify'):
        event = [e for e in events if e.get('kind') == 'ert' and e.get('name') == command]
        require(len(event) == 1 and event[0]['run_id'] == report['run_id'], command + ': missing/foreign event')
        path = folder / 'native' / manifest['protocol_paths'][command]
        raw = path.read_bytes()
        lines = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'cp1251').splitlines()
        require(lines[:1] == ['HARNESS77-BEGIN:' + report['run_id'] + ':' + command]
                and lines[-1:] == ['HARNESS77-END:' + report['run_id'] + ':' + command], command + ': wrong protocol markers')
        if command == 'post' and refusal:
            require(probes.REFUSAL in lines, 'refusal diagnostic missing')
        if len(event) == 1:
            response = event[0]['value'].splitlines()
            if command == 'post':
                for key, field in [('post-return:', 'returned'), ('post-posted:', 'posted')]:
                    values = [line[len(key):].strip() for line in response if line.startswith(key)]
                    require(values == [str(post.get('posting', {}).get(field))], field + ': response/report differ')
            else:
                values = [line[len('fixture-value:'):] for line in response if line.startswith('fixture-value:')]
                require(values == [verify.get('value')], 'entry readback response/report differ')
    return {'run_id': report['run_id'], 'status': report['status'], 'post': post,
            'persisted_entries': verify.get('value'), 'run_sha256': digest(folder / 'run.json'), 'issues': issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, action='append', default=[])
    parser.add_argument('--suite', type=Path, action='append', default=[])
    parser.add_argument('--case', action='append', default=[], help='select series cases; suites are checked in full')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = {c['id']: c for c in probes.CASES}
    rows, suites, issues, excluded = [], [], [], []
    selected = set(args.case)
    found = set()
    for path in args.evidence:
        evidence = json.loads(path.read_text(encoding='utf-8'))
        if not all(evidence['series'].values()):
            issues.append(str(path) + ': source or base list changed')
        for row in evidence['cases']:
            if selected and row['id'] not in selected:
                excluded.append({'id': row['id'], 'run_id': row.get('run_id'), 'verdict': row['verdict'],
                                 'run_sha256': row.get('run_json_sha256')})
                continue
            found.add(row['id'])
            rows.append(check(ROOT / '.artifacts/runs' / row['run_id'], row['run_json_sha256'],
                              cases[row['id']], refusal=row['id'] == 'post-refused'))
    for folder in args.suite:
        suites.append(verify_suite(folder.resolve(), native=True))
        report = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))
        for row in report['scenarios']:
            sample = cases[{'success': 'post-ok', 'repeat': 'post-ok', 'after-failure': 'post-ok',
                            'refused': 'post-refused', 'wrong': 'post-wrong'}[row['id']]]
            rows.append(check((folder / row['report']['path']).parent, row['report']['sha256'],
                              case=sample, refusal=row['id'] == 'refused'))
    if not rows:
        issues.append('no native runs checked')
    if selected - found:
        issues.append('requested series cases missing: ' + ', '.join(sorted(selected - found)))
    issues += [r['run_id'] + ': ' + issue for r in rows for issue in r['issues']]
    issues += [s['suite_id'] + ': ' + issue for s in suites for issue in s['issues']]
    sources = ['research/forms/fixture77.py', 'research/forms/form_launcher77.py',
               'research/forms/tests/test_fixture77.py', 'research/forms/probe_posting77.py',
               'examples/document-posting/scenario.toml', 'examples/document-posting/prepare.py',
               'scripts/verify_posting77.py']
    result = {'schema_version': 1, 'status': 'failed' if issues else 'passed', 'issues': issues,
              'sources': {f: digest(ROOT / f) for f in sources}, 'runs': rows, 'suites': suites,
              'evidence': [{'path': str(p), 'sha256': digest(p)} for p in args.evidence],
              'selected_cases': sorted(selected), 'excluded_runs': excluded}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'status': result['status'], 'runs': len(rows), 'suites': len(suites), 'issues': issues}, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
