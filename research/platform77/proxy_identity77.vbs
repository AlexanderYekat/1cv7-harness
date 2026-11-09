' GetIDsOfNames only; no 1C Invoke, RMTrade or Initialize before permission.
Dim proxyInspector, proxyPid, proxyTid, proxyFolder, proxyFile, proxyStart, proxyPermit
Set proxyInspector = CreateObject("Harness77Diagnostic.ProxyIdentity")
CheckCOM "proxy-inspector"
proxyPid = proxyInspector.Challenge(v, "H77_" & Replace(runId, "-", ""))
CheckCOM "identity-challenge"
If proxyPid <> -2147352570 Then Fail "identity-challenge", "expected unknown member"
Set proxyInspector = Nothing
proxyFolder = fso.GetParentFolderName(eventPath)
Set proxyFile = fso.CreateTextFile(fso.BuildPath(proxyFolder, "proxy-challenge.tmp"), False)
proxyFile.WriteLine runId
proxyFile.Close
fso.MoveFile fso.BuildPath(proxyFolder, "proxy-challenge.tmp"), fso.BuildPath(proxyFolder, "proxy-challenge-complete")
CheckCOM "publish-proxy-identity"
proxyStart = CDbl(Timer)
Do
    If fso.FileExists(fso.BuildPath(proxyFolder, "cancel")) Then Fail "proxy-owner", "cancelled before Initialize"
    If Elapsed(proxyStart) > 10000 Then Fail "proxy-owner", "no controller permission"
    If fso.FileExists(fso.BuildPath(proxyFolder, "initialize-permit")) Then Exit Do
    WScript.Sleep 50
Loop
proxyPermit = ReadInitializePermit(fso.BuildPath(proxyFolder, "initialize-permit"))
If proxyPermit <> runId Then Fail "proxy-owner", "foreign permission"
Log "proxy-owner-verified=" & WScript.Arguments(3)
If WScript.Arguments(4) = "activation-only" Then
    Set v = Nothing
    CheckCOM "release-uninitialized"
    Log "activation-only-released"
    WScript.Quit 0
End If

Function InitializePermitDetail(operation, path, number, source, description, attempts, elapsedMs)
    InitializePermitDetail = "{""operation"":" & Quote(operation) & ",""path"":" & Quote(path) & _
        ",""error_number"":" & CStr(number) & ",""error_source"":" & Quote(source) & _
        ",""error_description"":" & Quote(description) & ",""attempts"":" & CStr(attempts) & _
        ",""elapsed_ms"":" & Replace(CStr(elapsedMs), ",", ".") & "}"
End Function

Sub CheckInitializePermitIO(operation, path, attempts, started)
    Dim number, source, description
    number = Err.Number: source = Err.Source: description = Err.Description
    Err.Clear
    If number <> 0 Then Fail "read-initialize-permit", _
        InitializePermitDetail(operation, path, number, source, description, attempts, Elapsed(started))
End Sub

Function ReadInitializePermit(path)
    Dim permitStream, started, attempts, number, source, description, elapsedMs, detail, value
    On Error Resume Next
    started = CDbl(Timer)
    For attempts = 1 To 26
        If fso.FileExists(fso.BuildPath(proxyFolder, "cancel")) Then Fail "proxy-owner", "cancelled before Initialize"
        Err.Clear
        Set permitStream = fso.OpenTextFile(path, 1, False)
        number = Err.Number: source = Err.Source: description = Err.Description
        Err.Clear
        If number = 0 Then
            value = permitStream.ReadAll
            CheckInitializePermitIO "permit-read", path, attempts, started
            permitStream.Close
            CheckInitializePermitIO "permit-close", path, attempts, started
            ReadInitializePermit = Trim(value)
            Exit Function
        End If
        elapsedMs = Elapsed(started)
        detail = InitializePermitDetail("permit-open", path, number, source, description, attempts, elapsedMs)
        If number <> 70 Or attempts = 26 Or elapsedMs >= 1000 Then Fail "read-initialize-permit", detail
        Emit "marker-read-retry", "initialize-permit", detail, elapsedMs
        WScript.Sleep 40
    Next
End Function
