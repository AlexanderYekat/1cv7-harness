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

Task 027 adds the table part of a document's form: ``{ add_row = true }``, ``{ row = 2 }``,
``{ cell = "<column>", text = "…" }``, ``{ delete_row = true }``, ``{ rows = 2 }``,
``{ total = "<column>", text = "…" }``, ``row = 2`` of a value step, and ``{ key = "Down" }`` in a
table part or a list. A column is one of the Browser section's, by identifier or caption. The
controller reports the rows, the current row and column with every call of a table step.

Task 033 adds ``{ reopen = true }`` for an existing document fixture: 1C++ closes
without saving; the watcher requires the old HWNDs gone, then the controller opens
the same saved reference. Subsequent steps resolve against the newly inspected windows.

Task 034 starts journal mode with ``{ create = "<native kind caption>" }``:
Insert, the native kind chooser, a new unsaved owned form. ``{ created = true }``
captures and reads its reference after UI save, before closing or reopening.

Task 035 adds ``find_document = true`` to start journal_existing: bounded End/Up
navigation, exact saved reference check, Enter and a fresh owned document form.
``close_form = true`` sends WM_CLOSE to the inspected MDI frame; dialog steps
answer its save question.
"""

import re

KINDS = ("click", "input", "check", "value", "message", "no_message", "dialog",
         "add_row", "row", "cell", "delete_row", "rows", "total", "key", "choose", "reopen", "create", "created", "find_document", "close_form", "journal_period", "journal_unpost", "journal_deletion", "journal_copy", "journal_basis", "journal_children", "tab")
OPTIONS = {"tab": {"browser_visible": bool}, "click": {"closes": bool}, "input": {"text": str}, "value": {"text": str, "row": int},
           "check": {"text": str, "checked": bool, "enabled": bool, "visible": bool},
           "message": {}, "no_message": {}, "dialog": {"button": str, "text": str, "closes": bool},
           "add_row": {}, "row": {}, "cell": {"text": str, "row": int}, "delete_row": {}, "rows": {}, "total": {"text": str},
           "key": {"closes": bool}, "choose": {"text": str, "cancel": bool}, "reopen": {"caption_control": str, "caption_text": str}, "create": {}, "created": {},
           "find_document": {"limit": int, "open": bool}, "close_form": {"closes": bool},
           "journal_period": {"start": str, "end": str, "cancel": bool},
           "journal_unpost": {"cancel": bool, "enabled": bool, "expected": str},
           "journal_deletion": {"deleted": bool, "cancel": bool, "expected": str},
           "journal_children": {"source": str, "link": str, "reference": int, "cancel": bool, "empty": bool, "limit": int, "kinds": str, "edit": bool, "browse": bool, "expected_after": str,
                                "journal": str, "expected": str, "caption_control": str, "caption_text": str, "browser_visible": bool},
           "journal_copy": {}, "journal_basis": {"source": str, "link": str, "cancel": bool, "caption_control": str, "caption_text": str, "return_journal": str}}
ACTIONS = ("click", "input", "add_row", "cell", "delete_row", "key", "choose", "close_form")
# Steps of the table part of a document's form (task 027); key also works in a list.
TABLE_KINDS = ("add_row", "row", "cell", "delete_row", "rows", "total", "choose")
COLUMN_KINDS = ("cell", "total", "choose")
# Keys of a table part or a list: (virtual-key code, extended); F2…F9 are 0x71…0x78.
KEYS = {"insert": ("Insert", 0x2D, True), "delete": ("Delete", 0x2E, True), "enter": ("Enter", 0x0D, False),
        "escape": ("Escape", 0x1B, False), "tab": ("Tab", 0x09, False), "up": ("Up", 0x26, True),
        "down": ("Down", 0x28, True), "left": ("Left", 0x25, True), "right": ("Right", 0x27, True),
        "home": ("Home", 0x24, True), "end": ("End", 0x23, True), "pageup": ("PageUp", 0x21, True),
        "pagedown": ("PageDown", 0x22, True)} | {f"f{n}": (f"F{n}", 0x6F + n, False) for n in range(2, 10)}
# The table part's window (task 022) and the number column, which takes no input; the type codes of the
# columns a cell step types into: string, number, date.
TABLE_WINDOW_ID, LINE_NUMBER, TYPED = 4151, "НомерСтроки", ("S", "N", "D")
TABLE_ERROR = "error:"
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
        others = [key for key in kinds if key != "row"]
        if len(kinds) == 2 and len(others) == 1 and "row" in OPTIONS[others[0]]:
            kinds = others  # row is an option of value/cell when another step kind names it
        if len(kinds) != 1:
            raise ValueError(f"{where}: exactly one of {', '.join(KINDS)}, got {sorted(item)}")
        kind = kinds[0]
        unknown = set(item) - {kind} - set(OPTIONS[kind])
        if unknown:
            raise ValueError(f"{where} ({kind}): unknown keys {sorted(unknown)}")
        step = {"index": number, "kind": kind, "target": _target(kind, item[kind], where)}
        for key, expected in OPTIONS[kind].items():
            if key in item:
                if expected is int:
                    step[key] = _number(item[key], f"{where} ({kind}) {key}", 1)
                    continue
                if not isinstance(item[key], expected):
                    raise ValueError(f"{where} ({kind}): {key} must be {'a string' if expected is str else 'true or false'}")
                step[key] = _text(item[key], f"{where} {key}") if expected is str else item[key]
        if kind in ("input", "value", "cell", "total") and "text" not in step:
            raise ValueError(f"{where} ({kind}): text is required")
        if kind == "choose" and not (("text" in step and step["text"].strip() and "cancel" not in step)
                                      or (step.get("cancel") is True and "text" not in step)):
            raise ValueError(f"{where} (choose): either non-empty text or cancel = true")
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
        if kind == "reopen":
            import journal_basis77
            journal_basis77.validate_caption(step)
            if 'caption_control' in step and not any(s['kind'] == 'journal_basis' or (s['kind'] == 'journal_children' and (s.get('edit') or s.get('browse'))) for s in result):
                raise ValueError('reopen runtime caption requires journal_basis or editable journal_children')
            if not result or result[-1]["kind"] == "reopen":
                raise ValueError(f"{where} (reopen): requires a preceding scenario action or check")
            if (not isinstance(parameters.get("form_object"), str)
                    or not re.fullmatch(r"Документ\.[^\W\d]\w*", parameters["form_object"], re.IGNORECASE)
                    or (parameters.get("fixture_mode", "existing") not in ("existing", "journal_existing") and not
                        (parameters.get("fixture_mode") == "journal" and any(s["kind"] == "created" for s in result)))
                    or not parameters.get("fixture_setup") or not parameters.get("fixture_verify")):
                raise ValueError(f"{where} (reopen): requires an existing document fixture with verification")
            closed = None
        if kind == "journal_period":
            import journal77
            journal77.validate_period(parameters, result, step)
        if kind in ('journal_unpost', 'journal_deletion'):
            if any(s['kind'] in ('journal_copy', 'journal_basis') and not s.get('cancel') for s in result):
                raise ValueError('journal commands cannot follow the transition to a copied document form')
            if not any(s['kind'] == 'find_document' and s.get('open') is False for s in result) or not step.get('expected'):
                raise ValueError(kind + ' requires find_document open=false and expected readback')
            if kind == 'journal_deletion' and 'deleted' not in step:
                raise ValueError('journal_deletion requires explicit deleted = true/false')
        if kind == 'journal_children':
            import journal_children77
            journal_children77.validate(parameters, result, step)
            if 'kinds' in step:
                step['target_kind'] = parameters['form_object'].split('.')[1]
        if kind == 'journal_basis':
            import journal_basis77
            journal_basis77.validate(parameters, result, step)
        if kind == 'journal_copy':
            import journal_copy77
            journal_copy77.validate(parameters, result)
        if (any(s['kind'] == 'find_document' and s.get('open') is False for s in result)
                and not any((s['kind'] in ('journal_copy', 'journal_basis') and not s.get('cancel')) or (s['kind'] == 'journal_children' and (s.get('edit') or s.get('browse'))) for s in result)
                and kind not in ('journal_unpost', 'journal_deletion', 'journal_copy', 'journal_basis', 'journal_children')):
            raise ValueError('only journal commands may follow a journal cursor selection')
        if kind == "find_document":
            import journal77
            journal77.validate(parameters, parameters.get("form_object"))
            if parameters.get("fixture_mode") != "journal_existing" or not parameters.get("fixture_setup") or any(s['kind'] != 'journal_period' for s in result):
                raise ValueError(f"{where}: find_document must start journal_existing with fixture_setup")
            if step.get("limit", 100) > 200:
                raise ValueError(f"{where}: find_document limit must be 1…200")
        if kind in ("create", "created"):
            import journal77
            journal77.validate(parameters, parameters.get("form_object"))
            copy_capture = kind == 'created' and any(s['kind'] in ('journal_copy', 'journal_basis') and not s.get('cancel') for s in result)
            if (parameters.get("fixture_mode") != ("journal_existing" if copy_capture else "journal")
                    or not parameters.get("fixture_setup")):
                raise ValueError(f"{where}: requires journal mode and fixture_setup")
            if kind == "create" and result:
                raise ValueError(f"{where}: create must be the first step")
            if kind == "created" and (not result or not any(s["kind"] in ("create", "journal_copy", "journal_basis") for s in result)):
                raise ValueError(f"{where}: created requires an earlier create")
        if kind == 'reopen' and any(s['kind'] in ('journal_copy', 'journal_basis') and not s.get('cancel') for s in result) and not any(s['kind'] == 'created' for s in result):
            raise ValueError('copied document must be captured with created before reopen')
        if closed is not None and kind not in ("message", "no_message"):
            raise ValueError(f"{where} ({kind}): the form is closed at step {closed}; only message steps follow")
        if step.get("closes"):
            closed = number
        result.append(step)
    if parameters.get("fixture_mode") == "journal" and result[0]["kind"] != "create":
        raise ValueError("journal mode requires create as its first step")
    if parameters.get("fixture_mode") == "journal_existing" and not any(s['kind'] == 'find_document' for s in result):
        raise ValueError("journal_existing requires find_document as its first step")
    editing = [s for s in result if s['kind'] == 'journal_children' and s.get('edit')]
    if editing:
        tail = result[editing[0]['index']:]
        if len(editing) != 1 or not any(s['kind'] == 'reopen' for s in tail):
            raise ValueError('editable journal_children requires one handoff and subsequent reopen')
        if any(s['kind'] in ('journal_period', 'find_document', 'journal_children', 'journal_copy', 'journal_basis', 'journal_unpost', 'journal_deletion', 'created', 'create') for s in tail):
            raise ValueError('editable journal_children tail requires document form steps only')
    viewing = [s for s in result if s['kind'] == 'journal_children' and s.get('browse')]
    if viewing:
        tail = result[viewing[0]['index']:]
        if len(viewing) != 1 or not tail or not any(s['kind'] == 'tab' for s in tail):
            raise ValueError('browse journal_children requires one handoff and tab steps')
        if any(s['kind'] not in ('tab', 'check', 'value', 'rows', 'total') for s in tail):
            raise ValueError('browse journal_children allows only read-only form steps')
    return result


def _number(value, where, least):
    if isinstance(value, bool) or not isinstance(value, int) or not least <= value <= 99999:
        raise ValueError(f"{where}: a number {least}…99999, got {value!r}")
    return value


def _target(kind, value, where):
    """The value of a step's kind: true for add_row and delete_row, a number for row and rows, a key name for key."""
    if kind in ("add_row", "delete_row", "reopen", "created", "find_document", "close_form", "journal_period", "journal_unpost", "journal_deletion", "journal_copy", "journal_children"):
        if value is not True:
            raise ValueError(f"{where} ({kind}): write {kind} = true")
        return kind
    if kind in ("row", "rows"):
        return _number(value, f"{where} ({kind})", 1 if kind == "row" else 0)
    text = _text(value, f"{where} {kind}", empty=False).strip()
    if kind == "key":
        if text.casefold() not in KEYS:
            raise ValueError(f"{where} (key): one of {', '.join(name for name, _, _ in KEYS.values())}, got {text!r}")
        return KEYS[text.casefold()][0]
    return text


