"""MCP server (task 014): the protocol, equality with the CLI and cancellation."""

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

from harness77 import __version__, ert_module as ert, mcp77, run77
from harness77.visual77 import Image, write_png
from stage4_fixtures import base_scenario, write_project, write_sim_stand
from test_ert_dialog import DIALOG, make_ert

# Fixtures next to this file: the package check runs the tests from a copy outside the repository.
P2 = Path(__file__).resolve().parent / "fixtures" / "compiler_protocol77" / "p2.txt"
CLI = [sys.executable, "-m", "harness77"]
TIMEOUT_S = 120
GOOD = "Процедура Проверка() Экспорт\n    Сообщить(42);\nКонецПроцедуры\n"


def good_module(directory):
    path = Path(directory) / "good.1s"
    path.write_text(GOOD, encoding="utf-8")
    return path


def simulation(directory):
    """A project and a simulation stand of the stage-4 fixtures: (project, stand)."""
    directory = Path(directory)
    return write_project(directory), write_sim_stand(directory, base_scenario())


class Lines:
    """Messages from a binary stream, read on a thread."""

    def __init__(self, stream):
        self.queue = queue.Queue()
        threading.Thread(target=self._read, args=(stream,), daemon=True).start()

    def _read(self, stream):
        with stream:
            for line in stream:
                self.queue.put(json.loads(line.decode("utf-8")))
        self.queue.put(None)

    def next(self, timeout=TIMEOUT_S):
        return self.queue.get(timeout=timeout)


