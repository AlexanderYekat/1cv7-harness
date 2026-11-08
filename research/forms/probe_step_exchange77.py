"""Real 32-bit Windows FSO exchange and controlled sharing failures; no 1C or base."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

import scenario77
import step_exchange77
from form_launcher77 import FormWatcher

HERE = Path(__file__).resolve().parent
MODES = ('request-open-transient', 'request-open-persistent', 'request-delete-transient',
         'request-delete-persistent', 'request-open-missing', 'request-read-empty',
         'answer-create', 'answer-publish', 'foreign-request', 'duplicate-step',
         'python-answer-read-transient', 'python-answer-read-persistent')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def client_source(hook=None):
    utilities = (HERE.parent / 'platform77/module_suite77.vbs').read_text('utf-8')
    utilities = '\n'.join(re.search(r'(?ms)^(?:Function|Sub) ' + name + r'\(.*?^End (?:Function|Sub)', utilities).group(0)
                          for name in ('Quote', 'Elapsed', 'Emit', 'Fail', 'CheckCOM'))
    # This test-only marker observes a retry before the parent releases its handle.
    utilities = utilities.replace('    If kind = "complete" Then', '''    If kind = "step-exchange-retry" Then
        If Not fso.FileExists(WScript.Arguments(0) & "\\retry-seen") Then
            Set probeMarker = fso.CreateTextFile(WScript.Arguments(0) & "\\retry-seen", False)
            probeMarker.Close
        End If
    End If
    If kind = "complete" Then''')
    body = scenario77.client('form-click-done', 60000)
    if hook:
        target = {'request-open-missing': '            Set stream = OpenStepRequest(requestPath)',
                  'answer-create': '            Set stream = fso.CreateTextFile(answerPath & ".tmp", False, True)',
                  'answer-publish': '            fso.MoveFile answerPath & ".tmp", answerPath & "-done"'}[hook]
        if body.count(target) != 1:
            raise ValueError('unexpected client layout for controlled observation')
        body = body.replace(target, f'            ProbePause "{hook}"\n' + target)
    prefix = '''Option Explicit
Dim fso, runId, eventPath, evidencePath, controller, h77EventStream, h77LogStream, probeMarker, probeCalls, probeStartTime
Set fso = CreateObject("Scripting.FileSystemObject")
runId = "probe45"
eventPath = WScript.Arguments(0) & "\\ert-events.jsonl"
evidencePath = WScript.Arguments(0) & "\\Протоколы проверки\\result.txt"
probeCalls = 0
Set controller = New ControllerStub
Class ControllerStub
    Public Function Harness77Step(number, protocol, marker)
        Dim s
        probeCalls = probeCalls + 1
        Set s = fso.CreateTextFile(WScript.Arguments(0) & "\\controller-calls.txt", True)
        s.Write CStr(probeCalls)
        s.Close
        Set s = fso.CreateTextFile(protocol, True, True)
        s.Write "HARNESS77-STEP:" & marker
        s.Close
        Harness77Step = "value:" & CStr(number)
    End Function
End Class
Sub ProbePause(name)
    Dim marker, started
    Set marker = fso.CreateTextFile(WScript.Arguments(0) & "\\" & name & "-ready", False)
    marker.Close
    started = CDbl(Timer)
    Do While Not fso.FileExists(WScript.Arguments(0) & "\\" & name & "-continue")
        WScript.Sleep 10
        If Elapsed(started) > 10000 Then Fail "probe-hook-timeout", name
    Loop
End Sub
'''
    return prefix + utilities + '''
On Error Resume Next
probeStartTime = CDbl(Timer)
Do While Not fso.FileExists(WScript.Arguments(0) & "\\probe-start")
    WScript.Sleep 10
    If Elapsed(probeStartTime) > 10000 Then Fail "probe-start-timeout", "parent did not publish"
Loop
AwaitClick
CheckCOM "outer-result"
Emit "complete", "probe", "done", 0
''' + body


def start(folder, hook=None):
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'Протоколы проверки').mkdir()
    script = folder / 'client.vbs'
    script.write_text(client_source(hook), encoding='utf-16')
    host = Path(os.environ['WINDIR']) / 'SysWOW64/cscript.exe'
    process = subprocess.Popen([str(host), '//nologo', str(script), str(folder)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    return process


def wait_path(path, process, timeout=10):
    until = time.monotonic() + timeout
    while not path.exists():
        if process.poll() is not None or time.monotonic() >= until:
            raise RuntimeError('probe observation missing: ' + str(path))
        time.sleep(.01)


def hold(path, exclusive=False):
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0 if exclusive else 3, None, 3, 0, None)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    return kernel, handle


def collect(folder, process, number=-1):
    stdout, stderr = process.communicate(timeout=15)
    (folder / 'stdout.txt').write_bytes(stdout)
    (folder / 'stderr.txt').write_bytes(stderr)
    events = [json.loads(line) for line in (folder / 'ert-events.jsonl').read_text('utf-16').splitlines()]
    failure = step_exchange77.failure(folder, 'probe45', number)
    calls_path = folder / 'controller-calls.txt'
    return dict(exit_code=process.returncode, calls=int(calls_path.read_text('ascii')) if calls_path.exists() else 0,
                events=events, failure=failure, client_sha256=digest(folder / 'client.vbs'))


def controlled(folder, mode):
    if mode.startswith('python-answer-read-'):
        return reader_control(folder, mode)
    hook = mode if mode in ('request-open-missing', 'answer-create', 'answer-publish') else None
    # The host has not received a request yet, so seed and lock it before serving.
    process = start(folder, hook)
    handles = []
    issues = []
    started = time.monotonic()
    try:
        request = folder / scenario77.REQUEST
        request.write_text('foreign:-1' if mode == 'foreign-request' else '' if mode == 'request-read-empty' else 'probe45:-1', encoding='ascii')
        if mode.startswith('request-open-') and mode != 'request-open-missing':
            handles.append(hold(request, exclusive=True))
        if mode.startswith('request-delete-'):
            handles.append(hold(request))
        if mode == 'duplicate-step':
            (folder / 'form-step--1-done').write_text('value:old', encoding='utf-16')
        # Ensure the file cannot be consumed before a controlled lock/fixture is ready.
        (folder / 'probe-start').write_text('go', encoding='ascii')
        if mode.endswith('-transient'):
            wait_path(folder / 'retry-seen', process)
            kernel, handle = handles.pop()
            kernel.CloseHandle(handle)
        if hook:
            wait_path(folder / (hook + '-ready'), process)
            if mode == 'request-open-missing': request.unlink()
            elif mode == 'answer-create': (folder / 'form-step--1.tmp').mkdir()
            else: handles.append(hold(folder / 'form-step--1.tmp'))
            (folder / (hook + '-continue')).write_text('go', encoding='ascii')
        if mode.endswith('-transient'):
            wait_path(folder / 'form-step--1-done', process)
            answer = scenario77.answer((folder / 'form-step--1-done').read_text('utf-16'))
            if answer != {'value': '-1'}: issues.append('wrong answer after release')
            (folder / 'form-click-done').write_text('done', encoding='ascii')
        result = collect(folder, process)
    finally:
        for kernel, handle in handles: kernel.CloseHandle(handle)
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
    result['duration_s'] = round(time.monotonic() - started, 3)
    retries = [e for e in result['events'] if e['kind'] == 'step-exchange-retry']
    transient = mode.endswith('-transient')
    expected_operation = {'request-open-transient':'request-open','request-open-persistent':'request-open',
        'request-delete-transient':'request-delete','request-delete-persistent':'request-delete',
        'request-open-missing':'request-open','request-read-empty':'request-read','answer-create':'answer-create',
        'answer-publish':'answer-publish','foreign-request':'request-run-id','duplicate-step':'duplicate-step'}[mode]
    expected_calls = 1 if transient or mode.startswith('answer-') else 0
    if result['calls'] != expected_calls: issues.append('controller count differs; possible replay')
    if result['exit_code'] != (0 if transient else 2): issues.append('wrong host outcome')
    if transient:
        if result['failure'] or not retries: issues.append('transient lock not observed/recovered')
    else:
        detail = result['failure']
        if (not detail or detail['operation'] != expected_operation
                or detail['controller_may_have_executed'] is not mode.startswith('answer-')):
            issues.append('missing/wrong diagnostic context')
        blocked = [e for e in result['events'] if e['kind'] == 'blocked']
        if len(blocked) != 1 or json.loads(blocked[0]['value']) != detail:
            issues.append('event/sidecar diagnostic differ')
        if mode.endswith('-persistent'):
            if not detail or detail['error_number'] != 70 or not 2 <= detail['attempts'] <= 26 or result['duration_s'] > 10:
                issues.append('persistent lock not bounded')
        elif retries:
            issues.append('unexpected retry outside pre-controller request access')
    result.update(mode=mode, status='failed' if issues else 'passed', issues=issues)
    write_json(folder / 'summary.json', result)
    return result


def reader_control(folder, mode):
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / 'form-step--1-done'
    path.write_text('value:-1', encoding='utf-16')
    before = digest(path)
    kernel, handle = hold(path, exclusive=True)
    released = False
    def release_then_pause(seconds):
        nonlocal released
        kernel.CloseHandle(handle)
        released = True
        time.sleep(seconds)
    transient = mode.endswith('-transient')
    try:
        if transient:
            answer, retries, error = step_exchange77.read_answer(path, 'probe45', -1, pause=release_then_pause)
        else:
            answer, retries, error = step_exchange77.read_answer(path, 'probe45', -1)
    finally:
        if not released: kernel.CloseHandle(handle)
    issues = []
    if not retries: issues.append('real sharing denial not observed')
    if transient:
        if answer != 'value:-1' or error is not None: issues.append('read did not recover after release')
    elif answer is not None or not error or not error['controller_may_have_executed'] or not 1 <= error['attempts'] <= 26:
        issues.append('persistent read denial not refused with uncertain execution')
    if digest(path) != before or (folder / scenario77.REQUEST).exists():
        issues.append('answer was modified or request replayed')
    result = dict(mode=mode, status='failed' if issues else 'passed', issues=issues, calls=0,
                  answer=answer, retries=retries, failure=error, answer_sha256=before)
    write_json(folder / 'summary.json', result)
    return result


def stress(folder, count):
    process = start(folder)
    stop = threading.Event()
    watcher = FormWatcher.__new__(FormWatcher)
    watcher.out, watcher.lifecycle, watcher.stopped = folder, {'run_id':'probe45'}, threading.Event()
    def monitor():
        process.wait()
        if not stop.is_set(): watcher.stopped.set()
    threading.Thread(target=monitor, daemon=True).start()
    rows, issues = [], []
    try:
        (folder / 'probe-start').write_text('go', encoding='ascii')
        for index in range(count):
            number = -111000-index
            trip = watcher.round_trip(number)
            rows.append(dict(number=number, **trip))
            if trip.get('value') != str(number) or not trip.get('complete'):
                issues.append('incomplete/failed/foreign response')
                break
            if (index+1) % 250 == 0: print('completed', index+1, flush=True)
        stop.set()
        (folder / 'form-click-done').write_text('done', encoding='ascii')
        result = collect(folder, process, rows[-1]['number'] if rows else -1)
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
    if result['exit_code'] != 0 or result['calls'] != count or len(rows) != count:
        issues.append('host/count mismatch; possible replay')
    result.update(status='failed' if issues else 'passed', issues=issues, requested=count, rows=rows)
    write_json(folder / 'summary.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['controlled','stress'], default='controlled')
    parser.add_argument('--count', type=int, default=5000)
    args = parser.parse_args()
    if os.name != 'nt': parser.error('real Windows FSO required')
    if not 1 <= args.count <= 20000: parser.error('count must be 1..20000')
    output = args.output.resolve()
    if args.mode == 'stress':
        results = [stress(output, args.count)]
    else:
        output.mkdir(parents=True, exist_ok=False)
        results = []
        for mode in MODES:
            result = controlled(output / mode, mode)
            results.append(result)
            print(mode, result['status'], result['issues'], flush=True)
    issues = [i for result in results for i in result['issues']]
    summary = dict(status='failed' if issues else 'passed', issues=issues,
        cases=[{k:v for k,v in result.items() if k not in ('events','rows')} for result in results],
        sources={str(p.relative_to(HERE.parents[1])):digest(p) for p in (Path(__file__), HERE/'step_exchange77.py', HERE/'scenario77.py', HERE/'form_launcher77.py')})
    write_json(output / 'verification.json', summary)
    print(json.dumps(dict(status=summary['status'], issues=issues)), flush=True)
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
