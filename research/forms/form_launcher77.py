"""Stand launcher for the visible-form probe (tasks 008, 010–012): the stage-4 launcher with a form adapter.

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
  click_id`` it then sends ``BM_CLICK`` to that button; with ``actions``
  (task 011) it runs a sequence of ``click:<ID>`` and ``type:<ID>=<text>``
  (``WM_CHAR`` to a field) and records the text of every field and the state of
  every check box before and after.
- ``result``: the client first waits for the watcher's ``form-click-done``
  marker, so 1C is idle in its message loop while the click is handled; then
  the controller returns the form's parameter list (the handlers add
  ``clicked:<n>`` and, in task 011, ``flag:``, ``value:`` and ``label:`` lines)
  and closes the form. The value of ``result`` is every handler line, joined
  by ``;``, except ``repr:<name>=<text>`` (task 012): the representation of a
  value depends on the base's data, so these lines go to ``representations``
  and the acceptance compares them with the text of the field windows.

With ``--captures-json`` (the product's visual checks, task 010) the watcher
also shows the hidden main 1C window on the private desktop without activating
it, captures the ``open`` state, clicks, captures the ``clicked`` state and
hides the window again. Each capture is ``PrintWindow`` with
``PW_RENDERFULLCONTENT``, repeated until two in a row agree outside the blinking
caret, with the caret rectangle and the capture environment. The captures are
compared by the product, not here.

With ``[platform.parameters] form_object = "Обработка.<Имя>"`` (or ``Документ.<Имя>``,
``Отчет.<Имя>``; task 022) the controller opens that form of the configuration instead of
the run's ERT, and the expected controls are its dialog in the 1Cv7.MD of the base the
session opens (the run's copy with the built configuration), with the place of its table part
among the windows. ``Форма.Закрыть(0)`` closes a new document the form modified without asking
to write it (f-doc-close). The capture environment then names the stand base's configuration,
not the built one, so a baseline outlives the change under test. Task 023 adds the forms of
catalogs and journals, named as their module files: ``Справочник.<Вид>.ФормаЭлемента`` and
``…ФормаГруппы`` open a new element or group, ``Справочник.<Вид>.ФормаСписка.<Форма>`` and
``Журнал.<Имя>.ФормаСписка.<Форма>`` a list form, whose list is placed among the windows as a
document's table part.

Task 024 adds ``fixture_setup``: an ordinary 1C function body returning a saved
reference, run once before ``check`` and only on the product's verified base copy.
``fixture_mode = "existing"`` opens that reference; ``owner`` supplies it as the
owner of a new subordinate catalog element. ``fixture_verify`` is a function body
with argument ``Объект77`` (the prepared reference), run as the declared ``verify``
test after the form closes. It returns one string for ``expect_value``. See
examples/test-data for the complete create/open/change/write/read-back example.

Task 025 adds ``steps`` (scenario77): a readable scenario instead of ``actions``. Its elements are
named by identifier or caption; after each step the client calls the controller once (messages,
an attribute's value), then the windows are read and the step judged. The form needs no harness
protocol: ``ОткрытьФорму() = 1`` and the found window confirm it, a 1C error of any command fails
it, and ``result`` passes when every step passed and the form is closed (by the controller or a
step declared ``closes``). See examples/form-steps.

``check`` passes when the form loaded, opened and closed; ``open`` passes when
the form opened, loaded and matched its description (layout and the captions
of buttons, labels, check boxes and group boxes); ``result`` with actions passes
when every target was found inside the client area, every message returned and
a clicked handler ran exactly once (``clicked:1``); without actions it passes
when the form closed. What the module received is the test's ``expect_value``.
Evidence: ``<run>/form/``.
"""

import contextlib
import json
from pathlib import Path
import re
import sys
import threading
import time

import fixture77
import scenario77

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform77"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import stage4_launcher77 as launcher  # noqa: E402
from shutdown77 import atomic_json, sha256  # noqa: E402

