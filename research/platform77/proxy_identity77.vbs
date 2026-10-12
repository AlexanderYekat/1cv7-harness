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
Set proxyFile = fso.OpenTextFile(fso.BuildPath(proxyFolder, "initialize-permit"), 1, False)
proxyPermit = Trim(proxyFile.ReadAll)
proxyFile.Close
CheckCOM "read-initialize-permit"
If proxyPermit <> runId Then Fail "proxy-owner", "foreign permission"
Log "proxy-owner-verified=" & WScript.Arguments(3)
If WScript.Arguments(4) = "activation-only" Then
    Set v = Nothing
    CheckCOM "release-uninitialized"
    Log "activation-only-released"
    WScript.Quit 0
End If
