"""Read-only Win32 foreground sampling. No input injection or window actions."""
import ctypes
from ctypes import wintypes
import threading
import time


class FocusObserver:
    def __init__(self):
        self.stop_event = threading.Event()
        self.samples = 0
        self.max_gap_ms = 0
        self.transitions = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        last = None
        previous_time = time.monotonic()
        while not self.stop_event.is_set():
            now = time.monotonic()
            self.max_gap_ms = max(self.max_gap_ms, (now - previous_time) * 1000)
            previous_time = now
            hwnd = user.GetForegroundWindow()
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            current = (hwnd, pid.value)
            if current != last:
                self.transitions.append({"at_unix": time.time(), "hwnd": hwnd, "pid": pid.value})
                last = current
            self.samples += 1
            self.stop_event.wait(0.01)

    def start(self):
        self.thread.start()

    def finish(self):
        self.stop_event.set()
        self.thread.join(2)
        return {"method": "GetForegroundWindow/GetWindowThreadProcessId, read-only",
                "requested_interval_ms": 10, "max_gap_ms": round(self.max_gap_ms, 3),
                "samples": self.samples, "transitions": self.transitions}