IDENTITY = "harness77-form"
COMMANDS = ("check", "open", "result")
DONE = "form-click-done"
# Lines of the controller itself; every other line of ``result`` comes from a handler.
CONTROL_LINES = ("selected:", "open-return:", "open-error:", "loaded:", "closed:", "close-error:", "no-open-form")
# Handler lines with data-dependent text, kept apart from the value (task 012).
REPRESENTATION = "repr:"
CLICK_WAIT_S = 60
STEP_WAIT_S = 30  # the watcher's wait for the client's answer to one step (task 025)
# Visual captures (task 010): states around the click, windows of the form.
STATES = ("open", "clicked")
WINDOWS = ("form", "dialog")
STABLE_ATTEMPTS = 6
STABLE_PAUSE_S = 0.35  # between the captures of one stability series
PLATFORM_VERSION = "7.70.027"
# Forms of the configuration the controller opens by name (task 022): their own dialog, «Форма»;
# a catalog's element, group and list forms and a journal's list form (task 023), named as their
# module files in the md-extract layout.
NAME = r"[^\W\d]\w*"
FORM_OBJECT = re.compile(rf"(?:(?P<own>(?:Документ|Обработка|Отчет)\.{NAME})"
                         rf"|(?P<catalog>Справочник\.(?P<kind>{NAME}))\.(?P<form>ФормаЭлемента|ФормаГруппы|ФормаСписка\.{NAME})"
                         rf"|(?P<journal>Журнал\.{NAME})\.(?P<list>ФормаСписка\.{NAME}))\Z", re.IGNORECASE)
OPEN_ERT = '            Открыта77 = ОткрытьФорму("Отчет", Контекст77, Путь);\n'

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


def _record_id(text, where):
    if not text.isdigit() or not 1 <= int(text) <= 0xFFFF:
        raise ValueError(f"{where}: a control ID 1…65535, got {text!r}")
    return int(text)


def actions(parameters):
    """The actions after the inspection: ``click_id`` or ``actions`` of ``[platform.parameters]``.

    ``actions = "type:4167=Тест77,click:4164,click:4161"``: a click is ``BM_CLICK``
    to the record's window, typing is ``WM_CHAR`` per character (task 011). The
    text has no commas and must fit Windows-1251, like everything a 7.7 form shows.
    """
    single, value = click_id(parameters), parameters.get("actions")
    if value is None:
        return [] if single is None else [{"action": "click", "id": single}]
    if single is not None:
        raise ValueError("[platform.parameters] sets either click_id or actions, not both")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("[platform.parameters] actions must be a non-empty string")
    result = []
    for part in value.split(","):
        kind, _, rest = part.strip().partition(":")
        where = f"[platform.parameters] actions {part.strip()!r}"
        if kind == "click":
            result.append({"action": "click", "id": _record_id(rest, where)})
        elif kind == "type":
            target, equals, text = rest.partition("=")
            if not equals or not text:
                raise ValueError(f"{where}: type:<ID>=<text> with a non-empty text")
            text.encode("cp1251")
            result.append({"action": "type", "id": _record_id(target, where), "text": text})
        else:
            raise ValueError(f"{where}: click:<ID> or type:<ID>=<text>")
    return result


def form_object(parameters):
    """The configuration form ``[platform.parameters] form_object`` names, or None for the run's ERT."""
    value = parameters.get("form_object")
    if value is None:
        return None
    if not isinstance(value, str) or not FORM_OBJECT.match(value):
        raise ValueError("[platform.parameters] form_object is Документ.<Имя>, Обработка.<Имя>, Отчет.<Имя>, "
                         "Справочник.<Вид>.ФормаЭлемента|ФормаГруппы|ФормаСписка.<Форма> or "
                         f"Журнал.<Имя>.ФормаСписка.<Форма>, got {value!r}")
    return value


