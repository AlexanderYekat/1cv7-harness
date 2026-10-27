"""The open ERT form among the owned windows, its geometry, clicks and typing (tasks 008, 011).

Only windows of the verified server thread on the run's own private desktop are
read; the identity of the process is rechecked immediately before every message
(the ``OwnedModal`` rules of stage 2). A click is a ``BM_CLICK`` message to the
button window, typing is ``WM_CHAR`` messages to the field window: no input
injection, no foreground activation, no desktop switch. ``fit_units``,
``judge_layout`` and ``judge_captions`` are portable and tested.

Task 026: the last message of a step's action is sent from a thread of its own (``Pending``),
so the modal window its handler opens is found among the server thread's top-level windows,
read and answered by ``WM_COMMAND`` from its button, as the warning of task 002.

Task 027: a key of a table part is ``WM_KEYDOWN``/``WM_KEYUP`` posted to its window or to the
cell's editor (``post_key``), so 1C's message loop handles it as it handles the keyboard: still a
message to a verified window, not system input. ``Posted`` stands for such an action in a chain.
"""

import ctypes as C
from ctypes import wintypes as W
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform77"))

BM_CLICK, BM_GETCHECK, WM_CHAR, WM_GETTEXT = 0x00F5, 0x00F0, 0x0102, 0x000D
# Steps (task 025): the dialog moves the focus as on Tab or a click into the field; the field's text is selected
# and replaced; VK_BACK as a character clears the selection for an empty text.
WM_NEXTDLGCTL, EM_SETSEL, VK_BACK = 0x0028, 0x00B1, 0x08
# Modal windows (task 026): a button of the window is pressed as WM_COMMAND/BN_CLICKED (task 002); the last
# message of an action waits in its own thread while the windows its handler opens are answered.
WM_COMMAND, GW_OWNER = 0x0111, 4
# Keys of a table part (task 027): lParam of WM_KEYDOWN is the repeat count 1, the scan code in bits 16–23
# and the extended-key flag in bit 24; WM_KEYUP adds the previous-state and transition bits 30 and 31.
WM_KEYDOWN, WM_KEYUP, MAPVK_VK_TO_VSC = 0x0100, 0x0101, 0
PENDING_TIMEOUT_MS = 300000
FIRST_WINDOW_ID = 4152
# The tree of groups of a catalog's list form: the last record of 26 list forms of base-for-test and
# 20 of Торговля+Склад, one per form; 1C gives its window this ID (task 023, l-button).
TREE, TREE_WINDOW_ID = "SysTreeView32", 4679
# Classes whose window text is the caption of the description (task 011); a
# field's window text is its value instead.
CAPTIONED = ("BUTTON", "STATIC", "CHECKBOX", "1CGROUPBOX")
SMTO_ABORTIFHUNG = 0x0002
TOLERANCE_PX = 2
# A field's window is one pixel wider than its record on every side (its border): width and height
# +2.0 and +1.9 px, left −0.5…−1.0 px for all 14 fields of task 011 E1 and task 022 f-elements; the
# fit takes the inner rectangle of these classes.
EDGED, EDGE_PX = ("1CEDIT", "BMASKED"), 1
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
GWL_STYLE = -16
WS_VISIBLE = 0x10000000
PW_CLIENTONLY, PW_RENDERFULLCONTENT = 1, 2
DESKTOP_ACCESS = 0x0001 | 0x0002 | 0x0040 | 0x0080  # read/create windows, enumerate, write objects


def _line(points, sizes):
    """Scale and offset of pixel = offset + scale × unit: least squares over the positions and the
    sizes together (a size is scale × units, without the offset), then the median offset.

    Positions alone gave a scale 0.6% off on a list form with two distinct x positions (task 023,
    l-tree: 1.4912 for 1.5), 2.6 px over a label 300 units wide; the sizes carry the scale as well.
    """
    count = len(points)
    sum_u, sum_p = sum(u for u, _ in points), sum(p for _, p in points)
    sum_uu = sum(u * u for u, _ in points) + sum(w * w for w, _ in sizes)
    sum_up = sum(u * p for u, p in points) + sum(w * s for w, s in sizes)
    determinant = count * sum_uu - sum_u * sum_u
    scale = ((count * sum_up - sum_u * sum_p) / determinant if determinant
             else sum(s for _, s in sizes) / max(1, sum(w for w, _ in sizes)))
    return scale, statistics.median(p - scale * u for u, p in points)


def inside(rect, client_size):
    """The whole rectangle lies in the parent's client area."""
    left, top, width, height = rect
    return left >= 0 and top >= 0 and left + width <= client_size[0] and top + height <= client_size[1]


def window_ids(description):
    """Record ID → window ID: 1C gives the window of record i of N the ID 4152 + N − 1 − i (F0).

    It creates the windows from the last record; a form of a 1Cv7.MD with a table part (task 022)
    gets it after the first ``browser.position`` windows, and its ``browser.columns`` columns take
    as many IDs (f-doc: 26 and 4, windows 4152…4177 and 4182…4196). A list form is numbered the
    same (task 023), but the tree of a catalog's groups (``SysTreeView32``) gets the window ID 4679
    and keeps its place in the order (l-button: new button 4152, tree 4679, 4153 unused).
    """
    count = len(description["controls"])
    browser = description.get("browser") or {}
    position, columns = browser.get("position", count), browser.get("columns", 0)
    return {item["id"]: TREE_WINDOW_ID if browser and item.get("class") == TREE else
            FIRST_WINDOW_ID + k + (columns if k >= position else 0)
            for item, k in ((item, count - 1 - index) for index, item in enumerate(description["controls"]))}


def edged_ids(description):
    """Window IDs of the controls whose window has the one-pixel border of a field."""
    ids = window_ids(description)
    return {ids[item["id"]] for item in description["controls"] if item.get("class") in EDGED}


