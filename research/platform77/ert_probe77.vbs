Option Explicit
Dim v, fso, result, actualBase, controller, runId, eventPath, i, command, file, t
Dim sourceController, ertPath, identity, evidencePath, eventFile
Set fso = CreateObject("Scripting.FileSystemObject")
runId = __RUN_ID__
ertPath = __ERT_PATH__
identity = __IDENTITY__
eventPath = fso.BuildPath(fso.GetParentFolderName(WScript.Arguments(2)), "ert-events.jsonl")
__SOURCES__
__UTILITIES__
On Error Resume Next
Set v = CreateObject("V77L.Application")
CheckCOM "activation"
__PROXY_IDENTITY__
result = v.Initialize(v.RMTrade, "/D""" & WScript.Arguments(0) & """ /N""" & WScript.Arguments(1) & """", "NO_SPLASH_SHOW")
CheckCOM "initialize"
If Not result Then Fail "initialize", "returned false"
actualBase = v.EvalExpr("КаталогИБ()")
CheckCOM "base-path"
If LCase(actualBase) <> LCase(WScript.Arguments(0) & "\") Then Fail "base-path", "unexpected database"
Log "answer=" & CStr(v.EvalExpr("6 * 7"))
Emit "phase", "base", "ok", 0
Set controller = v.CreateObject("ВыполняемыйМодуль")
CheckCOM "create-controller"
controller.AssignSource sourceController
CheckCOM "assign-controller"
result = controller.Compile()
CheckCOM "compile-controller"
If result <> 1 Then Fail "compile-controller", CStr(result)
result = controller.Execute()
CheckCOM "execute-controller"
If result <> 1 Then Fail "execute-controller", CStr(result)
Emit "phase", "controller", "ok", 0
Set file = fso.CreateTextFile(fso.BuildPath(fso.GetParentFolderName(eventPath), "ert-operation-started"), False)
file.WriteLine runId
file.Close
For Each command In Array(__COMMANDS__)
    evidencePath = fso.BuildPath(fso.GetParentFolderName(eventPath), command & ".txt")
    t = CDbl(Timer)
    result = controller.Harness77Ert(ertPath, command, evidencePath, runId & ":" & command)
    CheckCOM command
    Emit "ert", command, CStr(result), Elapsed(t)
Next
Set file = fso.CreateTextFile(fso.BuildPath(fso.GetParentFolderName(eventPath), "ert-operation-finished"), False)
file.WriteLine runId
file.Close
Set controller = Nothing
CheckCOM "release-controller"
__SHUTDOWN__
Set v = Nothing
CheckCOM "release"
ShutdownEvent "server_released", "ok"
Log "released"
Emit "complete", "ert", "done", 0
