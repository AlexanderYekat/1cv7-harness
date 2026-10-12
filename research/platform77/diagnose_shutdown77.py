"""One bounded diagnostic session; CDB owns the server and stops on the first AV.

This is not an acceptance runner. A debugger stop is recorded as a diagnostic
stop, not as proof that the exception would have been unhandled by 1C.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


from win32_session77 import kernel, processes, register_cleanup_helper


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--user", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--cdb", required=True, type=Path)
    parser.add_argument("--shutdown", choices=("release", "exit-system", "exit-system-confirm"), default="release")
    parser.add_argument("--trace-shutdown", action="store_true")
    parser.add_argument("--trace-icpp-unload", action="store_true")
    parser.add_argument("--basic-release-mode", choices=("none", "trace", "skip"), default="none",
                        help="diagnose the borrowed BASIC handle release in the exact installed 1CPP 2.5.0.7")
    parser.add_argument("--extension-action", choices=("none", "inspect-service", "unload-icpp", "unload-icpp-native", "flush-com", "unload-icpp-coordinated", "module-suite", "module-suite-coordinated"), default="none")
    parser.add_argument("--suite-iterations", type=int, default=1)
    parser.add_argument("--unload-name", choices=("full-path", "base-name"), default="full-path")
    parser.add_argument("--com-cleanup-dll", type=Path)
    parser.add_argument("--com-flush-mode", choices=("default", "immediate"), default="default")
    parser.add_argument("--run-diagnostic", required=True, action="store_true")
    args = parser.parse_args()
    gate = Path(__file__).resolve().parents[2] / ".artifacts/platform77/active-session.json"
    if gate.exists():
        parser.error("guarded session is active or its cleanup needs inspection: " + str(gate))
    if not 1 <= args.suite_iterations <= 10000:
        parser.error("suite iterations must be between 1 and 10000")
    suite_mode = args.extension_action in ("module-suite", "module-suite-coordinated")
    if suite_mode and args.shutdown != "release":
        parser.error("module suite requires normal COM release")
    coordinated = args.extension_action in ("unload-icpp-coordinated", "module-suite-coordinated")
    if args.com_flush_mode != "default" and not coordinated:
        parser.error("immediate flush is restricted to the coordinated unload diagnostic")
    if (args.extension_action == "flush-com" or coordinated) != bool(args.com_cleanup_dll):
        parser.error("flush-com / unload-icpp-coordinated require --com-cleanup-dll; other modes must omit it")
    if coordinated and args.shutdown != "release":
        parser.error("coordinated unload requires normal COM release")
    cleanup_dll = args.com_cleanup_dll.resolve(strict=True) if args.com_cleanup_dll else None
    base, exe, cdb = [path.resolve(strict=True) for path in (args.base, args.exe, args.cdb)]
    if args.trace_icpp_unload or args.basic_release_mode != "none" or coordinated:
        # Return offsets were disassembled from this exact installed 2.5.0.7 DLL.
        icpp_bytes = (base / "1CPP.dll").read_bytes()
        icpp_sha = hashlib.sha256(icpp_bytes).hexdigest()
        if icpp_sha != "d690756abc7ecb839f258a5b1abcbabd622d3f3d85410141b00493edcf7c2bfb":
            parser.error("offset-based diagnostics require the inspected 1CPP binary")
        if coordinated and hashlib.sha256((base / "FormEx.dll").read_bytes()).hexdigest() != "32fa9996a24bd6075d5010051550671af5f7cfd8ba98e990ac67a1ed1585f798":
            parser.error("coordinated unload requires the inspected FormEx binary")
        if args.basic_release_mode != "none":
            # For this pinned PE, .text RVA equals its file offset. At +2c917:
            # push edi; call dword ptr [FreeLibrary IAT]. Skip BOTH instructions
            # before the push, so ESP is unchanged and no stdcall cleanup is lost.
            if icpp_bytes[0x2c917:0x2c91e] != bytes.fromhex("57 ff 15 20 57 0d 24"):
                parser.error("borrowed BASIC release instructions do not match")
    out = args.output.resolve()
    if out.is_relative_to(base) or any(c in str(out) for c in '"; \r\n'):
        parser.error("output must be outside the base and safe for a debugger command")
    before_processes = processes()
    if before_processes:
        parser.error(f"refusing to start with existing 1C processes: {before_processes}")
    out.mkdir(parents=True, exist_ok=False)

    def hashes():
        return {name: hashlib.sha256((base / name).read_bytes()).hexdigest()
                for name in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll")}

    script = out / "baseline.vbs"
    client_source = '''Option Explicit
Dim v, fso, stream, result, actualBase
Set fso = CreateObject("Scripting.FileSystemObject")
Sub Log(text)
    Set stream = fso.OpenTextFile(WScript.Arguments(2), 8, True, -1)
    stream.WriteLine CStr(Now) & " " & text
    stream.Close
End Sub
Log "activation-start"
Set v = CreateObject("V77L.Application")
Log "activation-ok"
result = v.Initialize(v.RMTrade, "/D""" & WScript.Arguments(0) & """ /N""" & WScript.Arguments(1) & """", "NO_SPLASH_SHOW")
Log "initialize=" & CStr(result)
If Not result Then WScript.Quit 2
actualBase = v.EvalExpr("КаталогИБ()")
Log "base=" & actualBase
If LCase(actualBase) <> LCase(WScript.Arguments(0) & "\\") Then WScript.Quit 2
result = v.EvalExpr("6 * 7")
Log "answer=" & CStr(result)
If result <> 42 Then WScript.Quit 2
__EXTENSION__
__SHUTDOWN__
Set v = Nothing
Log "released"
'''
    shutdown_source = ""
    if args.shutdown in ("exit-system", "exit-system-confirm"):
        shutdown_source = '''result = v.EvalExpr("ПустоеЗначение(ВосстановитьЗначение(""НеЗапрашиватьПодтверждениеПриВыходе""))")
Log "would-prompt=" & CStr(result)
If result = 0 Then
    Log "exit-system-start"
    result = v.ExecuteBatch("ЗавершитьРаботуСистемы(0);")
    Log "exit-system-result=" & CStr(result)
Else
    Log "exit-system-skipped-to-avoid-modal-prompt"
End If'''
        if args.shutdown == "exit-system-confirm":
            # Explicit diagnostic mode: allow the existing confirmation dialog.
            # Answer it through the observed UI; do not change user preferences.
            shutdown_source = shutdown_source.replace("If result = 0 Then", "If True Then")
    extension_source = ""
    if args.extension_action not in ("none", "module-suite"):
        native_source = '''Функция Harness77Inspect() Экспорт
    Инф = СоздатьОбъект("Информатор");
    Срв = СоздатьОбъект("Сервис");
    Таб = Инф.ПолучитьТаблицуМетодов(Срв);
    Ответ = "";
    Таб.ВыбратьСтроки();
    Пока Таб.ПолучитьСтроку() = 1 Цикл
        Если Найти(ВРег(Таб.NameEng), "UNLOAD") > 0 Тогда
            Ответ = Ответ + Таб.NameEng + ":" + СокрЛП(Строка(Таб.NParams)) + ":" + СокрЛП(Строка(Таб.HasRetVal)) + ";";
        КонецЕсли;
    КонецЦикла;
    Возврат Ответ;
КонецФункции'''
        if args.extension_action in ("unload-icpp-native", "flush-com") or coordinated:
            global_source = '''Функция Harness77Unload(Путь) Экспорт
    Срв = СоздатьОбъект("Сервис");
    Возврат Срв.UnLoadAddIn(Путь);
КонецФункции'''
            if args.extension_action == "flush-com" or coordinated:
                global_source = '''Функция Harness77CleanupPID() Экспорт
    Очистка = СоздатьОбъект("Harness77Diagnostic.ComCleanup");
    Возврат Очистка.ProcessId();
КонецФункции
Функция Harness77FlushCom() Экспорт
    Очистка = СоздатьОбъект("Harness77Diagnostic.ComCleanup");
    Возврат Очистка.Flush();
КонецФункции'''
                if coordinated:
                    if args.com_flush_mode == "immediate":
                        global_source = global_source.replace("Очистка.Flush()", "Очистка.FlushNow()")
                    global_source += '''
Функция Harness77HoldIcpp() Экспорт
    Очистка = СоздатьОбъект("Harness77Diagnostic.ComCleanup");
    Возврат Очистка.HoldIcpp();
КонецФункции
Функция Harness77ReleaseIcpp() Экспорт
    Очистка = СоздатьОбъект("Harness77Diagnostic.ComCleanup");
    Возврат Очистка.ReleaseIcpp();
КонецФункции
Функция Harness77IcppLoaded() Экспорт
    Очистка = СоздатьОбъект("Harness77Diagnostic.ComCleanup");
    Возврат Очистка.IcppLoaded();
КонецФункции
Функция Harness77UnloadIcpp() Экспорт
    Срв = СоздатьОбъект("Сервис");
    Возврат Срв.UnLoadAddIn("1cpp.dll");
КонецФункции'''
            native_literal = ' + РазделительСтрок + '.join('"' + line.replace('"', '""') + '"' for line in global_source.splitlines())
            native_source += '\nФункция Harness77Install() Экспорт\n    Срв = СоздатьОбъект("Сервис");\n    Возврат Срв.AddGlobalModule(' + native_literal + ');\nКонецФункции'
        # Bound physical VBScript line length as the diagnostic module grows.
        vb_source = 'Dim nativeSource\nnativeSource = ""\n' + "\n".join(
            'nativeSource = nativeSource & "' + line.replace('"', '""') + '" & vbCrLf'
            for line in native_source.splitlines())
        extension_source = '''Dim m, methods, service, unloadError
Set m = v.CreateObject("ВыполняемыйМодуль")
Log "module-created"
__SOURCE__
m.AssignSource nativeSource
result = m.Compile()
Log "module-compile=" & CStr(result)
If result <> 1 Then WScript.Quit 3
result = m.Execute()
Log "module-execute=" & CStr(result)
If result <> 1 Then WScript.Quit 3
methods = CStr(m.Harness77Inspect())
Log "service-unload-methods=" & methods
__INSTALL__
Set m = Nothing
Log "module-released"'''.replace("__SOURCE__", vb_source)
        install_source = ""
        if args.extension_action in ("unload-icpp-native", "flush-com") or coordinated:
            install_source = '''result = m.Harness77Install()
Log "global-module-id=" & CStr(result)
If result <= 0 Then WScript.Quit 3'''
        extension_source = extension_source.replace("__INSTALL__", install_source)
        if args.extension_action == "unload-icpp":
            # Never unload 1CPP while executing code in its module object.
            extension_source += '''
If methods <> "UnLoadAddIn:1:1;" Then WScript.Quit 3
Set service = v.CreateObject("Сервис")
Log "unload-icpp-start"
result = Empty
On Error Resume Next
result = service.UnLoadAddIn(WScript.Arguments(0) & "\\1CPP.dll")
unloadError = Err.Number
Log "unload-icpp-error=" & CStr(unloadError) & " " & Err.Description
Err.Clear
On Error GoTo 0
If unloadError = 0 Then Log "unload-icpp-result=" & CStr(result)
Set service = Nothing
Log "service-released"
If unloadError <> 0 Then WScript.Quit 3'''
        if args.extension_action == "unload-icpp-native":
            extension_source += '''
Log "native-unload-icpp-start"
result = v.EvalExpr("Harness77Unload(""" & WScript.Arguments(0) & "\\1CPP.dll"")")
Log "native-unload-icpp-result=" & CStr(result)
Log "answer-after-unload=" & CStr(v.EvalExpr("6 * 7"))'''
            if args.unload_name == "base-name":
                extension_source = extension_source.replace('result = v.EvalExpr("Harness77Unload(""" & WScript.Arguments(0) & "\\1CPP.dll"")")',
                    'result = v.EvalExpr("Harness77Unload(""1cpp.dll"")")')
        if coordinated:
            extension_source += '''