def fit_units(expected, measured, tolerance=TOLERANCE_PX, edged=()):
    """One linear mapping of form numbers to pixels for all controls.

    ``expected``: {window id: (x, y, width, height)} from the description;
    ``measured``: {window id: (left, top, width, height)} in pixels of the parent's
    client area. Scale and offset are fitted from the positions; every control's
    position and size must agree with them within ``tolerance`` pixels. The windows
    in ``edged`` are fields: their rectangle without the border is compared.
    """
    measured = {i: ((r[0] + EDGE_PX, r[1] + EDGE_PX, r[2] - 2 * EDGE_PX, r[3] - 2 * EDGE_PX) if i in edged else r)
                for i, r in measured.items()}
    ids = sorted(set(expected) & set(measured))
    if not ids:
        return {"consistent": False, "reason": "no common controls", "controls": 0}
    scale_x, offset_x = _line([(expected[i][0], measured[i][0]) for i in ids],
                              [(expected[i][2], measured[i][2]) for i in ids])
    scale_y, offset_y = _line([(expected[i][1], measured[i][1]) for i in ids],
                              [(expected[i][3], measured[i][3]) for i in ids])
    residuals = {}
    for i in ids:
        x, y, w, h = expected[i]
        left, top, width, height = measured[i]
        residuals[i] = round(max(abs(left - (offset_x + scale_x * x)), abs(top - (offset_y + scale_y * y)),
                                 abs(width - scale_x * w), abs(height - scale_y * h)), 2)
    worst = max(residuals.values())
    pixels = abs(scale_x - 1) < 0.02 and abs(scale_y - 1) < 0.02
    return {"consistent": worst <= tolerance, "tolerance_px": tolerance, "controls": len(ids),
            "edged": sorted(set(edged) & set(ids)),
            "scale_x": round(scale_x, 4), "scale_y": round(scale_y, 4),
            "offset_x": round(offset_x, 2), "offset_y": round(offset_y, 2),
            "units": "pixels" if pixels else "scaled", "max_residual_px": worst,
            "residuals_px": {str(i): r for i, r in residuals.items()}}


def judge_layout(description, inspection):
    """Issues of an inspected form against its description; [] when it matches."""
    if not inspection or not inspection.get("found"):
        return ["form window not found: " + str((inspection or {}).get("reason"))]
    issues = []
    controls = {c["id"]: c for c in inspection["controls"]}
    expected = set(window_ids(description).values())
    missing = sorted(expected - set(controls))
    if missing:
        issues.append("controls missing: " + ", ".join(map(str, missing)))
    fit = inspection.get("units") or {}
    if not fit.get("consistent"):
        issues.append("positions do not follow one mapping: max residual "
                      + str(fit.get("max_residual_px", fit.get("reason"))))
    return issues


def judge_captions(description, inspection):
    """Issues where the window text of a captioned control differs from its caption."""
    if not inspection or not inspection.get("found"):
        return []
    texts = {c["id"]: c["text"] for c in inspection["controls"] if "text" in c}
    ids, issues = window_ids(description), []
    for item in description["controls"]:
        window = ids[item["id"]]
        if item.get("class") == "STATIC" and item.get("formula"):
            continue  # a label with a formula shows its value (task 022: «Р/с № …» of Доверенность, record 4189)
        if item.get("class") in CAPTIONED and window in texts and texts[window] != item["caption"]:
            issues.append(f"control {item['id']} ({item['class']}) shows {texts[window]!r}, "
                          f"described {item['caption']!r}")
    return issues


def editor(control):
    """The window that holds a field's text: its single inner window, else the control itself.

    ``1CEDIT`` is a wrapper; at open the focus and caret are in an inner window
    with ID 0, and ``WM_CHAR`` to the wrapper changes nothing (E1a, task 011).
    """
    inner = control.get("children") or []
    return inner[0] if len(inner) == 1 else control


def expected_geometry(description):
    """{window id: (x, y, width, height)} of the described controls."""
    ids = window_ids(description)
    return {ids[item["id"]]: (item["x"], item["y"], item["width"], item["height"])
            for item in description["controls"]}


class RECT(C.Structure):
    _fields_ = [("left", W.LONG), ("top", W.LONG), ("right", W.LONG), ("bottom", W.LONG)]


class GUITHREADINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND), ("hwndFocus", W.HWND),
                ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND), ("hwndMoveSize", W.HWND),
                ("hwndCaret", W.HWND), ("rcCaret", RECT)]


class LOGFONTW(C.Structure):
    _fields_ = [("lfHeight", W.LONG), ("lfWidth", W.LONG), ("lfEscapement", W.LONG), ("lfOrientation", W.LONG),
                ("lfWeight", W.LONG), ("lfItalic", W.BYTE), ("lfUnderline", W.BYTE), ("lfStrikeOut", W.BYTE),
                ("lfCharSet", W.BYTE), ("lfOutPrecision", W.BYTE), ("lfClipPrecision", W.BYTE),
                ("lfQuality", W.BYTE), ("lfPitchAndFamily", W.BYTE), ("lfFaceName", W.WCHAR * 32)]


class NONCLIENTMETRICSW(C.Structure):
    _fields_ = [("cbSize", W.UINT), ("iBorderWidth", C.c_int), ("iScrollWidth", C.c_int),
                ("iScrollHeight", C.c_int), ("iCaptionWidth", C.c_int), ("iCaptionHeight", C.c_int),
                ("lfCaptionFont", LOGFONTW), ("iSmCaptionWidth", C.c_int), ("iSmCaptionHeight", C.c_int),
                ("lfSmCaptionFont", LOGFONTW), ("iMenuWidth", C.c_int), ("iMenuHeight", C.c_int),
                ("lfMenuFont", LOGFONTW), ("lfStatusFont", LOGFONTW), ("lfMessageFont", LOGFONTW),
                ("iPaddedBorderWidth", C.c_int)]


class HIGHCONTRASTW(C.Structure):
    _fields_ = [("cbSize", W.UINT), ("dwFlags", W.DWORD), ("lpszDefaultScheme", W.LPWSTR)]


