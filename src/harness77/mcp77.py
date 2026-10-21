"""MCP server on stdio: the CLI operations as tools (task 014).

Each tool is one CLI command. A call runs ``python -m harness77 <command> ...`` in a
child process with the tool's arguments mapped to the command's keys, so it returns
exactly what the CLI prints: the exit code, stdout and stderr (parsed when the
operation wrote JSON). The server holds no rules of its own. Only JSON-RPC goes to
stdout, one message per line; the server's own log goes to stderr.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from . import __version__

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PROGRESS_INTERVAL_S = 10.0
POLL_S = 0.2
CHILD = (sys.executable, "-m", "harness77")

INSTRUCTIONS = """\
harness77 — проверка разработки для 1С 7.7: статический анализ модулей, разбор протокола \
компилятора, извлечение и сборка ERT с формой, полный цикл проверки настоящей 1С (run), \
сравнение снимков формы. Каждый инструмент — команда CLI `harness77 <команда>` с теми же \
ключами; ответ — код выхода и JSON операции: 0 — прошло, 1 — найден дефект кода или провален \
тест (это результат проверки), 2 — отказ входа или инфраструктуры (isError). Относительные \
пути — от рабочего каталога сервера: {cwd}. Выход (output) — только новый файл или каталог: \
существующие не перезаписываются. run запускает 1С на базе стенда и может идти десятки минут; \
отмена запроса отменяет запуск. Утверждение визуальных эталонов и построение каталога \
платформы — только через CLI."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {"type": "string"},
        "argv": {"type": "array", "items": {"type": "string"}, "description": "Аргументы harness77"},
        "cwd": {"type": "string"},
        "exit_code": {"type": "integer", "description": "0 прошло, 1 дефект или провал теста, 2 отказ"},
        "stdout": {"description": "JSON операции, текст или null"},
        "stderr": {"description": "JSON отказа, текст или null"},
        "duration_s": {"type": "number"},
    },
    "required": ["tool", "argv", "cwd", "exit_code", "stdout", "stderr", "duration_s"],
}

TYPES = {"string": "строка", "boolean": "логическое", "integer": "целое", "number": "число",
         "array": "массив строк"}


class ArgumentError(ValueError):
    pass


class Arg:
    """One tool argument: ``flag`` None is positional (after ``--``); ``default`` is
    always passed, so every command has a key before ``--`` (the top-level parser
    takes a ``--`` that follows the command word itself)."""

    def __init__(self, name, flag, kind, description, *, required=False, choices=None, default=None):
        self.name, self.flag, self.kind, self.description = name, flag, kind, description
        self.required, self.choices, self.default = required, choices, default

    def schema(self):
        schema = {"type": "array", "items": {"type": "string"}} if self.kind == "array" else {"type": self.kind}
        if self.kind == "array" and self.required:
            schema["minItems"] = 1
        if self.choices:
            schema["enum"] = list(self.choices)
        if self.default is not None:
            schema["default"] = self.default
        schema["description"] = self.description
        return schema

    def check(self, value):
        if self.kind == "string":
            ok = isinstance(value, str)
        elif self.kind == "boolean":
            ok = isinstance(value, bool)
        elif self.kind == "integer":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif self.kind == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        if not ok:
            raise ArgumentError(f"{self.name}: ожидается {TYPES[self.kind]}")
        if self.choices and value not in self.choices:
            raise ArgumentError(f"{self.name}: допустимо {', '.join(self.choices)}")
        if self.kind == "array" and self.required and not value:
            raise ArgumentError(f"{self.name}: нужен хотя бы один элемент")
        if any("\x00" in item for item in (value if isinstance(value, list) else [value]) if isinstance(item, str)):
            raise ArgumentError(f"{self.name}: символ NUL не передаётся в командную строку")


