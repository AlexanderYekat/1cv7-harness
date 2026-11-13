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

Task 026 adds ``dialog`` steps: the last message of an action is sent from a thread of its own, and a
modal window its handler opens (``Предупреждение``, ``Вопрос``, ``ВвестиСтроку``…) is read and answered
by the dialog steps after the action. The round trip follows the last of them. A window no step
expects fails the step and, like the window of any failed step, is closed with the safest answer.

Task 027 adds the table part of a document's form (``add_row``, ``row``, ``cell``, ``delete_row``, ``rows``,
``total``, ``value`` with ``row``) and ``key`` in a table part or a list. A table step calls 1C before its keys
(the rows, the current row and column; for ``cell`` its column in edit mode), then posts Insert, Delete,
Down/Up or the cell's text and Enter, and calls 1C again. 1C makes the cursor the document's current row in
its idle update, which reaches a visible main window only: while the steps of such a form run, the main window
is shown on the run's private desktop without activation, as for the captures of task 010.

Task 033 adds ``reopen``: on the verified copy, close the existing document form with
the pinned 1C++ System.CloseForm, require its dialog/frame HWNDs to disappear, then
open the same fixture reference and inspect the new windows before continuing.
It does not save or post the document; those actions remain the scenario's UI steps.

Task 034 adds journal mode: open the configured journal, Insert and select a
document kind through its native chooser, verify the new unsaved context/HWND,
then resolve steps against the document form. Capture its reference after UI save
with ``created``; ``reopen`` and independent verification use that same reference.

Task 035 adds journal_existing and find_document: navigate the journal with
End/Up, read each current reference, Enter only on the exact fixture reference.
close_form sends WM_CLOSE to the inspected MDI frame for a native save question.

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
# An action returns or opens a modal window within this (the message timeout of task 025); a failed step
# closes at most this many windows before it leaves the rest to the session's deadlines (task 026).
ACTION_WAIT_S = 10
CELL_EDITOR_WAIT_S = 1
DISMISS_LIMIT = 5
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
    """{position, columns, fields} of a dialog's table part (form_window77.window_ids), or None without one.

    ``fields`` are the columns of its ``Fixed`` record in order (task 027): identifier (the attribute),
    caption, class and formula, and the window ID their cell editor is expected to get, the IDs 1C
    keeps for the columns after the first ``position`` windows (task 022).
    """
    from harness77.ert_module import parse_dialog
    from form_window77 import FIRST_WINDOW_ID
    for section in parse_dialog(text)[1:]:
        if isinstance(section, list) and section[:1] == ["Browser"]:
            fixed = [item for item in section[2:] if isinstance(item, list) and item[:1] == ["Fixed"]]
            if len(fixed) != 1 or not section[1].isdigit():
                raise ValueError("unknown layout of the Browser section")
            position, columns = int(section[1]), fixed[0][1:]
            if any(not isinstance(item, list) or len(item) < 8 for item in columns):
                raise ValueError("unknown layout of a Browser column")
            fields = [{"identifier": item[7], "caption": item[1], "class": item[3], "formula": item[6],
                       "window_id": FIRST_WINDOW_ID + position + number} for number, item in enumerate(columns)]
            return {"position": position, "columns": len(columns), "fields": fields}
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
        # The table part of a document's own form takes table steps; a list form's list only keys (task 027).
        table["document"] = owner.casefold().startswith("документ.") and module == "Форма"
        if table["document"]:
            # The type code of a column's attribute (S, N, D or a reference): text goes only into the first three.
            attributes = metadata.attributes("Документ", owner.split(".", 1)[1]) or {}
            for field in table["fields"]:
                found = attributes.get((field["identifier"] or "").casefold())
                field["type"] = found.code if found is not None else None
                field["kind"] = found.kind if found is not None else None
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


def finish_click(record, outcome):
    """Complete a click's record when its message returned (or did not in ACTION_WAIT_S)."""
    record.update(returned=bool(outcome.get("returned")), last_error=outcome.get("last_error"))
    if outcome.get("timeout"):
        record["reason"] = f"no return in {ACTION_WAIT_S} s"


class Chain:  # pragma: no cover - native, verified on the stand
    """An action whose last message is pending, and the modal windows its handler opens (task 026).

    ``window`` is the window the action waits in now, or None once it returned (or did not, in
    ACTION_WAIT_S without a window); ``seen`` are the top-level windows that are not a new modal one:
    those before the action and every window answered since; ``trips`` are the chain's calls to 1C.
    """

    def __init__(self, form, record, pending, seen, finish):
        self.form, self.record, self.pending, self.finish = form, record, pending, finish
        self.seen, self.window, self.trips = set(seen), None, []
        self.before = None  # a table step's call to 1C before its keys (task 027)

    def wait(self):
        outcome = self.form.await_action(self.pending, self.seen, ACTION_WAIT_S)
        self.window = outcome.pop("window", None)
        self.record.setdefault("waits", []).append(dict(outcome, window=self.window["hwnd"] if self.window else None))
        if self.window is not None:
            self.seen.add(self.window["hwnd"])
        else:
            self.finish(self.record, outcome)
        return self.window


