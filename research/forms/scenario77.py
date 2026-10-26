"""Task 025: steps on an open form — read from the profile, resolved against the form, judged.

``[platform.parameters] steps`` is an array of TOML tables, one step each, with exactly one
key naming its kind:

- ``{ click = "<element>" }``, ``closes = true`` when the click closes the form;
- ``{ input = "<element>", text = "…" }``: go to the field, replace its text, leave it;
- ``{ check = "<element>", text | checked | enabled | visible = … }``: what the window shows;
- ``{ value = "<attribute>", text = "…" }``: ``Строка()`` of the attribute in the form's context;
- ``{ message = "…" }``, ``{ no_message = "…" }``: a line among 1C's messages since the last action.

An element is a control of the form's description: by identifier, else by caption without ``&``,
case-insensitive; exactly one of a class the step accepts. After every step the client calls the
controller once (``Harness77Step``): it saves the messages since the previous call, reads the
requested attribute and, being a call through 1C's message queue, comes after what the action
posted. Then the windows are read and the step judged. Everything here is portable; the windows
and the round trip are in form_launcher77 and form_window77.

Task 026 adds ``{ dialog = "<text>", button = "…", text = "…", closes = true }``: the modal window
an action opened (``Предупреждение``, ``Вопрос``, ``ВвестиСтроку``…), its text, the answer. Dialog
steps follow the action that opens the window, or another dialog step; the chain is one action,
and its messages, errors and closing belong to its last step.
"""

import re

KINDS = ("click", "input", "check", "value", "message", "no_message", "dialog")
OPTIONS = {"click": {"closes": bool}, "input": {"text": str}, "value": {"text": str},
           "check": {"text": str, "checked": bool, "enabled": bool, "visible": bool},
           "message": {}, "no_message": {}, "dialog": {"button": str, "text": str, "closes": bool}}
ACTIONS = ("click", "input")
# Classes of the description a step accepts; a text check reads any window.
CLASSES = {"click": ("BUTTON", "CHECKBOX"), "input": ("1CEDIT", "BMASKED"), "checked": ("CHECKBOX",)}
NAME = re.compile(r"[^\W\d]\w*\Z")
STEP_MARKER = "HARNESS77-STEP:"
REQUEST = "form-step-request"
VALUE, VALUE_ERROR = "value:", "value-error:"
# A modal window (task 026): its message is in static children, its answers are push buttons, its input
# field is an edit of Windows or of 1C. A failed scenario closes the window with the safest answer.
FIELD_CLASSES = ("edit", "1cedit", "bmasked")
PUSH_STYLES = (0, 1)  # BS_PUSHBUTTON, BS_DEFPUSHBUTTON: the low four bits of a button's style
SAFE_ANSWERS = (("отмена", "cancel"), ("нет", "no"))
IDCANCEL = 2
# A button's caption compares as it looks: the «OK» of 1C's warning is Latin (task 002), a scenario writes «ОК».
LOOKALIKES = str.maketrans("abcehkmoptxy", "авсенкмортху")


def _text(value, where, empty=True):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{where}: a {'' if empty else 'non-empty '}string")
    if "\0" in value or "\r" in value or "\n" in value:
        raise ValueError(f"{where}: one line without NUL")
    value.encode("cp1251")
    return value


