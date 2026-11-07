"""Independently read task 031 native responses, persisted entries, cleanup and JUnit."""
import argparse
import hashlib
import json
from pathlib import Path
from verify_suite77 import verify as verify_suite

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(folder):
    result = verify_suite(folder, native=True)
    issues = result['issues']
    report = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))
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
        operations = {op['name']: op for op in platform['operations']}
        expected = [('post-initial', '1|1', '1|2|1|43>40:3:30;43>40:2:40;'),
                    ('post-repeat', '1|1', '1|2|1|43>40:3:30;43>40:2:40;'),
                    ('post-changed', '1|1', '1|2|1|43>40:5:50;43>40:2:40;'),
                    ('unpost-cancel', '1|0', '0|0|1|'),
                    ('post-restored', '1|1', '1|2|1|43>40:5:50;43>40:2:40;')]
        manifest = json.loads((run / 'native/ert-manifest.json').read_text(encoding='utf-8'))
        events = [json.loads(line) for line in (run / 'native/ert-events.jsonl').read_text(encoding='utf-16').splitlines()]
        commands = ['check', 'open', 'result']
        for command, value, entries in expected:
            verify_command = 'verify-' + command.split('-', 1)[1]
            commands += [command, verify_command]
            operation = operations.get(command, {})
            failure = scenario['id'] == 'error' and command == 'post-repeat'
            require(operation.get('status') == ('failed' if failure else 'passed'), command + ': operation status')
            if failure:
                require(bool(operation.get('posting', {}).get('errors') or operation.get('diagnostics')), command + ': missing error')
            else:
                require(operation.get('value') == value, command + ': return/state mismatch')
            check = operations.get(verify_command, {})
            require(check.get('status') == 'passed' and check.get('value') == entries, verify_command + ': entries differ')
        commands += ['verify']
        require(manifest['commands'] == commands, 'operation order differs')
        require(operations.get('verify', {}).get('value') == expected[-1][2], 'final entries differ')
        for command in commands[3:]:
            event = [e for e in events if e.get('kind') == 'ert' and e.get('name') == command]
            require(len(event) == 1 and event[0]['run_id'] == scenario['run_id'], command + ': missing/foreign response')
            path = run / 'native' / manifest['protocol_paths'][command]
            raw = path.read_bytes()
            lines = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'cp1251').splitlines()
            require(lines[:1] == ['HARNESS77-BEGIN:' + scenario['run_id'] + ':' + command] and
                    lines[-1:] == ['HARNESS77-END:' + scenario['run_id'] + ':' + command], command + ': protocol identity')
            if len(event) == 1:
                response = event[0]['value'].splitlines()
                op = operations.get(command, {})
                if command.startswith('verify'):
                    values = [line[len('fixture-value:'):] for line in response if line.startswith('fixture-value:')]
                    require(values == [op.get('value')], command + ': response/report mismatch')
                else:
                    for prefix, field in [('post-return:', 'returned'), ('post-posted:', 'posted')]:
                        values = [line[len(prefix):].strip() for line in response if line.startswith(prefix)]
                        field_value = op.get('posting', {}).get(field)
                        require(values == ([] if field_value is None else [str(field_value)]), command + ': response/report mismatch')
        child = json.loads((run / 'run.json').read_text(encoding='utf-8'))
        tests = next(s for s in child['stages'] if s['stage'] == 'tests')['tests']
        unmet = [t['name'] for t in tests if t.get('expectation_met') is not True]
        require(unmet == (['verify-changed'] if scenario['id'] == 'wrong' else []), 'unexpected failing checks')
        require(child['status'] == ('failed' if scenario['id'] == 'wrong' else 'passed'), 'unexpected child status')
        rows.append({'id': scenario['id'], 'run_id': scenario['run_id'], 'status': child['status'],
                     'entries': {k: v.get('value') for k, v in operations.items() if k.startswith('verify')},
                     'run_sha256': digest(run / 'run.json')})
    result.update(status='failed' if issues else 'passed', runs=rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', action='append', type=Path, required=True)
    parser.add_argument('--regression', type=Path, help='task 030 suite, checked for native cleanup and JUnit')
    parser.add_argument('--excluded-suite', type=Path, help='preserve an open_timeout regression attempt separately')
    parser.add_argument('--no-copy', type=Path, help='run directory of the expected preflight refusal')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    suites = [verify(p.resolve()) for p in args.suite]
    regression = verify_suite(args.regression.resolve(), native=True) if args.regression else None
    excluded = None
    if args.excluded_suite:
        folder = args.excluded_suite.resolve()
        excluded = verify_suite(folder, native=True)
        suite = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))
        allowed = []
        excluded['excluded_runs'] = []
        for row in suite['scenarios']:
            if row['status'] == 'blocked' and row.get('report'):
                run = folder / row['report']['path']
                child = json.loads(run.read_text(encoding='utf-8'))
                if child.get('reason') == 'open_timeout' and not child['platform_checked']:
                    allowed.append(row['id'] + ': no native check')
                    excluded['excluded_runs'].append({'run_id': child['run_id'], 'reason': child['reason'],
                                                     'run_sha256': digest(run), 'shutdown': child['shutdown']})
        excluded['issues'] = [issue for issue in excluded['issues'] if issue not in allowed]
        if not excluded['excluded_runs']:
            excluded['issues'].append('no open_timeout attempt found')
        excluded.update(status='failed' if excluded['issues'] else 'passed', excluded_from_functional_results=True)
    refusal = None
    if args.no_copy:
        report = json.loads((args.no_copy / 'run.json').read_text(encoding='utf-8'))
        refusal = {'run_id': report['run_id'], 'run_sha256': digest(args.no_copy / 'run.json'),
                   'status': 'passed' if report['status'] == 'blocked' and report['exit_code'] == 2
                   and report['platform_checked'] is False and 'verified base copy' in (report.get('reason') or '')
                   and not (args.no_copy / 'native/debugger.log').exists() else 'failed'}
    sources = ['research/forms/fixture77.py', 'research/forms/form_launcher77.py',
               'research/forms/tests/test_fixture77.py', 'examples/document-lifecycle/prepare.py',
               'scripts/verify_lifecycle77.py']
    checked = suites + [s for s in (regression, refusal, excluded) if s is not None]
    result = {'schema_version': 1, 'status': 'passed' if all(s['status'] == 'passed' for s in checked) else 'failed',
              'suites': suites, 'regression': regression, 'no_copy': refusal, 'excluded_regression': excluded,
              'test_logs': {p: digest(ROOT / '.artifacts' / p) for p in
                            ('stage31-forms-tests.txt', 'stage31-product-tests.txt', 'stage31-platform-tests.txt')
                            if (ROOT / '.artifacts' / p).is_file()},
              'sources': {p: digest(ROOT / p) for p in sources}}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
