"""Modules of a 1Cv7.MD as named files: extract them, build a new 1Cv7.MD (task 021).

A module of the configuration is the stream ``MD Programm text`` of its folder: raw
DEFLATE of Windows-1251 text, as in an ERT (task 020 read all 992 of base-for-test).
Its file is named by the object it belongs to (``Metadata.module_object``): the global
module, a document's module and form, a catalog's element, group and list forms, a
journal's list forms, a report's or a processing's form. A folder without a named
object goes to Прочие under its own name; ``TypedText/UserHelp_*`` are descriptions,
not code, and stay out.

A build replaces only the modules whose text differs from the template's and keeps
every other stream, the metadata included, byte for byte: the data dictionary of a
base follows its metadata, and a module change leaves the metadata alone. With the
index of an extraction, a module the template changed after it is refused rather than
silently overwritten.

The dialog of a form (task 022) is described next to its module, ``<module>.json`` in the
harness77-form schema of the ERT forms (tasks 008, 011–013); a build rebuilds the dialog of a
description that differs from the template's and checks it in the configuration's context:
its metadata name and number the kinds, the built global module's exports are callable, and a
field named after an attribute of the form's object is that attribute's field. The
description carries the hash of the dialog it was made from, so a stale one is refused.
"""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

from .artifacts import _decode, _destination, _input, _publish, _unchanged, sha256
from .ert_module import (CompoundFile, DIALOG_STREAM, ErtError, MODULE_STREAM, compress_module, decode_dialog,
                         decompress_module, normalize_newlines)
from .lint77 import cfb_paths
from .metadata77 import Metadata

INDEX = "modules.json"
FORMAT = "harness77-md-modules"
# Version 2 (task 022) adds the forms; a version 1 index (task 021) is still read.
INDEX_VERSION, INDEX_VERSIONS = 2, (1, 2)
SUFFIX = ".1s"
FORM_SUFFIX = ".json"
GLOBAL = "TypedText/ModuleText_Number1/" + MODULE_STREAM
OTHER = "Прочие"
# <folder>/<kind>_Number<n>[/WorkBook]/MD Programm text, as every module of base-for-test and Торговля+Склад.
PATH = re.compile(r"(\w+)/(\w+?)_Number(\d+)(/WorkBook)?/" + MODULE_STREAM + r"\Z")
# The file of a form module by its folder; a list form adds the form's name.
FORMS = {"Document": "Форма", "Subconto": "ФормаЭлемента", "SubFolder": "ФормаГруппы",
         "SubList": "ФормаСписка", "Journal": "ФормаСписка", "Report": "Форма", "CalcVar": "Форма"}
LISTS = ("SubList", "Journal")
# Folders of the forms of an object, whose fields may be its attributes' (task 022).
OBJECT_FORMS = ("Document", "Subconto", "SubFolder")
IDENTIFIER = re.compile(r"[^\W\d]\w*\Z")


@dataclass
class Module:
    file: str           # the file in the layout, with "/"
    path: str           # the stream in 1Cv7.MD
    entry_id: int
    object: str | None  # "Документ.Доверенность"; None for the global module and Прочие
    module: str | None  # "МодульДокумента", "Форма", "ФормаСписка.Основная"…
    raw: bytes          # the text in Windows-1251 as stored

    def public(self):
        return {"file": self.file, "path": self.path, "object": self.object, "module": self.module,
                "sha256": sha256(self.raw)}


@dataclass
class Form:
    file: str            # the description in the layout, with "/"
    module_file: str     # the file of its module
    path: str            # the Dialog Stream in 1Cv7.MD
    module_path: str     # the stream of its module
    entry_id: int
    object: str | None   # as Module.object
    module: str | None   # as Module.module
    owner: tuple | None  # (class, name) of a document's or catalog's own form, whose fields may be attributes
    payload: bytes       # the stream as stored
    text: str            # the dialog text

    def public(self):
        return {"file": self.file, "path": self.path, "object": self.object, "module": self.module,
                "dialog_sha256": sha256(self.text.encode("cp1251"))}


