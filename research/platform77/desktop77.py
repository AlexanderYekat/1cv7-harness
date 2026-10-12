"""Private Windows desktop for native tests; never switch the user's desktop."""
import ctypes as C
from ctypes import wintypes as W
import uuid
import os
import msvcrt
import subprocess
import time


class StartupInfo(C.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR),
        ("lpTitle", W.LPWSTR), ("dwX", W.DWORD), ("dwY", W.DWORD),
        ("dwXSize", W.DWORD), ("dwYSize", W.DWORD), ("dwXCountChars", W.DWORD),
        ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD), ("dwFlags", W.DWORD),
        ("wShowWindow", W.WORD), ("cbReserved2", W.WORD), ("lpReserved2", C.c_void_p),
        ("hStdInput", W.HANDLE), ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]


class ProcessInfo(C.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE),
                ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


def thread_desktop_name(thread_id):
    user = C.WinDLL("user32", use_last_error=True)
    user.GetThreadDesktop.argtypes = [W.DWORD]
    user.GetThreadDesktop.restype = W.HANDLE
    user.GetUserObjectInformationW.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    handle = user.GetThreadDesktop(thread_id)
    if not handle:
        raise C.WinError(C.get_last_error())
    text, needed = C.create_unicode_buffer(256), W.DWORD()
    if not user.GetUserObjectInformationW(handle, 2, text, C.sizeof(text), C.byref(needed)):
        raise C.WinError(C.get_last_error())
    return text.value


def verify_server_desktop(thread_id, process_id, desktop):
    api = C.WinDLL("kernel32", use_last_error=True)
    api.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    api.OpenThread.restype = W.HANDLE
    api.GetProcessIdOfThread.argtypes = [W.HANDLE]
    api.GetProcessIdOfThread.restype = W.DWORD
    api.CloseHandle.argtypes = [W.HANDLE]
    handle = api.OpenThread(0x0800, False, thread_id)
    if not handle:
        raise C.WinError(C.get_last_error())
    try:
        if api.GetProcessIdOfThread(handle) != process_id or thread_desktop_name(thread_id) != desktop:
            raise RuntimeError("OLE server thread is not on the owned private desktop")
    finally:
        api.CloseHandle(handle)


class DesktopProcess:
    """Minimal Popen-like wrapper: subprocess.STARTUPINFO ignores lpDesktop."""
    def __init__(self, command, desktop, stdout, cwd=None):
        self.api = C.WinDLL("kernel32", use_last_error=True)
        self.api.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p,
            W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR, C.POINTER(StartupInfo), C.POINTER(ProcessInfo)]
        self.api.GetCurrentProcess.restype = W.HANDLE
        self.api.DuplicateHandle.argtypes = [W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD]
        self.api.CloseHandle.argtypes = [W.HANDLE]
        self.api.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
        self.api.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        self.api.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
        self._handle = None
        self.stdin = None
        self.returncode = None
        inherited = []
        current = self.api.GetCurrentProcess()
        def duplicate(file):
            handle = W.HANDLE()
            if not self.api.DuplicateHandle(current, msvcrt.get_osfhandle(file.fileno()),
                    current, C.byref(handle), 0, True, 2):
                raise C.WinError(C.get_last_error())
            inherited.append(handle)
            return handle.value
        try:
            with open(os.devnull, "rb") as null:
                info = StartupInfo()
                info.cb = C.sizeof(info)
                info.lpDesktop = desktop
                info.dwFlags = 0x101  # STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
                info.wShowWindow = 0
                info.hStdInput = duplicate(null)
                info.hStdOutput = duplicate(stdout)
                info.hStdError = info.hStdOutput
                process = ProcessInfo()
                line = C.create_unicode_buffer(subprocess.list2cmdline(list(map(str, command))))
                if not self.api.CreateProcessW(str(command[0]), line, None, None, True,
                        0x08000000, None, cwd, C.byref(info), C.byref(process)):
                    raise C.WinError(C.get_last_error())
                self._handle, self.pid, self.thread_id = process.hProcess, process.dwProcessId, process.dwThreadId
                self.api.CloseHandle(process.hThread)
        finally:
            for handle in inherited:
                self.api.CloseHandle(handle)

    def poll(self):
        if self.returncode is None and self.api.WaitForSingleObject(self._handle, 0) == 0:
            code = W.DWORD()
            if not self.api.GetExitCodeProcess(self._handle, C.byref(code)):
                raise C.WinError(C.get_last_error())
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout):
        until = time.monotonic() + timeout
        while self.poll() is None:
            if time.monotonic() >= until:
                raise subprocess.TimeoutExpired("private desktop child", timeout)
            time.sleep(0.05)
        return self.returncode

    def kill(self):
        if not self.api.TerminateProcess(self._handle, 1):
            raise C.WinError(C.get_last_error())

    def __del__(self):
        if getattr(self, "_handle", None):
            self.api.CloseHandle(self._handle)


class PrivateDesktop:
    def __init__(self):
        self.name = "harness77_" + uuid.uuid4().hex
        self.user = C.WinDLL("user32", use_last_error=True)
        self.user.CreateDesktopW.argtypes = [W.LPCWSTR, W.LPCWSTR, C.c_void_p, W.DWORD, W.DWORD, C.c_void_p]
        self.user.CreateDesktopW.restype = W.HANDLE
        self.user.CloseDesktop.argtypes = [W.HANDLE]
        self.handle = None

    def __enter__(self):
        self.handle = self.user.CreateDesktopW(self.name, None, None, 0, 0x10000000, None)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        return self

    def __exit__(self, *unused):
        if not self.user.CloseDesktop(self.handle):
            raise C.WinError(C.get_last_error())