def steps(parameters):
    """The validated steps of ``[platform.parameters]``, numbered from 1, or None without them."""
    value = parameters.get("steps")
    if value is None:
        return None
    if parameters.get("actions") is not None or parameters.get("click_id") is not None:
        raise ValueError("[platform.parameters] sets either steps or actions/click_id, not both")
    if not isinstance(value, list) or not value:
        raise ValueError("[platform.parameters] steps must be a non-empty array of tables")
    result, closed = [], None
    for number, item in enumerate(value, 1):
        where = f"step {number}"
        if not isinstance(item, dict):
            raise ValueError(f"{where}: a table such as {{ click = \"ОК\" }}")
        kinds = [key for key in item if key in KINDS]
        if len(kinds) != 1:
            raise ValueError(f"{where}: exactly one of {', '.join(KINDS)}, got {sorted(item)}")
        kind = kinds[0]
        unknown = set(item) - {kind} - set(OPTIONS[kind])
        if unknown:
            raise ValueError(f"{where} ({kind}): unknown keys {sorted(unknown)}")
        step = {"index": number, "kind": kind, "target": _text(item[kind], f"{where} {kind}", empty=False).strip()}
        for key, expected in OPTIONS[kind].items():
            if key in item:
                if not isinstance(item[key], expected):
                    raise ValueError(f"{where} ({kind}): {key} must be {'a string' if expected is str else 'true or false'}")
                step[key] = _text(item[key], f"{where} {key}") if expected is str else item[key]
        if kind in ("input", "value") and "text" not in step:
            raise ValueError(f"{where} ({kind}): text is required")
        if kind == "dialog" and "button" in step:
            if not step["button"].strip():
                raise ValueError(f"{where} (dialog): button is the caption of a button of the window")
            step["button"] = step["button"].strip()
        if kind == "check":
            expectations = [key for key in OPTIONS["check"] if key in step]
            if len(expectations) != 1:
                raise ValueError(f"{where} (check): exactly one of text, checked, enabled, visible")
            step["expect"] = expectations[0]
        if kind == "value" and not NAME.match(step["target"]):
            raise ValueError(f"{where} (value): an attribute name, got {step['target']!r}")
        if kind == "dialog":
            previous = result[-1] if result else None
            if previous is None or previous["kind"] not in ACTIONS + ("dialog",):
                raise ValueError(f"{where} (dialog): follows the click or input that opens the window, "
                                 "or another dialog step")
            if previous.get("closes"):
                raise ValueError(f"step {previous['index']} ({previous['kind']}): the form closes after the window; "
                                 "put closes on the last dialog step")
            step["chain"] = previous.get("chain", previous["index"])
            if previous["kind"] == "dialog":
                previous["last"] = False
            else:
                previous["dialogs"] = 0
            result[step["chain"] - 1]["dialogs"] += 1
            step["last"] = True
        if closed is not None and kind not in ("message", "no_message"):
            raise ValueError(f"{where} ({kind}): the form is closed at step {closed}; only message steps follow")
        if step.get("closes"):
            closed = number
        result.append(step)
    return result


def _caption(text):
    return (text or "").replace("&", "").strip().casefold()


def resolve(items, description):
    """Every element step with the record ID and class of its control; ValueError names the step."""
    controls = description["controls"]
    resolved = []
    for step in items:
        step = dict(step)
        if step["kind"] in ("click", "input", "check"):
            where = f"step {step['index']} ({step['kind']} {step['target']!r})"
            wanted = step["target"].casefold()
            found = [c for c in controls if (c.get("identifier") or "").casefold() == wanted] \
                or [c for c in controls if _caption(c.get("caption")) == wanted]
            if not found:
                raise ValueError(f"{where}: no element with this identifier or caption")
            if len(found) > 1:
                raise ValueError(f"{where}: {len(found)} elements match: " + ", ".join(str(c["id"]) for c in found))
            control = found[0]
            classes = CLASSES.get(step["kind"]) or CLASSES.get(step.get("expect"))
            if classes and control["class"] not in classes:
                raise ValueError(f"{where}: element {control['id']} is {control['class']}, the step needs "
                                 + " or ".join(classes))
            step.update(record_id=control["id"], element_class=control["class"])
        resolved.append(step)
    return resolved


def normalized(text):
    """Text with every run of spaces and line breaks as one space: a window wraps its message itself."""
    return " ".join((text or "").split())


def _children(window, classes):
    return [c for c in window.get("children") or []
            if c.get("parent") in (None, window.get("hwnd")) and (c.get("class") or "").casefold() in classes]


