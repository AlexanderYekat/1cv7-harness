r"""A copy of the stand base for a run with a changed configuration (task 021).

A changed configuration must not reach the stand base: the run copies the base, puts
the built 1Cv7.MD into the copy, and 1C opens the copy. 1C 7.7 opens through OLE only
a base its list of bases has (HKCU\Software\1C\1Cv7\7.7\Titles); for any other path
it waits on «Регистрация Информационной Базы» (task 021, m-same). So the copy has one
place, the stand's ``copy_path``, registered in that list once, and each run makes it
afresh: a lock (``<copy_path>.lock``) keeps a second run away, a marker file in the
copy names the run it was made for, and only a marked directory is ever removed.

Everything of the base is copied but the top-level subdirectories the stand names in
``copy_exclude``: 1C needs the user's working directory (usrdef/users.usr names it,
".\Вера" for ВВВ in base-for-test) with the values the global module restores at
start. A base open in 1C is refused: a working 1C locks 1SUSERS.DBF (task 007), the
Configurator in exclusive mode 1SJOURN.DBF. After the run the copy is removed, and
the base must be as it was: the same files with the same sizes and times.
"""

import ctypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

from .config77 import path_tag

LOCKED = ("1SUSERS.DBF", "1SJOURN.DBF")
MD = "1Cv7.MD"
MARKER = "harness77-copy.json"
# The event log of 1C 7.7: date;time;user;mode;category;event;number;text;; in Windows-1251.
LOG = "SYSLOG/1cv7.mlg"
LOG_ENTRIES = 200


class BaseCopyError(RuntimeError):
    """The base cannot be copied for this run."""


def listing(base):
    """{relative path: [size, mtime_ns]} of every file under a base."""
    found = {}
    for root, dirs, files in os.walk(base):
        dirs.sort()
        for name in files:
            path = Path(root) / name
            stat = path.stat()
            found[path.relative_to(base).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return found


def _digest(found):
    return hashlib.sha256(json.dumps(sorted(found.items()), ensure_ascii=False).encode("utf-8")).hexdigest()


def open_in_1c(base):
    """The name of a table a working 1C holds, or None."""
    for name in LOCKED:
        path = Path(base) / name
        if not path.exists():
            continue
        try:
            with path.open("rb") as stream:
                stream.read(32)
        except PermissionError:
            return name
    return None


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alive(pid):
    """Whether a process with this id runs; a reused id only makes a lock look held."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102  # WAIT_TIMEOUT: still running
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def lock_path(target):
    target = Path(target)
    return target.with_name(target.name + ".lock")


def acquire(target, run_id):
    """Lock the copy path for this run; a lock whose process is gone is taken over."""
    lock = lock_path(target)
    stale = None
    for _ in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = _read_json(lock) or {}
            if _alive(holder.get("pid")):
                raise BaseCopyError(f"путь копии занят прогоном {holder.get('run_id')} "
                                    f"(процесс {holder.get('pid')})") from None
            stale = holder.get("run_id")
            lock.unlink(missing_ok=True)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"run_id": run_id, "pid": os.getpid()}, stream)
        return {"lock": lock.name, "stale_run_id": stale}
    raise BaseCopyError("замок пути копии не захвачен")


def release(target, run_id):
    """Remove the lock if it is this run's."""
    lock = lock_path(target)
    if (_read_json(lock) or {}).get("run_id") == run_id:
        lock.unlink(missing_ok=True)
        return True
    return False


def _rmtree(target):
    errors = []

    def failed(function, path, error):
        errors.append(f"{Path(path).name}: {error if isinstance(error, BaseException) else error[1]}")
    # onerror is deprecated from Python 3.12 on, onexc does not exist before it.
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=failed)
    else:
        shutil.rmtree(target, onerror=failed)
    return errors


def _clear(target):
    """Remove a previous copy at the path: only a marked one, never a base 1C holds."""
    if not target.exists():
        return None
    if not (target / MARKER).is_file():
        raise BaseCopyError(f"каталог копии {target.name} существует без метки {MARKER}: это не копия harness77; "
                            "удалите его или задайте другой copy_path")
    locked = open_in_1c(target)
    if locked:
        raise BaseCopyError(f"прежняя копия открыта в 1С ({locked} заблокирован)")
    previous = (_read_json(target / MARKER) or {}).get("run_id")
    errors = _rmtree(target)
    if target.exists():
        raise BaseCopyError(f"прежняя копия не удалена: {errors[0] if errors else 'каталог остался'}")
    return previous


