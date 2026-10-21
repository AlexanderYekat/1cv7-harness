"""Native probes of task 015: the launcher after its process tree is killed and under load.

    python -B research/launcher/launcher_probes77.py <case> --output .artifacts/launcher/<fresh dir>
        [--profiles .local/stage14-native]

Cases (docs/tasks/015-launcher-robustness.md): L0 control run; L4 keys of the older
layout without an owner record; L5 a 1-second open deadline; L1 kill the `harness77 run`
tree during the calculation; L2 the next run after L1; L3 a second run while a long one
runs; L6 a run under processor load; R1 the research run_ert77.py with its 20/30 s;
P2 (docs/tasks/017-poll-round.md) a run under disk write load.
`gate-take`/`gate-release` hold the research active-session gate around L0-L6 (R1 takes it itself).

Each case writes <output>/<case>.json: what was run, the exit code, the run report's
essentials and snapshots of the temporary COM keys (with the decoded owner record),
the 1C/CDB/cscript processes and the trace on the base, before and after.
"""

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import winreg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "platform77"))
import stage4_launcher77  # noqa: E402
from win32_session77 import OWNER_VALUE, ProcessEntry, kernel, process_identity, read_tree  # noqa: E402

ROOTS = [r"Software\Classes\Harness77Diagnostic.ComCleanup",
         r"Software\Classes\CLSID\{16B8A521-07E4-46D1-A8E7-197BD1CE4477}",
         r"Software\Classes\Harness77Diagnostic.ProxyIdentity",
         r"Software\Classes\CLSID\{7E477C71-018E-4C27-9E38-2D5DDA9F6A07}"]
VIEW = winreg.KEY_WOW64_32KEY
WATCHED = ("1cv7", "cdb.exe", "cscript.exe")


def keys():
    """The four temporary roots as found, owner records decoded."""
    found = {}
    for root in ROOTS:
        tree = read_tree(root, VIEW)
        if tree is None:
            continue
        for path, values in tree.items():
            values = dict(values)
            if OWNER_VALUE in values:
                values[OWNER_VALUE] = json.loads(values[OWNER_VALUE])
            found[path] = values
    return found


def processes():
    """1C, CDB and cscript processes with parent and creation time."""
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    result = []
    try:
        entry = ProcessEntry()
        entry.dwSize = C.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, C.byref(entry))
        while found:
            name = entry.szExeFile.lower()
            if name.startswith(WATCHED[0]) and name.endswith(".exe") or name in WATCHED[1:]:
                row = {"pid": entry.th32ProcessID, "parent_pid": entry.th32ParentProcessID, "name": name}
                handle = kernel.OpenProcess(0x1000, False, entry.th32ProcessID)
                if handle:
                    try:
                        row.update(process_identity(handle))
                    except OSError:
                        pass
                    kernel.CloseHandle(handle)
                result.append(row)
            found = kernel.Process32NextW(snapshot, C.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return sorted(result, key=lambda p: p["pid"])


def state(base):
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "keys": keys(), "processes": processes(),
            "base_trace": stage4_launcher77.base_trace(base)}