class Tool:
    def __init__(self, name, title, command, description, args, *, read_only, destructive=False,
                 cancel_file=False):
        self.name, self.title, self.command, self.description, self.args = name, title, command, description, args
        self.read_only, self.destructive, self.cancel_file = read_only, destructive, cancel_file

    def describe(self):
        return {"name": self.name, "title": self.title, "description": self.description,
                "inputSchema": {"type": "object", "properties": {a.name: a.schema() for a in self.args},
                                "required": [a.name for a in self.args if a.required],
                                "additionalProperties": False},
                "outputSchema": OUTPUT_SCHEMA,
                "annotations": {"title": self.title, "readOnlyHint": self.read_only,
                                "destructiveHint": self.destructive, "idempotentHint": self.read_only,
                                "openWorldHint": False}}

    def argv(self, arguments):
        """The CLI arguments after ``harness77``; ArgumentError before any process starts."""
        if not isinstance(arguments, dict):
            raise ArgumentError("arguments: ожидается объект")
        unknown = sorted(set(arguments) - {arg.name for arg in self.args})
        if unknown:
            raise ArgumentError("неизвестные аргументы: " + ", ".join(unknown))
        options, positional = [], []
        for arg in self.args:
            if arg.name not in arguments:
                if arg.required:
                    raise ArgumentError(f"нет обязательного аргумента {arg.name}")
                if arg.default is not None:
                    options.append(f"{arg.flag}={arg.default}")
                continue
            value = arguments[arg.name]
            arg.check(value)
            if arg.flag is None:
                positional.extend(value if isinstance(value, list) else [value])
            elif arg.kind == "boolean":
                if value:
                    options.append(arg.flag)
            elif arg.kind == "array":
                options.extend(f"{arg.flag}={item}" for item in value)
            else:
                options.append(f"{arg.flag}={value}")
        return [*self.command, *options, *(["--", *positional] if positional else [])]


def _encoding(*choices):
    return Arg("encoding", "--encoding", "string", "Кодировка входа", choices=choices, default="auto")


