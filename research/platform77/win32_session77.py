"""Windows primitives shared by guarded 7.7 experiments; no launch on import."""
import contextlib
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
import winreg

# Named value on the ProgID root: who registered it and the processes of its session (task 015).
OWNER_VALUE = "Harness77Owner"
# Checking, removing and creating the roots is one step for every guarded session of this user.
REGISTRATION_MUTEX = "Local\\Harness77Diagnostic.Registration"
DESCRIPTION = "Harness77 diagnostic COM cleanup"


class TemporaryRegistration:
    """Two temporary HKCU32 COM roots of one session; calling it removes them.

    The ProgID root carries an owner record: the registering process and, as the
    session starts them, its debugger, 1C server and client. A registration left
    by a killed session (task 014: Claude Code removes the MCP server's process
    tree) is replaced only when every recorded process is proven gone.
    """

    def __init__(self, roots, view, state, record):
        self.roots, self.view, self.state, self.record = roots, view, state, record
        self.created = []

    def owner_text(self):
        return json.dumps(self.record, ensure_ascii=True, sort_keys=True)

    def note_process(self, role, pid, handle):
        """Add a process this session started to the owner record."""
        self.record["processes"].append(dict(role=role, pid=pid, creation_filetime=creation_filetime(handle)))
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.roots[0], 0, winreg.KEY_SET_VALUE | self.view) as key:
            winreg.SetValueEx(key, OWNER_VALUE, 0, winreg.REG_SZ, self.owner_text())
        self.state["owner"] = json.loads(self.owner_text())

    def create(self, entries):
        for path, value in entries:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE | self.view) as key:
                if path == self.roots[0]:
                    # The owner first: a root without it can never be proven stale.
                    winreg.SetValueEx(key, OWNER_VALUE, 0, winreg.REG_SZ, self.owner_text())
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
                self.created.append((path, value))
                if path.endswith("InprocServer32"):
                    winreg.SetValueEx(key, "ThreadingModel", 0, winreg.REG_SZ, "Apartment")

    def __call__(self):
        # Verify all values before removing any keys; do not delete a changed root.
        for path, value in self.created:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | self.view) as key:
                if winreg.QueryValueEx(key, "")[0] != value:
                    raise RuntimeError(f"temporary COM registration was changed: {path}")
                if path == self.roots[0] and winreg.QueryValueEx(key, OWNER_VALUE)[0] != self.owner_text():
                    raise RuntimeError(f"temporary COM registration owner was changed: {path}")
        for path, _ in reversed(self.created):
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, self.view, 0)
        for root in self.roots:
            if read_tree(root, self.view) is not None:
                raise RuntimeError(f"temporary COM root still exists: {root}")
        self.state["removed"] = True