def module_file(path, metadata):
    """(file, object, module) of a module stream, or None for a description (UserHelp)."""
    if path == GLOBAL:
        return "ГлобальныйМодуль" + SUFFIX, None, "ГлобальныйМодуль"
    match = PATH.match(path)
    if match is None:
        return f"{OTHER}/{path[:-len(MODULE_STREAM) - 1].replace('/', '.')}{SUFFIX}", None, None
    top, folder, number, workbook = match[1], match[2], int(match[3]), bool(match[4])
    if top == "TypedText" and folder == "UserHelp":
        return None
    found = kind = None
    if top == "TypedText" and folder == "Transact" and not workbook:
        found, kind = metadata.module_object("Transact", number), "МодульДокумента"
    elif top == folder and workbook and folder in FORMS:
        found, kind = metadata.module_object(folder, number), FORMS[folder]
    if found is not None and folder in LISTS:
        kind = f"{kind}.{found[2]}" if found[2] and IDENTIFIER.match(found[2]) else None
    if found is None or kind is None or not IDENTIFIER.match(found[1]):
        return f"{OTHER}/{folder}_Number{number}{SUFFIX}", None, None
    cls, name, _ = found
    return f"{cls}/{name}/{kind}{SUFFIX}", f"{cls}.{name}", kind


def read_modules(compound, metadata):
    """The modules of a 1Cv7.MD in directory order; refuses an unreadable one or a repeated file."""
    paths = cfb_paths(compound)
    modules, seen = [], {}
    for entry in compound.directory_entries:
        if entry.object_type != 2 or entry.name != MODULE_STREAM or entry.entry_id not in paths:
            continue
        path = paths[entry.entry_id]
        named = module_file(path, metadata)
        if named is None:
            continue
        raw = decompress_module(compound.read_stream(entry))
        try:
            raw.decode("cp1251")
        except UnicodeDecodeError as error:
            raise ErtError(f"Модуль {path} не декодируется как Windows-1251: {error}") from None
        file, owner, kind = named
        if file.casefold() in seen:
            raise ErtError(f"Модули {seen[file.casefold()]} и {path} получили один файл {file}")
        seen[file.casefold()] = path
        modules.append(Module(file, path, entry.entry_id, owner, kind, raw))
    return modules


def read_forms(compound, metadata):
    """The forms of a 1Cv7.MD in directory order: each dialog is named by the module of its folder."""
    paths = cfb_paths(compound)
    forms = []
    for entry in compound.directory_entries:
        if entry.object_type != 2 or entry.name != DIALOG_STREAM or entry.entry_id not in paths:
            continue
        path = paths[entry.entry_id]
        module_path = path[:-len(DIALOG_STREAM)] + MODULE_STREAM
        named = module_file(module_path, metadata)
        if named is None:
            raise ErtError(f"Диалог {path}: в папке описания, а не формы")
        file, owner, kind = named
        match = PATH.match(module_path)
        objects = (tuple(owner.split(".", 1)) if owner and match and match[1] == match[2]
                   and match[2] in OBJECT_FORMS else None)
        payload = compound.read_stream(entry)
        try:
            text = decode_dialog(payload)
        except (ErtError, ValueError, UnicodeDecodeError) as error:
            raise ErtError(f"Диалог {path} не читается: {error}") from None
        forms.append(Form(file[:-len(SUFFIX)] + FORM_SUFFIX, file, path, module_path, entry.entry_id, owner, kind,
                          objects, payload, text))
    return forms


def _open(data, path):
    """(compound, metadata, modules, forms) of a 1Cv7.MD."""
    metadata = Metadata(data, path)
    compound = CompoundFile(data)
    return compound, metadata, read_modules(compound, metadata), read_forms(compound, metadata)


def _describe(form, metadata):
    """(description, None) of a form, or (None, reason) when its dialog does not rebuild losslessly."""
    from .form77 import describe
    try:
        return describe(form.text, metadata), None
    except ErtError as error:
        return None, str(error)


