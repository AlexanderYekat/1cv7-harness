"""Compile candidate controller texts inside the owned 1C session and keep the errors (task 008).

``ВыполняемыйМодуль.Compile()`` called from the client returns only 0 or 1. Here
a minimal controller of the accepted shape reads each candidate from a CP1251
file, compiles it with a nested ``ВыполняемыйМодуль`` and saves the message
window, so the compiler's text and line reach the run's protocol (as in
``module_suite77``). One command per candidate; nothing is executed.

    python -B research/forms/diagnose_controller77.py --stand .local/stage8-native/stand.toml \
        --ert BUILT.ert --output .artifacts/forms/controller-diag-YYYYMMDD
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import form_launcher77 as form  # noqa: E402

launcher = form.launcher
VARIANTS = {
    "full": form.CONTROLLER,
    "novars": "\n".join(line for line in form.CONTROLLER.splitlines() if not line.startswith("Перем ")),
    "onevar": "Перем Harness77А;\n\nФункция Harness77Ф() Экспорт\n    Возврат 1;\nКонецФункции\n",
}

DIAGNOSTIC = """Функция Harness77Ert(Путь, Команда, Протокол, Метка) Экспорт
    Сообщения77 = СоздатьОбъект("MessageView");
    Сообщения77.SetSystemMessages();
    Сообщения77.Clear();
    Сообщить("HARNESS77-BEGIN:" + Метка);
    Ответ77 = "selected:" + Путь + РазделительСтрок;
    Текст77 = СоздатьОбъект("Текст");
    Текст77.Открыть(__DIRECTORY__ + Команда + ".txt");
    Исходник77 = "";
    Для Номер77 = 1 По Текст77.КоличествоСтрок() Цикл
        Исходник77 = Исходник77 + Текст77.ПолучитьСтроку(Номер77) + РазделительСтрок;
    КонецЦикла;
    Ответ77 = Ответ77 + "lines:" + СокрЛП(Строка(Текст77.КоличествоСтрок())) + РазделительСтрок;
    Модуль77 = СоздатьОбъект("ВыполняемыйМодуль");
    Модуль77.УстановитьМодуль(Исходник77);
    Попытка
        Ответ77 = Ответ77 + "compile:" + СокрЛП(Строка(Модуль77.КомпилироватьМодуль())) + РазделительСтрок;
    Исключение
        Ответ77 = Ответ77 + "compile-error:" + ОписаниеОшибки() + РазделительСтрок;
    КонецПопытки;
    Сообщить("HARNESS77-END:" + Метка);
    Сообщения77.SaveToFile(Протокол);
    Возврат Ответ77;
КонецФункции
"""


class DiagnosticAdapter(launcher.Harness77Adapter):
    def __init__(self, directory):
        self.directory = directory

    def commands(self, parameters, requested):
        return list(VARIANTS)

    def controller(self, parameters):
        literal = '"' + (str(self.directory) + "\\").replace('"', '""') + '"'
        return DIAGNOSTIC.replace("__DIRECTORY__", literal)

    def operation(self, command, lines, actual, row):
        row["value"] = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("compile")), None)
        row["lines"] = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("lines:")), None)
        row["status"] = "passed" if "compile:1" in lines else "failed"
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stand", type=Path, required=True)
    parser.add_argument("--ert", type=Path, required=True, help="any built ERT; it is copied, not opened")
    parser.add_argument("--output", type=Path, required=True, help="new run directory")
    args = parser.parse_args(argv)
    stand = tomllib.loads(args.stand.read_text(encoding="utf-8"))["stand"]
    out = args.output.resolve()
    sources = out / "sources"
    sources.mkdir(parents=True, exist_ok=False)
    for name, text in VARIANTS.items():
        (sources / (name + ".txt")).write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("cp1251"))
    ert = args.ert.resolve()
    deadlines = {"open_timeout_s": 120, "calculation_timeout_s": 60, "cancel_timeout_s": 15,
                 "shutdown_timeout_s": 30, "total_timeout_s": 400}
    argv = ["--run-dir", str(out), "--ert", str(ert), "--ert-sha256", hashlib.sha256(ert.read_bytes()).hexdigest(),
            "--run-id", str(uuid.uuid4()), "--base", stand["base"]["path"], "--user", stand["base"]["user"],
            "--exe", stand["paths"]["exe"], "--result", str(out / "platform-result.json"),
            "--deadlines-json", json.dumps(deadlines)]
    for role in ("cdb", "helper", "identity"):
        argv += ["--" + role, stand["paths"][role]]
    code = launcher.main(argv, adapter=DiagnosticAdapter(sources))
    result = json.loads((out / "platform-result.json").read_text(encoding="utf-8"))
    print(json.dumps({"status": result["status"], "reason": result["reason"],
                      "operations": [{k: op.get(k) for k in ("name", "status", "value", "lines", "diagnostics")}
                                     for op in result["operations"]]}, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
