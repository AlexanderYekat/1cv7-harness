"""Pinned shutdown policy and evidence contract; importable without Windows."""
import hashlib
import json
from pathlib import Path

MODE = "coordinated-icpp-v1"
PINNED = {
    "exe": "562790a34f8491782886e91e36a0800b8fd359afe91bfcf6f575ee4cb181f9bf",
    "1Cv7.MD": "931b26eb2e388ba3000196ab024351e65cb324e02e885dc4cef5be68059ecfa1",
    "1Cv7.DD": "618e7da54316d74f260e2d02931cc377032ab9f94be577041cd02890e7b82cbd",
    "1CPP.dll": "d690756abc7ecb839f258a5b1abcbabd622d3f3d85410141b00493edcf7c2bfb",
    "FormEx.dll": "32fa9996a24bd6075d5010051550671af5f7cfd8ba98e990ac67a1ed1585f798",
    "helper": "22874e18fec26b06425b4c937131ace99dfc60cca2594fae4620e73f6714a9eb",
}
STEPS = (
    ("modules_released", "ok"), ("installer_compiled", "1"),
    ("installer_executed", "1"), ("global_installed", "positive"),
    ("installer_released", "ok"), ("helper_pid", "pid"),
    ("loaded_initially", "1"), ("reference_held", "pid"),
    ("addin_unloaded", "1"), ("loaded_before_flush", "1"),
    ("com_flushed", "pid"), ("loaded_after_flush", "0"),
    ("reference_consumed", "0"), ("loaded_after_release", "0"),
    ("answer", "42"), ("server_released", "ok"),
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path, value):
    """Serialize fully before touching the final report."""
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(data, encoding="utf-8")
    temporary.replace(path)


def read_events(out):
    return [json.loads(line) for line in (out / "shutdown-events.jsonl").read_text(
        encoding="utf-16").splitlines()]


class Deadline:
    """External clock policy, with a shutdown deadline that cannot be renewed."""
    def __init__(self, started, total=145, shutdown=10):
        self.total_at = started + total
        self.shutdown_limit = shutdown
        self.shutdown_at = None

    def observe_shutdown(self, now):
        if self.shutdown_at is None:
            self.shutdown_at = now + self.shutdown_limit

    def expired(self, now):
        if self.shutdown_at is not None and now >= self.shutdown_at:
            return "shutdown"
        if now >= self.total_at:
            return "session"
        return None


def prepare_shutdown(out, run_id, fault="none"):
    """Only the fixed policy is generated; no caller supplied native code."""
    if fault not in ("none", "com-error", "release-timeout"):
        raise ValueError("unknown fault")
    from module_suite77 import vb_assignment
    functions = []
    for name, method in (("PID", "ProcessId"), ("Hold", "HoldIcpp"),
                         ("Flush", "FlushNow"), ("Loaded", "IcppLoaded"),
                         ("Release", "ReleaseIcpp")):
        functions.append(f'''Функция H77{name}() Экспорт
    Очистка = СоздатьОбъект("Harness77Diagnostic.ComCleanup");
    Возврат Очистка.{method}();
КонецФункции''')
    functions.append('''Функция H77Unload() Экспорт
    Сервис = СоздатьОбъект("Сервис");
    Возврат Сервис.UnLoadAddIn("1cpp.dll");
КонецФункции''')
    global_source = "\n".join(functions)
    literal = ' + РазделительСтрок + '.join('"' + line.replace('"', '""') + '"'
                                            for line in global_source.splitlines())
    installer = ('Функция H77Install() Экспорт\n    Сервис = СоздатьОбъект("Сервис");\n'
                 '    Возврат Сервис.AddGlobalModule(' + literal + ');\nКонецФункции')
    source_path = out / "shutdown-installer.1s"
    source_path.write_text(installer + "\n", encoding="utf-8")
    template = Path(__file__).with_suffix(".vbs").read_text(encoding="utf-8")
    fragment = template.replace("__INSTALLER__", vb_assignment("shutdownSource", installer))
    fragment = fragment.replace("__FAULT__", fault)
    manifest = {"mode": MODE, "run_id": run_id, "fault": fault,
                "sources": {source_path.name: sha256(source_path)}}
    return fragment, manifest