def form_target(name):
    """(object, module, the arguments of ОткрытьФорму) of a form_object.

    The syntax helper of 7.70.027 (1cv7Lang.als): a new element is «Элемент.<Вид>» with the parent
    group, the group flag (1 — a new group) and the owner; a list form is «Справочник.<Вид>.<Форма>»,
    a journal's form «Журнал.<Имя>.<Форма>». The controller opens a new element or group, as a new
    document in task 022.
    """
    match = FORM_OBJECT.match(name)
    if match["own"]:
        return match["own"], "Форма", f'"{name}", Контекст77'
    if match["journal"]:
        return match["journal"], match["list"], f'"{match["journal"]}.{match["list"].split(".", 1)[1]}", Контекст77'
    catalog, form = match["catalog"], match["form"]
    if form.casefold() == "формаэлемента":
        return catalog, "ФормаЭлемента", f'"Элемент.{match["kind"]}", Контекст77'
    if form.casefold() == "формагруппы":
        return catalog, "ФормаГруппы", f'"Элемент.{match["kind"]}", Контекст77, , 1'
    return catalog, form, f'"{catalog}.{form.split(".", 1)[1]}", Контекст77'


def controller_text(parameters, fixture_context=None):
    """The controller module: it opens the run's ERT, or the configuration form of form_object."""
    name = form_object(parameters)
    settings = fixture77.options(parameters, name)
    if name is None:
        return CONTROLLER
    if CONTROLLER.count(OPEN_ERT) != 1:
        raise ValueError("unexpected controller layout")
    arguments = fixture77.open_arguments(name, settings) if settings else form_target(name)[2]
    text = CONTROLLER.replace(OPEN_ERT, OPEN_ERT.replace('"Отчет", Контекст77, Путь', arguments))
    if settings:
        if fixture_context is None:
            raise ValueError("fixture controller requires the verified copy's metadata")
        text = fixture77.controller(text, settings, fixture_context)
    return text


def browser(text):
    """{position, columns} of a dialog's table part (form_window77.window_ids), or None without one."""
    from harness77.ert_module import parse_dialog
    for section in parse_dialog(text)[1:]:
        if isinstance(section, list) and section[:1] == ["Browser"]:
            fixed = [item for item in section[2:] if isinstance(item, list) and item[:1] == ["Fixed"]]
            if len(fixed) != 1 or not section[1].isdigit():
                raise ValueError("unknown layout of the Browser section")
            return {"position": int(section[1]), "columns": len(fixed[0]) - 1}
    return None


def configuration_description(md_path, name, fixture=None):
    """(description, source) of the form ``name`` of a 1Cv7.MD: its own dialog, as md-extract describes it."""
    from harness77.ert_module import CompoundFile
    from harness77.form77 import describe
    from harness77.md77 import read_forms
    from harness77.metadata77 import Metadata
    data = Path(md_path).read_bytes()
    metadata = Metadata(data)
    owner, module, _ = form_target(name)
    found = [form for form in read_forms(CompoundFile(data), metadata)
             if (form.object or "").casefold() == owner.casefold() and (form.module or "").casefold() == module.casefold()]
    if len(found) != 1:
        raise ValueError(f"the configuration has no form of {name}")
    form = found[0]
    if module in ("ФормаЭлемента", "ФормаГруппы"):
        catalog = metadata.catalog(owner.split(".", 1)[1])
        if catalog["owner"] and fixture is None:
            # A new element of a subordinate catalog needs its owner (ЭлементВладелец): not opened (task 023).
            raise ValueError(f"{name}: the catalog has an owner ({catalog['owner']}); "
                             "a new element or group of a subordinate catalog is not opened")
        if module == "ФормаЭлемента" and catalog["edit"] == "list":
            # ОткрытьФорму("Элемент.<Вид>") returned no value and opened nothing (e-attribute, e-in-list).
            raise ValueError(f"{name}: the catalog is edited in its list; 1C opens no element form of it")
    description = describe(form.text, metadata)
    table = browser(form.text)
    if table is not None:
        description["browser"] = table
    return description, {"form_object": name, "md_sha256": sha256(md_path), "path": form.path, "file": form.file}