def extract(md, output):
    """Every module of a 1Cv7.MD into a new directory, UTF-8, the description of every form next to
    its module, and the index modules.json."""
    from .form77 import dumps, loads
    md, data = _input(md)
    output = _destination(output)
    _, metadata, modules, forms = _open(data, md)
    # A dialog a description would not rebuild losslessly gets none: its form stays the template's.
    found = [(form, *_describe(form, metadata)) for form in forms]
    descriptions = [(form, description) for form, description, _ in found if description is not None]
    undescribed = [{"file": form.file, "path": form.path, "reason": reason} for form, _, reason in found if reason]
    index = {"schema_version": INDEX_VERSION, "format": FORMAT, "md": metadata.public() | {"path": None},
             "modules": [module.public() for module in modules],
             "forms": [form.public() | {"described": reason is None} for form, _, reason in found]}
    staging = Path(tempfile.mkdtemp(dir=output.parent, prefix=".harness77-"))
    try:
        for module in modules:
            target = staging / module.file
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "xb") as stream:
                stream.write(module.raw.decode("cp1251").encode("utf-8"))
        for form, description in descriptions:
            with open(staging / form.file, "xb") as stream:
                stream.write(dumps(description).encode("utf-8"))
        with open(staging / INDEX, "x", encoding="utf-8", newline="\n") as stream:
            json.dump(index, stream, ensure_ascii=False, indent=1)
        for module in modules:
            if (staging / module.file).read_bytes().decode("utf-8").encode("cp1251") != module.raw:
                raise ErtError(f"Файл {module.file} после записи отличается от модуля")
        for form, description in descriptions:
            if loads((staging / form.file).read_bytes()) != description:
                raise ErtError(f"Описание {form.file} после записи отличается от формы")
        _unchanged([(md, data)])
        os.rename(staging, output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if staging.exists():
            raise ErtError(f"Не удалён временный каталог {staging}") from None
        raise
    return {"schema_version": 1, "tool": "harness77", "operation": "md-extract", "status": "passed",
            "scope": "md_module_extract", "input": {"path": str(md), **metadata.public()},
            "output": {"path": str(output), "modules": len(modules), "forms": len(descriptions), "encoding": "utf-8",
                       "index": INDEX, "index_sha256": sha256((output / INDEX).read_bytes())},
            "forms_not_described": undescribed, "inputs_unchanged": True, "platform_checked": False}


def _index(folder):
    """{casefolded file: module sha256} of an extraction's index, or None without one."""
    path = folder / INDEX
    if not path.is_file():
        return None, None
    raw = path.read_bytes()
    try:
        index = json.loads(raw.decode("utf-8"))
        if index.get("format") != FORMAT or index.get("schema_version") not in INDEX_VERSIONS:
            raise ValueError("не индекс md-extract")
        recorded = {row["file"].casefold(): row["sha256"] for row in index["modules"]}
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ErtError(f"{INDEX}: {error}") from None
    return recorded, {"sha256": sha256(raw), "md_sha256": (index.get("md") or {}).get("sha256")}


def _files(folder):
    """Relative paths ("/") of the files of the module directory, sorted."""
    found = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            found.append((Path(root) / name).relative_to(folder).as_posix())
    return found


def _changed(module, path, raw, recorded):
    """(new Windows-1251 text, encoding) of a module file, or None when its text is the template's."""
    try:
        text, encoding = _decode(raw, "auto")
    except UnicodeDecodeError as error:
        raise ErtError(f"{path}: не читается как UTF-8, UTF-16 с BOM или Windows-1251: {error}") from None
    text = normalize_newlines(text)
    if text == normalize_newlines(module.raw.decode("cp1251")):
        return None
    try:
        new = text.encode("cp1251")
    except UnicodeEncodeError as error:
        line = text.count("\n", 0, error.start) + 1
        column = error.start - (text.rfind("\n", 0, error.start) + 1) + 1
        raise ErtError(f"{path}, строка {line}:{column}: символ {text[error.start]!r} "
                       f"(U+{ord(text[error.start]):04X}) нельзя записать в модуль 1С 7.7 (нужна Windows-1251)") from None
    if recorded is not None:
        before = recorded.get(module.file.casefold())
        if before is None:
            raise ErtError(f"{path}: модуля нет в {INDEX} — файл не из этого извлечения")
        if before != sha256(module.raw):
            raise ErtError(f"{path}: модуль {module.path} изменился в шаблоне после извлечения; "
                           "извлеките модули заново и перенесите правку")
    return new, encoding


def _verify(original, data, expected, dialogs=None):
    """The rebuilt 1Cv7.MD: the same directory, the expected modules and dialogs ({entry id: stream
    bytes}), every other stream as it was."""
    dialogs = dialogs or {}
    check = CompoundFile(data)
    if len(check.directory_entries) != len(original.directory_entries):
        raise ErtError("Изменился состав каталога 1Cv7.MD")
    for old, new in zip(original.directory_entries, check.directory_entries):
        # Sector locations and sizes are rebuilt; names, tree links, CLSIDs and times stay.
        end = 116 if old.object_type in (2, 5) else 128
        if old.raw[:end] != new.raw[:end]:
            raise ErtError(f"Изменилась запись каталога: {old.name}")
        if old.object_type != 2:
            continue
        content = check.read_stream(new)
        if old.entry_id in expected:
            if decompress_module(content) != expected[old.entry_id]:
                raise ErtError(f"Модуль {old.name} после обратного чтения отличается")
        elif old.entry_id in dialogs:
            if content != dialogs[old.entry_id]:
                raise ErtError(f"Диалог {old.name} после обратного чтения отличается")
        elif content != original.read_stream(old):
            raise ErtError(f"Изменился посторонний поток: {old.name}")
    Metadata(data)


def exports(text):
    """Casefolded names of the exported procedures and functions of a global module's text."""
    from .lint77 import Source, parse
    parsed = parse(Source("ГлобальныйМодуль", "ГлобальныйМодуль", text, is_global=True))
    return frozenset(key for key, symbol in parsed.symbols.items() if symbol.exported and not symbol.forward)


def _form_change(form, relative, raw, metadata, module_text, global_exports):
    """(form77.Rebuilt, Dialog Stream bytes) of a description, or None when it gives the template's dialog."""
    from .form77 import FormContext, describe, dialog_payload, loads, rebuild
    try:
        description = loads(raw)
        if description == describe(form.text, metadata, description["schema_version"]):
            return None
        # The configuration names and numbers the kinds of its own forms: it is both the target and the copy.
        result = rebuild(form.text, description, module_text, metadata, metadata,
                         FormContext.of(form.owner, metadata, global_exports(), form.module))
        if result.text == form.text:
            return None
        payload = dialog_payload(result.text, form.payload)
        if decode_dialog(payload) != result.text:
            raise ErtError("диалог не читается обратно")
    except ErtError as error:
        raise ErtError(f"{relative}: {error}") from None
    return result, payload


def build(template, modules, output):
    """A new 1Cv7.MD: the template with the modules and the form dialogs whose files differ from it."""
    template, data = _input(template)
    folder = Path(modules).resolve(strict=True)
    if not folder.is_dir():
        raise ErtError(f"Модули задаются каталогом (раскладка md-extract): {folder}")
    output = _destination(output)
    compound, metadata, found, forms = _open(data, template)
    by_file = {module.file.casefold(): module for module in found}
    by_form = {form.file.casefold(): form for form in forms}
    recorded, index = _index(folder)
    inputs, changes, seen, described = [(template, data)], [], {}, []
    for relative in _files(folder):
        if relative == INDEX:
            continue
        form = by_form.get(relative.casefold())
        module = by_file.get(relative.casefold())
        if module is None and form is None:
            what = "такой формы" if relative.casefold().endswith(FORM_SUFFIX) else "такого модуля"
            raise ErtError(f"{relative}: в {template.name} нет {what} (новые модули и формы не создаются; "
                           "имена файлов — как у md-extract)")
        file = module.file if module is not None else form.file
        if file in seen:
            raise ErtError(f"{relative} и {seen[file]}: один {'модуль' if module is not None else 'диалог'} {file}")
        seen[file] = relative
        raw = (folder / relative).read_bytes()
        inputs.append((folder / relative, raw))
        if form is not None:
            described.append((form, relative, raw))
            continue
        changed = _changed(module, relative, raw, recorded)
        if changed is not None:
            changes.append((module, *changed))
    expected = {module.entry_id: new for module, new, _ in changes}
    # A formula and an identifier are checked against the modules as they will be in the build.
    final = {module.file: expected.get(module.entry_id, module.raw).decode("cp1251") for module in found}
    memo = {}

    def global_exports():
        if "exports" not in memo:
            memo["exports"] = exports(final.get("ГлобальныйМодуль" + SUFFIX, ""))
        return memo["exports"]

    form_changes = []
    for form, relative, raw in described:
        changed = _form_change(form, relative, raw, metadata, final.get(form.module_file), global_exports)
        if changed is not None:
            form_changes.append((form, *changed))
    dialogs = {form.entry_id: payload for form, _, payload in form_changes}
    replacements = {key: compress_module(new) for key, new in expected.items()} | dialogs
    rebuilt = compound.rebuild(replacements) if replacements else data
    verify = lambda disk: _verify(compound, disk, expected, dialogs)
    verify(rebuilt)
    result = _publish(output, rebuilt, verify, inputs)
    return {"schema_version": 1, "tool": "harness77", "operation": "md-build", "status": "passed",
            "scope": "md_module_build", "template": {"path": str(template), **metadata.public()},
            "modules": {"path": str(folder), "files": len(seen) - len(described), "forms": len(described),
                        "index": index},
            "output": result, "rebuilt": bool(replacements),
            "changed": [{"file": module.file, "path": module.path, "object": module.object, "module": module.module,
                         "encoding": encoding, "sha256_before": sha256(module.raw), "sha256_after": sha256(new),
                         "lines_before": module.raw.count(b"\n") + 1, "lines_after": new.count(b"\n") + 1}
                        for module, new, encoding in changes],
            "unchanged_modules": len(found) - len(changes),
            "changed_forms": [{"file": form.file, "path": form.path, "object": form.object, "module": form.module,
                               "module_file": form.module_file, "module_path": form.module_path,
                               "dialog_sha256_before": sha256(form.text.encode("cp1251")),
                               "dialog_sha256_after": sha256(rebuilt_form.text.encode("cp1251")),
                               "changes": rebuilt_form.changes, "kinds": rebuilt_form.kinds}
                              for form, rebuilt_form, _ in form_changes],
            "unchanged_forms": len(forms) - len(form_changes),
            "verification": {"disk_readback": True, "changed_modules": True, "changed_dialogs": True,
                             "other_streams": True, "directory_metadata": True, "metadata_stream": True,
                             "inputs_unchanged": True},
            "platform_checked": False}


# A compile error 1C 7.7 reports: "<source with <<?>>> : {<module>(<line>)}: <message>" (task 021: the
# copy's event log and the message window name Глобальный модуль, Документ.<Имя>.Модуль Документа,
# Документ.<Имя>.Форма.Модуль).
COMPILE_ERROR = re.compile(r"(?P<source>.*) : \{(?P<module>[^{}]+)\((?P<line>\d+)\)\}: (?P<message>.*)\Z", re.S)
CLASSES = ("Справочник", "Документ", "Журнал", "Отчет", "Обработка")


# How 1C names the module of a form in a compile error, (class, the words between the object and
# «Модуль») -> the form's module in the layout; "*" is the name of a list form. A processing's form
# (task 022, series 0); a catalog's element, group and list forms, a journal's form and a report's form
# (task 023, series 0: Справочник.Банки.Форма.Модуль, …Форма группы.Модуль, …ФормаСписка.Основная.Модуль,
# Журнал.Доверенности.Форма.ФормаСписка.Модуль, Отчет.КурсыВалют.Форма.Модуль).
PLATFORM_FORMS = {("Документ", ("Форма",)): "Форма", ("Обработка", ("Форма",)): "Форма",
                  ("Отчет", ("Форма",)): "Форма", ("Справочник", ("Форма",)): "ФормаЭлемента",
                  ("Справочник", ("Форма группы",)): "ФормаГруппы",
                  ("Справочник", ("ФормаСписка", "*")): "ФормаСписка.*", ("Журнал", ("Форма", "*")): "ФормаСписка.*"}


def platform_module(name):
    """The file in the layout of a module as 1C names it in a compile error, or None."""
    if name == "Глобальный модуль":
        return "ГлобальныйМодуль" + SUFFIX
    parts = name.split(".")
    if len(parts) == 3 and parts[0] == "Документ" and parts[2] == "Модуль Документа":
        return f"Документ/{parts[1]}/МодульДокумента{SUFFIX}"
    if len(parts) < 4 or parts[-1] != "Модуль":
        return None
    words = parts[2:-1]
    named = words[-1] if len(words) == 2 and IDENTIFIER.match(words[-1]) else None
    module = PLATFORM_FORMS.get((parts[0], tuple(words if named is None else (*words[:-1], "*"))))
    if module is None:
        return None
    return f"{parts[0]}/{parts[1]}/{module.replace('*', named or '*')}{SUFFIX}"


def configuration_diagnostics(entries, changed, texts=None):
    """Compile errors of configuration modules in a session's event log entries (basecopy77.session_log).

    changed: the rows of md-build's "changed"; texts: {file: built text} to place the error's column
    on the module's own line (1C shows the line without its indent). A module 1C names but the
    layout does not map (a form name not seen in tasks 022–023, say) counts as changed when its object's module was.
    """
    files = {row["file"] for row in changed}
    objects = {row["object"] for row in changed if row.get("object")}
    found = []
    for entry in entries:
        match = COMPILE_ERROR.match(entry.get("text", ""))
        if entry.get("event") != "GrbgSyntaxErr" or match is None:
            continue
        module = match["module"]
        file = platform_module(module)
        if file is None and not module.startswith(tuple(c + "." for c in CLASSES)):
            continue  # an external processing's own module: the ERT checks report it
        source, line = match["source"], int(match["line"])
        row = {"module": module, "file": file, "line": line, "message": match["message"], "time": entry.get("time")}
        if source.count("<<?>>") == 1:
            row["source_line"] = source.replace("<<?>>", "", 1).strip()
            lines = (texts or {}).get(file, "").splitlines()
            before = source.split("<<?>>", 1)[0].lstrip()
            if 0 < line <= len(lines) and before and lines[line - 1].find(before) >= 0:
                row["column"] = lines[line - 1].find(before) + len(before) + 1
        owner = ".".join(module.split(".")[:2])
        row["changed"] = file in files if file is not None else owner in objects
        found.append(row)
    return found


def main(command, argv):
    parser = argparse.ArgumentParser(prog=f"harness77 {command}", allow_abbrev=False)
    if command == "md-build":
        parser.add_argument("--template", required=True, type=Path, help="1Cv7.MD-шаблон (база стенда)")
        parser.add_argument("--modules", required=True, type=Path,
                            help="Каталог модулей в раскладке md-extract; отсутствующие файлы — без изменений")
        parser.add_argument("--output", required=True, type=Path, help="Новый 1Cv7.MD в существующем каталоге")
    else:
        parser.add_argument("input", type=Path, help="1Cv7.MD")
        parser.add_argument("--output", required=True, type=Path, help="Новый каталог в существующем")
    args = parser.parse_args(argv)
    try:
        report = build(args.template, args.modules, args.output) if command == "md-build" \
            else extract(args.input, args.output)
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()
        return 0
    except (OSError, ValueError, ErtError, struct.error, RuntimeError) as exc:
        report = {"schema_version": 1, "tool": "harness77", "operation": command, "status": "blocked",
                  "scope": "md_module_build" if command == "md-build" else "md_module_extract",
                  "output_path": str(args.output), "error": str(exc), "platform_checked": False}
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 2