def buttons(window):
    """The push buttons of a modal window, in its order (check boxes and radio buttons are buttons too)."""
    return [c for c in _children(window, ("button",)) if c.get("visible", True)
            and (c.get("style") is None or c["style"] & 0x0F in PUSH_STYLES)]


def dialog_text(window):
    """What a modal window shows: its message (the texts of its static children), else its title."""
    message = normalized(" ".join(c.get("text") or "" for c in _children(window, ("static",))))
    return message or normalized(window.get("text"))


def describe_window(window):
    """The window for a reason: its text and the captions of its buttons."""
    return f"{dialog_text(window)!r} with buttons {[_caption_shown(b) for b in buttons(window)]}"


def _caption_shown(button):
    return (button.get("text") or "").replace("&", "")


def _button(text):
    return _caption(text).translate(LOOKALIKES)


def answer_plan(step, window):
    """(button, field, issue) of a dialog step in its window: the button to press, the field for ``text``.

    The window matches by its message or its title; the button by caption without ``&``, case-insensitive,
    Latin and Cyrillic lookalikes alike, or the only one; the field is the window's single input field.
    ``issue`` says why the step fails.
    """
    wanted = normalized(step["target"])
    if wanted not in (dialog_text(window), normalized(window.get("text"))):
        return None, None, f"the window shows {describe_window(window)}"
    choices = buttons(window)
    if "button" in step:
        found = [b for b in choices if _button(b.get("text")) == _button(step["button"])]
        if len(found) != 1:
            return None, None, (f"{len(found)} buttons {step['button']!r}" if found else
                                f"no button {step['button']!r} among {[_caption_shown(b) for b in choices]}")
    elif len(choices) != 1:
        return None, None, f"the window has buttons {[_caption_shown(b) for b in choices]}; name one with button"
    else:
        found = choices
    field = None
    if "text" in step:
        fields = _children(window, FIELD_CLASSES)
        if len(fields) != 1:
            return None, None, f"the window has {len(fields)} input fields, text needs one"
        field = fields[0]
    return found[0], field, None


def safe_button(window):
    """The answer that closes a window a scenario did not expect: «Отмена», else «Нет», else the only button."""
    choices = buttons(window)
    for captions in SAFE_ANSWERS:
        found = [b for b in choices if _button(b.get("text")) in {_button(c) for c in captions}]
        if found:
            return found[0]
    if len(choices) == 1:
        return choices[0]
    return next((b for b in choices if b.get("id") == IDCANCEL), None)


def step_function(items):
    """``Harness77Step`` of the controller: messages of the step and the requested attribute."""
    branches = "".join(f'''    Если Номер77Шага = {step["index"]} Тогда
        Попытка
            Ответ77 = "{VALUE}" + Harness77Строка(Контекст77Формы.{step["target"]});
        Исключение
            Ответ77 = "{VALUE_ERROR}" + ОписаниеОшибки();
        КонецПопытки;
    КонецЕсли;
''' for step in items if step["kind"] == "value")
    return f'''Функция Harness77Строка(Значение77)
    Возврат СтрЗаменить(СтрЗаменить(Строка(Значение77), "\\", "\\\\"), РазделительСтрок, "\\n");
КонецФункции

Функция Harness77Step(Номер77Шага, Протокол, Метка) Экспорт
    Сообщения77 = СоздатьОбъект("MessageView");
    Сообщения77.SetSystemMessages();
    Ответ77 = "";
{branches}    Сообщить("{STEP_MARKER}" + Метка);
    Сообщения77.SaveToFile(Протокол);
    Сообщения77.Clear();
    Возврат Ответ77;
КонецФункции

'''


SAVE = "    Сообщения77.SaveToFile(Протокол);\n    Возврат Ответ77;\nКонецФункции\n"


