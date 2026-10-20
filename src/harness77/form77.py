"""Form description of an ERT dialog: lossless extract and verified changes (tasks 008, 011–013).

The description is versioned JSON with the supported properties only: the form
caption, size and layers; per control its numeric ID, class, caption, position,
size, formula, identifier, layer and (version 2) data type; version 3 names the
configuration object of a reference type (task 012) by the copy of the metadata
the ERT carries, and a target base is checked by these names (task 013). It is
bound to its template by the SHA-256 of the template's dialog text; every other
field and section stays the template's. An unchanged description therefore
rebuilds the dialog byte for byte, and anything outside the supported changes
is refused explicitly.

The dialog layout rule (CRLF before every nested list, two spaces after the
root) and the field numbers come from the static survey of 416 forms in
task 008, the data type fields and the default records of new classes from the
surveys of tasks 011 and 012. Whether the dialog works in 1C is the native acceptance,
not here.
"""

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from .ert_module import (DIALOG_STREAM, ErtError, decode_dialog, encode_dialog,
                         parse_dialog)
from .metadata77 import SECTIONS, STREAM, TYPES, parse_name, type_name

SCHEMA = "harness77-form"
SCHEMA_VERSION = 3
SCHEMA_VERSIONS = (1, 2, 3)

# Field numbers (from zero) of a Controls record and of the Frame record.
CAPTION, CLASS, X, Y, WIDTH, HEIGHT, ID, FORMULA, IDENTIFIER, LAYER = 0, 1, 3, 4, 5, 6, 9, 11, 12, 41
TYPE, LENGTH, PRECISION, OBJECT = 14, 15, 16, 17
FRAME_WIDTH, FRAME_HEIGHT, FRAME_CAPTION, FRAME_LAYERS = 14, 15, 16, 28
GEOMETRY = (("x", X), ("y", Y), ("width", WIDTH), ("height", HEIGHT))
CONTROL_KEYS = ("id", "class", "caption", "x", "y", "width", "height", "formula", "identifier", "layer", "type")
CONTROL_KEYS_V1 = CONTROL_KEYS[:-1]
FORM_KEYS = ("caption", "width", "height", "layers")
TOP_KEYS = ("schema", "schema_version", "template_dialog_sha256", "form", "controls")
TYPE_KEYS = ("kind", "length", "precision", "code", "object", "object_id")
# Field 14 holds the type code (task 011 survey): S, N, D, U; B, E, O, K, T are references
# (metadata77.TYPES), with the number of the metadata object in field 17 (task 012).
KINDS = {"S": "string", "N": "number", "D": "date", "U": "undefined"}
REFERENCE = "reference"
FIRST_ID = 4152
GROUP = "1CGROUPBOX"
# The client area of a form in form units, measured natively in task 008 (F0):
# the window caption takes the top 15 units, the borders 4 at the left and 3 at
# the right and bottom; 8730 of 8741 corpus controls start at y >= 15.
CLIENT_LEFT, CLIENT_TOP, CLIENT_MARGIN = 4, 15, 3


def _default(kind, style, code="U", flags="0", font=("0",) * 12):
    """A record of the corpus layout; None marks the fields the description sets."""
    return ([None, kind, style, None, None, None, None, "0", "0", None, "", None, None, "-1", code,
             "0", "0", "0", "0", flags, "", "", "", "0", "-11", *font, "MS Sans Serif", "-1", "-1", "0",
             None, '{"0","0"}'])