def environment(window, configuration_sha256, platform_version):  # pragma: no cover - native
    """What the image of a form depends on besides the form: compared before any pixel.

    Platform and configuration, Windows build, system and window DPI, theme,
    system fonts and smoothing, locale and the capture method. Read in the
    measuring process of the same user session.
    """
    user = C.WinDLL("user32", use_last_error=True)
    kernel32 = C.WinDLL("kernel32")
    uxtheme = C.WinDLL("uxtheme")
    user.SystemParametersInfoW.argtypes = [W.UINT, W.UINT, C.c_void_p, W.UINT]
    user.GetDpiForWindow.argtypes = [W.HWND]
    version = sys.getwindowsversion()

    def parameter(action, value, sized=True):
        if not user.SystemParametersInfoW(action, C.sizeof(value) if sized else 0, C.byref(value), 0):
            raise C.WinError(C.get_last_error())
        return value

    def font(record):
        return {"face": record.lfFaceName, "height": record.lfHeight, "weight": record.lfWeight,
                "quality": record.lfQuality}

    metrics = parameter(0x0029, NONCLIENTMETRICSW(cbSize=C.sizeof(NONCLIENTMETRICSW)))  # SPI_GETNONCLIENTMETRICS
    contrast = parameter(0x0042, HIGHCONTRASTW(cbSize=C.sizeof(HIGHCONTRASTW)))  # SPI_GETHIGHCONTRAST
    smoothing = parameter(0x004A, W.BOOL(), sized=False)  # SPI_GETFONTSMOOTHING
    smoothing_type = parameter(0x200A, W.UINT(), sized=False)  # SPI_GETFONTSMOOTHINGTYPE
    name = C.create_unicode_buffer(260)
    themed = uxtheme.GetCurrentThemeName(name, 260, None, 0, None, 0) == 0
    units = user.GetDialogBaseUnits()
    return {"platform_version": platform_version, "configuration": configuration_sha256,
            "windows_build": f"{version.major}.{version.minor}.{version.build}",
            "system_dpi": user.GetDpiForSystem(), "window_dpi": user.GetDpiForWindow(window),
            "theme": {"active": bool(uxtheme.IsThemeActive()), "app_themed": bool(uxtheme.IsAppThemed()),
                      "name": Path(name.value).name if themed else None,
                      "high_contrast": bool(contrast.dwFlags & 1)},
            "font": {"dialog_base_units": [units & 0xFFFF, (units >> 16) & 0xFFFF],
                     "smoothing": bool(smoothing.value), "smoothing_type": smoothing_type.value,
                     "caption": font(metrics.lfCaptionFont), "message": font(metrics.lfMessageFont),
                     "caption_height": metrics.iCaptionHeight, "border_width": metrics.iBorderWidth,
                     "padded_border_width": metrics.iPaddedBorderWidth},
            "locale": {"user_lcid": kernel32.GetUserDefaultLCID(), "ansi_cp": kernel32.GetACP(),
                       "oem_cp": kernel32.GetOEMCP()},
            "capture": {"method": "PrintWindow", "flags": PW_RENDERFULLCONTENT, "desktop": "private",
                        "main_window": "SW_SHOWNOACTIVATE"}}


class Pending:  # pragma: no cover - native, verified on the stand
    """One message to an owned window, sent from a thread of its own (task 026).

    1C's window procedure does not return while a modal window its handler opened is open, so the
    watcher reads and answers the windows meanwhile. ``outcome`` is {returned, last_error, elapsed_s}
    once the message returned or ``timeout_ms`` passed.
    """

    def __init__(self, form, hwnd, message, wparam=0, lparam=0, timeout_ms=PENDING_TIMEOUT_MS):
        self.message, self.outcome, self.started = message, None, time.monotonic()
        self.thread = threading.Thread(target=self._send, args=(form, hwnd, message, wparam, lparam, timeout_ms),
                                       name="harness77-action", daemon=True)
        self.thread.start()

    def _send(self, form, hwnd, message, wparam, lparam, timeout_ms):
        try:
            returned, _, error = form.send(hwnd, message, wparam, lparam, timeout_ms)
            outcome = {"returned": returned, "last_error": error}
        except (OSError, RuntimeError) as error:
            outcome = {"returned": False, "last_error": f"{type(error).__name__}: {error}"}
        self.outcome = dict(outcome, elapsed_s=round(time.monotonic() - self.started, 3))

    def done(self, wait_s=0):
        self.thread.join(wait_s)
        return not self.thread.is_alive()


class Posted:
    """An action whose messages were posted (task 027): nothing to wait for, 1C handles them in its queue.

    The call to 1C after it comes later in the same queue; a modal window the key opened serves that call
    in its own loop, as after ``#Закрыть`` (task 026).
    """

    def __init__(self, record):
        self.message, self.started = record.get("message"), time.monotonic()
        self.outcome = {"returned": bool(record.get("returned")), "last_error": record.get("last_error"),
                        "posted": True, "elapsed_s": 0.0}

    def done(self, wait_s=0):
        return True


def key_parameters(vk, extended, scan):
    """(lParam of WM_KEYDOWN, lParam of WM_KEYUP) of one key press."""
    down = 1 | (scan & 0xFF) << 16 | (1 << 24 if extended else 0)
    return down, down | 1 << 30 | 1 << 31


