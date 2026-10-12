Option Explicit
Dim base, user, logPath, v, m, service, ok, result, moduleId, source, fso, failed, sourceFile
base = WScript.Arguments(0)
user = WScript.Arguments(1)
logPath = WScript.Arguments(2)
Set fso = CreateObject("Scripting.FileSystemObject")
failed = False

Sub Log(text)
    Dim stream
    Set stream = fso.OpenTextFile(logPath, 8, True, -1)
    stream.WriteLine text
    stream.Close
End Sub

Function Check(stage)
    If Err.Number <> 0 Then
        Log stage & "-error=" & Hex(Err.Number) & ":" & Err.Description
        Err.Clear
        failed = True
        Check = False
    Else
        Log stage & "-ok"
        Check = True
    End If
End Function

On Error Resume Next
Log "started"
Set v = CreateObject("V77L.Application")
If Not Check("activation") Then WScript.Quit 2
ok = v.Initialize(v.RMTrade, "/D""" & base & """ /N""" & user & """", "NO_SPLASH_SHOW")
If Not Check("initialize") Then WScript.Quit 2
If Not ok Then WScript.Quit 2
Log "base=" & v.EvalExpr("КаталогИБ()")
Log "answer=" & v.EvalExpr("6 * 7")
Log "icpp-load=" & v.EvalExpr("ЗагрузитьВнешнююКомпоненту(""" & base & "\1CPP.dll"")")
Log "formex-load=" & v.EvalExpr("ЗагрузитьВнешнююКомпоненту(""" & base & "\FormEx.dll"")")

Set m = v.CreateObject("ВыполняемыйМодуль")
If Check("icpp-create") Then
    m.AssignSource "Функция Harness77Answer() Экспорт" & vbCrLf & "Возврат 42;" & vbCrLf & "КонецФункции"
    If Check("icpp-source") Then
        result = m.Compile()
        Log "icpp-compile=" & result
        If Check("icpp-compile") Then
            result = m.Execute()
            Log "icpp-execute=" & result
            If Check("icpp-execute") Then
                result = m.Harness77Answer()
                Log "icpp-answer=" & result
                Check "icpp-answer"
            End If
        End If
    End If
End If
Set m = Nothing

If WScript.Arguments.Count > 3 Then
    Set sourceFile = fso.OpenTextFile(WScript.Arguments(4), 1, False, -1)
    source = sourceFile.ReadAll
    sourceFile.Close
    Set m = v.CreateObject("ВыполняемыйМодуль")
    m.AssignSource source
    If Check("controller-source") Then
        result = m.Compile()
        Log "controller-compile=" & result
        If Check("controller-compile") And result = 1 Then
            result = m.Execute()
            Log "controller-execute=" & result
            If Check("controller-execute") And result = 1 Then
                Log "form-probe-started"
                result = m.Harness77FormProbe(WScript.Arguments(3))
                Log result
                Check "form-probe"
            End If
        End If
    End If
    Set m = Nothing
End If
Set v = Nothing
Log "released"
If failed Then WScript.Quit 2
