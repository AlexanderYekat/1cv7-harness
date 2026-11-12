"""Verify recovery after a suite crash through MCP on a pinned 1C 7.7 stand."""
import argparse
from contextlib import ExitStack
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from harness77 import basecopy77
from harness77.config77 import ConfigError, load_project, load_stand, resolve_deadlines
from harness77.report77 import atomic_json, sha256_file

ROOT = Path(__file__).resolve().parents[2]
if os.name == "nt":
    import winreg

    sys.path.insert(0, str(ROOT / "research/platform77"))
    from win32_session77 import (OWNER_VALUE, ProcessEntry, base_titles_fingerprint, kernel, process_gone,
                                 process_identity, processes, read_tree, register_cleanup_helper, registration_lock)

VIEW = 0x0200
COM = (
    r"Software\Classes\Harness77Diagnostic.ProxyIdentity",
    r"Software\Classes\CLSID\{7E477C71-018E-4C27-9E38-2D5DDA9F6A07}",
    r"Software\Classes\Harness77Diagnostic.ComCleanup",
    r"Software\Classes\CLSID\{16B8A521-07E4-46D1-A8E7-197BD1CE4477}",
)
NAMES = ("Первый сценарий", "Второй сценарий", "Третий сценарий")
FIRST, SECOND, THIRD = [f"suite: сценарий {index}/3 «{name}»" for index, name in enumerate(NAMES, 1)]
START = "запускает 1С"
WAIT_COPY = "ждёт освобождения пути копии"
PREPARE_COPY = "готовит копию"
CONTROLLERS = ("mcp", "suite", "registrar")
SURVIVORS = ("client", "server", "debugger")
KILL_CODE = 0x8200
DEADLINES = {"open_timeout_s": 650, "total_timeout_s": 900}


class Probe:
    def __init__(self, stand, project, output, retry_count, waiter_mode=None):
        self.stand, self.project, self.out = stand, project, output
        self.source = stand.base.resolve(strict=True)
        self.runs = output / "runs"
        self.copy = output / "copy"
        self.lock = basecopy77.lock_path(self.copy)
        self.guard = self.lock.with_name(self.lock.name + ".guard")
        self.marker = self.copy / basecopy77.MARKER
        self.sentinel = self.copy / "stale-copy.txt"
        self.waiter_mode = waiter_mode
        self.task = {"cancel": "084", "timeout": "085", "close": "086", "crash": "087"}.get(
            waiter_mode, "082" if retry_count == 1 else "083")
        self.retries = {channel: self.runs / str(uuid4())
                        for channel in ("retry", "retry-2")[:retry_count]}
        self.next_run = self.runs / str(uuid4()) if waiter_mode else None


def toml_value(value):
    """Encode the TOML-compatible profile values accepted by config77."""
    if isinstance(value, Path):
        value = value.as_posix()
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{toml_value(key)} = {toml_value(item)}" for key, item in value.items()) + " }"
    if isinstance(value, (tuple, list)):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def write_profile(path, **tables):
    text = "schema_version = 1\n" + "".join(f"{key} = {toml_value(value)}\n" for key, value in tables.items())
    path.write_text(text, encoding="utf-8")


def write_profiles(probe):
    stand, project = probe.stand, probe.project
    write_profile(probe.out / "stand.toml", deadlines=stand.deadlines_raw, stand={
        "name": stand.name, "backend": stand.backend, "platform_version": stand.platform_version,
        "launcher": Path(__file__).with_name("suite_recovery_launcher77.py").resolve(),
        "screenshots": stand.screenshots, "credential_source": stand.credential_source,
        "paths": {key: getattr(stand, key) for key in ("exe", "cdb", "helper", "identity")},
        "base": {"path": probe.source, "user": stand.user, "copy_path": probe.copy, "copy_exclude": stand.copy_exclude},
        "pinned": stand.pinned, "tool_hashes": stand.tool_hashes,
    })
    build = {"template": project.template, "source": project.source, "encoding": project.encoding,
             "legacy_normalize": project.legacy_normalize}
    build.update({key: getattr(project, key) for key in ("form", "metadata") if getattr(project, key) is not None})
    test = dict(project.tests[0], expect_value="42")
    for filename, hold in (("project.toml", False), ("hold.toml", True)):
        write_profile(probe.out / filename, project={"id": project.project_id}, build=build,
                      analysis={"globals": project.globals, "allow": project.allow, "strict": project.strict},
                      configuration={"modules": project.configuration, "keep_copy": False},
                      deadlines=project.deadlines_raw,
                      platform={"tests": [test], "parameters": dict(project.parameters, probe_hold=hold)})
    scenarios = [{"id": name, "project": filename}
                 for name, filename in zip(NAMES, ("project.toml", "hold.toml", "project.toml"))]
    write_profile(probe.out / "suite.toml", suite={"id": f"open-copy-recovery-{probe.task}"}, scenarios=scenarios)


def checked(value):
    if not value:
        raise C.WinError(C.get_last_error())
    return value


