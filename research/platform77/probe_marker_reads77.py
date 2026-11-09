"""Windows sharing-lock probes for task 051, using the production readers without 1C."""
import argparse
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import time

from marker_read77 import MarkerReadError, read_marker


@contextmanager
def exclusive(path):
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def permit_source():
    here = Path(__file__).resolve().parent
    gate = (here / "proxy_identity77.vbs").read_text(encoding="utf-8")
    helper = gate[gate.index("Function InitializePermitDetail"):]
    anchor = '        Emit "marker-read-retry", "initialize-permit", detail, elapsedMs'
    if helper.count(anchor) != 1:
        raise ValueError("unexpected permit reader layout")
    helper = helper.replace(anchor, anchor + '''
        If attempts = 1 Then
            Set probeSignal = fso.CreateTextFile(fso.BuildPath(proxyFolder, "retry-seen"), False)
            probeSignal.Close
        End If''')
    suite = (here / "module_suite77.vbs").read_text(encoding="utf-8")
    utilities = suite[suite.index("Function Quote"):suite.index("Sub CompileCase")]
    return '''Option Explicit
Dim fso, runId, eventPath, proxyFolder, proxyPermit, probeSignal
Set fso = CreateObject("Scripting.FileSystemObject")
runId = "probe51"
proxyFolder = WScript.Arguments(0)
eventPath = fso.BuildPath(proxyFolder, "events.jsonl")
''' + utilities + helper + '''
proxyPermit = ReadInitializePermit(fso.BuildPath(proxyFolder, "initialize-permit"))
If proxyPermit <> runId Then Fail "proxy-owner", "foreign permission"
Emit "probe-call", "Initialize", "invoke", 0
Emit "complete", "probe", "done", 0
'''


def permit_case(folder, mode):
    folder.mkdir()
    marker = folder / "initialize-permit"
    marker.write_text("foreign" if mode == "foreign" else "probe51", encoding="ascii")
    script = folder / "client.vbs"
    script.write_text(permit_source(), encoding="utf-16")
    host = Path(os.environ["WINDIR"]) / "SysWOW64/cscript.exe"
    command = [str(host), "//B", "//NoLogo", str(script), str(folder)]
    if mode == "foreign":
        result = subprocess.run(command, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        code = result.returncode
    else:
        process = None
        try:
            with exclusive(marker):
                process = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)
                if mode in ("transient", "cancel"):
                    until = time.monotonic() + 5
                    while not (folder / "retry-seen").exists():
                        if time.monotonic() >= until or process.poll() is not None:
                            raise RuntimeError("retry not observed while the permit was locked")
                        time.sleep(0.01)
                    if mode == "cancel":
                        (folder / "cancel").touch(exist_ok=False)
                if mode != "transient":
                    process.wait(timeout=15)
            code = process.wait(timeout=15)
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text(encoding="utf-16").splitlines()]
    calls = [e for e in events if e["kind"] == "probe-call"]
    retries = [json.loads(e["value"]) for e in events if e["kind"] == "marker-read-retry"]
    blocked = [e for e in events if e["kind"] == "blocked"]
    assert len(calls) == int(mode == "transient") and code == (0 if mode == "transient" else 2)
    assert bool(retries) == (mode != "foreign") and all(r["error_number"] == 70 for r in retries)
    if mode == "persistent":
        detail = json.loads(blocked[0]["value"])
        assert blocked[0]["name"] == "read-initialize-permit" and detail["operation"] == "permit-open"
        assert detail["error_number"] == 70 and 2 <= detail["attempts"] <= 26
    elif mode == "cancel":
        assert blocked[0]["name"] == "proxy-owner" and blocked[0]["value"] == "cancelled before Initialize"
    elif mode == "foreign":
        assert blocked[0]["name"] == "proxy-owner" and blocked[0]["value"] == "foreign permission"
    return {"mode": mode, "exit_code": code, "initialize_calls": len(calls), "retries": retries, "blocked": blocked}


def completion_case(folder):
    folder.mkdir()
    marker = folder / "ert-result-finished"
    marker.write_text("probe51", encoding="ascii")
    retries = []
    with exclusive(marker):
        try:
            read_marker(marker, retries, check=lambda: None)
        except MarkerReadError as error:
            detail = error.detail
        else:
            raise AssertionError("the locked completion marker could be read")
    assert detail["errno"] == 13 and 2 <= detail["attempts"] <= 26 and retries
    assert read_marker(marker, [], check=lambda: None) == "probe51"
    return {"mode": "persistent", "retries": retries, "failure": detail}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    permits = [permit_case(output / ("permit-" + mode), mode)
               for mode in ("transient", "persistent", "foreign", "cancel")]
    completion = completion_case(output / "finished-persistent")
    summary = {"status": "passed", "permit": permits, "finished": completion}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("passed: four FSO permit probes and a Windows completion-marker lock")


if __name__ == "__main__":
    main()
