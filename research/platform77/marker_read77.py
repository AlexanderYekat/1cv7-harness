"""Bounded reads of already published native ERT markers."""
import errno
import time


class MarkerReadError(RuntimeError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(f"read {detail['path']} failed after {detail['attempts']} attempt(s): {detail['error']}")


def read_marker(path, retries, *, check, clock=time.monotonic, pause=time.sleep):
    """Retry access to the same file, with no publication or platform calls."""
    started = clock()
    for attempt in range(1, 27):
        check()
        try:
            return path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as error:
            elapsed = clock() - started
            detail = {"operation": "ert-marker-read", "path": str(path), "attempts": attempt,
                      "errno": getattr(error, "errno", None), "winerror": getattr(error, "winerror", None),
                      "error": f"{type(error).__name__}: {error}", "elapsed_ms": round(elapsed * 1000, 3)}
            remaining = 1 - elapsed
            access_error = isinstance(error, PermissionError) and (
                error.errno == errno.EACCES or detail["winerror"] in (5, 32, 33))
            if not access_error or attempt == 26 or remaining <= 0:
                raise MarkerReadError(detail) from error
            retries.append(detail)
            pause(min(0.04, remaining))