def process_parents(image=None):
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        parents = {}
        row = ProcessEntry()
        row.dwSize = C.sizeof(row)
        found = kernel.Process32FirstW(snapshot, C.byref(row))
        while found:
            if image is None or row.szExeFile.casefold() == image.casefold():
                parents[row.th32ProcessID] = row.th32ParentProcessID
            found = kernel.Process32NextW(snapshot, C.byref(row))
        return parents
    finally:
        kernel.CloseHandle(snapshot)


def retain_suite_processes(probe, stack, suite_server, cli_pid, native_processes):
    parents = process_parents()
    registrar, debugger, server, client = native_processes
    expected_parents = {suite_server.pid: os.getpid(), cli_pid: suite_server.pid,
                        registrar["pid"]: cli_pid, debugger["pid"]: registrar["pid"],
                        server["pid"]: debugger["pid"], client["pid"]: registrar["pid"]}
    assert len(expected_parents) == 6 and all(parents.get(pid) == parent for pid, parent in expected_parents.items())
    identities, handles = {}, {}
    python = Path(sys.executable).resolve()
    images = {suite_server.pid: python, cli_pid: python, registrar["pid"]: python,
              debugger["pid"]: probe.stand.cdb.resolve(),
              server["pid"]: probe.stand.exe.resolve(),
              client["pid"]: (Path(os.environ["SystemRoot"]) / "SysWOW64/cscript.exe").resolve()}
    roles = {suite_server.pid: "mcp", cli_pid: "suite"}
    roles.update({entry["pid"]: entry["role"] for entry in native_processes})
    for pid, role in roles.items():
        access = 0x100000 | 0x1000
        if role in CONTROLLERS:
            access |= 1
        handle = checked(kernel.OpenProcess(access, False, pid))
        stack.callback(kernel.CloseHandle, handle)
        identity = process_identity(handle)
        assert kernel.WaitForSingleObject(handle, 0) == 0x102
        assert Path(identity["image"]).resolve() == images[pid]
        handles[role] = handle
        identities[pid] = dict(identity, pid=pid, parent_pid=parents[pid], role=role)
    assert all(identities[entry["pid"]]["creation_filetime"] == entry["creation_filetime"]
               for entry in native_processes)
    assert identities[suite_server.pid]["creation_filetime"] == process_identity(int(suite_server._handle))["creation_filetime"]
    return handles, list(identities.values())


def stop_owned(role, handle):
    assert role in (*CONTROLLERS, "cli")
    state = kernel.WaitForSingleObject(handle, 0)
    if state == 0:
        return
    if state != 0x102:
        raise RuntimeError(f"unexpected process state for {role}: {state}")
    terminated = kernel.TerminateProcess(handle, KILL_CODE)
    error = C.get_last_error() if not terminated else None
    if kernel.WaitForSingleObject(handle, 20000) == 0:
        return
    if error is not None:
        raise RuntimeError(f"test process {role} did not exit") from C.WinError(error)
    raise TimeoutError(f"test process {role} did not exit")


def await_survivors(handles):
    exit_codes = {}
    for role in SURVIVORS:
        if kernel.WaitForSingleObject(handles[role], 120000) != 0:
            raise TimeoutError(f"test process {role} did not exit after the OLE client resumed")
        code = C.c_ulong()
        checked(kernel.GetExitCodeProcess(handles[role], C.byref(code)))
        exit_codes[role] = code.value
    return exit_codes


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def com_snapshot():
    return [read_tree(key, VIEW) for key in COM]


def copy_snapshot(probe):
    return (probe.lock.read_bytes(), probe.marker.read_bytes(), basecopy77.listing(probe.copy),
            sha256_file(probe.copy / basecopy77.MD), com_snapshot())


def platform(report):
    return next(stage for stage in report["stages"] if stage["stage"] == "platform_check")


def verify_copy(report):
    copy = platform(report)["base_copy"]
    assert copy["removal"]["removed"] and copy["lock"]["released"] and copy["source_check"]["unchanged"]
    assert platform(report)["base_list"]["unchanged"]


def verify_passed(run):
    report = read_json(run / "run.json")
    assert report["run_id"] == run.name and report["status"] == "passed" and report["exit_code"] == 0
    assert report["platform_checked"] and report["platform"]["platform_version"] == "7.70.027"
    assert report["shutdown"]["cleanup_verified"] and report["shutdown"]["others_preserved"]
    assert not report["shutdown"]["forced_cleanup"]
    verify_copy(report)
    events = [json.loads(line) for line in (run / "native/ert-events.jsonl").read_text(encoding="utf-16").splitlines()]
    assert all(event["run_id"] == run.name for event in events)
    calls = sum(event.get("kind") == "probe57" and event.get("name") == "Initialize" for event in events)
    values = [test["value"] for stage in report["stages"] if stage["stage"] == "tests" for test in stage["tests"]]
    assert calls == 1 and values == ["42"]
    return {"run_id": run.name, "values": values, "initialize_calls": calls}


