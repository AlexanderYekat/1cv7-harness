Option Explicit
Dim v, fso, stream, result, actualBase, controller, target
Dim runId, eventPath, t, sourceOk, sourceBad, sourceUnused, sourceController, i, batchOk
Set fso = CreateObject("Scripting.FileSystemObject")
runId = __RUN_ID__
eventPath = fso.BuildPath(fso.GetParentFolderName(WScript.Arguments(2)), "suite-events.jsonl")
__SOURCES__

Function Quote(value)
    Dim text, j, ch, code, escaped
    text = CStr(value)
    escaped = ""
    For j = 1 To Len(text)
        ch = Mid(text, j, 1)
        code = AscW(ch)
        If ch = Chr(34) Then
            escaped = escaped & Chr(92) & Chr(34)
        ElseIf ch = Chr(92) Then
            escaped = escaped & Chr(92) & Chr(92)
        ElseIf code >= 0 And code < 32 Then
            escaped = escaped & Chr(92) & "u" & Right("0000" & Hex(code), 4)
        Else
            escaped = escaped & ch
        End If
    Next
    Quote = Chr(34) & escaped & Chr(34)
End Function

Function Elapsed(start)
    Dim delta
    delta = CDbl(Timer) - start
    If delta < 0 Then delta = delta + 86400
    Elapsed = Round(delta * 1000, 3)
End Function

Dim h77LogStream, h77EventStream

Sub Log(text)
    On Error Resume Next
    If Not IsObject(h77LogStream) Then Set h77LogStream = fso.OpenTextFile(WScript.Arguments(2), 8, True, -1)
    h77LogStream.WriteLine CStr(Now) & " " & text
    If Err.Number <> 0 Then WScript.Quit 2
End Sub

Sub Emit(kind, name, value, elapsedMs)
    On Error Resume Next
    If Not IsObject(h77EventStream) Then Set h77EventStream = fso.OpenTextFile(eventPath, 8, True, -1)
    h77EventStream.WriteLine "{""run_id"":" & Quote(runId) & ",""kind"":" & Quote(kind) & _
        ",""name"":" & Quote(name) & ",""value"":" & Quote(value) & _
        ",""elapsed_ms"":" & Replace(CStr(elapsedMs), ",", ".") & "}"
    If kind = "complete" Then
        h77EventStream.Close
        If IsObject(h77LogStream) Then h77LogStream.Close
    End If
    If Err.Number <> 0 Then WScript.Quit 2
End Sub

Sub Fail(name, description)
    Emit "blocked", name, description, 0
    WScript.Quit 2
End Sub

Sub CheckCOM(name)
    Dim number, description
    number = Err.Number
    description = Err.Description
    Err.Clear
    If number <> 0 Then Fail name, CStr(number) & ": " & description
End Sub

Sub CompileCase(name, source)
    Dim started, value, path
    On Error Resume Next
    path = fso.BuildPath(fso.GetParentFolderName(eventPath), name & ".txt")
    started = CDbl(Timer)
    value = controller.Harness77CheckSource(source, path, runId & ":" & name)
    CheckCOM name
    Emit "case", name, value, Elapsed(started)
End Sub

Function LoadModule(source)
    Dim module, compiled, executed
    On Error Resume Next
    Set module = v.CreateObject("ВыполняемыйМодуль")
    CheckCOM "create-module"
    module.AssignSource source
    CheckCOM "assign-source"
    compiled = module.Compile()
    CheckCOM "compile-module"
    If compiled <> 1 Then Fail "compile-module", "return=" & CStr(compiled)
    executed = module.Execute()
    CheckCOM "execute-module"
    If executed <> 1 Then Fail "execute-module", "return=" & CStr(executed)
    Set LoadModule = module
End Function

On Error Resume Next
Log "activation-start"
t = CDbl(Timer)
Set v = CreateObject("V77L.Application")
CheckCOM "activation"
Emit "phase", "activation", "ok", Elapsed(t)
Log "activation-ok"
t = CDbl(Timer)
result = v.Initialize(v.RMTrade, "/D""" & WScript.Arguments(0) & """ /N""" & WScript.Arguments(1) & """", "NO_SPLASH_SHOW")
CheckCOM "initialize"
If Not result Then Fail "initialize", "returned false"
Emit "phase", "initialize", "ok", Elapsed(t)
t = CDbl(Timer)
actualBase = v.EvalExpr("КаталогИБ()")
CheckCOM "base-path"
If LCase(actualBase) <> LCase(WScript.Arguments(0) & "\") Then Fail "base-path", "unexpected database"
result = v.EvalExpr("6 * 7")
CheckCOM "control-answer"
If result <> 42 Then Fail "control-answer", CStr(result)
Emit "phase", "base_check", "ok", Elapsed(t)
Log "base=" & actualBase
Log "answer=42"

t = CDbl(Timer)
Set controller = LoadModule(sourceController)
Emit "phase", "controller_load", "ok", Elapsed(t)
t = CDbl(Timer)
Set target = LoadModule(sourceOk)
Emit "phase", "target_load", "ok", Elapsed(t)
CompileCase "compile_valid", sourceOk
t = CDbl(Timer)
result = target.Harness77Sum(20, 22)
CheckCOM "value-correct"
Emit "case", "value_correct", result, Elapsed(t)
t = CDbl(Timer)
result = target.Harness77Sum(20, 22)
CheckCOM "value-wrong"
Emit "case", "value_wrong", result, Elapsed(t)

t = CDbl(Timer)
batchOk = True
For i = 1 To __ITERATIONS__
    result = target.Harness77Sum(20, 22)
    If Err.Number <> 0 Then CheckCOM "batch-call"
    If result <> 42 Then batchOk = False
Next
If Not batchOk Then Fail "batch-call", "unexpected result"
Emit "batch", "calls_loaded", "ok", Elapsed(t)
t = CDbl(Timer)
result = controller.Harness77Repeat(sourceOk, __ITERATIONS__)
CheckCOM "batch-inside-1c"
If result <> __ITERATIONS__ Then Fail "batch-inside-1c", CStr(result)
Emit "batch", "calls_inside_1c", "ok", Elapsed(t)
Set target = Nothing
t = CDbl(Timer)
For i = 1 To __FRESH_MODULES__
    Set target = LoadModule(sourceOk)
    result = target.Harness77Sum(20, 22)
    CheckCOM "batch-fresh-call"
    If result <> 42 Then Fail "batch-fresh-call", CStr(result)
    Set target = Nothing
Next
Emit "batch", "fresh_modules", "ok", Elapsed(t)

CompileCase "compile_syntax", sourceBad
CompileCase "compile_unused", sourceUnused
CompileCase "compile_recovery", sourceOk
Set target = LoadModule(sourceOk)
t = CDbl(Timer)
result = target.Harness77Sum(20, 22)
CheckCOM "value-recovery"
Emit "case", "value_recovery", result, Elapsed(t)
Set target = Nothing
Set controller = Nothing

__BEFORE_RELEASE__
t = CDbl(Timer)
Set v = Nothing
CheckCOM "release"
__AFTER_RELEASE__
Emit "phase", "release", "ok", Elapsed(t)
Log "released"
Emit "complete", "suite", "done", 0