class Client:
    """The real server, ``python -m harness77 mcp``, in its own process."""

    def __init__(self, cwd):
        self.process = subprocess.Popen([*CLI, "mcp"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        self.lines = Lines(self.process.stdout)
        self.stderr = []
        threading.Thread(target=lambda: self.stderr.extend(self.process.stderr), daemon=True).start()
        self.counter = 0

    def send_raw(self, data):
        self.process.stdin.write(data + b"\n")
        self.process.stdin.flush()

    def send(self, message):
        self.send_raw(json.dumps(message, ensure_ascii=False).encode("utf-8"))

    def request(self, method, params=None):
        self.counter += 1
        message = {"jsonrpc": "2.0", "id": self.counter, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        return self.response(self.counter)

    def response(self, request_id):
        while True:
            message = self.lines.next()
            if message is None:
                raise AssertionError("the server closed its output")
            if message.get("id") == request_id and "method" not in message:
                return message

    def call(self, name, arguments):
        return self.request("tools/call", {"name": name, "arguments": arguments})["result"]

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        code = self.process.wait(timeout=TIMEOUT_S)
        self.process.stdout.close()
        self.process.stderr.close()
        return code


def cli(argv, cwd):
    result = subprocess.run([*CLI, *argv], cwd=cwd, capture_output=True, timeout=TIMEOUT_S)
    return result.returncode, mcp77._parse(result.stdout), mcp77._parse(result.stderr)


def same(result, expected, replace=()):
    """The tool result next to the CLI's (exit code, stdout, stderr) with output paths swapped."""
    actual = (result["structuredContent"]["exit_code"], result["structuredContent"]["stdout"],
              result["structuredContent"]["stderr"])
    text = json.dumps(actual, ensure_ascii=False)
    for old, new in replace:
        text = text.replace(json.dumps(str(old), ensure_ascii=False)[1:-1],
                            json.dumps(str(new), ensure_ascii=False)[1:-1])
    return json.loads(text), json.loads(json.dumps(expected, ensure_ascii=False))


class ServerProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="harness77-mcp-")
        cls.root = Path(cls.temp.name)
        cls.client = Client(cls.root)
        cls.init = cls.client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                     "clientInfo": {"name": "tests", "version": "1"}})
        cls.client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temp.cleanup()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=self.root))

    def test_initialize(self):
        result = self.init["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(result["serverInfo"]["version"], __version__)
        self.assertIn(str(self.root.resolve()), result["instructions"])
        unknown = self.client.request("initialize", {"protocolVersion": "1999-01-01", "capabilities": {},
                                                     "clientInfo": {"name": "tests", "version": "1"}})
        self.assertEqual(unknown["result"]["protocolVersion"], mcp77.PROTOCOL_VERSIONS[0])

    def test_tools_list(self):
        tools = {tool["name"]: tool for tool in self.client.request("tools/list")["result"]["tools"]}
        self.assertEqual(list(tools), ["lint", "compiler-protocol", "triage", "extract", "form-extract", "build",
                                       "run", "visual-compare"])
        for tool in tools.values():
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertEqual(tool["outputSchema"], mcp77.OUTPUT_SCHEMA)
        self.assertEqual(tools["build"]["inputSchema"]["required"], ["template", "source", "output"])
        self.assertTrue(tools["lint"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["run"]["annotations"]["destructiveHint"])
        self.assertFalse(tools["build"]["annotations"]["destructiveHint"])

    def test_protocol_errors(self):
        self.assertEqual(self.client.request("ping"), {"jsonrpc": "2.0", "id": self.client.counter, "result": {}})
        for raw, code in ((b"not json", -32700), (b"[1, 2]", -32600), (b'{"jsonrpc":"2.0","id":true,"method":"ping"}',
                                                                        -32600)):
            self.client.send_raw(raw)
            message = self.client.response(None)
            self.assertEqual(message["error"]["code"], code, raw)
        self.assertEqual(self.client.request("resources/list")["error"]["code"], -32601)
        self.assertEqual(self.client.request("tools/call", {"name": "catalog"})["error"]["code"], -32602)
        self.client.send({"jsonrpc": "2.0", "id": "text-id", "method": "tools/list", "params": [1]})
        self.assertEqual(self.client.response("text-id")["error"]["code"], -32602)

    def test_invalid_arguments_start_no_process(self):
        cases = ({"paths": []}, {"paths": "x.1s"}, {"paths": ["x.1s"], "format": "text"}, {"strict": True},
                 {"paths": ["x.1s"], "strict": "yes"}, {"paths": ["x\x00.1s"]})
        for arguments in cases:
            result = self.client.call("lint", arguments)
            self.assertTrue(result["isError"], arguments)
            self.assertNotIn("structuredContent", result)
        result = self.client.call("lint", None)  # arguments may be omitted: then the required one is missing
        self.assertIn("нет обязательного аргумента paths", result["content"][0]["text"])
        result = self.client.call("build", {"template": "a", "source": "b", "output": "c", "encoding": "koi8-r"})
        self.assertIn("encoding", result["content"][0]["text"])
        self.assertTrue(self.client.call("visual-compare", {"baseline": "a", "actual": "b", "output": "c",
                                                            "channel_tolerance": 1.5})["isError"])

    def test_lint_equals_cli(self):
        good = good_module(self.dir)
        bad = self.dir / "bad.1s"
        bad.write_text("Перем Если;\nСообщить(1);\n", encoding="utf-8")
        result = self.client.call("lint", {"paths": [str(good), str(bad)], "strict": True})
        self.assertEqual(result["structuredContent"]["exit_code"], 1)
        self.assertEqual(result["structuredContent"]["stdout"]["modules"], 2)
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        self.assertEqual(*same(result, cli(["lint", "--format=json", "--strict", str(good), str(bad)], self.root)))

    def test_path_beginning_with_a_dash(self):
        name = f"-{self.dir.name}.txt"  # relative to the server's directory
        shutil.copyfile(P2, self.root / name)
        result = self.client.call("compiler-protocol", {"input": name})
        self.assertEqual(result["structuredContent"]["argv"], ["compiler-protocol", "--encoding=auto", "--", name])
        self.assertEqual(result["structuredContent"]["exit_code"], 1, result)

    def test_protocol_and_triage_equal_cli(self):
        result = self.client.call("compiler-protocol", {"input": str(P2)})
        self.assertEqual(result["structuredContent"]["stdout"]["status"], "failed")
        self.assertEqual(*same(result, cli(["compiler-protocol", str(P2)], self.root)))
        result = self.client.call("triage", {"protocol": str(P2), "encoding": "auto"})
        self.assertEqual(*same(result, cli(["triage", str(P2)], self.root)))
        both = self.client.call("triage", {"protocol": str(P2), "source": "a.1s", "ert": "a.ert"})
        self.assertTrue(both["isError"])  # the CLI's own usage error, as text
        self.assertIn("not allowed with argument", both["structuredContent"]["stderr"])

    def test_ert_operations_equal_cli(self):
        template = self.dir / "шаблон.ert"
        template.write_bytes(make_ert(ert.encode_dialog(DIALOG)))
        source = self.dir / "модуль.1s"
        source.write_text("Процедура ВыгрузкаЭ02()\nКонецПроцедуры\n", encoding="utf-8")
        mcp, direct = self.dir / "mcp", self.dir / "cli"
        mcp.mkdir()
        direct.mkdir()

        result = self.client.call("extract", {"input": str(template), "output": str(mcp / "m.txt")})
        self.assertEqual(*same(result, cli(["extract", str(template), "--output", str(direct / "m.txt")], self.root),
                               [(mcp, direct)]))
        result = self.client.call("form-extract", {"input": str(template), "output": str(mcp / "f.json")})
        self.assertEqual(result["structuredContent"]["exit_code"], 0, result)
        self.assertEqual(*same(result, cli(["form-extract", str(template), "--output", str(direct / "f.json")],
                                           self.root), [(mcp, direct)]))
        result = self.client.call("build", {"template": str(template), "source": str(source),
                                            "output": str(mcp / "b.ert"), "form": str(mcp / "f.json")})
        self.assertEqual(result["structuredContent"]["stdout"]["form"]["dialog_unchanged"], True)
        expected = cli(["build", "--template", str(template), "--source", str(source), "--output",
                        str(direct / "b.ert"), "--form", str(direct / "f.json")], self.root)
        self.assertEqual(*same(result, expected, [(mcp, direct)]))
        self.assertEqual((mcp / "b.ert").read_bytes(), (direct / "b.ert").read_bytes())

        again = self.client.call("build", {"template": str(template), "source": str(source),
                                           "output": str(mcp / "b.ert")})
        self.assertTrue(again["isError"])
        self.assertEqual(again["structuredContent"]["stdout"], None)
        self.assertEqual(again["structuredContent"]["stderr"]["status"], "blocked")
        self.assertIn("Выход уже существует", again["structuredContent"]["stderr"]["error"])

    def test_visual_compare_equals_cli(self):
        baseline, actual = self.dir / "a.png", self.dir / "b.png"
        write_png(baseline, Image(4, 3, bytes(36)))
        write_png(actual, Image(4, 3, bytes(33) + b"\xff\xff\xff"))
        result = self.client.call("visual-compare", {"baseline": str(baseline), "actual": str(actual),
                                                     "output": str(self.dir / "mcp"), "masks": ["0,0,1,1"]})
        self.assertEqual(result["structuredContent"]["exit_code"], 1)
        self.assertFalse(result["isError"])
        expected = cli(["visual", "compare", str(baseline), str(actual), "--output", str(self.dir / "cli"),
                        "--mask", "0,0,1,1"], self.root)
        self.assertEqual(*same(result, expected, [(self.dir / "mcp", self.dir / "cli")]))

    def test_run_on_the_simulation_stand_equals_cli(self):
        project, stand = simulation(self.dir / "sim")
        arguments = {"project": str(project), "stand": str(stand), "run_id": "mcp-equality",
                     "output_root": str(self.dir / "mcp")}
        result = self.client.call("run", arguments)
        self.assertEqual(result["structuredContent"]["exit_code"], 0, result)
        self.assertTrue(any(item.startswith("--cancel-file=") for item in result["structuredContent"]["argv"]))
        expected = cli(["run", "--project", arguments["project"], "--stand", arguments["stand"], "--run-id",
                        "mcp-equality", "--output-root", str(self.dir / "cli")], self.root)
        self.assertEqual(*same(result, expected, [(self.dir / "mcp", self.dir / "cli")]))
        report = json.loads((self.dir / "mcp" / "mcp-equality" / "run.json").read_text(encoding="utf-8"))
        self.assertFalse(report["cancelled"])

    def test_closed_input_answers_calls_in_flight(self):
        client = Client(self.dir)
        try:
            client.counter = 7
            client.send({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                         "params": {"name": "lint", "arguments": {"paths": [str(good_module(self.dir))]}}})
        finally:
            client.process.stdin.close()
        self.assertEqual(client.response(8)["result"]["structuredContent"]["exit_code"], 0)
        self.assertEqual(client.close(), 0)


FAKE_CHILD = textwrap.dedent('''
    import json, os, sys, time
    argv = sys.argv[1:]
    cancel = next((a.split("=", 1)[1] for a in argv if a.startswith("--cancel-file=")), None)
    seconds = float(os.environ.get("FAKE_SECONDS", "1"))
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        if cancel and os.path.exists(cancel):
            print(json.dumps({"cancelled": True, "argv": argv}))
            sys.exit(2)
        time.sleep(0.05)
    print(json.dumps({"cancelled": False, "argv": argv}))
''')


class ServerThreadTests(unittest.TestCase):
    """The server in this process with a fake child: progress, cancellation, closed input."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-mcp-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        fake = root / "fake_child.py"
        fake.write_text(FAKE_CHILD, encoding="utf-8")
        read_in, self.write_in = os.pipe()
        read_out, write_out = os.pipe()
        self.input = os.fdopen(self.write_in, "wb")
        self.log = open(root / "server.log", "w", encoding="utf-8")
        self.addCleanup(self.log.close)
        reader, writer = os.fdopen(read_in, "rb"), os.fdopen(write_out, "wb")
        self.server = mcp77.Server(reader, writer, child=[sys.executable, str(fake)], cwd=root,
                                   progress_interval=0.3, log=self.log)
        self.exit = []

        def serve():
            try:
                self.exit.append(self.server.serve())
            finally:
                reader.close()
                writer.close()
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        self.lines = Lines(os.fdopen(read_out, "rb"))
        self.seen = []

    def send(self, message):
        self.input.write(json.dumps(message).encode("utf-8") + b"\n")
        self.input.flush()

    def call(self, request_id, name, arguments, meta=None):
        params = {"name": name, "arguments": arguments}
        if meta:
            params["_meta"] = meta
        self.send({"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": params})

    def until(self, request_id):
        while True:
            message = self.lines.next(timeout=30)
            self.seen.append(message)
            if message is not None and message.get("id") == request_id:
                return message

    def close(self):
        self.input.close()
        self.thread.join(timeout=30)
        self.assertEqual(self.exit, [0])
        rest = []
        while (message := self.lines.next(timeout=10)) is not None:
            rest.append(message)
        return rest

    def test_progress_while_a_call_runs(self):
        os.environ["FAKE_SECONDS"] = "1.2"
        self.addCleanup(os.environ.pop, "FAKE_SECONDS")
        self.call(1, "lint", {"paths": ["a.1s"]}, meta={"progressToken": "p1"})
        self.send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(self.until(2)["result"], {})  # answered while the call is running
        result = self.until(1)["result"]
        self.assertEqual(result["structuredContent"]["stdout"]["cancelled"], False)
        progress = [m["params"] for m in self.seen if m and m.get("method") == "notifications/progress"]
        self.assertGreaterEqual(len(progress), 2)
        self.assertTrue(all(p["progressToken"] == "p1" for p in progress))
        values = [p["progress"] for p in progress]
        self.assertEqual(values, sorted(set(values)))
        self.assertEqual(self.close(), [])

    def test_cancelled_run_gets_the_cancel_file_and_no_response(self):
        os.environ["FAKE_SECONDS"] = "20"
        self.addCleanup(os.environ.pop, "FAKE_SECONDS")
        self.call("r", "run", {"project": "p.toml", "stand": "s.toml"})
        time.sleep(0.5)
        self.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": "r",
                                                                                     "reason": "test"}})
        deadline = time.monotonic() + 15
        while self.server.calls and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.server.calls, {})
        self.send({"jsonrpc": "2.0", "id": "after", "method": "ping"})
        self.assertEqual(self.until("after")["result"], {})
        self.assertFalse(any(m and m.get("id") == "r" for m in self.seen))
        self.assertEqual(self.close(), [])
        self.assertFalse(self.server.cancel_dir.exists())

    def test_cancelled_short_call_finishes_without_response(self):
        os.environ["FAKE_SECONDS"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_SECONDS")
        self.call(5, "build", {"template": "t", "source": "s", "output": "o"})
        time.sleep(0.3)
        self.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 5}})
        started = time.monotonic()
        while self.server.calls and time.monotonic() - started < 10:
            time.sleep(0.05)
        self.assertGreater(time.monotonic() - started, 0.3)  # not killed: the child ran to its end
        self.assertEqual(self.close(), [])
        self.assertFalse(any(m and m.get("id") == 5 for m in self.seen))

    def test_closed_input_stops_a_run_and_still_answers(self):
        os.environ["FAKE_SECONDS"] = "20"
        self.addCleanup(os.environ.pop, "FAKE_SECONDS")
        self.call(9, "run", {"project": "p.toml", "stand": "s.toml"})
        time.sleep(0.5)
        rest = self.close()
        [response] = [m for m in rest if m.get("id") == 9]  # the child saw the cancel file, not its 20 s end
        self.assertEqual(response["result"]["structuredContent"]["stdout"]["cancelled"], True)
        self.assertTrue(response["result"]["isError"])

    def test_argv_mapping(self):
        tool = mcp77.TOOLS_BY_NAME["run"]
        self.assertEqual(tool.argv({"project": "-p.toml", "stand": "s.toml", "open_timeout_s": 120,
                                    "total_timeout_s": 7.5}),
                         ["run", "--project=-p.toml", "--stand=s.toml", "--open-timeout-s=120",
                          "--total-timeout-s=7.5"])
        tool = mcp77.TOOLS_BY_NAME["visual-compare"]
        self.assertEqual(tool.argv({"baseline": "a.png", "actual": "-b.png", "output": "o", "masks": ["1,2,3,4"],
                                    "max_diff_pixels": 0}),
                         ["visual", "compare", "--output=o", "--mask=1,2,3,4", "--max-diff-pixels=0", "--",
                          "a.png", "-b.png"])
        self.assertEqual(mcp77.TOOLS_BY_NAME["lint"].argv({"paths": ["a", "b"], "allow": ["X"], "strict": False}),
                         ["lint", "--format=json", "--allow=X", "--", "a", "b"])
        self.close()


class RunCancelFileTests(unittest.TestCase):
    def test_watch_sets_cancel_when_the_file_appears(self):
        with tempfile.TemporaryDirectory(prefix="harness77-cancel-") as temp:
            path = Path(temp) / "cancel"
            cancel, done = threading.Event(), threading.Event()
            watcher = threading.Thread(target=run77._watch_cancel_file, args=(path, cancel, done, 0.02))
            watcher.start()
            time.sleep(0.1)
            self.assertFalse(cancel.is_set())
            path.touch()
            watcher.join(timeout=5)
            self.assertTrue(cancel.is_set())
            other = threading.Event()
            done.set()
            stopped = threading.Thread(target=run77._watch_cancel_file, args=(Path(temp) / "never", other, done))
            stopped.start()
            stopped.join(timeout=5)  # done is set: the watcher ends without cancelling
            self.assertFalse(stopped.is_alive())
            self.assertFalse(other.is_set())

    def test_existing_cancel_file_blocks_before_anything_starts(self):
        with tempfile.TemporaryDirectory(prefix="harness77-cancel-") as temp:
            cancel = Path(temp) / "cancel"
            cancel.touch()
            project, stand = simulation(Path(temp) / "sim")
            code, stdout, stderr = cli(["run", "--project", str(project), "--stand", str(stand),
                                        "--output-root", str(Path(temp) / "runs"),
                                        "--cancel-file", str(cancel)], temp)
            self.assertEqual((code, stdout), (2, None))
            self.assertIn("FileExistsError", stderr["reason"])
            self.assertFalse((Path(temp) / "runs").exists())


if __name__ == "__main__":
    unittest.main()