# The most frequent record of each new class and type in the corpus (tasks 008, 011):
# the button as "Закрыть" in FIO.ERT (347 of 2936), the label 425 of 2641 (left
# aligned, explicit MS Sans Serif 8), the group box 455 of 612, the string field
# 115 of 283, the number field 239 of 425, the date field 193 of 334, the check
# box 130 of 502 (BS_AUTOCHECKBOX).
DEFAULT_BUTTON = _default("BUTTON", "1342177291")
DEFAULTS = {
    ("BUTTON", None): DEFAULT_BUTTON,
    ("STATIC", None): _default("STATIC", "1342177280", flags="192",
                               font=("0", "0", "0", "400", "0", "0", "0", "204", "1", "2", "1", "34")),
    (GROUP, None): _default(GROUP, "1342177287"),
    ("1CEDIT", "string"): _default("1CEDIT", "1350565888", "S"),
    ("BMASKED", "number"): _default("BMASKED", "1350565888", "N", flags="67108896"),
    ("BMASKED", "date"): _default("BMASKED", "1350565888", "D", flags="32"),
    ("CHECKBOX", "number"): _default("CHECKBOX", "1342177283", "N"),
}
# The most frequent BMASKED record of each reference code differs from the number
# field in the flags only (task 012): B 45 of 114, O 9 of 20, E 1 of 1, T 4 of 6,
# K 4 of 6. The corpus forms have no field of the chart-of-accounts type P.
REFERENCE_FLAGS = {"B": "0", "O": "16777248", "E": "0", "T": "0", "K": "32"}
# What a new control of each class needs: its own properties, the type kinds it
# takes and whether its formula must be a call (True), may be one (False) or is
# not supported (None). Data controls are form attributes, so they need a name.
NEW_CLASSES = {
    "BUTTON": {"required": ("caption", "formula"), "kinds": (), "formula": True},
    "STATIC": {"required": ("caption",), "kinds": (), "formula": None},
    GROUP: {"required": ("caption",), "kinds": (), "formula": None},
    "1CEDIT": {"required": ("identifier", "type"), "kinds": ("string",), "formula": False},
    "BMASKED": {"required": ("identifier", "type"), "kinds": ("number", "date", REFERENCE), "formula": False},
    "CHECKBOX": {"required": ("caption", "identifier"), "kinds": ("number",), "formula": False},
}
FORMULAS = {kind: rules["formula"] for kind, rules in NEW_CLASSES.items() if rules["formula"] is not None}
CHECKBOX_TYPE = {"kind": "number", "length": 1}

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


def _type(record, where, version=SCHEMA_VERSION, metadata=None):
    """Data type of a record; None for the undefined type without length and precision.

    Version 3 names a reference type: any object of the type by the type alone, a
    kind by the name the metadata give its number, else by code and number.
    """
    code, length, precision = record[TYPE], _int(record[LENGTH], where), _int(record[PRECISION], where)
    if (code, length, precision) == ("U", 0, 0):
        return None
    if version >= 3 and code in TYPES and (length, precision) == (0, 0):
        number = _int(record[OBJECT], where)
        name = type_name(code, number, metadata)
        return ({"kind": REFERENCE, "object": name} if name else
                {"kind": REFERENCE, "code": code, "object_id": number})
    kind = KINDS.get(code, "other")
    value = {"kind": kind}
    if kind == "other":
        value["code"] = code
    if length:
        value["length"] = length
    if precision:
        value["precision"] = precision
    return value


def _control(record, version=SCHEMA_VERSION, metadata=None):
    where = f"Элемент {record[ID]!r}"
    item = {"id": _int(record[ID], where), "class": record[CLASS], "caption": record[CAPTION]}
    for key, index in GEOMETRY:
        item[key] = _int(record[index], where)
    item.update(formula=record[FORMULA], identifier=record[IDENTIFIER], layer=record[LAYER])
    data_type = _type(record, where, version, metadata)
    if data_type:
        item["type"] = data_type
    return item


def describe(text, metadata=None, version=SCHEMA_VERSION):
    """Description of a dialog text; refuses layouts that would not rebuild losslessly.

    metadata (metadata77.Metadata, the ERT's own copy) names the kinds of reference
    fields (task 012).
    """
    _, frame, section = _structure(text)
    return {"schema": SCHEMA, "schema_version": version,
            "template_dialog_sha256": sha256(text.encode("cp1251")),
            "form": {"caption": frame[FRAME_CAPTION], "width": _int(frame[FRAME_WIDTH], "Форма"),
                     "height": _int(frame[FRAME_HEIGHT], "Форма"),
                     "layers": [layer[0] for layer in frame[FRAME_LAYERS][1:]]},
            "controls": [_control(record, version, metadata) for record in section[1:]]}


def by_number(description):
    """Reference fields whose kind the description gives by number, not by name."""
    return [{"control": item["id"], "code": item["type"]["code"], "object_id": item["type"]["object_id"]}
            for item in description["controls"]
            if item.get("type", {}).get("kind") == REFERENCE and "object_id" in item["type"]]


def needs_metadata(description):
    """Whether a description has a field of a configuration kind, by name (Справочник.Контрагенты) or number."""
    return any(item.get("type", {}).get("kind") == REFERENCE
               and ("." in item["type"].get("object", "") or item["type"].get("object_id", 0) > 0)
               for item in description["controls"])


