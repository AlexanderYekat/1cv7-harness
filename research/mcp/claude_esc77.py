"""Task 014 probe C5: Esc in interactive Claude Code cancels ``run``.

Claude Code runs in a pseudo-console (pywinpty) with the server as the owner adds it
(``claude mcp add``, local scope of the project) and without the session markers of a
parent Claude Code. The agent is asked to call ``run`` on the long profile; once the
launcher marks the calculation started, the probe presses Esc. After the run is over it
asks for ``lint`` (the server still serves) and leaves the client with /exit.

Needs pywinpty in the probe environment (.local/mcp-client/venv).
Evidence: ``<output>/C5.json`` and ``C5-screen.txt`` (screen text without escape codes,
rewritten every few seconds while the probe runs).
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from winpty import PtyProcess

from claude_probe77 import NATIVE, ROOT
from verify_mcp77 import one_c_processes, run_summary

ESCAPES = re.compile(r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[=>()][0-9A-Za-z]?")


class Screen:
    def __init__(self, process, path):
        self.process, self.path, self.chunks, self.started = process, path, [], time.monotonic()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        saved = 0
        while True:
            try:
                self.chunks.append(self.process.read(65536))
            except EOFError:
                return
            if time.monotonic() - saved > 3:
                self.save()
                saved = time.monotonic()

    def save(self):
        self.path.write_text(self.text(), encoding="utf-8", newline="\n")

    def text(self):
        return ESCAPES.sub("", "".join(self.chunks))

    def wait(self, needle, timeout_s, since=0):
        """Wait for text on the screen; the pseudo-console often drops spaces, so compare without them."""
        needle = re.sub(r"\s", "", needle)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if needle in re.sub(r"\s", "", self.text()[since:]):
                return True
            time.sleep(0.5)
        return False

    def type(self, text):
        """Key by key, then Enter once the text is on the screen; returns whether it was."""
        since = len(self.text())
        for char in text:
            self.process.write(char)
            time.sleep(0.02)
        echoed = self.wait(text[-20:], 15, since)
        time.sleep(1)
        self.process.write("\r")
        return echoed

    def at(self):
        return round(time.monotonic() - self.started, 1)


def com_keys():
    out = subprocess.run(["reg", "query", r"HKCU\Software\Classes", "/f", "Harness77Diagnostic", "/k"],
                         capture_output=True, text=True, errors="replace").stdout
    return [line.strip() for line in out.splitlines() if "Harness77Diagnostic" in line]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--stand", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--claude", default=str(NATIVE))
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--marker", default="native/ert-execute-started")
    parser.add_argument("--esc-after-s", type=float, default=5)
    parser.add_argument("--wait-s", type=float, default=600)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run_dir = args.output / "runs" / args.run_id
    if run_dir.exists():
        parser.error("the run directory already exists")
    rel = lambda path: path.resolve().relative_to(ROOT).as_posix()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_"))}
    evidence = {"probe": "C5", "arguments": {"project": rel(args.project), "stand": rel(args.stand),
                                             "output_root": f"{rel(args.output)}/runs", "run_id": args.run_id},
                "one_c_before": one_c_processes(), "com_keys_before": com_keys(),
                "env_dropped": sorted(set(os.environ) - set(env))}
    process = PtyProcess.spawn([args.claude, "--model", args.model, "--allowedTools", "mcp__harness77"],
                               cwd=str(ROOT), env=env, dimensions=(50, 200))
    screen = Screen(process, args.output / "C5-screen.txt")
    events = evidence["events"] = []
    try:
        events.append({"ready": screen.wait("❯", 180), "at_s": screen.at()})
        time.sleep(10)  # the prompt is drawn before the input takes keys
        typed = screen.type("Вызови инструмент run сервера harness77 с аргументами: "
                            + ", ".join(f"{k} {v}" for k, v in evidence["arguments"].items())
                            + ". Больше ничего не делай.")
        events.append({"run_asked_at_s": screen.at(), "typed": typed})
        marker = run_dir / args.marker
        deadline = time.monotonic() + args.wait_s
        report = run_dir / "run.json"
        while not marker.exists() and not report.exists() and time.monotonic() < deadline:
            time.sleep(0.5)
        events.append({"marker": marker.exists(), "at_s": screen.at()})
        evidence["run_json_after_esc_s"] = None
        if marker.exists():  # otherwise the run ended before the calculation: nothing to cancel
            time.sleep(args.esc_after_s)
            process.write("\x1b")
            esc = time.monotonic()
            events.append({"esc_at_s": screen.at()})
            while not report.exists() and time.monotonic() - esc < args.wait_s:
                time.sleep(0.5)
            evidence["run_json_after_esc_s"] = round(time.monotonic() - esc, 1) if report.exists() else None
        time.sleep(5)
        typed = screen.type("Проверь examples/hello.1s инструментом lint сервера harness77 и ответь одной строкой: "
                            "код выхода и число диагностик.")
        since = len(screen.text())
        # Claude Code 2.1.304 shows an MCP call in progress as "Calling harness77…"; the answer follows it.
        called = screen.wait("Calling harness77", 180, since)
        time.sleep(20)
        events.append({"lint_asked_at_s": screen.at(), "typed": typed, "lint_answered": called,
                       "at_s": screen.at()})
        evidence["lint_screen"] = screen.text()[since:][-1500:]
    finally:
        if run_dir.exists() and not (run_dir / "run.json").exists():
            # Leaving the client during run kills its tree (C3): cancel the run first.
            process.write("\x1b")
            deadline = time.monotonic() + args.wait_s
            while not (run_dir / "run.json").exists() and time.monotonic() < deadline:
                time.sleep(0.5)
        time.sleep(3)
        screen.type("/exit")
        deadline = time.monotonic() + 30
        while process.isalive() and time.monotonic() < deadline:
            time.sleep(0.5)
        evidence["client_exited"] = not process.isalive()
        if process.isalive():
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
        screen.save()
    evidence["run"] = run_summary(run_dir)
    evidence["one_c_after"] = one_c_processes()
    evidence["com_keys_after"] = com_keys()
    run = evidence["run"] or {}
    evidence["outcome"] = {
        "run": {k: run.get(k) for k in ("status", "exit_code", "cancelled", "reason")},
        "shutdown": run.get("shutdown"), "run_json_after_esc_s": evidence["run_json_after_esc_s"],
        "lint_answered": events[-1].get("lint_answered") if events else None,
        "client_exited": evidence["client_exited"],
        "one_c_left": sorted(set(evidence["one_c_after"]) - set(evidence["one_c_before"])),
        "com_keys_left": evidence["com_keys_after"]}
    (args.output / "C5.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8", newline="\n")
    print(json.dumps(evidence["outcome"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