class OwnedForm:  # pragma: no cover - native, verified on the stand
    """Read-only inventory of the owned windows plus one verified button click."""

    LIMIT = 4096

    def __init__(self, handle, server, tid, desktop, run_id):
        from win32_modal77 import OwnedModal
        self.modal = OwnedModal(handle, server, tid, desktop, run_id)
        user = self.user = self.modal.user
        user.SendMessageTimeoutA.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT,
                                             C.POINTER(C.c_size_t)]
        user.SendMessageTimeoutA.restype = W.LPARAM
        user.IsWindowUnicode.argtypes = [W.HWND]
        user.GetParent.argtypes = [W.HWND]
        user.GetParent.restype = W.HWND
        user.GetWindowRect.argtypes = [W.HWND, C.POINTER(RECT)]
        user.GetClientRect.argtypes = [W.HWND, C.POINTER(RECT)]
        user.MapWindowPoints.argtypes = [W.HWND, W.HWND, C.POINTER(RECT), W.UINT]
        self.dpi_for_window = getattr(user, "GetDpiForWindow", None)
        if self.dpi_for_window:
            self.dpi_for_window.argtypes = [W.HWND]
            self.dpi_for_window.restype = W.UINT

    def descendants(self, top):
        handles = []

        @self.modal.callback_type
        def visit(hwnd, unused):
            handles.append(hwnd)
            return len(handles) <= self.LIMIT
        self.user.EnumChildWindows(top, visit, 0)
        if len(handles) > self.LIMIT:
            raise RuntimeError("owned window enumeration limit")
        return handles

    def rect_in_parent(self, hwnd, parent):
        rect = RECT()
        if not self.user.GetWindowRect(hwnd, C.byref(rect)):
            raise C.WinError(C.get_last_error())
        C.set_last_error(0)
        self.user.MapWindowPoints(None, parent, C.byref(rect), 2)
        return [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]

    def client_size(self, hwnd):
        rect = RECT()
        if not self.user.GetClientRect(hwnd, C.byref(rect)):
            raise C.WinError(C.get_last_error())
        return [rect.right - rect.left, rect.bottom - rect.top]

    def dpi(self, hwnd):
        return self.dpi_for_window(hwnd) if self.dpi_for_window else None

    def state(self, hwnd):
        """Own WS_VISIBLE bit and IsWindowVisible (false while any ancestor is hidden)."""
        self.user.GetWindowLongW.argtypes = [W.HWND, C.c_int]
        style = self.user.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
        return {"hwnd": hwnd, "style": style, "ws_visible": bool(style & WS_VISIBLE),
                "visible": bool(self.user.IsWindowVisible(hwnd))}

    def show(self, hwnd, command, budget_s=5.0):
        """``ShowWindowAsync`` to an owned top-level window, then wait for the visibility to follow.

        Only the run's own server thread on its own private desktop is touched;
        no activation (``SW_SHOWNOACTIVATE`` / ``SW_HIDE``) and no desktop switch.
        """
        self.modal.verify()
        if self.modal.owner(hwnd) != (self.modal.server["pid"], self.modal.tid):
            raise RuntimeError("window is not on the verified server thread")
        self.user.ShowWindowAsync.argtypes = [W.HWND, C.c_int]
        before = self.state(hwnd)
        started = time.monotonic()
        if not self.user.ShowWindowAsync(hwnd, command):
            raise C.WinError(C.get_last_error())
        wanted = command != SW_HIDE
        while self.state(hwnd)["visible"] != wanted and time.monotonic() - started < budget_s:
            time.sleep(0.05)
        after = self.state(hwnd)
        return {"command": command, "before": before, "after": after, "reached": after["visible"] == wanted,
                "elapsed_s": round(time.monotonic() - started, 3), "identity_rechecked": True}

    def caret(self, target):
        """The server thread's caret as a rectangle of ``target``'s window image, or None.

        The system caret blinks, so captures differ in its rectangle (V0); the
        rectangle comes from ``GetGUIThreadInfo`` and is masked, nothing else.
        """
        self.user.GetGUIThreadInfo.argtypes = [W.DWORD, C.POINTER(GUITHREADINFO)]

        def read():
            info = GUITHREADINFO(cbSize=C.sizeof(GUITHREADINFO))
            if not self.user.GetGUIThreadInfo(self.modal.tid, C.byref(info)):
                raise C.WinError(C.get_last_error())
            return info
        info = on_desktop(self.modal.desktop, read)
        focus = None
        if info.hwndFocus:
            focus = {"id": self.user.GetDlgCtrlID(info.hwndFocus)}
        if not info.hwndCaret or info.rcCaret.right <= info.rcCaret.left:
            return None, focus
        rect = RECT(info.rcCaret.left, info.rcCaret.top, info.rcCaret.right, info.rcCaret.bottom)
        self.user.MapWindowPoints(info.hwndCaret, None, C.byref(rect), 2)
        origin = RECT()
        if not self.user.GetWindowRect(target, C.byref(origin)):
            raise C.WinError(C.get_last_error())
        caret = {"x": rect.left - origin.left, "y": rect.top - origin.top,
                 "width": rect.right - rect.left, "height": rect.bottom - rect.top}
        size = (origin.right - origin.left, origin.bottom - origin.top)
        if caret["x"] + caret["width"] <= 0 or caret["y"] + caret["height"] <= 0 \
                or caret["x"] >= size[0] or caret["y"] >= size[1]:
            return None, focus  # the caret is outside this window
        return caret, focus

    def inventory(self, budget_s=10.0):
        """All owned top-level windows with their descendants: class, text, ID, parent."""
        self.modal.verify()
        until = time.monotonic() + budget_s
        windows = []
        for top in self.modal.enumerate():
            if self.modal.owner(top) != (self.modal.server["pid"], self.modal.tid):
                continue
            item = self.modal.info(top, until)
            item.update(parent=None, top=top, desktop=self.modal.desktop)
            windows.append(item)
            for child in self.descendants(top):
                if self.modal.owner(child) != (self.modal.server["pid"], self.modal.tid):
                    continue  # a window of another thread is never read or messaged
                info = self.modal.info(child, until)
                info.update(parent=self.user.GetParent(child) or None, top=top)
                windows.append(info)
        return windows

    def inspect(self, expected_ids, budget_s=10.0):
        """The form: the parent whose children carry every expected control ID."""
        windows = self.inventory(budget_s)
        children = {}
        for window in windows:
            if window["parent"]:
                children.setdefault(window["parent"], []).append(window)
        candidates = [parent for parent, items in children.items()
                      if set(expected_ids) <= {w["id"] for w in items}]
        summary = {"owned_windows": len(windows),
                   "top_level": [{k: w[k] for k in ("hwnd", "class", "text", "visible", "enabled")}
                                 for w in windows if w["parent"] is None]}
        by_handle = {w["hwnd"]: w for w in windows}
        if len(candidates) != 1:
            # The child IDs of the windows with most children tell how 1C numbered a form (task 022).
            parents = sorted(children.items(), key=lambda pair: -len(pair[1]))[:10]
            return dict(summary, found=False, expected_ids=sorted(expected_ids),
                        parents=[{"hwnd": parent, "class": by_handle.get(parent, {}).get("class"),
                                  "text": by_handle.get(parent, {}).get("text"),
                                  "ids": sorted(w["id"] for w in items),
                                  "classes": sorted({w["class"] for w in items})} for parent, items in parents],
                        reason="no window holds every expected control ID" if not candidates
                        else f"{len(candidates)} windows hold the expected control IDs")
        parent = candidates[0]
        chain, cursor = [], parent
        while cursor:
            window = by_handle.get(cursor)
            if window is None:
                break
            chain.append({k: window[k] for k in ("hwnd", "class", "text", "visible", "enabled")}
                         | {"dpi": self.dpi(cursor), "client_size": self.client_size(cursor)})
            cursor = window["parent"]
        controls = []
        for window in children[parent]:
            rect = self.rect_in_parent(window["hwnd"], parent)
            # A 1CEDIT field is a wrapper: its text lives in one inner window (E1a, task 011).
            inner = [{k: w[k] for k in ("hwnd", "class", "id", "text")} for w in children.get(window["hwnd"], [])]
            controls.append({"id": window["id"], "hwnd": window["hwnd"], "class": window["class"],
                             "text": window["text"], "visible": window["visible"], "enabled": window["enabled"],
                             "rect": rect, "inside_client": inside(rect, chain[0]["client_size"]),
                             "children": inner})
        return dict(summary, found=True, parent=chain[0], chain=chain, controls=controls)

    def send(self, hwnd, message, wparam=0, lparam=0, timeout_ms=10000, ansi=False):
        """``SendMessageTimeoutW`` (``A`` with ``ansi``) to an owned window after rechecking the server identity."""
        self.modal.verify()
        if self.modal.owner(hwnd) != (self.modal.server["pid"], self.modal.tid):
            raise RuntimeError("window is not on the verified server thread")
        result = C.c_size_t()
        C.set_last_error(0)
        function = self.user.SendMessageTimeoutA if ansi else self.user.SendMessageTimeoutW
        returned = function(hwnd, message, wparam, lparam, SMTO_ABORTIFHUNG, timeout_ms, C.byref(result))
        return bool(returned), result.value, C.get_last_error() if not returned else 0

    def text(self, hwnd):
        """Current window text (``WM_GETTEXT``): a field's value, a label's caption."""
        buffer = C.create_unicode_buffer(2048)
        returned, _, error = self.send(hwnd, WM_GETTEXT, len(buffer), C.addressof(buffer), 1000)
        if not returned:
            raise RuntimeError(f"WM_GETTEXT did not return, last error {error}")
        return buffer.value

    def checked(self, hwnd):
        """``BM_GETCHECK`` of a check box: 0 cleared, 1 checked, 2 indeterminate."""
        returned, value, error = self.send(hwnd, BM_GETCHECK, timeout_ms=1000)
        if not returned:
            raise RuntimeError(f"BM_GETCHECK did not return, last error {error}")
        return value

    def click(self, inspection, control_id, timeout_ms=10000):
        """BM_CLICK to the button with ``control_id``, after rechecking the server identity."""
        button = next((c for c in inspection.get("controls", []) if c["id"] == control_id), None)
        if button is None:
            return {"control_id": control_id, "found": False, "requested": False}
        started = time.monotonic()
        returned, _, error = self.send(button["hwnd"], BM_CLICK, timeout_ms=timeout_ms)
        return {"control_id": control_id, "found": True, "requested": True, "message": "BM_CLICK",
                "returned": returned, "last_error": error,
                "elapsed_s": round(time.monotonic() - started, 3), "identity_rechecked": True,
                "button": {k: button[k] for k in ("hwnd", "class", "text", "visible", "enabled", "rect",
                                                  "inside_client")}}

    def type_text(self, inspection, control_id, text, timeout_ms=10000):
        """``WM_CHAR`` per character to the field with ``control_id``, then its text read back.

        Messages to the window, not keyboard input: no accelerators, no focus
        change. The text before and after shows what the field accepted (task 011).
        """
        field = next((c for c in inspection.get("controls", []) if c["id"] == control_id), None)
        if field is None:
            return {"control_id": control_id, "found": False, "requested": False}
        target = editor(field)
        started = time.monotonic()
        before, sent, error = self.text(target["hwnd"]), 0, 0
        # A Unicode WM_CHAR to an ANSI window is converted by the input language of 1C's thread,
        # which follows the user's current layout: Cyrillic became "????" under the English one
        # (task 022, f-elements). The window of a 7.7 field gets the Windows-1251 byte instead.
        ansi = not self.user.IsWindowUnicode(target["hwnd"])
        for character in text:
            code = character.encode("cp1251")[0] if ansi else ord(character)
            returned, _, error = self.send(target["hwnd"], WM_CHAR, code, 1, timeout_ms, ansi=ansi)
            if not returned:
                break
            sent += 1
        return {"control_id": control_id, "found": True, "requested": True, "message": "WM_CHAR",
                "encoding": "cp1251" if ansi else "utf-16",
                "returned": sent == len(text), "characters_sent": sent, "last_error": error, "text": text,
                "text_before": before, "text_after": self.text(target["hwnd"]),
                "target": {k: target.get(k) for k in ("hwnd", "class", "id")},
                "elapsed_s": round(time.monotonic() - started, 3), "identity_rechecked": True,
                "field": {k: field[k] for k in ("hwnd", "class", "visible", "enabled", "rect", "inside_client")}}

    def focused(self):
        """The window with the server thread's keyboard focus: hwnd, ID and its parent's ID, or None."""
        self.user.GetGUIThreadInfo.argtypes = [W.DWORD, C.POINTER(GUITHREADINFO)]

        def read():
            info = GUITHREADINFO(cbSize=C.sizeof(GUITHREADINFO))
            if not self.user.GetGUIThreadInfo(self.modal.tid, C.byref(info)):
                raise C.WinError(C.get_last_error())
            return info.hwndFocus
        hwnd = on_desktop(self.modal.desktop, read)
        if not hwnd:
            return None
        parent = self.user.GetParent(hwnd)
        return {"hwnd": hwnd, "id": self.user.GetDlgCtrlID(hwnd), "parent_id": self.user.GetDlgCtrlID(parent)
                if parent else None}

    def click_pending(self, inspection, control_id):
        """``BM_CLICK`` to a button from a thread of its own (task 026): (record, Pending), or (record, None).

        The handler may open a modal window; the message returns when the handler does. The record is
        completed when the message returned (``returned``, ``last_error``).
        """
        button = next((c for c in inspection.get("controls", []) if c["id"] == control_id), None)
        if button is None:
            return {"control_id": control_id, "found": False, "requested": False, "returned": False}, None
        record = {"control_id": control_id, "found": True, "requested": True, "message": "BM_CLICK",
                  "identity_rechecked": True,
                  "button": {k: button[k] for k in ("hwnd", "class", "text", "visible", "enabled", "rect",
                                                    "inside_client")}}
        return record, Pending(self, button["hwnd"], BM_CLICK)

    def enter_text(self, inspection, control_id, text, leave_to, timeout_ms=10000):
        """Go to the field, replace its text and leave it, as the user does with the keyboard (task 025).

        ``WM_NEXTDLGCTL`` to the dialog gives the field's editor the focus in 1C's own thread, ``EM_SETSEL``
        selects its text, ``WM_CHAR`` per character replaces it (``VK_BACK`` clears it for an empty text),
        and ``WM_NEXTDLGCTL`` to ``leave_to`` (the next element that takes the focus) leaves the field, so 1C
        takes the value. ``WM_NEXTDLGCTL(0, 0)`` kept the focus in the editor, a grandchild of the dialog, and
        the attribute stayed empty (s-input, series 0); ``GetNextDlgTabItem`` returned the field itself
        (series 0b): the caller names the next control from the form's description.

        The leave runs the field's formula, which may open a modal window (task 026): it is returned as a
        Pending with the record, (record, Pending), and ``left`` completes the record when it returned;
        (record, None) when the text did not get that far.
        """
        field = next((c for c in inspection.get("controls", []) if c["id"] == control_id), None)
        if field is None:
            return {"control_id": control_id, "found": False, "requested": False, "returned": False}, None
        target, dialog = editor(field), inspection["chain"][0]["hwnd"]
        record = {"control_id": control_id, "found": True, "requested": True, "message": "WM_CHAR",
                  "target": {k: target.get(k) for k in ("hwnd", "class", "id")}, "field": {"hwnd": field["hwnd"]},
                  "text": text}
        started = time.monotonic()
        record["text_before"] = self.text(target["hwnd"])
        stages = [("focus", dialog, WM_NEXTDLGCTL, target["hwnd"], 1, False),
                  ("select", target["hwnd"], EM_SETSEL, 0, -1, False)]
        ansi = not self.user.IsWindowUnicode(target["hwnd"])
        record["encoding"] = "cp1251" if ansi else "utf-16"
        characters = [character.encode("cp1251")[0] if ansi else ord(character) for character in text] or [VK_BACK]
        stages += [("type", target["hwnd"], WM_CHAR, code, 1, ansi) for code in characters]
        sent, pending = [], None
        for name, hwnd, message, wparam, lparam, as_ansi in stages:
            returned, _, error = self.send(hwnd, message, wparam, lparam, timeout_ms, ansi=as_ansi)
            if not returned:
                record.update(returned=False, failed_stage=name, last_error=error)
                break
            if name == "focus":
                record["focus"] = self.focused()
            sent.append(name)
        else:
            record["text_typed"] = self.text(target["hwnd"])
            record["next_control"] = {k: leave_to[k] for k in ("hwnd", "id", "class")} if leave_to else None
            if not leave_to:
                record.update(returned=False, failed_stage="leave", reason="no other element takes the focus")
            else:
                pending = Pending(self, dialog, WM_NEXTDLGCTL, leave_to["hwnd"], 1)
        record.update(characters_sent=sent.count("type"), elapsed_s=round(time.monotonic() - started, 3),
                      identity_rechecked=True)
        return record, pending

    def left(self, record, outcome):
        """Complete an input's record when its leave returned (or did not): the focus left the field."""
        returned = bool(outcome.get("returned"))
        focus = self.focused() if returned else None
        left = returned and (focus is None or focus["hwnd"] not in (record["target"]["hwnd"], record["field"]["hwnd"]))
        record.update(returned=left, last_error=outcome.get("last_error"), focus_after=focus)
        if not left:
            record.update(failed_stage="leave",
                          reason="the field kept the focus" if returned else "the message did not return")

    def style(self, hwnd):
        self.user.GetWindowLongW.argtypes = [W.HWND, C.c_int]
        return self.user.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF

    def top_windows(self):
        """The top-level windows of the server thread now: none of them is the modal window of a later action."""
        self.modal.verify()
        mine = (self.modal.server["pid"], self.modal.tid)
        return {hwnd for hwnd in self.modal.enumerate() if self.modal.owner(hwnd) == mine}

    def modal_window(self, seen):
        """A visible top-level window of the server thread not in ``seen`` that disabled its owner, or a new
        dialog box (``#32770``): its record (``window_record``), or None (task 026)."""
        self.modal.verify()
        mine = (self.modal.server["pid"], self.modal.tid)
        name = C.create_unicode_buffer(256)
        for hwnd in self.modal.enumerate():
            if hwnd in seen or self.modal.owner(hwnd) != mine or not self.user.IsWindowVisible(hwnd):
                continue
            owner = self.user.GetWindow(hwnd, GW_OWNER)
            self.user.GetClassNameW(hwnd, name, len(name))
            if (owner and not self.user.IsWindowEnabled(owner)) or name.value == "#32770":
                return self.window_record(hwnd)
        return None

    def window_record(self, hwnd):
        """A modal window: class, title, owner, style and every descendant with its parent, ID, text and style."""
        until = time.monotonic() + 2
        record = self.modal.info(hwnd, until)
        owner = self.user.GetWindow(hwnd, GW_OWNER)
        record.update(owner=owner or None, owner_enabled=bool(self.user.IsWindowEnabled(owner)) if owner else None,
                      style=self.style(hwnd))
        record["children"] = [dict(self.modal.info(child, until), parent=self.user.GetParent(child) or None,
                                   style=self.style(child)) for child in self.descendants(hwnd)]
        return record

    def await_action(self, pending, seen, budget_s, poll_s=0.05):
        """Until the pending message returns or a modal window opens (task 026).

        {returned, last_error, elapsed_s, waited_s} when it returned, {window, waited_s} when a window not in
        ``seen`` opened first, {timeout, waited_s} after ``budget_s`` without either. The time a window was
        open before is not in the budget: the wait starts again after every answer.
        """
        started = time.monotonic()
        while not pending.done(poll_s):
            window = self.modal_window(seen)
            if window is not None:
                return {"window": window, "waited_s": round(time.monotonic() - started, 3)}
            if time.monotonic() - started > budget_s:
                return {"timeout": True, "waited_s": round(time.monotonic() - started, 3)}
        return dict(pending.outcome, waited_s=round(time.monotonic() - started, 3))

    def answer(self, window, button, field=None, text=None, timeout_ms=10000):
        """Answer a modal window: ``text`` into its field, then ``button`` pressed (task 026).

        The text goes as into a form's field (task 025): the focus to the field's editor, its text selected
        and replaced, then the focus to the button. The button is pressed as the warning of task 002 was
        closed: ``WM_COMMAND``/``BN_CLICKED`` from it, posted to the window, once the window and the button
        are found again on the verified server thread.
        """
        dialog = window["hwnd"]
        record = {"button": {k: button.get(k) for k in ("hwnd", "id", "text")}, "requested": False}
        if field is not None:
            inner = [c for c in window["children"] if c.get("parent") == field["hwnd"]]
            target = inner[0] if len(inner) == 1 else field
            ansi = not self.user.IsWindowUnicode(target["hwnd"])
            record.update(field={k: target.get(k) for k in ("hwnd", "class", "id")}, text=text,
                          encoding="cp1251" if ansi else "utf-16", text_before=self.text(target["hwnd"]))
            codes = [character.encode("cp1251")[0] if ansi else ord(character) for character in text] or [VK_BACK]
            stages = ([("focus", dialog, WM_NEXTDLGCTL, target["hwnd"], 1, False),
                       ("select", target["hwnd"], EM_SETSEL, 0, -1, False)]
                      + [("type", target["hwnd"], WM_CHAR, code, 1, ansi) for code in codes]
                      + [("leave", dialog, WM_NEXTDLGCTL, button["hwnd"], 1, False)])
            for name, hwnd, message, wparam, lparam, as_ansi in stages:
                returned, _, error = self.send(hwnd, message, wparam, lparam, timeout_ms, ansi=as_ansi)
                if not returned:
                    record.update(error=f"{name} did not return", last_error=error)
                    return record
            record["text_after"] = self.text(target["hwnd"])
        current = self.window_record(dialog)
        found = next((c for c in current["children"] if c["hwnd"] == button["hwnd"] and c["id"] == button["id"]), None)
        if found is None or not found["enabled"] or not found["visible"]:
            record["error"] = "the button is gone, disabled or hidden"
            return record
        self.modal.verify()
        if not self.user.PostMessageW(dialog, WM_COMMAND, button["id"] & 0xFFFF, button["hwnd"]):
            raise C.WinError(C.get_last_error())
        record.update(requested=True, message="WM_COMMAND/BN_CLICKED", identity_rechecked=True)
        return record

    def post(self, hwnd, message, wparam=0, lparam=0):
        """``PostMessageW`` to an owned window after rechecking the server identity (task 027)."""
        self.modal.verify()
        if self.modal.owner(hwnd) != (self.modal.server["pid"], self.modal.tid):
            raise RuntimeError("window is not on the verified server thread")
        self.user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        C.set_last_error(0)
        posted = bool(self.user.PostMessageW(hwnd, message, wparam, lparam))
        return posted, 0 if posted else C.get_last_error()

    def post_key(self, hwnd, name, vk, extended):
        """One key pressed in a window of 1C: ``WM_KEYDOWN`` and ``WM_KEYUP`` posted to it (task 027).

        1C's message loop translates and dispatches them as keyboard input of its thread; the system's input
        state, the foreground and the desktop are not touched.
        """
        self.user.MapVirtualKeyW.argtypes = [W.UINT, W.UINT]
        down, up = key_parameters(vk, extended, self.user.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC))
        record = {"key": name, "vk": vk, "hwnd": hwnd, "id": self.user.GetDlgCtrlID(hwnd), "message": "WM_KEYDOWN/WM_KEYUP",
                  "posted": True, "identity_rechecked": True}
        for stage, message, lparam in (("down", WM_KEYDOWN, down), ("up", WM_KEYUP, up)):
            posted, error = self.post(hwnd, message, vk, lparam)
            if not posted:
                return dict(record, returned=False, failed_stage=stage, last_error=error)
        return dict(record, returned=True, last_error=0)

    def give_focus(self, dialog, hwnd, timeout_ms=10000):
        """``WM_NEXTDLGCTL`` to the dialog: the focus to ``hwnd`` in 1C's own thread, as for a field (task 025)."""
        returned, _, error = self.send(dialog, WM_NEXTDLGCTL, hwnd, 1, timeout_ms)
        if not returned:
            raise RuntimeError(f"WM_NEXTDLGCTL did not return, last error {error}")
        return self.focused()

    def within(self, hwnd, ancestor):
        """``hwnd`` is ``ancestor`` or one of its descendants."""
        cursor, steps = hwnd, 0
        while cursor and steps < 32:
            if cursor == ancestor:
                return True
            cursor, steps = self.user.GetParent(cursor), steps + 1
        return False

    def editor_of(self, focus, table):
        """The cell editor that holds ``focus``: the child window of the table part above it, or None."""
        if not focus or focus["hwnd"] == table or not self.within(focus["hwnd"], table):
            return None
        cursor = focus["hwnd"]
        while self.user.GetParent(cursor) != table:
            cursor = self.user.GetParent(cursor)
        until = time.monotonic() + 2
        info = self.modal.info(cursor, until)
        return {k: info.get(k) for k in ("hwnd", "class", "id", "text", "visible", "enabled")}

    def table_windows(self, table):
        """The table part's window, its descendants (cell editors) and the focus, for the evidence (task 027)."""
        until = time.monotonic() + 2
        children = [dict({k: info.get(k) for k in ("hwnd", "class", "id", "text", "visible", "enabled")},
                         parent=self.user.GetParent(child) or None)
                    for child, info in ((child, self.modal.info(child, until)) for child in self.descendants(table))]
        return {"table": table, "children": children, "focus": self.focused()}

    def replace_text(self, hwnd, text, timeout_ms=10000):
        """Select the text of the window with the focus and replace it, as in a form's field (task 025)."""
        record = {"hwnd": hwnd, "id": self.user.GetDlgCtrlID(hwnd), "text": text, "text_before": self.text(hwnd)}
        ansi = not self.user.IsWindowUnicode(hwnd)
        record["encoding"] = "cp1251" if ansi else "utf-16"
        codes = [character.encode("cp1251")[0] if ansi else ord(character) for character in text] or [VK_BACK]
        for name, message, wparam, lparam, as_ansi in ([("select", EM_SETSEL, 0, -1, False)]
                                                        + [("type", WM_CHAR, code, 1, ansi) for code in codes]):
            returned, _, error = self.send(hwnd, message, wparam, lparam, timeout_ms, ansi=as_ansi)
            if not returned:
                return dict(record, typed=False, failed_stage=name, last_error=error)
        return dict(record, typed=True, text_after=self.text(hwnd))

    def alive(self, hwnd):
        """The window still exists on the verified server thread (the form was not closed)."""
        self.modal.verify()
        self.user.IsWindow.argtypes = [W.HWND]
        return bool(self.user.IsWindow(hwnd)) and self.modal.owner(hwnd) == (self.modal.server["pid"], self.modal.tid)

    def element_state(self, control, checkbox=False):
        """What a control's window shows now: text (a field's editor), enabled, own WS_VISIBLE, check state."""
        hwnd = control["hwnd"]
        if not self.alive(hwnd):
            return {"error": "the element's window no longer exists"}
        self.user.IsWindowEnabled.argtypes = [W.HWND]
        state = {"text": self.text(editor(control)["hwnd"]), "enabled": bool(self.user.IsWindowEnabled(hwnd)),
                 "visible": self.state(hwnd)["ws_visible"]}
        if checkbox:
            value = self.checked(hwnd)
            state["checked"] = {0: False, 1: True}.get(value, value)
        return state


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