def _kind(record):
    """(code, number) of a field of a configuration kind, or None (another type, or any object)."""
    if record[TYPE] not in SECTIONS or (record[LENGTH], record[PRECISION]) != ("0", "0"):
        return None
    number = _int(record[OBJECT], f"Элемент {record[ID]}")
    return (record[TYPE], number) if number else None


def kinds(text, names, target=None):
    """Fields of a configuration kind as 1C reads them (task 013).

    The name of each number comes from names (the ERT's own copy; None if the number
    is not there), the number of that name from target (the base; None if it lacks it).
    """
    rows = []
    for record in _structure(text)[2][1:]:
        key = _kind(record)
        if key is None:
            continue
        row = {"control": int(record[ID]), "object": type_name(*key, names), "code": key[0], "object_id": key[1]}
        if target is not None:
            row["target_object_id"] = target.number(key[0], names.names[key]) if row["object"] else None
        rows.append(row)
    return rows


def dumps(description):
    return json.dumps(description, ensure_ascii=False, indent=2) + "\n"


def loads(data):
    """Description from UTF-8 JSON bytes, with the exact shape of schema version 1 or 2."""
    try:
        description = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ErtError(f"Описание формы не читается как JSON UTF-8: {error}") from error
    if not isinstance(description, dict) or description.get("schema") != SCHEMA:
        raise ErtError(f'Описание формы должно иметь "schema": "{SCHEMA}"')
    version = description.get("schema_version")
    if isinstance(version, bool) or version not in SCHEMA_VERSIONS:
        raise ErtError(f"Поддерживается schema_version = {' или '.join(map(str, SCHEMA_VERSIONS))}")
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
        _keys(item, CONTROL_KEYS if version >= 2 else CONTROL_KEYS_V1, ("class",), where)
        _typed(item, where, id=int, x=int, y=int, width=int, height=int, type=dict,
               **{key: str for key in ("class", "caption", "formula", "identifier", "layer")})
        if "type" in item:
            _loads_type(item["type"], where + ".type", version)
    return description


def _loads_type(data_type, where, version):
    _keys(data_type, TYPE_KEYS if version >= 3 else TYPE_KEYS[:4], ("kind",), where)
    _typed(data_type, where, kind=str, length=int, precision=int, code=str, object=str, object_id=int)
    kinds = (*KINDS.values(), "other") + ((REFERENCE,) if version >= 3 else ())
    if data_type["kind"] not in kinds:
        raise ErtError(f"{where}.kind: неизвестный вид типа {data_type['kind']!r}")
    if data_type["kind"] != REFERENCE:
        if ("code" in data_type) != (data_type["kind"] == "other"):
            raise ErtError(f"{where}: code задаётся только у вида other и обязателен у него")
        if "object" in data_type or "object_id" in data_type:
            raise ErtError(f"{where}: object и object_id задаются только у вида reference")
        return
    keys = set(data_type) - {"kind"}
    if keys == {"object"}:
        parse_name(data_type["object"])
    elif keys == {"code", "object_id"}:
        if data_type["code"] not in TYPES or data_type["object_id"] < 0:
            raise ErtError(f"{where}: code — один из {', '.join(TYPES)}, object_id — номер ≥ 0")
    else:
        raise ErtError(f"{where}: у вида reference задаётся object (имя, например Справочник.Контрагенты) "
                       "или code и object_id (номер в метаданных), без длины и точности")


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


def module_names(module_text):
    """Casefolded (procedure and function names, module Перем names) of a module."""
    from .lint77 import Source, module_variables, parse
    parsed = parse(Source("module", "module", module_text))
    return set(parsed.symbols), set(module_variables(parsed))


def platform_functions():
    """Casefolded global function names of the packaged platform catalog."""
    from .catalog77 import load_packaged
    return {name.casefold() for item in load_packaged()["items"] if item["kind"] == "global_function"
            for name in (item["name_ru"], item["name_en"]) if name}


def _reserved():
    from .catalog77 import load_packaged
    return {name.casefold() for name in load_packaged()["reserved"]["names"]}


