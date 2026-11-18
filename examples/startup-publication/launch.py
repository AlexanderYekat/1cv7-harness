"""109 verification launcher: real Windows reader locks, no changes to package files."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

import harness77
from harness77 import native_runtime77

root=Path(sys.argv[sys.argv.index('--run-dir')+1]).resolve()
ert=Path(sys.argv[sys.argv.index('--ert')+1])
mode=ert.stem.removeprefix('h109-')
allowed={'baseline','transient-pre','transient-owned','persistent-pre','persistent-owned','deadline','after-failure','cancel','after-cancel'}
assert mode in allowed, mode
info=native_runtime77.inspect_runtime('forms')
payload=Path(harness77.__file__).parent/'_native'
sys.path[:0]=[str(payload/'forms'),str(payload/'platform77')]
import startup77

k=C.WinDLL('kernel32',use_last_error=True)
k.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
k.CreateFileW.restype=W.HANDLE
k.CloseHandle.argtypes=[W.HANDLE];k.CloseHandle.restype=W.BOOL
save=startup77.StartupTrace.save
replace=Path.replace
replace_trace=getattr(startup77,'replace_trace',None)
lock_handle=None
timers=[]
evidence=dict(mode=mode,version=harness77.__version__,package=harness77.__file__,runtime=info,
              diagnostic_file_lock_injection=mode not in ('baseline','after-failure','after-cancel'),
              injected=False,replacement_errors=[])
target_stage='debugger_commands' if mode.endswith('owned') else 'debugger_create'
mutex=threading.Lock()

def close_reader():
    global lock_handle
    with mutex:
        if lock_handle is not None:
            assert k.CloseHandle(lock_handle)
            lock_handle=None
            evidence['released_after_s']=round(time.monotonic()-evidence['held_at'],6)

def checked_replace(path,target):
    try:return replace(path,target)
    except OSError as error:
        if Path(target).name=='startup.json':
            evidence['replacement_errors'].append(dict(winerror=getattr(error,'winerror',None),
                source=path.name,elapsed_s=round(time.monotonic()-evidence['held_at'],6) if evidence.get('injected') else None))
        raise


def checked_trace_replace(path,target):
    # New runtime can reject the real kernel sharing conflict at preflight.
    try:return replace_trace(path,target)
    except OSError as error:
        evidence['replacement_errors'].append(dict(winerror=getattr(error,'winerror',None),
            source=path.name,elapsed_s=round(time.monotonic()-evidence['held_at'],6) if evidence.get('injected') else None))
        raise

def injected_save(trace,*args,**kwargs):
    global lock_handle
    if evidence['diagnostic_file_lock_injection'] and not evidence['injected'] and trace.data['waiting_for']==target_stage:
        evidence.update(injected=True,held_at=time.monotonic(),phase=target_stage,path=str(trace.path),
                        prior_sha256=hashlib.sha256(trace.path.read_bytes()).hexdigest())
        lock_handle=k.CreateFileW(str(trace.path),0x80000000,3,None,3,0x80,None)
        assert lock_handle!=C.c_void_p(-1).value,C.WinError(C.get_last_error())
        # Keep old single-attempt controls held until their failure is recorded:
        # MoveFileEx can itself wait past a short timer and then succeed.
        if mode.startswith('transient') and replace_trace is not None:
            timer=threading.Timer(0.2,close_reader);timers.append(timer);timer.start()
        if mode=='cancel':
            timer=threading.Timer(0.06,lambda:(root/'cancel').write_text('test 109',encoding='ascii'))
            timers.append(timer);timer.start()
    return save(trace,*args,**kwargs)

try:
    startup77.StartupTrace.save=injected_save
    if replace_trace is None:Path.replace=checked_replace
    else:startup77.replace_trace=checked_trace_replace
    raise SystemExit(native_runtime77.main(['--adapter','forms',*sys.argv[1:]]))
finally:
    for timer in timers:timer.cancel();timer.join()
    if evidence['injected']:
        p=Path(evidence['path'])
        evidence['last_sha256_before_release']=hashlib.sha256(p.read_bytes()).hexdigest()
    close_reader()
    Path.replace=replace
    if replace_trace is not None:startup77.replace_trace=replace_trace
    evidence.pop('held_at',None)
    evidence['temporary_files']=[p.name for p in (root/'native').glob('*startup*.tmp')]
    (root/'fault109.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