def _print_window(hwnd, flags):  # pragma: no cover - native GDI
    """PrintWindow into a 32-bit top-down DIB section; returns an RGB image."""
    from harness77.visual77 import Image
    user = C.WinDLL("user32", use_last_error=True)
    gdi = C.WinDLL("gdi32", use_last_error=True)
    user.GetWindowRect.argtypes = user.GetClientRect.argtypes = [W.HWND, C.POINTER(RECT)]
    user.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
    gdi.CreateCompatibleDC.argtypes = [W.HDC]
    gdi.CreateCompatibleDC.restype = W.HDC
    gdi.CreateDIBSection.argtypes = [W.HDC, C.POINTER(BITMAPINFOHEADER), W.UINT, C.POINTER(C.c_void_p),
                                     W.HANDLE, W.DWORD]
    gdi.CreateDIBSection.restype = W.HBITMAP
    gdi.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
    gdi.SelectObject.restype = W.HGDIOBJ
    gdi.DeleteObject.argtypes = [W.HGDIOBJ]
    gdi.DeleteDC.argtypes = [W.HDC]
    rect = RECT()
    measure = user.GetClientRect if flags & PW_CLIENTONLY else user.GetWindowRect
    if not measure(hwnd, C.byref(rect)):
        raise C.WinError(C.get_last_error())
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"window has no area: {width}x{height}")
    header = BITMAPINFOHEADER(biSize=C.sizeof(BITMAPINFOHEADER), biWidth=width, biHeight=-height,
                              biPlanes=1, biBitCount=32)
    memory = gdi.CreateCompatibleDC(None)
    if not memory:
        raise RuntimeError("CreateCompatibleDC failed")
    bits = C.c_void_p()
    bitmap = gdi.CreateDIBSection(memory, C.byref(header), 0, C.byref(bits), None, 0)
    try:
        if not bitmap or not bits.value:
            raise RuntimeError("CreateDIBSection failed")
        previous = gdi.SelectObject(memory, bitmap)
        C.set_last_error(0)
        printed = user.PrintWindow(hwnd, memory, flags)
        error = C.get_last_error()
        gdi.GdiFlush()
        data = C.string_at(bits.value, width * height * 4)
        gdi.SelectObject(memory, previous)
    finally:
        if bitmap:
            gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
    if not printed:
        raise RuntimeError(f"PrintWindow failed, last error {error}")
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = data[2::4], data[1::4], data[0::4]
    return Image(width, height, bytes(rgb))


