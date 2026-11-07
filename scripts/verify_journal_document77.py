"""Independently verify task 034 journal creation, UI provenance, readback and cleanup."""
import argparse
import json
from pathlib import Path
import re
from verify_document_form77 import ROOT, digest, excluded as document_excluded, step_issues as document_steps, check as document_check
from verify_suite77 import verify as verify_suite

READBACK = '1|1|Harness77 журнал 034|2|3:10:30;2:20:40;|1|2|43>40:3:30;43>40:2:40;'


def step_issues(records, kind):
    issues = []
    def require(condition, message):
        if not condition:
            issues.append(message)
    creates = [r for r in records if r.get('kind') == 'create']
    require(len(creates) == 1 and records[0] is creates[0], 'creation must start in journal exactly once')
    if len(creates) != 1:
        return issues
    create = creates[0]
    require(create.get('action', {}).get('key') == 'Insert' and create['action'].get('returned') is True
            and create['action'].get('id') == 4151 and create['action'].get('identity_rechecked') is True,
            'no owned journal Insert action')
    chooser = create.get('kind_window') or {}
    require(chooser.get('text') == 'Выбор вида документа', 'native document-kind chooser missing')
    selection = create.get('kind_selection') or {}
    require(selection.get('names', []).count('Гот.прод. (Передача готовой продукции на склад)') == 1
            and selection.get('caption') == 'Гот.прод. (Передача готовой продукции на склад)'
            and selection.get('answer', {}).get('requested') is True
            and selection.get('answer', {}).get('button', {}).get('id') == 1,
            'document kind was not uniquely selected and confirmed through UI')
    trip = create.get('round_trip') or {}
    chain = create.get('created_form', {}).get('chain', [])
    require(trip.get('journal_new') == '1' and not trip.get('journal_error')
            and create.get('new_form_verified') is True
            and str(trip.get('journal_hwnd')) in [str(w['hwnd']) for w in chain[:2]],
            'new unsaved document context/window not independently matched')
    require(create.get('status') == 'passed', 'journal creation step failed')
    captures = [r for r in records if r.get('kind') == 'created']
    if kind == 'cancel':
        require(not captures and not any(r.get('kind') == 'reopen' for r in records), 'cancel unexpectedly captured a document')
        require([r.get('target') for r in records if r.get('kind') == 'click'] == ['Закрыть'], 'cancel must close through UI')
        dialogs = [r for r in records if r.get('kind') == 'dialog']
        require(len(dialogs) == 1 and dialogs[0].get('target') == 'Сохранить Документ?'
                and dialogs[0].get('button') == 'Нет' and dialogs[0].get('answer', {}).get('requested') is True
                and dialogs[0].get('form_open') is False and dialogs[0].get('closes') is True,
                'cancel did not reject saving and close the document')
        require(all(r.get('status') == 'passed' for r in records), 'cancel scenario failed')
        return issues
    require(len(captures) == 1, 'exactly one saved reference capture required')
    if captures:
        saved = captures[0]
        require(saved.get('status') == 'passed' and saved.get('round_trip', {}).get('journal_saved') == '1'
                and bool(saved.get('round_trip', {}).get('journal_reference')),
                'saved created reference missing')
        reopen = next((r for r in records if r.get('kind') == 'reopen'), {})
        require(saved['index'] < reopen.get('index', 0), 'reference was not captured before reopening')
    issues += document_steps(records, kind == 'wrong-reopen', comment='Harness77 журнал 034')
    return issues


def check(folder, kind='success', expected_hash=None):
    result = document_check(folder, kind, expected_hash, readback='0|none' if kind == 'cancel' else READBACK,
                            step_validator=step_issues)
    text = (folder / 'native/ert-controller.1s').read_text(encoding='utf-8')
    setup = text.split('Функция Harness77ПодготовитьДанные()', 1)[1].split('КонецФункции', 1)[0]
    if re.search(r'Док77\.(Новый|Записать|Провести|НоваяСтрока)\(', setup):
        result['issues'].append('fixture setup creates or modifies a document')
    if 'Ссылка77.Выбран() <> 0' not in text or (kind != 'cancel' and 'Док77Чтения.НайтиДокумент(Ссылка77)' not in text):
        result['issues'].append('new/saved reference readback guards missing')
    form = json.loads((folder / 'form/form-window.json').read_text(encoding='utf-8'))
    if any(w['hwnd'] == form['chain'][0]['hwnd'] for w in (form.get('steps') or [{}])[0].get('created_form', {}).get('chain', [])[:2]):
        result['issues'].append('journal window reused as the new document')
    return result