def verify_stopped(run, reason):
    report = read_json(run / "run.json")
    assert (report["run_id"], report["status"], report["exit_code"]) == (run.name, "blocked", 2)
    cancelled = reason == "cancelled"
    assert report["cancelled"] == cancelled and not report["platform_checked"]
    assert report["timeout_phase"] == (None if cancelled else "open")
    stage = platform(report)
    assert stage["reason"] == reason and not stage["platform_checked"]
    assert set(stage["base_copy"]) == {"wait"}
    copy_wait = stage["base_copy"]["wait"]
    assert not copy_wait["acquired"] and copy_wait["elapsed_s"] > 0
    return {"run_id": run.name, "status": report["status"], "exit_code": report["exit_code"],
            "reason": stage["reason"], "platform_checked": False, "copy_wait": copy_wait}


def initialize_calls(native):
    events = native / "ert-events.jsonl"
    if not events.is_file():
        return 0
    rows = (json.loads(line) for line in events.read_text(encoding="utf-16").splitlines())
    return sum(row.get("kind") == "probe57" and row.get("name") == "Initialize" for row in rows)


def verify_checkpoint(probe, first, second):
    folder = probe.out / "crash"
    report = read_json(folder / "suite.json")
    assert report["suite_id"] == "crash" and not report["complete"] and not report["cancelled"]
    assert (report["status"], report["finished_at"], report["exit_code"]) == ("blocked", None, 2)
    assert report["counts"] == {"passed": 1, "failed": 0, "blocked": 1, "skipped": 1}
    junit = folder / "junit.xml"
    assert report["junit"]["complete"] and sha256_file(junit) == report["junit"]["sha256"]
    root = ET.parse(junit).getroot()
    assert [root.get(key) for key in ("tests", "failures", "errors", "skipped")] == ["3", "0", "1", "1"]
    cases = root.findall("testsuite/testcase")
    assert [case.get("name") for case in cases] == list(NAMES)
    rows = report["scenarios"]
    assert [row["status"] for row in rows] == ["passed", "blocked", "skipped"]
    assert rows[0]["platform_checked"] and rows[1]["reason"] == "scenario is running; no complete result yet"
    assert rows[1]["run_id"] == second.name and rows[1]["report"] is None and not rows[1]["platform_checked"]
    assert rows[2]["run_id"] is None and rows[2]["report"] is None
    assert all(cases[0].find(tag) is None for tag in ("error", "failure", "skipped"))
    assert cases[1].find("error").get("message") == rows[1]["reason"] and cases[2].find("skipped") is not None
    assert root.find("testsuite/properties/property[@name='complete']").get("value") == "False"
    for row, case in zip(rows, cases):
        link = json.loads(case.findtext("system-out"))
        assert link["run_id"] == row["run_id"] and link["report"] == row["report"]
    path = (folder / rows[0]["report"]["path"]).resolve()
    assert path == first / "run.json" and rows[0]["run_id"] == first.name
    assert sha256_file(path) == rows[0]["report"]["sha256"]
    assert not (second / "run.json").exists()
    native = second / "native"
    assert (native / "ert-probe-holding").is_file() and (native / "initialize-permit").is_file()
    assert initialize_calls(native) == 1
    return {"complete": report["complete"], "counts": report["counts"], "junit": report["junit"],
            "first": verify_passed(first), "first_report_sha256": sha256_file(path),
            "second": {"run_id": second.name, "started_1c": True, "initialize_calls": 1, "complete_report": False},
            "suite_report_sha256": sha256_file(folder / "suite.json")}


