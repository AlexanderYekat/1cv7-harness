' Inserted only after fixed suite objects have been released.
Dim shutdownPath, shutdownSource, shutdownInstaller, shutdownGlobalId, shutdownStarted
shutdownPath = fso.BuildPath(fso.GetParentFolderName(eventPath), "shutdown-events.jsonl")
shutdownStarted = CDbl(Timer)

Sub ShutdownEvent(name, value)
    Dim file
    Set file = fso.OpenTextFile(shutdownPath, 8, True, -1)
    file.WriteLine "{""run_id"":" & Quote(runId) & ",""name"":" & Quote(name) & _
        ",""value"":" & Quote(value) & ",""elapsed_ms"":" & Replace(CStr(Elapsed(shutdownStarted)), ",", ".") & "}"
    file.Close
End Sub

Sub ShutdownError(name)
    Dim number, description
    number = Err.Number
    description = Err.Description
    Err.Clear
    If number <> 0 Then
        ShutdownEvent "error", name & ": " & CStr(number) & ": " & description
        WScript.Quit 2
    End If
End Sub

Sub ShutdownRequire(name, value, expected)
    ShutdownError name
    ShutdownEvent name, value
    If CStr(value) <> CStr(expected) Then WScript.Quit 2
End Sub

ShutdownError "release-suite-modules"
ShutdownEvent "modules_released", "ok"
__INSTALLER__
Set shutdownInstaller = v.CreateObject("ВыполняемыйМодуль")
ShutdownError "create-installer"
shutdownInstaller.AssignSource shutdownSource
ShutdownError "assign-installer"
result = shutdownInstaller.Compile()
ShutdownRequire "installer_compiled", result, 1
result = shutdownInstaller.Execute()
ShutdownRequire "installer_executed", result, 1
shutdownGlobalId = shutdownInstaller.H77Install()
ShutdownError "install-global"
ShutdownEvent "global_installed", shutdownGlobalId
If shutdownGlobalId <= 0 Then WScript.Quit 2
Set shutdownInstaller = Nothing
ShutdownError "release-installer"
ShutdownEvent "installer_released", "ok"
result = v.EvalExpr("H77PID()")
ShutdownRequire "helper_pid", result, WScript.Arguments(3)
result = v.EvalExpr("H77Loaded()")
ShutdownRequire "loaded_initially", result, 1
result = v.EvalExpr("H77Hold()")
ShutdownRequire "reference_held", result, WScript.Arguments(3)
result = v.EvalExpr("H77Unload()")
ShutdownRequire "addin_unloaded", result, 1
result = v.EvalExpr("H77Loaded()")
ShutdownRequire "loaded_before_flush", result, 1
result = v.EvalExpr("H77Flush()")
ShutdownRequire "com_flushed", result, WScript.Arguments(3)
result = v.EvalExpr("H77Loaded()")
ShutdownRequire "loaded_after_flush", result, 0
' ReleaseIcpp must only forget the consumed reference, never call FreeLibrary.
result = v.EvalExpr("H77Release()")
ShutdownRequire "reference_consumed", result, 0
result = v.EvalExpr("H77Loaded()")
ShutdownRequire "loaded_after_release", result, 0
result = v.EvalExpr("6 * 7")
ShutdownRequire "answer", result, 42
If "__FAULT__" = "com-error" Then
    result = v.Harness77MissingMethod()
    ShutdownError "injected-com-error"
    ShutdownEvent "error", "injected method unexpectedly exists"
    WScript.Quit 2
End If
If "__FAULT__" = "release-timeout" Then
    ' Poll only a file; no UI input or blocking calls into 1C.
    Do While Not fso.FileExists(fso.BuildPath(fso.GetParentFolderName(eventPath), "cancel"))
        WScript.Sleep 50
    Loop
End If
