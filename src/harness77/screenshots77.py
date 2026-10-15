"""Diagnostic screenshots of the run's own windows (roadmap stage 4 scope).

On an error or a timeout the native backend may capture windows that belong to
its own process on its own private desktop, to attach as diagnostic evidence.
Capture is bounded in time and must never delay cancellation or shutdown. A
missing window, an unavailable capture or a write error is recorded with an
explicit reason, separately from the failure that triggered the capture. A PNG
file existing with a matching hash does not by itself prove correct contents;
that is the native acceptance. Automatic visual comparison is stage 5.1, not
here.

``evaluate`` and ``evidence`` are portable and tested. ``capture_window`` is a
best-effort Windows GDI capture, used only on the real stand.
"""

from __future__ import annotations

from pathlib import Path

from .report77 import file_evidence


def evaluate(window, *, own_pid, desktop):
    """Decide whether one enumerated window may be captured. Fail closed.

    Only a window on the run's own process and own private desktop is eligible.
    Returns ``(allowed, reason)``; ``reason`` is set when capture is refused.
    """
    if not isinstance(window, dict):
        return False, "window metadata missing"
    if window.get("pid") != own_pid:
        return False, "window belongs to another process"
    if not desktop or window.get("desktop") != desktop:
        return False, "window is not on the owned private desktop"
    if not window.get("hwnd"):
        return False, "no window handle"
    return True, None


def evidence(path, *, run_id, phase, window, root, captured=True, error=None):
    """Evidence record for one screenshot attempt, with size and SHA-256."""
    record = {"run_id": run_id, "phase": phase,
              "window": {k: window.get(k) for k in ("hwnd", "pid", "tid", "class", "text", "desktop")},
              "captured": bool(captured and error is None)}
    if error is not None:
        record.update(captured=False, error=str(error), file=None)
        return record
    record["file"] = file_evidence(path, root=root, complete=True)
    if record["file"].get("exists") is not True or not record["file"].get("size_bytes"):
        record["captured"] = False
        record.setdefault("error", "capture file missing or empty")
    return record


def collect(windows, *, own_pid, desktop, run_id, phase, out_dir, capture, budget_s=5.0, clock=None):
    """Capture every eligible own window within a finite budget; never block.

    ``capture(hwnd, path)`` performs the native capture (raises on failure).
    Returns a list of evidence records. Refused and failed captures are recorded
    with their reason and never raise out of this function.
    """
    import time

    now = clock.now if clock else time.monotonic
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    deadline = now() + budget_s
    records = []
    for index, window in enumerate(windows):
        allowed, reason = evaluate(window, own_pid=own_pid, desktop=desktop)
        if not allowed:
            records.append(evidence(None, run_id=run_id, phase=phase, window=window if isinstance(window, dict) else {},
                                    root=out_dir, error="refused: " + reason))
            continue
        if now() >= deadline:
            records.append(evidence(None, run_id=run_id, phase=phase, window=window,
                                    root=out_dir, error="screenshot budget exhausted"))
            continue
        target = out_dir / f"{phase}-{index:02d}-{window['hwnd']}.png"
        try:
            capture(window["hwnd"], target)
            records.append(evidence(target, run_id=run_id, phase=phase, window=window, root=out_dir))
        except (OSError, RuntimeError) as error:
            records.append(evidence(None, run_id=run_id, phase=phase, window=window,
                                    root=out_dir, error=f"capture failed: {type(error).__name__}: {error}"))
    return records


def capture_window(hwnd, path):  # pragma: no cover - native GDI, verified on the stand
    """Capture one window to a PNG via Win32 GDI PrintWindow. Windows only."""
    import ctypes as C
    from ctypes import wintypes as W

    user = C.WinDLL("user32", use_last_error=True)
    gdi = C.WinDLL("gdi32", use_last_error=True)

    class RECT(C.Structure):
        _fields_ = [("left", W.LONG), ("top", W.LONG), ("right", W.LONG), ("bottom", W.LONG)]

    rect = RECT()
    if not user.GetWindowRect(W.HWND(hwnd), C.byref(rect)):
        raise C.WinError(C.get_last_error())
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError("window has no visible area")
    window_dc = user.GetWindowDC(W.HWND(hwnd))
    if not window_dc:
        raise RuntimeError("GetWindowDC failed")
    try:
        mem_dc = gdi.CreateCompatibleDC(window_dc)
        bitmap = gdi.CreateCompatibleBitmap(window_dc, width, height)
        gdi.SelectObject(mem_dc, bitmap)
        if not user.PrintWindow(W.HWND(hwnd), mem_dc, 2):  # PW_RENDERFULLCONTENT
            raise RuntimeError("PrintWindow failed")
        _write_bmp_as_png(gdi, mem_dc, bitmap, width, height, Path(path))
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(mem_dc)
    finally:
        user.ReleaseDC(W.HWND(hwnd), window_dc)


def _write_bmp_as_png(gdi, mem_dc, bitmap, width, height, path):  # pragma: no cover - native
    """Pull 32-bit pixels and write a minimal, valid PNG without extra packages."""
    import ctypes as C
    from ctypes import wintypes as W
    import struct
    import zlib

    class BITMAPINFOHEADER(C.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
                    ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                    ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG),
                    ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]

    header = BITMAPINFOHEADER()
    header.biSize = C.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height  # top-down
    header.biPlanes = 1
    header.biBitCount = 32
    buffer = (C.c_char * (width * height * 4))()
    if not gdi.GetDIBits(mem_dc, bitmap, 0, height, buffer, C.byref(header), 0):
        raise RuntimeError("GetDIBits failed")
    raw = bytearray()
    pixels = bytes(buffer)
    for y in range(height):
        raw.append(0)  # filter type 0
        row = pixels[y * width * 4:(y + 1) * width * 4]
        raw.extend(b"".join(bytes((row[i + 2], row[i + 1], row[i])) for i in range(0, len(row), 4)))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
