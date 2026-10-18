"""Stand launcher for the visible-form probe (task 008): the stage-4 launcher with a form adapter.

A stand profile points ``launcher`` here; ``harness77 run`` then opens the form of
the run's ERT *visibly* in the owned 1C session and checks it as a window:

- ``check``: the form opens and closes at once; this is the load (compile) check.
- ``open``: the controller opens the form (the module answers
  ``loaded:harness77-form`` and does not call ``СтатусВозврата(0)``) and keeps
  its context. When the call returns, the watcher finds the form among the owned
  windows on the run's private desktop: the window whose children carry every
  control ID of the built ERT's dialog. It records each control's rectangle in
  the parent's client area, the DPI, one linear mapping of the form numbers to
  pixels and a screenshot (evidence only). With ``[platform.parameters]
  click_id`` it then sends ``BM_CLICK`` to that button.
- ``result``: the client first waits for the watcher's ``form-click-done``
  marker, so 1C is idle in its message loop while the click is handled; then
  the controller returns the form's parameter list (the handler adds
  ``clicked:<n>``) and closes the form.

``check`` passes when the form loaded, opened and closed; ``open`` passes when
the form opened, loaded and matched its description;
``result`` with a click passes when the button was found, the message returned
and the handler ran exactly once (value ``clicked:1``); without a click it
passes when the form closed. Evidence: ``<run>/form/``.
"""

import contextlib
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform77"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import stage4_launcher77 as launcher  # noqa: E402
from shutdown77 import atomic_json, sha256  # noqa: E402

IDENTITY = "harness77-form"
COMMANDS = ("check", "open", "result")
DONE = "form-click-done"
CLICK_WAIT_S = 60

CONTROLLER = """Перем Параметры77Формы;
Перем Контекст77Формы;

Функция Harness77Ert(Путь, Команда, Протокол, Метка) Экспорт
    Сообщения77 = СоздатьОбъект("MessageView");
    Сообщения77.SetSystemMessages();
    Сообщения77.Clear();
    Сообщить("HARNESS77-BEGIN:" + Метка);
    Ответ77 = "selected:" + Путь + РазделительСтрок;
    Если (Команда = "check") ИЛИ (Команда = "open") Тогда
        Параметры77 = СоздатьОбъект("СписокЗначений");
        Параметры77.ДобавитьЗначение(Команда);
        Контекст77 = Параметры77;
        Попытка
            Открыта77 = ОткрытьФорму("Отчет", Контекст77, Путь);
            Ответ77 = Ответ77 + "open-return:" + СокрЛП(Строка(Открыта77)) + РазделительСтрок;
            Если Открыта77 = 1 Тогда
                Если Команда = "check" Тогда
                    Контекст77.Форма.Закрыть(0);
                    Ответ77 = Ответ77 + "closed:1" + РазделительСтрок;
                Иначе
                    Контекст77Формы = Контекст77;
                    Параметры77Формы = Параметры77;
                КонецЕсли;
            КонецЕсли;
        Исключение
            Ответ77 = Ответ77 + "open-error:" + ОписаниеОшибки() + РазделительСтрок;
        КонецПопытки;
        Для Номер77 = 2 По Параметры77.РазмерСписка() Цикл
            Ответ77 = Ответ77 + Параметры77.ПолучитьЗначение(Номер77) + РазделительСтрок;
        КонецЦикла;
    ИначеЕсли ТипЗначенияСтр(Параметры77Формы) = "СписокЗначений" Тогда
        Для Номер77 = 2 По Параметры77Формы.РазмерСписка() Цикл
            Ответ77 = Ответ77 + Параметры77Формы.ПолучитьЗначение(Номер77) + РазделительСтрок;
        КонецЦикла;
        Попытка
            Контекст77Формы.Форма.Закрыть(0);
            Ответ77 = Ответ77 + "closed:1" + РазделительСтрок;
        Исключение
            Ответ77 = Ответ77 + "close-error:" + ОписаниеОшибки() + РазделительСтрок;
        КонецПопытки;
        Контекст77Формы = 0;
        Параметры77Формы = 0;
    Иначе
        Ответ77 = Ответ77 + "no-open-form" + РазделительСтрок;
    КонецЕсли;
    Сообщить("HARNESS77-END:" + Метка);
    Сообщения77.SaveToFile(Протокол);
    Возврат Ответ77;
КонецФункции
"""

