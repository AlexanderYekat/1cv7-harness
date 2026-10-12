"""Bounded, read-only OLE smoke probe on an existing 1C 7.7 database.

Uses Windows PowerShell's COM adapter in a separate process. Does not change
ExecutionPolicy, drive the desktop, force-close 1C, or execute business reports.
The timeout bounds the helper only; server cleanup must be observed separately.
"""

import argparse
import base64
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time


def ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--user", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bits", type=int, choices=[32, 64], default=32)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--extensions", action="store_true", help="Probe installed FormEx/1CPP with a synthetic in-memory function")
    parser.add_argument("--runtime-extensions", action="store_true", help="Run the synthetic extension checks inside 1C's ExecuteBatch")
    parser.add_argument("--formex-fixture", type=Path, help="Synthetic ERT built by build_formex_fixture.py")
    parser.add_argument("--global-module-probe", action="store_true", help="Test FormEx's transient global module bridge")
    args = parser.parse_args()
    raise SystemExit("Runtime probes are blocked after the 2026-10-10 access-violation incident. See research/platform77/README.md; investigate shutdown before re-enabling launches.")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    base = args.base.resolve(strict=True)
    if '"' in str(base) or '"' in args.user:
        parser.error("quotes in database path or user are not supported")
    if args.output.resolve().is_relative_to(base):
        parser.error("output must be outside the database")
    args.output.mkdir(parents=True, exist_ok=False)
    if args.formex_fixture:
        fixture = args.formex_fixture.resolve(strict=True)
        if fixture.is_relative_to(base):
            parser.error("synthetic fixture must be outside the database")
        manifest = json.loads(fixture.with_name("fixture-manifest.json").read_text(encoding="utf-8"))
        if hashlib.sha256(fixture.read_bytes()).hexdigest() != manifest["synthetic_sha256"]:
            parser.error("fixture hash differs from builder manifest")
        form_result = fixture.with_name("form-result.txt")
        if form_result.exists():
            parser.error("rebuild the fixture in a new directory before another run")

    def hashes():
        return {name: hashlib.sha256((base / name).read_bytes()).hexdigest()
                for name in ["1Cv7.MD", "1Cv7.DD"]}

    report = {"started_at": datetime.datetime.now().astimezone().isoformat(),
              "base": str(base), "user": args.user, "bits": args.bits,
              "timeout_seconds": args.timeout, "hashes_before": hashes(),
              "scope": "ole_and_extensions" if args.extensions else "ole_open_and_eval_only",
              "forced_server_cleanup": False}
    extension_code = ""
    if args.extensions or args.runtime_extensions:
        for dll in ["FormEx.dll", "1CPP.dll"]:
            if not (base / dll).is_file():
                parser.error("Requested extension is missing: " + dll)
        extension_code = r'''
    Emit77 'extensions_started' @{}
    foreach ($dll77 in @('1CPP.dll', 'FormEx.dll')) {
        $dllPath77 = [IO.Path]::Combine(__BASE_PATH__, $dll77)
        $loadExpression77 = 'ЗагрузитьВнешнююКомпоненту("' + $dllPath77 + '")'
        $loaded77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @($loadExpression77))
        Emit77 'extension_loaded' @{name=$dll77;result=$loaded77}
    }
    $service77 = $null
    $module77 = $null
    $extensionFailure77 = $false
    try {
        try {
            $service77 = $type77.InvokeMember('CreateObject', $invoke77, $null, $v77, @('Сервис'))
            Emit77 'formex_service_created' @{created=($null -ne $service77)}
            if ($null -eq $service77) {throw 'FormEx service is null'}
        } catch {
            $extensionFailure77 = $true
            Emit77 'formex_error' @{message=$_.Exception.GetBaseException().Message}
        }
        try {
        Emit77 'icpp_create_started' @{}
        $module77 = $type77.InvokeMember('CreateObject', $invoke77, $null, $v77, @('ВыполняемыйМодуль'))
        Emit77 'icpp_created' @{created=($null -ne $module77)}
        $moduleType77 = $module77.GetType()
        $source77 = "Функция Harness77Answer() Экспорт`r`nВозврат 42;`r`nКонецФункции"
        [void]$moduleType77.InvokeMember('AssignSource', $invoke77, $null, $module77, @($source77))
        Emit77 'icpp_source_assigned' @{}
        $compiled77 = $moduleType77.InvokeMember('Compile', $invoke77, $null, $module77, $null)
        Emit77 'synthetic_module_compiled' @{result=$compiled77}
        if ($compiled77 -ne 1) {throw 'Synthetic module did not compile'}
        $executed77 = $moduleType77.InvokeMember('Execute', $invoke77, $null, $module77, $null)
        Emit77 'synthetic_module_executed' @{result=$executed77}
        if ($executed77 -ne 1) {throw 'Synthetic module did not initialize'}
        $answer77 = $moduleType77.InvokeMember('Harness77Answer', $invoke77, $null, $module77, $null)
        Emit77 'synthetic_function_evaluated' @{value=$answer77}
        if ($answer77 -ne 42) {throw 'Unexpected synthetic function result'}
        } catch {
            $extensionFailure77 = $true
            Emit77 'icpp_error' @{message=$_.Exception.GetBaseException().Message}
        }
    } finally {
        if ($null -ne $module77) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($module77); $module77=$null }
        if ($null -ne $service77) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($service77); $service77=$null }
    }
    if ($extensionFailure77) {throw 'Extension probes did not all succeed'}
'''
    if args.runtime_extensions:
        result_path = (args.output / "runtime-result.txt").resolve()
        batch = '''Т77 = СоздатьОбъект("Текст");
Попытка
    Т77.ДобавитьСтроку("1CPP-load=" + ЗагрузитьВнешнююКомпоненту("__DLL__"));
    М77 = СоздатьОбъект("ВыполняемыйМодуль");
    Т77.ДобавитьСтроку("module-created");
    М77.AssignSource("Функция Harness77Answer() Экспорт" + РазделительСтрок + "Возврат 42;" + РазделительСтрок + "КонецФункции");
    Т77.ДобавитьСтроку("source-assigned");
    Т77.ДобавитьСтроку("compile=" + М77.Compile());
    Т77.ДобавитьСтроку("execute=" + М77.Execute());
    Т77.ДобавитьСтроку("answer=" + М77.Harness77Answer());
Исключение
    Т77.ДобавитьСтроку("error=" + ОписаниеОшибки());
КонецПопытки;
Т77.Записать("__RESULT__");
'''.replace("__DLL__", str(base / "1CPP.dll")).replace("__RESULT__", str(result_path))
        extension_code = """
    Emit77 'runtime_extensions_started' @{}
    foreach ($expr77 in @('ТипЗначенияСтр(СоздатьОбъект("Текст"))', 'ТипЗначенияСтр(СоздатьОбъект("ВыполняемыйМодуль"))', 'ЗагрузитьВнешнююКомпоненту("__FORMEX__")', 'ТипЗначенияСтр(СоздатьОбъект("Сервис"))')) {
        $result77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @($expr77))
        Emit77 'runtime_type_probe' @{expression=$expr77;value=$result77}
    }
    $batchResult77 = $type77.InvokeMember('ExecuteBatch', $invoke77, $null, $v77, @(__BATCH__))
    Emit77 'runtime_extensions_returned' @{result=$batchResult77}
    $errorText77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @('ОписаниеОшибки()'))
    Emit77 'runtime_last_error' @{message=$errorText77}
""".replace("__BATCH__", ps_string(batch)).replace("__FORMEX__", str(base / "FormEx.dll"))
    if args.formex_fixture:
        extension_code = """
    $load77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @(__LOAD__))
    Emit77 'formex_loaded' @{result=$load77}
    Emit77 'form_open_started' @{}
    $open77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @(__OPEN__))
    Emit77 'form_open_returned' @{result=$open77}
    $deadline77 = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline77) {
        if (Test-Path -LiteralPath __RESULT__) {
            $resultText77 = [IO.File]::ReadAllText(__RESULT__, [Text.Encoding]::GetEncoding(1251))
            if ($resultText77 -match '(?m)^done\\r?$') {break}
        }
        Start-Sleep -Milliseconds 100
    }
    Emit77 'form_wait_finished' @{}
""".replace("__LOAD__", ps_string('ЗагрузитьВнешнююКомпоненту("' + str(base / "FormEx.dll") + '")')).replace(
            "__OPEN__", ps_string('ОткрытьФорму("Отчет", , "' + str(fixture) + '")')).replace("__RESULT__", ps_string(form_result))
    if args.global_module_probe:
        native_source = '''Функция Harness77NativeProbe() Экспорт
    М77 = СоздатьОбъект("ВыполняемыйМодуль");
    М77.AssignSource("Функция Harness77Answer() Экспорт" + РазделительСтрок + "Возврат 42;" + РазделительСтрок + "КонецФункции");
    Если М77.Compile() <> 1 Тогда Возврат "compile-failed"; КонецЕсли;
    Если М77.Execute() <> 1 Тогда Возврат "execute-failed"; КонецЕсли;
    Возврат М77.Harness77Answer();
КонецФункции
'''
        expression = 'СоздатьОбъект("Сервис").ДобавитьГлобальныйМодуль("' + native_source.replace('"', '""').replace('\n', '" + РазделительСтрок + "') + '")'
        extension_code = """
    $load77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @(__LOAD__))
    Emit77 'formex_loaded' @{result=$load77}
    $added77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @(__ADD__))
    Emit77 'global_module_added' @{result=$added77}
    if ($added77 -le 0) {throw 'Temporary global module not loaded'}
    try {
        $answer77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @('Harness77NativeProbe()'))
        Emit77 'global_module_answer' @{value=$answer77}
        if ($answer77 -ne 42) {throw 'Wrong native answer'}
    } finally {
        $delExpr77 = 'СоздатьОбъект("Сервис").УдалитьГлобальныйМодуль(' + $added77 + ')'
        $removed77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @($delExpr77))
        Emit77 'global_module_removed' @{result=$removed77}
    }
""".replace("__LOAD__", ps_string('ЗагрузитьВнешнююКомпоненту("' + str(base / "FormEx.dll") + '")')).replace("__ADD__", ps_string(expression))
    command_line = '/D"' + str(base) + '" /N"' + args.user + '"'
    command = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
