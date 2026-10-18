"""Root, cascade and link marking of 1C 7.7 compiler diagnostics.

Every diagnostic is identified by the platform's own message catalog (the
``messages`` section of the packaged catalog, from 1crcrus.dll) and marked as
``root`` (fix it), ``cascade`` (a consequence of an earlier root, expected to
vanish after the fix), ``link`` (found while linking: each call site is its own
defect) or ``unknown`` (not in the catalog). Nothing is removed or reordered.
The rules and their confidence come from native probes of 7.70.027 (task 009);
a marking is advice for the next fix, not proof: recompile after fixing roots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

SCHEMA_VERSION = 1
_MARKER = "<<?>>"
_IDENT = r"[A-Za-zА-Яа-яЁё_][\wЁё]*"
_HEADER = re.compile(r"^\s*(?:процедура|функция|procedure|function)\s+(" + _IDENT + r")\s*\(", re.I)
_END = re.compile(r"^\s*(?:конецпроцедуры|конецфункции|endprocedure|endfunction)\b", re.I)
_FORWARD = re.compile(r"\)\s*(?:далее|forward)\b", re.I)
_ASSIGN = re.compile(r"^\s*(" + _IDENT + r")\s*=")
_ARGUMENT = re.compile(r"^(.*) \((.*)\)$", re.S)

# Catalog ids of 7.70.027 the rules refer to; their texts are checked against the catalog.
HEADER_PARAMETER = 1488   # Ожидается имя формального параметра
LOGICAL_END = 1475        # Обнаружено логическое завершение исходного текста модуля
END_EXPECTED = {1462, 1463}  # Ожидается ключевое слово 'КонецПроцедуры' / 'КонецФункции'
REDEFINED = 1533          # Процедура или функция с указанным именем уже определена
UNDEFINED = 1535          # Переменная не определена
TOO_MANY = 1539           # Слишком много фактических параметров
UNRESOLVED = 1560         # ... объявлена, но не определена в текущем модуле
LINK = {1531, 1532}       # Процедура не обнаружена / Функция не обнаружена
SEMANTIC = {UNDEFINED, UNRESOLVED} | LINK

# Rule code -> native evidence (docs/tasks/009-protocol-root-cascade.md).
RULES = {
    "root": "K3-K8, K13, P1n", "link": "K0, K1, K3-K16, P2n", "unknown": "",
    "header-swallowed": "K9, K11, K16, P1n", "header-parameter": "K9, K16, P1n",
    "header-call": "K14", "header-end": "K12, K16, P1n", "header-redefined": "K12",
    "same-line": "K12, K16, P1n", "logical-end": "K12, K16", "stopped": "K12, K16, P1n",
}
LIMITATIONS = [
    "Правила установлены нативными пробами 7.70.027 на модулях внешней обработки; другие версии и модули MD не проверялись.",
    "Без модуля правило header-swallowed не применяется, остальные правила по заголовку имеют меньшую уверенность.",
    "Разметка — подсказка для следующего исправления: после исправления корней нужна новая компиляция.",
]


def _code(line: str) -> str:
    """The line without string literals and the // comment."""
    result, quoted = [], False
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
            result.append(char)
        elif not quoted and line.startswith("//", index):
            break
        else:
            result.append(" " if quoted else char)
    return "".join(result)


class _Module:
    """Procedure boundaries, definitions and first body statements of a module text."""

    def __init__(self, text: str):
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.scope = [None] * (len(self.lines) + 2)
        self.defined, self.first_assignment = set(), {}
        open_header = None
        for number, raw in enumerate(self.lines, 1):
            code = _code(raw)
            header = _HEADER.match(code)
            if header and not _FORWARD.search(code):
                open_header = number
                self.defined.add(header.group(1).casefold())
                self.first_assignment[number] = self._first_statement(number)
            if open_header is not None:
                self.scope[number] = open_header
                if _END.match(code):
                    open_header = None

    def _first_statement(self, header: int) -> tuple[int, str] | None:
        """(line, name) when the first statement of the body is `Имя = ...`."""
        for number in range(header + 1, len(self.lines) + 1):
            code = _code(self.lines[number - 1])
            if not code.strip():
                continue
            if _END.match(code):
                return None
            match = _ASSIGN.match(code)
            return (number, match.group(1).casefold()) if match else None
        return None

    def line(self, number: int) -> str | None:
        return self.lines[number - 1] if 1 <= number <= len(self.lines) else None

    def assigned_between(self, name: str, first: int, last: int) -> bool:
        return any((m := _ASSIGN.match(_code(self.lines[n - 1]))) and m.group(1).casefold() == name
                   for n in range(first, min(last, len(self.lines) + 1)))