def capture(hwnd, flags=0, desktop=None, timeout_s=10.0):  # pragma: no cover - native
    """One window to an RGB image by ``PrintWindow``, in this thread or on ``desktop``."""
    if desktop is None:
        return _print_window(hwnd, flags)
    return on_desktop(desktop, lambda: _print_window(hwnd, flags), timeout_s)


def on_desktop(desktop, work, timeout_s=10.0):  # pragma: no cover - native
    """``work()`` in a fresh thread attached to ``desktop``; its value or its exception.

    ``SetThreadDesktop`` changes only that thread (a thread without windows may
    switch); the input desktop is never switched. Some calls need it:
    ``GetGUIThreadInfo`` for a thread of another desktop is denied (V1).
    """
    outcome = {}

    def run():
        user = C.WinDLL("user32", use_last_error=True)
        kernel32 = C.WinDLL("kernel32")
        user.OpenDesktopW.argtypes = [W.LPCWSTR, W.DWORD, W.BOOL, W.DWORD]
        user.OpenDesktopW.restype = W.HANDLE
        user.GetThreadDesktop.argtypes = [W.DWORD]
        user.GetThreadDesktop.restype = W.HANDLE
        user.SetThreadDesktop.argtypes = [W.HANDLE]
        user.CloseDesktop.argtypes = [W.HANDLE]
        original = user.GetThreadDesktop(kernel32.GetCurrentThreadId())
        handle = user.OpenDesktopW(desktop, 0, False, DESKTOP_ACCESS)
        if not handle:
            outcome["error"] = C.WinError(C.get_last_error())
            return
        try:
            if not user.SetThreadDesktop(handle):
                outcome["error"] = C.WinError(C.get_last_error())
                return
            try:
                outcome["value"] = work()
            except (OSError, RuntimeError, ValueError) as error:
                outcome["error"] = error
            finally:
                user.SetThreadDesktop(original)
        finally:
            user.CloseDesktop(handle)
    worker = threading.Thread(target=run, name="harness77-desktop", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise RuntimeError("desktop thread did not finish in time")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def awareness():  # pragma: no cover - native
    """DPI awareness of this (measuring) thread and the system DPI, for the evidence."""
    user = C.WinDLL("user32")
    record = {}
    try:
        user.GetThreadDpiAwarenessContext.restype = C.c_void_p
        user.GetAwarenessFromDpiAwarenessContext.argtypes = [C.c_void_p]
        record["thread_awareness"] = user.GetAwarenessFromDpiAwarenessContext(
            user.GetThreadDpiAwarenessContext())
        record["system_dpi"] = user.GetDpiForSystem()
    except AttributeError:
        record["thread_awareness"] = None
    return record
