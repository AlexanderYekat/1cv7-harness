"""The open ERT form among the owned windows, its geometry, clicks and typing (tasks 008, 011).

Only windows of the verified server thread on the run's own private desktop are
read; the identity of the process is rechecked immediately before every message
(the ``OwnedModal`` rules of stage 2). A click is a ``BM_CLICK`` message to the
button window, typing is ``WM_CHAR`` messages to the field window: no input
injection, no foreground activation, no desktop switch. ``fit_units``,
``judge_layout`` and ``judge_captions`` are portable and tested.
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
FIRST_WINDOW_ID = 4152
# Classes whose window text is the caption of the description (task 011); a
# field's window text is its value instead.
CAPTIONED = ("BUTTON", "STATIC", "CHECKBOX", "1CGROUPBOX")
SMTO_ABORTIFHUNG = 0x0002
TOLERANCE_PX = 2
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
GWL_STYLE = -16
WS_VISIBLE = 0x10000000
PW_CLIENTONLY, PW_RENDERFULLCONTENT = 1, 2
DESKTOP_ACCESS = 0x0001 | 0x0002 | 0x0040 | 0x0080  # read/create windows, enumerate, write objects


def _line(points, sizes):
    """Scale and offset of pixel = offset + scale × unit: least squares over positions,
    or the size ratio when every control shares one position."""
    units = [u for u, _ in points]
    if len(set(units)) > 1:
        mean_u, mean_p = statistics.fmean(units), statistics.fmean(p for _, p in points)
        scale = (sum((u - mean_u) * (p - mean_p) for u, p in points)
                 / sum((u - mean_u) ** 2 for u in units))
    else:
        scale = sum(p for _, p in sizes) / max(1, sum(u for u, _ in sizes))
    return scale, statistics.median(p - scale * u for u, p in points)


def inside(rect, client_size):
    """The whole rectangle lies in the parent's client area."""
    left, top, width, height = rect
    return left >= 0 and top >= 0 and left + width <= client_size[0] and top + height <= client_size[1]


def window_ids(description):
    """Record ID → window ID: 1C gives the window of record i of N the ID 4152 + N − 1 − i (F0)."""
    count = len(description["controls"])
    return {item["id"]: FIRST_WINDOW_ID + count - 1 - index for index, item in enumerate(description["controls"])}


def fit_units(expected, measured, tolerance=TOLERANCE_PX):
    """One linear mapping of form numbers to pixels for all controls.

    ``expected``: {window id: (x, y, width, height)} from the description;
    ``measured``: {window id: (left, top, width, height)} in pixels of the parent's
    client area. Scale and offset are fitted from the positions; every control's
    position and size must agree with them within ``tolerance`` pixels.
    """
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


class OwnedForm:  # pragma: no cover - native, verified on the stand
    """Read-only inventory of the owned windows plus one verified button click."""

    LIMIT = 4096

    def __init__(self, handle, server, tid, desktop, run_id):
        from win32_modal77 import OwnedModal
        self.modal = OwnedModal(handle, server, tid, desktop, run_id)
        user = self.user = self.modal.user
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
        if len(candidates) != 1:
            return dict(summary, found=False,
                        reason="no window holds every expected control ID" if not candidates
                        else f"{len(candidates)} windows hold the expected control IDs")
        parent = candidates[0]
        chain, cursor = [], parent
        by_handle = {w["hwnd"]: w for w in windows}
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

    def send(self, hwnd, message, wparam=0, lparam=0, timeout_ms=10000):
        """``SendMessageTimeoutW`` to an owned window after rechecking the server identity."""
        self.modal.verify()
        if self.modal.owner(hwnd) != (self.modal.server["pid"], self.modal.tid):
            raise RuntimeError("window is not on the verified server thread")
        result = C.c_size_t()
        C.set_last_error(0)
        returned = self.user.SendMessageTimeoutW(hwnd, message, wparam, lparam, SMTO_ABORTIFHUNG,
                                                 timeout_ms, C.byref(result))
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
        for character in text:
            returned, _, error = self.send(target["hwnd"], WM_CHAR, ord(character), 1, timeout_ms)
            if not returned:
                break
            sent += 1
        return {"control_id": control_id, "found": True, "requested": True, "message": "WM_CHAR",
                "returned": sent == len(text), "characters_sent": sent, "last_error": error, "text": text,
                "text_before": before, "text_after": self.text(target["hwnd"]),
                "target": {k: target.get(k) for k in ("hwnd", "class", "id")},
                "elapsed_s": round(time.monotonic() - started, 3), "identity_rechecked": True,
                "field": {k: field[k] for k in ("hwnd", "class", "visible", "enabled", "rect", "inside_client")}}


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