def capture_requests(requests):
    """Validated ``--captures-json``: a list of {state, window} the visual checks need."""
    if not isinstance(requests, list):
        raise ValueError("captures must be a list")
    checked = []
    for request in requests:
        if not isinstance(request, dict) or set(request) != {"state", "window"}:
            raise ValueError(f"a capture request is {{state, window}}, got {request!r}")
        if request["state"] not in STATES or request["window"] not in WINDOWS:
            raise ValueError(f"unsupported capture {request['state']!r}/{request['window']!r}")
        if request not in checked:
            checked.append(dict(request))
    return checked


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
    """After ``open`` returns: inspect the owned form, run the actions, then release the client."""

    def __init__(self, out, lifecycle, desktop, description, actions, evidence_dir, visual_probe=False,
                 captures=(), configuration=None, steps=None):
        super().__init__(name="harness77-form-watcher", daemon=True)
        self.out, self.lifecycle, self.desktop = out, lifecycle, desktop
        self.description, self.actions, self.evidence_dir = description, list(actions), evidence_dir
        self.visual_probe = visual_probe
        self.captures, self.configuration = list(captures), configuration
        self.steps = steps  # resolved steps of task 025, or None
        self.stopped = threading.Event()

    def run(self):
        clicks = [a["id"] for a in self.actions if a["action"] == "click"]
        record = {"run_id": self.lifecycle["run_id"], "click_requested": clicks[-1] if clicks else None,
                  "actions_requested": self.actions}
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
        from form_window77 import OwnedForm, awareness, edged_ids, expected_geometry, fit_units
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
                inspection["units"] = fit_units(expected, measured, edged=edged_ids(self.description))
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
                if self.visual_probe:
                    inspection["visual_probe"] = self.probe_visual(form, inspection)
            captures = []
            shown = self.show_main(form, inspection) if self.captures else None
            try:
                if shown is not None:
                    captures += self.shoot(form, inspection, "open", shown)
                if inspection["found"]:
                    inspection["fields_open"] = self.fields(form, inspection)
                if self.steps and inspection["found"]:
                    inspection["steps"] = self.run_steps(form, inspection)
                    if form.alive(inspection["chain"][0]["hwnd"]):
                        inspection["fields_after"] = self.fields(form, inspection)
                elif self.actions:
                    done = self.act(form, inspection)
                    if inspection["found"]:
                        inspection["fields_after"] = self.fields(form, inspection)
                    if shown is not None:
                        failed = next((a for a in done if not a.get("returned")), None)
                        refused = None
                        if failed is not None or len(done) != len(self.actions):
                            refused = (f"the {(failed or {}).get('action', 'action')} did not happen: "
                                       + str((failed or {}).get("reason") or "the message did not return"))
                        captures += self.shoot(form, inspection, "clicked", shown, refused=refused)
            finally:
                if shown is not None:
                    inspection["visual"] = dict(shown, hide=self.hide_main(form, shown))
            if self.captures:
                inspection["captures"] = captures
            return inspection
        finally:
            kernel.CloseHandle(handle)

    def act(self, form, inspection):
        """Every action in order; the sequence stops at the first one that did not happen."""
        from form_window77 import window_ids
        ids, done = window_ids(self.description), []
        for action in self.actions:
            window_id = ids.get(action["id"])
            if window_id is None or not inspection["found"]:
                outcome = {"control_id": window_id, "found": False, "requested": False,
                           "reason": "no such record in the description" if window_id is None else "form not found"}
            elif action["action"] == "click":
                outcome = form.click(inspection, window_id)
            else:
                outcome = form.type_text(inspection, window_id, action["text"])
            done.append(dict(outcome, action=action["action"], record_id=action["id"]))
            if not outcome.get("returned"):
                break
        inspection["actions"] = done
        clicks = [a for a in done if a["action"] == "click"]
        if clicks:
            inspection["click"] = clicks[-1]
        return done

    def run_steps(self, form, inspection):
        """Every step in order (task 025): action, one round trip through 1C, the windows; stop at a failure."""
        from form_window77 import window_ids
        ids, dialog = window_ids(self.description), inspection["chain"][0]["hwnd"]
        windows = {c["id"]: c for c in inspection["controls"]}
        records, pending = [], []
        for step in self.steps:
            record = dict(step)
            control = windows.get(ids[step["record_id"]]) if "record_id" in step else None
            try:
                if "record_id" in step and control is None:
                    raise RuntimeError(f"no window of element {step['record_id']} in the form")
                if step["kind"] in scenario77.ACTIONS:
                    shown = form.element_state(control)
                    if "error" in shown or not shown["enabled"] or not shown["visible"]:
                        record["action"] = {"refused": shown.get("error") or ("the element is disabled" if not
                                                                              shown["enabled"] else "the element is hidden"),
                                            "state": shown}
                    elif step["kind"] == "click":
                        record["action"] = form.click(inspection, control["id"])
                    else:
                        record["action"] = form.enter_text(inspection, control["id"], step["text"],
                                                           self.leave_to(form, step, ids, windows))
                if not (record.get("action") or {}).get("refused") and (
                        step["kind"] not in scenario77.ACTIONS or record["action"].get("returned")):
                    record["round_trip"] = self.round_trip(step["index"])
                    if step["kind"] in scenario77.ACTIONS:
                        pending = []
                    pending = pending + record["round_trip"].get("messages", [])
                    record["form_open"] = form.alive(dialog)
                    if control is not None and record["form_open"]:
                        record["state"] = form.element_state(control, checkbox=step.get("element_class") == "CHECKBOX")
                record["issue"] = scenario77.judge(step, record, pending, record.get("form_open", True))
            except (OSError, RuntimeError, ValueError) as error:
                record["issue"] = f"step {step['index']} ({step['kind']} {step['target']!r}): {type(error).__name__}: {error}"
            record["status"] = "failed" if record["issue"] else "passed"
            records.append(record)
            if record["issue"]:
                break
        return records

    def leave_to(self, form, step, ids, windows):
        """The window that takes the focus after a field: the next element of the description, as Tab moves.

        A field, button or check box after the field's record, from the start again past the last one, enabled
        and with its own WS_VISIBLE; None when there is no such element.
        """
        records = self.description["controls"]
        position = next(n for n, item in enumerate(records) if item["id"] == step["record_id"])
        for item in records[position + 1:] + records[:position]:
            window = windows.get(ids[item["id"]])
            if item["class"] in ("1CEDIT", "BMASKED", "BUTTON", "CHECKBOX") and window is not None:
                shown = form.element_state(window)
                if shown.get("enabled") and shown.get("visible"):
                    return window
        return None

    def round_trip(self, number):
        """One controller call by the client after a step: its answer, the step's messages and 1C errors."""
        run_id = self.lifecycle["run_id"]
        request = self.out / scenario77.REQUEST
        temporary = self.out / (scenario77.REQUEST + ".tmp")
        temporary.write_text(f"{run_id}:{number}", encoding="ascii")
        temporary.replace(request)
        done = self.out / f"form-step-{number}-done"
        started = time.monotonic()
        while not done.exists():
            if self.stopped.wait(0.02):
                return {"returned": False, "error": "the session ended"}
            if time.monotonic() - started > STEP_WAIT_S:
                return {"returned": False, "error": f"no answer in {STEP_WAIT_S} s"}
        record = {"returned": True, "elapsed_s": round(time.monotonic() - started, 3)}
        record.update(scenario77.answer(done.read_text(encoding="utf-16")))
        try:
            data = (self.out / launcher.PROTOCOL_DIRECTORY / f"step-{number}.txt").read_bytes()
            protocol = data.decode("utf-16" if data.startswith(b"\xff\xfe") else "cp1251")
        except (OSError, UnicodeError) as error:
            return dict(record, complete=False, error=f"step protocol: {error}")
        record["messages"], record["complete"] = scenario77.messages(protocol, f"{run_id}:step:{number}")
        record["diagnostics"] = launcher.protocol_diagnostics(protocol)
        return record

    def fields(self, form, inspection):
        """Text of the field windows and the state of the check boxes, by record ID."""
        from form_window77 import editor, window_ids
        ids = window_ids(self.description)
        windows = {c["id"]: c for c in inspection["controls"]}
        record = {}
        for item in self.description["controls"]:
            control = windows.get(ids[item["id"]])
            if control is None or item["class"] not in ("1CEDIT", "BMASKED", "CHECKBOX"):
                continue
            try:
                record[str(item["id"])] = ({"checked": form.checked(control["hwnd"])} if item["class"] == "CHECKBOX"
                                           else {"text": form.text(editor(control)["hwnd"])})
            except (OSError, RuntimeError) as error:
                record[str(item["id"])] = {"error": f"{type(error).__name__}: {error}"}
        return record

    def show_main(self, form, inspection):
        """Show the owned main 1C window without activation, so the form paints (V0)."""
        from form_window77 import SW_SHOWNOACTIVATE
        if not inspection["found"]:
            return {"error": "form not found"}
        main = inspection["chain"][-1]
        record = {"main": {k: main[k] for k in ("hwnd", "class", "text")}}
        try:
            record["show"] = form.show(main["hwnd"], SW_SHOWNOACTIVATE)
            if not record["show"]["reached"]:
                record["error"] = "the main window did not become visible"
            record["states"] = [form.state(w["hwnd"]) for w in inspection["chain"]]
        except (OSError, RuntimeError) as error:
            record["error"] = f"{type(error).__name__}: {error}"
        return record

    def hide_main(self, form, shown):
        from form_window77 import SW_HIDE
        if "show" not in shown:
            return None
        try:
            return form.show(shown["main"]["hwnd"], SW_HIDE)
        except (OSError, RuntimeError) as error:
            return {"error": f"{type(error).__name__}: {error}"}

    def shoot(self, form, inspection, state, shown, refused=None):
        """Every requested capture of ``state``; an unusable one carries its reason."""
        records = []
        for request in (r for r in self.captures if r["state"] == state):
            record = {"state": state, "window": request["window"], "stable": False, "attempts": 0}
            reason = refused or shown.get("error")
            if reason:
                record["error"] = reason
            else:
                chain = inspection["chain"]
                window = chain[0] if request["window"] == "dialog" or len(chain) == 1 else chain[1]
                record.update(self.capture_state(form, state, request["window"], window["hwnd"]))
            records.append(record)
        return records

    def capture_state(self, form, state, role, hwnd):
        """Capture until two captures in a row agree outside the caret (it blinks, V0)."""
        from form_window77 import PW_RENDERFULLCONTENT, capture, environment
        from harness77.visual77 import compare, write_png
        record = {"hwnd": hwnd}
        started = time.monotonic()
        try:
            previous = None
            for attempt in range(1, STABLE_ATTEMPTS + 1):
                caret, focus = form.caret(hwnd)
                image = capture(hwnd, PW_RENDERFULLCONTENT)
                record.update(attempts=attempt, caret=caret, focus=focus)
                if previous is not None and caret == previous[1]:
                    masks = [dict(caret, reason="caret")] if caret else []
                    if compare(previous[0], image, masks=masks)[0]["status"] == "passed":
                        record["stable"] = True
                        break
                previous = (image, caret)
                time.sleep(STABLE_PAUSE_S)
            path = self.evidence_dir / f"capture-{state}-{role}.png"
            write_png(path, image)
            record["file"] = {"path": path.relative_to(self.evidence_dir.parent).as_posix(),
                              "sha256": sha256(path), "size": path.stat().st_size, "complete": True}
            record.update(width=image.width, height=image.height,
                          environment=environment(hwnd, self.configuration, PLATFORM_VERSION))
        except (OSError, RuntimeError, ValueError) as error:
            record["error"] = f"{type(error).__name__}: {error}"
        record["elapsed_s"] = round(time.monotonic() - started, 3)
        return record

    def probe_visual(self, form, inspection):
        """Probe V0 (task 010): which capture shows the form, hidden and after showing the main window."""
        from form_window77 import PW_RENDERFULLCONTENT, SW_HIDE, SW_SHOWNOACTIVATE, capture
        from harness77.visual77 import write_png
        chain = inspection["chain"]
        main = chain[-1]
        windows = {"dialog": chain[0]["hwnd"], "form": chain[1]["hwnd"] if len(chain) > 1 else chain[0]["hwnd"]}
        variants = (("print", 0, None), ("full", PW_RENDERFULLCONTENT, None),
                    ("print-desktop", 0, self.desktop), ("full-desktop", PW_RENDERFULLCONTENT, self.desktop))
        record = {"main": {k: main[k] for k in ("hwnd", "class", "text")},
                  "states_hidden": [form.state(w["hwnd"]) for w in chain], "shots": []}

        def shoot(stage):
            for role, hwnd in windows.items():
                for name, flags, desktop in variants:
                    entry = {"stage": stage, "role": role, "variant": name, "flags": flags,
                             "thread_desktop": desktop is not None}
                    try:
                        image = capture(hwnd, flags, desktop)
                        path = self.evidence_dir / f"visual-{stage}-{role}-{name}.png"
                        write_png(path, image)
                        entry.update(file=path.name, width=image.width, height=image.height,
                                     colours=image.colours(), sha256=sha256(path))
                    except (OSError, RuntimeError) as error:
                        entry["error"] = f"{type(error).__name__}: {error}"
                    record["shots"].append(entry)

        shoot("hidden")
        try:
            record["show"] = form.show(main["hwnd"], SW_SHOWNOACTIVATE)
            record["states_shown"] = [form.state(w["hwnd"]) for w in chain]
            time.sleep(0.5)
            shoot("shown")
            time.sleep(1.0)
            shoot("shown2")
        finally:
            record["hide"] = form.show(main["hwnd"], SW_HIDE)
        return record