result = v.EvalExpr("Harness77HoldIcpp()")
Log "hold-icpp-process-id=" & CStr(result)
If CStr(result) <> WScript.Arguments(3) Then WScript.Quit 4
result = v.EvalExpr("Harness77UnloadIcpp()")
Log "coordinated-unload-icpp=" & CStr(result)
If result <> 1 Then WScript.Quit 4
Log "icpp-loaded-before-flush=" & CStr(v.EvalExpr("Harness77IcppLoaded()"))'''
        if args.extension_action == "flush-com" or coordinated:
            extension_source += '''
result = v.EvalExpr("Harness77CleanupPID()")
Log "cleanup-process-id=" & CStr(result)
If CStr(result) <> WScript.Arguments(3) Then WScript.Quit 4
Log "com-flush-start"
result = v.EvalExpr("Harness77FlushCom()")
Log "com-flush-process-id=" & CStr(result)
If CStr(result) <> WScript.Arguments(3) Then WScript.Quit 4
Log "cleanup-native-function-returned"
Log "answer-after-flush=" & CStr(v.EvalExpr("6 * 7"))'''
        if coordinated:
            extension_source += '''
Log "icpp-loaded-after-flush=" & CStr(v.EvalExpr("Harness77IcppLoaded()"))
result = v.EvalExpr("Harness77ReleaseIcpp()")
Log "release-icpp-process-id=" & CStr(result)
If result = 0 Then
    Log "held-reference-consumed-by-external-cleanup"