def read_tree(root, view):
    """{key path: {value name: data}} of an HKCU key and its subkeys; None when absent."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, root, 0, winreg.KEY_READ | view)
    except FileNotFoundError:
        return None
    tree = {}

    def visit(key, path):
        subkeys, values, unused = winreg.QueryInfoKey(key)
        tree[path] = dict(winreg.EnumValue(key, index)[:2] for index in range(values))
        for index in range(subkeys):
            name = winreg.EnumKey(key, index)
            with winreg.OpenKey(key, name, 0, winreg.KEY_READ | view) as child:
                visit(child, path + "\\" + name)
    with key:
        visit(key, root)
    return tree


def process_gone(entry):
    """How a recorded process is proven gone ("absent", "exited", "pid-reused"); None if it runs.

    Anything else, such as a PID this user cannot open, is not a proof and raises.
    """
    handle = kernel.OpenProcess(0x100000 | 0x1000, False, entry["pid"])
    if not handle:
        error = C.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: no process has this PID
            return "absent"
        raise C.WinError(error)
    try:
        if kernel.WaitForSingleObject(handle, 0) == 0:
            return "exited"
        return "pid-reused" if creation_filetime(handle) != entry["creation_filetime"] else None
    finally:
        kernel.CloseHandle(handle)


def stale_registration(roots, view, clsid):
    """Proof that existing roots were left by a finished session of this tool, or why not.

    Returns (evidence, None) when the roots hold exactly this tool's layout (or part
    of it, after a kill while creating or removing) and every process of the owner
    record is gone; otherwise (None, reason).
    """
    found = {}
    for root in roots:
        found.update(read_tree(root, view) or {})
    try:
        record = json.loads(found[roots[0]][OWNER_VALUE])
        processes_ = record["processes"]
        dll = record["dll"]
        if not processes_ or not all(type(p.get("pid")) is int and type(p.get("creation_filetime")) is int
                                     for p in processes_):
            raise ValueError("no processes")
    except (KeyError, TypeError, AttributeError, ValueError):
        return None, "no owner record (another tool, an older launcher or an interrupted creation)"
    layout = {roots[0]: {"": DESCRIPTION, OWNER_VALUE: found[roots[0]][OWNER_VALUE]},
              roots[0] + r"\CLSID": {"": clsid},
              roots[1]: {"": DESCRIPTION},
              roots[1] + r"\InprocServer32": {"": dll, "ThreadingModel": "Apartment"}}
    for path, values in found.items():
        expected = layout.get(path)
        if expected is None or any(name not in expected or expected[name] != data for name, data in values.items()):
            return None, "unexpected key or value: " + path
    evidence = []
    for entry in processes_:
        try:
            gone = process_gone(entry)
        except OSError as error:
            return None, f"process {entry['pid']} ({entry.get('role')}) cannot be checked: {error}"
        if gone is None:
            return None, f"owner process alive: {entry['pid']} ({entry.get('role')}, run {record.get('run_id')})"
        evidence.append(dict(entry, gone=gone))
    return {"run_id": record.get("run_id"), "processes": evidence, "keys": sorted(found)}, None


@contextlib.contextmanager
def registration_lock(timeout_ms=30000):
    handle = kernel.CreateMutexW(None, False, REGISTRATION_MUTEX)
    if not handle:
        raise C.WinError(C.get_last_error())
    try:
        # WAIT_ABANDONED: the previous holder died; the registry check below still applies.
        waited = kernel.WaitForSingleObject(handle, timeout_ms)
        if waited not in (0, 0x80):
            raise RuntimeError("COM registration lock is busy; wait=" + str(waited))
        try:
            yield
        finally:
            kernel.ReleaseMutex(handle)
    finally:
        kernel.CloseHandle(handle)


def register_cleanup_helper(dll, report, *, identity=False):
    """Own two temporary HKCU32 COM roots; replace an existing registration only when stale."""
    clsid = "{16B8A521-07E4-46D1-A8E7-197BD1CE4477}"
    progid = "Harness77Diagnostic.ComCleanup"
    if identity:
        clsid = "{7E477C71-018E-4C27-9E38-2D5DDA9F6A07}"
        progid = "Harness77Diagnostic.ProxyIdentity"
    roots = [rf"Software\Classes\{progid}", rf"Software\Classes\CLSID\{clsid}"]
    view = winreg.KEY_WOW64_32KEY
    entries = [(roots[0], DESCRIPTION),
               (roots[0] + r"\CLSID", clsid),
               (roots[1], DESCRIPTION),
               (roots[1] + r"\InprocServer32", str(dll))]
    state = {"roots": roots, "view": "HKCU32", "dll": str(dll),
             "sha256": hashlib.sha256(dll.read_bytes()).hexdigest(), "removed": False}
    current = kernel.GetCurrentProcess()
    record = {"schema_version": 1, "run_id": report.get("run_id"), "dll": str(dll),
              "processes": [{"role": "registrar", "pid": os.getpid(), "creation_filetime": creation_filetime(current)}]}
    registration = TemporaryRegistration(roots, view, state, record)
    with registration_lock():
        if any(read_tree(root, view) is not None for root in roots):
            evidence, reason = stale_registration(roots, view, clsid)
            if evidence is None:
                raise RuntimeError(f"refusing to overwrite existing COM registration: {roots[0]}: {reason}")
            for path in sorted(evidence["keys"], key=lambda p: p.count("\\"), reverse=True):
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, view, 0)
            if any(read_tree(root, view) is not None for root in roots):
                raise RuntimeError(f"stale COM registration still exists: {roots[0]}")
            state["stale_removed"] = evidence
        report["identity_registration" if identity else "temporary_com_registration"] = state
        state["owner"] = json.loads(registration.owner_text())
        try:
            registration.create(entries)
        except Exception:
            registration()
            raise
    return registration


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
kernel.GetCurrentProcess.restype = W.HANDLE
kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
kernel.CreateMutexW.restype = W.HANDLE
kernel.ReleaseMutex.argtypes = [W.HANDLE]


def creation_filetime(handle):
    times = [W.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *[C.byref(t) for t in times]):
        raise C.WinError(C.get_last_error())
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def process_identity(handle):
    image, length = C.create_unicode_buffer(32768), W.DWORD(32768)
    if not kernel.QueryFullProcessImageNameW(handle, 0, image, C.byref(length)):
        raise C.WinError(C.get_last_error())
    return {"image": image.value, "creation_filetime": creation_filetime(handle)}


def process_cpu_ms(handle):
    """Cumulative CPU time from a retained process handle, also after exit."""
    times = [W.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *[C.byref(t) for t in times]):
        raise C.WinError(C.get_last_error())
    return round(sum((t.dwHighDateTime << 32) | t.dwLowDateTime for t in times[2:]) / 10000, 3)


def base_titles_fingerprint():
    """Read-only snapshot of the 7.7 user database list; no names in the report."""
    root = r"Software\1C\1Cv7\7.7\Titles"
    entries = []

    def visit(key, path):
        subkeys, values, unused = winreg.QueryInfoKey(key)
        for index in range(values):
            name, value, kind = winreg.EnumValue(key, index)
            entries.append((path, name, kind, repr(value)))
        for index in range(subkeys):
            name = winreg.EnumKey(key, index)
            with winreg.OpenKey(key, name) as child:
                visit(child, path + "\\" + name)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            visit(key, root)
    except FileNotFoundError:
        return {"root": root, "present": False}
    data = json.dumps(sorted(entries), ensure_ascii=True).encode("ascii")
    return {"root": root, "present": True, "values": len(entries), "sha256": hashlib.sha256(data).hexdigest()}


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