def controller(text, items):
    """The form controller with the step function; ``open`` clears the messages it saved."""
    if text.count(SAVE) != 1 or text.count("Функция Harness77Ert(") != 1:
        raise ValueError("unexpected form controller layout for steps")
    text = text.replace(SAVE, SAVE.replace("    Возврат", '    Если Команда = "open" Тогда\n'
                                                     "        Сообщения77.Clear();\n    КонецЕсли;\n    Возврат", 1))
    return text.replace("Функция Harness77Ert(", step_function(items) + "Функция Harness77Ert(", 1)


# The client's wait before ``result`` (task 008) serves the watcher's step requests meanwhile: each
# request is one controller call, its answer a UTF-16 file the watcher waits for. The wait for the
# end restarts after every served step.
CLIENT = """
Sub AwaitClick()
    Dim donePath, requestPath, waitStarted, request, number, answer, stream, folder, answerPath
    folder = fso.GetParentFolderName(eventPath)
    donePath = fso.BuildPath(folder, "__DONE__")
    requestPath = fso.BuildPath(folder, "__REQUEST__")
    waitStarted = CDbl(Timer)
    Do While Not fso.FileExists(donePath)
        If fso.FileExists(requestPath) Then
            Set stream = fso.OpenTextFile(requestPath, 1)
            request = stream.ReadLine
            stream.Close
            fso.DeleteFile requestPath
            CheckCOM "step-request"
            If Left(request, Len(runId) + 1) <> runId & ":" Then Fail "step-request", "foreign step request"
            number = CLng(Mid(request, Len(runId) + 2))
            answer = controller.Harness77Step(number, fso.BuildPath(fso.GetParentFolderName(evidencePath), _
                "step-" & number & ".txt"), runId & ":step:" & number)
            CheckCOM "step-" & number
            answerPath = fso.BuildPath(folder, "form-step-" & number)
            Set stream = fso.CreateTextFile(answerPath & ".tmp", True, True)
            stream.Write CStr(answer)
            stream.Close
            fso.MoveFile answerPath & ".tmp", answerPath & "-done"
            CheckCOM "step-answer"
            Emit "phase", "step-" & number, "ok", Elapsed(waitStarted)
            waitStarted = CDbl(Timer)
        End If
        WScript.Sleep 20
        If Elapsed(waitStarted) > __WAIT_MS__ Then
            Emit "phase", "click-wait", "timeout", Elapsed(waitStarted)
            Exit Sub
        End If
    Loop
    Emit "phase", "click-wait", "ok", Elapsed(waitStarted)
End Sub
"""


def client(done, wait_ms):
    return CLIENT.replace("__DONE__", done).replace("__REQUEST__", REQUEST).replace("__WAIT_MS__", str(wait_ms))


def answer(text):
    """{value | value_error} of the controller's answer to a step."""
    if text.startswith(VALUE):
        return {"value": _unescape(text[len(VALUE):])}
    if text.startswith(VALUE_ERROR):
        return {"value_error": text[len(VALUE_ERROR):].strip()}
    return {}


def _unescape(text):
    out, index = [], 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text) and text[index + 1] in "\\n":
            out.append("\\" if text[index + 1] == "\\" else "\r\n")
            index += 2
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def trip_number(index, count):
    """The number of the ``count``-th call to 1C of step ``index`` (from 0): the step's own number first.

    A chain asks 1C after its action returned and again after every window answered then (task 026);
    each call saves its own protocol and answer, and only the step's own number reads a value.
    """
    return index + 1000 * count


def merge_trips(trips):
    """The calls to 1C of one chain as one: all returned and complete, their messages and errors in order."""
    if not trips:
        return {"returned": False, "error": "1C was not asked"}
    merged = {"returned": all(t.get("returned") for t in trips), "complete": all(t.get("complete") for t in trips),
              "messages": [line for t in trips for line in t.get("messages") or []],
              "diagnostics": [d for t in trips for d in t.get("diagnostics") or []], "calls": len(trips)}
    error = next((t["error"] for t in trips if t.get("error")), None)
    if error:
        merged["error"] = error
    return merged


