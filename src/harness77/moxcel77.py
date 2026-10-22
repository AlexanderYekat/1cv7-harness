"""Named areas of a 1C 7.7 table (MOXCEL worksheet), for the context of form modules (task 020).

A report or processing form module reads the named areas of its form's table as
variables (platform catalog: «Модуль формы отчета (обработки)/Атрибуты <ИмяОбласти>»).
The form's table is the worksheet whose title (Container.Contents) the form's
Container.Profile names: {"MoxelName","<title>",""}. Native probes of task 020: naming
another worksheet there makes its areas the variables and the former ones undeclared;
"\\x01Blank" or "" names none. In base-for-test's ExtForms all 11 246 such reads are
areas of the named worksheet, in each case also the first listed.

A worksheet stream starts with "MOXCEL" and ends with its named areas: a 32-bit
count, then for each area an MFC string (a length byte, 0xFF and a 16-bit length for
longer ones, cp1251 bytes) and seven 32-bit fields, the first being the kind of area
(1 a rectangle, 2 rows in the corpus). Static survey of 1931 worksheets of the stand's
ExtForms and 1Cv7.MD: the list always ends the stream.
"""

import re
import struct

SIGNATURE = b"MOXCEL"
WORKSHEET = re.compile(r'\{"Moxcel\.Worksheet","(Page\.\d+)","([^"]*)"')
MOXEL_NAME = re.compile(r'\{"MoxelName","([^"]*)"')
# Kinds of areas are small numbers; a larger first field means a misread, not an area.
MAX_KIND = 16
ENTRY = 28


def _string(raw, offset):
    size = raw[offset]
    offset += 1
    if size == 0xFF:
        size = struct.unpack_from("<H", raw, offset)[0]
        offset += 2
    return raw[offset:offset + size], offset + size


def _areas_at(raw, offset):
    """Area names if a count at offset is followed by exactly that many areas up to the end."""
    count = struct.unpack_from("<I", raw, offset)[0]
    if count * (ENTRY + 2) > len(raw) - offset - 4:
        return None
    offset, names = offset + 4, []
    try:
        for _ in range(count):
            name, offset = _string(raw, offset)
            kind = struct.unpack_from("<I", raw, offset)[0]
            offset += ENTRY
            text = name.decode("cp1251")
            # Any printable name is an area ("200" in Conv7742.ERT); only identifiers are variables.
            if kind > MAX_KIND or not text or not text.isprintable():
                return None
            names.append(text)
    except (IndexError, struct.error, UnicodeDecodeError):
        return None
    return names if offset == len(raw) else None


def area_names(raw):
    """Names of the named areas of a worksheet stream; None when it is not one this reader knows.

    The list is found from its end: the earliest offset whose count and areas reach
    exactly the end of the stream (a later one would be a coincidence inside the list).
    """
    if not raw.startswith(SIGNATURE):
        return None
    found = None
    for offset in range(len(raw) - 4, len(SIGNATURE) - 1, -1):
        names = _areas_at(raw, offset)
        if names is not None:
            found = names
    return found


def worksheets(contents):
    """(stream name, title) of each worksheet a Container.Contents lists, in its order."""
    return WORKSHEET.findall(contents.decode("cp1251", "replace"))


def form_table(contents, profile):
    """The stream name of the worksheet Container.Profile names as the form's table, or None."""
    match = MOXEL_NAME.search(profile.decode("cp1251", "replace"))
    titles = {title: page for page, title in worksheets(contents)}
    return titles.get(match.group(1)) if match else None
