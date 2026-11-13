"""Read-only Windows observations for doctor; no COM activation or registration."""

import ctypes as C
from ctypes import wintypes as W
import os

TITLES = r"Software\1C\1Cv7\7.7\Titles"
COM_KEYS = (
    r"Software\Classes\Harness77Diagnostic.ProxyIdentity",
    r"Software\Classes\CLSID\{7E477C71-018E-4C27-9E38-2D5DDA9F6A07}",
    r"Software\Classes\Harness77Diagnostic.ComCleanup",
    r"Software\Classes\CLSID\{16B8A521-07E4-46D1-A8E7-197BD1CE4477}",
)


class WindowsInspector:
    def registered(self, path):
        import winreg
        wanted = os.path.normcase(os.path.abspath(path)).rstrip("\\")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TITLES, 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
                count = winreg.QueryInfoKey(key)[1]
                for index in range(count):
                    name = winreg.EnumValue(key, index)[0]
                    if name and os.path.normcase(os.path.abspath(name)).rstrip("\\") == wanted:
                        return True
        except FileNotFoundError:
            return False
        return False

    def com_registrations(self):
        import winreg
        found = []
        for name in COM_KEYS:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, name, 0,
                                    winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
                    found.append(name)
            except FileNotFoundError:
                pass
        return found

    def processes(self):
        class Entry(C.Structure):
            _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD),
                        ("pid", W.DWORD), ("heap", C.c_size_t), ("module", W.DWORD),
                        ("threads", W.DWORD), ("parent", W.DWORD), ("priority", W.LONG),
                        ("flags", W.DWORD), ("image", W.WCHAR * 260)]

        kernel = C.WinDLL("kernel32", use_last_error=True)
        kernel.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = W.HANDLE
        kernel.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(Entry)]
        kernel.Process32NextW.argtypes = [W.HANDLE, C.POINTER(Entry)]
        kernel.CloseHandle.argtypes = [W.HANDLE]
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        try:
            row = Entry()
            row.dwSize = C.sizeof(row)
            result = []
            found = kernel.Process32FirstW(snapshot, C.byref(row))
            if not found and C.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                raise C.WinError(C.get_last_error())
            while found:
                if row.image.lower().startswith("1cv7") and row.image.lower().endswith(".exe"):
                    result.append({"pid": row.pid, "parent_pid": row.parent, "image": row.image})
                found = kernel.Process32NextW(snapshot, C.byref(row))
            if C.get_last_error() != 18:
                raise C.WinError(C.get_last_error())
            return sorted(result, key=lambda item: item["pid"])
        finally:
            kernel.CloseHandle(snapshot)
