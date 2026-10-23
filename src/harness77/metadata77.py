"""Names of the configuration objects in a 1Cv7.MD, for reference-typed form fields (task 012).

A form field of a reference type stores a type code and the number of a
metadata object (fields 14 and 17 of the dialog record, as attributes do in
1Cv7.MD). The number belongs to the configuration, so a description names the
object and the build translates the name with the metadata of the target base.

The ``Main MetaData Stream`` of 1Cv7.MD is the brace text of the dialog with the
same length prefix (static survey of base-for-test, task 012): catalogs in
``SbCnts``, documents in ``Documents``, enumerations in ``EnumList``, charts of
accounts in ``Buh`` -> ``Plans``; an object record starts {"<number>", "<name>", …}.

An ERT carries its own copy in a stream of the same name, followed by a NUL
byte (all 416 corpus forms), and 1C finds the kind of a form field there: with
the empty copy of FIO.ERT a field of a kind is refused, one of any object is
not (task 012, R1 and its diagnosis). The copy turns the number into a name, and
1C looks the name up in the open configuration (the owner's check in
Торговля+Склад 9.2), so a target base is compared by names (task 013).

Module code names objects of more classes (task 018): constants in ``Consts``,
registers in ``Registers``, reports in ``ReportList``, processings in ``CalcVars``,
journals in ``Journalisters``, subconto kinds in ``Buh`` -> ``SbKind``, the values
of an enumeration in its ``EnumVal`` (static survey of base-for-test and of the
owner's Торговля+Склад 9.2). They are read on demand, so a form build never
depends on them.

The attributes of an object follow its record (task 019): ``Params`` of a catalog,
``Head Fields`` and ``Table Fields`` of a document with the common ``GenJrnlFldDef``
of every document, ``Props``, ``Figures`` and ``Flds`` of a register. An attribute
record is {"<number>", "<name>", "<comment>", "<synonym>", "<type code>", "<length>",
"<precision>", "<kind number>", …}, as in base-for-test and Торговля+Склад 9.2.
"""

import hashlib
from pathlib import Path
import re
import struct

from .ert_module import CompoundFile, ErtError, _dialog_length, parse_dialog

STREAM = "Main MetaData Stream"
# Type codes of reference types and their names in the 1C 7.7 language.
TYPES = {"B": "Справочник", "O": "Документ", "E": "Перечисление", "T": "Счет", "K": "ВидСубконто",
         "P": "ПланСчетов"}
CODES = {name.casefold(): code for code, name in TYPES.items()}
# Codes whose fields may take any object of the type (number 0): every code but the
# enumeration, which neither the corpus nor the metadata has without a kind.
ANY = ("B", "O", "T", "K", "P")
# Codes with kinds and where their names are: the top-level section or Buh -> Plans.
SECTIONS = {"B": "SbCnts", "O": "Documents", "E": "EnumList", "T": "Plans"}
# Classes of objects module code names, and their sections (task 018); Buh sections are nested.
CLASSES = {"Константа": "Consts", "Справочник": "SbCnts", "Документ": "Documents", "Перечисление": "EnumList",
           "Регистр": "Registers", "Отчет": "ReportList", "Обработка": "CalcVars", "Журнал": "Journalisters",
           "ПланСчетов": "Plans", "ВидСубконто": "SbKind"}
BUH = ("Plans", "SbKind")
NUMBER = re.compile(r"[1-9][0-9]*\Z")
# Classes with attributes and the subsections of their records (task 019); GENERAL are every document's.
ATTRIBUTES = {"Справочник": ("Params",), "Документ": ("Head Fields", "Table Fields"),
              "Регистр": ("Props", "Figures", "Flds")}
GENERAL = "GenJrnlFldDef"
ATTRIBUTE_TYPES = ("S", "N", "D", "B", "O", "E", "T", "K", "P", "U")
# Folders of 1Cv7.MD modules that run in the context of an object (task 020) and the type code
# of their number: a document's form and module, a catalog's element and group forms. A list
# form is numbered as the form in its catalog's (SubList) or journal's (Journal) record.
MODULE_OWNERS = {"Document": "O", "Transact": "O", "Subconto": "B", "SubFolder": "B"}
LIST_FORMS = {"SubList": ("SbCnts", "Справочник"), "Journal": ("Journalisters", "Журнал")}
# Folders of the form modules of reports and processings, numbered as their records (task 021).
FORM_OBJECTS = {"Report": "Отчет", "CalcVar": "Обработка"}
# The forms of a catalog an attribute may be on, as Attribute.use names them (task 023).
USE = ("element", "group")
# Fields of a catalog's record (task 023): 4 — the number of its owner catalog, 0 without one;
# 11 — how it is edited, by the element forms of base-for-test and Торговля+Склад 9.2.
CATALOG_OWNER, CATALOG_EDIT = 4, 11
CATALOG_EDITS = {"0": "list", "1": "dialog", "2": "both"}