class _Changes:
    def __init__(self, module_text, metadata=None, template=None):
        self.items = []
        self.module_text = module_text
        self.metadata = metadata
        self.template = template
        self._names = None

    def existing(self, data_type):
        """A reference type of an existing field as code and number: {"kind": "reference", "code", "object_id"}.

        A named kind is numbered by the template's own copy, where 1C reads the
        number of the field (task 013); object_id is None when the copy lacks it.
        """
        if data_type is None or data_type.get("kind") != REFERENCE or "object_id" in data_type:
            return data_type
        code, kind = parse_name(data_type["object"])
        number = 0 if kind is None else self.template.number(code, kind) if self.template else None
        return {"kind": REFERENCE, "code": code, "object_id": number}

    def module(self, what):
        if self._names is None:
            if self.module_text is None:
                raise ErtError(f"Связь {what} с модулем проверяется только при сборке с модулем")
            self._names = module_names(self.module_text)
        return self._names

    def procedures(self):
        return self.module("формулы")[0] | platform_functions()


def _caption(value, where):
    try:
        value.encode("cp1251")
    except UnicodeEncodeError as error:
        raise ErtError(f"{where}: символ {value[error.start:error.end]!r} вне Windows-1251") from None
    return value


def _formula(value, kind, where, changes):
    """A formula the class takes: a call Имя(…) of a module procedure or a platform function."""
    if kind not in FORMULAS:
        raise ErtError(f"{where}: формула элемента {kind} не поддерживается")
    if not value and not FORMULAS[kind]:
        return value
    match = CALL.match(value)
    if not match:
        raise ErtError(f"{where}: формула элемента {kind} должна быть вызовом Имя(…), получено {value!r}")
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


def _new_type(item, kind, where, changes):
    """The checked data type of a new control: {kind, length, precision[, code, object_id, object]} or None."""
    kinds = NEW_CLASSES[kind]["kinds"]
    value = item.get("type", CHECKBOX_TYPE if kind == "CHECKBOX" else None)
    if value is None:
        return None
    if not kinds:
        raise ErtError(f"{where}: у элемента {kind} нет типа данных")
    if value["kind"] not in kinds:
        raise ErtError(f"{where}: тип {value['kind']} не подходит элементу {kind} (допустимо: {', '.join(kinds)})")
    if value["kind"] == REFERENCE:
        if "object" not in value:
            raise ErtError(f"{where}: тип нового поля задаётся именем объекта (object), не номером: "
                           "номер принадлежит конфигурации и без метаданных не проверяется")
        code, kind = parse_name(value["object"])
        if code not in REFERENCE_FLAGS:
            raise ErtError(f"{where}: новое поле типа {TYPES[code]} не поддерживается (в формах корпуса нет "
                           "такого поля, образца записи нет)")
        if kind is not None and changes.metadata is None:
            raise ErtError(f"{where}: тип {value['object']} — вид объекта конфигурации; он сверяется по именам "
                           "с метаданными целевой базы: build --metadata <база>/1Cv7.MD или [build] metadata "
                           "в профиле (run берёт 1Cv7.MD базы стенда)")
        # The number of a kind is given by the copy the ERT will carry (_numbered).
        return {"kind": REFERENCE, "length": 0, "precision": 0, "code": code, "name": kind}
    length, precision = value.get("length", 0), value.get("precision", 0)
    rules = {"string": (length >= 0 and precision == 0, "длина ≥ 0, без точности"),
             "number": (length >= 1 and 0 <= precision < length, "длина ≥ 1, 0 ≤ точность < длина"),
             "date": (length == 0 and precision == 0, "без длины и точности")}
    valid, rule = rules[value["kind"]]
    if kind == "CHECKBOX":
        valid, rule = (length, precision) == (1, 0), "флажок — число длины 1 без точности"
    if not valid:
        raise ErtError(f"{where}: тип {value['kind']} длины {length} и точности {precision} не поддерживается "
                       f"({rule})")
    return {"kind": value["kind"], "length": length, "precision": precision}


def _box(item):
    return item["x"], item["y"], item["x"] + item["width"], item["y"] + item["height"]


def _overlap(a, b):
    """Rectangles (x0, y0, x1, y1) share area; touching edges do not overlap."""
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _grouped(a, b):
    """One of two controls is a group box that wholly contains the other."""
    def contains(outer, inner):
        (x0, y0, x1, y1), (u0, v0, u1, v1) = _box(outer), _box(inner)
        return outer["class"] == GROUP and x0 <= u0 and y0 <= v0 and x1 >= u1 and y1 >= v1
    return contains(a, b) or contains(b, a)