def _caption(text):
    return (text or "").replace("&", "").strip().casefold()


def table_step(step):
    """The step works with the table part of a document's form (task 027)."""
    return step["kind"] in TABLE_KINDS or (step["kind"] == "value" and "row" in step)


def column(step, table):
    """The column of a cell or total step among the table part's fields, by identifier then caption."""
    where = f"step {step['index']} ({step['kind']} {step['target']!r})"
    wanted = step["target"].casefold()
    fields = table.get("fields") or []
    found = [f for f in fields if (f.get("identifier") or "").casefold() == wanted] \
        or [f for f in fields if _caption(f.get("caption")) == wanted]
    if not found:
        raise ValueError(f"{where}: no column of the table part with this identifier or caption")
    if len(found) > 1:
        raise ValueError(f"{where}: {len(found)} columns match: " + ", ".join(f["identifier"] or f["caption"] for f in found))
    field = found[0]
    if step["kind"] == "total" and not NAME.match(field.get("identifier") or ""):
        raise ValueError(f"{where}: the column has no attribute to total")
    if step["kind"] == "cell" and (field["class"] not in CLASSES["input"] or field["identifier"] == LINE_NUMBER
                                   or not NAME.match(field.get("identifier") or "")):
        raise ValueError(f"{where}: column {field['identifier'] or field['caption']!r} is {field['class']}, "
                         "the step needs a field of an attribute (1CEDIT or BMASKED)")
    if step["kind"] == "cell" and field.get("type") not in (None,) + TYPED:
        # A reference is chosen in a form of its own (F4, selection), which the steps do not open.
        raise ValueError(f"{where}: column {field['identifier']!r} holds a reference ({field['type']}); "
                         "text goes into a string, number or date column")
    if step["kind"] == "choose" and (field.get("type") != "B" or not field.get("kind")
                                     or field["class"] not in CLASSES["input"] or not NAME.match(field["identifier"] or "")):
        raise ValueError(f"{where}: choose needs a column of a named catalog reference")
    return field


