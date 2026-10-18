"""Stand launcher for the KUDiR export (task 006): the stage-4 launcher with the KUDiR contract.

A stand profile points ``launcher`` here; ``harness77 run`` then drives the export
of a project built from the KUDiR ERT and TXT. The KUDiR module itself is not
changed: it already runs without a form when opened with the list
``KUDIR4-HEADLESS``, command, window start, window end (procedure КУДиР4_БезФормы)
and answers ``loaded:<version>`` and, per export, ``catalog:<dir>`` and
``status:<COMPLETE|FAILED|...>``.

- Commands: ``check`` (load only) and the commands of the project's tests:
  ``full`` or a series ``full_<step>_...`` (ok, ledger62, documents, snapshots,
  quarters, idmap, precheck, publish: a controlled fault of that step).
- ``[platform.parameters]``: ``start`` and ``end`` of the window, YYYY-MM-DD.
- ``KUDIR_PROTO_ROOT`` points into the run directory, so every package lands in
  ``<run>/kudir/exchange`` and the KUDiR project's own ``exchange`` is not touched.
- Every package directory there becomes result files with size and SHA-256;
  ``complete`` only when the module said COMPLETE and export_status.csv agrees.
  A package the module never reported (a cancelled or timed-out export) is
  listed too, incomplete.
- The base may be a copy of base-for-test with the same pinned files; it must
  hold kudir_source_id.txt, without which the export refuses to start.
"""

import datetime
import hashlib
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform77"))

import stage4_launcher77 as launcher  # noqa: E402

MARKER = "KUDIR4-HEADLESS"
STEPS = ("ok", "ledger62", "documents", "snapshots", "quarters", "idmap", "precheck", "publish")
COMMAND = re.compile(r"check|full(?:_(?:" + "|".join(STEPS) + r"))*")

CONTROLLER = """Функция Harness77Ert(Путь, Команда, Протокол, Метка) Экспорт
    Сообщения77 = СоздатьОбъект("MessageView");
    Сообщения77.SetSystemMessages();
    Сообщения77.Clear();
    Сообщить("HARNESS77-BEGIN:" + Метка);
    Параметры77 = СоздатьОбъект("СписокЗначений");
    Параметры77.ДобавитьЗначение("KUDIR4-HEADLESS");
    Параметры77.ДобавитьЗначение(Команда);
    Параметры77.ДобавитьЗначение(__START__);
    Параметры77.ДобавитьЗначение(__END__);
    Контекст77 = Параметры77;
    Ответ77 = "selected:" + Путь + РазделительСтрок;
    Попытка
        Открыта77 = ОткрытьФорму("Отчет", Контекст77, Путь);
        Ответ77 = Ответ77 + "open-return:" + СокрЛП(Строка(Открыта77)) + РазделительСтрок;
        Если Открыта77 = 1 Тогда
            Контекст77.Форма.Закрыть(0);
            Ответ77 = Ответ77 + "unexpected-visible-form" + РазделительСтрок;
        КонецЕсли;
    Исключение
        Ответ77 = Ответ77 + "open-error:" + ОписаниеОшибки() + РазделительСтрок;
    КонецПопытки;
    Для Номер77 = 5 По Параметры77.РазмерСписка() Цикл
        Ответ77 = Ответ77 + Параметры77.ПолучитьЗначение(Номер77) + РазделительСтрок;
    КонецЦикла;
    Контекст77 = 0;
    Параметры77 = 0;
    Сообщить("HARNESS77-END:" + Метка);
    Сообщения77.SaveToFile(Протокол);
    Возврат Ответ77;
КонецФункции
"""


def steps_of(command):
    return command.split("_")[1:] or ["ok"]


def window(parameters):
    dates = []
    for key in ("start", "end"):
        value = parameters.get(key)
        try:
            dates.append(datetime.date.fromisoformat(str(value)))
        except ValueError:
            raise ValueError(f"[platform.parameters] {key} must be a date YYYY-MM-DD, got {value!r}") from None
    if dates[0] > dates[1]:
        raise ValueError("[platform.parameters] start is after end")
    return dates