function Emit77($eventName, $data) {
    [pscustomobject]@{event=$eventName; at=(Get-Date).ToString('o'); data=$data} | ConvertTo-Json -Depth 8 -Compress
}
function Processes77 {
    @(Get-Process -Name 1cv7l -ErrorAction SilentlyContinue | Select-Object Id,StartTime,Path,MainWindowTitle)
}
$v77 = $null
$failure77 = $false
Emit77 'helper_started' @{pid=$PID;bits=([IntPtr]::Size*8)}
Emit77 'processes_before' @{processes=(Processes77)}
try {
    Emit77 'activation_started' @{}
    $v77 = New-Object -ComObject V77L.Application
    Emit77 'activated' @{processes=(Processes77)}
    $type77 = $v77.GetType()
    $invoke77 = [Reflection.BindingFlags]::InvokeMethod
    $mode77 = $type77.InvokeMember('RMTrade', $invoke77, $null, $v77, $null)
    Emit77 'initialize_started' @{mode=$mode77;mode_type=$mode77.GetType().FullName}
    $initialized77 = $type77.InvokeMember('Initialize', $invoke77, $null, $v77, @($mode77, __COMMAND_LINE__, 'NO_SPLASH_SHOW'))
    Emit77 'initialized' @{result=$initialized77}
    if (-not $initialized77) {throw 'Initialize returned false'}
    $path77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @('КаталогИБ()'))
    $value77 = $type77.InvokeMember('EvalExpr', $invoke77, $null, $v77, @('6 * 7'))
    Emit77 'evaluated' @{database_path=$path77;value=$value77}
    if ([IO.Path]::GetFullPath([string]$path77).TrimEnd('\') -ine __BASE_PATH__) {throw 'Unexpected database path'}
    if ($value77 -ne 42) {throw 'Unexpected arithmetic result'}
__EXTENSIONS__
} catch {
    $failure77 = $true
    $ex77 = $_.Exception.GetBaseException()
    Emit77 'error' @{message=$ex77.Message;hresult=('0x{0:X8}' -f $ex77.HResult)}
} finally {
    if ($null -ne $v77) {
        Emit77 'release_started' @{}
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($v77)
        $v77 = $null
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
        Emit77 'released' @{}
    }
}
Emit77 'helper_finished' @{processes=(Processes77)}
if ($failure77) {exit 2}
'''.replace("__EXTENSIONS__", extension_code).replace("__COMMAND_LINE__", ps_string(command_line)).replace("__BASE_PATH__", ps_string(base))
    shell = Path("C:/Windows") / ("SysWOW64" if args.bits == 32 else "System32") / "WindowsPowerShell/v1.0/powershell.exe"
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    start = time.monotonic()
    focus = None
    if args.formex_fixture:
        from focus_observer import FocusObserver
        focus = FocusObserver()
        focus.start()
    with (args.output / "events.jsonl").open("wb") as out, (args.output / "stderr.txt").open("wb") as err:
        process = subprocess.Popen([str(shell), "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
                                   stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        report["helper_pid"] = process.pid
        try:
            report["exit_code"] = process.wait(timeout=args.timeout)
            report["timed_out"] = False
        except subprocess.TimeoutExpired:
            process.kill()  # This exact helper, never a 1C process selected by name.
            process.wait()
            report["exit_code"] = process.returncode
            report["timed_out"] = True
    report["elapsed_seconds"] = round(time.monotonic() - start, 3)
    if focus is not None:
        report["focus"] = focus.finish()
    report["hashes_after"] = hashes()
    report["metadata_unchanged"] = report["hashes_before"] == report["hashes_after"]
    events = [json.loads(line) for line in (args.output / "events.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    report["events"] = events
    runtime_ok = True
    if args.runtime_extensions:
        runtime_text = result_path.read_text(encoding="cp1251") if result_path.exists() else ""
        report["runtime_result"] = runtime_text
        runtime_ok = all(line in runtime_text.splitlines() for line in ["compile=1", "execute=1", "answer=42"])
    if args.formex_fixture:
        report["scope"] = "synthetic_formex_form_and_icpp"
        runtime_text = form_result.read_text(encoding="cp1251") if form_result.exists() else ""
        report["form_result"] = runtime_text
        runtime_ok = all(line in runtime_text.splitlines() for line in [
            "icpp-compile=1", "icpp-execute=1", "icpp-answer=42", "formex-attached", "done",
            "handler-call=1", "after-handler=background-77;background-77|1;0"])
    report["outcome"] = "passed" if (not report["timed_out"] and report["exit_code"] == 0
                                      and report["metadata_unchanged"] and runtime_ok
                                      and any(e["event"] == "evaluated" for e in events)) else "blocked"
    (args.output / "observation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"outcome": report["outcome"], "elapsed_seconds": report["elapsed_seconds"],
                      "timed_out": report["timed_out"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["outcome"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
