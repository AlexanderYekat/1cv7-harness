"""Re-read task 028 runs, references, windows, copy preservation, and earlier scenario regressions.

Use --evidence once per final series, --example-run twice, and
--regression 027=RUN_ID --regression 026=RUN_ID --regression 025=RUN_ID.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'research/forms'))
import probe_reference77 as probes


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def example(folder):
    profile = tomllib.loads((ROOT / 'examples' / folder / 'scenario.toml').read_text(encoding='utf-8'))
    value = {'id': folder, 'parameters': {'steps': profile['platform']['parameters']['steps']}}
    verification = next((t for t in profile['platform']['tests'] if t['command'] == 'verify'), None)
    if verification:
        value['verify_value'] = verification['expect_value']
    return value


def check(case, run_id, expected_hash=None):
    folder = ROOT / '.artifacts/runs' / run_id
    observed = probes.base.observe(folder)
    issues, choices = [], []
    if probes.scenario.judge(case, observed) != 'confirmed':
        issues.append('the run does not match its declared expectations')
    run_hash = digest(folder / 'run.json')
    if expected_hash and expected_hash != run_hash:
        issues.append('run.json changed since the series')
    copied = observed['copy']
    if not copied.get('source_unchanged') or not (copied.get('removal') or {}).get('removed'):
        issues.append('source preservation or copy removal not confirmed')
    if case.get('blocked'):
        if (folder / 'native/debugger.log').exists():
            issues.append('1C started for a case refused before launch')
    elif observed['shutdown'] != 'passed':
        issues.append('normal shutdown not confirmed')
    platform = json.loads((folder / 'platform-result.json').read_text(encoding='utf-8'))
    if platform.get('base_list', {}).get('unchanged') is False:
        issues.append('the registered base list changed')
    result = observed['operations'].get('result') or {}
    for step in result.get('steps') or []:
        action = step.get('action') or {}
        if (step.get('dismissed') or {}).get('open'):
            issues.append(f"step {step['index']}: a modal window stayed open")
        if step.get('pending_choice_cleanup') and not step['pending_choice_cleanup'].get('closed'):
            issues.append(f"step {step['index']}: the pending choice stayed open")
        for name in ('choice_cleanup', 'nested_cleanup'):
            if name in action and action[name].get('closed') is not True:
                issues.append(f"step {step['index']}: {name} did not close the choice")
        if step['kind'] != 'choose':
            continue
        window = action.get('choice_window') or {}
        calls = step.get('calls') or []
        context = next((c.get('choice_hwnd') for c in calls if 'choice_hwnd' in c), None)
        if window and context is not None and context != window['frame']['hwnd']:
            issues.append(f"step {step['index']}: context/window mismatch")
        if action.get('choice_verified') and (not window or context != window['frame']['hwnd']
                                               or not any(c.get('choice_ready') == 1 for c in calls)):
            issues.append(f"step {step['index']}: choice context or cursor evidence missing")
        if step['status'] == 'passed' and not step.get('modal'):
            if not action.get('choice_verified') or not action.get('choice_closed'):
                issues.append(f"step {step['index']}: returned reference or closed choice not confirmed")
        choices.append({'step': step['index'], 'status': step['status'], 'issue': step.get('issue'),
                        'frame': window.get('frame'), 'context_hwnd': context,
                        'current': action.get('choice_current'), 'returned': action.get('choice_value'),
                        'verified': action.get('choice_verified'), 'closed': action.get('choice_closed'),
                        'cleanup': action.get('choice_cleanup')})
    # A choose with a formula dialog is judged at the end of the chain.
    for step in result.get('steps') or []:
        action = step.get('action') or {}
        if step['kind'] == 'dialog' and step['status'] == 'passed' and step.get('last') and action.get('choice'):
            if not action.get('choice_verified') or not action.get('choice_closed'):
                issues.append('dialog chain did not confirm the returned reference')
    return {'id': case['id'], 'run_id': run_id, 'run_sha256': run_hash,
            'status': 'failed' if issues else 'passed', 'issues': issues,
            'tests': observed['tests'], 'form_issues': result.get('form_issues'), 'choices': choices,
            'source_unchanged': copied.get('source_unchanged'), 'copy_removed': copied.get('removal'),
            'shutdown': observed['shutdown']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', action='append', required=True, type=Path)
    parser.add_argument('--example-run', action='append', required=True)
    parser.add_argument('--regression', action='append', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    latest, series = {}, []
    for path in args.evidence:
        evidence = json.loads(path.read_text(encoding='utf-8'))
        latest.update({row['id']: row for row in evidence['cases']})
        series.append({'file': path.name, 'sha256': digest(path), 'checks': evidence['series']})
    expected = {c['id']: c for c in probes.CASES}
    missing = sorted(set(expected) - set(latest))
    rows = [check(expected[name], row['run_id'], row['run_json_sha256']) for name, row in latest.items() if name in expected]
    examples = [check(example('reference-choice'), run_id) for run_id in args.example_run]
    regressions = []
    folders = {'027': 'table-part', '026': 'modal-dialogs', '025': 'form-steps'}
    for item in args.regression:
        task, _, run_id = item.partition('=')
        regressions.append(dict(check(example(folders[task]), run_id), task=task))
    ok = not missing and len(examples) >= 2 and all(all(s['checks'].values()) for s in series) \
        and sorted(r['task'] for r in regressions) == sorted(folders) \
        and all(r['status'] == 'passed' for r in rows + examples + regressions)
    value = {'schema_version': 1, 'scope': probes.SCOPE, 'status': 'passed' if ok else 'failed',
             'missing': missing, 'series': series, 'cases': rows, 'examples': examples, 'regressions': regressions,
             'sources': {name: digest(ROOT / name) for name in (
                 'research/forms/choice77.py', 'research/forms/scenario77.py', 'research/forms/form_launcher77.py',
                 'research/forms/probe_reference77.py', 'examples/reference-choice/scenario.toml',
                 'examples/reference-choice/prepare.py')}}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=1)
    print(json.dumps({'status': value['status'], 'cases': len(rows), 'examples': len(examples),
                      'regressions': len(regressions), 'missing': missing, 'output': str(args.output)}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