class FormAdapter(launcher.Harness77Adapter):
    identity = IDENTITY

    def __init__(self):
        self.run_dir = None
        self.parameters = {}
        self.requests = []
        self.configuration = None
        self.form = None  # (description, source) of a configuration form (task 022)
        self.fixture_context = None

    def request_captures(self, requests):
        self.requests = capture_requests(requests)

    def preflight(self, base, exe, cdb, helper, drive):
        super().preflight(base, exe, cdb, helper, drive)
        self.configuration = sha256(base / "1Cv7.MD")

    def select_base(self, base, configuration_sha256=None):
        name = form_object(self.parameters)
        settings = fixture77.options(self.parameters, name)
        if settings and not configuration_sha256:
            raise ValueError("fixtures require [configuration] and the run's verified base copy")
        if configuration_sha256:
            # A copy with the built configuration: a baseline names the stand base's (task 022).
            from shutdown77 import PINNED
            self.configuration = PINNED["1Cv7.MD"]
        if name is not None:
            self.form = configuration_description(base / "1Cv7.MD", name, fixture=settings)
        if settings:
            from harness77.metadata77 import Metadata
            self.fixture_context = fixture77.context(name, settings, Metadata((base / "1Cv7.MD").read_bytes()))

    def commands(self, parameters, requested):
        scenario77.steps(parameters)
        actions(parameters)
        name = form_object(parameters)
        settings = fixture77.options(parameters, name)
        self.parameters = dict(parameters)
        commands = list(COMMANDS) + (["verify"] if settings and settings["verify"] is not None else [])
        if "verify" in commands and "verify" not in requested:
            raise ValueError("fixture_verify requires a declared platform test with command verify")
        unknown = [command for command in requested if command not in commands]
        if unknown:
            raise ValueError("unknown form command: " + ", ".join(unknown))
        return commands

    def controller(self, parameters):
        text = controller_text(parameters, self.fixture_context)
        steps = scenario77.steps(parameters)
        return text if steps is None else scenario77.controller(text, steps)

    def client(self, text):
        if text.count(CALL) != 1:
            raise ValueError("unexpected client layout: the ERT call is not found once")
        text = text.replace(CALL, '    If command = "result" Then AwaitClick\n' + CALL)
        if scenario77.steps(self.parameters) is not None:
            return text + scenario77.client(DONE, CLICK_WAIT_S * 1000)
        return text + AWAIT.replace("__DONE__", DONE).replace("__WAIT_MS__", str(CLICK_WAIT_S * 1000))

    def prepare(self, run_dir, parameters):
        if any(r["state"] == "clicked" for r in self.requests) and scenario77.steps(parameters) is not None:
            raise ValueError("the clicked state is not captured after steps; capture the open state")
        if any(r["state"] == "clicked" for r in self.requests) and not actions(parameters):
            raise ValueError("the clicked state needs [platform.parameters] click_id or actions")
        self.run_dir, self.parameters = run_dir, dict(parameters)
        (run_dir / "form").mkdir(exist_ok=False)
        return {}

    def captures(self, run_dir):
        """The requested captures from the watcher's evidence; [] when it recorded none."""
        if not self.requests:
            return None
        inspection = load_json(run_dir / "form" / "form-window.json") or {}
        return [c for c in inspection.get("captures") or [] if isinstance(c, dict)]

    def watch(self, out, lifecycle, desktop):  # pragma: no cover - native
        if self.form is not None:
            description = self.form[0]
            atomic_json(self.run_dir / "form" / "form-source.json", self.form[1])
        else:
            description = built_description(out / "Тестовые обработки" / "Обработка проверки.ert")
        atomic_json(self.run_dir / "form" / "description.json", description)
        steps = scenario77.steps(self.parameters)
        if steps is not None:
            # Every element resolves in the form's description before 1C starts (task 025).
            steps = scenario77.resolve(steps, description)
            atomic_json(self.run_dir / "form" / "steps.json", steps)

        @contextlib.contextmanager
        def watching():
            watcher = FormWatcher(out, lifecycle, desktop, description, actions(self.parameters),
                                  self.run_dir / "form", visual_probe=self.parameters.get("visual_probe") is True,
                                  captures=self.requests, configuration=self.configuration, steps=steps)
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
        from form_window77 import judge_captions, judge_layout
        handled, issue = fixture77.operation(command, lines, row)
        if handled:
            return issue
        steps = scenario77.steps(self.parameters)
        # With steps the form needs no harness protocol (task 025): ОткрытьФорму and the window confirm it.
        if "open-error:" in actual or (steps is None and not any(line == "loaded:" + IDENTITY for line in lines)):
            if row["diagnostics"]:
                row["status"] = "failed"
                return None
            row["status"] = "blocked"
            return "no form loaded marker and no diagnostic: " + command
        if steps is not None and row["diagnostics"]:
            row["status"] = "failed"
            row["form_issues"] = ["1C reported an error: line {line}: {message}".format(**row["diagnostics"][0])]
            return None
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
                issues += judge_layout(description, inspection) + judge_captions(description, inspection)
                row["form"] = {key: inspection.get(key) for key in ("found", "parent", "units", "screenshots",
                                                                     "fields_open")}
            row["form_issues"] = issues
            row["status"] = "failed" if issues else "passed"
            return None
        handlers = [line for line in lines if not line.startswith(CONTROL_LINES)]
        clicks = [line for line in handlers if line.startswith("clicked:")]
        shown = [line for line in handlers if line.startswith(REPRESENTATION)]
        if shown:
            row["representations"] = dict(line[len(REPRESENTATION):].partition("=")[::2] for line in shown)
        row["value"] = ";".join(line for line in handlers if not line.startswith(REPRESENTATION)) or None
        if steps is not None:
            records = (inspection or {}).get("steps")
            row["steps"] = records or []
            issues = scenario77.judge_result(steps, records, "closed:1" in lines)
            if inspection is None:
                issues.insert(0, "no form inspection evidence")
            elif inspection.get("error") or not inspection.get("found"):
                issues.insert(0, "inspection: " + str(inspection.get("error") or inspection.get("reason")))
            row["form_issues"] = issues
            row["status"] = "failed" if issues else "passed"
            return None
        issues = [] if "closed:1" in lines else ["the form was not closed"]
        requested = actions(self.parameters)
        if requested:
            inspection = inspection or {}
            done = {a.get("record_id"): a for a in inspection.get("actions") or []}
            if not done and inspection.get("click"):  # evidence written before task 011
                done = {inspection["click"].get("record_id"): dict(inspection["click"], action="click")}
            row["actions"] = [done.get(a["id"], {"record_id": a["id"]}) for a in requested]
            if any(a["action"] == "click" for a in requested):
                row["click"] = inspection.get("click") or {}
            for action, outcome in zip(requested, row["actions"]):
                target = ("button " if action["action"] == "click" else "field ") + str(action["id"])
                window = outcome.get("button" if action["action"] == "click" else "field") or {}
                if not outcome.get("found"):
                    issues.append(f"{target} not found")
                    break
                if not outcome.get("returned"):
                    issues.append(f"{outcome.get('message')} to {target} did not return")
                    break
                if not window.get("inside_client"):
                    issues.append(f"{target} is not wholly inside the form's client area")
            if any(a["action"] == "click" for a in requested) and clicks != ["clicked:1"]:
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