def messages(protocol, marker):
    """(lines, complete) of a step's saved messages: everything before its own marker line."""
    lines = protocol.splitlines()
    complete = bool(lines) and lines[-1] == STEP_MARKER + marker
    return (lines[:-1] if complete else lines), complete


def judge(step, record, pending, form_open):
    """The issue of one executed step, or None; ``record`` holds what happened and what the windows show.

    ``pending`` are the message lines since the last action, this step's included.
    """
    name = f"step {step['index']} ({step['kind']} {step['target']!r})"
    action = record.get("action") or {}
    if action.get("refused"):
        return f"{name}: {action['refused']}"
    if record.get("unexpected"):
        return f"{name}: an unexpected modal window {describe_window(record['unexpected'])}"
    if step["kind"] == "dialog":
        if record.get("window") is None:
            return f"{name}: no modal window opened"
        answer = record.get("answer") or {}
        if answer.get("refused"):
            return f"{name}: {answer['refused']}"
        if not answer.get("requested"):
            return f"{name}: the window was not answered: {answer.get('error') or 'no answer'}"
        if not step["last"]:
            return None  # the next dialog step judges the next window
    elif record.get("modal") is not None:
        return None  # the action opened the window its dialog steps answer; they judge the rest
    if step["kind"] in ACTIONS or step["kind"] == "dialog":
        if not action.get("returned"):
            after = " after the window closed" if step["kind"] == "dialog" else ""
            if action.get("failed_stage"):
                return (f"{name}: {action['failed_stage']} failed{after}: "
                        + (action.get("reason") or "the message did not return"))
            return f"{name}: {action.get('message') or 'the message'} did not return{after}"
    trip = record.get("round_trip") or {}
    if not trip.get("returned"):
        return f"{name}: 1C did not answer after the step: {trip.get('error') or 'no answer'}"
    if not trip.get("complete"):
        return f"{name}: the step's messages were not saved completely"
    if trip.get("diagnostics"):
        first = trip["diagnostics"][0]
        return f"{name}: 1C reported an error: line {first['line']}: {first['message']}"
    if step.get("closes") and form_open:
        return f"{name}: the form did not close"
    if not form_open and not step.get("closes") and step["kind"] not in ("message", "no_message"):
        return f"{name}: the form closed"
    if step["kind"] == "check":
        shown = record.get("state") or {}
        key = step["expect"]
        if "error" in shown:
            return f"{name}: the window was not read: {shown['error']}"
        actual, wanted = shown.get(key), step[key]
        if key == "text":
            if (actual or "").strip() != wanted.strip():
                return f"{name}: shows {actual!r}, expected {wanted!r}"
        elif actual is not wanted:
            return f"{name}: {key} is {actual}, expected {wanted}"
    if step["kind"] == "value":
        if "value_error" in trip:
            return f"{name}: 1C did not read the attribute: {trip['value_error']}"
        if "value" not in trip:
            return f"{name}: no value in 1C's answer"
        if trip["value"].strip() != step["text"].strip():
            return f"{name}: is {trip['value']!r}, expected {step['text']!r}"
    if step["kind"] in ("message", "no_message"):
        found = any(line.strip() == step["target"] for line in pending)
        if step["kind"] == "message" and not found:
            return f"{name}: no such message among {pending!r}"
        if step["kind"] == "no_message" and found:
            return f"{name}: the message is there"
    return None


def judge_result(items, records, closed_by_controller):
    """Issues of the scenario for ``result``: every step ran and passed, the form is closed."""
    issues = []
    records = records or []
    failed = next((r for r in records if r.get("issue")), None)
    if failed is not None:
        issues.append(failed["issue"])
    elif len(records) != len(items):
        issues.append(f"only {len(records)} of {len(items)} steps ran")
    closed_by_step = any(r.get("closes") and r.get("form_open") is False for r in records)
    if not (closed_by_controller or closed_by_step):
        issues.append("the form was not closed")
    return issues