def resolve(items, description):
    """Every element step with the record ID and class of its control; ValueError names the step.

    A step of the table part needs a document's form with one (task 027); a column step gets its column.
    """
    controls = description["controls"]
    table = description.get("browser")
    resolved = []
    for step in items:
        step = dict(step)
        where = f"step {step['index']} ({step['kind']})"
        if step["kind"] == "key" and not table:
            raise ValueError(f"{where}: the form has no table part or list")
        if table_step(step):
            if not table:
                raise ValueError(f"{where}: the form has no table part")
            if not table.get("document"):
                raise ValueError(f"{where}: only the table part of a document's form; a list takes key steps")
        if step["kind"] in COLUMN_KINDS:
            field = column(step, table)
            step.update(column=field["identifier"], column_class=field["class"], column_window=field.get("window_id"))
            if step["kind"] == "choose":
                step["catalog"] = field["kind"]
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


def _literal(text):
    return '"' + text.replace('"', '""') + '"'


def _branch(number, body):
    return f'''    Если Номер77Шага = {number} Тогда
        Попытка
{body}        Исключение
            Ответ77 = "{TABLE_ERROR}" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
'''


def _table_branch(step):
    """What the controller does for a table step on its own call (task 027), before the step's window action.

    ``row``: refuses a row the table part lacks (the keys move the cursor: ``АктивизироватьСтроку`` called from
    the controller moves nothing, series 1c); ``cell``: its column current and in edit mode
    (``Активизировать(<колонка>, 1)``); ``total``: the column's total; ``value`` with ``row``: the attribute of
    that row from the unloaded table part, so the cursor stays.
    """
    number, kind = step["index"], step["kind"]
    if kind == "row":
        return _branch(number, f'''            Если Контекст77Формы.КоличествоСтрок() < {step["target"]} Тогда
                Ответ77 = "{TABLE_ERROR}no row {step["target"]} of " + Строка(Контекст77Формы.КоличествоСтрок());
            КонецЕсли;
''')
    if kind == "cell":
        return _branch(number, f"            Контекст77Формы.Активизировать({_literal(step['column'])}, 1);\n")
    if kind == "total":
        return _branch(number, f'''            Ответ77 = "total:" + Harness77Строка(Контекст77Формы.Итог({_literal(step["column"])}));
''')
    if kind == "value" and "row" in step:
        return f'''    Если Номер77Шага = {number} Тогда
        Попытка
            Таблица77 = СоздатьОбъект("ТаблицаЗначений");
            Контекст77Формы.ВыгрузитьТабличнуюЧасть(Таблица77, {_literal(step["target"])});
            Если Таблица77.КоличествоСтрок() < {step["row"]} Тогда
                Ответ77 = "{VALUE_ERROR}no row {step["row"]} of " + Строка(Таблица77.КоличествоСтрок());
            Иначе
                Ответ77 = "{VALUE}" + Harness77Строка(Таблица77.ПолучитьЗначение({step["row"]}, {_literal(step["target"])}));
            КонецЕсли;
        Исключение
            Ответ77 = "{VALUE_ERROR}" + ОписаниеОшибки();
        КонецПопытки;
    КонецЕсли;
'''
    return ""