_EXPECTED = {HEADER_PARAMETER: "Ожидается имя формального параметра",
             LOGICAL_END: "Обнаружено логическое завершение исходного текста модуля",
             REDEFINED: "Процедура или функция с указанным именем уже определена в текущем модуле",
             UNDEFINED: "Переменная не определена", TOO_MANY: "Слишком много фактических параметров",
             UNRESOLVED: "Процедура или функция с указанным именем объявлена, но не определена в текущем модуле",
             1462: "Ожидается ключевое слово 'КонецПроцедуры' ('EndProcedure')",
             1463: "Ожидается ключевое слово 'КонецФункции' ('EndFunction')",
             1531: "Процедура не обнаружена", 1532: "Функция не обнаружена"}


def message_index(catalog: dict) -> dict[str, int]:
    """Message text -> catalog id; the ids the rules use must carry their 7.70.027 texts."""
    messages = {m["id"]: m["text"] for m in catalog.get("messages", [])}
    wrong = [i for i, text in _EXPECTED.items() if messages.get(i) != text]
    if wrong:
        raise ValueError(f"каталог сообщений не совпадает с 7.70.027 (номера {wrong})")
    return {text: i for i, text in messages.items()}


def identify(message: str, index: dict[str, int]) -> tuple[int | None, str | None]:
    if message in index:
        return index[message], None
    match = _ARGUMENT.match(message)
    if match and match.group(1) in index:
        return index[match.group(1)], match.group(2)
    return None, None


def _before_marker(diagnostic: dict) -> str | None:
    source, column = diagnostic.get("source_line"), diagnostic.get("column")
    if source is None or not isinstance(column, int) or column < 1:
        return None
    return source[:column - 1]


def _after_marker(diagnostic: dict) -> str | None:
    source, column = diagnostic.get("source_line"), diagnostic.get("column")
    if source is None or not isinstance(column, int) or column < 1:
        return None
    return source[column - 1:]


def _called_name(before: str) -> str | None:
    """Name of the call whose argument list holds the marker."""
    depth = 0
    for position in range(len(before) - 1, -1, -1):
        char = before[position]
        if char == ")":
            depth += 1
        elif char == "(":
            if depth == 0:
                match = re.search("(" + _IDENT + r")\s*$", before[:position])
                return match.group(1) if match else None
            depth -= 1
    return None


def _verify_module(diagnostics: list[dict], module: _Module) -> str | None:
    for diagnostic in diagnostics:
        source = diagnostic.get("source_line")
        if source is None:
            continue
        actual = module.line(diagnostic["line"])
        if actual is None or actual.strip() != source.strip():
            return f"строка {diagnostic['line']} протокола не совпадает с модулем"
    return None


