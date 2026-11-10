"""Optional progress checkpoints for MCP runs, suites and native launchers."""

import json
import os
from pathlib import Path

MCP_PROGRESS_ENV = "HARNESS77_MCP_PROGRESS"
SUITE_PROGRESS_SUFFIX = ".suite-progress"


def publish_mcp_progress(phase):
    prefix = os.environ.get(MCP_PROGRESS_ENV)
    if prefix:
        path = Path(prefix)
        if path.suffix == SUITE_PROGRESS_SUFFIX:
            _append_suite_progress(path, {"phase": phase})
            return
        try:
            path.with_suffix("." + phase).touch()
        except (OSError, ValueError):
            pass  # A progress checkpoint must not affect the run.


def publish_suite_scenario(index, total, name):
    prefix = os.environ.get(MCP_PROGRESS_ENV)
    if prefix and (path := Path(prefix)).suffix == SUITE_PROGRESS_SUFFIX:
        _append_suite_progress(path, {"scenario": name, "index": index, "total": total})


def _append_suite_progress(path, event):
    # Suite scenarios are sequential. The native launcher finishes before the next scenario.
    try:
        with path.open("ab") as stream:
            stream.write(json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n")
    except (OSError, ValueError):
        pass


def read_suite_progress(path, offset):
    """Consume complete events in order, even if several arrived between polls."""
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read()
    except OSError:
        return offset, []
    complete, separator, _ = data.rpartition(b"\n")
    if not separator:
        return offset, []
    events = []
    for line in complete.split(b"\n"):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return offset + len(complete) + 1, events
