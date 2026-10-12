"""Import a saved 1C 7.7 error protocol; this module never runs the platform."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


_MARKER = "<<?>>"
_TERMINATOR = "При проверке модуля обнаружены синтаксические ошибки!"
_MAX_LINE_DIGITS = 640
_HEADER = re.compile(r"\{(?P<file>.+?)\((?P<line>[0-9]+)\)\}: (?P<message>.+)")


def _issue(code: str, message: str, protocol_line: int | None = None) -> dict:
    return {"code": code, "message": message, "protocol_line": protocol_line}


def _new_report(data: bytes) -> dict:
    return {
        "schema_version": 1,
        "tool": "compiler-protocol77",
        "scope": "imported_platform_protocol",
        "status": "blocked",
        "protocol_sha256": hashlib.sha256(data).hexdigest(),
        "input_encoding": None,
        "diagnostics": [],
        "unparsed_lines": [],
        "issues": [],
    }


def _decode(data: bytes, encoding: str) -> tuple[str | None, str | None, dict | None]:
    # Check UTF-32 first: its LE BOM starts with the UTF-16 LE BOM.
    for bom, name in ((b"\xff\xfe\x00\x00", "UTF-32 LE"),
                      (b"\x00\x00\xfe\xff", "UTF-32 BE"),
                      (b"\xff\xfe", "UTF-16 LE"), (b"\xfe\xff", "UTF-16 BE")):
        if data.startswith(bom):
            return None, None, _issue(
                "unsupported_encoding", f"BOM {name} не поддерживается; режим {encoding}.")
    has_bom = data.startswith(b"\xef\xbb\xbf")
    if has_bom and encoding == "cp1251":
        return None, None, _issue(
            "unsupported_encoding", "BOM UTF-8 противоречит режиму cp1251.")
    decoders = (["utf-8-sig"] if has_bom else
                ["utf-8", "cp1251"] if encoding == "auto" else [encoding])
    errors = []
    for decoder in decoders:
        try:
            return data.decode(decoder, errors="strict"), decoder, None
        except UnicodeDecodeError as exc:
            offset = exc.start + (3 if has_bom else 0)
            errors.append(f"{decoder}: байтовое смещение {offset} (с нуля)")
    return None, None, _issue("decode_error", "Ошибка декодирования: " + "; ".join(errors) + ".")


def _physical_lines(text: str) -> list[str]:
    parts = text.split("\n")
    lines = [part[:-1] if part.endswith("\r") else part for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _parse_header(match: re.Match[str] | None) -> dict | None:
    if match is None:
        return None
    file, digits, message = match.group("file", "line", "message")
    if not file.strip(" \t") or not message.strip(" \t"):
        return None
    digits = digits.lstrip("0")
    # 640 significant digits serialize even at Python's lowest configurable
    # decimal conversion limit. Do not bypass or change that process-wide limit.
    if not digits or len(digits) > _MAX_LINE_DIGITS:
        return None
    return {"file": file, "line": int(digits), "column": None, "message": message,
            "source_line": None, "protocol_line": None}


def parse_protocol(data: bytes, *, encoding: str = "auto") -> dict:
    """Return a fresh schema-v1 report, preserving partial diagnostics and issues.

    Invalid call arguments raise ValueError/TypeError. Invalid protocol bytes
    return blocked; a complete error protocol returns failed, never passed.
    Columns count Unicode code points (including TAB as one), starting at one.
    """
    if encoding not in ("auto", "utf-8", "cp1251"):
        raise ValueError("encoding must be auto, utf-8 or cp1251")
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    report = _new_report(data)
    text, decoder, error = _decode(data, encoding)
    if error is not None:
        report["issues"].append(error)
        return report
    report["input_encoding"] = decoder
    lines = _physical_lines(text)

    # Pass one: classification is independent of neighbours.
    kinds = []
    headers = {}
    terminators = []
    for index, line in enumerate(lines):
        if "\r" in line:
            kind = "unknown"
        elif not line.strip(" \t"):
            kind = "blank"
        elif line == _TERMINATOR:
            kind = "terminator"
            terminators.append(index)
        else:
            match = _HEADER.fullmatch(line)
            header = _parse_header(match)
            if header is not None:
                kind = "diagnostic"
                headers[index] = header
            elif match is not None and len(match.group("line").lstrip("0")) > _MAX_LINE_DIGITS:
                # An oversized header must not become another record's source
                # just because its message contains one source marker.
                kind = "unknown"
            elif line.count(_MARKER) == 1:
                kind = "source_candidate"
            else:
                kind = "unknown"
        kinds.append(kind)

    # Pass two: only an immediately preceding candidate can supply source text.
    used = set()
    for index, diagnostic in headers.items():
        diagnostic["protocol_line"] = index + 1
        if index > 0 and kinds[index - 1] == "source_candidate":
            source = lines[index - 1]
            diagnostic["column"] = source.index(_MARKER) + 1
            diagnostic["source_line"] = source.replace(_MARKER, "", 1)
            used.add(index - 1)
        report["diagnostics"].append(diagnostic)

    local_issues = []
    for index, (line, kind) in enumerate(zip(lines, kinds)):
        if kind == "unknown" or (kind == "source_candidate" and index not in used):
            report["unparsed_lines"].append({"protocol_line": index + 1, "text": line})
            local_issues.append(_issue("unparsed_line", "Строка протокола не распознана.", index + 1))

    significant = [i for i, kind in enumerate(kinds) if kind != "blank"]
    if not significant:
        report["issues"].append(_issue("empty_protocol", "Протокол не содержит значимых строк."))
    if not headers:
        report["issues"].append(_issue("no_diagnostics", "Диагностики не найдены."))
    if not terminators:
        report["issues"].append(_issue("missing_terminator", "Завершающий маркер отсутствует."))
    for index in terminators:
        if (len(terminators) != 1 or index != significant[-1]
                or not any(position < index for position in headers)):
            local_issues.append(_issue(
                "invalid_terminator",
                "Маркер должен быть единственным завершением после диагностик.", index + 1))
    report["issues"].extend(sorted(local_issues, key=lambda item: (item["protocol_line"], item["code"])))
    if not report["issues"]:
        report["status"] = "failed"
    return report


def _serialize(report: dict) -> bytes:
    return (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _check_destination(input_path: Path, output_path: Path) -> None:
    """Fail closed when file identity cannot be established."""
    if os.path.normcase(str(input_path)) == os.path.normcase(str(output_path)):
        raise ValueError("Вход и выход указывают на один файл.")
    if not stat.S_ISDIR(output_path.parent.stat().st_mode):
        raise ValueError("Родитель выходного файла должен быть каталогом.")
    try:
        output_stat = output_path.stat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(output_stat.st_mode):
        raise ValueError("Выход должен быть обычным файлом, а не каталогом или устройством.")
    if os.path.samefile(input_path, output_path):
        raise ValueError("Вход и выход имеют одну файловую идентичность (ссылка).")


def _resolve_paths(input_name: str, output_name: str | None) -> tuple[Path, Path | None]:
    input_path = Path(input_name).resolve(strict=True)
    if not stat.S_ISREG(input_path.stat().st_mode):
        raise ValueError("Вход должен быть доступным обычным файлом.")
    output_path = None
    if output_name is not None:
        output_path = Path(output_name).resolve(strict=False)
        _check_destination(input_path, output_path)
    return input_path, output_path


def _atomic_write(input_path: Path, output_path: Path, payload: bytes) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=output_path.parent,
                                         prefix=".compiler-protocol77-", suffix=".tmp",
                                         delete=False) as stream:
            temporary_path = Path(stream.name)
            if stream.write(payload) != len(payload):
                raise OSError("Временный файл записан не полностью.")
            stream.flush()
        # Recheck after closing the temporary file, immediately before publishing.
        _check_destination(input_path, output_path)
        os.replace(temporary_path, output_path)
    except (OSError, ValueError, RuntimeError) as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise OSError(f"{exc}; не удалось удалить временный файл "
                              f"{temporary_path}: {cleanup_error}") from exc
        raise


def _silence_failed_stdout() -> None:
    # A buffered broken pipe may otherwise flush again at interpreter shutdown,
    # print an ignored exception and override our exit code with 120.
    try:
        descriptor = sys.stdout.fileno()
        with open(os.devnull, "wb") as sink:
            os.dup2(sink.fileno(), descriptor)
    except (OSError, ValueError):
        # Some embedded callers supply a binary stream without an OS descriptor.
        # Close it explicitly so its destructor cannot repeat the failed flush.
        try:
            sys.stdout.close()
        except (OSError, ValueError):
            pass
        sys.stdout = None


def _write_stdout(payload: bytes) -> None:
    try:
        if sys.stdout.buffer.write(payload) != len(payload):
            raise OSError("stdout принял не весь JSON.")
        sys.stdout.buffer.flush()
    except (OSError, ValueError):
        _silence_failed_stdout()
        raise


def _operational_error(exc: Exception, output_name: str | None) -> int:
    message = f"compiler-protocol77: {exc}"
    if output_name is not None:
        separator = " " if message.endswith((".", "!", "?")) else ". "
        message += separator + "Новый результат не записан; существующий выходной файл не подтверждает этот запуск"
    print(message, file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compiler-protocol77",
        allow_abbrev=False,
        description="Импорт сохранённого протокола ошибок Конфигуратора 1С 7.7 в JSON.")
    parser.add_argument("input", metavar="INPUT", help="файл протокола")
    parser.add_argument("--encoding", choices=("auto", "utf-8", "cp1251"), default="auto")
    parser.add_argument("--format", choices=("json",), default="json")
    parser.add_argument("--output", metavar="OUTPUT", help="файл JSON (по умолчанию stdout)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        input_path, output_path = _resolve_paths(args.input, args.output)
        data = input_path.read_bytes()
    except (OSError, ValueError, RuntimeError) as exc:
        return _operational_error(exc, args.output)
    report = parse_protocol(data, encoding=args.encoding)
    try:
        payload = _serialize(report)
    except (TypeError, ValueError) as exc:
        return _operational_error(exc, args.output)
    try:
        if output_path is None:
            _write_stdout(payload)
        else:
            _atomic_write(input_path, output_path, payload)
    except (OSError, ValueError, RuntimeError) as exc:
        return _operational_error(exc, args.output)
    return 1 if report["status"] == "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