ElseIf CStr(result) <> WScript.Arguments(3) Then
    WScript.Quit 4
End If
result = v.EvalExpr("Harness77IcppLoaded()")
Log "icpp-loaded-after-release=" & CStr(result)
If result <> 0 Then WScript.Quit 4
Log "answer-after-coordinated-unload=" & CStr(v.EvalExpr("6 * 7"))'''
            extension_source = '''Dim cleanupStarted, cleanupElapsed
cleanupStarted = CDbl(Timer)
''' + extension_source + '''
cleanupElapsed = CDbl(Timer) - cleanupStarted
If cleanupElapsed < 0 Then cleanupElapsed = cleanupElapsed + 86400
Log "coordinated-unload-ms=" & Replace(CStr(Round(cleanupElapsed * 1000, 3)), ",", ".")'''
    suite_manifest = None
    if suite_mode:
        from module_suite77 import prepare_client
        # All target/controller references are released before this fragment.
        # Stop on a COM error in shutdown code instead of resuming past it.
        before_release = "On Error GoTo 0\n" + extension_source if coordinated else ""
        client_source, suite_manifest = prepare_client(out, args.suite_iterations, before_release)
    script.write_text(client_source.replace("__SHUTDOWN__", shutdown_source).replace("__EXTENSION__", extension_source), encoding="utf-16")
    commands = out / "debugger.txt"
    trace_commands = ""
    if args.trace_shutdown:
        trace_commands = (
            'bp ntdll!RtlDeleteCriticalSection ".echo HARNESS77_DELETE_CS; dd @esp L4; kv 6; gc"\n'
            'bp ntdll!LdrUnloadDll ".echo HARNESS77_UNLOAD_DLL; dd @esp L4; kv 6; gc"\n'
            'bm BkEnd!*DeInit* ".echo HARNESS77_BKEND_DEINIT; kv 8; gc"\n'
        )
    if args.trace_icpp_unload:
        trace_commands += (
            'bu 1cpp!DllCanUnloadNow+0x34 ".echo HARNESS77_CAN_UNLOAD_S_OK; .time; r eax; kv 6; gc"\n'
            'bu 1cpp!DllCanUnloadNow+0x48 ".echo HARNESS77_CAN_UNLOAD_S_FALSE; .time; r eax; kv 6; gc"\n'
        )
    if args.basic_release_mode != "none":
        action = ""
        if args.basic_release_mode == "skip":
            action = '.echo HARNESS77_BASIC_RELEASE_SKIPPED; r eip = @eip + 0x7; '
        trace_commands += (
            'bu 1cpp!DllCanUnloadNow-0x3ef9 ".echo HARNESS77_BASIC_RELEASE_SITE; '
            'r edi; lm a @edi; kv 6; ' + action + 'gc"\n'
        )
    # Stop before the application's own AV dialog/handler; preserve its context.
    commands.write_text(
        'sxe -c ".echo HARNESS77_FIRST_CHANCE_AV; .exr -1; r; kv; dps @esp L100; ~*kv; lm; '
        '.dump /ma ' + (out / "first-av.dmp").as_posix() + '; q" av\n'
        + trace_commands + '.echo HARNESS77_DEBUGGER_READY\n'
        'g\n', encoding="ascii")
    report = {"started_at": dt.datetime.now().astimezone().isoformat(),
              "purpose": "bounded OLE shutdown diagnostic",
              "extension_action": args.extension_action,
              "unload_name": args.unload_name,
              "shutdown": args.shutdown,
              "trace_shutdown": args.trace_shutdown,
              "trace_icpp_unload": args.trace_icpp_unload,
              "basic_release_mode": args.basic_release_mode,
              "com_flush_mode": args.com_flush_mode,
              "diagnostic_execution_modified": args.basic_release_mode == "skip" or coordinated,
              "hashes_before": hashes(), "processes_before": before_processes,
              "debugger_stops_at_first_chance_av": True,
              "timeout_seconds": 145, "forced_cleanup": False}
    debugger = helper = None
    handle = None
    cleanup_registration = None
    started = time.monotonic()
    try:
        if cleanup_dll:
            cleanup_registration = register_cleanup_helper(cleanup_dll, report)
        with (out / "cdb-stdout.txt").open("wb") as debug_stdout, (out / "client-stdout.txt").open("wb") as client_stdout:
            debugger = subprocess.Popen([str(cdb), "-hd", "-G", "-sins", "-y", str(out),
                                         "-logo", str(out / "debugger.log"), "-cf", str(commands),
                                         str(exe), "-Embedding"], stdin=subprocess.PIPE,
                                        stdout=debug_stdout, stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW, cwd=str(exe.parent))
            report["debugger_pid"] = debugger.pid
            deadline = started + 145
            while time.monotonic() < started + 20:
                children = [p for p in processes() if p["parent_pid"] == debugger.pid]
                if len(children) == 1:
                    report["server"] = children[0]
                    handle = kernel.OpenProcess(0x100000 | 0x1000 | 1, False, children[0]["pid"])
                    if not handle:
                        raise C.WinError(C.get_last_error())
                    buf = C.create_unicode_buffer(32768)
                    size = W.DWORD(len(buf))
                    if not kernel.QueryFullProcessImageNameW(handle, 0, buf, C.byref(size)):
                        raise C.WinError(C.get_last_error())
                    if Path(buf.value).resolve() != exe:
                        raise RuntimeError("debugger child executable mismatch")
                    times = [W.FILETIME() for _ in range(4)]
                    if not kernel.GetProcessTimes(handle, *[C.byref(t) for t in times]):
                        raise C.WinError(C.get_last_error())
                    report["server"].update(image=buf.value,
                        creation_filetime=(times[0].dwHighDateTime << 32) | times[0].dwLowDateTime,
                        ownership="direct child created by this CDB; retained process handle")
                    (out / "session.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    break
                if debugger.poll() is not None:
                    raise RuntimeError("debugger exited before server ownership was established")
                time.sleep(0.1)
            else:
                raise TimeoutError("debugger child was not observed")
            while time.monotonic() < started + 30:
                log = out / "debugger.log"
                if log.exists() and "\nHARNESS77_DEBUGGER_READY\n" in log.read_text(errors="replace"):
                    break
                if debugger.poll() is not None:
                    raise RuntimeError("debugger exited before ready")
                time.sleep(0.1)
            else:
                raise TimeoutError("debugger did not become ready")
            time.sleep(1)
            helper = subprocess.Popen([os.path.join(os.environ["WINDIR"], "SysWOW64", "cscript.exe"),
                                       "//B", "//NoLogo", "//T:110", str(script), str(base), args.user,
                                       str(out / "client.log"), str(report["server"]["pid"])], stdout=client_stdout, stderr=subprocess.STDOUT,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            report["helper_pid"] = helper.pid
            while time.monotonic() < deadline:
                debug_text = (out / "debugger.log").read_text(errors="replace")
                if any(message in debug_text for message in ("Numeric expression missing", "Syntax error at", "Unable to insert breakpoint")):
                    raise RuntimeError("debugger command failed; diagnostic is inconclusive")
                if debugger.poll() is not None and helper.poll() is not None:
                    break
                time.sleep(0.25)
            else:
                raise TimeoutError("bounded session timeout")
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if helper and helper.poll() is None:
            helper.kill()
            helper.wait(timeout=10)
            report["forced_cleanup"] = True
        if handle:
            if kernel.WaitForSingleObject(handle, 5000) == 0x102:
                kernel.TerminateProcess(handle, 0xE0000077)
                kernel.WaitForSingleObject(handle, 5000)
                report["forced_cleanup"] = True
            exit_code = W.DWORD()
            if kernel.GetExitCodeProcess(handle, C.byref(exit_code)):
                report["server_exit_code"] = exit_code.value
                report["server_exit_hex"] = f"0x{exit_code.value:08x}"
            kernel.CloseHandle(handle)
        if debugger and debugger.poll() is None:
            try:
                debugger.wait(timeout=5)
            except subprocess.TimeoutExpired:
                debugger.kill()
                debugger.wait(timeout=5)
                report["forced_cleanup"] = True
        report["helper_exit_code"] = helper.returncode if helper else None
        report["debugger_exit_code"] = debugger.returncode if debugger else None
        if cleanup_registration:
            try:
                cleanup_registration()
            except Exception as error:
                report["registration_cleanup_error"] = f"{type(error).__name__}: {error}"
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["hashes_after"] = hashes()
        report["processes_after"] = processes()
        log = out / "client.log"
        report["client_log"] = log.read_text(encoding="utf-16") if log.exists() else ""
        report["coordinated_reference_consumed"] = "held-reference-consumed-by-external-cleanup" in report["client_log"]
        cleanup_timing = re.search(r" coordinated-unload-ms=([0-9]+(?:\.[0-9]+)?)", report["client_log"])
        report["coordinated_unload_ms"] = float(cleanup_timing.group(1)) if cleanup_timing else None
        report["av_dump_saved"] = (out / "first-av.dmp").exists()
        debug_log = out / "debugger.log"
        report["first_chance_av_observed"] = (debug_log.exists() and
            "\nHARNESS77_FIRST_CHANCE_AV\n" in debug_log.read_text(errors="replace"))
        report["debugger_terminated_on_av"] = report["first_chance_av_observed"]
        debug_text = debug_log.read_text(errors="replace") if debug_log.exists() else ""
        report["basic_release_site_hits"] = debug_text.count("\nHARNESS77_BASIC_RELEASE_SITE\n")
        report["basic_release_skips"] = debug_text.count("\nHARNESS77_BASIC_RELEASE_SKIPPED\n")
        report["basic_release_intervention_observed"] = (
            args.basic_release_mode == "skip" and report["basic_release_skips"] > 0)
        if args.basic_release_mode != "none" and not report["basic_release_site_hits"]:
            report["diagnostic_limit"] = "borrowed BASIC release site was not reached"
        report["normal_shutdown_observed"] = (not report.get("error") and not report.get("registration_cleanup_error") and not report["first_chance_av_observed"]
            and not report["forced_cleanup"] and report.get("server_exit_code") == 0
            and report["helper_exit_code"] == 0 and "answer=42" in report["client_log"]
            and "released" in report["client_log"] and not report["processes_after"]
            and report["hashes_before"] == report["hashes_after"]
            and (args.basic_release_mode == "none" or report["basic_release_site_hits"] > 0)
            and (args.basic_release_mode != "skip" or report["basic_release_intervention_observed"]))
        if suite_manifest is not None:
            from module_suite77 import read_results
            report["module_suite"] = read_results(out, suite_manifest, report)
            (out / "suite-report.json").write_text(json.dumps(report["module_suite"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out / "observation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if suite_manifest is not None:
        return {"passed": 0, "failed": 1, "blocked": 2}[report["module_suite"]["status"]]
    if coordinated:
        return 0 if report["normal_shutdown_observed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