def triage(diagnostics: list[dict], *, module_text: str | None = None, catalog: dict | None = None) -> dict:
    """Marked copies of ``diagnostics`` (line, message, optional column/source_line) and a summary."""
    if catalog is None:
        from .catalog77 import load_packaged
        catalog = load_packaged()
    index = message_index(catalog)
    module, module_info = None, None
    if module_text is not None:
        candidate = _Module(module_text)
        reason = _verify_module(diagnostics, candidate)
        verified = any(d.get("source_line") is not None for d in diagnostics)
        module_info = {"used": reason is None, "verified": reason is None and verified, "reason": reason}
        module = candidate if reason is None else None
    marked, headers, root_scopes, stops = [], [], set(), []
    for number, original in enumerate(diagnostics, 1):
        item = dict(original)
        message_id, argument = identify(item.get("message", ""), index)
        item.update(index=number, message_id=message_id, argument=argument)
        previous = marked[-1] if marked else None
        scope = module.scope[item["line"]] if module and 0 < item["line"] < len(module.scope) else None

        def mark(role, rule, confidence, explanation, cause=None):
            item.update(role=role, cause=cause, confidence=confidence, rule=rule, explanation=explanation)

        def root_of(other):
            return other["cause"] if other["role"] == "cascade" else other["index"]

        before, after = _before_marker(item), _after_marker(item)
        name = (argument or "").casefold()
        header = _header(item, module)
        if message_id is None:
            mark("unknown", "unknown", "low", "Сообщения нет в каталоге платформы 7.70.027.")
        elif message_id in LINK:
            mark("link", "link", "high", "Найдено при связывании: вызываемой процедуры или функции нет; "
                                         "каждое место вызова — отдельный дефект.")
        elif message_id == UNRESOLVED:
            earlier = next((d for d in reversed(marked) if d["message_id"] != UNRESOLVED), None)
            if module is not None and name in module.defined and earlier is not None:
                stops.append(item["line"])
                mark("cascade", "stopped", "high", f"Компиляция остановилась на строке {item['line']} и до "
                     f"определения {argument} не дошла.", root_of(earlier))
            elif module is None and earlier is not None and item.get("source_line") is not None:
                stops.append(item["line"])
                mark("cascade", "stopped", "medium", f"Похоже на остановку компиляции на строке {item['line']}: "
                     "сообщение стоит не в конце модуля; без модуля это не проверить.", root_of(earlier))
            else:
                mark("root", "root", "high" if module is not None else "medium",
                     "Процедура объявлена через Далее, но не определена.")
        elif message_id == LOGICAL_END and previous is not None:
            stops.append(item["line"])
            if previous["role"] == "cascade":
                mark("cascade", "logical-end", previous["confidence"], f"Разбор потерял структуру после ошибки строки "
                     f"{marked[previous['cause'] - 1]['line']}; компиляция остановлена.", previous["cause"])
            else:
                mark("cascade", "logical-end", "medium", f"Вероятно, следствие ошибки строки {previous['line']}; "
                     "компиляция остановлена.", root_of(previous))
        elif (message_id in END_EXPECTED and previous is not None
              and (target := _header_root(previous, headers, marked)) is not None):
            mark("cascade", "header-end", "high", f"Следствие ошибки в заголовке строки {target['line']}: "
                 "разбор ждёт конца процедуры.", target["index"])
        elif (message_id == REDEFINED and (target := next(
                (h for h in headers if h["forward"] and h["name"] == name), None)) is not None):
            mark("cascade", "header-redefined", "high", f"Объявление {argument} с ошибкой в заголовке (строка "
                 f"{target['line']}) принято за определение.", target["index"])
        elif (message_id == TOO_MANY and before is not None
              and (called := _called_name(before)) is not None
              and (target := next((h for h in headers if h["name"] == called.casefold()), None)) is not None):
            mark("cascade", "header-call", "high", f"Вызов {called}, у которой ошибка в заголовке (строка "
                 f"{target['line']}): параметры после ошибки не учтены.", target["index"])
        elif (message_id == UNDEFINED and module is not None and scope is not None
              and (target := next((h for h in headers if h["line"] == scope), None)) is not None
              and (first := module.first_assignment.get(scope)) is not None and first[1] == name
              and not module.assigned_between(name, first[0] + 1, item["line"])):
            mark("cascade", "header-swallowed", "high", f"Первый оператор после ошибочного заголовка (строка "
                 f"{target['line']}) не компилируется: присваивание {argument} в строке {first[0]} пропало.",
                 target["index"])
        elif (before is not None and (target := next(
                (h for h in reversed(headers) if h["parameter"] and h["line"] < item["line"]
                 and (module is None or scope == h["line"])
                 and re.search(r"(?<![\wЁё])" + re.escape(h["parameter"]) + r"$", before, re.I)), None)) is not None):
            mark("cascade", "header-parameter", "high" if module is not None else "medium",
                 f"Параметр {target['parameter']} из ошибочного заголовка (строка {target['line']}) не объявлен.",
                 target["index"])
        elif (previous is not None and message_id not in SEMANTIC and previous["role"] == "cascade"
              and previous["line"] == item["line"]
              and (item.get("column") or 0) >= (previous.get("column") or 0)):
            mark("cascade", "same-line", previous["confidence"],
                 "Та же строка правее каскадной ошибки — следствие того же корня.", previous["cause"])
        else:
            if message_id == LOGICAL_END:
                stops.append(item["line"])
            # Without the module every earlier root may share the procedure.
            key = scope if module is not None else None
            confidence = "high" if header is not None or key not in root_scopes else "medium"
            explanation = ("Ошибка в заголовке процедуры — самостоятельная ошибка; её следствия помечены каскадом."
                           if header is not None else "Не объясняется предыдущими диагностиками — самостоятельная ошибка.")
            if message_id == UNDEFINED and module is None and headers:
                explanation += " Может быть следствием ошибочного заголовка; для проверки нужен модуль."
            mark("root", "root", confidence, explanation)
            root_scopes.add(key)
        if header is not None and item["role"] == "root":
            headers.append({"index": number, **header})
        marked.append(item)
    counts = {role: sum(d["role"] == role for d in marked) for role in ("root", "cascade", "link", "unknown")}
    used = sorted({d["rule"] for d in marked})
    return {"summary": {"diagnostics": len(marked), **counts, "complete": not stops,
                        "compiled_through_line": max(stops) if stops else None,
                        "to_fix": [d["index"] for d in marked if d["role"] in ("root", "link")]},
            "module": module_info, "rules": {code: RULES[code] for code in used},
            "catalog": {"platform_version": catalog.get("platform_version"),
                        "strings_sha256": next((s["sha256"] for s in catalog.get("sources", [])
                                                if s.get("name", "").lower() == "1crcrus.dll"), None)},
            "diagnostics": marked, "limitations": LIMITATIONS}


