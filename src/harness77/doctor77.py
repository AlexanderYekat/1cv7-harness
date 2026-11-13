"""Read-only prerequisite checks; a ready snapshot never certifies execution."""

import argparse
import json
import os
from pathlib import Path
import re

from . import __version__
from .basecopy77 import lock_path, open_in_1c
from .config77 import load_project, load_stand, resolve_deadlines
from .report77 import sha256_file


def pe_machine(path):
    """Read bounded PE headers; never load the binary into this process."""
    with Path(path).open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError("нет заголовка MZ")
        offset = int.from_bytes(header[60:64], "little")
        if offset < 64 or offset > 16 * 1024 * 1024:
            raise ValueError("неверное смещение PE")
        stream.seek(offset)
        pe = stream.read(6)
        if len(pe) != 6 or pe[:4] != b"PE\0\0":
            raise ValueError("нет заголовка PE")
        return int.from_bytes(pe[4:6], "little")


def diagnose(project_path, stand_path, *, output_root=Path(".artifacts/runs"), windows=None):
    checks = []

    def add(id_, status, code, message, **details):
        checks.append({"id": id_, "status": status, "code": code, "message": message, "details": details})

    def attempt(id_, function):
        try:
            return function()
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            add(id_, "blocked", "inspection_error", f"{type(error).__name__}: {error}")
            return None

    def profile(id_, loader, path):
        def read():
            value = loader(path)
            add(id_, "passed", "profile_loaded", "Профиль прочитан", path=str(value.path))
            return value
        return attempt(id_, read)

    def file(id_, path, directory=False):
        def inspect():
            if path is None:
                add(id_, "blocked", "path_not_configured", "Путь не задан")
                return False
            path_ = Path(path)
            if not (path_.is_dir() if directory else path_.is_file()):
                add(id_, "blocked", "directory_missing" if directory else "file_missing",
                    "Нет каталога" if directory else "Нет файла", path=str(path_))
                return False
            if directory:
                with os.scandir(path_) as entries:
                    next(entries, None)
            else:
                with path_.open("rb") as stream:
                    stream.read(1)
            add(id_, "passed", "path_readable", "Каталог доступен" if directory else "Файл доступен", path=str(path_))
            return True
        return attempt(id_, inspect)

    def binary(id_, path):
        def inspect():
            machine = pe_machine(path)
            add(id_, "passed" if machine == 0x14c else "blocked",
                "pe_x86" if machine == 0x14c else "pe_wrong_machine",
                "PE x86" if machine == 0x14c else "Требуется PE x86", path=str(path), machine=machine)
        attempt(id_, inspect)

    def hash_check(id_, path, expected):
        def inspect():
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                raise ValueError("ожидается SHA-256 из 64 шестнадцатеричных цифр")
            actual = sha256_file(path)
            matched = actual == expected.lower()
            add(id_, "passed" if matched else "blocked", "hash_matches" if matched else "hash_mismatch",
                "SHA-256 совпадает" if matched else "SHA-256 не совпадает",
                path=str(path), expected=expected.lower(), actual=actual)
        attempt(id_, inspect)

    project = profile("project.profile", load_project, project_path)
    stand = profile("stand.profile", load_stand, stand_path)
    if project is not None:
        file("project.template", project.template)
        file("project.source", project.source)
        for name in ("form", "metadata", "configuration"):
            value = getattr(project, name)
            if value is not None:
                file("project." + name, value, directory=name == "configuration")
        for index, value in enumerate(project.globals):
            file(f"project.globals.{index}", value)
    if project is not None and stand is not None:
        def deadlines():
            limits = resolve_deadlines(project, stand)
            add("deadlines", "passed", "deadlines_valid", "Сроки согласованы", effective=limits.effective())
        attempt("deadlines", deadlines)

    if stand is not None and stand.backend != "native":
        file("stand.scenario" if stand.backend == "simulation" else "stand.import_protocol",
             stand.scenario if stand.backend == "simulation" else stand.import_protocol)
        add("native", "skipped", "non_native_backend", "Нативные проверки не требуются", backend=stand.backend)
    if stand is not None and stand.backend == "native":
        file("stand.base", stand.base, directory=True)
        if 'runtime' in stand.extra:
            def runtime():
                from .native_runtime77 import inspect_runtime
                info = inspect_runtime(stand.extra['runtime'])
                add('stand.runtime', 'passed', 'runtime_verified', 'Нативный исполнитель проверен', **info)
            attempt('stand.runtime', runtime)
            if project is not None and (project.configuration is None or stand.copy_path is None):
                add('runtime.copy', 'blocked', 'runtime_requires_copy',
                    'Штатный исполнитель требует configuration.modules и зарегистрированный copy_path')
        else:
            file("stand.launcher", stand.extra.get("launcher"))
        for name in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll", "1SUSERS.DBF", "1SJOURN.DBF"):
            if file("base." + name, stand.base / name) and name.endswith(".dll"):
                binary("pe." + name, stand.base / name)
        for role in ("exe", "cdb", "helper", "identity"):
            path = getattr(stand, role)
            if file("stand." + role, path):
                binary("pe." + role, path)
        for name, expected in stand.pinned.items():
            # Same pinned mapping as NativeBackend: exe, or a file in the base.
            if not isinstance(name, str) or name != Path(name).name or name in (".", "..") or ":" in name or "\\" in name:
                add("pinned." + str(name), "blocked", "invalid_hash_role", "Неверное имя файла базы")
            else:
                hash_check("pinned." + name, stand.exe if name == "exe" else stand.base / name, expected)
        tools = {role: getattr(stand, role) for role in ("exe", "cdb", "helper", "identity")}
        tools["launcher"] = stand.extra.get("launcher")
        for name, expected in stand.tool_hashes.items():
            if name not in tools or tools[name] is None:
                add("tool_hash." + str(name), "blocked", "invalid_hash_role", "Неизвестный или незаданный инструмент")
            else:
                hash_check("tool_hash." + name, tools[name], expected)
        if not stand.pinned and not stand.tool_hashes:
            add("hashes", "warning", "no_pinned_hashes", "Хеши зависимостей не объявлены")

        def base_idle():
            locked = open_in_1c(stand.base)
            add("base.idle", "blocked" if locked else "passed", "base_busy_or_unreadable" if locked else "base_readable",
                "Таблица заблокирована или недоступна" if locked else "Таблицы доступны для чтения", table=locked)
        attempt("base.idle", base_idle)
        needs_copy = project is not None and project.configuration is not None
        target = stand.copy_path if needs_copy else None
        if target is None:
            add("copy.path", "blocked" if needs_copy else "skipped",
                "copy_not_configured" if needs_copy else "copy_not_required",
                "Путь копии не задан" if needs_copy else "Проект не использует копию базы")
        else:
            file("copy.parent", target.parent, directory=True)
            def copy_state():
                lock = lock_path(target)
                present = os.path.lexists(target)
                locked = os.path.lexists(lock)
                add("copy.state", "blocked" if present or locked else "passed",
                    "copy_requires_inspection" if present or locked else "copy_path_idle",
                    "Обнаружена копия или замок; требуется проверка владельца/восстановление" if present or locked else "Копия и замок отсутствуют",
                    path=str(target), copy_present=present, lock_present=locked,
                    guard_present=lock.with_name(lock.name + ".guard").exists())
            attempt("copy.state", copy_state)

        def overlaps():
            paths = {"base": stand.base.resolve(), "output": Path(output_root).resolve()}
            if target is not None:
                paths["copy"] = target.resolve()
            collisions = []
            for left, a in paths.items():
                for right, b in paths.items():
                    if left < right and (a == b or a.is_relative_to(b) or b.is_relative_to(a)):
                        collisions.append([left, right])
            add("paths.overlap", "blocked" if collisions else "passed", "paths_overlap" if collisions else "paths_separate",
                "Пути базы, копии и результатов пересекаются" if collisions else "Пути базы, копии и результатов разделены",
                paths={k: str(v) for k, v in paths.items()}, collisions=collisions)
            ancestor = paths["output"]
            while not ancestor.exists() and ancestor != ancestor.parent:
                ancestor = ancestor.parent
            valid = ancestor.is_dir()
            add("output.directory", "passed" if valid else "blocked", "output_parent_exists" if valid else "output_is_file",
                "Существующий родитель результатов — каталог" if valid else "Путь результатов или его родитель занят файлом",
                path=str(ancestor))
        attempt("paths.overlap", overlaps)
        add("output.writable", "skipped", "write_not_probed", "Права записи не проверяются созданием файлов")

        if windows is None and os.name == "nt":
            from .doctor_windows77 import WindowsInspector
            windows = WindowsInspector()
        if windows is None:
            add("native.windows", "blocked", "windows_required", "Нативный стенд требует Windows")
            add("native.observations", "skipped", "windows_unavailable", "Реестр и процессы Windows не проверены")
        else:
            add("native.windows", "passed", "windows_available", "Доступны наблюдения Windows")
            if target is not None:
                def registration():
                    registered = windows.registered(target)
                    add("copy.registration", "passed" if registered else "blocked", "copy_registered" if registered else "copy_unregistered",
                        "Путь копии зарегистрирован" if registered else "Путь копии отсутствует в 32-битном списке баз 1С",
                        path=str(target))
                attempt("copy.registration", registration)
            def com():
                found = windows.com_registrations()
                add("native.com", "blocked" if found else "passed", "com_registration_present" if found else "com_roots_absent",
                    "Обнаружены COM-регистрации активного или прерванного сеанса" if found else "Временных COM-регистраций нет", keys=found)
            attempt("native.com", com)
            def processes():
                found = windows.processes()
                add("native.processes", "warning" if found else "passed", "processes_observed" if found else "no_1c_processes",
                    "Есть процессы 1С; принадлежность выбранной базе не установлена" if found else "Процессов 1С не обнаружено", processes=found)
            attempt("native.processes", processes)

    blocked = any(row["status"] == "blocked" for row in checks)
    return {"schema_version": 1, "tool": "harness77", "operation": "doctor", "version": __version__,
            "status": "blocked" if blocked else "ready", "exit_code": 2 if blocked else 0,
            "platform_checked": False, "launch_performed": False,
            "scope": "read-only prerequisite snapshot; execution and write access are not certified",
            "checks": checks, "counts": {s: sum(row["status"] == s for row in checks)
                                          for s in ("passed", "blocked", "warning", "skipped")}}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="harness77 doctor", allow_abbrev=False, description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--stand", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path(".artifacts/runs"), help="Будущий корень результатов run; не создаётся")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    report = diagnose(args.project, args.stand, output_root=args.output_root)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"doctor: {report['status']} (exit {report['exit_code']}); запуск 1С не выполнялся")
        for row in report["checks"]:
            print(f"[{row['status']}] {row['id']}: {row['message']} ({row['code']})")
            if row["details"].get("path"):
                print(f"  {row['details']['path']}")
        print("Это снимок предпосылок. Исполнение сценария подтверждает run.")
    return report["exit_code"]