def copy(source, target, exclude=(), configuration=None, run_id=None):
    """(evidence, listing of the source) of a fresh copy at target, its 1Cv7.MD the built one.

    The caller holds the lock of the path (acquire). The marker goes in first, so a copy
    broken off midway is still recognised as one and removed by the next run.
    """
    source, target = Path(source).resolve(strict=True), Path(os.path.abspath(target))
    try:
        # Both resolved, so a short 8.3 name or a link does not hide that one holds the other.
        target = target.parent.resolve(strict=True) / target.name
    except OSError:
        raise BaseCopyError(f"нет каталога для копии: {target.parent}") from None
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise BaseCopyError("путь копии и база не должны совпадать или вкладываться друг в друга")
    if not (source / MD).is_file():
        raise BaseCopyError(f"в {source.name} нет {MD}")
    locked = open_in_1c(source)
    if locked:
        raise BaseCopyError(f"база открыта в 1С ({locked} заблокирован); копия не снимается")
    previous = _clear(target)
    before = listing(source)
    names = {name.casefold(): name for name in exclude}
    started = time.monotonic()
    target.mkdir()
    marker = {"run_id": run_id, "source": path_tag(source), "complete": False,
              "created_at": dt.datetime.now().astimezone().isoformat()}
    (target / MARKER).write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
    excluded = []
    for entry in sorted(os.scandir(source), key=lambda e: e.name):
        if entry.name.casefold() in names:
            excluded.append(entry.name)
        elif entry.name == MARKER:
            raise BaseCopyError(f"в базе есть {MARKER}: это копия, а не база стенда")
        elif entry.is_dir(follow_symlinks=False):
            shutil.copytree(entry.path, target / entry.name, copy_function=shutil.copy2)
        elif entry.is_file(follow_symlinks=False):
            shutil.copy2(entry.path, target / entry.name)
        else:
            raise BaseCopyError(f"{entry.name}: не файл и не каталог (ссылка?); копия не снимается")
    copied = listing(target)
    copied.pop(MARKER)
    skipped = {name.casefold() for name in excluded}
    expected = {path: row[0] for path, row in before.items() if path.split("/", 1)[0].casefold() not in skipped}
    if {path: row[0] for path, row in copied.items()} != expected:
        raise BaseCopyError("копия не совпала с базой по составу и размерам файлов")
    evidence = {"source": path_tag(source), "path": path_tag(target), "files": len(copied),
                "bytes": sum(row[0] for row in copied.values()), "excluded": excluded,
                "excluded_absent": sorted(name for key, name in names.items() if key not in skipped),
                "previous_run_id": previous, "source_listing_sha256": _digest(before),
                "source_md_sha256": _sha256(source / MD)}
    if configuration is not None:
        data = Path(configuration).read_bytes()
        (target / MD).write_bytes(data)
        if _sha256(target / MD) != hashlib.sha256(data).hexdigest():
            raise BaseCopyError(f"{MD} копии после записи отличается от собранного")
        evidence["md_sha256"] = hashlib.sha256(data).hexdigest()
    else:
        evidence["md_sha256"] = evidence["source_md_sha256"]
    marker["complete"] = True
    (target / MARKER).write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
    evidence["seconds"] = round(time.monotonic() - started, 3)
    return evidence, before


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def remove(target):
    """Remove the copy at target, a marked one only; {"removed": bool, "error": text or None}."""
    target = Path(os.path.abspath(target))
    if not target.exists():
        return {"removed": True, "error": None, "errors": 0}
    if not (target / MARKER).is_file():
        return {"removed": False, "error": f"нет метки {MARKER}: каталог не удаляется", "errors": 1}
    errors = _rmtree(target)
    return {"removed": not target.exists(), "error": errors[0] if errors else None, "errors": len(errors)}


def log_size(base):
    """The size of the base's event log, or None without one."""
    try:
        return (Path(base) / LOG).stat().st_size
    except OSError:
        return None


def session_log(base, offset, evidence):
    """What 1C wrote to the copy's event log after offset: the raw part into the evidence file and
    the entries parsed, compilation errors of the configuration's modules among them (GrbgSyntaxErr)."""
    path = Path(base) / LOG
    try:
        with path.open("rb") as stream:
            stream.seek(offset or 0)
            data = stream.read()
    except OSError as error:
        return {"path": LOG, "error": f"{type(error).__name__}: {error}"}
    Path(evidence).write_bytes(data)
    entries = []
    for line in data.decode("cp1251", errors="replace").splitlines():
        fields = line.split(";", 7)
        if len(fields) < 8:
            continue
        text = fields[7]
        text = text[:-2] if text.endswith(";;") else text
        if len(text) > 1 and text.startswith('"') and text.endswith('"'):
            text = text[1:-1].replace('""', '"')
        entries.append({"date": fields[0], "time": fields[1], "user": fields[2], "mode": fields[3],
                        "category": fields[4], "event": fields[5], "text": text})
    return {"path": LOG, "offset": offset, "bytes": len(data), "evidence": Path(evidence).name,
            "count": len(entries), "entries": entries[:LOG_ENTRIES]}


def unchanged(source, before):
    """The source base against its listing before the copy."""
    after = listing(source)
    differences = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    return {"unchanged": not differences, "differences": differences[:20], "count": len(differences)}
