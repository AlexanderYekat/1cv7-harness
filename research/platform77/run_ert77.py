"""One bounded synthetic ERT probe on a private desktop, under x86 CDB."""
import argparse
import json
from pathlib import Path

from ert_probe77 import CASES, prepare, read_results
from run_shutdown77 import ROOT, preflight
from shutdown77 import MODE, assess, atomic_json, sha256

from concurrent77 import IDENTITY_SHA


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    for name in ("base", "exe", "cdb", "com-cleanup-dll", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--user", required=True)
    parser.add_argument("--case", choices=CASES, default="ok")
    parser.add_argument("--identity-dll", type=Path, help="enable verified concurrent sessions with the pinned client inspector")
    parser.add_argument("--activation-only", action="store_true", help="verify proxy ownership and release it without opening any database")
    args = parser.parse_args(argv)
    report = {"schema_version": 1, "scope": "synthetic ERT research", "shutdown_mode": MODE,
              "fault": "none", "case": args.case, "status": "blocked", "ert_operation_timeout_seconds": 30}
    gate = ROOT / ".artifacts/platform77/active-session.json"
    out = None
    owns_gate = False
    try:
        identity = args.identity_dll.resolve(strict=True) if args.identity_dll else None
        if args.activation_only and identity is None:
            raise ValueError("activation-only requires identity-dll")
        if identity is not None and sha256(identity) != IDENTITY_SHA:
            raise ValueError("unqualified proxy inspector")
        report["activation_only"] = args.activation_only
        base, exe, cdb, helper = [p.resolve(strict=True) for p in (args.base, args.exe, args.cdb, args.com_cleanup_dll)]
        destination = args.output.resolve()
        preflight(base, exe, cdb, helper, destination)
        if any(c in args.user for c in '\"\r\n'):
            raise ValueError("invalid user name")
        from session77 import run_session
        from win32_session77 import processes
        from desktop77 import PrivateDesktop
        existing = processes()
        if existing and identity is None:
            report["processes_before"] = existing
            raise RuntimeError("existing 1C process; native ERT was not started")
        gate.parent.mkdir(parents=True, exist_ok=True)
        with gate.open("x", encoding="utf-8") as stream:
            owns_gate = True
            stream.write(json.dumps({"output": str(destination), "scope": "synthetic ERT"}))
        destination.mkdir(parents=True, exist_ok=False)
        out = destination
        manifest, shutdown_manifest = prepare(out, base / "ExtForms/rp14q1.GRP/FIO.ERT", args.case, concurrent=identity is not None)
        report["run_id"] = manifest["run_id"]
        with PrivateDesktop() as desktop:
            report = run_session(base, exe, cdb, helper, args.user, out, report, desktop=desktop.name, identity_dll=identity)
        report["desktop_closed"] = True
        if args.activation_only:
            from concurrent77 import concurrency_issues
            issues = concurrency_issues(report)
            for key in ("error", "cleanup_errors", "forced_cleanup", "first_chance_av_observed", "av_dump_saved"):
                if report.get(key):
                    issues.append(key + ": " + str(report[key]))
            for key in ("server_exit_code", "helper_exit_code", "debugger_exit_code"):
                if report.get(key) != 0:
                    issues.append(key + " must be zero")
            if not report.get("cleanup_verified"):
                issues.append("cleanup not verified")
            report["activation_issues"] = issues
            report["status"] = "blocked" if issues else "passed"
        else:
            report["shutdown_assessment"] = assess(out, shutdown_manifest, report)
            report["shutdown_assessment"]["scope"] = "coordinated shutdown mechanics after the synthetic ERT probe"
            report["ert"] = read_results(out, manifest, report, report["shutdown_assessment"])
            report["status"] = report["ert"]["status"]
        atomic_json(out / "run.json", report)
        if report.get("cleanup_verified") and report["desktop_closed"]:
            gate.unlink()
            owns_gate = False
        print(json.dumps({k: report.get(k) for k in ("status", "case", "run_id", "elapsed_seconds", "error", "timeout_phase", "cleanup_verified", "proxy_identity", "baseline_preserved", "activation_issues", "shutdown_assessment", "ert")}, ensure_ascii=False, indent=2))
        return {"passed": 0, "failed": 1, "blocked": 2}[report["status"]]
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        report["active_gate_retained"] = owns_gate
        if out is not None:
            atomic_json(out / "run.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
