"""Bounded native startup evidence; observation timestamps are not target timestamps."""
import json
import os
from pathlib import Path
import tempfile
import time


class StartupWriteError(RuntimeError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(f"startup trace {detail['stage']} failed after {detail['attempts']} attempt(s): {detail['error']}")


def replace_trace(source, target):
    # Detect an existing incompatible reader before MoveFileEx, which can take
    # a long time to reject the same conflict. Close the probe before rename:
    # even a shared DELETE handle can prevent replacement of its destination.
    # This is a preflight, not a lock; replacement errors still need retries.
    if os.name == 'nt':
        import ctypes as C
        from ctypes import wintypes as W
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
        kernel.CreateFileW.restype = W.HANDLE
        kernel.CloseHandle.argtypes = [W.HANDLE]
        kernel.CloseHandle.restype = W.BOOL
        handle = kernel.CreateFileW(str(target), 0x10000, 7, None, 3, 0x80, None)
        if handle == C.c_void_p(-1).value:
            code = C.get_last_error()
            if code != 2:  # first publication has no destination yet
                raise C.WinError(code)
        elif not kernel.CloseHandle(handle):
            raise C.WinError(C.get_last_error())
    source.replace(target)


def command_marker(run_id):
    return 'HARNESS77_STARTUP_COMMANDS:' + run_id


def commands_processed(log, run_id):
    lines = log.splitlines()
    count = lines.count(command_marker(run_id))
    if count > 1:
        raise ValueError('duplicate startup command marker')
    return count == 1


class StartupTrace:
    def __init__(self, out, run_id, clock=time.perf_counter, *, check=None, publish=True,
                 write_clock=time.monotonic, pause=time.sleep):
        self.path = out / 'startup.json'
        self.clock, self.started = clock, clock()
        self.data = {'schema_version': 1, 'run_id': run_id, 'status': 'waiting',
                     'waiting_for': 'registration', 'events': []}
        self.seen = set()
        self.check, self.write_clock, self.pause = check, write_clock, pause
        if publish:
            self.save()

    def save(self, *, retry=True, guarded=True, first_guard=True):
        """Replace a complete trace, tolerating at most one second of Windows contention.

        Only replacement errors 5/32/33 are retried, never creation/write errors,
        errno-only permission failures or a change of permissions. The unique
        temporary file is on the same volume; the prior report stays intact.
        """
        started = self.write_clock()
        temporary, detail, committed, last_error = None, None, False, None
        attempt, replacements, stage = 0, 0, 'serialize'
        try:
            data = json.dumps(self.data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
            stage = 'check'
            if guarded and self.check and first_guard:
                self.check()
            stage = 'create'
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.'+self.path.name+'.', suffix='.tmp')
            temporary = Path(name)
            os.close(fd)
            for attempt in range(1, 27):
                stage = 'check'
                remaining = self.check() if guarded and self.check and (first_guard or attempt > 1) else None
                if detail is not None and self.write_clock()-started >= 1:
                    stage = 'replace'
                    raise last_error
                if detail is not None:
                    detail.update(attempts=replacements+1, elapsed_ms=round((self.write_clock()-started)*1000, 3), recovered=True)
                    data = json.dumps(self.data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
                stage = 'write'
                temporary.write_text(data, encoding='utf-8')
                stage = 'check'
                remaining = self.check() if guarded and self.check and (first_guard or attempt > 1) else remaining
                stage = 'replace'
                if detail is not None and self.write_clock()-started >= 1:
                    raise last_error
                try:
                    replacements += 1
                    replace_trace(temporary, self.path)
                    committed = True
                    if guarded and self.check and (first_guard or attempt > 1):
                        stage = 'check'
                        self.check()
                    return
                except OSError as error:
                    if stage == 'check':
                        raise
                    last_error = error
                    elapsed = self.write_clock()-started
                    stage = 'check'
                    if guarded and self.check:
                        remaining = self.check()
                    stage = 'replace'
                    transient = getattr(error, 'winerror', None) in (5, 32, 33)
                    if not retry or not transient or attempt == 26 or elapsed >= 1:
                        raise
                    if detail is None:
                        detail = dict(operation='startup-trace-replace', path=self.path.name,
                                      waiting_for=self.data['waiting_for'])
                        self.data.setdefault('write_retries', []).append(detail)
                    detail.update(attempts=attempt, winerror=error.winerror, errno=error.errno,
                                  error=str(error), elapsed_ms=round(elapsed*1000, 3), recovered=False)
                    stage = 'check'
                    if guarded and self.check:
                        remaining = self.check()
                    # A guard may return the remaining phase/session allowance.
                    delay = min(0.04, 1-elapsed)
                    if remaining is not None:
                        delay = min(delay, max(0, remaining))
                    self.pause(delay)
        except OSError as error:
            if stage == 'check':
                raise  # preserve the caller's timeout/cancellation classification
            failure = dict(path=self.path.name, stage=stage, attempts=replacements,
                           errno=error.errno, winerror=getattr(error, 'winerror', None),
                           error=f'{type(error).__name__}: {error}',
                           elapsed_ms=round((self.write_clock()-started)*1000, 3))
            self.data.setdefault('write_failures', []).append(failure)
            raise StartupWriteError(failure) from error
        finally:
            if detail is not None and not committed:
                detail['recovered'] = False
                detail['attempts'] = replacements
            if temporary is not None and not committed:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as error:
                    self.data.setdefault('temporary_cleanup_errors', []).append(
                        dict(path=temporary.name, error=f'{type(error).__name__}: {error}'))

    def note(self, stage, *, waiting_for=None, **details):
        if stage in self.seen:
            return
        self.seen.add(stage)
        self.data['events'].append({'stage': stage, 'observed_s': round(self.clock() - self.started, 6), **details})
        if waiting_for is not None:
            self.data['waiting_for'] = waiting_for
        self.save()

    def finish(self, error=None, cancelled=False):
        self.data['status'] = 'cancelled' if cancelled else 'blocked' if error else 'ready'
        if error:
            self.data['error'] = error
        # Failure/cancellation diagnostics are attempted once, after owned cleanup.
        self.save(retry=not (error or cancelled), guarded=not (error or cancelled), first_guard=False)
