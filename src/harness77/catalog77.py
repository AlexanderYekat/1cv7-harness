"""Catalog of 1C 7.7 names extracted from the installed platform.

Sources are the platform's own files: the syntax helper ``1cv7Lang.als`` (names,
folders, component flags and parameter counts of every signature) and the string
resources of ``1crcrus.dll`` (``English,Русское`` name pairs and the messages of
the language processor). Descriptions and
insertion templates are not copied: the catalog keeps names and arity only.
The same input bytes always give the same output bytes.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import struct
import sys

SCHEMA_VERSION = 1
PACKAGED = "catalog77.json"
LIMITATIONS = [
    "Имена и число параметров взяты из справочника и ресурсов платформы, а не из компилятора.",
    "Методы объектов конфигурации, COM и внешних компонент (1С++, FormEx) в каталоге отсутствуют.",
    "Одноимённые методы разных объектов не различаются: правила берут наибольшее число параметров.",
    "Пары из 1crcrus.dll не имеют вида: это известные платформе имена, без указания контекста.",
    "reserved — непрерывный блок строк 1crcrus.dll от таблицы ключевых слов (If,Если); "
    "что эти имена нельзя объявлять, установлено пробой 7.70.027, а не самим файлом.",
    "messages — строки 1crcrus.dll между опорными «Ошибок не обнаружено», «Индексное выражение должно "
    "иметь целочисленный тип» и таблицей ключевых слов; блоки compile/runtime — по расположению строк. "
    "Что сообщение выдаёт компилятор, установлено пробами 7.70.027 только для наблюдённых сообщений.",
]
_COMPILE_ANCHOR = "Ошибок не обнаружено"
_RUNTIME_ANCHOR = "Индексное выражение должно иметь целочисленный тип"
_TOKEN = re.compile(r'"((?:[^"]|"")*)"|([{}])|(,)|(\s+)|(.)', re.S)
_IDENT = re.compile(r"[A-Za-zА-Яа-яЁё_][\wЁё]*")
_PAIR = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-zА-Яа-яЁё_][\wЁё]*)\s*")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
RT_STRING = 6
RT_VERSION = 16


class CatalogError(ValueError):
    pass


def _als_tree(text: str) -> list:
    """Nested lists of strings: the brace notation of the syntax helper."""
    stack: list[list] = [[]]
    for match in _TOKEN.finditer(text):
        string, brace, _comma, _space, other = match.groups()
        if string is not None:
            stack[-1].append(string.replace('""', '"'))
        elif brace == "{":
            node: list = []
            stack[-1].append(node)
            stack.append(node)
        elif brace == "}":
            if len(stack) == 1:
                raise CatalogError("Лишняя закрывающая скобка в справочнике.")
            stack.pop()
        elif other is not None:
            raise CatalogError(f"Неожиданный символ {other!r} в справочнике.")
    if len(stack) != 1 or len(stack[0]) != 1 or not isinstance(stack[0][0], list):
        raise CatalogError("Справочник не является одним списком в фигурных скобках.")
    return stack[0][0]


def _signature_counts(signature: str, name: str) -> list[int | None]:
    """Parameter count of each call of ``name`` in the text; None means variadic."""
    counts = []
    candidates = ([m.end() - 1 for m in re.finditer(r"(?<!\w)" + re.escape(name) + r"\s*\(", signature)]
                  if name else [])
    if not candidates:
        first = signature.find("(")
        candidates = [first] if first >= 0 else []
    for start in candidates:
        depth, commas, end = 0, 0, None
        for index in range(start, len(signature)):
            char = signature[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    end = index
                    break
            elif char == "," and depth == 1:
                commas += 1
        if end is None:
            continue
        inner = signature[start + 1:end]
        if "..." in inner or "…" in inner:
            counts.append(None)
        else:
            counts.append(commas + 1 if inner.strip() else 0)
    return counts


def _call_name(template: str) -> str | None:
    """Identifier a module writes: last name before '(' or the attribute itself."""
    head = template.split("(", 1)[0].split("\n", 1)[0].strip()
    head = re.sub(r"^(Процедура|Функция|Procedure|Function)\s+", "", head)
    # Placeholders such as <Реквизит> or Форма.<?> are not names.
    if not head or head.endswith(">"):
        return None
    names = _IDENT.findall(head)
    return names[-1] if names else None


def _kind(folder: list[str], template: str) -> str:
    if folder[:1] == ["Конструкции языка"]:
        return "keyword"
    if folder[:2] == ["Запрос", "Язык Запросов"]:
        return "query_language"
    if re.match(r"\s*(Процедура|Функция)\s", template):
        return "predefined_procedure"
    if folder[:2] == ["Системные", "Функции/процедуры"]:
        return "global_function"
    if folder[:2] == ["Системные", "Константы"]:
        return "global_constant"
    return "method" if "(" in template else "attribute"


def parse_als(text: str) -> list[dict]:
    tree = _als_tree(text)
    items: list[dict] = []

    def walk(node: list, folder: list[str]) -> None:
        if node and node[0] == "Folder":
            if len(node) < 3 or not isinstance(node[2], str):
                raise CatalogError("Папка справочника без имени.")
            folder = folder + [node[2]] if node[2] else folder
        elif node and node[0] == "Item":
            if len(node) != 7 or not all(isinstance(value, str) for value in node):
                raise CatalogError(f"Неизвестная структура записи справочника: {node[:3]!r}")
            _, flags, title_ru, title_en, template_ru, template_en, description = node
            kind = _kind(folder, template_ru)
            name_ru, name_en = _call_name(template_ru), _call_name(template_en)
            if kind == "keyword":
                name_ru = (_IDENT.findall(title_ru) or [None])[0]
                name_en = (_IDENT.findall(title_en) or [None])[0]
            item = {"kind": kind, "name_ru": name_ru, "name_en": name_en,
                    "title_ru": title_ru, "title_en": title_en,
                    "folder": "/".join(folder), "components": flags}
            if "(" in template_ru and kind not in ("keyword", "query_language"):
                syntax = re.search(r"@Синтаксис:(.*?)(?:\n\s*@|\Z)", description.replace("\r\n", "\n"), re.S)
                signatures = _signature_counts(template_ru, name_ru or "")
                if syntax:
                    signatures += _signature_counts(syntax.group(1), name_ru or "")
                item["params"] = signatures
                item["max_params"] = None if None in signatures or not signatures else max(signatures)
            items.append(item)
            return
        for child in node:
            if isinstance(child, list):
                walk(child, folder)

    walk(tree, [])
    if not items:
        raise CatalogError("В справочнике не найдено записей Item.")
    return items


class _Pe:
    def __init__(self, data: bytes):
        self.data = data
        try:
            if data[:2] != b"MZ":
                raise CatalogError("Файл ресурсов не является PE (нет MZ).")
            pe = struct.unpack_from("<I", data, 0x3C)[0]
            if data[pe:pe + 4] != b"PE\0\0":
                raise CatalogError("Файл ресурсов не является PE (нет сигнатуры PE).")
            sections, optional_size = struct.unpack_from("<H12xH", data, pe + 6)
            optional = pe + 24
            magic = struct.unpack_from("<H", data, optional)[0]
            directories = optional + {0x10B: 96, 0x20B: 112}.get(magic, -1)
            if directories < optional:
                raise CatalogError(f"Неизвестный формат PE optional header: {magic:#x}.")
            self.resource_rva, self.resource_size = struct.unpack_from("<II", data, directories + 2 * 8)
            table = optional + optional_size
            self.sections = [struct.unpack_from("<8xIIII", data, table + 40 * i) for i in range(sections)]
        except struct.error as error:
            raise CatalogError(f"Повреждён заголовок PE: {error}") from error
        if not self.resource_rva:
            raise CatalogError("В PE нет каталога ресурсов.")
        self.base = self.offset(self.resource_rva)

    def offset(self, rva: int) -> int:
        for virtual_size, address, raw_size, raw_pointer in self.sections:
            if address <= rva < address + max(virtual_size, raw_size):
                return raw_pointer + rva - address
        raise CatalogError(f"RVA {rva:#x} вне секций PE.")

    def entries(self, offset: int, seen: set[int]):
        if offset in seen or len(seen) > 100000:
            raise CatalogError("Зацикленный каталог ресурсов PE.")
        seen.add(offset)
        named, numbered = struct.unpack_from("<HH", self.data, self.base + offset + 12)
        for index in range(named + numbered):
            name, target = struct.unpack_from("<II", self.data, self.base + offset + 16 + 8 * index)
            yield (None if name & 0x80000000 else name), target

    def resources(self, wanted: int):
        """(name id, language, bytes) of every resource of a numeric type."""
        seen: set[int] = set()
        try:
            for type_id, type_target in self.entries(0, seen):
                if type_id != wanted or not type_target & 0x80000000:
                    continue
                for name_id, name_target in self.entries(type_target & 0x7FFFFFFF, seen):
                    if name_id is None or not name_target & 0x80000000:
                        continue
                    for language, data_target in self.entries(name_target & 0x7FFFFFFF, seen):
                        if data_target & 0x80000000:
                            continue
                        rva, size = struct.unpack_from("<II", self.data, self.base + data_target)
                        start = self.offset(rva)
                        if start + size > len(self.data):
                            raise CatalogError("Ресурс PE выходит за пределы файла.")
                        yield name_id, language, self.data[start:start + size]
        except struct.error as error:
            raise CatalogError(f"Повреждён каталог ресурсов PE: {error}") from error


def string_table(data: bytes) -> list[tuple[int, int, str]]:
    """(string id, language, text) of every non-empty RT_STRING entry."""
    result = []
    for block, language, payload in _Pe(data).resources(RT_STRING):
        position = 0
        for index in range(16):
            if position + 2 > len(payload):
                raise CatalogError(f"Обрезан блок строк {block}.")
            length = struct.unpack_from("<H", payload, position)[0]
            position += 2
            text = payload[position:position + 2 * length]
            if len(text) != 2 * length:
                raise CatalogError(f"Обрезана строка в блоке {block}.")
            position += 2 * length
            if length:
                result.append(((block - 1) * 16 + index, language, text.decode("utf-16-le")))
    return sorted(result)


def file_version(data: bytes) -> str | None:
    for _name, _language, payload in _Pe(data).resources(RT_VERSION):
        index = payload.find(struct.pack("<I", 0xFEEF04BD))
        if index >= 0 and index + 16 <= len(payload):
            high, low = struct.unpack_from("<II", payload, index + 8)
            return f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}"
    return None


def name_pairs(data: bytes) -> list[dict]:
    pairs = []
    for string_id, language, text in string_table(data):
        match = _PAIR.fullmatch(text)
        if match and _CYRILLIC.search(match.group(2)):
            pairs.append({"id": string_id, "lang": language, "en": match.group(1), "ru": match.group(2)})
    return pairs


def reserved_block(data: bytes) -> dict:
    """The contiguous string block that starts with the keyword table (If,Если).

    In 1crcrus.dll 7.70.027 it holds the keywords and the compiler's built-in
    functions; empty string ids bound it on both sides.
    """
    table = {string_id: text for string_id, _language, text in string_table(data)}
    anchor = next((string_id for string_id, text in sorted(table.items())
                   if (match := _PAIR.fullmatch(text)) and match.groups() == ("If", "Если")), None)
    if anchor is None:
        raise CatalogError("В ресурсах нет таблицы ключевых слов (If,Если).")
    first = last = anchor
    while first - 1 in table and _PAIR.fullmatch(table[first - 1]):
        first -= 1
    while last + 1 in table and _PAIR.fullmatch(table[last + 1]):
        last += 1
    names = [part for string_id in range(first, last + 1)
             for part in _PAIR.fullmatch(table[string_id]).groups()]
    return {"first_id": first, "last_id": last, "names": names}


def compiler_messages(data: bytes) -> list[dict]:
    """Messages of the language processor: the compile block, then the runtime block.

    In 1crcrus.dll 7.70.027 the compile block starts at "Ошибок не обнаружено"
    (1440), the runtime block at the integer index message (1600), and both end
    before the keyword table (1640). Text templates with % are not messages.
    """
    table = {string_id: text for string_id, _language, text in string_table(data)}
    anchors = {}
    for name, text in (("compile", _COMPILE_ANCHOR), ("runtime", _RUNTIME_ANCHOR)):
        found = [string_id for string_id, value in table.items() if value == text]
        if len(found) != 1:
            raise CatalogError(f"В ресурсах нет единственной опорной строки сообщений «{text}».")
        anchors[name] = found[0]
    end = reserved_block(data)["first_id"]
    if not anchors["compile"] < anchors["runtime"] < end:
        raise CatalogError("Раскладка сообщений компилятора в ресурсах не распознана.")
    messages = []
    for block, first, last in (("compile", anchors["compile"], anchors["runtime"]),
                               ("runtime", anchors["runtime"], end)):
        messages += [{"id": string_id, "block": block, "text": table[string_id]}
                     for string_id in range(first, last)
                     if string_id in table and "%" not in table[string_id]]
    return messages


def _source(path: Path, data: bytes) -> dict:
    return {"name": path.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build_catalog(als_path: Path, strings_path: Path) -> dict:
    als, strings = als_path.read_bytes(), strings_path.read_bytes()
    items = parse_als(als.decode("cp1251"))
    version = file_version(strings)
    platform = None
    if version and re.fullmatch(r"\d+\.\d+\.0\.\d+", version):
        major, minor, _zero, build = version.split(".")
        platform = f"{major}.{minor}.{int(build):03d}"
    pairs = name_pairs(strings)
    if not pairs:
        raise CatalogError("В ресурсах не найдено пар имён English,Русское.")
    messages = compiler_messages(strings)
    return {"schema_version": SCHEMA_VERSION, "tool": "harness77", "scope": "platform_catalog",
            "platform_version": platform, "strings_file_version": version,
            "sources": [_source(als_path, als), _source(strings_path, strings)],
            "limitations": LIMITATIONS,
            "counts": {"items": len(items), "pairs": len(pairs), "messages": len(messages)},
            "reserved": reserved_block(strings),
            "items": items, "pairs": pairs, "messages": messages}


def dumps(catalog: dict) -> str:
    """Stable text: one item or pair per line, so diffs stay readable."""
    lines = ["{"]
    keys = list(catalog)
    for position, key in enumerate(keys):
        value = catalog[key]
        tail = "," if position < len(keys) - 1 else ""
        if key in ("items", "pairs", "messages"):
            rows = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in value]
            lines.append(f' "{key}": [')
            lines.extend("  " + row + ("," if n < len(rows) - 1 else "") for n, row in enumerate(rows))
            lines.append(" ]" + tail)
        else:
            lines.append(f" {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{tail}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def load_packaged() -> dict:
    return json.loads(files("harness77").joinpath(PACKAGED).read_text(encoding="utf-8"))


def _write_new(path: Path, text: str) -> None:
    """Publish a new file only: an existing path (or link) is never replaced."""
    temporary = path.with_name(path.name + ".tmp-" + os.urandom(6).hex())
    with open(temporary, "x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="harness77 catalog", allow_abbrev=False,
                                     description="Каталог имён 1С 7.7 из файлов установленной платформы")
    parser.add_argument("--als", required=True, type=Path, help="BIN\\1cv7Lang.als")
    parser.add_argument("--strings", required=True, type=Path, help="BIN\\1crcrus.dll")
    parser.add_argument("--output", required=True, type=Path, help="Новый файл JSON (не перезаписывается)")
    args = parser.parse_args(argv)
    try:
        if os.path.lexists(args.output):
            raise CatalogError(f"Выходной файл уже существует: {args.output}")
        if not args.output.parent.is_dir():
            raise CatalogError(f"Каталог результата не существует: {args.output.parent}")
        catalog = build_catalog(args.als, args.strings)
        text = dumps(catalog)
        _write_new(args.output, text)
    except (OSError, UnicodeError, CatalogError) as error:
        print(json.dumps({"schema_version": 1, "tool": "harness77", "operation": "catalog",
                          "status": "blocked", "error": f"{type(error).__name__}: {error}"},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"schema_version": 1, "tool": "harness77", "operation": "catalog", "status": "passed",
                      "output": {"path": str(args.output), "size": len(text.encode("utf-8")),
                                 "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
                      "platform_version": catalog["platform_version"], "counts": catalog["counts"],
                      "sources": catalog["sources"]}, ensure_ascii=False, indent=2))
    return 0