# Every call of a scenario on a document's form with a table part reports its rows, the current row and column.
TABLE_STATE = '''Функция Harness77Таблица()
    Ответ77 = "";
    Попытка
        Ответ77 = Ответ77 + РазделительСтрок + "rows:" + Строка(Контекст77Формы.КоличествоСтрок());
        Ответ77 = Ответ77 + РазделительСтрок + "row:" + Строка(Контекст77Формы.НомерСтроки);
        Ответ77 = Ответ77 + РазделительСтрок + "column:" + Harness77Строка(Контекст77Формы.Форма.ТекущаяКолонка());
    Исключение
        Ответ77 = Ответ77 + РазделительСтрок + "state-error:" + Harness77Строка(ОписаниеОшибки());
    КонецПопытки;
    Возврат Ответ77;
КонецФункции

'''


def step_function(items, table=False, journal_kind=None):
    """``Harness77Step`` of the controller: messages of the step and the requested attribute.

    ``table``: the form is a document's with a table part (task 027); every answer ends with its state.
    """
    branches = "".join(f'''    Если Номер77Шага = {step["index"]} Тогда
        Попытка
            Система77 = СоздатьОбъект("System");
            Закрыта77 = Система77.CloseForm(Контекст77Формы, 0);
            Контекст77Формы = 0;
            Параметры77Формы = 0;
            Ответ77 = "reopen-close:" + Строка(Закрыта77) + РазделительСтрок;
        Исключение
            Ответ77 = "reopen-error:" + ОписаниеОшибки() + РазделительСтрок;
        КонецПопытки;
    КонецЕсли;
    Если Номер77Шага = {trip_number(step["index"], 1)} Тогда
        Попытка
            Параметры77 = СоздатьОбъект("СписокЗначений");
            Контекст77 = Параметры77;
            Открыта77 = ОткрытьФорму(Объект77Данных, Контекст77, 0);
            Ответ77 = "reopen-return:" + Строка(Открыта77) + РазделительСтрок;
            Если Открыта77 = 1 Тогда
                Контекст77Формы = Контекст77;
                Параметры77Формы = Параметры77;
                Если Контекст77Формы.ТекущийДокумент() = Объект77Данных Тогда
                    Ответ77 = Ответ77 + "reopen-same:1" + РазделительСтрок;
                Иначе
                    Ответ77 = Ответ77 + "reopen-same:0" + РазделительСтрок;
                КонецЕсли;
            КонецЕсли;
        Исключение
            Ответ77 = "reopen-error:" + ОписаниеОшибки() + РазделительСтрок;
        КонецПопытки;
    КонецЕсли;
''' if step["kind"] == "reopen" else f'''    Если Номер77Шага = {step["index"]} Тогда
        Попытка
            Ответ77 = "{VALUE}" + Harness77Строка(Контекст77Формы.{step["target"]});
        Исключение
            Ответ77 = "{VALUE_ERROR}" + ОписаниеОшибки();
        КонецПопытки;
    КонецЕсли;
''' if step["kind"] == "value" and "row" not in step else _table_branch(step) for step in items)
    editing = next((s for s in items if s['kind'] == 'journal_children' and s.get('edit')), None)
    if editing:
        # Keep Объект77Данных bound to the source for journal return and fixture checks.
        reference = f"Объект77Подготовки.ПолучитьЗначение({editing['reference']})"
        branches = branches.replace('ОткрытьФорму(Объект77Данных, Контекст77, 0)', f'ОткрытьФорму({reference}, Контекст77, 0)')
        branches = branches.replace('Контекст77Формы.ТекущийДокумент() = Объект77Данных', f'Контекст77Формы.ТекущийДокумент() = {reference}')
    choice = any(s["kind"] == "choose" for s in items)
    if choice:
        import choice77
    state = "    Ответ77 = Ответ77 + Harness77Таблица();\n" if table else ""
    if any(s['kind'] == 'find_document' and s.get('open') is False for s in items):
        copies = [s['index'] for s in items if (s['kind'] in ('journal_copy', 'journal_basis') and not s.get('cancel')) or (s['kind'] == 'journal_children' and (s.get('edit') or s.get('browse')))]
        state = ('    Если (Номер77Шага >= ' + str(copies[0]) + ') Тогда\n' + state + '    КонецЕсли;\n') if copies else ''
    if state and any(s["kind"] == "find_document" for s in items):
        state = ('    Если (Номер77Шага > -101000) ИЛИ (Номер77Шага < -101200) Тогда\n'
                 + state + '    КонецЕсли;\n')
    if state and any(s['kind'] == 'journal_period' for s in items):
        excluded = [s['index'] for s in items if s['kind'] == 'journal_period']
        state = '    Если ((Номер77Шага > -102000) ИЛИ (Номер77Шага <= -104000)) И ' + ' И '.join(f'(Номер77Шага <> {n})' for n in excluded) + ' Тогда\n' + state + '    КонецЕсли;\n'
    work = '    Ответ77 = Ответ77 + Harness77Выбор(Номер77Шага);\n' if choice else ''
    journal_helper = ''
    if journal_kind:
        import journal77
        journal_helper = journal77.function(items, journal_kind)
        work += '    Ответ77 = Ответ77 + Harness77Журнал(Номер77Шага);\n'
    return f'''Функция Harness77Строка(Значение77)
    Возврат СтрЗаменить(СтрЗаменить(Строка(Значение77), "\\", "\\\\"), РазделительСтрок, "\\n");
КонецФункции

{TABLE_STATE if table else ""}{choice77.function(items) if choice else ""}{journal_helper}Функция Harness77Step(Номер77Шага, Протокол, Метка) Экспорт
    Сообщения77 = СоздатьОбъект("MessageView");
    Сообщения77.SetSystemMessages();
    Ответ77 = "";
{branches}{work}{state}    Сообщить("{STEP_MARKER}" + Метка);
    Сообщения77.SaveToFile(Протокол);
    Сообщения77.Clear();
    Возврат Ответ77;
КонецФункции

'''