def _placement(before, after, placed):
    """Refuse a new overlap of a new, moved or relayered control with a control of its layer.

    Real forms overlap (614 pairs in 135 corpus forms, mostly drop-down lists), so
    only overlaps the change creates are refused; a group box may contain a control.
    """
    old = {item["id"]: item for item in before}
    for item in after:
        if item["id"] not in placed:
            continue
        for other in after:
            if other["id"] == item["id"] or other["layer"] != item["layer"] \
                    or not _overlap(_box(item), _box(other)) or _grouped(item, other):
                continue
            was = old.get(item["id"]), old.get(other["id"])
            if all(was) and was[0]["layer"] == was[1]["layer"] and _overlap(_box(was[0]), _box(was[1])):
                continue  # the template already overlapped them
            x0, y0, x1, y1 = _box(other)
            raise ErtError(f"Элемент {item['id']} ({item['x']}, {item['y']}, {item['width']}×{item['height']}) "
                           f"накладывается на элемент {other['id']} ({x0}, {y0}, {x1 - x0}×{y1 - y0}) "
                           f"слоя {item['layer']!r}; наложение допускается, только если рамка группы "
                           "целиком содержит элемент")


def _shown(data_type, changes):
    """A type for a message; a reference also by code/number and its name in the template's copy."""
    if not data_type or data_type.get("kind") != REFERENCE:
        return str(data_type)
    number = changes.existing(data_type)
    if number["object_id"] is None:
        return f"{data_type['object']} (нет в копии метаданных шаблона)"
    name = type_name(number["code"], number["object_id"], changes.template)
    shown = f"{number['code']}/{number['object_id']}" + (f" = {name}" if name else "")
    return f"{data_type['object']} ({shown})" if "object" in data_type else shown


def _same_type(new, old, changes):
    """Types of an existing control are equal; a named kind is compared by its number in the template's copy."""
    kind = (new or {}).get("kind")
    if kind != (old or {}).get("kind") or kind != REFERENCE:
        return new == old
    return changes.existing(new) == changes.existing(old)


def _numbered(records, pending, changes):
    """Number the new kind fields by the copy the ERT will carry; returns "kept" or "replaced" (task 013).

    1C turns the number of a field into a name by the ERT's own copy and looks the
    name up in the open configuration, where a kind it lacks silently costs the
    field its kind: a catalog or a document of no kind, an enumeration becomes a
    string (the owner's checks in Торговля+Склад 9.2, tasks 012 and 013). A number
    the copy lacks fails the ERT with an empty copy (task 012: R1) and silently makes
    the field one of any object with another copy (task 013: K5, K5b). So every kind
    number must be in the copy, every kind must be in the target base by name, and
    a different number there is no matter. The copy stays when it has every new
    kind; otherwise the target's metadata replace it, and the old kind fields are
    renumbered by name.
    """
    template, target = changes.template, changes.metadata
    old = []
    for record in records:
        key = _kind(record)
        if key is None:
            continue
        name = template.names.get(key) if template else None
        if name is None:
            if template:
                where = f"номера {key[0]}/{key[1]} нет в копии метаданных шаблона, {template.describe()}"
            else:
                where = f"поле вида {key[0]}/{key[1]}, а в шаблоне нет копии метаданных (потока {STREAM})"
            raise ErtError(f"Элемент {record[ID]}: {where}; 1С ищет вид поля в ней, и без него поле теряет вид: "
                           f"становится «любым» ({TYPES[key[0]]} без вида), а с пустой копией 1С не создаёт отчёт")
        old.append((record, key, name))
    if target is not None:
        missing = [f"элемент {record[ID]} {TYPES[code]}.{name}" for record, (code, _), name in old
                   if target.number(code, name) is None]
        missing += [f"новый элемент {record[ID]} {TYPES[code]}.{kind}" for record, code, kind, _ in pending
                    if target.number(code, kind) is None]
        if missing:
            raise ErtError(f"В метаданных целевой базы {target.describe()} нет видов полей формы: "
                           f"{', '.join(missing)}; 1С откроет форму, но такие поля молча потеряют вид: "
                           "справочник, документ или счёт станет «любым», перечисление — строкой")
    keep = all(template is not None and template.number(code, kind) is not None for _, code, kind, _ in pending)
    if not keep and template is None:
        raise ErtError(f"В шаблоне нет своей копии метаданных (потока {STREAM}), а 1С ищет вид поля "
                       "в ней: поле вида в такой шаблон не встроить")
    copy = template if keep else target
    for record, code, kind, change in pending:
        number = copy.number(code, kind)
        record[OBJECT] = str(number)
        change["type"] = {"object": f"{TYPES[code]}.{copy.names[code, number]}", "code": code, "object_id": number}
    if not keep:
        for record, (code, number), name in old:
            renumbered = target.number(code, name)
            if renumbered != number:
                record[OBJECT] = str(renumbered)
                changes.items.append({"control": int(record[ID]), "property": "object_id", "from": number,
                                      "to": renumbered, "object": f"{TYPES[code]}.{name}"})
    return "kept" if keep else "replaced"