class Attribute:
    """An attribute of a metadata object: its name, type code and the class and name of its kind, if any.

    length, precision and the number of its kind complete the type; part is the list it is in
    ("Head Fields", "Table Fields", GENERAL, "Params"…), as a form field of it needs (task 022).
    use is ("element", "group"), the forms of a catalog's attribute (task 023), or None when unknown.
    """

    def __init__(self, name, code, kind, length=None, precision=None, number=0, part=None, use=None):
        self.name, self.code, self.kind = name, code, kind
        self.length, self.precision, self.number, self.part = length, precision, number, part
        self.use = use

    @property
    def target(self):
        """(class, kind name) of the object a reference attribute names, or None."""
        return (TYPES[self.code], self.kind) if self.kind and self.code in ("B", "O") else None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def type_name(code, object_id, metadata=None):
    """The name of a reference type, or None when the number has no name here."""
    if code not in TYPES:
        return None
    if object_id == 0:
        return TYPES[code] if code in ANY else None
    if metadata is None or code not in SECTIONS:
        return None
    name = metadata.names.get((code, object_id))
    return f"{TYPES[code]}.{name}" if name else None


def parse_name(value):
    """(code, kind or None) of a type name such as "Справочник.Контрагенты"; refuses unknown forms."""
    head, dot, kind = value.partition(".")
    code = CODES.get(head.casefold())
    if code is None:
        raise ErtError(f"Тип {value!r}: неизвестный ссылочный тип {head!r} "
                       f"(допустимо: {', '.join(TYPES.values())})")
    if not dot:
        if code not in ANY:
            raise ErtError(f"Тип {value!r}: {TYPES[code]} без вида не поддерживается — укажите вид, "
                           f"например {TYPES[code]}.<Имя>")
        return code, None
    if code not in SECTIONS:
        raise ErtError(f"Тип {value!r}: у типа {TYPES[code]} нет видов")
    if not kind:
        raise ErtError(f"Тип {value!r}: после точки нужно имя вида")
    return code, kind