class Probe:
    def __init__(self, args):
        self.args = args
        self.out = args.output.resolve()
        self.out.mkdir(parents=True, exist_ok=False)
        self.runs = self.out / "runs"
        profiles = args.profiles.resolve()
        self.stand = profiles / "stand.toml"
        self.profiles = profiles
        import tomllib
        self.base = Path(tomllib.loads(self.stand.read_text(encoding="utf-8"))["stand"]["base"]["path"])

    def command(self, profile, run_id, *extra):
        return [sys.executable, "-B", "-m", "harness77", "run", "--project", str(self.profiles / profile),
                "--stand", str(self.stand), "--run-id", run_id, "--output-root", str(self.runs), *extra]

    def essentials(self, run_id):
        path = self.runs / run_id / "run.json"
        if not path.exists():
            return {"run_json": False}
        report = json.loads(path.read_text(encoding="utf-8"))
        stage = next((s for s in report.get("stages", []) if s.get("stage") == "platform_check"), {})
        tests = next((s for s in report.get("stages", []) if s.get("stage") == "tests"), {})
        platform = json.loads((self.runs / run_id / "platform-result.json").read_text(encoding="utf-8")) \
            if (self.runs / run_id / "platform-result.json").exists() else {}
        return {"run_json": True, "status": report.get("status"), "reason": report.get("reason"),
                "timeout_phase": report.get("timeout_phase"), "cancelled": report.get("cancelled"),
                "platform_checked": report.get("platform_checked"), "shutdown": report.get("shutdown"),
                "platform_reason": platform.get("reason"), "native_timeout_phase": platform.get("native_timeout_phase"),
                "open": stage.get("open"), "tests_status": tests.get("status"),
                "values": [t.get("value") for t in tests.get("tests") or []]}

    def run(self, profile, *extra, env=None):
        run_id = str(uuid.uuid4())
        before = state(self.base)
        started = time.monotonic()
        done = subprocess.run(self.command(profile, run_id, *extra), capture_output=True, env=env)
        return {"run_id": run_id, "profile": profile, "extra": list(extra), "exit_code": done.returncode,
                "duration_s": round(time.monotonic() - started, 1),
                "stdout_tail": done.stdout.decode("utf-8", "replace")[-2000:],
                "stderr_tail": done.stderr.decode("utf-8", "replace")[-2000:],
                "report": self.essentials(run_id), "before": before, "after": state(self.base)}

    def wait_marker(self, run_id, name, limit_s, process):
        marker = self.runs / run_id / "native" / name
        until = time.monotonic() + limit_s
        while time.monotonic() < until and process.poll() is None:
            if marker.exists():
                return round(limit_s - (until - time.monotonic()), 1)
            time.sleep(0.2)
        return None

    def save(self, case, record):
        (self.out / (case + ".json")).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
        print(json.dumps({k: record.get(k) for k in ("case", "exit_code", "report")}, ensure_ascii=False,
                         indent=2)[:4000])

    def L0(self):
        return self.run("project-control.toml")

    def L4(self):
        # The older launcher's layout exactly, without the owner record.
        layout = [(ROOTS[2], "Harness77 diagnostic COM cleanup", {}),
                  (ROOTS[2] + r"\CLSID", "{7E477C71-018E-4C27-9E38-2D5DDA9F6A07}", {}),
                  (ROOTS[3], "Harness77 diagnostic COM cleanup", {}),
                  (ROOTS[3] + r"\InprocServer32",
                   str(ROOT / ".artifacts/platform77/proxy-challenge-build-20261011/proxy_identity77.dll"),
                   {"ThreadingModel": "Apartment"})]
        if keys():
            raise SystemExit("temporary keys exist before L4; not touching them")
        for path, value, extra in layout:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE | VIEW) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
                for name, data in extra.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, data)
        planted = keys()
        record = self.run("project-control.toml")
        record["planted"] = planted
        record["unchanged"] = keys() == planted
        # Remove only what was planted, after checking the values.
        if record["unchanged"]:
            for path, value, _ in reversed(layout):
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, VIEW, 0)
        record["removed_by_probe"] = keys() == {}
        return record

    def L5(self):
        return self.run("project-control.toml", "--open-timeout-s", "1")

    def L1(self):
        run_id = str(uuid.uuid4())
        before = state(self.base)
        process = subprocess.Popen(self.command("project-long.toml", run_id), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        record = {"run_id": run_id, "profile": "project-long.toml", "pid": process.pid, "before": before}
        record["execute_started_after_s"] = self.wait_marker(run_id, "ert-execute-started", 600, process)
        record["during"] = state(self.base)
        time.sleep(3)
        kill = subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
        record["taskkill"] = {"exit_code": kill.returncode,
                              "output": kill.stdout.decode("cp866", "replace")[-1500:]}
        record["exit_code"] = process.wait(timeout=30)
        time.sleep(5)
        record["after"] = state(self.base)
        record["report"] = self.essentials(run_id)
        return record

    def L2(self):
        return self.run("project-control-reindex.toml")

    def L3(self):
        run_a = str(uuid.uuid4())
        record = {"before": state(self.base), "a": {"run_id": run_a, "profile": "project-long.toml"}}
        process = subprocess.Popen(self.command("project-long.toml", run_a), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        record["a"]["execute_started_after_s"] = self.wait_marker(run_a, "ert-execute-started", 600, process)
        keys_a = keys()
        record["b"] = self.run("project-control.toml")
        record["a_keys_during_b"] = keys_a
        record["a_keys_unchanged_by_b"] = keys() == keys_a
        record["a"]["exit_code"] = process.wait(timeout=900)
        record["a"]["report"] = self.essentials(run_a)
        record["after"] = state(self.base)
        return record

    def L6(self):
        count = (os.cpu_count() or 2) * 2
        busy = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(count)]
        try:
            time.sleep(5)
            record = self.run("project-control.toml", *self.args.run_args.split())
        finally:
            for process in busy:
                process.kill()
        record["busy_processes"] = count
        return record

    def P2(self):
        """Task 017: a run while 4 processes keep writing 64 MB files with fsync (disk, antivirus)."""
        load = self.out / "io-load"
        load.mkdir()
        writer = ("import os, sys\n"
                  "path, block, n = sys.argv[1], os.urandom(1 << 20), 0\n"
                  "while True:\n"
                  "    with open(path, 'wb') as f:\n"
                  "        for _ in range(64):\n"
                  "            f.write(block)\n"
                  "        f.flush(); os.fsync(f.fileno())\n"
                  "    n += 1\n"
                  "    open(path + '.count', 'w').write(str(n))\n")
        writers = [subprocess.Popen([sys.executable, "-c", writer, str(load / f"w{i}.bin")]) for i in range(4)]
        try:
            time.sleep(5)
            record = self.run("project-control.toml", *self.args.run_args.split())
        finally:
            for process in writers:
                process.kill()
                process.wait()
        counts = [int(p.read_text()) for p in load.glob("*.count")]
        record["io_writers"] = {"count": len(writers), "files_of_64_mb_written": sum(counts)}
        for path in load.iterdir():
            path.unlink()
        load.rmdir()
        return record

    def R1(self):
        output = self.out / "r1"
        before = state(self.base)
        stand = self.stand.read_text(encoding="utf-8")
        import tomllib
        paths = tomllib.loads(stand)["stand"]["paths"]
        command = [sys.executable, "-B", str(ROOT / "research/platform77/run_ert77.py"), "--base", str(self.base),
                   "--user", "ВВВ", "--output", str(output), "--exe", paths["exe"], "--cdb", paths["cdb"],
                   "--com-cleanup-dll", paths["helper"], "--identity-dll", paths["identity"], "--case", "ok"]
        done = subprocess.run(command, capture_output=True)
        report = json.loads((output / "run.json").read_text(encoding="utf-8")) if (output / "run.json").exists() else {}
        return {"command": command, "exit_code": done.returncode, "before": before, "after": state(self.base),
                "stdout_tail": done.stdout.decode("utf-8", "replace")[-2000:],
                "report": {k: report.get(k) for k in ("status", "error", "cleanup_verified", "timeout_phase",
                                                       "temporary_com_registration", "identity_registration")}}


GATE = ROOT / ".artifacts/platform77/active-session.json"
GATE_TEXT = json.dumps({"output": "harness77 task 015 native probes", "scope": "harness77 run, launcher_probes77.py"})


def gate(action):
    """Hold the research active-session gate during the series: kudir jobs and research
    scripts then refuse at once instead of failing on this series' COM registration."""
    if action == "gate-take":
        with GATE.open("x", encoding="utf-8") as stream:
            stream.write(GATE_TEXT)
    elif GATE.read_text(encoding="utf-8") == GATE_TEXT:
        GATE.unlink()
    else:
        raise SystemExit("the gate is not this series': " + GATE.read_text(encoding="utf-8"))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case", choices=("L0", "L4", "L5", "L1", "L2", "L3", "L6", "P2", "R1", "gate-take", "gate-release"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profiles", type=Path, default=ROOT / ".local/stage14-native")
    parser.add_argument("--run-args", default="", help="L6: extra `harness77 run` options, e.g. wider deadlines")
    args = parser.parse_args(argv)
    if args.case.startswith("gate-"):
        return gate(args.case)
    if args.output is None:
        parser.error("--output is required")
    probe = Probe(args)
    record = dict(case=args.case, **getattr(probe, args.case)())
    probe.save(args.case, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