# A rebuilt dialog: its text, the changes, what the ERT's copy of the metadata needs
# ("kept" or "replaced" by the target's) and the kind fields (task 013).
Rebuilt = collections.namedtuple("Rebuilt", "text changes ert_metadata kinds")


def apply(text, description, module_text=None, metadata=None, template=None):
    """New dialog text from the template text and a description; returns (text, changes)."""
    return tuple(rebuild(text, description, module_text, metadata, template)[:2])


def rebuild(text, description, module_text=None, metadata=None, template=None):
    """The dialog of a description over the template text, as Rebuilt.

    metadata (metadata77.Metadata of the target base) is checked by the names of
    the kinds; template (the ERT's own copy) names and numbers them (task 013).
    """
    tree, frame, section = _structure(text)
    current = describe(text, version=description["schema_version"])
    if description["template_dialog_sha256"] != current["template_dialog_sha256"]:
        raise ErtError("Описание сделано для другого шаблона: хеш диалога не совпадает")
    typed = description["schema_version"] >= 2
    changes = _Changes(module_text, metadata, template)
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
    placed = set()
    for record, item, old in zip(records, items, current["controls"]):
        where = f"Элемент {old['id']}"
        if item.get("id") != old["id"] or item["class"] != old["class"]:
            raise ErtError(f"{where}: перестановка, удаление или смена ID/класса не поддерживаются "
                           f"(в описании id={item.get('id')!r}, класс {item['class']})")
        missing = [key for key in CONTROL_KEYS_V1 if key not in item]
        if missing:
            raise ErtError(f"{where}: нет свойств {', '.join(missing)}")
        if typed and not _same_type(item.get("type"), old.get("type"), changes):
            raise ErtError(f"{where}: изменение типа данных существующего элемента не поддерживается "
                           f"(в шаблоне {_shown(old.get('type'), changes)}, "
                           f"в описании {_shown(item.get('type'), changes)})")
        moved = False
        for key in CONTROL_KEYS_V1[2:]:
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
                placed.add(old["id"])
            else:
                record[dict(GEOMETRY)[key]] = str(item[key])
                moved = True
            changes.items.append({"control": old["id"], "property": key, "from": old[key], "to": item[key]})
        if moved:
            _geometry(item, width, height, where)
            placed.add(old["id"])
    stored = [old["id"] for old in current["controls"]]
    pending = []
    for number, item in enumerate(items[len(records):], start=len(records) + 1):
        kind = item["class"]
        if kind not in NEW_CLASSES:
            raise ErtError(f"controls[{number}]: новый элемент класса {kind} не поддерживается "
                           f"(поддерживаются {', '.join(NEW_CLASSES)})")
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
        where = f"Новый элемент {control_id} ({kind})"
        required = ("x", "y", "width", "height") + NEW_CLASSES[kind]["required"]
        missing = [key for key in required if key not in item or item[key] == ""]
        if missing:
            raise ErtError(f"{where}: нет свойств {', '.join(missing)}")
        _geometry(item, width, height, where)
        data_type = _new_type(item, kind, where, changes)
        if data_type and data_type["kind"] == REFERENCE:
            record = _default(kind, "1350565888", data_type["code"], flags=REFERENCE_FLAGS[data_type["code"]])
        else:
            record = list(DEFAULTS[kind, data_type and data_type["kind"]])
        record[CAPTION] = _caption(item.get("caption", ""), where)
        for key, index in GEOMETRY:
            record[index] = str(item[key])
        record[ID] = str(control_id)
        if data_type:
            record[LENGTH], record[PRECISION] = str(data_type["length"]), str(data_type["precision"])
        formula = item.get("formula", "")
        record[FORMULA] = _formula(formula, kind, where, changes) if formula or FORMULAS.get(kind) else ""
        record[IDENTIFIER] = item.get("identifier", "")
        record[LAYER] = item.get("layer", form["layers"][0] if form["layers"] else "")
        section.append(record)
        placed.add(control_id)
        change = {"control": control_id, "added": kind}
        if data_type and data_type["kind"] == REFERENCE:
            if data_type["name"] is None:
                change["type"] = {"object": TYPES[data_type["code"]], "code": data_type["code"], "object_id": 0}
            else:
                pending.append((record, data_type["code"], data_type["name"], change))
        changes.items.append(change)
    ert_metadata = _numbered(records, pending, changes)
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
            procedures, variables = changes.module("идентификатора")
            if name.casefold() in procedures | variables:
                # 1C compiles such a module, but a Перем shadows the form attribute: the
                # module's assignments never reach the field (task 011, E4 and E4b).
                if name.casefold() in procedures:
                    raise ErtError(f"{where}: идентификатор {name!r} совпадает с процедурой или функцией "
                                   "модуля: имя неоднозначно")
                raise ErtError(f"{where}: идентификатор {name!r} совпадает с переменной Перем модуля: 1С такой "
                               "модуль примет, но переменная перекроет реквизит формы, и модуль не увидит поле")
    _placement(current["controls"], [_control(record) for record in section[1:]], placed)
    text = serialize_dialog(tree)
    return Rebuilt(text, changes.items, ert_metadata,
                   kinds(text, template if ert_metadata == "kept" else metadata, metadata))


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


