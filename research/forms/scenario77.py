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
"""

import re

KINDS = ("click", "input", "check", "value", "message", "no_message")
OPTIONS = {"click": {"closes": bool}, "input": {"text": str}, "value": {"text": str},
           "check": {"text": str, "checked": bool, "enabled": bool, "visible": bool},
           "message": {}, "no_message": {}}
ACTIONS = ("click", "input")
# Classes of the description a step accepts; a text check reads any window.
CLASSES = {"click": ("BUTTON", "CHECKBOX"), "input": ("1CEDIT", "BMASKED"), "checked": ("CHECKBOX",)}
NAME = re.compile(r"[^\W\d]\w*\Z")
STEP_MARKER = "HARNESS77-STEP:"
REQUEST = "form-step-request"
VALUE, VALUE_ERROR = "value:", "value-error:"


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
        if kind == "check":
            expectations = [key for key in OPTIONS["check"] if key in step]
            if len(expectations) != 1:
                raise ValueError(f"{where} (check): exactly one of text, checked, enabled, visible")
            step["expect"] = expectations[0]
        if kind == "value" and not NAME.match(step["target"]):
            raise ValueError(f"{where} (value): an attribute name, got {step['target']!r}")
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
    if step["kind"] in ACTIONS and not action.get("returned"):
        if action.get("failed_stage"):
            return f"{name}: {action['failed_stage']} failed: {action.get('reason') or 'the message did not return'}"
        return f"{name}: {action.get('message') or 'the message'} did not return"
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
