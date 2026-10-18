"""The open ERT form among the owned windows, its geometry and one button click (task 008).

Only windows of the verified server thread on the run's own private desktop are
read; the identity of the process is rechecked immediately before the click
(the ``OwnedModal`` rules of stage 2). The click is a ``BM_CLICK`` message to
the button window: no input injection, no foreground activation, no desktop
switch. ``fit_units`` and ``judge_layout`` are portable and tested.
"""

import ctypes as C
from ctypes import wintypes as W
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform77"))

BM_CLICK = 0x00F5
FIRST_WINDOW_ID = 4152
SMTO_ABORTIFHUNG = 0x0002
TOLERANCE_PX = 2


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


def expected_geometry(description):
    """{window id: (x, y, width, height)} of the described controls."""
    ids = window_ids(description)
    return {ids[item["id"]]: (item["x"], item["y"], item["width"], item["height"])
            for item in description["controls"]}


class RECT(C.Structure):
    _fields_ = [("left", W.LONG), ("top", W.LONG), ("right", W.LONG), ("bottom", W.LONG)]


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
            controls.append({"id": window["id"], "hwnd": window["hwnd"], "class": window["class"],
                             "text": window["text"], "visible": window["visible"], "enabled": window["enabled"],
                             "rect": rect, "inside_client": inside(rect, chain[0]["client_size"])})
        return dict(summary, found=True, parent=chain[0], chain=chain, controls=controls)

    def click(self, inspection, control_id, timeout_ms=10000):
        """BM_CLICK to the button with ``control_id``, after rechecking the server identity."""
        button = next((c for c in inspection.get("controls", []) if c["id"] == control_id), None)
        if button is None:
            return {"control_id": control_id, "found": False, "requested": False}
        self.modal.verify()
        if self.modal.owner(button["hwnd"]) != (self.modal.server["pid"], self.modal.tid):
            raise RuntimeError("button is not on the verified server thread")
        result = C.c_size_t()
        started = time.monotonic()
        C.set_last_error(0)
        returned = self.user.SendMessageTimeoutW(button["hwnd"], BM_CLICK, 0, 0, SMTO_ABORTIFHUNG,
                                                 timeout_ms, C.byref(result))
        return {"control_id": control_id, "found": True, "requested": True, "message": "BM_CLICK",
                "returned": bool(returned), "last_error": C.get_last_error() if not returned else 0,
                "elapsed_s": round(time.monotonic() - started, 3), "identity_rechecked": True,
                "button": {k: button[k] for k in ("hwnd", "class", "text", "visible", "enabled", "rect",
                                                  "inside_client")}}


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