def extract(input_path, output, metadata=None):
    """The kinds of reference fields are named by the copy of the metadata the ERT carries, as 1C
    reads them; metadata, a 1Cv7.MD path, is checked by these names (task 013)."""
    from .artifacts import _container, _destination, _input, _publish
    from .metadata77 import Metadata
    input_path, raw = _input(input_path)
    inputs = [(input_path, raw)]
    if metadata is not None:
        metadata_path, metadata_data = _input(metadata)
        inputs.append((metadata_path, metadata_data))
        metadata = Metadata(metadata_data, metadata_path)
    output = _destination(output)
    compound, _, _ = _container(raw)
    text = decode_dialog(compound.read_stream(dialog_entry(compound)))
    own = Metadata.of_ert(compound)
    description = describe(text, own)
    payload = dumps(description).encode("utf-8")
    result = _publish(output, payload, lambda data: describe(text, own) == loads(data) or _mismatch(),
                      inputs)
    fields = kinds(text, own, metadata)
    report = {"schema_version": 1, "tool": "harness77", "operation": "form-extract", "status": "passed",
              "scope": "ert_form_extract", "input": {"path": str(input_path), "sha256": sha256(raw)},
              "output": {**result, "encoding": "utf-8"},
              "template_dialog_sha256": description["template_dialog_sha256"],
              "controls": len(description["controls"]),
              "names_from": "ert" if own else None,
              "references_by_number": by_number(description), "kinds": fields,
              "inputs_unchanged": True, "platform_checked": False}
    if own is not None:
        report["ert_metadata"] = {"sha256": own.sha256, "configuration": own.configuration}
    if metadata is not None:
        report["metadata"] = metadata.public()
        report["missing_in_metadata"] = [{"control": row["control"], "object": row["object"]}
                                         for row in fields if row["target_object_id"] is None]
    return report


def _mismatch():
    raise ErtError("Описание после обратного чтения отличается")


def main(argv):
    parser = argparse.ArgumentParser(prog="harness77 form-extract", allow_abbrev=False,
                                     description=f"Описание формы ERT в JSON (схема {SCHEMA} {SCHEMA_VERSION})")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Новый файл в существующем каталоге")
    parser.add_argument("--metadata", type=Path,
                        help="1Cv7.MD базы: сверить виды ссылочных полей с ней по именам")
    args = parser.parse_args(argv)
    try:
        report = extract(args.input, args.output, args.metadata)
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return 0
    except (OSError, ValueError, ErtError, struct.error, RuntimeError) as exc:
        report = {"schema_version": 1, "tool": "harness77", "operation": "form-extract", "status": "blocked",
                  "scope": "ert_form_extract", "output_path": str(args.output), "error": str(exc),
                  "platform_checked": False}
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 2
