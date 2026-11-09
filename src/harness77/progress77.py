"""Optional progress checkpoints for an MCP run and its native launcher."""

import os
from pathlib import Path

MCP_PROGRESS_ENV = "HARNESS77_MCP_PROGRESS"


def publish_mcp_progress(phase):
    prefix = os.environ.get(MCP_PROGRESS_ENV)
    if prefix:
        try:
            Path(prefix).with_suffix("." + phase).touch()
        except (OSError, ValueError):
            pass  # A progress checkpoint must not affect the run.
