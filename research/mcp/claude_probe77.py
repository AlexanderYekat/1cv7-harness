"""Task 014 probes with Claude Code as the MCP client (headless ``claude -p``).

lint (C2)      harness77 mcp is the only MCP server and ``mcp__harness77__lint`` the
               only allowed tool; the agent is asked to check examples/hello.1s.
shutdown (C3)  the stub server (stub_server77.py) is the only server; the agent calls
               its ``noop`` tool once. The stub's log then shows how Claude Code ended
               it: stdin closed or not, how long it waited, whether the child lived on.
registered (C4) the server as the owner adds it (``claude mcp add``, no config of the
               probe); the agent checks a module, takes the form description out of an
               ERT and builds a new ERT from it, all by paths relative to the project.

Evidence: ``<output>/<probe>.json`` with the stream-json events of the session.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
# npm installs a .cmd shim; the shim runs this executable.
NATIVE = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                         text=True, errors="replace").stdout
    return f'"{pid}"' in out


def session(args, config, prompt, allowed):
    command = [args.claude, "-p", prompt]
    if config is not None:
        config_path = args.output / f"{args.probe}-mcp.json"
        config_path.write_text(json.dumps({"mcpServers": config}, ensure_ascii=False, indent=2), encoding="utf-8")
        command += ["--mcp-config", str(config_path), "--strict-mcp-config"]
    command += ["--allowedTools", allowed, "--output-format", "stream-json", "--verbose", "--model", args.model]
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=600)
    events = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            events.append({"raw": line})
    return {"command": command, "exit_code": result.returncode, "duration_s": round(time.monotonic() - started, 1),
            "stderr": result.stderr.decode("utf-8", errors="replace")[-4000:], "events": events}


def tool_calls(events):
    calls, results = [], []
    for event in events:
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append({"name": block.get("name"), "input": block.get("input")})
            if isinstance(block, dict) and block.get("type") == "tool_result":
                content = block.get("content")
                text = content if isinstance(content, str) else "".join(
                    part.get("text", "") for part in content or [] if isinstance(part, dict))
                results.append({"is_error": block.get("is_error"), "text": text[:3000]})
    return calls, results


def init_event(events):
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    return {"mcp_servers": init.get("mcp_servers"),
            "mcp_tools": [t for t in init.get("tools") or [] if str(t).startswith("mcp__")]}


def lint(args):
    config = {"harness77": {"command": args.python, "args": ["-m", "harness77", "mcp"]}}
    prompt = (f"Проверь файл {ROOT / 'examples' / 'hello.1s'} инструментом lint сервера harness77 "
              "и ответь одной строкой: код выхода и число диагностик.")
    evidence = {"probe": "C2", **session(args, config, prompt, "mcp__harness77__lint")}
    calls, results = tool_calls(evidence["events"])
    evidence["outcome"] = {"exit_code": evidence["exit_code"], **init_event(evidence["events"]), "tool_calls": calls,
                           "tool_results": results,
                           "answer": next((e.get("result") for e in evidence["events"] if e.get("type") == "result"),
                                          None)}
    return evidence


def shutdown(args):
    log = args.output / "C3-stub.jsonl"
    config = {"stub77": {"command": sys.executable, "args": [str(Path(__file__).with_name("stub_server77.py")),
                                                            str(log)]}}
    evidence = {"probe": "C3", **session(args, config, "Вызови инструмент noop сервера stub77 один раз и ответь ok.",
                                         "mcp__stub77__noop")}
    ended = time.monotonic()
    time.sleep(40)  # The stub stays 30 s after stdin closes; look after that.
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    start = next((r for r in records if r["event"] == "start"), {})
    closed = next((r for r in records if r["event"] == "stdin-closed"), None)
    last = records[-1] if records else None
    evidence["stub_log"] = records
    calls, results = tool_calls(evidence["events"])
    evidence["outcome"] = {"exit_code": evidence["exit_code"], **init_event(evidence["events"]), "tool_calls": calls,
                           "server_windir": start.get("windir"), "server_env_names": len(start.get("env_names") or []),
                           "stdin_closed": closed is not None,
                           "server_last_event": last and {k: last.get(k) for k in ("event", "at_s", "second")},
                           "server_alive_after_s": round(time.monotonic() - ended, 1),
                           "server_alive_now": bool(start) and alive(start["pid"]),
                           "child_alive_now": bool(start) and alive(start["child_pid"]),
                           "server_in_job": start.get("in_job"), "breakaway_error": start.get("breakaway_error"),
                           "orphan_alive_now": bool(start.get("orphan_pid")) and alive(start["orphan_pid"]),
                           "breakaway_alive_now": bool(start.get("breakaway_pid")) and alive(start["breakaway_pid"])}
    return evidence


def registered(args):
    out = args.output.resolve().relative_to(ROOT).as_posix()
    prompt = (f"Работай только инструментами сервера harness77, пути — относительно текущего каталога. "
              f"1) Проверь модуль examples/full-cycle/module.1s инструментом lint. "
              f"2) Инструментом form-extract извлеки описание формы из examples/full-cycle/form.ert "
              f"в {out}/form.json. "
              f"3) Инструментом build собери {out}/new.ert: шаблон examples/full-cycle/form.ert, "
              f"модуль examples/full-cycle/module.1s, форма {out}/form.json. "
              "Ответь тремя строками: инструмент, код выхода, status из JSON.")
    evidence = {"probe": "C4", **session(args, None, prompt, "mcp__harness77")}
    calls, results = tool_calls(evidence["events"])
    built = ROOT / out / "new.ert"
    evidence["outcome"] = {"exit_code": evidence["exit_code"], **init_event(evidence["events"]), "tool_calls": calls,
                           "tool_results": results, "new_ert_bytes": built.stat().st_size if built.is_file() else None,
                           "answer": next((e.get("result") for e in evidence["events"] if e.get("type") == "result"),
                                          None)}
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("probe", choices=("lint", "shutdown", "registered"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--claude", default=str(NATIVE) if NATIVE.is_file() else "claude")
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--python", default=sys.executable, help="Интерпретатор с установленным harness77")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {"lint": lint, "shutdown": shutdown, "registered": registered}[args.probe](args)
    name = evidence["probe"]
    (args.output / f"{name}.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8", newline="\n")
    print(json.dumps(evidence["outcome"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
