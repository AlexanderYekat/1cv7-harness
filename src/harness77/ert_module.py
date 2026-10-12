#!/usr/bin/env python3
"""
Extract and replace source text of a 1C:Enterprise 7.7 external report (*.ert).

No third-party packages are required.

Examples:
    python ert_module.py extract hello.ert module.txt
    python ert_module.py replace hello.ert module.txt hello_new.ert
    python ert_module.py show hello.ert

Диалог формы (поток "Dialog Stream"):
    python ert_module.py dialog-controls hello.ert
    python ert_module.py dialog-extract hello.ert dialog.txt
    python ert_module.py dialog-replace hello.ert dialog.txt hello_new.ert

Пакетный перенос между каталогами (отдельные скрипты, чтобы не перепутать направление):
    python push_txt_to_ert.py --dry-run   # 1cv77/*.txt -> 1cv77-extforms/*.ert
    python pull_ert_to_txt.py --dry-run   # 1cv77-extforms/*.ert -> 1cv77/*.txt
    python sync_modules.py --dry-run      # авто по версии (куда новее)

The module text is stored in the OLE/CFB stream "MD Programm text" as
raw DEFLATE data encoded in Windows-1251.

The form layout is stored uncompressed in the stream "Dialog Stream": one
Windows-1251 string with a length prefix (see decode_dialog). Changing the
text without recalculating the prefix produces a broken form.
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF
MODULE_STREAM = "MD Programm text"
DIALOG_STREAM = "Dialog Stream"


class ErtError(Exception):
    """Readable error for invalid/unsupported ERT files."""


@dataclass
class DirectoryEntry:
    entry_id: int
    name: str
    object_type: int
    start_sector: int
    size: int
    raw: bytearray


class CompoundFile:
    """Small CFB/OLE reader and writer sufficient for 1C 7.7 ERT files."""

    def __init__(self, data: bytes):
        if len(data) < 512 or data[:8] != SIGNATURE:
            raise ErtError("Файл не является OLE/CFB-контейнером 1С 7.7")

        self.data = data
        self.header = bytearray(data[:512])
        self.major_version = self._u16(0x1A)
        self.byte_order = self._u16(0x1C)
        self.sector_shift = self._u16(0x1E)
        self.mini_sector_shift = self._u16(0x20)

        if self.major_version != 3 or self.byte_order != 0xFFFE:
            raise ErtError(
                f"Поддерживается CFB v3 (512-байтовые сектора), найден CFB v{self.major_version}"
            )

        self.sector_size = 1 << self.sector_shift
        self.mini_sector_size = 1 << self.mini_sector_shift
        self.mini_stream_cutoff = self._u32(0x38)
        if self.sector_size != 512 or self.mini_sector_size != 64:
            raise ErtError("Неожиданный размер сектора OLE-контейнера")

        self.fat = self._read_fat()
        self.directory_entries = self._read_directory()
        if not self.directory_entries or self.directory_entries[0].object_type != 5:
            raise ErtError("В OLE-контейнере отсутствует Root Entry")

        self.mini_fat = self._read_mini_fat()
        root = self.directory_entries[0]
        self.mini_stream = self._read_regular_stream(root.start_sector, root.size)

    def _u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def _u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]

    def _sector(self, sector_id: int) -> bytes:
        start = (sector_id + 1) * self.sector_size
        end = start + self.sector_size
        if start < self.sector_size or end > len(self.data):
            raise ErtError(f"Некорректная ссылка на сектор {sector_id}")
        return self.data[start:end]

    @staticmethod
    def _chain(start: int, table: list[int], label: str) -> list[int]:
        if start in (FREESECT, ENDOFCHAIN):
            return []
        result: list[int] = []
        seen: set[int] = set()
        current = start
        while current not in (FREESECT, ENDOFCHAIN):
            if current in seen:
                raise ErtError(f"Цикл в цепочке {label}")
            if current >= len(table):
                raise ErtError(f"Некорректная цепочка {label}: сектор {current}")
            seen.add(current)
            result.append(current)
            current = table[current]
        return result

    def _read_fat(self) -> list[int]:
        number_of_fat_sectors = self._u32(0x2C)
        first_difat_sector = self._u32(0x44)
        number_of_difat_sectors = self._u32(0x48)

        difat = list(struct.unpack_from("<109I", self.data, 0x4C))
        fat_sector_ids = [x for x in difat if x != FREESECT]

        current = first_difat_sector
        entries_per_difat = self.sector_size // 4 - 1
        for _ in range(number_of_difat_sectors):
            sector = self._sector(current)
            values = struct.unpack("<%dI" % (entries_per_difat + 1), sector)
            fat_sector_ids.extend(x for x in values[:-1] if x != FREESECT)
            current = values[-1]

        fat_sector_ids = fat_sector_ids[:number_of_fat_sectors]
        if len(fat_sector_ids) != number_of_fat_sectors:
            raise ErtError("Повреждена таблица DIFAT/FAT")

        fat: list[int] = []
        entries_per_fat = self.sector_size // 4
        for sector_id in fat_sector_ids:
            fat.extend(struct.unpack("<%dI" % entries_per_fat, self._sector(sector_id)))
        return fat

    def _read_regular_stream(self, start_sector: int, size: int | None = None) -> bytes:
        chunks = [self._sector(x) for x in self._chain(start_sector, self.fat, "FAT")]
        result = b"".join(chunks)
        return result if size is None else result[:size]

    def _read_directory(self) -> list[DirectoryEntry]:
        first_directory_sector = self._u32(0x30)
        raw_directory = self._read_regular_stream(first_directory_sector)
        result: list[DirectoryEntry] = []

        for offset in range(0, len(raw_directory), 128):
            raw = bytearray(raw_directory[offset : offset + 128])
            if len(raw) < 128:
                break
            name_length = struct.unpack_from("<H", raw, 64)[0]
            if 2 <= name_length <= 64:
                name = bytes(raw[: name_length - 2]).decode("utf-16le", errors="replace")
            else:
                name = ""
            result.append(
                DirectoryEntry(
                    entry_id=offset // 128,
                    name=name,
                    object_type=raw[66],
                    start_sector=struct.unpack_from("<I", raw, 116)[0],
                    size=struct.unpack_from("<Q", raw, 120)[0],
                    raw=raw,
                )
            )
        return result

    def _read_mini_fat(self) -> list[int]:
        first_mini_fat_sector = self._u32(0x3C)
        number_of_mini_fat_sectors = self._u32(0x40)
        if number_of_mini_fat_sectors == 0:
            return []

        sector_ids = self._chain(first_mini_fat_sector, self.fat, "MiniFAT")
        sector_ids = sector_ids[:number_of_mini_fat_sectors]
        result: list[int] = []
        entries_per_sector = self.sector_size // 4
        for sector_id in sector_ids:
            result.extend(struct.unpack("<%dI" % entries_per_sector, self._sector(sector_id)))
        return result

    def find_stream(self, name: str) -> DirectoryEntry:
        matches = [x for x in self.directory_entries if x.object_type == 2 and x.name == name]
        if not matches:
            raise ErtError(f'Поток "{name}" не найден')
        if len(matches) > 1:
            raise ErtError(f'Найдено несколько потоков "{name}"')
        return matches[0]

    def read_stream(self, entry: DirectoryEntry) -> bytes:
        if entry.object_type != 2:
            raise ErtError(f'"{entry.name}" не является потоком')
        if entry.size == 0:
            return b""
        if entry.size < self.mini_stream_cutoff:
            mini_ids = self._chain(entry.start_sector, self.mini_fat, "mini stream")
            chunks = [
                self.mini_stream[x * self.mini_sector_size : (x + 1) * self.mini_sector_size]
                for x in mini_ids
            ]
            return b"".join(chunks)[: entry.size]
        return self._read_regular_stream(entry.start_sector, entry.size)

    def all_stream_data(self) -> dict[int, bytes]:
        return {
            entry.entry_id: self.read_stream(entry)
            for entry in self.directory_entries
            if entry.object_type == 2
        }

    def rebuild(self, replacements: dict[int, bytes]) -> bytes:
        """Rebuild the whole CFB container, allowing stream sizes to change."""
        stream_data = self.all_stream_data()
        stream_data.update(replacements)

        sector_size = self.sector_size
        mini_sector_size = self.mini_sector_size
        entries_per_fat_sector = sector_size // 4
        entries_per_difat_sector = entries_per_fat_sector - 1

        small_stream_ids = [
            e.entry_id
            for e in self.directory_entries
            if e.object_type == 2 and len(stream_data[e.entry_id]) < self.mini_stream_cutoff
        ]
        large_stream_ids = [
            e.entry_id
            for e in self.directory_entries
            if e.object_type == 2 and len(stream_data[e.entry_id]) >= self.mini_stream_cutoff
        ]

        mini_fat_values: list[int] = []
        mini_stream_parts: list[bytes] = []
        stream_start: dict[int, int] = {}

        for entry_id in small_stream_ids:
            payload = stream_data[entry_id]
            if not payload:
                stream_start[entry_id] = ENDOFCHAIN
                continue
            count = math.ceil(len(payload) / mini_sector_size)
            first = len(mini_fat_values)
            stream_start[entry_id] = first
            for index in range(count):
                mini_fat_values.append(first + index + 1 if index + 1 < count else ENDOFCHAIN)
                part = payload[index * mini_sector_size : (index + 1) * mini_sector_size]
                mini_stream_parts.append(part.ljust(mini_sector_size, b"\x00"))

        mini_stream_payload = b"".join(mini_stream_parts)

        directory_size = max(1, math.ceil(len(self.directory_entries) * 128 / sector_size)) * sector_size
        mini_fat_sector_count = (
            math.ceil(len(mini_fat_values) * 4 / sector_size) if mini_fat_values else 0
        )

        large_sector_counts = {
            entry_id: math.ceil(len(stream_data[entry_id]) / sector_size)
            for entry_id in large_stream_ids
        }
        root_sector_count = (
            math.ceil(len(mini_stream_payload) / sector_size) if mini_stream_payload else 0
        )
        directory_sector_count = directory_size // sector_size

        base_sector_count = (
            sum(large_sector_counts.values())
            + root_sector_count
            + directory_sector_count
            + mini_fat_sector_count
        )

        fat_sector_count = 0
        difat_sector_count = 0
        while True:
            total = base_sector_count + fat_sector_count + difat_sector_count
            new_fat = math.ceil(total / entries_per_fat_sector)
            new_difat = (
                math.ceil(max(new_fat - 109, 0) / entries_per_difat_sector)
                if new_fat > 109
                else 0
            )
            if (new_fat, new_difat) == (fat_sector_count, difat_sector_count):
                break
            fat_sector_count, difat_sector_count = new_fat, new_difat

        sectors: list[bytearray] = []
        chains: list[list[int]] = []

        def allocate(payload: bytes, count: int) -> list[int]:
            if count == 0:
                return []
            ids = list(range(len(sectors), len(sectors) + count))
            for index in range(count):
                part = payload[index * sector_size : (index + 1) * sector_size]
                sectors.append(bytearray(part.ljust(sector_size, b"\x00")))
            chains.append(ids)
            return ids

        for entry_id in large_stream_ids:
            ids = allocate(stream_data[entry_id], large_sector_counts[entry_id])
            stream_start[entry_id] = ids[0] if ids else ENDOFCHAIN

        root_chain = allocate(mini_stream_payload, root_sector_count)

        # Directory entries are patched after all starts are known.
        directory_placeholder_index = len(sectors)
        directory_chain = allocate(b"\x00" * directory_size, directory_sector_count)

        mini_fat_bytes = b""
        if mini_fat_sector_count:
            capacity = mini_fat_sector_count * entries_per_fat_sector
            padded = mini_fat_values + [FREESECT] * (capacity - len(mini_fat_values))
            mini_fat_bytes = struct.pack("<%dI" % capacity, *padded)
        mini_fat_chain = allocate(mini_fat_bytes, mini_fat_sector_count)

        difat_sector_ids = list(
            range(len(sectors), len(sectors) + difat_sector_count)
        )
        for _ in difat_sector_ids:
            sectors.append(bytearray(sector_size))

        fat_sector_ids = list(range(len(sectors), len(sectors) + fat_sector_count))
        for _ in fat_sector_ids:
            sectors.append(bytearray(sector_size))

        total_sector_count = len(sectors)
        fat_capacity = fat_sector_count * entries_per_fat_sector
        fat_values = [FREESECT] * fat_capacity

        def mark_chain(ids: Iterable[int]) -> None:
            ids = list(ids)
            for index, sector_id in enumerate(ids):
                fat_values[sector_id] = ids[index + 1] if index + 1 < len(ids) else ENDOFCHAIN

        for chain_ids in chains:
            mark_chain(chain_ids)
        for sector_id in difat_sector_ids:
            fat_values[sector_id] = DIFSECT
        for sector_id in fat_sector_ids:
            fat_values[sector_id] = FATSECT

        if total_sector_count > fat_capacity:
            raise ErtError("Внутренняя ошибка расчёта FAT")

        # Patch directory entries while preserving names, tree links, CLSIDs and timestamps.
        directory_bytes = bytearray(directory_size)
        for entry in self.directory_entries:
            raw = bytearray(entry.raw)
            if entry.entry_id == 0:
                root_start = root_chain[0] if root_chain else ENDOFCHAIN
                struct.pack_into("<I", raw, 116, root_start)
                struct.pack_into("<Q", raw, 120, len(mini_stream_payload))
            elif entry.object_type == 2:
                struct.pack_into("<I", raw, 116, stream_start[entry.entry_id])
                struct.pack_into("<Q", raw, 120, len(stream_data[entry.entry_id]))
            start = entry.entry_id * 128
            directory_bytes[start : start + 128] = raw

        for index, sector_id in enumerate(directory_chain):
            part = directory_bytes[index * sector_size : (index + 1) * sector_size]
            sectors[sector_id][:] = part

        # DIFAT sectors contain additional FAT sector IDs and a pointer to the next DIFAT sector.
        remaining_fat_ids = fat_sector_ids[109:]
        for index, sector_id in enumerate(difat_sector_ids):
            chunk = remaining_fat_ids[
                index * entries_per_difat_sector : (index + 1) * entries_per_difat_sector
            ]
            values = chunk + [FREESECT] * (entries_per_difat_sector - len(chunk))
            next_sector = (
                difat_sector_ids[index + 1]
                if index + 1 < len(difat_sector_ids)
                else ENDOFCHAIN
            )
            values.append(next_sector)
            sectors[sector_id][:] = struct.pack(
                "<%dI" % entries_per_fat_sector, *values
            )

        for index, sector_id in enumerate(fat_sector_ids):
            chunk = fat_values[
                index * entries_per_fat_sector : (index + 1) * entries_per_fat_sector
            ]
            sectors[sector_id][:] = struct.pack(
                "<%dI" % entries_per_fat_sector, *chunk
            )

        header = bytearray(self.header)
        struct.pack_into("<I", header, 0x28, 0)  # directory sectors for CFB v3
        struct.pack_into("<I", header, 0x2C, fat_sector_count)
        struct.pack_into("<I", header, 0x30, directory_chain[0])
        struct.pack_into("<I", header, 0x34, 0)  # transaction signature
        struct.pack_into(
            "<I", header, 0x3C, mini_fat_chain[0] if mini_fat_chain else ENDOFCHAIN
        )
        struct.pack_into("<I", header, 0x40, mini_fat_sector_count)
        struct.pack_into(
            "<I", header, 0x44, difat_sector_ids[0] if difat_sector_ids else ENDOFCHAIN
        )
        struct.pack_into("<I", header, 0x48, difat_sector_count)

        header_difat = fat_sector_ids[:109] + [FREESECT] * max(0, 109 - len(fat_sector_ids))
        struct.pack_into("<109I", header, 0x4C, *header_difat[:109])

        return bytes(header) + b"".join(bytes(x) for x in sectors)


def decompress_module(payload: bytes) -> bytes:
    try:
        return zlib.decompress(payload, wbits=-15)
    except zlib.error as exc:
        raise ErtError(f"Не удалось распаковать поток {MODULE_STREAM}: {exc}") from exc


def compress_module(source: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    return compressor.compress(source) + compressor.flush()


def load_compound(path: Path) -> CompoundFile:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ErtError(f"Не удалось прочитать {path}: {exc}") from exc
    return CompoundFile(data)


def load_ert(path: Path) -> tuple[CompoundFile, DirectoryEntry]:
    compound = load_compound(path)
    return compound, compound.find_stream(MODULE_STREAM)


def extract_text(ert_path: Path) -> str:
    compound, entry = load_ert(ert_path)
    module_bytes = decompress_module(compound.read_stream(entry))
    try:
        return module_bytes.decode("cp1251")
    except UnicodeDecodeError as exc:
        raise ErtError("Текст модуля не декодируется как Windows-1251") from exc


def decode_source_bytes(raw: bytes, path: Path | None = None) -> str:
    """Decode TXT exchange source.

    UTF-8 is the default. UTF-16 is accepted only with BOM: CP1251 is a
    single-byte encoding and otherwise swallows UTF-16 (NUL between letters).
    """
    encodings: list[str] = []
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.extend(["utf-8-sig", "cp1251"])

    seen: set[str] = set()
    for encoding in encodings:
        if encoding in seen:
            continue
        seen.add(encoding)
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            continue
        if encoding == "utf-16" and path is not None:
            print(
                f"Замечание: {path.name}: исходник в UTF-16, для обмена лучше UTF-8",
                file=sys.stderr,
            )
        return text

    where = f" {path}" if path else ""
    raise ErtError(
        f"Файл{where} должен быть в UTF-8, UTF-16 (с BOM) или Windows-1251"
    )


def read_source_file(path: Path) -> str:
    return decode_source_bytes(path.read_bytes(), path)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


# Символы, которых нет в Windows-1251. 1С 7.7 иначе отказывается писать модуль.
# Значения сами должны кодироваться в cp1251.
CP1251_FALLBACKS: dict[str, str] = {
    "\u2190": "<-",  # ←
    "\u2192": "->",  # →
    "\u2194": "<->",  # ↔
    "\u21d0": "<=",  # ⇐
    "\u21d2": "=>",  # ⇒
    "\u21d4": "<=>",  # ⇔
    "\u2191": "^",  # ↑
    "\u2193": "v",  # ↓
    "\u2794": "->",  # ➔
    "\u279c": "->",  # ➜
    "\u27a1": "->",  # ➡
    "\u2026": "...",  # …
    "\u2013": "-",  # –
    "\u2014": "-",  # —
    "\u2015": "-",  # ―
    "\u2212": "-",  # −
    "\u2010": "-",  # ‐
    "\u2011": "-",  # ‑
    "\u2018": "'",  # ‘
    "\u2019": "'",  # ’
    "\u201a": ",",  # ‚
    "\u201c": '"',  # “
    "\u201d": '"',  # ”
    "\u201e": '"',  # „
    "\u2022": "*",  # •
    "\u25cf": "*",  # ●
    "\u2260": "<>",  # ≠
    "\u2264": "<=",  # ≤
    "\u2265": ">=",  # ≥
    "\u2248": "~",  # ≈
    "\u200b": "",  # zero-width space
    "\u200c": "",
    "\u200d": "",
    "\u2060": "",
    "\ufeff": "",
    "\u202f": " ",
    "\u2007": " ",
    "\u2008": " ",
    "\u2009": " ",
    "\u200a": " ",
}


def sanitize_for_cp1251(text: str) -> tuple[str, list[tuple[str, str, int]]]:
    """Заменить символы вне Windows-1251 на допустимые аналоги."""
    notes: list[tuple[str, str, int]] = []
    for src, dst in CP1251_FALLBACKS.items():
        count = text.count(src)
        if count:
            text = text.replace(src, dst)
            notes.append((src, dst, count))
    return text, notes


def _format_cp1251_notes(notes: list[tuple[str, str, int]]) -> str:
    parts: list[str] = []
    for src, dst, count in notes:
        src_label = " ".join(f"U+{ord(c):04X}" for c in src)
        dst_label = dst.encode("ascii", "backslashreplace").decode("ascii") or '""'
        extra = f" x{count}" if count > 1 else ""
        parts.append(f"{src_label}->{dst_label}{extra}")
    return ", ".join(parts)


def encode_cp1251(text: str) -> tuple[bytes, list[tuple[str, str, int]]]:
    sanitized, notes = sanitize_for_cp1251(text)
    try:
        return sanitized.encode("cp1251"), notes
    except UnicodeEncodeError as exc:
        bad = sanitized[exc.start : exc.end]
        line = sanitized.count("\n", 0, exc.start) + 1
        col = exc.start - (sanitized.rfind("\n", 0, exc.start) + 1) + 1
        code = f"U+{ord(bad[0]):04X}" if bad else "U+????"
        raise ErtError(
            f"Символ {bad!r} ({code}) в строке {line}:{col} "
            f"нельзя записать в модуль 1С 7.7 (нужна Windows-1251)"
        ) from exc


def replace_text(ert_path: Path, source_path: Path, output_path: Path) -> None:
    compound, entry = load_ert(ert_path)
    text = normalize_newlines(read_source_file(source_path))
    source_bytes, notes = encode_cp1251(text)
    if notes:
        print(
            f"Замечание: {source_path.name}: символы вне Windows-1251 заменены "
            f"({_format_cp1251_notes(notes)})",
            file=sys.stderr,
        )

    if b"\x00" in source_bytes:
        raise ErtError(
            f"{source_path.name}: текст модуля содержит нулевые байты "
            "(похоже, исходник прочитан в неверной кодировке)"
        )

    compressed = compress_module(source_bytes)
    rebuilt = compound.rebuild({entry.entry_id: compressed})

    try:
        output_path.write_bytes(rebuilt)
    except OSError as exc:
        raise ErtError(f"Не удалось записать {output_path}: {exc}") from exc

    # Immediate structural and content verification.
    check = CompoundFile(rebuilt)
    check_entry = check.find_stream(MODULE_STREAM)
    check_source = decompress_module(check.read_stream(check_entry))
    if check_source != source_bytes:
        raise ErtError("Проверка созданного ERT не пройдена: текст после записи отличается")


# Dialog Stream — строка с префиксом длины, как CString в MFC CArchive:
# длина < 0xFF — один байт; < 0xFFFE — 0xFF и uint16; иначе 0xFF, 0xFFFF и uint32.
# В формах 1С 7.7 наблюдалась только вторая форма (0xFF + uint16).
_PREFIX_KINDS = {1: "1 байт", 3: "0xFF + uint16", 7: "0xFF 0xFFFF + uint32"}


def _dialog_length(payload: bytes) -> tuple[int, int]:
    """Вернуть (длина текста, размер префикса) потока Dialog Stream."""
    if not payload:
        raise ErtError(f"Поток {DIALOG_STREAM} пуст")
    if payload[0] < 0xFF:
        return payload[0], 1
    if len(payload) < 3:
        raise ErtError(f"Поток {DIALOG_STREAM} оборван в заголовке длины")
    length = struct.unpack_from("<H", payload, 1)[0]
    if length == 0xFFFE:
        raise ErtError(f"Поток {DIALOG_STREAM} в Unicode не поддерживается")
    if length < 0xFFFF:
        return length, 3
    if len(payload) < 7:
        raise ErtError(f"Поток {DIALOG_STREAM} оборван в заголовке длины")
    return struct.unpack_from("<I", payload, 3)[0], 7


def decode_dialog(payload: bytes) -> str:
    """Текст диалога из потока Dialog Stream; заголовок длины обязан совпадать с данными."""
    length, offset = _dialog_length(payload)
    body = payload[offset:]
    if len(body) != length:
        raise ErtError(
            f"Длина диалога в заголовке {length} байт, фактически {len(body)}: "
            "текст менялся без пересчёта длины"
        )
    try:
        return body.decode("cp1251")
    except UnicodeDecodeError as exc:
        raise ErtError("Текст диалога не декодируется как Windows-1251") from exc


def encode_dialog(text: str) -> bytes:
    """Поток Dialog Stream для текста в Windows-1251, с пересчитанной длиной."""
    try:
        body = text.encode("cp1251")
    except UnicodeEncodeError as exc:
        raise ErtError(
            f"Символ {text[exc.start:exc.end]!r} нельзя записать в диалог 1С 7.7 "
            "(нужна Windows-1251)"
        ) from exc
    length = len(body)
    if length < 0xFF:
        prefix = bytes([length])
    elif length < 0xFFFE:
        prefix = b"\xff" + struct.pack("<H", length)
    else:
        prefix = b"\xff\xff\xff" + struct.pack("<I", length)
    return prefix + body


def _dialog_error(text: str, pos: int, message: str) -> ErtError:
    line = text.count("\n", 0, pos) + 1
    return ErtError(f"Диалог, строка {line}: {message}")


def _skip_dialog_space(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t\r\n":
        pos += 1
    return pos


def _parse_dialog_value(text: str, pos: int) -> tuple[str | list, int]:
    if pos >= len(text):
        raise _dialog_error(text, pos, "текст оборван")
    if text[pos] == '"':
        parts: list[str] = []
        pos += 1
        while True:
            end = text.find('"', pos)
            if end < 0:
                raise _dialog_error(text, pos, "незакрытая строка")
            parts.append(text[pos:end])
            if text.startswith('""', end):
                parts.append('"')
                pos = end + 2
                continue
            return "".join(parts), end + 1
    if text[pos] != "{":
        raise _dialog_error(text, pos, f"ожидается '{{' или '\"', найдено {text[pos]!r}")
    items: list[str | list] = []
    pos = _skip_dialog_space(text, pos + 1)
    if pos < len(text) and text[pos] == "}":
        return items, pos + 1
    while True:
        value, pos = _parse_dialog_value(text, pos)
        items.append(value)
        pos = _skip_dialog_space(text, pos)
        if pos < len(text) and text[pos] == ",":
            pos = _skip_dialog_space(text, pos + 1)
            continue
        if pos < len(text) and text[pos] == "}":
            return items, pos + 1
        found = repr(text[pos]) if pos < len(text) else "конец текста"
        raise _dialog_error(text, pos, f"ожидается ',' или '}}', найдено {found}")


def parse_dialog(text: str) -> list:
    """Разобрать текст диалога: вложенные списки {…} из строк в кавычках ("" внутри строки)."""
    value, pos = _parse_dialog_value(text, _skip_dialog_space(text, 0))
    if not isinstance(value, list):
        raise _dialog_error(text, 0, "диалог должен начинаться с '{'")
    pos = _skip_dialog_space(text, pos)
    if pos != len(text):
        raise _dialog_error(text, pos, "лишний текст после закрывающей '}'")
    return value


@dataclass
class DialogControl:
    caption: str
    kind: str
    control_id: str
    formula: str
    identifier: str


def dialog_controls(text: str) -> list[DialogControl]:
    """Элементы формы из раздела {"Controls", …}.

    Номера полей записи (с нуля) взяты из форм 1С 7.7: 0 — подпись, 1 — класс
    (BUTTON, 1CEDIT, BMASKED, STATIC…), 9 — числовой ID, 11 — формула, 12 — идентификатор.
    """
    root = parse_dialog(text)
    if not root or root[0] != "Dialogs":
        raise ErtError('Неизвестная структура диалога: нет заголовка "Dialogs"')
    result: list[DialogControl] = []
    for section in root[1:]:
        if not isinstance(section, list) or not section or section[0] != "Controls":
            continue
        for number, record in enumerate(section[1:], start=1):
            if not isinstance(record, list) or len(record) < 13 or not all(
                isinstance(x, str) for x in record[:13]
            ):
                raise ErtError(f"Неизвестная структура элемента формы № {number}")
            result.append(DialogControl(record[0], record[1], record[9], record[11], record[12]))
    return result


def extract_dialog(ert_path: Path) -> str:
    compound = load_compound(ert_path)
    return decode_dialog(compound.read_stream(compound.find_stream(DIALOG_STREAM)))


def _verify_rebuilt(compound: CompoundFile, rebuilt: bytes, replacements: dict[int, bytes]) -> None:
    """Те же записи каталога; изменились только потоки из replacements."""
    check = CompoundFile(rebuilt)
    before = [(e.name, e.object_type) for e in compound.directory_entries]
    after = [(e.name, e.object_type) for e in check.directory_entries]
    if before != after:
        raise ErtError("Проверка созданного ERT не пройдена: изменился состав потоков")
    for entry in compound.directory_entries:
        if entry.object_type != 2:
            continue
        expected = replacements.get(entry.entry_id)
        if expected is None:
            expected = compound.read_stream(entry)
        if check.read_stream(check.directory_entries[entry.entry_id]) != expected:
            raise ErtError(f'Проверка созданного ERT не пройдена: поток "{entry.name}" отличается')


def replace_dialog_text(ert_path: Path, text: str, output_path: Path) -> None:
    """Заменить весь текст диалога формы и пересчитать заголовок длины.

    Новый текст сначала разбирается; файл пишется только после сверки потоков.
    Смена формы заголовка длины (порог 0xFF или 0xFFFE байт) отклоняется:
    в 1С 7.7 она не проверялась.
    """
    compound = load_compound(ert_path)
    entry = compound.find_stream(DIALOG_STREAM)
    old_payload = compound.read_stream(entry)
    decode_dialog(old_payload)

    text, notes = sanitize_for_cp1251(normalize_newlines(text))
    if notes:
        print(
            f"Замечание: диалог: символы вне Windows-1251 заменены "
            f"({_format_cp1251_notes(notes)})",
            file=sys.stderr,
        )
    parse_dialog(text)
    payload = encode_dialog(text)
    old_prefix = _dialog_length(old_payload)[1]
    new_prefix = _dialog_length(payload)[1]
    if old_prefix != new_prefix:
        raise ErtError(
            f"Заголовок длины диалога сменил бы форму ({_PREFIX_KINDS[old_prefix]} -> "
            f"{_PREFIX_KINDS[new_prefix]}); такой случай в 1С 7.7 не проверен"
        )

    rebuilt = compound.rebuild({entry.entry_id: payload})
    _verify_rebuilt(compound, rebuilt, {entry.entry_id: payload})
    try:
        output_path.write_bytes(rebuilt)
    except OSError as exc:
        raise ErtError(f"Не удалось записать {output_path}: {exc}") from exc


def replace_dialog_strings(
    ert_path: Path, replacements: Iterable[tuple[str, str]], output_path: Path
) -> None:
    """Заменить фрагменты диалога по порядку; каждый должен встречаться ровно один раз.

    Пример — переименовать кнопку и сменить её формулу:
    [('"&Набор Э0.2"', '"&Набор Э0.3"'), ('"ВыгрузкаЭ02()"', '"ВыгрузкаЭ03()"')].
    """
    text = extract_dialog(ert_path)
    for old, new in replacements:
        count = text.count(old)
        if count != 1:
            raise ErtError(f"Фрагмент {old!r} встречается в диалоге {count} раз, нужен ровно 1")
        text = text.replace(old, new)
    replace_dialog_text(ert_path, text, output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Извлечение и замена текста модуля в *.ert 1С:Предприятия 7.7"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="показать текст модуля в консоли")
    show.add_argument("ert", type=Path)

    extract = subparsers.add_parser("extract", help="извлечь текст модуля в UTF-8")
    extract.add_argument("ert", type=Path)
    extract.add_argument("text", type=Path)

    replace = subparsers.add_parser("replace", help="заменить текст модуля и создать новый ERT")
    replace.add_argument("ert", type=Path, help="исходный ERT")
    replace.add_argument("text", type=Path, help="текст в UTF-8 или CP1251")
    replace.add_argument("output", type=Path, help="новый ERT (не исходный файл)")

    dialog_show = subparsers.add_parser("dialog-show", help="показать текст диалога формы")
    dialog_show.add_argument("ert", type=Path)

    dialog_list = subparsers.add_parser(
        "dialog-controls", help="элементы формы: ID, класс, подпись, формула, идентификатор"
    )
    dialog_list.add_argument("ert", type=Path)

    dialog_extract = subparsers.add_parser("dialog-extract", help="извлечь текст диалога в UTF-8")
    dialog_extract.add_argument("ert", type=Path)
    dialog_extract.add_argument("text", type=Path)

    dialog_replace = subparsers.add_parser(
        "dialog-replace", help="заменить текст диалога и создать новый ERT"
    )
    dialog_replace.add_argument("ert", type=Path, help="исходный ERT")
    dialog_replace.add_argument("text", type=Path, help="текст диалога в UTF-8 или CP1251")
    dialog_replace.add_argument("output", type=Path, help="новый ERT (не исходный файл)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "show":
            sys.stdout.write(extract_text(args.ert))
        elif args.command == "extract":
            text = extract_text(args.ert)
            args.text.write_text(text, encoding="utf-8-sig", newline="")
            print(f"Извлечено: {args.text}")
        elif args.command == "replace":
            if args.ert.resolve() == args.output.resolve():
                raise ErtError("Выходной файл должен отличаться от исходного ERT")
            replace_text(args.ert, args.text, args.output)
            print(f"Создано и проверено: {args.output}")
        elif args.command == "dialog-show":
            sys.stdout.write(extract_dialog(args.ert))
        elif args.command == "dialog-controls":
            print("id\tclass\tcaption\tformula\tidentifier")
            for control in dialog_controls(extract_dialog(args.ert)):
                print("\t".join([control.control_id, control.kind, control.caption,
                                 control.formula, control.identifier]))
        elif args.command == "dialog-extract":
            text = extract_dialog(args.ert)
            args.text.write_text(text, encoding="utf-8-sig", newline="")
            print(f"Извлечено: {args.text}")
        elif args.command == "dialog-replace":
            if args.ert.resolve() == args.output.resolve():
                raise ErtError("Выходной файл должен отличаться от исходного ERT")
            replace_dialog_text(args.ert, read_source_file(args.text), args.output)
            print(f"Создано и проверено: {args.output}")
        return 0
    except (ErtError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
