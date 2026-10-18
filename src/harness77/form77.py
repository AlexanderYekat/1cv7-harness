"""Form description of an ERT dialog: lossless extract and verified changes (task 008).

The description is versioned JSON with the supported properties only: the form
caption, size and layers; per control its numeric ID, class, caption, position,
size, formula, identifier and layer. It is bound to its template by the SHA-256
of the template's dialog text; every other field and section stays the
template's. An unchanged description therefore rebuilds the dialog byte for
byte, and anything outside the supported changes is refused explicitly.

The dialog layout rule (CRLF before every nested list, two spaces after the
root) and the field numbers come from the static survey of 416 forms in
task 008. Whether the dialog works in 1C is the native acceptance, not here.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from .ert_module import (DIALOG_STREAM, ErtError, decode_dialog, encode_dialog,
                         parse_dialog)

SCHEMA = "harness77-form"
SCHEMA_VERSION = 1

# Field numbers (from zero) of a Controls record and of the Frame record.
CAPTION, CLASS, X, Y, WIDTH, HEIGHT, ID, FORMULA, IDENTIFIER, LAYER = 0, 1, 3, 4, 5, 6, 9, 11, 12, 41
FRAME_WIDTH, FRAME_HEIGHT, FRAME_CAPTION, FRAME_LAYERS = 14, 15, 16, 28
GEOMETRY = (("x", X), ("y", Y), ("width", WIDTH), ("height", HEIGHT))
CONTROL_KEYS = ("id", "class", "caption", "x", "y", "width", "height", "formula", "identifier", "layer")
FORM_KEYS = ("caption", "width", "height", "layers")
TOP_KEYS = ("schema", "schema_version", "template_dialog_sha256", "form", "controls")
NEW_CLASSES = ("BUTTON",)
FIRST_ID = 4152
# The client area of a form in form units, measured natively in task 008 (F0):
# the window caption takes the top 15 units, the borders 4 at the left and 3 at
# the right and bottom; 8730 of 8741 corpus controls start at y >= 15.
CLIENT_LEFT, CLIENT_TOP, CLIENT_MARGIN = 4, 15, 3

# The most frequent button record of the corpus (347 of 2936 buttons, the same
# as "Закрыть" in FIO.ERT); None marks the fields the description sets.
DEFAULT_BUTTON = ([None, "BUTTON", "1342177291", None, None, None, None, "0", "0", None, "", None,
                   None, "-1", "U"] + ["0"] * 5 + ["", "", "", "0", "-11"] + ["0"] * 12
                  + ["MS Sans Serif", "-1", "-1", "0", None, '{"0","0"}'])

NAME = re.compile(r"[A-Za-zА-Яа-яЁё_][0-9A-Za-zА-Яа-яЁё_]*\Z")
CALL = re.compile(r"\s*([A-Za-zА-Яа-яЁё_][0-9A-Za-zА-Яа-яЁё_]*)\s*\(.*\)\s*;?\s*\Z", re.DOTALL)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def serialize_dialog(tree):
    """Dialog text in the 1C 7.7 layout: CRLF before every nested list."""
    def value(item):
        if isinstance(item, str):
            return '"' + item.replace('"', '""') + '"'
        return "{" + ",".join(("\r\n" if isinstance(x, list) else "") + value(x) for x in item) + "}"
    return value(tree) + "  "


def _structure(text):
    """Parsed dialog, its Frame record and Controls section; refuse unknown layouts."""
    tree = parse_dialog(text)
    if serialize_dialog(tree) != text:
        raise ErtError("Диалог записан не в разметке 1С 7.7: обратное преобразование было бы с потерями")
    if not tree or tree[0] != "Dialogs":
        raise ErtError('Неизвестная структура диалога: нет заголовка "Dialogs"')
    frames = [s for s in tree[1:] if isinstance(s, list) and s[:1] == ["Frame"]]
    sections = [s for s in tree[1:] if isinstance(s, list) and s[:1] == ["Controls"]]
    if len(frames) != 1 or len(sections) != 1 or len(frames[0]) != 2 or not isinstance(frames[0][1], list):
        raise ErtError("Нужен ровно один раздел Frame и один раздел Controls")
    frame = frames[0][1]
    if len(frame) <= FRAME_LAYERS or not isinstance(frame[FRAME_LAYERS], list):
        raise ErtError("Неизвестная структура записи Frame")
    layers = frame[FRAME_LAYERS]
    if not layers or not all(isinstance(x, list) and len(x) == 2 and all(isinstance(s, str) for s in x)
                             for x in layers[1:]):
        raise ErtError("Неизвестная структура слоёв формы")
    for index in (FRAME_CAPTION, FRAME_WIDTH, FRAME_HEIGHT):
        if not isinstance(frame[index], str):
            raise ErtError("Неизвестная структура записи Frame")
    for number, record in enumerate(sections[0][1:], start=1):
        if not isinstance(record, list) or len(record) <= LAYER or not all(isinstance(x, str) for x in record):
            raise ErtError(f"Неизвестная структура элемента формы № {number}")
    return tree, frame, sections[0]


def _int(text, where):
    if not re.fullmatch(r"-?[0-9]+", text) or str(int(text)) != text:
        raise ErtError(f"{where}: не целое число {text!r}")
    return int(text)


def _control(record):
    where = f"Элемент {record[ID]!r}"
    item = {"id": _int(record[ID], where), "class": record[CLASS], "caption": record[CAPTION]}
    for key, index in GEOMETRY:
        item[key] = _int(record[index], where)
    item.update(formula=record[FORMULA], identifier=record[IDENTIFIER], layer=record[LAYER])
    return item


def describe(text):
    """Description of a dialog text; refuses layouts that would not rebuild losslessly."""
    _, frame, section = _structure(text)
    return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION,
            "template_dialog_sha256": sha256(text.encode("cp1251")),
            "form": {"caption": frame[FRAME_CAPTION], "width": _int(frame[FRAME_WIDTH], "Форма"),
                     "height": _int(frame[FRAME_HEIGHT], "Форма"),
                     "layers": [layer[0] for layer in frame[FRAME_LAYERS][1:]]},
            "controls": [_control(record) for record in section[1:]]}


def dumps(description):
    return json.dumps(description, ensure_ascii=False, indent=2) + "\n"


def loads(data):
    """Description from UTF-8 JSON bytes, with the exact shape of schema version 1."""
    try:
        description = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ErtError(f"Описание формы не читается как JSON UTF-8: {error}") from error
    if not isinstance(description, dict) or description.get("schema") != SCHEMA:
        raise ErtError(f'Описание формы должно иметь "schema": "{SCHEMA}"')
    if description.get("schema_version") != SCHEMA_VERSION:
        raise ErtError(f"Поддерживается schema_version = {SCHEMA_VERSION}")
    _keys(description, TOP_KEYS, TOP_KEYS, "Описание")
    form = description["form"]
    _keys(form, FORM_KEYS, FORM_KEYS, "form")
    _typed(form, "form", caption=str, width=int, height=int, layers=list)
    if not all(isinstance(x, str) for x in form["layers"]):
        raise ErtError("form.layers: нужен список строк")
    if not isinstance(description["template_dialog_sha256"], str):
        raise ErtError("template_dialog_sha256: нужна строка")
    if not isinstance(description["controls"], list):
        raise ErtError("controls: нужен список")
    for number, item in enumerate(description["controls"], start=1):
        where = f"controls[{number}]"
        _keys(item, CONTROL_KEYS, ("class",), where)
        _typed(item, where, id=int, x=int, y=int, width=int, height=int,
               **{key: str for key in ("class", "caption", "formula", "identifier", "layer")})
    return description


def _keys(item, allowed, required, where):
    if not isinstance(item, dict):
        raise ErtError(f"{where}: нужен объект")
    unknown = sorted(set(item) - set(allowed))
    if unknown:
        raise ErtError(f"{where}: неизвестные свойства {', '.join(unknown)}")
    missing = [key for key in required if key not in item]
    if missing:
        raise ErtError(f"{where}: нет свойств {', '.join(missing)}")


def _typed(item, where, **types):
    for key, kind in types.items():
        if key in item and (not isinstance(item[key], kind) or isinstance(item[key], bool)):
            raise ErtError(f"{where}.{key}: нужен тип {kind.__name__}")


def module_procedures(module_text):
    """Casefolded names of the procedures and functions declared in a module."""
    from .lint77 import Source, parse
    return set(parse(Source("module", "module", module_text)).symbols)


def platform_functions():
    """Casefolded global function names of the packaged platform catalog."""
    from .catalog77 import load_packaged
    return {name.casefold() for item in load_packaged()["items"] if item["kind"] == "global_function"
            for name in (item["name_ru"], item["name_en"]) if name}


def _reserved():
    from .catalog77 import load_packaged
    return {name.casefold() for name in load_packaged()["reserved"]["names"]}


class _Changes:
    def __init__(self, module_text):
        self.items = []
        self.module_text = module_text
        self._procedures = None

    def procedures(self):
        if self._procedures is None:
            if self.module_text is None:
                raise ErtError("Связь формулы с модулем проверяется только при сборке с модулем")
            self._procedures = module_procedures(self.module_text) | platform_functions()
        return self._procedures


def _caption(value, where):
    try:
        value.encode("cp1251")
    except UnicodeEncodeError as error:
        raise ErtError(f"{where}: символ {value[error.start:error.end]!r} вне Windows-1251") from None
    return value


def _formula(value, kind, where, changes):
    if kind != "BUTTON":
        raise ErtError(f"{where}: изменение формулы элемента {kind} не поддерживается")
    match = CALL.match(value)
    if not match:
        raise ErtError(f"{where}: формула кнопки должна быть вызовом Имя(…), получено {value!r}")
    if match.group(1).casefold() not in changes.procedures():
        raise ErtError(f"{where}: формула вызывает {match.group(1)}, которого нет ни в модуле, "
                       "ни среди глобальных функций платформы")
    return _caption(value, where)


def _geometry(item, width, height, where):
    x, y, w, h = (item[key] for key, _ in GEOMETRY)
    right, bottom = width - CLIENT_MARGIN, height - CLIENT_MARGIN
    if w <= 0 or h <= 0 or x < CLIENT_LEFT or y < CLIENT_TOP or x + w > right or y + h > bottom:
        raise ErtError(f"{where}: элемент ({x}, {y}, {w}×{h}) выходит за клиентскую область формы "
                       f"[{CLIENT_LEFT}, {right}]×[{CLIENT_TOP}, {bottom}] (форма {width}×{height})")


def apply(text, description, module_text=None):
    """New dialog text from the template text and a description; returns (text, changes)."""
    tree, frame, section = _structure(text)
    current = describe(text)
    if description["template_dialog_sha256"] != current["template_dialog_sha256"]:
        raise ErtError("Описание сделано для другого шаблона: хеш диалога не совпадает")
    changes = _Changes(module_text)
    form, old_form = description["form"], current["form"]
    if form["layers"] != old_form["layers"]:
        raise ErtError("Изменение слоёв формы не поддерживается")
    for key, index in (("caption", FRAME_CAPTION), ("width", FRAME_WIDTH), ("height", FRAME_HEIGHT)):
        if form[key] != old_form[key]:
            if key == "caption":
                _caption(form[key], "Заголовок формы")
            elif form[key] <= 0:
                raise ErtError(f"Форма: {key} должна быть больше нуля")
            frame[index] = str(form[key])
            changes.items.append({"control": None, "property": key, "from": old_form[key], "to": form[key]})
    width, height = form["width"], form["height"]
    records, items = section[1:], description["controls"]
    if len(items) < len(records):
        raise ErtError("Удаление элементов формы не поддерживается")
    for record, item, old in zip(records, items, current["controls"]):
        where = f"Элемент {old['id']}"
        if item.get("id") != old["id"] or item["class"] != old["class"]:
            raise ErtError(f"{where}: перестановка, удаление или смена ID/класса не поддерживаются "
                           f"(в описании id={item.get('id')!r}, класс {item['class']})")
        missing = [key for key in CONTROL_KEYS if key not in item]
        if missing:
            raise ErtError(f"{where}: нет свойств {', '.join(missing)}")
        moved = False
        for key in CONTROL_KEYS[2:]:
            if item[key] == old[key]:
                continue
            if key == "caption":
                record[CAPTION] = _caption(item[key], where)
            elif key == "formula":
                record[FORMULA] = _formula(item[key], old["class"], where, changes)
            elif key == "identifier":
                record[IDENTIFIER] = item[key]
            elif key == "layer":
                record[LAYER] = item[key]
            else:
                record[dict(GEOMETRY)[key]] = str(item[key])
                moved = True
            changes.items.append({"control": old["id"], "property": key, "from": old[key], "to": item[key]})
        if moved:
            _geometry(item, width, height, where)
    stored = [old["id"] for old in current["controls"]]
    for number, item in enumerate(items[len(records):], start=len(records) + 1):
        if item["class"] not in NEW_CLASSES:
            raise ErtError(f"controls[{number}]: новый элемент класса {item['class']} не поддерживается")
        if any(len(record) != len(DEFAULT_BUTTON) for record in records):
            raise ErtError("Новый элемент в форме прежнего формата (не 43 поля) не поддерживается")
        # 1C numbers records 4152, 4153, … in order (all 416 corpus forms) and gives
        # the windows IDs by position (task 008, F0): a new control only continues it.
        if stored != list(range(FIRST_ID, FIRST_ID + len(stored))):
            raise ErtError(f"Новый элемент в форме, где ID записей не идут подряд с {FIRST_ID}, не поддерживается")
        control_id = FIRST_ID + len(stored)
        if item.get("id", control_id) != control_id:
            raise ErtError(f"controls[{number}]: ID нового элемента — только следующий по порядку {control_id}, "
                           f"получено {item['id']}")
        stored.append(control_id)
        where = f"Новый элемент {control_id}"
        missing = [key for key in ("caption", "x", "y", "width", "height", "formula") if key not in item]
        if missing:
            raise ErtError(f"{where}: нет свойств {', '.join(missing)}")
        _geometry(item, width, height, where)
        record = list(DEFAULT_BUTTON)
        record[CAPTION] = _caption(item["caption"], where)
        for key, index in GEOMETRY:
            record[index] = str(item[key])
        record[ID] = str(control_id)
        record[FORMULA] = _formula(item["formula"], item["class"], where, changes)
        record[IDENTIFIER] = item.get("identifier", "")
        record[LAYER] = item.get("layer", form["layers"][0] if form["layers"] else "")
        section.append(record)
        changes.items.append({"control": control_id, "added": item["class"]})
    # Only what the description sets is validated: the template's own identifiers
    # and layers were accepted by 1C (a corpus form has the identifier "Дата").
    touched = {(str(c["control"]), c.get("property", "added")) for c in changes.items if c["control"]}
    owners = {}
    for record in section[1:]:
        if record[IDENTIFIER]:
            owners.setdefault(record[IDENTIFIER].casefold(), []).append(record[ID])
    for record in section[1:]:
        where = f"Элемент {record[ID]}"
        added = (record[ID], "added") in touched
        if (added or (record[ID], "layer") in touched) and record[LAYER] not in form["layers"]:
            raise ErtError(f"{where}: слоя {record[LAYER]!r} нет в форме")
        name = record[IDENTIFIER]
        if name and (added or (record[ID], "identifier") in touched):
            if not NAME.match(name) or name.casefold() in _reserved():
                raise ErtError(f"{where}: {name!r} не годится как идентификатор 1С")
            others = [other for other in owners[name.casefold()] if other != record[ID]]
            if others:
                raise ErtError(f"{where}: идентификатор {name!r} уже есть у элемента {others[0]}")
    return serialize_dialog(tree), changes.items


def dialog_payload(text, old_payload):
    """Dialog Stream bytes for a new text; the length prefix keeps its form."""
    from .ert_module import _PREFIX_KINDS, _dialog_length
    payload = encode_dialog(text)
    old_prefix, new_prefix = _dialog_length(old_payload)[1], _dialog_length(payload)[1]
    if old_prefix != new_prefix:
        raise ErtError(f"Заголовок длины диалога сменил бы вид ({_PREFIX_KINDS[old_prefix]} -> "
                       f"{_PREFIX_KINDS[new_prefix]}); такой случай в 1С 7.7 не проверен")
    return payload


def dialog_entry(compound):
    entries = [e for e in compound.directory_entries if e.object_type == 2 and e.name == DIALOG_STREAM]
    if len(entries) != 1:
        raise ErtError(f"Нужна ERT ровно с одним потоком {DIALOG_STREAM}")
    return entries[0]


def dialog_identifiers(description):
    """Form context for L7711: casefolded identifiers of the described controls."""
    return frozenset(item["identifier"].casefold() for item in description["controls"]
                     if item.get("identifier"))


def extract(input_path, output):
    from .artifacts import _container, _destination, _input, _publish
    input_path, raw = _input(input_path)
    output = _destination(output)
    compound, _, _ = _container(raw)
    text = decode_dialog(compound.read_stream(dialog_entry(compound)))
    description = describe(text)
    payload = dumps(description).encode("utf-8")
    result = _publish(output, payload, lambda data: describe(text) == loads(data) or _mismatch(),
                      [(input_path, raw)])
    return {"schema_version": 1, "tool": "harness77", "operation": "form-extract", "status": "passed",
            "scope": "ert_form_extract", "input": {"path": str(input_path), "sha256": sha256(raw)},
            "output": {**result, "encoding": "utf-8"},
            "template_dialog_sha256": description["template_dialog_sha256"],
            "controls": len(description["controls"]), "inputs_unchanged": True, "platform_checked": False}


def _mismatch():
    raise ErtError("Описание после обратного чтения отличается")


def main(argv):
    parser = argparse.ArgumentParser(prog="harness77 form-extract", allow_abbrev=False,
                                     description="Описание формы ERT в JSON (схема harness77-form 1)")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Новый файл в существующем каталоге")
    args = parser.parse_args(argv)
    try:
        report = extract(args.input, args.output)
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return 0
    except (OSError, ValueError, ErtError, struct.error, RuntimeError) as exc:
        report = {"schema_version": 1, "tool": "harness77", "operation": "form-extract", "status": "blocked",
                  "scope": "ert_form_extract", "output_path": str(args.output), "error": str(exc),
                  "platform_checked": False}
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 2