class Metadata:
    """Object names of one 1Cv7.MD or of an ERT's copy: (code, number) -> name and back."""

    def __init__(self, data, path=None):
        """A 1Cv7.MD file from its bytes; sha256 is the file's."""
        try:
            compound = CompoundFile(data)
        except (ErtError, ValueError, IndexError, struct.error) as error:
            raise ErtError(f"Метаданные не читаются как 1Cv7.MD: {error}") from error
        payload = _payload(compound)
        if payload is None:
            raise ErtError(f"Метаданные: нужен ровно один поток {STREAM!r} (это не 1Cv7.MD?)")
        self._read(payload, sha256(data), path, "1Cv7.MD")

    @classmethod
    def of_ert(cls, compound):
        """The copy an ERT carries, or None without one; sha256 is the stream's."""
        payload = _payload(compound)
        if payload is None:
            return None
        metadata = cls.__new__(cls)
        metadata._read(payload, sha256(payload), None, "копия метаданных ERT")
        return metadata

    def ert_stream(self):
        """The stream as an ERT carries it: the length prefix, the text and a NUL byte."""
        return self.stream if self.stream.endswith(b"\0") else self.stream + b"\0"

    def _read(self, payload, digest, path, label):
        self.path, self.sha256, self.stream, self.label = path, digest, payload, label
        self._tree, self._objects, self._attributes = _tree(payload), None, None
        task = _section(self._tree, "TaskItem")
        self.configuration = task[1][1] if task and len(task) > 1 and isinstance(task[1], list) \
            and len(task[1]) > 1 and isinstance(task[1][1], str) else None
        self.names, self.numbers = {}, {}
        for code, key in SECTIONS.items():
            for number, name in _records(self._section(key), key):
                self.names[code, number] = name
                self.numbers[code, name.casefold()] = number

    def _section(self, key):
        """A top-level section, or one of Buh (plans of accounts, subconto kinds)."""
        if key not in BUH:
            return _section(self._tree, key)
        found = None
        for item in (_section(self._tree, "Buh") or [None])[1:]:
            if isinstance(item, list):
                found = _section(item, key) if found is None else found
        return found

    def objects(self):
        """Names by class for module code (task 018): {class: {casefolded name: name}}; refuses unknown records."""
        if self._objects is None:
            objects = {name: {key.casefold(): key for _, key in _records(self._section(section), section)}
                       for name, section in CLASSES.items()}
            values = {}
            for record in (self._section("EnumList") or [None])[1:]:
                found = [item for item in record[2:] if isinstance(item, list) and item[:1] == ["EnumVal"]]
                if len(found) > 1:
                    raise ErtError(f"Метаданные: у перечисления {record[1]!r} повторяется список значений")
                values[record[1].casefold()] = {name.casefold(): name for _, name in
                                                _records(found[0] if found else None, f"EnumVal {record[1]}")}
            self._objects = objects, values
        return self._objects[0]

    def enum_values(self, kind):
        """{casefolded value: value} of an enumeration by its name, or None without one."""
        self.objects()
        return self._objects[1].get(kind.casefold())

    def attributes(self, name, kind):
        """{casefolded attribute: Attribute} of a catalog, document or register by its name, or None without it.

        A document has its head, table and common attributes (task 019); an attribute record
        of another layout or a repeated name refuses them all, as objects() does.
        """
        if self._attributes is None:
            general = [_attribute(record, GENERAL, self.names, GENERAL)
                       for record in (_section(self._tree, GENERAL) or [None])[1:]]
            found = {}
            for cls, subsections in ATTRIBUTES.items():
                key, found[cls] = CLASSES[cls], {}
                for record in (self._section(key) or [None])[1:]:
                    where = f"{key} {record[1]}"
                    items = [item for item in record[2:] if isinstance(item, list) and item[:1]
                             and item[0] in subsections]
                    if len({item[0] for item in items}) < len(items):
                        raise ErtError(f"Метаданные: в записи {where} повторяется список реквизитов")
                    attributes = [_attribute(row, f"{where} {item[0]}", self.names, item[0])
                                  for item in items for row in item[1:]]
                    attributes += general if cls == "Документ" else []
                    names = {attribute.name.casefold(): attribute for attribute in attributes}
                    if len(names) < len(attributes):
                        raise ErtError(f"Метаданные: у объекта {where} повторяется имя реквизита")
                    found[cls][record[1].casefold()] = names
            self._attributes = found
        return self._attributes[name].get(kind.casefold())

    def owner(self, folder, number):
        """(class, kind) of the object whose module or form a 1Cv7.MD folder holds, or None.

        Document_<n> and Transact_<n> are document n, Subconto_<n> and SubFolder_<n> catalog n,
        SubList_<n> and Journal_<n> the catalog or journal whose record lists form n (static
        survey of base-for-test and Торговля+Склад 9.2, task 020).
        """
        if folder in MODULE_OWNERS:
            code = MODULE_OWNERS[folder]
            name = self.names.get((code, number))
            return (TYPES[code], name) if name else None
        if folder in LIST_FORMS:
            found = self._list_form(folder, number)
            return found[:2] if found else None
        return None

    def module_object(self, folder, number):
        """(class, name, form name or None) of the object a 1Cv7.MD module folder belongs to, or None.

        As owner(), and the form module of a report or processing is numbered as its record;
        a list form (SubList, Journal) also names its form (task 021).
        """
        if folder in LIST_FORMS:
            return self._list_form(folder, number)
        if folder in FORM_OBJECTS:
            cls = FORM_OBJECTS[folder]
            names = dict(_records(self._section(CLASSES[cls]), CLASSES[cls]))
            return (cls, names[number], None) if number in names else None
        found = self.owner(folder, number)
        return (*found, None) if found else None

    def _list_form(self, folder, number):
        """(class, name, form name) of the catalog or journal whose record lists form n, or None."""
        key, cls = LIST_FORMS[folder]
        for record in (self._section(key) or [None])[1:]:
            for item in record[2:]:
                if not isinstance(item, list) or item[:1] != ["Form"]:
                    continue
                for form in item[1:]:
                    if isinstance(form, list) and form[:1] == [str(number)]:
                        return cls, record[1], form[1] if len(form) > 1 and isinstance(form[1], str) else None
        return None

    def catalog(self, kind):
        """{"owner": name or None, "edit": "list" | "dialog" | "both" | None} of catalog ``kind`` (task 023).

        Field 4 of its record is the owner's number (Договоры → Контрагенты in base-for-test; 9 of 58
        catalogs there, 16 of 60 in Торговля+Склад 9.2, each a catalog). Field 11 is how it is edited:
        every catalog with 1 or 2 has its own element form (26 and 35), most with 0 an empty one, and
        1C opens no element form of two with 0 (task 023, e-attribute and e-in-list). Refuses an
        unknown catalog or owner.
        """
        for record in (self._section("SbCnts") or [None])[1:]:
            if not (isinstance(record, list) and len(record) > CATALOG_OWNER and isinstance(record[1], str)
                    and record[1].casefold() == kind.casefold()):
                continue
            owner = record[CATALOG_OWNER]
            if owner != "0" and (not (isinstance(owner, str) and NUMBER.match(owner))
                                 or ("B", int(owner)) not in self.names):
                raise ErtError(f"Метаданные: у справочника {record[1]!r} неизвестный владелец {owner!r}")
            edit = record[CATALOG_EDIT] if len(record) > CATALOG_EDIT and isinstance(record[CATALOG_EDIT], str) else None
            return {"owner": None if owner == "0" else self.names["B", int(owner)], "edit": CATALOG_EDITS.get(edit)}
        raise ErtError(f"Метаданные: нет справочника {kind!r}")

    def number(self, code, kind):
        """The number of a kind by its name, as 1C finds it (letter case aside), or None."""
        return self.numbers.get((code, kind.casefold()))

    def resolve(self, value):
        """(code, number, canonical name) of a type name; refuses a kind these metadata lack."""
        code, kind = parse_name(value)
        if kind is None:
            return code, 0, TYPES[code]
        number = self.number(code, kind)
        if number is None:
            raise ErtError(f"Тип {value!r}: в метаданных {self.describe()} нет объекта "
                           f"{TYPES[code]}.{kind}")
        return code, number, f"{TYPES[code]}.{self.names[code, number]}"

    def describe(self):
        name = Path(self.path).name if self.path else self.label
        return f"{name} ({self.configuration or 'без имени конфигурации'}, {self.sha256[:8]}…)"

    def public(self):
        return {"path": str(self.path) if self.path else None, "sha256": self.sha256,
                "configuration": self.configuration}