SAVE = "    Сообщения77.SaveToFile(Протокол);\n    Возврат Ответ77;\nКонецФункции\n"


def controller(text, items, table=False, journal_kind=None):
    """The form controller with the step function; ``open`` clears the messages it saved."""
    if text.count(SAVE) != 1 or text.count("Функция Harness77Ert(") != 1:
        raise ValueError("unexpected form controller layout for steps")
    text = text.replace(SAVE, SAVE.replace("    Возврат", '    Если Команда = "open" Тогда\n'
                                                     "        Сообщения77.Clear();\n    КонецЕсли;\n    Возврат", 1))
    if any(s["kind"] == "choose" for s in items):
        import choice77
        text = choice77.GLOBALS + text
    return text.replace("Функция Harness77Ert(", step_function(items, table, journal_kind) + "Функция Harness77Ert(", 1)


# The client's wait before ``result`` (task 008) serves the watcher's step requests meanwhile: each
# request is one controller call, its answer a UTF-16 file the watcher waits for. The wait for the
# end restarts after every served step.
from step_exchange77 import CLIENT


def client(done, wait_ms):
    import step_exchange77
    return step_exchange77.client(done, REQUEST, wait_ms)


def answer(text):
    """{value | value_error, total, table_error, rows, row, column, state_error} of the controller's answer.

    The answer is lines ``name:text``; a text is escaped (no line breaks in it). The rows, the current row
    and column come with every call on a document's form with a table part (task 027); ``error:`` is what
    1C refused in a table step's own work.
    """
    names = {"rows": "rows", "row": "row", "column": "column", "total": "total", "error": "table_error",
             "reopen-return": "reopen_return", "reopen-same": "reopen_same", "reopen-error": "reopen_error",
             "reopen-close": "reopen_close",
             "journal-new": "journal_new", "journal-hwnd": "journal_hwnd", "journal-saved": "journal_saved",
             "journal-reference": "journal_reference", "journal-error": "journal_error",
             "journal-current": "journal_current", "journal-match": "journal_match", "journal-opened": "journal_opened",
             "journal-start": "journal_start", "journal-end": "journal_end",
             "journal-posted": "journal_posted", "journal-deleted": "journal_deleted", "journal-value": "journal_value",
             "journal-copy": "journal_copy", "journal-source": "journal_source",
             "journal-basis": "journal_basis", "journal-link": "journal_link", "journal-comment": "journal_comment",
             "journal-return": "journal_return",
             "journal-id": "journal_id", "journal-source-id": "journal_source_id",
             "journal-expected-id": "journal_expected_id", "journal-link-id": "journal_link_id",
             "journal-empty": "journal_empty",
             "journal-kind": "journal_kind", "journal-expected-kind": "journal_expected_kind",
             "journal-date": "journal_date", "journal-number": "journal_number",
             "state-error": "state_error", "choice-hwnd": "choice_hwnd", "choice-current": "choice_current",
             "choice-ready": "choice_ready", "choice-result": "choice_result", "choice-value": "choice_value"}
    record = {}
    journal_problem = None
    for line in text.splitlines():
        if line.startswith(VALUE):
            record["value"] = _unescape(line[len(VALUE):])
        elif line.startswith(VALUE_ERROR):
            record["value_error"] = line[len(VALUE_ERROR):].strip()
        else:
            name, separator, rest = line.partition(":")
            if separator and name.startswith("journal-") and name not in names:
                journal_problem = "unknown journal response field"
            if not separator or name not in names:
                continue
            if name.startswith("reopen-") and names[name] in record:
                record["reopen_error"] = "duplicate reopening response"
            if name.startswith("journal-") and names[name] in record:
                journal_problem = "duplicate journal response"
            if name == "journal-error":
                journal_problem = journal_problem or rest.strip() or "empty journal error response"
            rest = _unescape(rest)
            if name in ("rows", "row", "choice-hwnd", "choice-ready", "choice-result"):
                try:
                    record[names[name]] = int(rest.strip())
                except ValueError:
                    pass
                continue
            record[names[name]] = rest if name == "total" else rest.strip()
    if journal_problem:
        record["journal_error"] = journal_problem
    return record


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
    """The calls to 1C of one chain as one: all returned and complete, their messages and errors in order.

    The state of the table part (task 027) and what 1C answered for a step's own work are the last call's:
    after the action and its windows, or the own call of a row step after the Enters that ended a row's input.
    """
    if not trips:
        return {"returned": False, "error": "1C was not asked"}
    merged = {"returned": all(t.get("returned") for t in trips), "complete": all(t.get("complete") for t in trips),
              "messages": [line for t in trips for line in t.get("messages") or []],
              "diagnostics": [d for t in trips for d in t.get("diagnostics") or []], "calls": len(trips)}
    error = next((t["error"] for t in trips if t.get("error")), None)
    if error:
        merged["error"] = error
    merged.update({key: trips[-1][key] for key in ("rows", "row", "column", "state_error", "table_error", "value",
                                                   "value_error", "total", "choice_result", "choice_value",
                                                   "reopen_return", "reopen_same", "reopen_error") if key in trips[-1]})
    merged.update({key: trips[-1][key] for key in ("journal_new", "journal_hwnd", "journal_saved",
                                                 "journal_reference", "journal_error") if key in trips[-1]})
    return merged