class FormWatcher(threading.Thread):  # pragma: no cover - native, verified on the stand
    """After ``open`` returns: inspect the owned form, run the actions, then release the client."""

    def __init__(self, out, lifecycle, desktop, description, actions, evidence_dir, visual_probe=False,
                 captures=(), configuration=None, steps=None, show=False, created_description=None):
        super().__init__(name="harness77-form-watcher", daemon=True)
        self.out, self.lifecycle, self.desktop = out, lifecycle, desktop
        self.description, self.actions, self.evidence_dir = description, list(actions), evidence_dir
        self.visual_probe = visual_probe
        self.captures, self.configuration = list(captures), configuration
        self.steps = steps  # resolved steps of task 025, or None
        self.created_description = created_description
        # Task 027: 1C makes the cursor of a table part the document's current row in its idle update, which MFC
        # sends to a visible main window only (series 1b–1e): shown while the steps of such a form run.
        self.show = show
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
            shown = self.show_main(form, inspection) if self.captures or self.show else None
            try:
                if shown is not None:
                    captures += self.shoot(form, inspection, "open", shown)
                if inspection["found"]:
                    inspection["fields_open"] = self.fields(form, inspection)
                if self.steps and inspection["found"]:
                    inspection["steps"] = self.run_steps(form, inspection)
                    final_form = inspection.get("final_form", inspection)
                    if form.alive(final_form["chain"][0]["hwnd"]):
                        inspection["fields_after"] = self.fields(form, final_form)
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
        """Every step in order (task 025): action, one round trip through 1C, the windows; stop at a failure.

        An action whose handler opens a modal window is answered by the dialog steps after it (task 026).
        Once the action returned, 1C is asked, and a window it opened meanwhile continues the chain; the
        chain's calls to 1C are judged together with its last step. A window no step answers fails its
        step; a failed step's window is closed with the safest answer, so the session ends as usual.
        """
        from form_window77 import window_ids
        ids, dialog = window_ids(self.description), inspection["chain"][0]["hwnd"]
        windows = {c["id"]: c for c in inspection["controls"]}
        table = windows.get(scenario77.TABLE_WINDOW_ID)
        current_inspection = inspection
        records, pending, chain = [], [], None
        self.calls = {}
        self.pending_choice = None
        child_navigation = None
        source_description = self.description
        for step in self.steps:
            record = dict(step)
            # A step of the table part (task 027) works with its window, as an element step with its control's.
            tabular = step["kind"] == "key" or scenario77.table_step(step)
            control = windows.get(ids[step["record_id"]]) if "record_id" in step else table if tabular else None
            try:
                if step['kind'] == 'journal_children':
                    import journal_children77
                    handoff = journal_children77.execute(self, form, current_inspection, step, record)
                    if step.get('edit') or step.get('browse'):
                        current_inspection, child_navigation = handoff
                        self.description = journal_children77.runtime_description(self.created_description, step)
                        ids = window_ids(self.description)
                        dialog = current_inspection['chain'][0]['hwnd']
                        windows = {c['id']: c for c in current_inspection['controls']}
                        table = windows.get(scenario77.TABLE_WINDOW_ID)
                    record.update(form_open=True, issue=None, status='passed')
                    records.append(record)
                    continue
                if step['kind'] == 'tab':
                    import tabs77
                    current_inspection = tabs77.execute(self, form, current_inspection, step, record)
                    windows = {c['id']: c for c in current_inspection['controls']}
                    table = windows.get(scenario77.TABLE_WINDOW_ID)
                    record['form_open'] = form.alive(dialog)
                    record['issue'] = scenario77.judge(step, record, [], record['form_open'])
                    record['status'] = 'failed' if record['issue'] else 'passed'
                    records.append(record)
                    if record['issue']:
                        break
                    continue
                if step['kind'] == 'journal_deletion':
                    self.journal_deletion(form, current_inspection, step, record)
                    record.update(form_open=True, issue=None, status='passed')
                    records.append(record)
                    continue
                if step['kind'] == 'journal_unpost':
                    self.journal_unpost(form, current_inspection, step, record)
                    record.update(form_open=True, issue=None, status='passed')
                    records.append(record)
                    continue
                if step['kind'] == 'journal_period':
                    self.journal_period(form, current_inspection, step, record)
                    record.update(form_open=True, issue=None, status='passed')
                    records.append(record)
                    continue
                if step["kind"] == "close_form":
                    chain_windows = current_inspection.get("chain", [])
                    if len(chain_windows) < 3 or chain_windows[2].get("class") != "MDIClient":
                        raise RuntimeError("close_form requires an inspected MDI document frame")
                    control = chain_windows[1]
                if step['kind'] == 'journal_basis':
                    import journal_basis77
                    created = journal_basis77.execute(self, form, current_inspection, step, record)
                    if step.get('cancel'):
                        record.update(form_open=True, status='passed', issue=None)
                        records.append(record)
                        continue
                if step["kind"] in ("create", "find_document", "journal_copy", "journal_basis"):
                    created = (created if step["kind"] == "journal_basis" else self.create_document(form, current_inspection, step, record) if step["kind"] == "create"
                               else self.copy_document(form, current_inspection, step, record) if step['kind'] == 'journal_copy'
                               else self.find_document(form, current_inspection, step, record))
                    if step['kind'] == 'find_document' and step.get('open') is False:
                        record['form_open'] = form.alive(dialog)
                        record['issue'] = scenario77.judge(step, record, [], record['form_open'])
                        record['status'] = 'failed' if record['issue'] else 'passed'
                        records.append(record)
                        if record['issue']:
                            break
                        continue
                    self.description = self.created_description
                    current_inspection = created
                    ids = window_ids(self.description)
                    dialog = created["chain"][0]["hwnd"]
                    windows = {c["id"]: c for c in created["controls"]}
                    table = windows.get(scenario77.TABLE_WINDOW_ID)
                    record["form_open"] = form.alive(dialog)
                    record["issue"] = scenario77.judge(step, record, [], record["form_open"])
                    record["status"] = "failed" if record["issue"] else "passed"
                    records.append(record)
                    if record["issue"]:
                        break
                    continue
                if "record_id" in step and control is None:
                    raise RuntimeError(f"no window of element {step['record_id']} in the form")
                if tabular and control is None:
                    raise RuntimeError(f"no window {scenario77.TABLE_WINDOW_ID} of the table part in the form")
                if step["kind"] in scenario77.ACTIONS:
                    shown = form.element_state(control)
                    if "error" in shown or not shown["enabled"] or not shown["visible"]:
                        record["action"] = {"refused": shown.get("error") or ("the element is disabled" if not
                                                                              shown["enabled"] else "the element is hidden"),
                                            "state": shown}
                    else:
                        before_windows = {w["hwnd"] for w in form.inventory()}
                        chain = self.begin(form, current_inspection, step, control, ids, windows)
                        record["action"] = chain.record
                        if chain.before is not None:
                            record["before"] = chain.before
                        self.settle(form, chain, step)
                        if step["kind"] != "choose" and chain.window is None:
                            next_step = self.steps[step["index"]] if step["index"] < len(self.steps) else None
                            self.unexpected_form(form, chain, step, before_windows, next_step)
                        if step["kind"] == "cell":
                            self.committed(form, chain)
                        record["calls"] = list(chain.trips)
                        self.opened(step, record, chain)
                elif step["kind"] == "dialog":
                    record["window"] = chain.window if chain is not None else None
                    if record["window"] is not None:
                        first = len(chain.trips)
                        button, field, refusal = scenario77.answer_plan(step, chain.window)
                        record["answer"] = ({"refused": refusal} if refusal else
                                            form.answer(chain.window, button, field, step.get("text")))
                        if record["answer"].get("requested"):
                            chain.wait()
                            self.settle(form, chain, step)
                            record["calls"] = chain.trips[first:]
                            self.opened(step, record, chain)
                            if step["last"] and chain.window is None:
                                record["action"] = chain.record
                if step["kind"] == "reopen":
                    if any(w["exists"] for w in self.form_presence(form, current_inspection)["windows"]):
                        closing = self.call(step)
                        record["calls"] = [closing]
                        if (closing.get("reopen_close") != "1" or closing.get("reopen_error")
                                or closing.get("diagnostics") or not closing.get("complete")):
                            raise RuntimeError("the controller did not close the previous form: " + str(closing))
                    else:
                        record["calls"] = []
                        self.calls[step["index"]] = 1  # skip the close call of an already closed form
                    record["before_reopen"] = self.form_presence(form, current_inspection)
                    started = time.monotonic()
                    while any(w["exists"] for w in record["before_reopen"]["windows"]) and time.monotonic() - started < ACTION_WAIT_S:
                        if self.stopped.wait(0.05):
                            break
                        record["before_reopen"] = self.form_presence(form, current_inspection)
                    record["closing_wait_s"] = round(time.monotonic() - started, 3)
                    record["closed_before_reopen"] = all(not w["exists"] for w in record["before_reopen"]["windows"])
                    if not record["closed_before_reopen"]:
                        raise RuntimeError("the previous form is still open after controller closing")
                    record["calls"].append(self.call(step))
                    record["round_trip"] = scenario77.merge_trips(record["calls"])
                    pending = list(record["round_trip"].get("messages", []))
                    from form_window77 import edged_ids, expected_geometry, fit_units, judge_captions, judge_layout
                    if 'caption_control' in step:
                        import journal_basis77
                        self.description = journal_basis77.runtime_description(self.description, step)
                        record['runtime_caption_expectations'] = {step['caption_control']: step['caption_text']}
                    expected = expected_geometry(self.description)
                    reopened = form.inspect(list(expected))
                    record["reopened"] = reopened
                    if reopened.get("found"):
                        reopened["units"] = fit_units(expected, {c["id"]: tuple(c["rect"]) for c in reopened["controls"]},
                                                       edged=edged_ids(self.description))
                        issues = judge_layout(self.description, reopened) + judge_captions(self.description, reopened)
                        if issues:
                            raise RuntimeError("reopened form: " + "; ".join(issues))
                        dialog = reopened["chain"][0]["hwnd"]
                        current_inspection = reopened
                        windows = {c["id"]: c for c in reopened["controls"]}
                        table = windows.get(scenario77.TABLE_WINDOW_ID)
                        record["fields_open"] = self.fields(form, reopened)
                        chain = None
                elif step["kind"] == "row":
                    record["round_trip"] = self.go_to_row(form, current_inspection, step, record, control["hwnd"])
                    pending = pending + record["round_trip"].get("messages", [])
                elif step["kind"] not in scenario77.ACTIONS + ("dialog",):
                    record["round_trip"] = self.round_trip(step["index"])
                    pending = pending + record["round_trip"].get("messages", [])
                elif chain is not None and chain.window is None and record.get("action") is chain.record \
                        and chain.record.get("returned") and chain.trips:
                    # The step ended its action: every call of the chain, every message since the action.
                    record["round_trip"] = scenario77.merge_trips(chain.trips)
                    pending = list(record["round_trip"]["messages"])
                if "round_trip" in record:
                    record["form_open"] = form.alive(dialog)
                    if control is not None and record["form_open"]:
                        record["state"] = form.element_state(control, checkbox=step.get("element_class") == "CHECKBOX")
                    if tabular and record["form_open"]:
                        record["table"] = form.table_windows(control["hwnd"])
                record["issue"] = scenario77.judge(step, record, pending, record.get("form_open", True))
            except Exception as error:  # noqa: BLE001 - a failed step still closes its window (series 0b)
                record["issue"] = f"{scenario77.label(step)}: {type(error).__name__}: {error}"
                if step["kind"] == "create" and record.get("kind_window"):
                    window = record["kind_window"]
                    if form.alive(window["hwnd"]):
                        button, _, refusal = scenario77.answer_plan(dict(target=window["text"], button="Отмена"), window)
                        record["kind_cleanup"] = {"refused": refusal} if refusal else form.answer(window, button)
            if record["issue"] and self.pending_choice is not None and chain is not None:
                chain.choice_window, chain.choice_step = self.pending_choice, step
                self.pending_choice = None
                record["pending_choice_cleanup"] = self.cancel_choice(form, chain)
            if record["issue"] and chain is not None and chain.window is not None:
                record["dismissed"] = self.dismiss(form, chain, step)
            record["status"] = "failed" if record["issue"] else "passed"
            records.append(record)
            if record["issue"]:
                break
        if child_navigation is not None:
            import journal_children77
            returned = child_navigation['opening']['viewing_return' if child_navigation.get('step', {}).get('browse') else 'editing_return'] = {}
            try:
                current_inspection = journal_children77.finish_edit(self, form, current_inspection, child_navigation, returned)
                self.description = source_description
            except Exception as error:
                returned['issue'] = f'{type(error).__name__}: {error}'
                records[-1]['issue'] = (records[-1].get('issue') or '') + '; subordinate return: ' + returned['issue']
                records[-1]['status'] = 'failed'
        if current_inspection is not inspection:
            inspection["final_form"] = current_inspection
        return records

    def journal_deletion(self, form, inspection, step, record):
        """Toggle only a freshly verified saved target with the native journal command."""
        import journal77
        import journal_deletion77 as deletion
        from form_window77 import Pending
        number = -107000 - 2 * step['index']
        before = record['before_deletion'] = self.round_trip(number)
        record['calls'] = [dict(before, number=number)]
        deletion.checked_state(before, inspection)
        if before['journal_deleted'] == str(int(step['deleted'])):
            raise RuntimeError('document already has the requested deletion mark; refusing toggle')
        menu = record['menu'] = journal77.native_menu(form, inspection, deletion.DELETE_COMMAND, 'удал')
        if not menu['enabled']:
            raise RuntimeError('native deletion menu is disabled')
        action = record['action'] = dict(requested=True, command=deletion.DELETE_COMMAND,
            hwnd=inspection['chain'][1]['hwnd'], message='WM_COMMAND', identity_rechecked=True)
        seen = form.top_windows()
        chain = Chain(form, action, Pending(form, action['hwnd'], 0x111, deletion.DELETE_COMMAND, 0),
                      seen, finish_click)
        try:
            chain.wait()
            self.settle(form, chain, step)
            record['confirmation'] = chain.window
            if chain.window is not None:
                button = deletion.answer(chain.window, step['deleted'], step.get('cancel', False))
                record['answer'] = form.answer(chain.window, button)
                if not record['answer'].get('requested'):
                    raise RuntimeError('deletion confirmation was not answered')
                chain.wait()
                self.settle(form, chain, step)
            elif step.get('cancel'):
                raise RuntimeError('native deletion command provided no confirmation to cancel')
            if chain.window is not None or not action.get('returned'):
                raise RuntimeError('deletion command did not finish or opened another window')
        finally:
            record['calls'] += chain.trips
            if chain.window is not None:
                record['dismissed'] = self.dismiss(form, chain, step)
        after = record['after_deletion'] = self.round_trip(number - 1)
        record['calls'].append(dict(after, number=number - 1))
        deletion.checked_state(after, inspection)
        if after['journal_current'] != before['journal_current']:
            raise RuntimeError('journal target changed during deletion toggle')
        expected_mark = before['journal_deleted'] if step.get('cancel') else str(int(step['deleted']))
        if after['journal_deleted'] != expected_mark or after['journal_value'] != step['expected']:
            raise RuntimeError('saved deletion mark/document/entries differ from expectation')

    def journal_unpost(self, form, inspection, step, record):
        """Only the exact selected saved reference may receive the native unpost command."""
        import journal77
        from form_window77 import Pending
        number = -105000 - 2 * step['index']
        before = self.round_trip(number)
        record['before_unpost'] = before
        record['calls'] = [dict(before, number=number)]
        journal77.checked_cursor(before, inspection)
        menu = record['menu'] = journal77.unpost_menu(form, inspection)
        if menu['enabled'] != step.get('enabled', True):
            raise RuntimeError('native unpost menu enabled state differs from expectation')
        record['action'] = dict(requested=False, command=journal77.UNPOST_COMMAND)
        if menu['enabled']:
            action = dict(requested=True, command=journal77.UNPOST_COMMAND, hwnd=inspection['chain'][1]['hwnd'],
                          message='WM_COMMAND', identity_rechecked=True)
            chain = Chain(form, action, Pending(form, action['hwnd'], 0x111, journal77.UNPOST_COMMAND, 0),
                          form.top_windows(), finish_click)
            record['action'] = action
            try:
                chain.wait()
                self.settle(form, chain, step)
                record['confirmation'] = chain.window
                if chain.window is not None:
                    button = journal77.unpost_answer(chain.window, step.get('cancel', False))
                    record['answer'] = form.answer(chain.window, button)
                    if not record['answer'].get('requested'):
                        raise RuntimeError('unpost confirmation was not answered')
                    chain.wait()
                    self.settle(form, chain, step)
                elif step.get('cancel'):
                    raise RuntimeError('native unpost command provided no confirmation to cancel')
                if chain.window is not None or not action.get('returned'):
                    raise RuntimeError('unpost command did not finish or opened another window')
            finally:
                record['calls'] += chain.trips
                if chain.window is not None:
                    record['dismissed'] = self.dismiss(form, chain, step)
        after = self.round_trip(number - 1)
        record['after_unpost'] = after
        record['calls'].append(dict(after, number=number - 1))
        journal77.checked_cursor(after, inspection)
        if after['journal_current'] != before['journal_current']:
            raise RuntimeError('journal target changed during unpost')
        expected_posted = before['journal_posted'] if step.get('cancel') else '0'
        if after['journal_posted'] != expected_posted or after['journal_value'] != step['expected']:
            raise RuntimeError('saved document/entries after native unpost differ from expectation')

    def journal_period(self, form, inspection, step, record):
        """Invoke the platform's native Interval command on the inspected journal."""
        table = next(c for c in inspection['controls'] if c['id'] == scenario77.TABLE_WINDOW_ID)
        before_number = -102000 - step['index'] * 2
        record['before_period'] = self.round_trip(before_number)
        record['calls'] = [dict(record['before_period'], number=before_number)]
        import journal77
        journal77.read_period(record['before_period'])
        if len(inspection['chain']) < 3 or inspection['chain'][2].get('class') != 'MDIClient':
            raise RuntimeError('journal_period requires an inspected MDI journal')
        record['focus'] = form.give_focus(inspection['chain'][0]['hwnd'], table['hwnd'])
        seen = form.top_windows()
        posted, error = form.post(inspection['chain'][1]['hwnd'], 0x111, 0x8071)
        record['action'] = dict(posted=posted, last_error=error, command=0x8071)
        if not posted:
            raise RuntimeError('native Interval command could not be posted')
        window = None
        started = time.monotonic()
        while time.monotonic() - started < ACTION_WAIT_S and not self.stopped.is_set():
            window = form.modal_window(seen)
            if window:
                break
            self.stopped.wait(0.05)
        record['period_window'] = window
        if window is None:
            raise RuntimeError('native journal period dialog did not open')
        try:
            fields = journal77.period_fields(window)
            button, _, issue = scenario77.answer_plan(dict(target=window['text'], button='Отмена' if step.get('cancel') else 'ОК'), window)
            if issue:
                raise RuntimeError(issue)
            record['inputs'] = []
            for key, field in zip(('start', 'end'), fields):
                editors = [c for c in window['children'] if c.get('parent') == field['hwnd']]
                if len(editors) != 1 or editors[0]['class'].casefold() != '1ceditspr':
                    raise RuntimeError('journal date editor is ambiguous')
                form.give_focus(window['hwnd'], editors[0]['hwnd'])
                from datetime import date
                value = date.fromisoformat(step[key]).strftime('%d%m%y')
                typed = form.replace_text(editors[0]['hwnd'], value)
                record['inputs'].append(dict(typed, boundary=key))
                if not typed.get('typed'):
                    raise RuntimeError('journal date input did not return')
                form.give_focus(window['hwnd'], button['hwnd'])
            record['edited_window'] = form.window_record(window['hwnd'])
            record['answer'] = form.answer(window, button)
            if not record['answer'].get('requested'):
                raise RuntimeError('journal period dialog was not answered')
            started = time.monotonic()
            while form.alive(window['hwnd']) and time.monotonic() - started < ACTION_WAIT_S:
                if self.stopped.wait(0.05):
                    break
            if form.alive(window['hwnd']):
                raise RuntimeError('journal period dialog did not close')
            record['period_closed'] = True
            record['after_period'] = self.round_trip(before_number - 1)
            record['calls'].append(dict(record['after_period'], number=before_number - 1))
            journal77.check_period(step, record)
        finally:
            if form.alive(window['hwnd']):
                button, _, issue = scenario77.answer_plan(dict(target=window['text'], button='Отмена'), window)
                record['period_cleanup'] = {'refused': issue} if issue else form.answer(window, button)

    def find_document(self, form, inspection, step, record):
        """Search the owned journal by keyboard, read each reference, open the exact match with Enter."""
        from form_window77 import expected_geometry, edged_ids, fit_units, judge_layout, judge_captions
        table = next(c for c in inspection["controls"] if c["id"] == scenario77.TABLE_WINDOW_ID)
        journal_handles = [w["hwnd"] for w in inspection["chain"][:2]]
        before = {w["hwnd"] for w in form.inventory()}
        record["focus"] = form.give_focus(inspection["chain"][0]["hwnd"], table["hwnd"])
        record["search"] = []
        record["calls"] = []
        for offset in range(step.get("limit", 100)):
            if self.stopped.is_set():
                raise RuntimeError("journal search cancelled")
            key = "end" if offset == 0 else "up"
            action = form.post_key(table["hwnd"], *scenario77.KEYS[key])
            row = {"action": action}
            record["search"].append(row)
            if not action.get("returned"):
                raise RuntimeError("journal navigation key could not be posted")
            trip = self.round_trip(-101000 - offset)
            row["round_trip"] = trip
            record["calls"].append(dict(trip, number=-101000 - offset))
            if (not trip.get("returned") or not trip.get("complete") or trip.get("diagnostics")
                    or trip.get("journal_error") or trip.get("journal_match") not in ("0", "1")
                    or "journal_current" not in trip or int(trip.get("journal_hwnd", "0")) not in journal_handles):
                raise RuntimeError("journal cursor/reference could not be verified: " + str(trip))
            if trip["journal_match"] == "1":
                break
        else:
            raise RuntimeError("document not found within journal search limit")
        if step.get('open') is False:
            record.update(cursor_verified=True, round_trip=trip)
            return inspection
        record["action"] = form.post_key(table["hwnd"], *scenario77.KEYS["enter"])
        if not record["action"].get("returned"):
            raise RuntimeError("journal Enter could not be posted")
        trip = self.round_trip(step["index"])
        record["round_trip"] = trip
        record["calls"].append(dict(trip, number=step["index"]))
        if (not trip.get("returned") or not trip.get("complete") or trip.get("diagnostics")
                or trip.get("journal_opened") != "1" or trip.get("journal_match") != "1"
                or not trip.get("journal_reference") or trip.get("journal_error")):
            raise RuntimeError("opened document reference mismatch: " + str(trip))
        description = self.created_description
        expected = expected_geometry(description)
        opened = form.inspect(list(expected))
        record["opened_form"] = opened
        if not opened.get("found"):
            raise RuntimeError("existing document form not found")
        opened["units"] = fit_units(expected, {c["id"]: tuple(c["rect"]) for c in opened["controls"]},
                                    edged=edged_ids(description))
        issues = judge_layout(description, opened) + judge_captions(description, opened)
        hwnd = int(trip.get("journal_hwnd", "0"))
        if issues or hwnd not in [w["hwnd"] for w in opened["chain"][:2]] or hwnd in before:
            raise RuntimeError("existing form identity/layout mismatch: " + str(issues))
        record["existing_form_verified"] = True
        return opened

    def copy_document(self, form, inspection, step, record):
        """Recheck the selected saved source, dispatch Copy, bind a fresh unsaved form."""
        import journal77
        import journal_copy77 as copying
        from form_window77 import Pending, expected_geometry, edged_ids, fit_units, judge_layout, judge_captions
        before = record['before_copy'] = self.round_trip(-108000 - step['index'])
        record['calls'] = [dict(before, number=-108000 - step['index'])]
        journal77.checked_cursor(before, inspection)
        if before.get('journal_deleted') not in ('0', '1'):
            raise RuntimeError('saved source deletion state missing')
        menu = record['menu'] = journal77.native_menu(form, inspection, copying.COPY_COMMAND, 'копировать')
        if not menu['enabled']:
            raise RuntimeError('native journal copy command disabled')
        record['before_windows'] = form.inventory()
        old = {w['hwnd'] for w in record['before_windows']}
        seen = form.top_windows()
        action = record['action'] = dict(requested=True, command=copying.COPY_COMMAND,
                                        hwnd=inspection['chain'][1]['hwnd'], posted=False,
                                        message='WM_COMMAND', identity_rechecked=True)
        pending = Pending(form, action['hwnd'], 0x111, copying.COPY_COMMAND, 0)
        started = time.monotonic()
        while not pending.done() and time.monotonic() - started < ACTION_WAIT_S:
            window = form.modal_window(seen)
            if window:
                record['unexpected_window'] = window
                button = scenario77.safe_button(window)
                record['unexpected_cleanup'] = form.answer(window, button) if button else {'refused': 'no safe answer'}
                raise RuntimeError('unexpected modal window during document copying')
            if self.stopped.wait(0.05):
                break
        action.update(pending.outcome or {})
        if not pending.done() or not action.get('returned'):
            raise RuntimeError('native copy command did not return')
        action['posted'] = True
        trip = record['round_trip'] = self.round_trip(step['index'])
        record['calls'].append(dict(trip, number=step['index']))
        copying.checked_new(trip)
        if trip['journal_source'] != before['journal_current'] or trip['journal_value'] != before['journal_value']:
            raise RuntimeError('copy changed persisted source/neighbors/count')
        description = self.created_description
        expected = expected_geometry(description)
        created = record['created_form'] = form.inspect(list(expected))
        if not created.get('found'):
            raise RuntimeError('copied document form not found')
        created['units'] = fit_units(expected, {c['id']: tuple(c['rect']) for c in created['controls']},
                                    edged=edged_ids(description))
        issues = judge_layout(description, created) + judge_captions(description, created)
        hwnd = int(trip.get('journal_hwnd', '0'))
        if issues or hwnd not in [w['hwnd'] for w in created['chain'][:2]] or hwnd in old:
            raise RuntimeError('copied form identity/layout mismatch: ' + str(issues))
        record['after_windows'] = form.inventory()
        record['new_form_verified'] = True
        return created

    def create_document(self, form, inspection, step, record):
        """Insert in the owned journal, answer its kind chooser, bind the new unsaved form."""
        import journal77
        from form_window77 import expected_geometry, edged_ids, fit_units, judge_layout, judge_captions
        table = next(c for c in inspection["controls"] if c["id"] == scenario77.TABLE_WINDOW_ID)
        before = {w["hwnd"] for w in form.inventory()}
        seen = form.top_windows()
        record["focus"] = form.give_focus(inspection["chain"][0]["hwnd"], table["hwnd"])
        record["action"] = form.post_key(table["hwnd"], *scenario77.KEYS["insert"])
        if not record["action"].get("returned"):
            raise RuntimeError("Insert could not be posted")
        started = time.monotonic()
        chooser = None
        while time.monotonic() - started < ACTION_WAIT_S:
            chooser = form.modal_window(seen)
            if chooser:
                break
            if self.stopped.wait(0.05):
                break
        record["kind_window"] = chooser
        if chooser is None:
            raise RuntimeError("no native document-kind chooser opened")
        record["kind_selection"] = journal77.select_kind(form, chooser, step["target"])
        if not record["kind_selection"]["answer"].get("requested"):
            raise RuntimeError("document-kind chooser was not answered")
        started = time.monotonic()
        while form.alive(chooser["hwnd"]) and time.monotonic() - started < ACTION_WAIT_S:
            if self.stopped.wait(0.05):
                break
        if form.alive(chooser["hwnd"]):
            raise RuntimeError("document-kind chooser did not close")
        record["round_trip"] = self.round_trip(step["index"])
        trip = record["round_trip"]
        if trip.get("journal_new") != "1" or trip.get("journal_error"):
            raise RuntimeError("new document context: " + str(trip))
        description = self.created_description
        expected = expected_geometry(description)
        created = form.inspect(list(expected))
        record["created_form"] = created
        if not created.get("found"):
            raise RuntimeError("new document form not found: " + str(created))
        created["units"] = fit_units(expected, {c["id"]: tuple(c["rect"]) for c in created["controls"]},
                                     edged=edged_ids(description))
        issues = judge_layout(description, created) + judge_captions(description, created)
        hwnd = int(trip.get("journal_hwnd", "0"))
        if issues or hwnd not in [w["hwnd"] for w in created["chain"][:2]] or hwnd in before:
            raise RuntimeError("new form identity/layout mismatch: " + str(issues))
        record["new_form_verified"] = True
        return created

    @staticmethod
    def form_presence(form, inspection):
        """Snapshot owned dialog/frame existence and visibility before reopening.

        Check the dialog and its own frame, excluding MDIClient and the main window:
        the harness may hide the main window while leaving the form open. Reopening
        requires both HWNDs gone; visibility alone is insufficient.
        """
        windows = []
        for entry in inspection["chain"][:2]:
            exists = form.alive(entry["hwnd"])
            windows.append(dict(form.state(entry["hwnd"]) if exists else {"hwnd": entry["hwnd"]}, exists=exists))
        return {"windows": windows, "open": bool(windows) and all(
            w["exists"] and w.get("ws_visible") is True for w in windows)}

    def settle(self, form, chain, step):
        """Once the action's message returned: ask 1C, then look for a window the action opened meanwhile.

        What the action posted (``#Закрыть`` of a form) runs in 1C's queue before the call, and a window it
        opens serves the call in its own loop (m-close, series 0c): the window is open when the call returns.
        """
        if chain.window is not None or not chain.record.get("returned"):
            return
        chain.trips.append(self.call(step))
        window = form.modal_window(chain.seen)
        if window is not None:
            chain.window = dict(window, after_return=True)
            chain.seen.add(window["hwnd"])
        if chain.window is None and chain.record.get("choice") and not chain.record.get("choice_checked"):
            # Enter may run the column's formula and its dialog chain first. Only then compare references.
            self.verify_choice(form, chain)

    def call(self, step):
        """The step's next call to 1C, numbered by ``trip_number``: its own number first."""
        count = self.calls.get(step["index"], 0)
        self.calls[step["index"]] = count + 1
        number = scenario77.trip_number(step["index"], count)
        return dict(self.round_trip(number), number=number)

    def begin(self, form, inspection, step, control, ids, windows):
        """The action of a step with its last message pending: the Chain after its return or first window."""
        seen = form.top_windows()
        if step["kind"] == "close_form":
            from form_window77 import Pending
            record = dict(message="WM_CLOSE", hwnd=control["hwnd"], identity_rechecked=True, requested=True)
            chain = Chain(form, record, Pending(form, control["hwnd"], 0x0010, 0, 0), seen, finish_click)
            chain.wait()
            return chain
        if step["kind"] == "choose":
            return self.begin_choice(form, inspection, step, control, seen)
        if step["kind"] in scenario77.ACTIONS and step["kind"] not in ("click", "input"):
            return self.begin_table(form, inspection, step, control, seen)
        if step["kind"] == "click":
            record, pending = form.click_pending(inspection, control["id"])
            finish = finish_click
        else:
            record, pending = form.enter_text(inspection, control["id"], step["text"],
                                              self.leave_to(form, step, ids, windows))
            finish = form.left
        chain = Chain(form, record, pending, seen, finish)
        if pending is not None:
            chain.wait()
        return chain

    def choice_call(self, step, stage):
        import choice77
        number = choice77.request(step["index"], stage)
        return dict(self.round_trip(number), number=number)

    def unexpected_form(self, form, chain, step, seen, next_step=None):
        """A nested choice opened by a raw key is not an answered dialog or a successful action."""
        import choice77
        windows = form.inventory()
        if step["kind"] == "add_row":
            expects_popup = next_step is not None and "catalog_caption" in next_step
            popup = choice77.catalog_popup(windows, seen, form.focused())
            if popup is not None:
                if not expects_popup:
                    chain.record["refused"] = "the catalog popup requires an immediate explicit choose"
                    chain.choice_window, chain.choice_step = popup, step
                    chain.record["nested_cleanup"] = self.cancel_choice(form, chain)
                    return
                state = chain.trips[-1]
                self.pending_choice = chain.record["pending_choice"] = dict(
                    popup, catalog_popup=True, row=state.get("row"))
                if not state.get("row") or state["row"] != state.get("rows"):
                    chain.record["refused"] = "catalog popup is not on the appended row"
                return
            if expects_popup:
                chain.record["refused"] = "the new row did not open a focused catalog popup"
                return
        frames = choice77.new_frames(windows, seen)
        if not frames:
            return
        import journal_basis77
        if journal_basis77.returned_journal(self, form, step, frames, chain):
            return
        choice, issue = choice77.choice_window(windows, seen)
        if issue is None and step["kind"] == "add_row" and next_step and next_step["kind"] == "choose":
            # The unchanged document form may begin the reference choice immediately on Insert.
            self.pending_choice = choice
            chain.record["pending_choice"] = choice
            return
        chain.record["refused"] = "an unexpected nested form opened: " + repr([w.get("text") for w in frames])
        if issue is None:
            chain.choice_window, chain.choice_step = choice, step
            chain.record["nested_cleanup"] = self.cancel_choice(form, chain)

    @staticmethod
    def choice_issue(trip):
        if not trip.get("returned") or not trip.get("complete"):
            return "1C did not complete the choice call: " + str(trip.get("error") or "no complete answer")
        if trip.get("diagnostics"):
            return "1C reported an error during choice: " + str(trip["diagnostics"][0])
        return trip.get("table_error")

    def wait_cell_editor(self, form, table, focus, editor, expected=None, record=None):
        from form_window77 import cell_editor_ready
        # The controller can report the new column while focus still belongs to
        # the 1CEDIT wrapper. Wait for its real text child, without reactivation.
        deadline = time.monotonic() + CELL_EDITOR_WAIT_S
        observations = []
        if record is not None:
            record["editor_wait"] = {"observations": observations, "ready": False}
        while True:
            ready = cell_editor_ready(focus, editor)
            observations.append({"focus": focus, "editor": editor, "ready": ready})
            if ready or (editor is not None and expected is not None and editor.get("id") != expected):
                if record is not None:
                    record["editor_wait"]["ready"] = ready
                return focus, editor
            if time.monotonic() >= deadline or self.stopped.wait(0.02):
                return focus, None
            focus = form.focused()
            editor = form.editor_of(focus, table)

    def begin_choice(self, form, inspection, step, table, seen):
        """F4 in a reference editor, position the verified choice list, then Enter or Escape (task 028)."""
        import choice77
        from form_window77 import Posted
        preopened, self.pending_choice = self.pending_choice, None
        if preopened is not None:
            # Save the old reference without activating the parent while its choice is open.
            trip = self.choice_call(step, 5)
            self.calls[step["index"]] = 1
        else:
            trip = self.call(step)
        chain = Chain(form, {"returned": False, "choice": True}, None, seen, finish_click)
        chain.before, chain.trips, chain.choice_step = trip, [trip], step
        issue = self.choice_issue(trip) or scenario77.required_row_issue(step, trip)
        if preopened is not None:
            chain.choice_window = preopened
            chain.record["choice_window"] = preopened
            if (trip.get("column") or "").casefold() != step["column"].casefold():
                issue = issue or "the open choice belongs to another column"
        if ("catalog_caption" in step and "row" not in step
                and (not preopened or not preopened.get("catalog_popup") or trip.get("row") != preopened["row"])):
            issue = issue or "catalog popup does not belong to the appended row"
        if "row" in step and preopened is not None:
            issue = issue or "F4 requires an existing row without a pending choice"
        focus = form.focused()
        editor = form.editor_of(focus, table["hwnd"])
        if "row" in step and not issue:
            focus, editor = self.wait_cell_editor(form, table["hwnd"], focus, editor,
                                                  expected=step["column_window"], record=chain.record)
            if ((trip.get("column") or "").casefold() != step["column"].casefold()
                    or not editor or not editor.get("visible") or not editor.get("enabled")):
                issue = "the current column or its editor was not verified before F4"
        if issue or (preopened is None and (editor is None or editor["id"] != step["column_window"])):
            chain.record["refused"] = issue or "the reference column's editor did not open"
            if preopened is not None:
                chain.record["choice_cleanup"] = self.cancel_choice(form, chain)
            return chain
        chain.record.update(editor=editor, focus_before=focus)
        if preopened is None:
            before_windows = form.inventory()
            record = form.post_key(focus["hwnd"], *scenario77.KEYS["f4"])
            chain.record.update(record)
            if "row" in step:
                chain.record["open_key"] = record
            chain.pending = Posted(record)
            chain.wait()
            # The posted F4 runs before the call, just as a table key does.
            chain.trips.append(self.call(step))
            modal = form.modal_window(chain.seen)
            if modal is not None:
                chain.window = modal
                chain.seen.add(modal["hwnd"])
                chain.record["refused"] = "an unexpected modal window opened instead of the choice form"
                return chain
            windows = form.inventory()
            old = {w["hwnd"] for w in before_windows}
            chain.record["choice_windows"] = [w for w in windows if w["hwnd"] not in old]
            if "row" in step:
                popup = choice77.catalog_popup(windows, old, form.focused())
                if popup is None:
                    chain.record["refused"] = "F4 did not open a focused catalog popup"
                    return chain
                chain.choice_window = dict(popup, catalog_popup=True, row=step["row"])
                issue = self.choice_issue(chain.trips[-1]) or scenario77.required_row_issue(step, chain.trips[-1])
                if issue:
                    chain.record["refused"] = issue
                    chain.record["choice_cleanup"] = self.cancel_choice(form, chain)
                    return chain
                choice = self.choose_catalog_window(form, chain, step, chain.choice_window)
                if choice is None:
                    return chain
            else:
                choice, issue = choice77.choice_window(windows, old)
                if issue:
                    chain.record["refused"] = issue
                    return chain
        elif preopened.get("catalog_popup"):
            choice = self.choose_catalog_window(form, chain, step, preopened)
            if choice is None:
                return chain
        else:
            choice = preopened
            chain.record["preopened"] = True
        chain.choice_window = choice
        chain.record["choice_window"] = choice
        try:
            focused = form.give_focus(choice["dialog"]["hwnd"], choice["list"]["hwnd"])
            if focused is None or not form.within(focused["hwnd"], choice["list"]["hwnd"]):
                raise RuntimeError("the choice list did not take the focus")
            positioned = self.choice_call(step, 1)
            chain.trips.append(positioned)
            issue = self.choice_issue(positioned)
            if issue:
                raise RuntimeError(issue)
            if positioned.get("choice_hwnd") != choice["frame"]["hwnd"]:
                raise RuntimeError("the active choice context belongs to another window")
            positioned = self.choice_call(step, 2)
            chain.trips.append(positioned)
            issue = self.choice_issue(positioned)
            if issue:
                raise RuntimeError(issue)
            current = self.choice_call(step, 3)
            chain.trips.append(current)
            issue = self.choice_issue(current)
            if issue or current.get("choice_ready") != 1:
                raise RuntimeError(issue or "the requested element did not become current in the choice list")
            chain.record["choice_current"] = current.get("choice_current")
            key = "escape" if step.get("cancel") else "enter"
            record = form.post_key(choice["list"]["hwnd"], *scenario77.KEYS[key])
            chain.record.update(record)
            chain.pending = Posted(record)
            chain.wait()
        except Exception as error:
            chain.record["refused"] = f"{type(error).__name__}: {error}"
            chain.record["choice_cleanup"] = self.cancel_choice(form, chain)
        return chain

    def choose_catalog_window(self, form, chain, step, popup):
        try:
            return self.open_catalog_choice(form, chain, step, popup)
        except Exception as error:
            chain.record["refused"] = f"{type(error).__name__}: {error}"
            chain.record["choice_cleanup"] = self.cancel_choice(form, chain)
            return None

    def open_catalog_choice(self, form, chain, step, popup):
        """Finish the native kind popup and hand off to the ordinary catalog choice."""
        import choice77
        windows = form.inventory()
        seen = {w["hwnd"] for w in windows}
        handles = {popup[k]["hwnd"] for k in ("frame", "list")}
        current = choice77.catalog_popup(windows, seen - handles, form.focused())
        if current is None or {w["hwnd"] for w in current.values()} != handles:
            raise RuntimeError("the catalog popup is no longer focused or owned")
        evidence = chain.record["catalog_selection"] = dict(popup=popup)
        choice77.select_catalog(form, popup, step["catalog_caption"], evidence)
        trip = self.call(step)
        chain.trips.append(trip)
        windows = form.inventory()
        choice, issue = choice77.choice_window(windows, seen)
        evidence["choice_windows"] = [w for w in windows if w["hwnd"] not in seen]
        if choice:
            chain.choice_window = choice
        evidence["popup_closed"] = not any(w["hwnd"] in handles and w["visible"] for w in windows)
        issue = self.choice_issue(trip) or scenario77.required_row_issue(step, trip) or issue
        if issue or not evidence["popup_closed"]:
            raise RuntimeError(issue or "the catalog popup did not close")
        return choice

    def cancel_choice(self, form, chain):
        """Cancel only the choice frame we identified, using its own list, then verify it closed."""
        choice = chain.choice_window
        record = {}
        try:
            if form.alive(choice["frame"]["hwnd"]):
                record["key"] = form.post_key(choice["list"]["hwnd"], *scenario77.KEYS["escape"])
                chain.trips.append(self.call(chain.choice_step))
            record["closed"] = not form.alive(choice["frame"]["hwnd"])
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
        return record

    def verify_choice(self, form, chain):
        step, record = chain.choice_step, chain.record
        record["choice_checked"] = True
        if not hasattr(chain, "choice_window") or record.get("refused"):
            return
        choice = chain.choice_window
        record["choice_closed"] = not form.alive(choice["frame"]["hwnd"])
        if not record["choice_closed"]:
            record["refused"] = "the choice form did not close"
            record["choice_cleanup"] = self.cancel_choice(form, chain)
            return
        trip = self.choice_call(step, 4)
        chain.trips.append(trip)
        issue = self.choice_issue(trip)
        record["choice_value"] = trip.get("choice_value")
        record["choice_verified"] = not issue and trip.get("choice_result") == 1
        if "catalog_caption" in step and trip.get("row") != chain.before.get("row"):
            record["choice_verified"] = False
            issue = issue or "the catalog returned to a different row"
        if "row" in step and (trip.get("rows") != chain.before.get("rows") or trip.get("state_error")):
            record["choice_verified"] = False
            issue = issue or "the table row count changed during the choice"
        if not record["choice_verified"]:
            record["refused"] = issue or ("cancelling changed the reference" if step.get("cancel")
                                           else "the returned reference differs from the requested element")

    def begin_table(self, form, inspection, step, table, seen):
        """The action of a table step (task 027): 1C first, then a key to the table part or the cell's editor.

        The step's own call reports the rows, the current row and column before the keys; for ``cell`` it
        also makes its column current and opens the editor (``Активизировать(<колонка>, 1)``). Then the text
        replaces the editor's and Enter ends the input; ``add_row`` is Insert, ``delete_row`` Delete and
        ``key`` its key, in the cell's editor if it has the focus, else in the table part. The keys are posted
        (``Posted``): 1C's message loop handles them as its keyboard (series 0).
        """
        from form_window77 import Posted
        trip = self.call(step)
        chain = Chain(form, {"returned": False}, None, seen, finish_click)
        chain.before, chain.trips = trip, [trip]
        if not trip.get("returned"):
            chain.record["refused"] = "1C did not answer before the step: " + str(trip.get("error"))
            return chain
        if trip.get("table_error"):
            chain.record["refused"] = "1C refused: " + trip["table_error"]
            return chain
        row_issue = scenario77.required_row_issue(step, trip)
        if row_issue:
            chain.record["refused"] = row_issue
            return chain
        dialog, hwnd = inspection["chain"][0]["hwnd"], table["hwnd"]
        focus = form.focused()
        record = {"focus_before": focus, "editor_before": form.editor_of(focus, hwnd)}
        if step["kind"] == "cell":
            current = trip.get("column") or ""
            if current.casefold() != step["column"].casefold():
                chain.record.update(record, refused=f"column {step['column']!r} did not become current: {current!r}")
                return chain
            focus, editor = self.wait_cell_editor(form, hwnd, focus, record["editor_before"],
                                                  expected=step["column_window"], record=record)
            record.update(focus_before=focus, editor_before=editor)
            if editor is None:
                chain.record.update(record, refused=f"no cell editor opened; the focus is {focus}")
                return chain
            if editor["id"] != step["column_window"] or not editor["visible"] or not editor["enabled"]:
                chain.record.update(record, refused=f"unexpected or unavailable editor for {step['column']!r}: {editor}")
                return chain
            typed = form.replace_text(focus["hwnd"], step["text"])
            record.update(typing=typed, target=focus["hwnd"], expected_editor=step.get("column_window"))
            if not typed["typed"]:
                chain.record.update(record, failed_stage="type", last_error=typed.get("last_error"))
                return chain
            record["focus_before_enter"] = form.focused()
            if not record["focus_before_enter"] or record["focus_before_enter"]["hwnd"] != focus["hwnd"]:
                chain.record.update(record, refused="cell focus changed before Enter")
                return chain
            target, key = focus["hwnd"], scenario77.KEYS["enter"]
        else:
            if record["editor_before"] is not None and step["kind"] in ("add_row", "delete_row"):
                focus = self.end_input(form, step, chain.trips, record, focus, hwnd)
                if record["input_ended"] is False:
                    chain.record.update(record, refused="the row's input did not end: a cell editor stays open")
                    return chain
                if "row" in step:
                    chain.before = chain.trips[-1]
                    row_issue = scenario77.required_row_issue(step, chain.before)
                    if row_issue:
                        chain.record.update(record, refused=row_issue)
                        return chain
            if focus is None or not form.within(focus["hwnd"], hwnd):
                focus = record["focus_given"] = form.give_focus(dialog, hwnd)
            target = focus["hwnd"] if focus and form.within(focus["hwnd"], hwnd) else hwnd
            key = scenario77.KEYS[{"add_row": "insert", "delete_row": "delete"}.get(step["kind"], step["target"].casefold())]
        chain.record = dict(record, **form.post_key(target, *key))
        chain.pending = Posted(chain.record)
        chain.wait()
        return chain

    def end_input(self, form, step, trips, record, focus, table):
        """End the input of a row before a row's step (task 027): Enter in the open cell editor, as the keyboard
        user does, until none is open, at most once a column; each Enter is followed by a call to 1C (``trips``).

        Insert or Delete in the editor would change its text, not the rows; Escape there cancels the new row
        1C still takes the input of (series 0), and Insert in the editor or the menu's «Новая строка» did
        nothing (series 0b). ``АктивизироватьСтроку`` of another row does not end it (series 1, r-rows).
        """
        enters = []
        for _ in range(len((self.description.get("browser") or {}).get("fields") or []) + 1):
            if form.editor_of(focus, table) is None:
                break
            enters.append(form.post_key(focus["hwnd"], *scenario77.KEYS["enter"]))
            trips.append(self.call(step))
            focus = form.focused()
        record.update(input_enters=enters, input_ended=form.editor_of(focus, table) is None)
        return focus

    def go_to_row(self, form, inspection, step, record, table):
        """A row step (task 027): the cursor to the row by Down and Up, as the keyboard user moves it.

        The step's own call reports the rows and the current row (and refuses a row the table lacks); the input
        of a new row ends first (``end_input``); then one key at a time, each followed by a call to 1C, until the
        current row is the step's, the cursor stops moving or as many keys as rows were pressed. Neither
        ``АктивизироватьСтроку`` nor ``ПолучитьСтрокуПоНомеру`` called from the controller moves the row a cell
        step types into (series 1c, 1d); the keys do while the main window is shown (series 1e).
        """
        trips = [self.call(step)]
        state = trips[0]
        if not state.get("returned") or state.get("table_error") or "row" not in state:
            return scenario77.merge_trips(trips)
        focus = form.focused()
        if form.editor_of(focus, table) is not None:
            focus = self.end_input(form, step, trips, record, focus, table)
            if record["input_ended"] is False:
                return scenario77.merge_trips(trips)
        if focus is None or not form.within(focus["hwnd"], table):
            focus = record["focus_given"] = form.give_focus(inspection["chain"][0]["hwnd"], table)
        keys, current = [], trips[-1].get("row")
        for _ in range(state.get("rows", 0) + 1):
            if current is None or current == step["target"]:
                break
            # Giving focus to the table can restore a cell editor instead of focusing the table itself.
            if focus is None or focus["hwnd"] != table:
                record["row_focus_missing"] = True
                break
            keys.append(form.post_key(table, *scenario77.KEYS["down" if current < step["target"] else "up"]))
            trips.append(self.call(step))
            if trips[-1].get("row") == current:
                break  # the cursor did not move
            current = trips[-1].get("row")
            focus = form.focused()
        record["row_keys"] = keys
        return scenario77.merge_trips(trips)

    @staticmethod
    def committed(form, chain):
        """A cell's input ended (task 027): after Enter the focus left its editor or another column is current."""
        record = chain.record
        if chain.window is not None or not record.get("returned") or "target" not in record:
            return
        focus = form.focused()
        column = (chain.trips[-1] if chain.trips else {}).get("column")
        record.update(focus_after=focus, column_after=column)
        record["committed"] = (focus is None or focus["hwnd"] != record["target"]
                               or (column or "").casefold() != (chain.before.get("column") or "").casefold())

    @staticmethod
    def opened(step, record, chain):
        """Record the window the chain waits in: the next dialog step's, or one no step expects."""
        if chain.window is not None:
            expected = step.get("dialogs", 0) > 0 if step["kind"] in scenario77.ACTIONS else not step["last"]
            record["modal" if expected else "unexpected"] = chain.window

    def dismiss(self, form, chain, step):
        """Close the open windows of a failed step with the safest answer until its action ends (task 026)."""
        closed = []
        for _ in range(DISMISS_LIMIT):
            window = chain.window
            if window is None:
                break
            entry = {"hwnd": window["hwnd"], "text": scenario77.dialog_text(window)}
            closed.append(entry)
            button = scenario77.safe_button(window)
            if button is None:
                entry["error"] = "no button closes the window"
                break
            try:
                entry["answer"] = form.answer(window, button)
                if not entry["answer"].get("requested"):
                    break
                chain.wait()
                self.settle(form, chain, step)
            except Exception as error:  # noqa: BLE001 - the evidence names what kept the window open
                entry["error"] = f"{type(error).__name__}: {error}"
                break
        return {"windows": closed, "open": chain.window is not None, "action_returned": chain.record.get("returned")}

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
        import step_exchange77
        failed = step_exchange77.failed_trip(self.out, run_id, number)
        if failed is not None:
            return failed
        request = self.out / scenario77.REQUEST
        temporary = self.out / (scenario77.REQUEST + ".tmp")
        done = self.out / f"form-step-{number}-done"
        if done.exists() or done.with_name(f'form-step-{number}.tmp').exists():
            return {"returned": False, "error": "step response already exists; refusing replay", "number": number}
        temporary.write_text(f"{run_id}:{number}", encoding="ascii")
        temporary.replace(request)
        started = time.monotonic()
        while not done.exists():
            if self.stopped.wait(0.02):
                return step_exchange77.failed_trip(self.out, run_id, number) or {"returned": False, "error": "the session ended"}
            if time.monotonic() - started > STEP_WAIT_S:
                return {"returned": False, "error": f"no answer in {STEP_WAIT_S} s"}
        record = {"returned": True, "elapsed_s": round(time.monotonic() - started, 3)}
        answer, retries, error = step_exchange77.read_answer(done, run_id, number)
        if error is not None:
            return {"returned": False, "error": "step exchange answer-read: " + error['error_description'],
                    "exchange_error": error, "exchange_retries": retries}
        if retries:
            record['exchange_retries'] = retries
        record['elapsed_s'] = round(time.monotonic() - started, 3)
        record.update(scenario77.answer(answer))
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
        self.journal_form = None
        self.return_form = None
        self.children_form = None

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
        if settings and settings["mode"] in ("journal", "journal_existing"):
            self.journal_form = configuration_description(base / "1Cv7.MD", settings["journal"])
        if settings:
            from harness77.metadata77 import Metadata
            metadata = Metadata((base / "1Cv7.MD").read_bytes())
            self.fixture_context = fixture77.context(name, settings, metadata)
            for step in scenario77.steps(self.parameters) or []:
                if "catalog_caption" in step and step["catalog"].casefold() not in metadata.objects()["Справочник"]:
                    raise ValueError("unknown choice catalog: " + step["catalog"])
                if step['kind'] == 'journal_children':
                    import journal_children77
                    journal_children77.validate_metadata(metadata, name, step)
                    self.children_form = configuration_description(base / '1Cv7.MD', step['journal'])
                    journal_children77.runtime_description(self.form[0], step)
                if step['kind'] == 'journal_basis':
                    field = metadata.attributes('Документ', name.split('.')[1]).get(step['link'].casefold())
                    if field is None or field.code != 'O' or (field.kind and field.kind.casefold() != step['source'].casefold()):
                        raise ValueError('journal_basis link must be a document attribute accepting the source kind')
                    import journal_basis77
                    self.form = (journal_basis77.runtime_description(self.form[0], step),
                                 dict(self.form[1], runtime_caption_expectations={step['caption_control']: step['caption_text']} if 'caption_control' in step else {}))
                    if step.get('return_journal'):
                        self.return_form = configuration_description(base / '1Cv7.MD', step['return_journal'])

    def commands(self, parameters, requested):
        parsed_steps = scenario77.steps(parameters)
        actions(parameters)
        name = form_object(parameters)
        settings = fixture77.options(parameters, name)
        if settings and settings["mode"] in ("journal", "journal_existing") and parsed_steps is None:
            raise ValueError("journal mode requires create or find_document steps")
        self.parameters = dict(parameters)
        commands = list(COMMANDS) + fixture77.commands(settings)
        if settings and settings.get("operations"):
            missing = [cmd for cmd in fixture77.commands(settings) if cmd not in requested]
            if missing:
                raise ValueError("fixture_operations requires declared platform tests: " + ", ".join(missing))
        if "post" in commands and "post" not in requested:
            raise ValueError("fixture_post requires a declared platform test with command post")
        if "verify" in commands and "verify" not in requested:
            raise ValueError("fixture_verify requires a declared platform test with command verify")
        unknown = [command for command in requested if command not in commands]
        if unknown:
            raise ValueError("unknown form command: " + ", ".join(unknown))
        return commands

    def controller(self, parameters):
        text = controller_text(parameters, self.fixture_context)
        steps = scenario77.steps(parameters)
        if steps is None:
            return text
        table = (self.form[0].get("browser") or {}) if self.form is not None else {}
        if any(scenario77.table_step(step) or step["kind"] == "key" for step in steps):
            if self.form is None:
                raise ValueError("table steps need a form of the configuration with a table part or a list")
            # The code of the table steps names their columns: resolved before 1C starts (task 027).
            steps = scenario77.resolve(steps, self.form[0])
        return scenario77.controller(text, steps, table=bool(table.get("document")),
                                     journal_kind=self.parameters["form_object"].split(".")[1]
                                     if self.journal_form is not None else None)

    def client(self, text):
        if text.count(CALL) != 1:
            raise ValueError("unexpected client layout: the ERT call is not found once")
        # Keep the platform's diagnostics when the generated controller itself does not compile.
        text = text.replace('If result <> 1 Then Fail "compile-controller", CStr(result)', '''If result <> 1 Then
    Dim controllerMessages
    Set controllerMessages = v.CreateObject("MessageView")
    controllerMessages.SetSystemMessages
    controllerMessages.SaveToFile fso.BuildPath(fso.GetParentFolderName(eventPath), "controller-errors.txt")
    Fail "compile-controller", CStr(result)
End If''')
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
        created_description = None
        if self.journal_form is not None:
            created_description = description
            atomic_json(self.run_dir / "form" / "created-description.json", description)
            description = self.journal_form[0]
            atomic_json(self.run_dir / "form" / "description.json", description)
            atomic_json(self.run_dir / "form" / "journal-source.json", self.journal_form[1])

        @contextlib.contextmanager
        def watching():
            watcher = FormWatcher(out, lifecycle, desktop, description, actions(self.parameters),
                                  self.run_dir / "form", visual_probe=self.parameters.get("visual_probe") is True,
                                  captures=self.requests, configuration=self.configuration, steps=steps,
                                  show=steps is not None and bool(description.get("browser")),
                                  created_description=created_description)
            if getattr(self, 'children_form', None):
                watcher.children_description = self.children_form[0]
                atomic_json(self.run_dir / 'form' / 'children-description.json', self.children_form[0])
                atomic_json(self.run_dir / 'form' / 'children-source.json', self.children_form[1])
            if getattr(self, 'return_form', None):
                watcher.return_description = self.return_form[0]
                atomic_json(self.run_dir / 'form' / 'return-journal-description.json', self.return_form[0])
                atomic_json(self.run_dir / 'form' / 'return-journal-source.json', self.return_form[1])
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