def _records(section, key):
    """(number, name) of each object record {"<number>", "<name>", …} of a section; refuses others."""
    seen = set()
    for record in (section or [None])[1:]:
        if not isinstance(record, list) or len(record) < 2 or not all(
                isinstance(x, str) for x in record[:2]) or not NUMBER.match(record[0]):
            raise ErtError(f"Метаданные: неизвестная запись в разделе {key}: {str(record)[:80]}")
        name = record[1]
        if not name or name.casefold() in seen:
            raise ErtError(f"Метаданные: имя {name!r} в разделе {key} пусто или повторяется")
        seen.add(name.casefold())
        yield int(record[0]), name


def _use(record, part):
    """The forms a catalog's attribute is for: fields 11 and 12 of its Params record (task 023).

    Element forms show only attributes with field 11 = 1, group forms only with field 12 = 1: every
    such field of base-for-test, all but one of the 240 of Торговля+Склад 9.2; no attribute of the
    two has neither. A record without them gives None: unknown, not refused.
    """
    flags = record[11:13] if part == "Params" else []
    if len(flags) != 2 or not all(flag in ("0", "1") for flag in flags) or flags == ["0", "0"]:
        return None
    return tuple(form for form, flag in zip(USE, flags) if flag == "1")


def _attribute(record, where, names, part=None):
    """An Attribute of a record {"<number>", "<name>", "", "", "<type code>", "<length>", "<precision>",
    "<kind number>", …}."""
    if (not isinstance(record, list) or len(record) < 8 or not all(isinstance(x, str) for x in record[:8])
            or not NUMBER.match(record[0]) or not record[1] or record[4] not in ATTRIBUTE_TYPES
            or not record[7].isdigit()):
        raise ErtError(f"Метаданные: неизвестная запись реквизита в разделе {where}: {str(record)[:80]}")
    number = int(record[7])
    length, precision = (int(x) if x.isdigit() else None for x in record[5:7])
    return Attribute(record[1], record[4], names.get((record[4], number)) if number else None,
                     length, precision, number, part, _use(record, part))


def _payload(compound):
    entries = [e for e in compound.directory_entries if e.object_type == 2 and e.name == STREAM]
    if len(entries) > 1:
        raise ErtError(f"Метаданные: поток {STREAM!r} повторяется")
    return compound.read_stream(entries[0]) if entries else None


def _tree(payload):
    length, offset = _dialog_length(payload)
    if payload[offset + length:] not in (b"", b"\0") or len(payload) < offset + length:
        raise ErtError(f"Метаданные: длина потока {STREAM!r} в заголовке не совпадает с данными")
    try:
        tree = parse_dialog(payload[offset:offset + length].decode("cp1251"))
    except UnicodeDecodeError as error:
        raise ErtError("Метаданные не декодируются как Windows-1251") from error
    if _section(tree, "MainDataContDef") is None:
        raise ErtError("Метаданные: нет раздела MainDataContDef (это не 1Cv7.MD?)")
    return tree


def _section(tree, name):
    found = [item for item in tree if isinstance(item, list) and item[:1] == [name]]
    if len(found) > 1:
        raise ErtError(f"Метаданные: раздел {name} повторяется")
    return found[0] if found else None


def load(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ErtError(f"Метаданные должны быть файлом: {path}")
    return Metadata(path.read_bytes(), path)