def messages(protocol, marker):
    """(lines, complete) of a step's saved messages: everything before its own marker line."""
    lines = protocol.splitlines()
    complete = bool(lines) and lines[-1] == STEP_MARKER + marker
    return (lines[:-1] if complete else lines), complete


def label(step):
    """How a reason names a step: its number, kind and target."""
    if step["kind"] in ("add_row", "delete_row"):
        return f"step {step['index']} ({step['kind']})"
    return f"step {step['index']} ({step['kind']} {step['target']!r})"


def _judge_table(step, record, trip):
    """The issue of a table step's own check (task 027), once its action and the calls to 1C passed."""
    name, kind = label(step), step["kind"]
    if trip.get("table_error"):
        return f"{name}: 1C refused: {trip['table_error']}"
    if kind == "row" and record.get("input_ended") is False:
        return f"{name}: the row's input did not end: a cell editor stays open"
    if kind in ("add_row", "delete_row", "row", "rows") and ("rows" not in trip or "row" not in trip):
        return f"{name}: the table part was not read: {trip.get('state_error') or 'no state in 1C answer'}"
    if kind in ("add_row", "delete_row"):
        before = (record.get("before") or {}).get("rows")
        if before is None:
            return f"{name}: the table part was not read before the step"
        wanted = before + (1 if kind == "add_row" else -1)
        if trip["rows"] != wanted:
            return f"{name}: the table has {trip['rows']} rows, expected {wanted}"
    if kind == "cell" and not (record.get("action") or {}).get("committed"):
        return f"{name}: the cell kept its editor after Enter"
    if kind == "row" and trip["row"] != step["target"]:
        return f"{name}: the current row is {trip['row']}, expected {step['target']}"
    if kind == "rows" and trip["rows"] != step["target"]:
        return f"{name}: the table has {trip['rows']} rows, expected {step['target']}"
    if kind == "total":
        if "total" not in trip:
            return f"{name}: no total in 1C's answer"
        if trip["total"].strip() != step["text"].strip():
            return f"{name}: is {trip['total']!r}, expected {step['text']!r}"
    return None