def assess(out, manifest, lifecycle, pinned=None):
    """Do not infer success from process disappearance or a truthy flag.

    pinned: the expected hashes when not PINNED — the caller's, never the lifecycle's own
    (a run's copy of the base with the configuration it built, task 021)."""
    expected = pinned or PINNED
    issues = []
    result = {"mode": MODE, "status": "blocked", "issues": issues,
              "scope": "fixed synthetic module suite on pinned base-for-test; no ERT acceptance"}
    if manifest.get("mode") != MODE or lifecycle.get("shutdown_mode") != MODE:
        issues.append("shutdown mode mismatch")
    if manifest.get("run_id") != lifecycle.get("run_id"):
        issues.append("lifecycle run_id mismatch")
    if manifest.get("fault") != "none" or lifecycle.get("fault") != "none":
        issues.append("fault injection is not an acceptance run")
    for name, digest in manifest.get("sources", {}).items():
        try:
            if sha256(out / name) != digest:
                issues.append("shutdown source changed: " + name)
        except OSError:
            issues.append("shutdown source missing: " + name)
    if set(manifest.get("sources", {})) != {"shutdown-installer.1s", "client.vbs"}:
        issues.append("incomplete shutdown source manifest")
    for key in ("error", "registration_cleanup_error", "cleanup_errors", "timeout_phase"):
        if lifecycle.get(key):
            issues.append(key + ": " + str(lifecycle[key]))
    for key in ("forced_cleanup", "first_chance_av_observed", "av_dump_saved",
                "diagnostic_execution_modified"):
        if lifecycle.get(key) is not False:
            issues.append(key + " must be false")
    for key in ("server_exit_code", "helper_exit_code", "debugger_exit_code"):
        if type(lifecycle.get(key)) is not int or lifecycle[key] != 0:
            issues.append(key + " must be zero")
    if lifecycle.get("concurrent_mode"):
        from concurrent77 import concurrency_issues
        issues.extend(concurrency_issues(lifecycle))
    else:
        for key in ("processes_before", "processes_after"):
            if lifecycle.get(key) != []:
                issues.append(key + " must be empty")
    if lifecycle.get("hashes_before") != expected or lifecycle.get("hashes_after") != expected:
        issues.append("pinned binary/configuration hashes do not match")
    registration = lifecycle.get("temporary_com_registration", {})
    if registration.get("removed") is not True or registration.get("sha256") != PINNED["helper"]:
        issues.append("temporary registration not verified removed")
    server = lifecycle.get("server", {})
    if (server.get("ownership_verified") is not True or not server.get("creation_filetime")
            or type(server.get("pid")) is not int or server.get("pid", 0) <= 0
            or server.get("parent_pid") != lifecycle.get("debugger_pid")):
        issues.append("server ownership not verified")
    if lifecycle.get("debugger_ready") is not True or lifecycle.get("debugger_stops_at_first_chance_av") is not True:
        issues.append("debugger guard not verified")
    if lifecycle.get("shutdown_started_observed") is not True:
        issues.append("shutdown deadline was not armed")
    try:
        events = read_events(out)
    except (OSError, UnicodeError, ValueError) as error:
        issues.append("missing or malformed shutdown events: " + str(error))
        events = []
    if len(events) != len(STEPS):
        issues.append("shutdown event count mismatch")
    for event, (name, expected) in zip(events, STEPS):
        if not isinstance(event, dict):
            issues.append("invalid shutdown event")
            continue
        if event.get("run_id") != manifest.get("run_id") or event.get("name") != name:
            issues.append("foreign, duplicate or out-of-order shutdown event: " + name)
        value = event.get("value")
        valid = (isinstance(value, str) and value.isdecimal() and int(value) > 0
                 if expected == "positive" else value == str(server.get("pid"))
                 if expected == "pid" else value == expected)
        if not valid:
            issues.append("shutdown result mismatch: " + name)
    result["status"] = "blocked" if issues else "passed"
    return result
