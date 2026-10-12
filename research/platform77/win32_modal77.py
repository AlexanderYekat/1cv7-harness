"""Inspect only the owned private desktop; dismiss only the synthetic UUID warning.

No input injection, foreground activation, desktop switching or global window search.
"""
import ctypes as C
from ctypes import wintypes as W
import time

from desktop77 import verify_server_desktop
from modal_wait77 import select_dialog
from win32_session77 import kernel, process_identity


class OwnedModal:
    def __init__(self, handle, server, tid, desktop, run_id):
        self.handle, self.server, self.tid = handle, server, tid
        self.desktop, self.run_id = desktop, run_id
        self.user = C.WinDLL("user32", use_last_error=True)
        self.callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        self.user.GetThreadDesktop.argtypes = [W.DWORD]
        self.user.GetThreadDesktop.restype = W.HANDLE
        self.user.EnumDesktopWindows.argtypes = [W.HANDLE, self.callback_type, W.LPARAM]
        self.user.EnumChildWindows.argtypes = [W.HWND, self.callback_type, W.LPARAM]
        self.user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.user.GetWindowThreadProcessId.restype = W.DWORD
        self.user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
        self.user.GetDlgCtrlID.argtypes = [W.HWND]
        self.user.GetWindow.argtypes = [W.HWND, W.UINT]
        self.user.GetWindow.restype = W.HWND
        self.user.IsWindowEnabled.argtypes = [W.HWND]
        self.user.IsWindowVisible.argtypes = [W.HWND]
        self.user.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM,
                                                 W.UINT, W.UINT, C.POINTER(C.c_size_t)]
        self.user.SendMessageTimeoutW.restype = W.LPARAM
        self.user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]

    def verify(self):
        if (self.server.get("ownership_verified") is not True
                or not self.desktop.startswith("harness77_")
                or kernel.WaitForSingleObject(self.handle, 0) != 0x102
                or process_identity(self.handle) != {k: self.server[k] for k in ("image", "creation_filetime")}):
            raise RuntimeError("modal server identity no longer valid")
        verify_server_desktop(self.tid, self.server["pid"], self.desktop)

    def owner(self, hwnd):
        pid = W.DWORD()
        tid = self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return pid.value, tid

    def enumerate(self, parent=None):
        handles = []
        @self.callback_type
        def visit(hwnd, unused):
            handles.append(hwnd)
            return len(handles) <= 128
        if parent is None:
            if not self.user.EnumDesktopWindows(self.user.GetThreadDesktop(self.tid), visit, 0):
                raise C.WinError(C.get_last_error())
        else:
            self.user.EnumChildWindows(parent, visit, 0)
        if len(handles) > 128:
            raise RuntimeError("modal window enumeration limit")
        return handles

    def info(self, hwnd, until):
        if time.monotonic() >= until:
            raise TimeoutError("modal snapshot budget")
        pid, tid = self.owner(hwnd)
        if pid != self.server["pid"] or tid != self.tid:
            raise RuntimeError("window is not on the verified server thread")
        name, text, result = C.create_unicode_buffer(256), C.create_unicode_buffer(2048), C.c_size_t()
        if not self.user.GetClassNameW(hwnd, name, len(name)):
            raise C.WinError(C.get_last_error())
        if not self.user.SendMessageTimeoutW(hwnd, 0x000D, len(text), C.addressof(text), 0x22, 200, C.byref(result)):
            raise RuntimeError("owned window text did not respond")
        return {"hwnd": hwnd, "pid": pid, "tid": tid, "class": name.value, "text": text.value,
                "id": self.user.GetDlgCtrlID(hwnd), "visible": bool(self.user.IsWindowVisible(hwnd)),
                "enabled": bool(self.user.IsWindowEnabled(hwnd))}

    def snapshot(self):
        self.verify()
        until = time.monotonic() + 2
        windows = []
        for hwnd in self.enumerate():
            if self.owner(hwnd) != (self.server["pid"], self.tid):
                continue
            window = self.info(hwnd, until)
            window["desktop"] = self.desktop
            if window["class"] == "#32770":
                window["children"] = [self.info(child, until) for child in self.enumerate(hwnd)]
                owner = self.user.GetWindow(hwnd, 4)  # GW_OWNER
                window["owner"] = owner
                window["owner_pid"], window["owner_tid"] = self.owner(owner)
                window["owner_enabled"] = bool(self.user.IsWindowEnabled(owner))
            windows.append(window)
        return windows

    def dismiss(self, windows):
        chosen = select_dialog(windows, self.run_id, self.server["pid"], self.tid, self.desktop)
        # Re-enumerate and verify the retained process immediately before messaging.
        current = select_dialog(self.snapshot(), self.run_id, self.server["pid"], self.tid, self.desktop)
        if current != chosen:
            raise RuntimeError("modal dialog changed before dismissal")
        button = next(c for c in current["children"] if c["class"] == "Button")
        if not self.user.PostMessageW(current["hwnd"], 0x0111, button["id"], button["hwnd"]):
            raise C.WinError(C.get_last_error())
        return {"dialog": current, "requested": True, "message": "WM_COMMAND/BN_CLICKED",
                "control_id": button["id"], "identity_rechecked": True}