def judge(step, record, pending, form_open):
    """The issue of one executed step, or None; ``record`` holds what happened and what the windows show.

    ``pending`` are the message lines since the last action, this step's included.
    """
    name = label(step)
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
        if action.get("choice") and not action.get("choice_verified"):
            return f"{name}: the returned reference was not verified"
    trip = record.get("round_trip") or {}
    if not trip.get("returned"):
        return f"{name}: 1C did not answer after the step: {trip.get('error') or 'no answer'}"
    if not trip.get("complete"):
        return f"{name}: the step's messages were not saved completely"
    if trip.get("diagnostics"):
        first = trip["diagnostics"][0]
        return f"{name}: 1C reported an error: line {first['line']}: {first['message']}"
    if step["kind"] == "reopen":
        if trip.get("journal_error"):
            return f"{name}: {trip['journal_error']}"
        if record.get("closed_before_reopen") is not True:
            return f"{name}: previous form closing was not confirmed"
        if trip.get("reopen_error") or trip.get("reopen_return") != "1" or trip.get("reopen_same") != "1":
            return f"{name}: the saved document was not reopened: {trip.get('reopen_error') or trip}"
        if not (record.get("reopened") or {}).get("found"):
            return f"{name}: no owned form inspection after reopening"
    if step["kind"] in ("create", "created", "find_document", "journal_copy", "journal_basis"):
        if trip.get("journal_error"):
            return f"{name}: {trip['journal_error']}"
        if step["kind"] == "create" and (trip.get("journal_new") != "1" or not record.get("new_form_verified")):
            return f"{name}: new unsaved document form was not verified"
        if step['kind'] == 'journal_basis':
            import journal_basis77
            try:
                journal_basis77.checked_new(trip)
                if not record.get('new_form_verified'):
                    raise RuntimeError('new based document window not verified')
            except RuntimeError as error:
                return f'{name}: {error}'
        if step['kind'] == 'journal_copy':
            import journal_copy77
            try:
                journal_copy77.checked_new(trip)
                if not record.get('new_form_verified'):
                    raise RuntimeError('new copy window not verified')
            except RuntimeError as error:
                return f'{name}: {error}'
        if step["kind"] == "created" and (trip.get("journal_saved") != "1" or not trip.get("journal_reference")):
            return f"{name}: saved created reference was not verified"
        if step['kind'] == 'find_document' and step.get('open') is False:
            if trip.get('journal_match') != '1' or not record.get('cursor_verified'):
                return f'{name}: selected journal reference was not verified'
            return None
        if step["kind"] == "find_document" and (trip.get("journal_opened") != "1"
                or trip.get("journal_match") != "1" or not trip.get("journal_reference")
                or not record.get("existing_form_verified")):
            return f"{name}: existing document reference/window was not verified"
    if step.get("closes") and form_open:
        return f"{name}: the form did not close"
    if not form_open and not step.get("closes") and step["kind"] not in ("message", "no_message"):
        return f"{name}: the form closed"
    if step['kind'] == 'tab' and not record.get('tab_verified'):
        return f"{name}: native tab selection was not verified"
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
    if step["kind"] in TABLE_KINDS:
        issue = _judge_table(step, record, trip)
        if issue:
            return issue
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
    last_open = max((i for i, r in enumerate(records) if r.get("kind") == "reopen"), default=0)
    closed_by_step = any(r.get("closes") and r.get("form_open") is False for r in records[last_open:])
    if not (closed_by_controller or closed_by_step):
        issues.append("the form was not closed")
    return issues