TOOLS = (
    Tool("lint", "Статический анализ 1С 7.7", ("lint", "--format=json"),
         "Статический анализ модулей 1С 7.7 (lint77): текст TXT/1S/BSL, модуль ERT или модули 1Cv7.MD; "
         "JSON с диагностиками L77xx. Частичная проверка, не компилятор 1С. Код 1 — найдены ошибки.",
         [Arg("paths", None, "array", "Файлы TXT/1S/BSL/ERT/1Cv7.MD или каталоги исходников", required=True),
          Arg("globals", "--globals", "array", "Глобальный модуль (текст) или 1Cv7.MD: его экспортные функции"),
          Arg("allow", "--allow", "array", "Имена функций внешнего контекста, разрешённые явно"),
          Arg("dialog", "--dialog", "string", "ERT или описание формы JSON — контекст формы текстовых модулей"),
          Arg("metadata", "--metadata", "string",
              "1Cv7.MD базы, на которой исполняются модули: имена объектов метаданных (L7712, L7713)"),
          Arg("strict", "--strict", "boolean", "Неизвестные вызовы, L7709, L7711–L7713 считать ошибками")],
         read_only=True),
    Tool("compiler-protocol", "Протокол Конфигуратора в JSON", ("compiler-protocol",),
         "Импорт сохранённого протокола ошибок Конфигуратора 1С 7.7 в JSON: путь, строка, колонка, "
         "сообщение. 1С не запускается. Код 1 — в протоколе есть ошибки, 2 — протокол непригоден.",
         [Arg("input", None, "string", "Файл протокола", required=True), _encoding("auto", "utf-8", "cp1251")],
         read_only=True),
    Tool("triage", "Корень и каскад протокола", ("triage",),
         "Разметка протокола компилятора 1С 7.7: у каждой диагностики корень, каскад, связывание или "
         "неизвестное — с причиной и уверенностью, и где компиляция остановилась.",
         [Arg("protocol", None, "string", "Протокол Конфигуратора или нативный протокол загрузки", required=True),
          Arg("source", "--source", "string", "Текст модуля: уточняет правила (вместе с ert нельзя)"),
          Arg("ert", "--ert", "string", "ERT, из которой взят модуль (вместе с source нельзя)"),
          _encoding("auto", "utf-8", "cp1251")],
         read_only=True),
    Tool("extract", "Модуль ERT в текст", ("extract",),
         "Извлечь текст модуля ERT в новый файл UTF-8.",
         [Arg("input", None, "string", "ERT", required=True),
          Arg("output", "--output", "string", "Новый файл в существующем каталоге", required=True)],
         read_only=False),
    Tool("form-extract", "Описание формы ERT", ("form-extract",),
         "Описание формы ERT в JSON (harness77-form, схема 3): элементы, подписи, координаты, формулы, "
         "типы полей, в том числе ссылочные по имени. Записывается в новый файл; правленное описание "
         "собирает build.",
         [Arg("input", None, "string", "ERT", required=True),
          Arg("output", "--output", "string", "Новый файл в существующем каталоге", required=True),
          Arg("metadata", "--metadata", "string", "1Cv7.MD базы: сверить виды ссылочных полей по именам")],
         read_only=False),
    Tool("build", "Сборка ERT", ("build",),
         "Собрать новую ERT: шаблон + текст модуля, с описанием формы — и форму. Результат проверяется "
         "обратным чтением, остальные потоки шаблона сохраняются, существующий файл не перезаписывается. "
         "Платформой не проверяет — для этого run.",
         [Arg("template", "--template", "string", "ERT-шаблон", required=True),
          Arg("source", "--source", "string", "Текст модуля", required=True),
          Arg("output", "--output", "string", "Новая ERT в существующем каталоге", required=True),
          _encoding("auto", "utf-8", "cp1251", "utf-16"),
          Arg("legacy_normalize", "--legacy-normalize", "boolean",
              "Разрешить прежние замены символов вне CP1251 с перечислением в отчёте"),
          Arg("form", "--form", "string", "Описание формы (JSON harness77-form): собрать и диалог"),
          Arg("metadata", "--metadata", "string", "1Cv7.MD целевой базы: сверка видов полей формы по именам")],
         read_only=False),
    Tool("run", "Полный цикл на 1С 7.7", ("run",),
         "Полный цикл: статика → сборка → проверка настоящей 1С на базе стенда → тесты → отчёт "
         "(run.json в каталоге запуска). Профили проекта и стенда — TOML. Может идти десятки минут; "
         "отмена запроса отменяет запуск и останавливает свою 1С.",
         [Arg("project", "--project", "string", "Профиль проекта TOML", required=True),
          Arg("stand", "--stand", "string", "Профиль стенда TOML", required=True),
          Arg("output_root", "--output-root", "string", "Корень каталогов запусков (по умолчанию .artifacts/runs)"),
          Arg("run_id", "--run-id", "string", "run_id (по умолчанию новый UUID)"),
          *[Arg(f"{phase}_timeout_s", f"--{phase}-timeout-s", "number", f"Срок фазы {phase}, секунды")
            for phase in ("open", "calculation", "cancel", "shutdown", "total")],
          Arg("reindex_timeout_s", "--reindex-timeout-s", "number",
              "Запас к сроку открытия, если прошлый сеанс 1С на базе был прерван")],
         read_only=False, destructive=True, cancel_file=True),
    Tool("visual-compare", "Сравнение снимков формы", ("visual", "compare"),
         "Сравнить два PNG по пикселям вне масок; в новый каталог output пишутся diff.png и result.json. "
         "Код 1 — различия сверх допуска.",
         [Arg("baseline", None, "string", "Эталон PNG", required=True),
          Arg("actual", None, "string", "Снимок PNG", required=True),
          Arg("output", "--output", "string", "Новый каталог результата", required=True),
          Arg("masks", "--mask", "array", "Маски x,y,width,height"),
          Arg("channel_tolerance", "--channel-tolerance", "integer", "Допуск канала 0–255"),
          Arg("max_diff_pixels", "--max-diff-pixels", "integer", "Допустимое число отличающихся пикселей")],
         read_only=False),
)
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def _parse(data):
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _tool_error(message):
    return {"content": [{"type": "text", "text": message}], "isError": True}


