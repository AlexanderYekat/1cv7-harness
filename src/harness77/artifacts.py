"""Verified, non-overwriting file operations over the existing CFB implementation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

from .ert_module import (CompoundFile, ErtError, MODULE_STREAM, compress_module, decode_dialog,
                         decompress_module, normalize_newlines, sanitize_for_cp1251)
from .lint77 import cfb_paths


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _input(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ErtError(f"Вход должен быть обычным файлом: {path}")
    return path, path.read_bytes()


def _destination(path):
    path = Path(os.path.abspath(path))
    # lexists also catches dangling symlinks. Never follow an output link.
    if os.path.lexists(path):
        raise ErtError(f"Выход уже существует: {path}")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ErtError(f"Нет каталога результата: {parent}")
    return parent / path.name


def _unchanged(inputs):
    for path, original in inputs:
        if path.read_bytes() != original:
            raise ErtError(f"Вход изменился во время операции: {path}")


def _publish(output, payload, verify, inputs):
    """Read the staged bytes from disk; atomically create a new destination only.

    A hard link publishes the verified inode without an overwrite race. Filesystems
    without hard-link support fail closed; there is no copy/replace fallback.
    """
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".harness77-", delete=False) as handle:
            temporary = Path(handle.name)
            if handle.write(payload) != len(payload):
                raise OSError("Неполная запись временного файла")
            handle.flush()
            os.fsync(handle.fileno())
        disk = temporary.read_bytes()
        if disk != payload:
            raise ErtError("Записанные байты отличаются от подготовленного результата")
        verify(disk)
        _unchanged(inputs)
        os.link(temporary, output)
        return {"path": str(output), "sha256": sha256(disk), "size_bytes": len(disk)}
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError as exc:
                # Do not report success while cleanup remains unaccounted for.
                raise ErtError(f"Не удалён временный файл {temporary}: {exc}") from exc


def _container(data):
    compound = CompoundFile(data)
    paths = cfb_paths(compound)
    modules = [e for e in compound.directory_entries if e.object_type == 2 and e.name == MODULE_STREAM]
    if len(modules) != 1:
        raise ErtError("Нужна ERT ровно с одним потоком MD Programm text")
    for entry in compound.directory_entries:
        if entry.object_type == 2:
            if entry.entry_id not in paths or len(compound.read_stream(entry)) != entry.size:
                raise ErtError(f"Недоступный или усечённый поток: {entry.name}")
    return compound, modules[0], paths


def _decode(raw, encoding):
    if encoding == "auto":
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding = "utf-16"
        else:
            try:
                raw.decode("utf-8-sig")
                encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
            except UnicodeDecodeError:
                encoding = "cp1251"
    codec = "utf-8-sig" if encoding == "utf-8" else encoding
    text = raw.decode(codec, errors="strict")
    if "\x00" in text:
        raise ErtError("Исходник содержит NUL: проверьте кодировку")
    return text, encoding


def _verify_build(original, module_id, source_bytes, rebuilt, streams=None):
    """streams: {entry id: expected bytes} of the form's streams when it was rebuilt too
    (the dialog, and in task 012 the ERT's copy of the metadata)."""
    check, module, _ = _container(rebuilt)
    if module.entry_id != module_id or len(check.directory_entries) != len(original.directory_entries):
        raise ErtError("Изменился состав каталога ERT")
    for old, new in zip(original.directory_entries, check.directory_entries):
        # Sector locations and sizes are necessarily rebuilt; all other metadata,
        # including tree links, CLSIDs, flags and timestamps, must stay identical.
        end = 116 if old.object_type in (2, 5) else 128
        if old.raw[:end] != new.raw[:end]:
            raise ErtError(f"Изменилась запись каталога: {old.name}")
        if old.object_type == 2:
            content = check.read_stream(new)
            if old.entry_id == module_id:
                if decompress_module(content) != source_bytes:
                    raise ErtError("Текст после обратного чтения отличается")
            elif streams and old.entry_id in streams:
                if content != streams[old.entry_id]:
                    raise ErtError(f"Поток формы {old.name} после обратного чтения отличается")
            elif content != original.read_stream(old):
                raise ErtError(f"Изменился посторонний поток: {old.name}")


def build(template, source, output, *, encoding="auto", legacy_normalize=False, form=None, metadata=None):
    """form: a description (task 008) that also rebuilds the template's dialog;
    metadata: the target base's 1Cv7.MD, where every kind of the form's reference fields must be
    by name (tasks 012, 013)."""
    template, template_data = _input(template)
    source, source_data = _input(source)
    inputs = [(template, template_data), (source, source_data)]
    if form is not None:
        form, form_data = _input(form)
        inputs.append((form, form_data))
    if metadata is not None:
        from .metadata77 import Metadata
        if form is None:
            raise ErtError("Метаданные нужны только сборке формы: --metadata задаётся вместе с --form")
        metadata_path, metadata_data = _input(metadata)
        inputs.append((metadata_path, metadata_data))
        metadata = Metadata(metadata_data, metadata_path)
    output = _destination(output)
    compound, module, paths = _container(template_data)
    # Validate the old module too, so a broken compressed template is not silently repaired.
    decompress_module(compound.read_stream(module)).decode("cp1251")
    text, selected_encoding = _decode(source_data, encoding)
    text = normalize_newlines(text)
    notes = []
    if legacy_normalize:
        text, notes = sanitize_for_cp1251(text)
    source_bytes = text.encode("cp1251", errors="strict")
    replacements = {module.entry_id: compress_module(source_bytes)}
    streams = form_report = None
    if form is not None:
        streams, form_report = _form(compound, form, form_data, text, metadata)
        replacements.update(streams)
    rebuilt = compound.rebuild(replacements)
    verify = lambda data: _verify_build(compound, module.entry_id, source_bytes, data, streams)
    verify(rebuilt)
    result = _publish(output, rebuilt, verify, inputs)
    report = {"schema_version": 1, "tool": "harness77", "operation": "build", "status": "passed",
            "scope": "ert_container_build", "template": {"path": str(template), "sha256": sha256(template_data)},
            "source": {"path": str(source), "sha256": sha256(source_data), "encoding": selected_encoding},
            "output": result, "module_encoding": "cp1251", "newlines": "CRLF",
            "module_sha256": sha256(source_bytes),
            "normalizations": [{"from": old, "to": new, "count": count} for old, new, count in notes],
            "preserved_streams": [{"path": paths[e.entry_id], "sha256": sha256(compound.read_stream(e)),
                                   "size_bytes": e.size} for e in compound.directory_entries
                                  if e.object_type == 2 and e.entry_id not in replacements],
            "verification": {"disk_readback": True, "module": True, "other_streams": True,
                             "directory_metadata": True, "inputs_unchanged": True},
            "platform_checked": False}
    if form_report is not None:
        report["form"] = {"path": str(form), **form_report}
        report["verification"]["dialog"] = True
    return report


def _form(compound, form, form_data, module_text, metadata=None):
    """{entry id: new bytes} of the form's streams and the form part of the report."""
    from .form77 import dialog_entry, dialog_payload, loads, rebuild
    from .metadata77 import STREAM, Metadata
    entry = dialog_entry(compound)
    old_payload = compound.read_stream(entry)
    old_text = decode_dialog(old_payload)
    template = Metadata.of_ert(compound)
    new_text, changes, action, kinds = rebuild(old_text, loads(form_data), module_text, metadata, template)
    payload = dialog_payload(new_text, old_payload)
    if decode_dialog(payload) != new_text:
        raise ErtError("Диалог формы не читается обратно")
    streams = {entry.entry_id: payload}
    report = {"sha256": sha256(form_data), "template_dialog_sha256": sha256(old_text.encode("cp1251")),
              "dialog_sha256": sha256(new_text.encode("cp1251")), "dialog_unchanged": new_text == old_text,
              "changes": changes, "kinds": kinds}
    if metadata is not None:
        # The target base: every kind of the form is in it by name (task 013).
        report["metadata"] = metadata.public()
    if template is not None:
        report["ert_metadata"] = {"action": action, "template_sha256": template.sha256,
                                  "template_configuration": template.configuration}
    if action == "replaced":
        # 1C finds the kind of a field in the ERT's own copy (task 012): it becomes the target's.
        copy = next(e for e in compound.directory_entries if e.object_type == 2 and e.name == STREAM)
        streams[copy.entry_id] = metadata.ert_stream()
        report["ert_metadata"].update(sha256=sha256(streams[copy.entry_id]), configuration=metadata.configuration)
    return streams, report


def extract(input_path, output):
    input_path, raw = _input(input_path)
    output = _destination(output)
    compound, module, _ = _container(raw)
    payload = decompress_module(compound.read_stream(module)).decode("cp1251").encode("utf-8")
    result = _publish(output, payload, lambda data: data.decode("utf-8"), [(input_path, raw)])
    return {"schema_version": 1, "tool": "harness77", "operation": "extract", "status": "passed",
            "scope": "ert_module_extract", "input": {"path": str(input_path), "sha256": sha256(raw)},
            "output": {**result, "encoding": "utf-8"}, "inputs_unchanged": True, "platform_checked": False}


def main(command, argv):
    parser = argparse.ArgumentParser(prog=f"harness77 {command}", allow_abbrev=False)
    if command == "build":
        parser.add_argument("--template", required=True, type=Path)
        parser.add_argument("--source", required=True, type=Path)
        parser.add_argument("--encoding", choices=("auto", "utf-8", "cp1251", "utf-16"), default="auto")
        parser.add_argument("--legacy-normalize", action="store_true",
                            help="Разрешить прежние замены символов с перечислением в JSON")
        parser.add_argument("--form", type=Path,
                            help="Описание формы (JSON harness77-form): собрать и диалог")
        parser.add_argument("--metadata", type=Path,
                            help="1Cv7.MD целевой базы: сверка видов ссылочных полей формы по именам")
    else:
        parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Новый файл в существующем каталоге")
    args = parser.parse_args(argv)
    try:
        if command == "build":
            report = build(args.template, args.source, args.output, encoding=args.encoding,
                           legacy_normalize=args.legacy_normalize, form=args.form, metadata=args.metadata)
        else:
            report = extract(args.input, args.output)
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()
        return 0
    except (OSError, ValueError, ErtError, struct.error, RuntimeError) as exc:
        report = {"schema_version": 1, "tool": "harness77", "operation": command, "status": "blocked",
                  "scope": "ert_container_build" if command == "build" else "ert_module_extract",
                  "output_path": str(args.output), "error": str(exc), "platform_checked": False}
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 2
