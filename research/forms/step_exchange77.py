"""045: bounded request-file access; controller calls and answer publication never replay."""
import json
import time

FAILURE = 'form-step-error.json'


def failure(out, run_id, number):
    """Read a fatal client diagnostic only for this run and outstanding step."""
    path = out / FAILURE
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding='utf-16'))
        if (value.get('schema_version') != 1 or value.get('run_id') != run_id
                or value.get('step') not in (None, number)
                or (value.get('step') is not None and type(value['step']) is not int)
                or type(value.get('controller_may_have_executed')) is not bool
                or type(value.get('error_number')) is not int
                or type(value.get('attempts')) is not int or value['attempts'] < 1
                or not all(isinstance(value.get(k), str) and value[k] for k in ('operation','path','error_description'))):
            raise ValueError('foreign or malformed exchange diagnostic')
        return value
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError) as error:
        raise ValueError('invalid exchange failure evidence: ' + str(error)) from error


def failed_trip(out, run_id, number):
    try:
        detail = failure(out, run_id, number)
    except ValueError as error:
        return {'returned': False, 'error': str(error)}
    if detail is not None:
        return {'returned': False,
                'error': f"step exchange {detail['operation']}: {detail['error_number']}: {detail['error_description']}",
                'exchange_error': detail}
    return None


def read_answer(path, run_id, number, *, clock=time.monotonic, pause=time.sleep):
    """A visible renamed answer can still be sharing-locked; never republish its request."""
    started, retries = clock(), []
    for attempt in range(1, 27):
        try:
            return path.read_text(encoding='utf-16'), retries, None
        except (OSError, UnicodeError) as error:
            elapsed = max(0, (clock() - started) * 1000)
            detail = dict(schema_version=1, run_id=run_id, step=number, operation='answer-read', path=str(path),
                          error_number=getattr(error, 'winerror', None) or getattr(error, 'errno', None) or 0,
                          error_source=type(error).__name__, error_description=str(error), attempts=attempt,
                          elapsed_ms=round(elapsed, 3), controller_may_have_executed=True)
            if not isinstance(error, PermissionError) or attempt == 26 or elapsed >= 1000:
                return None, retries, detail
            retries.append(detail)
            pause(.04)