class Call:
    def __init__(self, request_id, tool, arguments, progress_token):
        self.id, self.tool, self.arguments, self.progress_token = request_id, tool, arguments, progress_token
        self.stop = threading.Event()       # ask the child to stop (run: the cancel file)
        self.withdrawn = threading.Event()  # the client cancelled: no response is sent


class Server:
    def __init__(self, reader, writer, *, child=CHILD, cwd=None, progress_interval=PROGRESS_INTERVAL_S, log=None):
        self.reader, self.writer = reader, writer
        self.child = list(child)
        self.cwd = str(Path(cwd or os.getcwd()).resolve())
        self.progress_interval = progress_interval
        self.log = log or sys.stderr
        self.state = threading.Lock()
        self.output = threading.Lock()
        self.calls, self.workers = {}, []
        self.broken = False
        self.cancel_dir, self.counter = None, 0

    def serve(self):
        self._log(f"started {__version__}, cwd {self.cwd}")
        try:
            for line in self.reader:
                if line.strip():
                    self._handle(line)
        finally:
            self._close()
        return 0

    def _log(self, text):
        try:
            print(f"harness77 mcp: {text}", file=self.log, flush=True)
        except (OSError, ValueError):
            pass

    def _send(self, message):
        data = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        with self.output:
            if self.broken:
                return
            try:
                self.writer.write(data)
                self.writer.flush()
            except (OSError, ValueError):
                self.broken = True  # The client is gone; finish quietly.

    def _reply(self, request_id, result):
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _error(self, request_id, code, message):
        self._send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def _handle(self, line):
        try:
            message = json.loads(line.decode("utf-8"))
        except ValueError:
            return self._error(None, -32700, "Parse error")
        if not isinstance(message, dict):
            return self._error(None, -32600, "Invalid Request: JSON-RPC batches are not supported"
                               if isinstance(message, list) else "Invalid Request")
        method, params = message.get("method"), message.get("params")
        params = {} if params is None else params
        if "id" not in message:
            if isinstance(method, str) and isinstance(params, dict):
                self._notification(method, params)
            return None
        request_id = message["id"]
        if not isinstance(method, str):
            if "result" in message or "error" in message:
                return None  # A response; the server sends no requests.
            return self._error(None, -32600, "Invalid Request")
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            return self._error(None, -32600, "Invalid Request: id must be a string or an integer")
        if not isinstance(params, dict):
            return self._error(request_id, -32602, "Invalid params: an object is expected")
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return self._reply(request_id, {
                "protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "harness77", "title": "harness77 — 1С 7.7", "version": __version__},
                "instructions": INSTRUCTIONS.format(cwd=self.cwd)})
        if method == "ping":
            return self._reply(request_id, {})
        if method == "tools/list":
            return self._reply(request_id, {"tools": [tool.describe() for tool in TOOLS]})
        if method == "tools/call":
            return self._start(request_id, params)
        self._log(f"method not found: {method}")  # e.g. server/discover of a 2026-07-28 client
        return self._error(request_id, -32601, f"Method not found: {method}")

    def _notification(self, method, params):
        if method == "notifications/cancelled":
            request_id = params.get("requestId")
            if isinstance(request_id, (str, int)) and not isinstance(request_id, bool):
                with self.state:
                    call = self.calls.get(request_id)
                if call is not None:
                    self._log(f"request {request_id!r} cancelled by the client: {params.get('reason')}")
                    call.withdrawn.set()
                    call.stop.set()

    def _start(self, request_id, params):
        tool = TOOLS_BY_NAME.get(params.get("name"))
        if tool is None:
            return self._error(request_id, -32602, f"Unknown tool: {params.get('name')}")
        meta = params.get("_meta")
        token = meta.get("progressToken") if isinstance(meta, dict) else None
        arguments = params.get("arguments")
        call = Call(request_id, tool, {} if arguments is None else arguments, token)
        with self.state:
            self.workers = [worker for worker in self.workers if worker.is_alive()]
            if request_id in self.calls:
                busy = True
            else:
                busy = False
                self.calls[request_id] = call
                worker = threading.Thread(target=self._run, args=(call,), name=f"harness77-mcp-{request_id}")
                self.workers.append(worker)
        if busy:
            return self._error(request_id, -32600, "Invalid Request: the id is already in use")
        worker.start()
        return None

    def _run(self, call):
        try:
            result = self._execute(call)
        except Exception as error:  # A request is never left without an answer.
            result = _tool_error(f"{type(error).__name__}: {error}")
        with self.state:
            self.calls.pop(call.id, None)
        if call.withdrawn.is_set():
            return
        self._reply(call.id, result)

    def _execute(self, call):
        try:
            argv = call.tool.argv(call.arguments)
        except ArgumentError as error:
            return _tool_error(f"{call.tool.name}: {error}")
        cancel_file = self._cancel_path() if call.tool.cancel_file else None
        if cancel_file is not None:
            argv.append(f"--cancel-file={cancel_file}")
        self._log(f"{call.tool.name} {argv}")
        started = time.monotonic()
        process = subprocess.Popen([*self.child, *argv], cwd=self.cwd, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        signalled = False
        progress_at = started + self.progress_interval
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=POLL_S)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if cancel_file is not None and call.stop.is_set() and not signalled:
                    # Other operations are short and publish new files only: they finish.
                    cancel_file.touch()
                    signalled = True
                    self._log(f"{call.tool.name}: cancel file created")
                now = time.monotonic()
                if call.progress_token is not None and now >= progress_at:
                    # Polls are POLL_S apart, so the rounded values only grow.
                    elapsed = round(now - started, 1)
                    self._send({"jsonrpc": "2.0", "method": "notifications/progress",
                                "params": {"progressToken": call.progress_token, "progress": elapsed,
                                           "message": f"{call.tool.name}: {int(elapsed)} с"}})
                    progress_at = now + self.progress_interval
        finally:
            if cancel_file is not None:
                cancel_file.unlink(missing_ok=True)
        duration = round(time.monotonic() - started, 3)
        self._log(f"{call.tool.name}: exit {process.returncode} in {duration} s")
        structured = {"tool": call.tool.name, "argv": argv, "cwd": self.cwd, "exit_code": process.returncode,
                      "stdout": _parse(stdout), "stderr": _parse(stderr), "duration_s": duration}
        return {"content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
                "structuredContent": structured, "isError": process.returncode not in (0, 1)}

    def _cancel_path(self):
        with self.state:
            if self.cancel_dir is None:
                self.cancel_dir = Path(tempfile.mkdtemp(prefix="harness77-mcp-"))
            self.counter += 1
            return self.cancel_dir / f"cancel-{self.counter}"

    def _close(self):
        """The client closed stdin: stop runs, let short calls finish, answer while it reads."""
        with self.state:
            calls, workers = list(self.calls.values()), list(self.workers)
        for call in calls:
            call.stop.set()
        if calls:
            self._log(f"input closed; waiting for {len(calls)} call(s)")
        for worker in workers:
            worker.join()
        if self.cancel_dir is not None:
            try:
                self.cancel_dir.rmdir()
            except OSError:
                pass
        self._log("stopped")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="harness77 mcp", allow_abbrev=False,
                                     description="MCP-сервер на stdio: операции harness77 как инструменты")
    parser.parse_args(argv)
    reader, writer = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr  # A stray print must never reach the protocol channel.
    return Server(reader, writer).serve()