CALL = '    result = controller.Harness77Ert(ertPath, command, evidencePath, runId & ":" & command)'
AWAIT = """
Sub AwaitClick()
    Dim donePath, waitStarted
    donePath = fso.BuildPath(fso.GetParentFolderName(eventPath), "__DONE__")
    waitStarted = CDbl(Timer)
    Do While Not fso.FileExists(donePath)
        WScript.Sleep 100
        If Elapsed(waitStarted) > __WAIT_MS__ Then
            Emit "phase", "click-wait", "timeout", Elapsed(waitStarted)
            Exit Sub
        End If
    Loop
    Emit "phase", "click-wait", "ok", Elapsed(waitStarted)
End Sub
"""


def click_id(parameters):
    value = parameters.get("click_id")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 0xFFFF:
        raise ValueError(f"[platform.parameters] click_id must be a control ID 1…65535, got {value!r}")
    return value


def built_description(ert_path):
    """Description of the built ERT's dialog: the expected controls and their numbers."""
    from harness77.ert_module import CompoundFile, decode_dialog
    from harness77.form77 import describe, dialog_entry
    compound = CompoundFile(Path(ert_path).read_bytes())
    return describe(decode_dialog(compound.read_stream(dialog_entry(compound))))


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class FormWatcher(threading.Thread):  # pragma: no cover - native, verified on the stand
    """After ``open`` returns: inspect the owned form, click once, then release the client."""

    def __init__(self, out, lifecycle, desktop, description, control_id, evidence_dir):
        super().__init__(name="harness77-form-watcher", daemon=True)
        self.out, self.lifecycle, self.desktop = out, lifecycle, desktop
        self.description, self.control_id, self.evidence_dir = description, control_id, evidence_dir
        self.stopped = threading.Event()

    def run(self):
        record = {"run_id": self.lifecycle["run_id"], "click_requested": self.control_id}
        opened = self.out / "ert-open-finished"
        try:
            while not opened.exists():
                if self.stopped.wait(0.05):
                    return
            if opened.read_text(encoding="ascii").strip() != self.lifecycle["run_id"]:
                raise ValueError("foreign open marker")
            record.update(self.inspect())
        except Exception as error:  # noqa: BLE001 - every failure becomes evidence
            record["error"] = f"{type(error).__name__}: {error}"
        finally:
            atomic_json(self.evidence_dir / "form-window.json", record)
            marker = self.out / (DONE + ".tmp")
            marker.write_text(self.lifecycle["run_id"], encoding="ascii")
            marker.replace(self.out / DONE)

    def inspect(self):
        import ctypes as C
        from form_window77 import OwnedForm, awareness, expected_geometry, fit_units
        from harness77.screenshots77 import capture_window, evidence
        from win32_session77 import kernel
        server, tid = self.lifecycle["server"], self.lifecycle["proxy_identity"]["tid"]
        handle = kernel.OpenProcess(0x100000 | 0x1000, False, server["pid"])
        if not handle:
            raise C.WinError(C.get_last_error())
        try:
            form = OwnedForm(handle, server, tid, self.desktop, self.lifecycle["run_id"])
            expected = expected_geometry(self.description)
            started = time.monotonic()
            inspection = form.inspect(list(expected))
            inspection["elapsed_s"] = round(time.monotonic() - started, 3)
            inspection["measuring_process"] = awareness()
            if inspection["found"]:
                measured = {c["id"]: tuple(c["rect"]) for c in inspection["controls"]}
                inspection["units"] = fit_units(expected, measured)
                shots = []
                for role, window in (("form", inspection["chain"][1] if len(inspection["chain"]) > 1
                                      else inspection["chain"][0]), ("dialog", inspection["chain"][0])):
                    target = self.evidence_dir / f"form-{role}.png"
                    try:
                        capture_window(window["hwnd"], target)
                        shots.append(dict(evidence(target, run_id=self.lifecycle["run_id"], phase="form-" + role,
                                                   window=window, root=self.evidence_dir.parent), role=role))
                    except (OSError, RuntimeError) as error:
                        shots.append(dict(evidence(None, run_id=self.lifecycle["run_id"], phase="form-" + role,
                                                   window=window, root=self.evidence_dir.parent,
                                                   error=f"{type(error).__name__}: {error}"), role=role))
                inspection["screenshots"] = shots
            if self.control_id is not None:
                from form_window77 import window_ids
                window_id = window_ids(self.description).get(self.control_id)
                if window_id is None or not inspection["found"]:
                    click = {"control_id": window_id, "found": False, "requested": False,
                             "reason": "no such record in the description" if window_id is None else "form not found"}
                else:
                    click = form.click(inspection, window_id)
                inspection["click"] = dict(click, record_id=self.control_id)
            return inspection
        finally:
            kernel.CloseHandle(handle)