def excluded(folder):
    report = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    if not (folder / 'native/ert-events.jsonl').exists() and report.get('platform_checked') is False:
        stage = next(s for s in report['stages'] if s['stage'] == 'platform_check')
        if stage.get('status') == 'skipped' and not stage.get('base_copy'):
            return {'run_id': report['run_id'], 'status': report['status'], 'reason': report['reason'],
                    'run_sha256': digest(folder / 'run.json'), 'native_not_started': True,
                    'cleanup_verified': True, 'issues': []}
    result = document_excluded(folder)
    result['forced_cleanup'] = (report.get('shutdown') or {}).get('forced_cleanup')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, action='append', required=True)
    parser.add_argument('--test-log', type=Path, action='append', default=[])
    parser.add_argument('--excluded-test-log', type=Path, action='append', default=[])
    parser.add_argument('--blocked-run', type=Path)
    parser.add_argument('--excluded-run', type=Path, action='append', default=[])
    parser.add_argument('--regression-report', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows, suites, issues, logs, regressions = [], [], [], [], []
    for folder in args.suite:
        suites.append(verify_suite(folder.resolve(), native=True))
        report = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))
        for row in report['scenarios']:
            kind = row['id'] if row['id'].startswith('wrong') or row['id'] == 'cancel' else 'success'
            rows.append(check((folder / row['report']['path']).parent, kind, row['report']['sha256']))
    for path in args.test_log:
        value = path.read_text(encoding='utf-8', errors='replace')
        if not value.rstrip().endswith(('OK', 'OK (skipped=3)')) or '\nRan ' not in value:
            issues.append(str(path) + ': tests did not pass')
        logs.append({'path': str(path), 'sha256': digest(path)})
    attempts = [excluded(folder) for folder in args.excluded_run]
    blocked = None
    if args.blocked_run:
        path = args.blocked_run / 'run.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        valid = (report['status'] == 'blocked' and report['platform_checked'] is False
                 and 'verified base copy' in str(report['reason'])
                 and not (args.blocked_run / 'native/ert-events.jsonl').exists())
        if not valid:
            issues.append('no-copy guard not confirmed before native session')
        blocked = {'run_id': report['run_id'], 'sha256': digest(path), 'verified': valid}
    for path in args.regression_report:
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('status') != 'passed' or value.get('issues'):
            issues.append(str(path) + ': regression did not pass')
        regressions.append({'path': str(path), 'sha256': digest(path)})
    issues += [r['run_id'] + ': ' + i for r in rows for i in r['issues']]
    issues += [s['suite_id'] + ': ' + i for s in suites for i in s['issues']]
    issues += [r['run_id'] + ': ' + i for r in attempts for i in r['issues']]
    sources = ['research/forms/scenario77.py', 'research/forms/form_launcher77.py', 'research/forms/fixture77.py',
               'research/forms/journal77.py', 'research/forms/tests/test_journal77.py',
               'examples/journal-document/scenario.toml', 'examples/journal-document/prepare.py',
               'scripts/verify_document_form77.py', 'scripts/verify_journal_document77.py']
    result = {'schema_version': 1, 'status': 'failed' if issues else 'passed', 'issues': issues,
              'runs': rows, 'suites': suites, 'test_logs': logs, 'excluded_attempts': attempts,
              'excluded_test_logs': [{'path': str(p), 'sha256': digest(p)} for p in args.excluded_test_log],
              'blocked_run': blocked, 'regressions': regressions, 'sources': {f: digest(ROOT / f) for f in sources}}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'status': result['status'], 'runs': len(rows), 'issues': issues}, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
