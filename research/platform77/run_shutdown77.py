"""Qualify a fixed module suite with the pinned coordinated-icpp-v1 policy.

No arbitrary ERT/native source input; no unguarded launch or debugger patching.
Exit codes: 0 this bounded contract passed, 1 test expectations failed, 2 blocked.
"""
import argparse
import json
from pathlib import Path

from module_suite77 import prepare_client, read_results
from shutdown77 import MODE, PINNED, assess, atomic_json, prepare_shutdown, sha256

ROOT = Path(__file__).resolve().parents[2]


def preflight(base, exe, cdb, helper, out):
    if base != (ROOT / ".local/bases/base-for-test").resolve(strict=True):
        raise ValueError("only the existing base-for-test is qualified")
    if out.is_relative_to(base) or base.is_relative_to(out):
        raise ValueError("output and database trees must not overlap")
    # CDB receives a generated command file; avoid command separators/quoting.
    if any(c in str(out) for c in '\"; \r\n') or not str(out).isascii():
        raise ValueError("output must be ASCII without spaces or debugger separators")
    if out.exists():
        raise ValueError("output must be a fresh directory")
    paths = {"exe": exe, "helper": helper,
             **{name: base / name for name in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll")}}
    for name, path in paths.items():
        if sha256(path) != PINNED[name]:
            raise ValueError("unqualified binary/configuration: " + name)
    data = cdb.read_bytes()
    pe = int.from_bytes(data[0x3c:0x40], "little")
    if data[:2] != b"MZ" or data[pe:pe + 6] != b"PE\0\0\x4c\x01":
        raise ValueError("x86 CDB is required")


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    for name in ("base", "exe", "cdb", "com-cleanup-dll", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--fault", choices=("none", "com-error", "release-timeout"), default="none")
    args = parser.parse_args(argv)
    gate = ROOT / ".artifacts/platform77/active-session.json"
    owns_gate = False
    report = {"schema_version": 1, "shutdown_mode": MODE, "fault": args.fault, "client_log_profile": "held-streams-v2",
              "status": "blocked", "cleanup_verified": False,
              "scope": "fixed synthetic native modules; ERT/P00-P08 not accepted"}
    out = None
    try:
        if not 1 <= args.iterations <= 10000:
            raise ValueError("iterations must be between 1 and 10000")
        if any(c in args.user for c in '\"\r\n'):
            raise ValueError("user name contains command delimiters")
        base, exe, cdb, helper = [p.resolve(strict=True) for p in (
            args.base, args.exe, args.cdb, args.com_cleanup_dll)]
        destination = args.output.resolve()
        preflight(base, exe, cdb, helper, destination)
        from session77 import run_session
        from win32_session77 import processes
        if processes():
            raise RuntimeError("existing 1C process; refusing to start")
        gate.parent.mkdir(parents=True, exist_ok=True)
        # Persistent exclusion: interrupted/unclean attempts require inspection.
        with gate.open("x", encoding="utf-8") as stream:
            owns_gate = True
            stream.write(json.dumps({"output": str(destination), "mode": MODE}) + "\n")
        destination.mkdir(parents=True, exist_ok=False)
        out = destination
        # The UUID comes from the suite; regenerate only placeholders, never UUIDs.
        client, manifest = prepare_client(out, args.iterations,
                                           "__SHUTDOWN_POLICY__", 'ShutdownEvent "server_released", "ok"')
        fragment, shutdown_manifest = prepare_shutdown(out, manifest["run_id"], args.fault)
        client = client.replace("__SHUTDOWN_POLICY__", fragment)
        (out / "client.vbs").write_text(client, encoding="utf-16")
        shutdown_manifest["sources"]["client.vbs"] = sha256(out / "client.vbs")
        atomic_json(out / "shutdown-manifest.json", shutdown_manifest)
        report["run_id"] = manifest["run_id"]
        report["paths"] = {"base": str(base), "exe": str(exe), "cdb": str(cdb), "helper": str(helper)}
        report = run_session(base, exe, cdb, helper, args.user, out, report)
        report["shutdown_assessment"] = assess(out, shutdown_manifest, report)
        report["normal_shutdown_observed"] = report["shutdown_assessment"]["status"] == "passed"
        report["module_suite"] = read_results(out, manifest, report, shutdown_manifest)
        report["status"] = report["module_suite"]["status"]
        atomic_json(out / "suite-report.json", report["module_suite"])
        atomic_json(out / "run.json", report)
        if report["cleanup_verified"]:
            gate.unlink()
            owns_gate = False
        print(json.dumps({key: report.get(key) for key in (
            "status", "shutdown_mode", "run_id", "fault", "elapsed_seconds", "error",
            "timeout_phase", "forced_cleanup", "cleanup_verified", "shutdown_assessment")},
            ensure_ascii=False, indent=2))
        return {"passed": 0, "failed": 1, "blocked": 2}[report["status"]]
    except Exception as error:
        report["status"] = "blocked"
        report["error"] = f"{type(error).__name__}: {error}"
        # Preserve the gate on controller/publication failure. Do not infer that
        # missing reports mean no native process or registration was created.
        report["active_gate_retained"] = owns_gate
        if out is not None:
            try:
                atomic_json(out / "run.json", report)
            except (OSError, ValueError) as write_error:
                report["report_write_error"] = str(write_error)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