def key_values(path):
    """export_status.csv / manifest.csv: key;value lines in Windows-1251."""
    try:
        lines = path.read_bytes().decode("cp1251").splitlines()
    except (OSError, UnicodeError):
        return {}
    return dict(line.split(";", 1) for line in lines[1:] if ";" in line)


def sha256_stream(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class KudirAdapter(launcher.Harness77Adapter):
    identity = MARKER

    def commands(self, parameters, requested):
        commands = ["check"]
        for command in requested:
            if not COMMAND.fullmatch(command):
                raise ValueError("unknown KUDiR command: " + command)
            if command not in commands:
                commands.append(command)
        if len(commands) > 1:
            window(parameters)
        return commands

    def controller(self, parameters):
        start, end = window(parameters) if "start" in parameters else (datetime.date(2026, 1, 1),) * 2
        literal = "Дата({}, {}, {})".format
        return (CONTROLLER.replace("__START__", literal(start.year, start.month, start.day))
                .replace("__END__", literal(end.year, end.month, end.day)))

    def prepare(self, run_dir, parameters):
        root = run_dir / "kudir"
        (root / "exchange").mkdir(parents=True, exist_ok=False)
        return {"KUDIR_PROTO_ROOT": str(root)}

    def preflight(self, base, exe, cdb, helper, drive):
        launcher.preflight_copy(base, exe, cdb, helper, drive)
        if not (base / "kudir_source_id.txt").is_file():
            raise ValueError("the base has no kudir_source_id.txt: the export would refuse to start")

    def operation(self, command, lines, actual, row):
        loaded = next((line[len("loaded:"):] for line in lines if line.startswith("loaded:")), None)
        errors = [line for line in lines if line.startswith(("error:", "open-error:"))]
        if "unexpected-visible-form" in actual:
            row["status"] = "blocked"
            return "the KUDiR form became visible: " + command
        if loaded is None:
            if row["diagnostics"]:
                row["status"] = "failed"  # the compiler rejected the module
                return None
            row["status"] = "blocked"
            return "no KUDiR loaded marker and no diagnostic: " + command
        row["module_version"] = loaded
        row["errors"] = errors
        if command == "check":
            row["status"], row["value"] = ("failed" if errors else "passed"), loaded
            return None
        catalogs = [line[len("catalog:"):] for line in lines if line.startswith("catalog:")]
        statuses = [line[len("status:"):] for line in lines if line.startswith("status:")]
        row["packages"] = [{"catalog": c, "status": s} for c, s in zip(catalogs, statuses)]
        row["value"] = ";".join(statuses) or None
        complete = (not errors and len(catalogs) == len(statuses) == len(steps_of(command))
                    and all(status == "COMPLETE" for status in statuses))
        # A FAILED package is the application's answer, judged by the declared test.
        row["status"] = "passed" if complete else "failed"
        return None

    def platform_status(self, operations):
        return "passed"

    def result_files(self, run_dir, operations):
        exchange = (run_dir / "kudir" / "exchange").resolve()
        reported = {}
        for operation in operations:
            for package in operation.get("packages", []):
                directory = Path(package["catalog"]).resolve()
                if not directory.is_relative_to(exchange):
                    raise ValueError("a KUDiR package was written outside the run: " + package["catalog"])
                reported[directory] = (operation["name"], package["status"])
        files = []
        for directory in sorted(p for p in exchange.iterdir() if p.is_dir()) if exchange.is_dir() else []:
            name, status = reported.get(directory, (None, None))
            export = key_values(directory / "export_status.csv")
            complete = (status == "COMPLETE" and export.get("status") == "COMPLETE"
                        and export.get("run_id") == directory.name)
            for path in sorted(p for p in directory.iterdir() if p.is_file()):
                files.append({"path": path.relative_to(run_dir).as_posix(), "size": path.stat().st_size,
                              "sha256": sha256_stream(path), "complete": complete, "operation": name,
                              "package": directory.name, "package_status": status or export.get("status")})
        return files


if __name__ == "__main__":
    raise SystemExit(launcher.main(adapter=KudirAdapter()))
