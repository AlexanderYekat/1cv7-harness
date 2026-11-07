"""Independently verify task 032 partial-write markers, rollback, recovery and cleanup."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from verify_suite77 import verify as verify_suite

ROOT = Path(__file__).resolve().parents[1]
STATES = {
    'first': '0|0|1||source:3:30',
    'recover': '1|2|1|43>40:3:30;43>40:2:40;|source:3:30',
    'repost': '1|2|1|43>40:3:30;43>40:2:40;|source:5:50',
    'final': '1|2|1|43>40:5:50;43>40:2:40;|source:5:50',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def partial_issues(lines, mode, quantity, amount):
    """A failed post alone cannot prove any partial entry was actually written."""
    issues = []
    markers = [line for line in lines if line.startswith('HARNESS77-032-PARTIAL:')]
    expected = f'HARNESS77-032-PARTIAL:Harness77 {mode} 032:1:{quantity}:{amount}'
    if markers != [expected]:
        issues.append('missing, duplicate or incorrect partial-write readback')
    if mode == 'runtime':
        errors = [i for i, line in enumerate(lines)
                  if line.startswith('{Документ.ГотоваяПродукция.Модуль Документа(') and line.endswith(': Деление на 0')]
        if len(errors) != 1 or not markers or lines.index(markers[0]) >= errors[0]:
            issues.append('missing runtime error after partial-write readback')
    else:
        refusals = [i for i, line in enumerate(lines) if line == 'HARNESS77-032-REFUSAL']
        if len(refusals) != 1 or not markers or lines.index(markers[0]) >= refusals[0]:
            issues.append('missing refusal after partial-write readback')
    return issues


def verify(folder):
    result = verify_suite(folder, native=True)
    issues = result['issues']
    report = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))
    scenario_ids = [s['id'] for s in report['scenarios']]
    if scenario_ids not in (['runtime', 'refusal', 'repeat'], ['wrong', 'after-failure']):
        issues.append('unexpected scenario order or missing rollback cases')
    rows = []
    for scenario in report['scenarios']:
        def require(condition, message):
            if not condition:
                issues.append(scenario['id'] + ': ' + message)
        if not scenario.get('report'):
            require(False, 'missing child report')
            continue
        run = (folder / scenario['report']['path']).parent
        platform = json.loads((run / 'platform-result.json').read_text(encoding='utf-8'))
        require(platform['run_id'] == scenario['run_id'], 'foreign platform identity')
        operations = {op['name']: op for op in platform['operations']}
        commands = ['check', 'open', 'result']
        for id_ in STATES:
            commands += ['post-' + id_, 'verify-' + id_]
        commands += ['verify']
        require([op['name'] for op in platform['operations']] == commands, 'missing/duplicate/reordered operations')
        manifest = json.loads((run / 'native/ert-manifest.json').read_text(encoding='utf-8'))
        require(manifest['commands'] == commands, 'controller command order differs')
        events = [json.loads(line) for line in (run / 'native/ert-events.jsonl').read_text(encoding='utf-16').splitlines()]
        mode = 'refusal' if scenario['id'] == 'refusal' else 'runtime'
        markers = {}
        for id_, expected_state in STATES.items():
            failed = id_ in ('first', 'repost')
            post = operations.get('post-' + id_, {})
            expected_value = ('0|0' if id_ == 'first' else '0|1') if failed else '1|1'
            require(post.get('status') == ('failed' if failed else 'passed') and post.get('value') == expected_value,
                    'post-' + id_ + ': return/persisted flag differ')
            require(post.get('posting') == {'returned': int(expected_value[0]), 'posted': int(expected_value[2]), 'errors': []},
                    'post-' + id_ + ': structured result differs')
            diagnostics = post.get('diagnostics', [])
            require(([d['message'] for d in diagnostics] == ['Деление на 0']) if failed and mode == 'runtime'
                    else not diagnostics, 'post-' + id_ + ': unexpected diagnostics')
            readback = operations.get('verify-' + id_, {})
            require(readback.get('status') == 'passed' and readback.get('value') == expected_state,
                    'verify-' + id_ + ': persisted entries/input differ')
        require(operations.get('verify', {}).get('status') == 'passed' and
                operations.get('verify', {}).get('value') == STATES['final'], 'final persisted entries differ')
        protocols = {}
        for command in commands[3:]:
            event = [e for e in events if e.get('kind') == 'ert' and e.get('name') == command]
            require(len(event) == 1 and event[0]['run_id'] == scenario['run_id'], command + ': missing/foreign event')
            path = run / 'native' / manifest['protocol_paths'][command]
            raw = path.read_bytes()
            lines = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'cp1251').splitlines()
            require(lines[:1] == ['HARNESS77-BEGIN:' + scenario['run_id'] + ':' + command] and
                    lines[-1:] == ['HARNESS77-END:' + scenario['run_id'] + ':' + command], command + ': protocol identity')
            protocols[command] = digest(path)
            if command in ('post-first', 'post-repost'):
                quantity, amount = (3, 30) if command == 'post-first' else (5, 50)
                for issue in partial_issues(lines, mode, quantity, amount):
                    require(False, command + ': ' + issue)
                markers[command] = [line for line in lines if line.startswith('HARNESS77-032-PARTIAL:')]
            elif command.startswith('post-'):
                require(not any(line.startswith('HARNESS77-032-') for line in lines), command + ': unexpected injected failure')
            if len(event) == 1:
                response = event[0]['value'].splitlines()
                op = operations.get(command, {})
                if command.startswith('verify'):
                    values = [line[len('fixture-value:'):] for line in response if line.startswith('fixture-value:')]
                    require(values == [op.get('value')], command + ': response/report mismatch')
                else:
                    for prefix, field in [('post-return:', 'returned'), ('post-posted:', 'posted')]:
                        values = [line[len(prefix):].strip() for line in response if line.startswith(prefix)]
                        require(values == [str(op.get('posting', {}).get(field))], command + ': response/report mismatch')
        child = json.loads((run / 'run.json').read_text(encoding='utf-8'))
        tests = next(s for s in child['stages'] if s['stage'] == 'tests')['tests']
        require([t['name'] for t in tests] == commands[1:], 'missing/duplicate/reordered declared tests')
        require([t['name'] for t in tests if t.get('expectation_met') is not True] ==
                (['verify-repost'] if scenario['id'] == 'wrong' else []), 'unexpected failing expectations')
        require(child['status'] == ('failed' if scenario['id'] == 'wrong' else 'passed'), 'unexpected child status')
        rows.append({'id': scenario['id'], 'run_id': scenario['run_id'], 'status': child['status'],
                     'partial_write_readback': markers, 'states': {k: operations.get('verify-' + k, {}).get('value') for k in STATES},
                     'run_sha256': digest(run / 'run.json'), 'protocol_sha256': protocols,
                     'events_sha256': digest(run / 'native/ert-events.jsonl')})
    result.update(status='failed' if issues else 'passed', runs=rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', action='append', type=Path, required=True)
    parser.add_argument('--regression', type=Path, help='task 031 suite')
    parser.add_argument('--no-copy', type=Path, help='run directory of the preflight refusal')
    parser.add_argument('--test-log', action='append', type=Path, default=[], help='completed successful unittest log')
    parser.add_argument('--excluded-test-log', action='append', type=Path, default=[], help='preserve an unsuccessful sandbox attempt')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    suites = [verify(p.resolve()) for p in args.suite]
    regression = None
    if args.regression:
        from verify_lifecycle77 import verify as verify_lifecycle
        regression = verify_lifecycle(args.regression.resolve())
    refusal = None
    if args.no_copy:
        report = json.loads((args.no_copy / 'run.json').read_text(encoding='utf-8'))
        refusal = {'run_id': report['run_id'], 'run_sha256': digest(args.no_copy / 'run.json'),
                   'status': 'passed' if report['status'] == 'blocked' and report['exit_code'] == 2
                   and report['platform_checked'] is False and 'verified base copy' in (report.get('reason') or '')
                   and not (args.no_copy / 'native/debugger.log').exists() else 'failed'}
    sources = ['examples/posting-rollback/prepare.py', 'scripts/verify_rollback77.py',
               'research/forms/tests/test_rollback77.py', 'research/forms/fixture77.py', 'research/forms/form_launcher77.py']
    logs = []
    for path in args.test_log:
        content = path.read_text(encoding='utf-8')
        complete = re.search(r'(?m)^Ran ([1-9][0-9]*) tests? in [0-9.]+s$', content)
        passed = complete is not None and re.search(r'\nOK(?: \(skipped=\d+\))?\s*\Z', content) is not None
        logs.append({'name': path.name, 'sha256': digest(path), 'status': 'passed' if passed else 'failed',
                     'tests': int(complete[1]) if complete else None,
                     'issues': [] if passed else [path.name + ': unittest did not finish successfully']})
    checked = suites + logs + [s for s in (regression, refusal) if s is not None]
    issues = [issue for s in checked for issue in s.get('issues', [])]
    if refusal and refusal['status'] != 'passed':
        issues.append('no-copy preflight refusal was not confirmed')
    result = {'schema_version': 1, 'status': 'passed' if all(s['status'] == 'passed' for s in checked) else 'failed',
              'issues': issues, 'suites': suites, 'regression': regression, 'no_copy': refusal,
              'sources': {p: digest(ROOT / p) for p in sources},
              'test_logs': logs,
              'excluded_test_logs': [{'name': p.name, 'sha256': digest(p), 'excluded_from_passed_checks': True}
                                     for p in args.excluded_test_log]}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'status': result['status'], 'suites': len(suites), 'issues': issues}, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
