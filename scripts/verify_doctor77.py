"""Task 089: installed doctor controls, unchanged stand, then task-088 regression.

Run with the clean kit's venv Python. Only this verifier creates its new output
and control profiles; every doctor invocation remains observational.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import harness77
from harness77 import basecopy77
from harness77.config77 import load_stand
from harness77.doctor_windows77 import COM_KEYS, TITLES


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(k) + " = " + table(v) for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(map(table, value)) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def registry_tree(root):
    import winreg
    def read(key):
        children, values, _ = winreg.QueryInfoKey(key)
        result = {"values": sorted([list(winreg.EnumValue(key, i)) for i in range(values)])}
        result["children"] = {}
        for i in range(children):
            name = winreg.EnumKey(key, i)
            with winreg.OpenKey(key, name, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as child:
                result["children"][name] = read(child)
        return result
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            return read(key)
    except FileNotFoundError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    kit, output = args.kit.resolve(strict=True), args.output.resolve()
    if os.name != "nt" or sys.prefix == sys.base_prefix or os.environ.get("PYTHONPATH") or os.environ.get("PYTHONHOME"):
        parser.error("requires clean Windows venv without PYTHONPATH/PYTHONHOME")
    if not Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        parser.error("harness77 must be installed in this venv")
    output.mkdir(parents=True, exist_ok=False)
    controls = output / "controls"
    controls.mkdir()
    working = output / "working"
    working.mkdir()
    stand_path = kit / "stand.toml"
    stand = load_stand(stand_path)
    manifest = json.loads((kit / "kit.json").read_text(encoding="utf-8"))
    lock = basecopy77.lock_path(stand.copy_path)
    guard = lock.with_name(lock.name + ".guard")
    from harness77.doctor_windows77 import WindowsInspector
    inspector = WindowsInspector()

    def snapshot():
        return {"source": basecopy77.listing(stand.base),
                "base_hashes": {n: digest(stand.base / n) for n in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll")},
                "registry": {key: registry_tree(key) for key in (TITLES, *COM_KEYS)},
                "processes": inspector.processes(),
                "guard": digest(guard) if guard.exists() else None,
                "copy_exists": stand.copy_path.exists(), "lock_exists": lock.exists(),
                "kit": {n: digest(kit / n) for n in manifest["files"]}}

    before = snapshot()
    result = {"status": "running", "environment": {"python": sys.executable, "module": harness77.__file__,
              "cwd": str(working), "pythonpath": os.environ.get("PYTHONPATH")}, "controls": []}
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")

    def doctor(name, profile, expected=0, required=None):
        command = [sys.executable, "-B", "-m", "harness77", "doctor", "--project", str(kit / "success/project.toml"),
                   "--stand", str(profile), "--output-root", str(output / "future-results"), "--format", "json"]
        execution = subprocess.run(command, cwd=working, env=env, capture_output=True, timeout=60)
        (output / (name + ".json")).write_bytes(execution.stdout)
        (output / (name + ".stderr.log")).write_bytes(execution.stderr)
        report = json.loads(execution.stdout)
        assert execution.returncode == expected == report["exit_code"], (name, report)
        assert report["platform_checked"] is False and report["launch_performed"] is False
        if required:
            id_, code = required
            assert any(c["id"] == id_ and c["code"] == code and c["status"] == "blocked" for c in report["checks"]), report
        assert snapshot() == before, name + ": stand or kit changed during doctor"
        assert not (output / "future-results").exists()
        result["controls"].append({"name": name, "exit_code": execution.returncode,
                                   "report_sha256": digest(output / (name + ".json")), "unchanged": True})

    def variant(name, change):
        data = tomllib.loads(stand_path.read_text(encoding="utf-8"))
        data["stand"]["launcher"] = str(stand.extra["launcher"])
        for role in ("exe", "cdb", "helper", "identity"):
            data["stand"]["paths"][role] = getattr(stand, role).as_posix()
        change(data["stand"])
        path = controls / (name + ".toml")
        path.write_text("schema_version = 1\nstand = " + table(data["stand"]) + "\n", encoding="utf-8")
        return path

    try:
        assert not before["processes"] and not before["copy_exists"] and not before["lock_exists"], "stand must be idle"
        doctor("ready", stand_path)
        path = variant("missing-dll", lambda s: s["paths"].update(helper=str(controls / "missing.dll")))
        doctor("missing-dll", path, 2, ("stand.helper", "file_missing"))
        path = variant("wrong-hash", lambda s: s["pinned"].update({"1Cv7.MD": "0" * 64}))
        doctor("wrong-hash", path, 2, ("pinned.1Cv7.MD", "hash_mismatch"))
        path = variant("unregistered-copy", lambda s: s["base"].update(copy_path=str(output / "unregistered-copy")))
        doctor("unregistered-copy", path, 2, ("copy.registration", "copy_unregistered"))
        path = variant("relative-launcher", lambda s: s.update(launcher="missing/launcher.py"))
        doctor("relative-launcher", path, 2, ("stand.launcher", "file_missing"))
        path = variant("overlap", lambda s: s["base"].update(copy_path=str(stand.base / "copy")))
        doctor("overlap", path, 2, ("paths.overlap", "paths_overlap"))
        # Fake lock has its own path, so the registered production copy is never touched.
        busy = output / "busy-copy"
        busy_lock = basecopy77.lock_path(busy)
        busy_lock.write_text("sentinel", encoding="utf-8")
        path = variant("lock-present", lambda s: s["base"].update(copy_path=str(busy)))
        doctor("lock-present", path, 2, ("copy.state", "copy_requires_inspection"))
        assert busy_lock.read_text(encoding="utf-8") == "sentinel"
        execution = subprocess.run([sys.executable, "-B", str(kit / "run.py"), "--output", str(output / "application")],
                                   cwd=working, env=env, capture_output=True, timeout=1500)
        (output / "application.log").write_bytes(execution.stdout + execution.stderr)
        assert execution.returncode == 0, "task-088 regression failed; see application.log"
        application = json.loads((output / "application/verified.json").read_text(encoding="utf-8"))
        assert application["status"] == "passed" and len(application["runs"]) == 4
        result["application"] = {"verified_sha256": digest(output / "application/verified.json"), "runs": 4}
        doctor("ready-after-application", stand_path)
        result["status"] = "passed"
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        after = snapshot()
        result["unchanged"] = {key: value == after[key] for key, value in before.items()}
        if not all(result["unchanged"].values()):
            result["status"] = "failed"
        (output / "verified.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output / "verified.json")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
