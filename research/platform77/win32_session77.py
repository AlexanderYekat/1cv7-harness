"""Windows primitives shared by guarded 7.7 experiments; no launch on import."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import winreg


def register_cleanup_helper(dll, report, *, identity=False):
    """Own two temporary HKCU32 COM roots; never replace existing registration."""
    clsid = "{16B8A521-07E4-46D1-A8E7-197BD1CE4477}"
    progid = "Harness77Diagnostic.ComCleanup"
    if identity:
        clsid = "{7E477C71-018E-4C27-9E38-2D5DDA9F6A07}"
        progid = "Harness77Diagnostic.ProxyIdentity"
    roots = [rf"Software\Classes\{progid}", rf"Software\Classes\CLSID\{clsid}"]
    view = winreg.KEY_WOW64_32KEY
    for root in roots:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, root, 0, winreg.KEY_READ | view)
        except FileNotFoundError:
            continue
        key.Close()
        raise RuntimeError(f"refusing to overwrite existing COM registration: {root}")
    entries = [(roots[0], "Harness77 diagnostic COM cleanup"),
               (roots[0] + r"\CLSID", clsid),
               (roots[1], "Harness77 diagnostic COM cleanup"),
               (roots[1] + r"\InprocServer32", str(dll))]
    created = []
    state = {"roots": roots, "view": "HKCU32", "dll": str(dll),
             "sha256": hashlib.sha256(dll.read_bytes()).hexdigest(), "removed": False}
    report["identity_registration" if identity else "temporary_com_registration"] = state

    def cleanup():
        # Verify all values before removing any keys; do not delete a changed root.
        for path, value in created:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | view) as key:
                if winreg.QueryValueEx(key, "")[0] != value:
                    raise RuntimeError(f"temporary COM registration was changed: {path}")
        for path, _ in reversed(created):
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, view, 0)
        for root in roots:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, root, 0, winreg.KEY_READ | view)
            except FileNotFoundError:
                continue
            key.Close()
            raise RuntimeError(f"temporary COM root still exists: {root}")
        state["removed"] = True

    try:
        for path, value in entries:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE | view) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
                created.append((path, value))
                if path.endswith("InprocServer32"):
                    winreg.SetValueEx(key, "ThreadingModel", 0, winreg.REG_SZ, "Apartment")
    except Exception:
        cleanup()
        raise
    return cleanup


class ProcessEntry(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD),
                ("th32ProcessID", W.DWORD), ("th32DefaultHeapID", C.c_size_t),
                ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", W.LONG),
                ("dwFlags", W.DWORD), ("szExeFile", W.WCHAR * 260)]


kernel = C.WinDLL("kernel32", use_last_error=True)
kernel.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
kernel.CreateToolhelp32Snapshot.restype = W.HANDLE
kernel.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]
kernel.Process32NextW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]
kernel.CloseHandle.argtypes = [W.HANDLE]
kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel.OpenProcess.restype = W.HANDLE
kernel.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
kernel.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
kernel.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4


def process_identity(handle):
    image, length = C.create_unicode_buffer(32768), W.DWORD(32768)
    if not kernel.QueryFullProcessImageNameW(handle, 0, image, C.byref(length)):
        raise C.WinError(C.get_last_error())
    times = [W.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *[C.byref(t) for t in times]):
        raise C.WinError(C.get_last_error())
    return {"image": image.value, "creation_filetime": (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime}


def process_cpu_ms(handle):
    """Cumulative CPU time from a retained process handle, also after exit."""
    times = [W.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *[C.byref(t) for t in times]):
        raise C.WinError(C.get_last_error())
    return round(sum((t.dwHighDateTime << 32) | t.dwLowDateTime for t in times[2:]) / 10000, 3)


class BaselineProcesses:
    """Hold query/synchronize-only handles to existing sessions, never stop them."""
    def __init__(self, inventory):
        self.items = []
        try:
            for item in inventory:
                handle = kernel.OpenProcess(0x100000 | 0x1000, False, item["pid"])
                if not handle:
                    raise C.WinError(C.get_last_error())
                self.items.append((handle, dict(item)))
                self.items[-1][1].update(process_identity(handle))
            if not self.preserved() or sorted(processes(), key=lambda p: p["pid"]) != sorted(inventory, key=lambda p: p["pid"]):
                raise RuntimeError("baseline changed while acquiring read-only handles")
        except Exception:
            self.close()
            raise

    def preserved(self):
        return all(kernel.WaitForSingleObject(handle, 0) == 0x102
                   and process_identity(handle) == {k: item[k] for k in ("image", "creation_filetime")}
                   for handle, item in self.items)

    def evidence(self):
        return [dict(item) for _, item in self.items]

    def close(self):
        for handle, _ in self.items:
            kernel.CloseHandle(handle)
        self.items.clear()


def processes():
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        entry = ProcessEntry()
        entry.dwSize = C.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, C.byref(entry))
        result = []
        while found:
            if entry.szExeFile.lower().startswith("1cv7") and entry.szExeFile.lower().endswith(".exe"):
                result.append({"pid": entry.th32ProcessID, "parent_pid": entry.th32ParentProcessID})
            found = kernel.Process32NextW(snapshot, C.byref(entry))
        return result
    finally:
        kernel.CloseHandle(snapshot)