class FormAdapter(launcher.Harness77Adapter):
    identity = IDENTITY

    def __init__(self):
        self.run_dir = None
        self.parameters = {}

    def commands(self, parameters, requested):
        click_id(parameters)
        unknown = [command for command in requested if command not in COMMANDS]
        if unknown:
            raise ValueError("unknown form command: " + ", ".join(unknown))
        return list(COMMANDS)

    def controller(self, parameters):
        return CONTROLLER

    def client(self, text):
        if text.count(CALL) != 1:
            raise ValueError("unexpected client layout: the ERT call is not found once")
        text = text.replace(CALL, '    If command = "result" Then AwaitClick\n' + CALL)
        return text + AWAIT.replace("__DONE__", DONE).replace("__WAIT_MS__", str(CLICK_WAIT_S * 1000))

    def prepare(self, run_dir, parameters):
        self.run_dir, self.parameters = run_dir, dict(parameters)
        (run_dir / "form").mkdir(exist_ok=False)
        return {}

    def watch(self, out, lifecycle, desktop):  # pragma: no cover - native
        description = built_description(out / "Тестовые обработки" / "Обработка проверки.ert")
        atomic_json(self.run_dir / "form" / "description.json", description)

        @contextlib.contextmanager
        def watching():
            watcher = FormWatcher(out, lifecycle, desktop, description, click_id(self.parameters),
                                  self.run_dir / "form")
            watcher.start()
            try:
                yield
            finally:
                watcher.stopped.set()
                watcher.join(timeout=30)
        return watching()

    def evidence(self):
        return (load_json(self.run_dir / "form" / "form-window.json") if self.run_dir else None,
                load_json(self.run_dir / "form" / "description.json") if self.run_dir else None)

    def operation(self, command, lines, actual, row):
        from form_window77 import judge_layout
        if "open-error:" in actual or not any(line == "loaded:" + IDENTITY for line in lines):
            if row["diagnostics"]:
                row["status"] = "failed"
                return None
            row["status"] = "blocked"
            return "no form loaded marker and no diagnostic: " + command
        inspection, description = self.evidence()
        if command == "check":
            row["value"] = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("open-return:")), None)
            row["status"] = "passed" if row["value"] == "1" and "closed:1" in lines else "failed"
            return None
        if command == "open":
            row["value"] = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("open-return:")), None)
            issues = [] if row["value"] == "1" else ["the form did not open visibly: open-return " + str(row["value"])]
            if inspection is None or description is None:
                issues.append("no form inspection evidence")
            else:
                if inspection.get("error"):
                    issues.append("inspection error: " + inspection["error"])
                issues += judge_layout(description, inspection)
                row["form"] = {key: inspection.get(key) for key in ("found", "parent", "units", "screenshots")}
            row["form_issues"] = issues
            row["status"] = "failed" if issues else "passed"
            return None
        clicks = [line for line in lines if line.startswith("clicked:")]
        row["value"] = ";".join(clicks) or None
        issues = [] if "closed:1" in lines else ["the form was not closed"]
        requested = click_id(self.parameters)
        if requested is not None:
            click = (inspection or {}).get("click") or {}
            row["click"] = click
            if not click.get("found"):
                issues.append(f"button {requested} not found")
            elif not click.get("returned"):
                issues.append("BM_CLICK did not return")
            if click.get("found") and not (click.get("button") or {}).get("inside_client"):
                issues.append(f"button {requested} is not wholly inside the form's client area")
            if clicks != ["clicked:1"]:
                issues.append("the handler did not run exactly once: " + str(clicks))
        row["form_issues"] = issues
        row["status"] = "failed" if issues else "passed"
        return None

    def platform_status(self, operations):
        """The session ran cleanly; the form and the click are judged by the declared tests."""
        return "passed"

    def result_files(self, run_dir, operations):
        files = []
        folder = run_dir / "form"
        for path in sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []:
            files.append({"path": path.relative_to(run_dir).as_posix(), "size": path.stat().st_size,
                          "sha256": sha256(path), "complete": True})
        return files


if __name__ == "__main__":
    raise SystemExit(launcher.main(adapter=FormAdapter()))
