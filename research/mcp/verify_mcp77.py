"""Task 014 probes: harness77 mcp under the official MCP SDK client and real 1C.

Run with the research environment that holds the SDK (``.local/mcp-client/venv``);
the server and the CLI run with ``--python`` (by default the base interpreter of
that environment, where harness77 is installed).

conformance (C1)  the SDK client in ``auto`` mode (``server/discover`` first, then
                  the ``initialize`` fallback) calls every portable tool on local
                  inputs; each result next to the same command run through the CLI.
run (N1, N2)      one ``run`` call through the SDK client with a progress token and
                  pings during the call; ``--cancel-after-s`` abandons the call (the
                  SDK sends ``notifications/cancelled``) and the client stays until
                  ``run.json`` exists and the server logged the child's exit.
close (N3)        a plain client (its own process, no job object) calls ``run`` and
                  closes stdin after ``--close-after-s``, then waits for the server.
cli-run           the same run directly through the CLI (the N1 comparison).

Evidence: ``<output>/<probe>.json`` and the server log ``<output>/<probe>-server.log``.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".local" / "bases" / "base-for-test"
FIO = BASE / "ExtForms" / "rp14q1.GRP" / "FIO.ERT"
DOGOVOR = BASE / "ExtForms" / "Договор_Оргтехники.ert"
MD = BASE / "1Cv7.MD"
HELLO = ROOT / "examples" / "hello.1s"
P1, P2 = (ROOT / "tests" / "fixtures" / "compiler_protocol77" / name for name in ("p1.txt", "p2.txt"))
EXAMPLE = ROOT / "examples" / "full-cycle"


def parse(data):
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def cli(python, argv):
    result = subprocess.run([python, "-m", "harness77", *argv], cwd=ROOT, capture_output=True, timeout=900)
    return {"exit_code": result.returncode, "stdout": parse(result.stdout), "stderr": parse(result.stderr)}


def swapped(value, pairs):
    text = json.dumps(value, ensure_ascii=False)
    for old, new in pairs:
        text = text.replace(json.dumps(str(old), ensure_ascii=False)[1:-1],
                            json.dumps(str(new), ensure_ascii=False)[1:-1])
    return json.loads(text)


def one_c_processes():
    """PIDs of running 1C executables (the probes must leave no own session behind)."""
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace").stdout
    rows = [line.split('","') for line in out.splitlines() if line.startswith('"')]
    return sorted(int(row[1]) for row in rows if row[0].strip('"').lower() in ("1cv7l.exe", "1cv7.exe", "1cv7s.exe"))


def write(output, name, evidence):
    path = output / f"{name}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: evidence[k] for k in ("probe", "outcome") if k in evidence}, ensure_ascii=False))


def sdk_client(python, log, *, full_env=False):
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=python, args=["-m", "harness77", "mcp"], cwd=str(ROOT),
                                   env=dict(os.environ) if full_env else None)
    return Client(stdio_client(params, errlog=log), mode="auto", read_timeout_seconds=None)


def conformance_cases(mcp_dir, cli_dir, images):
    def pair(tool, arguments, argv):
        return {"tool": tool, "arguments": arguments(mcp_dir), "argv": argv(cli_dir)}
    return [
        pair("lint", lambda d: {"paths": [str(FIO), str(HELLO)]},
             lambda d: ["lint", "--format=json", str(FIO), str(HELLO)]),
        pair("lint", lambda d: {"paths": [str(HELLO)], "dialog": str(FIO), "strict": True},
             lambda d: ["lint", "--format=json", "--dialog", str(FIO), "--strict", str(HELLO)]),
        pair("compiler-protocol", lambda d: {"input": str(P1)}, lambda d: ["compiler-protocol", str(P1)]),
        pair("compiler-protocol", lambda d: {"input": str(P2), "encoding": "cp1251"},
             lambda d: ["compiler-protocol", "--encoding", "cp1251", str(P2)]),
        pair("triage", lambda d: {"protocol": str(P1)}, lambda d: ["triage", str(P1)]),
        pair("triage", lambda d: {"protocol": str(P2)}, lambda d: ["triage", str(P2)]),
        pair("extract", lambda d: {"input": str(FIO), "output": str(d / "fio.txt")},
             lambda d: ["extract", str(FIO), "--output", str(d / "fio.txt")]),
        pair("extract", lambda d: {"input": str(DOGOVOR), "output": str(d / "dogovor.1s")},
             lambda d: ["extract", str(DOGOVOR), "--output", str(d / "dogovor.1s")]),
        pair("form-extract", lambda d: {"input": str(DOGOVOR), "output": str(d / "dogovor.json"), "metadata": str(MD)},
             lambda d: ["form-extract", str(DOGOVOR), "--output", str(d / "dogovor.json"), "--metadata", str(MD)]),
        pair("build", lambda d: {"template": str(DOGOVOR), "source": str(d / "dogovor.1s"),
                                 "output": str(d / "dogovor.ert"), "form": str(d / "dogovor.json"), "metadata": str(MD)},
             lambda d: ["build", "--template", str(DOGOVOR), "--source", str(d / "dogovor.1s"), "--output",
                        str(d / "dogovor.ert"), "--form", str(d / "dogovor.json"), "--metadata", str(MD)]),
        pair("build", lambda d: {"template": str(DOGOVOR), "source": str(d / "dogovor.1s"),
                                 "output": str(d / "dogovor.ert")},
             lambda d: ["build", "--template", str(DOGOVOR), "--source", str(d / "dogovor.1s"), "--output",
                        str(d / "dogovor.ert")]),
        pair("visual-compare", lambda d: {"baseline": str(images[0]), "actual": str(images[1]),
                                          "output": str(d / "visual"), "masks": ["0,0,2,2"]},
             lambda d: ["visual", "compare", str(images[0]), str(images[1]), "--output", str(d / "visual"),
                        "--mask", "0,0,2,2"]),
        pair("run", lambda d: {"project": str(EXAMPLE / "project.toml"), "stand": str(EXAMPLE / "stand-simulation.toml"),
                               "run_id": "c1-simulation", "output_root": str(d / "runs")},
             lambda d: ["run", "--project", str(EXAMPLE / "project.toml"), "--stand",
                        str(EXAMPLE / "stand-simulation.toml"), "--run-id", "c1-simulation", "--output-root",
                        str(d / "runs")]),
    ]


async def conformance(args):
    from mcp.shared.exceptions import MCPError
    sys.path.insert(0, str(ROOT / "src"))
    from harness77.visual77 import Image, write_png
    mcp_dir, cli_dir = args.output / "mcp", args.output / "cli"
    mcp_dir.mkdir()
    cli_dir.mkdir()
    images = [args.output / "a.png", args.output / "b.png"]
    write_png(images[0], Image(4, 3, bytes(36)))
    write_png(images[1], Image(4, 3, bytes(33) + b"\xff\xff\xff"))
    evidence = {"probe": "C1", "python": args.python, "cases": []}
    with (args.output / "C1-server.log").open("w", encoding="utf-8") as log:
        async with sdk_client(args.python, log) as client:
            init = client.session.initialize_result
            evidence["protocol_version"] = client.protocol_version
            evidence["server_info"] = init.server_info.model_dump(mode="json") if init else None
            tools = (await client.list_tools()).tools
            evidence["tools"] = [tool.name for tool in tools]
            for case in conformance_cases(mcp_dir, cli_dir, images):
                result = await client.call_tool(case["tool"], case["arguments"])  # validates outputSchema
                structured = result.structured_content
                actual = {key: structured[key] for key in ("exit_code", "stdout", "stderr")}
                expected = cli(args.python, case["argv"])
                equal = swapped(actual, [(mcp_dir, cli_dir)]) == expected
                evidence["cases"].append({"tool": case["tool"], "arguments": case["arguments"],
                                          "mcp_argv": structured["argv"], "cli_argv": case["argv"],
                                          "exit_code": structured["exit_code"], "is_error": result.is_error,
                                          "equal_to_cli": equal, "duration_s": structured["duration_s"],
                                          **({} if equal else {"mcp": actual, "cli": expected})})
            invalid = await client.call_tool("lint", {"paths": []})
            evidence["invalid_arguments"] = {"is_error": invalid.is_error, "text": invalid.content[0].text,
                                             "structured": invalid.structured_content}
            try:
                await client.call_tool("catalog", {})
                evidence["unknown_tool"] = "no error"
            except MCPError as error:
                evidence["unknown_tool"] = {"code": error.error.code, "message": error.error.message}
    evidence["server_log"] = (args.output / "C1-server.log").read_text(encoding="utf-8").splitlines()
    cases = evidence["cases"]
    evidence["outcome"] = {"protocol_version": evidence["protocol_version"], "tools": len(evidence["tools"]),
                           "cases": len(cases), "equal_to_cli": sum(c["equal_to_cli"] for c in cases),
                           "discover_fallback": any("server/discover" in line for line in evidence["server_log"])}
    write(args.output, "C1", evidence)


def run_arguments(args):
    arguments = {"project": str(args.project), "stand": str(args.stand), "run_id": args.run_id,
                 "output_root": str(args.output / "runs")}
    return arguments


def run_summary(run_dir):
    path = run_dir / "run.json"
    if not path.exists():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    tests = next((s for s in report["stages"] if s["stage"] == "tests"), {})
    return {"status": report["status"], "exit_code": report["exit_code"], "cancelled": report["cancelled"],
            "timeout_phase": report["timeout_phase"], "platform_checked": report["platform_checked"],
            "reason": report["reason"], "stages": {s["stage"]: s["status"] for s in report["stages"]},
            "tests": [{k: t.get(k) for k in ("name", "status", "value")} for t in tests.get("tests") or []],
            "shutdown": report.get("shutdown")}


async def run_probe(args):
    from mcp.shared.exceptions import MCPError
    arguments = run_arguments(args)
    run_dir = args.output / "runs" / args.run_id
    log_path = args.output / f"{args.name}-server.log"
    evidence = {"probe": args.name, "arguments": arguments, "one_c_before": one_c_processes(),
                "full_env": args.full_env, "progress": [], "pings": []}
    started = time.monotonic()

    async def progress(value, total, message):
        evidence["progress"].append({"at_s": round(time.monotonic() - started, 1), "progress": value,
                                     "message": message})

    with log_path.open("w", encoding="utf-8") as log:
        async with sdk_client(args.python, log, full_env=args.full_env) as client:
            evidence["protocol_version"] = client.protocol_version
            task = asyncio.ensure_future(client.call_tool("run", arguments, progress_callback=progress))
            cancelled_at = None
            while not task.done():
                await asyncio.sleep(5)
                sent = time.monotonic()
                await client.session.send_ping()
                evidence["pings"].append({"at_s": round(sent - started, 1),
                                          "latency_s": round(time.monotonic() - sent, 3)})
                if args.cancel_after_s and cancelled_at is None and sent - started >= args.cancel_after_s:
                    task.cancel()
                    cancelled_at = time.monotonic()
                    evidence["cancelled_at_s"] = round(cancelled_at - started, 1)
                    break
            if cancelled_at is None:
                try:
                    result = await task
                    evidence["result"] = {"is_error": result.is_error, "structured": result.structured_content}
                except MCPError as error:
                    evidence["result"] = {"error": error.error.model_dump(mode="json")}
            else:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                # The server finishes the cancellation on its own: wait for its child's exit.
                deadline = time.monotonic() + args.wait_s
                while time.monotonic() < deadline:
                    text = log_path.read_text(encoding="utf-8")
                    if "run: exit" in text:
                        break
                    await asyncio.sleep(1)
                evidence["child_exit_after_cancel_s"] = round(time.monotonic() - cancelled_at, 1)
                sent = time.monotonic()
                await client.session.send_ping()
                evidence["ping_after_cancel_s"] = round(time.monotonic() - sent, 3)
    evidence["duration_s"] = round(time.monotonic() - started, 1)
    evidence["run"] = run_summary(run_dir)
    evidence["one_c_after"] = one_c_processes()
    evidence["server_log"] = log_path.read_text(encoding="utf-8").splitlines()
    evidence["outcome"] = {"run": None if evidence["run"] is None else {
        k: evidence["run"][k] for k in ("status", "exit_code", "cancelled", "platform_checked")},
        "response": "none (cancelled)" if "cancelled_at_s" in evidence else (
            evidence.get("result", {}).get("structured", {}) or {}).get("exit_code"),
        "progress_notifications": len(evidence["progress"]), "pings": len(evidence["pings"]),
        "one_c_left": sorted(set(evidence["one_c_after"]) - set(evidence["one_c_before"]))}
    write(args.output, args.name, evidence)


def close_probe(args):
    arguments = run_arguments(args)
    run_dir = args.output / "runs" / args.run_id
    log_path = args.output / f"{args.name}-server.log"
    evidence = {"probe": args.name, "arguments": arguments, "one_c_before": one_c_processes(), "messages": []}
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([args.python, "-m", "harness77", "mcp"], cwd=ROOT, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=log)
        started = time.monotonic()

        def read():
            for line in process.stdout:
                evidence["messages"].append({"at_s": round(time.monotonic() - started, 1),
                                             "message": json.loads(line.decode("utf-8"))})
        reader = threading.Thread(target=read)
        reader.start()

        def send(message):
            process.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
            process.stdin.flush()
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                         "clientInfo": {"name": "verify_mcp77-close", "version": "1"}}})
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "run", "arguments": arguments, "_meta": {"progressToken": "n3"}}})
        if args.after_marker:
            # Close only once the launcher reached the given point (e.g. the calculation started).
            marker = run_dir / args.after_marker
            while not marker.exists() and time.monotonic() - started < args.wait_s:
                time.sleep(0.5)
            evidence["marker_at_s"] = round(time.monotonic() - started, 1) if marker.exists() else None
        time.sleep(args.close_after_s)
        process.stdin.close()
        closed = time.monotonic()
        evidence["closed_at_s"] = round(closed - started, 1)
        evidence["server_exit_code"] = process.wait(timeout=args.wait_s)
        evidence["server_exit_after_close_s"] = round(time.monotonic() - closed, 1)
        reader.join(timeout=30)
    evidence["run"] = run_summary(run_dir)
    evidence["one_c_after"] = one_c_processes()
    evidence["server_log"] = log_path.read_text(encoding="utf-8").splitlines()
    response = next((m["message"] for m in evidence["messages"] if m["message"].get("id") == 2), None)
    structured = (response or {}).get("result", {}).get("structuredContent") or {}
    evidence["outcome"] = {"server_exit_code": evidence["server_exit_code"],
                           "server_exit_after_close_s": evidence["server_exit_after_close_s"],
                           "response_exit_code": structured.get("exit_code"),
                           "response_cancelled": (structured.get("stdout") or {}).get("cancelled"),
                           "run": None if evidence["run"] is None else {
                               k: evidence["run"][k] for k in ("status", "exit_code", "cancelled")},
                           "one_c_left": sorted(set(evidence["one_c_after"]) - set(evidence["one_c_before"]))}
    write(args.output, args.name, evidence)


def cli_run(args):
    arguments = run_arguments(args)
    evidence = {"probe": args.name, "one_c_before": one_c_processes()}
    started = time.monotonic()
    evidence["cli"] = cli(args.python, ["run", "--project", arguments["project"], "--stand", arguments["stand"],
                                        "--run-id", args.run_id, "--output-root", arguments["output_root"]])
    evidence["duration_s"] = round(time.monotonic() - started, 1)
    evidence["run"] = run_summary(args.output / "runs" / args.run_id)
    evidence["one_c_after"] = one_c_processes()
    evidence["outcome"] = {"exit_code": evidence["cli"]["exit_code"], "run": evidence["run"] and {
        k: evidence["run"][k] for k in ("status", "exit_code", "cancelled", "platform_checked")}}
    write(args.output, args.name, evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("probe", choices=("conformance", "run", "close", "cli-run"))
    parser.add_argument("--output", type=Path, required=True, help="Каталог результатов (для conformance — новый)")
    parser.add_argument("--python", default=getattr(sys, "_base_executable", sys.executable),
                        help="Интерпретатор с установленным harness77 (сервер и CLI)")
    parser.add_argument("--name", help="Имя пробы в файлах результата")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--stand", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--cancel-after-s", type=float)
    parser.add_argument("--close-after-s", type=float, default=45)
    parser.add_argument("--after-marker", help="Файл каталога запуска, после которого отсчитывать --close-after-s")
    parser.add_argument("--wait-s", type=float, default=600)
    parser.add_argument("--full-env", action="store_true", help="Передать серверу всё окружение, а не окружение SDK")
    args = parser.parse_args()
    if args.probe == "conformance":
        args.output.mkdir(parents=True, exist_ok=False)
        asyncio.run(conformance(args))
        return
    args.output.mkdir(parents=True, exist_ok=True)
    if not (args.project and args.stand and args.run_id and args.name):
        parser.error("run, close and cli-run need --name, --project, --stand and --run-id")
    if (args.output / "runs" / args.run_id).exists():
        parser.error("the run directory already exists")
    if args.probe == "run":
        asyncio.run(run_probe(args))
    elif args.probe == "close":
        close_probe(args)
    else:
        cli_run(args)


if __name__ == "__main__":
    main()
