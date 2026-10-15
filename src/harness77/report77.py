"""Overall machine report: file evidence, stage results and atomic publication.

Large application reports and logs stay in files inside the run directory; the
report records their path, size, SHA-256 and completeness, never a second full
copy of their contents. A missing, empty or partial result is recorded as such
and never counts as success.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = 1
TOOL = "harness77"
# Statuses for a single stage.
PASSED, FAILED, BLOCKED, SKIPPED = "passed", "failed", "blocked", "skipped"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    """Serialize fully before touching the final file; never a partial report."""
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = Path(path).with_name(Path(path).name + ".tmp")
    temporary.write_text(data, encoding="utf-8")
    temporary.replace(path)


def file_evidence(path, *, root=None, complete=None, expected_sha256=None):
    """Describe a result file by relation to the run directory, size and hash.

    ``complete`` is the producer's own claim about whether it finished writing;
    it is reported verbatim and separately from existence. A file that is absent
    or that fails an expected-hash check is reported with ``complete=False``.
    """
    path = Path(path)
    record = {"name": path.name, "complete": bool(complete) if complete is not None else None}
    if root is not None:
        try:
            record["path"] = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            record["path"] = str(path)
    try:
        data = path.read_bytes()
    except OSError as error:
        record.update(exists=False, size_bytes=0, sha256=None, complete=False,
                      error=f"{type(error).__name__}: {error}")
        return record
    record.update(exists=True, size_bytes=len(data), sha256=sha256_bytes(data))
    if expected_sha256 is not None:
        record["sha256_matches"] = record["sha256"] == expected_sha256
        if not record["sha256_matches"]:
            record["complete"] = False
    return record


class Stage:
    """One pipeline stage: identity, requiredness, status, evidence and reason."""

    def __init__(self, stage_id, *, required, status=BLOCKED, scope=""):
        self.stage_id = stage_id
        self.required = required
        self.status = status
        self.scope = scope
        self.started_s = None
        self.ended_s = None
        self.diagnostics = []
        self.evidence = []
        self.reason = None
        self.details = {}

    def finish(self, status, *, reason=None, diagnostics=None, evidence=None, **details):
        self.status = status
        if reason is not None:
            self.reason = reason
        if diagnostics is not None:
            self.diagnostics = diagnostics
        if evidence is not None:
            self.evidence = evidence
        self.details.update(details)
        return self

    def as_dict(self):
        return {"stage": self.stage_id, "required": self.required, "status": self.status,
                "scope": self.scope, "reason": self.reason,
                "duration_s": None if self.started_s is None or self.ended_s is None
                else round(self.ended_s - self.started_s, 3),
                "diagnostics": self.diagnostics, "evidence": self.evidence, **self.details}


# Final run exit codes, aligned with the existing per-operation contracts and §8.3.
EXIT_PASSED = 0        # all required stages passed (incl. a verified expected-negative)
EXIT_CHECKED_FAIL = 1  # a confirmed defect in the checked code or a failed test
EXIT_BLOCKED = 2       # input/infrastructure error or an incomplete required result


def exit_code(status):
    return {PASSED: EXIT_PASSED, FAILED: EXIT_CHECKED_FAIL, BLOCKED: EXIT_BLOCKED,
            SKIPPED: EXIT_BLOCKED}[status]
