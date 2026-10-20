"""A stub stdio MCP server for probe C3 (task 014): how does a client end a server?

It answers ``initialize``, ``tools/list`` (one tool, ``noop``) and ``tools/call``.
At start it records the names of its environment variables (not the values) and
starts a child that sleeps 120 s. When stdin closes it records the moment and then
stays alive for 30 s more, writing a line every second, so the log shows whether
the client waited, killed the server, and whether the child outlived it.

Usage: ``python stub_server77.py LOG.jsonl``.
"""

import json
import os
import subprocess
import sys
import time

LOG = open(sys.argv[1], "a", encoding="utf-8")
STARTED = time.monotonic()


def record(event, **data):
    LOG.write(json.dumps({"event": event, "at_s": round(time.monotonic() - STARTED, 2), "pid": os.getpid(),
                          **data}, ensure_ascii=False) + "\n")
    LOG.flush()


def reply(request_id, result):
    sys.stdout.buffer.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode() + b"\n")
    sys.stdout.buffer.flush()


SLEEP = [sys.executable, "-c", "import time; time.sleep(120)"]
QUIET = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
child = subprocess.Popen(SLEEP, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **QUIET)
extra = {}
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    flag = wintypes.BOOL()
    kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(flag))
    extra["in_job"] = bool(flag.value)
    # A grandchild whose parent exits at once: outside the tree by parent PID, not outside a job.
    middle = subprocess.run([sys.executable, "-c", "import subprocess, sys; d = subprocess.DEVNULL; print("
                             "subprocess.Popen(sys.argv[1:], creationflags=0x08000000, stdin=d, stdout=d, "
                             "stderr=d).pid)", *SLEEP], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    extra["orphan_pid"] = int(middle.stdout.strip())
    try:
        extra["breakaway_pid"] = subprocess.Popen(SLEEP, creationflags=0x01000000 | 0x08000000, **QUIET).pid
    except OSError as error:
        extra["breakaway_error"] = str(error)
record("start", env_names=sorted(os.environ), windir="WINDIR" in os.environ, child_pid=child.pid, **extra)
for line in sys.stdin.buffer:
    message = json.loads(line)
    method = message.get("method")
    record("message", method=method)
    if "id" not in message:
        continue
    if method == "initialize":
        reply(message["id"], {"protocolVersion": message["params"].get("protocolVersion", "2025-11-25"),
                              "capabilities": {"tools": {}}, "serverInfo": {"name": "stub77", "version": "1"}})
    elif method == "tools/list":
        reply(message["id"], {"tools": [{"name": "noop", "description": "Returns ok.",
                                         "inputSchema": {"type": "object", "properties": {}}}]})
    elif method == "tools/call":
        reply(message["id"], {"content": [{"type": "text", "text": "ok"}]})
    else:
        sys.stdout.buffer.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {
            "code": -32601, "message": "Method not found"}}).encode() + b"\n")
        sys.stdout.buffer.flush()
record("stdin-closed")
for second in range(30):
    time.sleep(1)
    record("alive", second=second + 1)
record("exit")
