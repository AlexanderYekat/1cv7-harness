"""Compare native VBScript late binding with the PowerShell COM experiment."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
from focus_observer import FocusObserver


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--formex-fixture", type=Path)
    args = parser.parse_args()
    raise SystemExit("Runtime probes are blocked after the 2026-10-10 access-violation incident. See research/platform77/README.md; investigate shutdown before re-enabling launches.")
    base = args.base.resolve(strict=True)
    out = args.output.resolve()
    if out.is_relative_to(base):
        parser.error("output must be outside the base")
    out.mkdir(parents=True, exist_ok=False)
    script = out / "probe.vbs"
    script.write_text(Path(__file__).with_suffix(".vbs").read_text(encoding="utf-8"), encoding="utf-16")
    log = out / "dispatch.log"
    command = [r"C:\Windows\SysWOW64\cscript.exe", "//B", "//NoLogo", "//T:110", str(script), str(base), args.user, str(log)]
    if args.formex_fixture:
        fixture = args.formex_fixture.resolve(strict=True)
        if fixture.is_relative_to(base):
            parser.error("fixture must be outside the base")
        manifest = json.loads(fixture.with_name("fixture-manifest.json").read_text(encoding="utf-8"))
        if hashlib.sha256(fixture.read_bytes()).hexdigest() != manifest["synthetic_sha256"]:
            parser.error("fixture differs from its builder manifest")
        controller = out / "controller.txt"
        controller.write_text(Path(__file__).with_name("formex_controller.1s").read_text(encoding="utf-8"), encoding="utf-16")
        command.extend([str(fixture), str(controller)])

    def hashes():
        return {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in ["1Cv7.MD", "1Cv7.DD"]}

    report = {"at": datetime.datetime.now().astimezone().isoformat(), "hashes_before": hashes(),
              "client": "32-bit Windows Script Host, VBScript", "timeout_seconds": 120}
    start = time.monotonic()
    focus = FocusObserver()
    focus.start()
    with (out / "stdout.txt").open("wb") as stdout, (out / "stderr.txt").open("wb") as stderr:
        proc = subprocess.Popen(command,
                                stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        report["helper_pid"] = proc.pid
        try:
            report["exit_code"] = proc.wait(timeout=120)
            report["timed_out"] = False
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            report["exit_code"] = proc.returncode
            report["timed_out"] = True
    report["elapsed_seconds"] = round(time.monotonic() - start, 3)
    report["focus"] = focus.finish()
    report["hashes_after"] = hashes()
    report["log"] = log.read_text(encoding="utf-16") if log.exists() else ""
    report["passed"] = (report["exit_code"] == 0 and report["hashes_after"] == report["hashes_before"]
                        and "icpp-answer=42" in report["log"])
    if args.formex_fixture:
        report["passed"] = report["passed"] and all(line in report["log"].splitlines() for line in [
            "formex-attached", "handler-call=1", "after-handler=background-77;background-77|1;0", "form-closed"])
    (out / "observation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