def _header(item: dict, module: _Module | None) -> dict | None:
    """The procedure header the diagnostic points into, with the failed parameter name."""
    text = item.get("source_line")
    if text is None and module is not None:
        text = module.line(item["line"])
    if text is None:
        return None
    match = _HEADER.match(_code(text))
    if not match:
        return None
    before = _before_marker(item)
    if before is not None and "(" not in before:
        return None
    after = _after_marker(item) or ""
    parameter = re.match(r"\s*(" + _IDENT + ")", after) if item["message_id"] == HEADER_PARAMETER else None
    return {"line": item["line"], "name": match.group(1).casefold(),
            "parameter": parameter.group(1) if parameter else None, "forward": bool(_FORWARD.search(_code(text)))}


def _header_root(previous: dict, headers: list[dict], marked: list[dict]) -> dict | None:
    root = previous["cause"] if previous["role"] == "cascade" else previous["index"]
    return next((h for h in headers if h["index"] == root), None)


# --- protocol files and the command -------------------------------------------------

def read_protocol(data: bytes, *, encoding: str = "auto") -> dict:
    """Parse a saved Configurator protocol or a native load protocol (no terminator)."""
    from .compiler_protocol77 import parse_protocol
    kind = "configurator"
    if data.startswith(b"\xff\xfe") and not data.startswith(b"\xff\xfe\x00\x00"):
        data, encoding = data.decode("utf-16").encode("utf-8"), "utf-8"
    lines = data.splitlines(keepends=True)
    if lines and lines[0].startswith(b"HARNESS77-BEGIN:") and lines[-1].rstrip().startswith(b"HARNESS77-END:"):
        data, kind = b"".join(lines[1:-1]), "platform_load"
    parsed = parse_protocol(data, encoding=encoding)
    issues = parsed["issues"]
    if parsed["status"] == "blocked" and parsed["diagnostics"] and [i["code"] for i in issues] == ["missing_terminator"]:
        kind, issues = "platform_load", []
    return {"kind": kind, "encoding": parsed["input_encoding"], "diagnostics": parsed["diagnostics"],
            "unparsed_lines": parsed["unparsed_lines"], "issues": issues}


def _module_text(source: Path | None, ert: Path | None) -> tuple[str | None, dict | None]:
    from .ert_module import extract_text, read_source_file
    if source is not None:
        data = source.read_bytes()
        return read_source_file(source), {"kind": "source", "name": source.name, "sha256": hashlib.sha256(data).hexdigest()}
    if ert is not None:
        data = ert.read_bytes()
        return extract_text(ert), {"kind": "ert", "name": ert.name, "sha256": hashlib.sha256(data).hexdigest()}
    return None, None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="harness77 triage", allow_abbrev=False,
                                     description="Корень, каскад и связывание в протоколе компилятора 1С 7.7")
    parser.add_argument("protocol", type=Path, help="протокол Конфигуратора или нативный протокол загрузки")
    module = parser.add_mutually_exclusive_group()
    module.add_argument("--source", type=Path, help="текст модуля (TXT), уточняет правила")
    module.add_argument("--ert", type=Path, help="ERT, из которой взят модуль")
    parser.add_argument("--encoding", choices=("auto", "utf-8", "cp1251"), default="auto")
    parser.add_argument("--output", type=Path, help="новый файл JSON (по умолчанию stdout)")
    args = parser.parse_args(argv)
    report = {"schema_version": SCHEMA_VERSION, "tool": "harness77", "operation": "triage", "status": "blocked"}
    try:
        if args.output is not None and os.path.lexists(args.output):
            raise ValueError(f"выходной файл уже существует: {args.output}")
        data = args.protocol.read_bytes()
        protocol = read_protocol(data, encoding=args.encoding)
        text, module_source = _module_text(args.source, args.ert)
    except (OSError, ValueError, UnicodeError) as error:
        print(json.dumps({**report, "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    report["protocol"] = {"name": args.protocol.name, "sha256": hashlib.sha256(data).hexdigest(),
                          "kind": protocol["kind"], "encoding": protocol["encoding"]}
    report["issues"] = protocol["issues"]
    if not protocol["issues"]:
        result = triage(protocol["diagnostics"], module_text=text)
        if result["module"] is not None:
            result["module"].update(module_source)
        report.update(status="failed", **result)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    try:
        if args.output is None:
            sys.stdout.write(payload)
        else:
            with open(args.output, "x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
    except OSError as error:
        print(json.dumps({**report, "status": "blocked", "error": f"{type(error).__name__}: {error}"},
                         ensure_ascii=False)[:2000], file=sys.stderr)
        return 2
    return 1 if report["status"] == "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