def verify(probe, evidence):
    write_profiles(probe)
    held = set()
    channels = evidence["channels"] = {}
    servers, readers = {}, {}
    handles = {}
    crash_started = False
    waited_for_survivors = False
    temporary = probe.out / "mcp-tmp"
    temporary.mkdir()
    env = dict(os.environ, TEMP=str(temporary), TMP=str(temporary))
    with ExitStack() as logs, ExitStack() as retained:

        def receive(channel, server):
            for line in server.stdout:
                channels[channel]["received"].append(json.loads(line.decode("utf-8")))

        def send(channel, method, params=None, request=None):
            message = dict(jsonrpc="2.0", method=method, params=params or {})
            if request is not None:
                message["id"] = request
            server = servers[channel]
            server.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
            server.stdin.flush()
            channels[channel]["sent"].append(message)

        def reply(channel, request):
            return next((row for row in channels[channel]["received"] if row.get("id") == request), None)

        def wait(watch, predicate, label, seconds, pending=None):
            watched = (watch,) if isinstance(watch, str) else tuple(watch)
            deadline = time.monotonic() + seconds
            while not (value := predicate()):
                for channel in watched:
                    code = servers[channel].poll()
                    early = reply(channel, pending) if pending else None
                    if code is not None or early:
                        raise RuntimeError(f"missing {label}; {channel} MCP={code}; early reply={early}")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"missing {label}; watching {watched}")
                time.sleep(.05)
            return value

        def call(channel, tool, name, **arguments):
            arguments = dict(DEADLINES, **arguments, stand=str(probe.out / "stand.toml"))
            send(channel, "tools/call", dict(name=tool, arguments=arguments, _meta={"progressToken": name}), name)

        def progress(channel, name):
            return [row["params"]["message"].rsplit(", ", 1)[0] for row in channels[channel]["received"]
                    if row.get("method") == "notifications/progress" and row["params"]["progressToken"] == name]

        waiting = "run: " + WAIT_COPY

        def heartbeats(channel):
            return progress(channel, "retry").count(waiting)

        def verify_queued(channel, run):
            assert not (run / "native").exists() and not reply(channel, "retry")
            labels = progress(channel, "retry")
            assert "run: " + PREPARE_COPY not in labels and "run: " + START not in labels

        def suite_run(index):
            path = probe.out / "crash/suite.json"
            if path.is_file() and (run_id := read_json(path)["scenarios"][index]["run_id"]):
                return probe.runs / run_id
            return None

        def start_server(channel):
            channels[channel] = {"sent": [], "received": []}
            stderr = logs.enter_context((probe.out / f"mcp-{channel}-stderr.txt").open("wb"))
            server = servers[channel] = subprocess.Popen(
                [sys.executable, "-B", "-m", "harness77", "mcp"], cwd=ROOT, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=stderr, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            reader = readers[channel] = threading.Thread(target=receive, args=(channel, server))
            reader.start()
            channels[channel]["pid"] = server.pid
            send(channel, "initialize", dict(protocolVersion="2025-11-25", capabilities={},
                                             clientInfo={"name": f"task-{probe.task}-{channel}", "version": "1"}), "init")
            init = wait(channel, lambda: reply(channel, "init"), "MCP handshake", 60)
            assert init["result"]["serverInfo"]["name"] == "harness77"
            send(channel, "notifications/initialized")

        def start_retry(channel, run, **deadlines):
            held.add(run / "native")
            call(channel, "run", "retry", project=str(probe.out / "hold.toml"),
                 output_root=str(probe.runs), run_id=run.name, **deadlines)

        def stop_waiter(owner, run):
            channel = "retry-2"
            queued_run = probe.retries[channel]
            owner_copy = copy_snapshot(probe)
            registrations = [json.loads(owner_copy[4][index][COM[index]][OWNER_VALUE]) for index in (0, 2)]
            assert all(record["run_id"] == run.name for record in registrations)
            owner_processes = registrations[0]["processes"]
            assert owner_processes == registrations[1]["processes"]
            assert [row["role"] for row in owner_processes] == ["registrar", "debugger", "server", "client"]
            mode = probe.waiter_mode
            start_retry(channel, queued_run, **({"open_timeout_s": 25} if mode == "timeout" else {}))
            wait((owner, channel), lambda: heartbeats(channel) >= 2,
                 "second retry waiting for the recovered copy", 30, "retry")
            verify_queued(channel, queued_run)
            assert copy_snapshot(probe) == owner_copy
            log = probe.out / f"mcp-{channel}-stderr.txt"
            if mode == "crash":
                # A Windows console host may also be a child; select the Python CLI only.
                parents = process_parents(Path(sys.executable).name)
                server = servers[channel]
                children = [pid for pid, parent in parents.items() if parent == server.pid]
                assert len(children) == 1, f"expected one Python CLI child of {server.pid}, found {children}"
                killed = []
                # Retain both identities before ending either process. No owner or native PID is selected.
                with ExitStack() as waiter_handles:
                    targets = []
                    for role, pid in (("mcp", server.pid), ("cli", children[0])):
                        handle = checked(kernel.OpenProcess(0x100000 | 0x1000 | 1, False, pid))
                        waiter_handles.callback(kernel.CloseHandle, handle)
                        identity = process_identity(handle)
                        assert kernel.WaitForSingleObject(handle, 0) == 0x102
                        assert Path(identity["image"]).resolve() == Path(sys.executable).resolve()
                        if role == "mcp":
                            assert identity == process_identity(int(server._handle))
                        else:
                            assert identity["creation_filetime"] >= process_identity(int(server._handle))["creation_filetime"]
                            assert process_parents().get(pid) == server.pid
                        waiter_handles.callback(stop_owned, role, handle)
                        targets.append((role, handle))
                        killed.append(dict(identity, pid=pid, parent_pid=parents[pid], role=role))
                    for (role, handle), record in zip(targets, killed):
                        stop_owned(role, handle)
                        code = C.c_ulong()
                        checked(kernel.GetExitCodeProcess(handle, C.byref(code)))
                        assert code.value == KILL_CODE
                        record["exit_code"] = code.value
                assert server.wait(timeout=20) == KILL_CODE
                readers[channel].join(timeout=15)
                assert not readers[channel].is_alive()
                assert not (queued_run / "run.json").exists()
                assert "cancel file created" not in log.read_text(encoding="utf-8")
                stopped = {"run_id": queued_run.name, "terminated": killed, "complete_report": False}
                delivered = False
            else:
                if mode == "cancel":
                    send(channel, "notifications/cancelled", {"requestId": "retry", "reason": "cancel copy waiter"})
                elif mode == "close":
                    servers[channel].stdin.close()
                wait(owner, lambda: (queued_run / "run.json").is_file()
                     and "run: exit 2 in " in log.read_text(encoding="utf-8"),
                     "waiting CLI exits before the owner is released", 60)
                stopped = verify_stopped(queued_run, "open_timeout" if mode == "timeout" else "cancelled")
                if mode == "cancel":
                    send(channel, "ping", request="after-cancel")
                    pong = wait(channel, lambda: reply(channel, "after-cancel"), "MCP ping after cancellation", 15, "retry")
                    assert pong["result"] == {}
                    delivered = False
                else:
                    result = wait(owner, lambda: reply(channel, "retry"), "stopped retry result", 15)["result"]
                    assert result["isError"] and result["structuredContent"]["exit_code"] == 2
                    delivered = True
                    if mode == "close":
                        assert servers[channel].wait(timeout=20) == 0
                        readers[channel].join(timeout=15)
                        assert not readers[channel].is_alive()
                        assert "input closed; waiting for 1 call(s)" in log.read_text(encoding="utf-8")
                    else:
                        assert stopped["copy_wait"]["elapsed_s"] >= 25
                        send(channel, "ping", request="after-timeout")
                        assert wait(channel, lambda: reply(channel, "after-timeout"), "ping after timeout", 15)["result"] == {}
            assert not (queued_run / "native").exists() and initialize_calls(queued_run / "native") == 0
            labels = progress(channel, "retry")
            assert "run: " + PREPARE_COPY not in labels and "run: " + START not in labels
            assert bool(reply(channel, "retry")) == delivered
            assert not (run / "native/probe-release").exists() and not reply(owner, "retry")
            assert copy_snapshot(probe) == owner_copy
            assert basecopy77._native_holds_lock(probe.lock) and basecopy77.open_in_1c(probe.copy) == "1SUSERS.DBF"
            assert all(process_gone(entry) is None for entry in owner_processes)
            evidence_key = {"cancel": "cancelled_retry", "timeout": "timed_out_retry",
                            "close": "closed_retry", "crash": "crashed_retry"}[mode]
            evidence[evidence_key] = dict(
                stopped, channel=channel, copy_path=str(probe.copy), owner_run_id=run.name,
                owner_copy_preserved=True, owner_processes_live=True, mcp_response_delivered=delivered,
                initialize_calls=0, wait_heartbeats=heartbeats(channel))
            print(f"{channel} stopped ({mode}) before starting 1C; {owner} still holds the recovered copy", flush=True)

        try:
            start_server("suite")
            call("suite", "suite", "crash", suite=str(probe.out / "suite.toml"), output_root=str(probe.out),
                 suite_id="crash")
            first = wait("suite", lambda: suite_run(0), "first scenario run_id", 60, "crash")
            second = wait("suite", lambda: suite_run(1), "second scenario run_id", 900, "crash")
            print("first scenario finished; waiting for the second to open its copy", flush=True)
            native = second / "native"
            held.add(native)
            wait("suite", (native / "ert-probe-holding").is_file,
                 "second scenario paused after Initialize and check", 650, "crash")
            wait("suite", lambda: SECOND + " — " + START in progress("suite", "crash"),
                 "second scenario starts 1C", 15, "crash")
            lock = read_json(probe.lock)
            assert lock["run_id"] == second.name
            assert read_json(probe.marker)["run_id"] == second.name
            assert basecopy77._native_holds_lock(probe.lock) and basecopy77.open_in_1c(probe.copy) == "1SUSERS.DBF"
            checkpoint = verify_checkpoint(probe, first, second)
            probe.sentinel.write_text(second.name, encoding="ascii")
            stale_copy = copy_snapshot(probe)
            registrations = [json.loads(stale_copy[4][i][COM[i]][OWNER_VALUE]) for i in (0, 2)]
            for record, dll in zip(registrations, ("identity", "helper")):
                assert record["run_id"] == second.name
                assert Path(record["dll"]).resolve() == getattr(probe.stand, dll).resolve()
            native_processes = registrations[0]["processes"]
            assert native_processes == registrations[1]["processes"]
            assert [entry["role"] for entry in native_processes] == ["registrar", "debugger", "server", "client"]
            assert all(process_gone(entry) is None for entry in native_processes)
            proxy = read_json(native / "proxy-verified.json")
            assert proxy["identity"]["run_id"] == second.name and proxy["identity"]["pid"] == native_processes[2]["pid"]
            assert proxy["server"]["ownership_verified"]
            assert all(proxy["server"][key] == native_processes[2][key] for key in ("pid", "creation_filetime"))
            assert read_json(native / "owner.json")["debugger_pid"] == native_processes[1]["pid"]
            evidence["native_processes"] = native_processes
            evidence["crashed_run_id"] = second.name
            handles, identities = retain_suite_processes(probe, retained, servers["suite"], lock["pid"], native_processes)
            print("scenario 2 initialized once and holds the open copy; crashing controllers only", flush=True)

            crash_started = True
            for role in CONTROLLERS:
                stop_owned(role, handles[role])
            evidence["terminated"] = [entry for entry in identities if entry["role"] in CONTROLLERS]
            assert all(kernel.WaitForSingleObject(handles[role], 0) == 0x102 for role in SURVIVORS)
            suite_exit = servers["suite"].wait(timeout=20)
            readers["suite"].join(timeout=15)
            assert suite_exit == KILL_CODE and not readers["suite"].is_alive()
            suite_log = (probe.out / "mcp-suite-stderr.txt").read_text(encoding="utf-8")
            assert "input closed; waiting" not in suite_log and "suite: cancel file created" not in suite_log
            assert not reply("suite", "crash") and not (second / "cancel").exists()
            assert not (second / "platform-result.json").exists()
            assert verify_checkpoint(probe, first, second) == checkpoint and copy_snapshot(probe) == stale_copy
            assert basecopy77._native_holds_lock(probe.lock) and basecopy77.open_in_1c(probe.copy) == "1SUSERS.DBF"
            evidence["crash"] = {"mcp_exit_code": suite_exit, "response_delivered": False,
                                 "checkpoint": checkpoint, "stale_copy_files": len(stale_copy[2]),
                                 "both_com_registrations_left": True, "open_table": "1SUSERS.DBF"}
            labels = progress("suite", "crash")
            expected = (FIRST, FIRST + " — " + START, SECOND, SECOND + " — " + START)
            positions = [labels.index(label) for label in expected]
            assert positions == sorted(set(positions))
            assert all(label.startswith(SECOND) for label in labels[positions[2]:])
            assert not any(label.startswith(THIRD) for label in labels)
            assert all(row["method"] != "notifications/cancelled" for channel in channels.values() for row in channel["sent"])
            evidence["progress_labels"] = list(expected)
            print("MCP, CLI and launcher exited; CDB, 1C and OLE client are still live", flush=True)

            for channel in probe.retries:
                start_server(channel)
            initial_retries = {"retry": probe.retries["retry"]} if probe.next_run else probe.retries
            for channel, run in initial_retries.items():
                start_retry(channel, run)
            wait(initial_retries, lambda: all(heartbeats(channel) >= 2 for channel in initial_retries),
                 "retry copy queue heartbeats with live old session", 180, "retry")
            for channel, run in initial_retries.items():
                verify_queued(channel, run)
            assert all(kernel.WaitForSingleObject(handles[role], 0) == 0x102 for role in SURVIVORS)
            assert basecopy77._native_holds_lock(probe.lock) and basecopy77.open_in_1c(probe.copy) == "1SUSERS.DBF"
            assert copy_snapshot(probe) == stale_copy and probe.sentinel.read_text(encoding="ascii") == second.name
            assert verify_checkpoint(probe, first, second) == checkpoint
            evidence["waiting"] = {"heartbeats": heartbeats("retry"), "copy_preserved": True,
                                   "native_lease_active": True, "open_table": "1SUSERS.DBF",
                                   "live_processes": [entry for entry in identities if entry["role"] in SURVIVORS]}
            if len(initial_retries) == 2:
                evidence["waiting"]["retry_heartbeats"] = {channel: heartbeats(channel) for channel in initial_retries}
            print(f"{len(initial_retries)} retry request(s) waiting; old copy, lock, COM and processes preserved", flush=True)

            (native / "probe-release").touch()
            waited_for_survivors = True
            exit_codes = await_survivors(handles)
            assert exit_codes == dict.fromkeys(SURVIVORS, 0), exit_codes
            shutdown = [json.loads(line) for line in (native / "shutdown-events.jsonl")
                        .read_text(encoding="utf-16").splitlines()]
            assert all(row["run_id"] == second.name for row in shutdown)
            assert any(row["name"] == "server_released" for row in shutdown)
            assert all(process_gone(entry) for entry in native_processes)
            evidence["survivors_exited"] = {"exit_codes": exit_codes, "server_released": True}
            pending_retries = dict(initial_retries)
            completed = []
            while pending_retries:
                channel = wait(pending_retries, lambda: next(
                    (name for name, run in pending_retries.items() if (run / "native/ert-probe-holding").is_file()),
                    None), "retry checked the fresh copy after Initialize", 650, "retry")
                run = pending_retries.pop(channel)
                assert read_json(probe.lock)["run_id"] == read_json(probe.marker)["run_id"] == run.name
                assert not probe.sentinel.exists() and initialize_calls(run / "native") == 1
                for other, queued_run in pending_retries.items():
                    verify_queued(other, queued_run)
                    before = heartbeats(other)
                    owner_copy = copy_snapshot(probe)
                    wait((channel, other), lambda: heartbeats(other) > before,
                         "second retry still waiting behind the recovery owner", 30, "retry")
                    verify_queued(other, queued_run)
                    assert copy_snapshot(probe) == owner_copy
                    assert basecopy77._native_holds_lock(probe.lock)
                    assert basecopy77.open_in_1c(probe.copy) == "1SUSERS.DBF"
                    evidence["waiting"]["behind_recovery"] = {
                        "owner": channel, "waiter": other, "new_heartbeats": heartbeats(other) - before,
                        "owner_copy_preserved": True,
                    }
                    print(f"{channel} owns the fresh copy; {other} is still queued", flush=True)
                if probe.next_run and channel == "retry":
                    stop_waiter(channel, run)
                (run / "native/probe-release").touch()
                retry_reply = wait(channel, lambda: reply(channel, "retry"), "retry result", 900)["result"]
                assert not retry_reply["isError"] and retry_reply["structuredContent"]["exit_code"] == 0
                retry_stage = platform(read_json(run / "run.json"))
                retry_copy = retry_stage["base_copy"]
                stale_run_id = second.name if not completed else None
                assert retry_copy["previous_run_id"] == retry_copy["lock"]["stale_run_id"] == stale_run_id
                retry_labels = progress(channel, "retry")
                copy_wait = retry_copy.get("wait")
                if channel == "next":
                    assert copy_wait is None and waiting not in retry_labels
                    assert "run: " + START in retry_labels
                else:
                    assert copy_wait["acquired"] and copy_wait["elapsed_s"] >= 10
                    assert retry_labels.index(waiting) < retry_labels.index("run: " + PREPARE_COPY) < retry_labels.index("run: " + START)
                stale = retry_stage["open"]["stale_com_registrations"]
                assert len(stale) == (2 if stale_run_id else 0)
                for index, record in enumerate(stale):
                    assert record["run_id"] == stale_run_id and set(record["roots"]) == set(COM[index * 2:index * 2 + 2])
                    assert [{key: entry[key] for key in ("role", "pid", "creation_filetime")}
                             for entry in record["processes"]] == native_processes
                    assert all(entry["gone"] in ("absent", "exited") for entry in record["processes"])
                result = dict(verify_passed(run), stale_run_id=stale_run_id, copy_path=str(probe.copy),
                              fresh_copy_verified=True, copy_wait=copy_wait)
                completed.append(dict(result, channel=channel, stale_registrations=stale))
                if len(probe.retries) == 1:
                    evidence["retry"] = result
                    evidence["stale_registrations"] = stale
                else:
                    evidence["retries"] = completed
                print(f"{channel} initialized once, returned 42 and removed {len(stale)} stale COM registrations",
                      flush=True)
                if probe.next_run and channel == "retry":
                    assert not probe.copy.exists() and not probe.lock.exists() and com_snapshot() == [None] * len(COM)
                    start_server("next")
                    start_retry("next", probe.next_run)
                    pending_retries["next"] = probe.next_run
            assert verify_checkpoint(probe, first, second) == checkpoint
            assert not probe.copy.exists() and not probe.lock.exists() and com_snapshot() == [None] * len(COM)
        finally:
            for native in held:
                if (native / "ert-probe-holding").is_file():
                    (native / "probe-release").touch()
            for server in servers.values():
                if not server.stdin.closed:
                    server.stdin.close()
            if crash_started:
                for role in CONTROLLERS:
                    stop_owned(role, handles[role])
                if not waited_for_survivors:
                    await_survivors(handles)
            for channel, server in servers.items():
                channels[channel]["exit_code"] = server.wait(timeout=240)
                readers[channel].join(timeout=15)
    assert all(channels[channel]["exit_code"] == (
                   KILL_CODE if channel == "suite" or (channel == "retry-2" and probe.waiter_mode == "crash") else 0)
               and not reader.is_alive() for channel, reader in readers.items())
    if probe.next_run:
        assert bool(reply("retry-2", "retry")) == (probe.waiter_mode in ("timeout", "close"))


def recover_probe_state(probe, evidence):
    own_ids = {evidence["crashed_run_id"], *(run.name for run in probe.retries.values())}
    if probe.next_run:
        own_ids.add(probe.next_run.name)
    with registration_lock(timeout_ms=30000):
        for index, dll in ((0, "identity"), (2, "helper")):
            tree = read_tree(COM[index], VIEW)
            if not tree:
                continue
            record = json.loads(tree[COM[index]][OWNER_VALUE])
            assert record["run_id"] in own_ids and record["processes"]
            if not all(process_gone(entry) for entry in record["processes"]):
                raise RuntimeError(f"registration still has live processes: {COM[index]}")
            register_cleanup_helper(getattr(probe.stand, dll), {"run_id": str(uuid4())},
                                    identity=dll == "identity")()
    if probe.copy.exists() or probe.lock.exists():
        assert probe.copy.resolve() == probe.copy and probe.copy.parent == probe.out
        if probe.lock.exists():
            assert read_json(probe.lock)["run_id"] in own_ids
        marker_id = read_json(probe.marker)["run_id"] if probe.copy.exists() else None
        assert marker_id is None or marker_id in own_ids
        cleanup_id = str(uuid4())
        basecopy77.acquire(probe.copy, cleanup_id)
        try:
            if marker_id:
                assert basecopy77.remove(probe.copy, run_id=marker_id)["removed"]
        finally:
            assert basecopy77.release(probe.copy, cleanup_id)


def execute(probe):
    probe.out.mkdir(parents=True, exist_ok=False)
    source_before = basecopy77.listing(probe.source)
    titles_before = base_titles_fingerprint()
    com_before, processes_before = com_snapshot(), processes()
    evidence = {"copy_path": str(probe.copy), "stand": str(probe.stand.path), "project": str(probe.project.path)}
    try:
        if com_before != [None] * len(COM) or processes_before:
            raise RuntimeError("the native stand must be idle with no probe COM registrations")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\1C\1Cv7\7.7\Titles", 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE | VIEW) as titles:
            key, label = str(probe.copy) + "\\", f"harness77 task {probe.task} {probe.retries['retry'].name}"
            try:
                winreg.QueryValueEx(titles, key)
            except FileNotFoundError:
                winreg.SetValueEx(titles, key, 0, winreg.REG_SZ, label)
            else:
                raise RuntimeError("the probe copy path is already registered")
            try:
                verify(probe, evidence)
            except Exception:
                if evidence.get("crashed_run_id"):
                    try:
                        recover_probe_state(probe, evidence)
                        evidence["manual_recovery_after_probe_failure"] = True
                    except Exception as error:
                        evidence["manual_recovery_error"] = f"{type(error).__name__}: {error}"
                raise
            finally:
                assert winreg.QueryValueEx(titles, key) == (label, winreg.REG_SZ)
                winreg.DeleteValue(titles, key)
    except Exception as error:
        evidence["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if not probe.copy.exists() and not probe.lock.exists():
            probe.guard.unlink(missing_ok=True)
        evidence["cleanup"] = {
            "copy_removed": not probe.copy.exists(), "lock_removed": not probe.lock.exists(),
            "guard_removed": not probe.guard.exists(), "source_unchanged": basecopy77.listing(probe.source) == source_before,
            "base_list_unchanged": base_titles_fingerprint() == titles_before,
            "com_restored": com_snapshot() == com_before, "processes_restored": processes() == processes_before,
        }
        evidence["status"] = "passed" if "error" not in evidence and all(evidence["cleanup"].values()) else "failed"
        atomic_json(probe.out / "verified.json", evidence)
    if evidence["status"] != "passed":
        raise RuntimeError(f"probe cleanup failed: {evidence['cleanup']}")
    print(probe.out / "verified.json", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stand", type=Path, required=True, help="native stand TOML")
    parser.add_argument("--project", type=Path, required=True, help="TOML with a configuration and one execute test")
    parser.add_argument("--output", type=Path, required=True, help="new directory for the copy and evidence")
    parser.add_argument("--retries", type=int, choices=(1, 2), default=1,
                        help="number of independent MCP retry requests on the same copy")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--cancel-waiter", dest="waiter_mode", action="store_const", const="cancel",
                        help="cancel the second retry while the first holds the recovered copy, then run again")
    modes.add_argument("--timeout-waiter", dest="waiter_mode", action="store_const", const="timeout",
                       help="expire the second retry's open budget behind the recovered copy owner")
    modes.add_argument("--close-waiter", dest="waiter_mode", action="store_const", const="close",
                       help="close the waiting MCP server's stdin behind the recovered copy owner")
    modes.add_argument("--crash-waiter", dest="waiter_mode", action="store_const", const="crash",
                       help="terminate the waiting MCP and CLI behind the recovered copy owner")
    args = parser.parse_args(argv)
    if args.waiter_mode and args.retries != 2:
        parser.error("waiter modes require --retries 2")
    if os.name != "nt" or not __debug__:
        parser.error("the recovery probe requires Windows and enabled Python assertions")
    try:
        stand, project = load_stand(args.stand), load_project(args.project)
        probe = Probe(stand, project, args.output.resolve(), args.retries, args.waiter_mode)
        if (stand.backend != "native" or not probe.source.is_dir()
                or not all(path and path.is_file() for path in (stand.exe, stand.cdb, stand.helper, stand.identity))):
            raise ValueError("a native stand with a source base, 1C, x86 CDB, helper and identity DLLs is required")
        if (not project.configuration or not project.configuration.is_dir() or project.keep_copy or project.visual
                or len(project.tests) != 1 or project.commands() != ["execute"]
                or project.tests[0]["expect"] != "passed" or project.tests[0].get("expect_value", "42") != "42"):
            raise ValueError("use a project with a configuration, no visual checks, and one execute test expecting 42")
        output = str(probe.out)
        if (probe.out.exists() or probe.out.is_relative_to(probe.source) or probe.source.is_relative_to(probe.out)
                or not output.isascii() or any(char in output for char in '"; \r\n')):
            raise ValueError("output must be a new ASCII path without spaces or debugger separators, outside the source base")
        resolve_deadlines(project, stand, DEADLINES)
    except (ConfigError, OSError, ValueError) as error:
        parser.error(str(error))
    execute(probe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
