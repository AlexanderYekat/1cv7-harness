Option Explicit
Dim v, fso, result, runId, eventPath, missingBase, openNumber, openDescription, t, actualBase
Set fso = CreateObject("Scripting.FileSystemObject")
runId = __RUN_ID__
missingBase = __MISSING_BASE__
eventPath = fso.BuildPath(fso.GetParentFolderName(WScript.Arguments(2)), "open-events.jsonl")
__UTILITIES__

Sub OpenMarker(state)
    Dim file, path
    path = fso.BuildPath(fso.GetParentFolderName(eventPath), "base-open-" & state)
    Set file = fso.CreateTextFile(path & ".tmp", False)
    file.WriteLine runId
    file.Close
    fso.MoveFile path & ".tmp", path
    CheckCOM "open-marker"
End Sub

On Error Resume Next
Set v = CreateObject("V77L.Application")
CheckCOM "activation"
__PROXY_IDENTITY__
If fso.FolderExists(missingBase) Or fso.FileExists(missingBase) Then Fail "missing-base", "target exists"
Emit "phase", "open-start", missingBase, 0
OpenMarker "started"
t = CDbl(Timer)
result = v.Initialize(v.RMTrade, "/D""" & missingBase & """ /N""" & WScript.Arguments(1) & """", "NO_SPLASH_SHOW")
openNumber = Err.Number
openDescription = Err.Description
Err.Clear
Emit "open", "return", CStr(CInt(result)), Elapsed(t)
Emit "open", "variant-type", CStr(VarType(result)), 0
Emit "open", "return-text", CStr(result), 0
Emit "open", "error-number", CStr(openNumber), 0
Emit "open", "error-description", openDescription, 0
OpenMarker "finished"
If openNumber = 0 And result <> 0 Then
    actualBase = v.EvalExpr("КаталогИБ()")
    Emit "blocked", "unexpected-base", CStr(actualBase), 0
    Fail "missing-base", "Initialize unexpectedly succeeded"
End If
Set v = Nothing
CheckCOM "release-uninitialized"
Emit "phase", "released", "ok", 0
Emit "complete", "open-failure", "done", 0