CLIENT = '''
Dim h77StepNumber, h77StepControllerStarted

Function StepExchangeDetails(operation, path, number, source, description, attempts, elapsedMs)
    Dim stepJson, controllerJson
    stepJson = "null"
    If Not IsEmpty(h77StepNumber) Then stepJson = CStr(h77StepNumber)
    controllerJson = "false"
    If h77StepControllerStarted Then controllerJson = "true"
    StepExchangeDetails = "{""schema_version"":1,""run_id"":" & Quote(runId) & _
        ",""step"":" & stepJson & ",""operation"":" & Quote(operation) & ",""path"":" & Quote(path) & _
        ",""error_number"":" & CStr(number) & ",""error_source"":" & Quote(source) & _
        ",""error_description"":" & Quote(description) & ",""attempts"":" & CStr(attempts) & _
        ",""elapsed_ms"":" & Replace(CStr(elapsedMs), ",", ".") & _
        ",""controller_may_have_executed"":" & controllerJson & "}"
End Function

Sub StepExchangeFailure(operation, path, number, source, description, attempts, elapsedMs)
    Dim details, stream, errorPath
    On Error Resume Next
    Err.Clear
    details = StepExchangeDetails(operation, path, number, source, description, attempts, elapsedMs)
    Emit "blocked", "step-exchange", details, elapsedMs
    errorPath = fso.BuildPath(fso.GetParentFolderName(eventPath), "form-step-error.json")
    Set stream = fso.CreateTextFile(errorPath, False, True)
    If Err.Number = 0 Then
        stream.Write details
        stream.Close
    End If
    Err.Clear
    WScript.Quit 2
End Sub

Sub StepExchangeCheck(operation, path)
    Dim number, source, description
    number = Err.Number: source = Err.Source: description = Err.Description
    Err.Clear
    If number <> 0 Then StepExchangeFailure operation, path, number, source, description, 1, 0
End Sub

Function OpenStepRequest(path)
    Dim started, attempts, stream, number, source, description
    On Error Resume Next
    started = CDbl(Timer)
    For attempts = 1 To 26
        Err.Clear
        Set stream = fso.OpenTextFile(path, 1)
        number = Err.Number: source = Err.Source: description = Err.Description
        Err.Clear
        If number = 0 Then
            Set OpenStepRequest = stream
            Exit Function
        End If
        If number <> 70 Or attempts = 26 Or Elapsed(started) >= 1000 Then
            StepExchangeFailure "request-open", path, number, source, description, attempts, Elapsed(started)
        End If
        Emit "step-exchange-retry", "request-open", _
            StepExchangeDetails("request-open", path, number, source, description, attempts, Elapsed(started)), Elapsed(started)
        WScript.Sleep 40
    Next
End Function

Sub DeleteStepRequest(path)
    Dim started, attempts, number, source, description
    On Error Resume Next
    started = CDbl(Timer)
    For attempts = 1 To 26
        Err.Clear
        fso.DeleteFile path
        number = Err.Number: source = Err.Source: description = Err.Description
        Err.Clear
        If number = 0 Then Exit Sub
        If number <> 70 Or attempts = 26 Or Elapsed(started) >= 1000 Then
            StepExchangeFailure "request-delete", path, number, source, description, attempts, Elapsed(started)
        End If
        Emit "step-exchange-retry", "request-delete", _
            StepExchangeDetails("request-delete", path, number, source, description, attempts, Elapsed(started)), Elapsed(started)
        WScript.Sleep 40
    Next
End Sub

Sub AwaitClick()
    Dim donePath, requestPath, waitStarted, request, number, answer, stream, folder, answerPath, protocol
    On Error Resume Next
    folder = fso.GetParentFolderName(eventPath)
    donePath = fso.BuildPath(folder, "__DONE__")
    requestPath = fso.BuildPath(folder, "__REQUEST__")
    waitStarted = CDbl(Timer)
    Do While Not fso.FileExists(donePath)
        If fso.FileExists(requestPath) Then
            h77StepNumber = Empty
            h77StepControllerStarted = False
            Set stream = OpenStepRequest(requestPath)
            request = stream.ReadLine
            StepExchangeCheck "request-read", requestPath
            stream.Close
            StepExchangeCheck "request-close", requestPath
            Set stream = Nothing
            If Left(request, Len(runId) + 1) <> runId & ":" Then
                StepExchangeFailure "request-run-id", requestPath, 0, "harness77", "foreign step request", 1, 0
            End If
            number = CLng(Mid(request, Len(runId) + 2))
            StepExchangeCheck "request-number", requestPath
            h77StepNumber = number
            answerPath = fso.BuildPath(folder, "form-step-" & number)
            If fso.FileExists(answerPath & "-done") Or fso.FileExists(answerPath & ".tmp") Then
                StepExchangeFailure "duplicate-step", answerPath, 0, "harness77", "step response already exists", 1, 0
            End If
            DeleteStepRequest requestPath
            protocol = fso.BuildPath(fso.GetParentFolderName(evidencePath), "step-" & number & ".txt")
            h77StepControllerStarted = True
            answer = controller.Harness77Step(number, protocol, runId & ":step:" & number)
            StepExchangeCheck "controller-call", protocol
            Set stream = fso.CreateTextFile(answerPath & ".tmp", False, True)
            StepExchangeCheck "answer-create", answerPath & ".tmp"
            stream.Write CStr(answer)
            StepExchangeCheck "answer-write", answerPath & ".tmp"
            stream.Close
            StepExchangeCheck "answer-close", answerPath & ".tmp"
            Set stream = Nothing
            fso.MoveFile answerPath & ".tmp", answerPath & "-done"
            StepExchangeCheck "answer-publish", answerPath & "-done"
            Emit "phase", "step-" & number, "ok", Elapsed(waitStarted)
            waitStarted = CDbl(Timer)
        End If
        WScript.Sleep 20
        If Elapsed(waitStarted) > __WAIT_MS__ Then
            Emit "phase", "click-wait", "timeout", Elapsed(waitStarted)
            Exit Sub
        End If
    Loop
    Emit "phase", "click-wait", "ok", Elapsed(waitStarted)
End Sub
'''


def client(done, request, wait_ms):
    return CLIENT.replace('__DONE__', done).replace('__REQUEST__', request).replace('__WAIT_MS__', str(wait_ms))
