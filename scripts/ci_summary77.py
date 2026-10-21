"""Markdown summary of `unittest -v` logs for the CI job page (task 016).

Prints the result line, every skipped test with its reason and every failed
test, so a run that is green only by skipping shows it. Always exits 0: the
test step itself decides the job's status.
"""

import locale
import re
import sys
from pathlib import Path


TEST = re.compile(r"^(\w+) \(([\w.]+)\)")
SKIPPED = re.compile(r"\.\.\. skipped (['\"])(.*)\1\s*$")
PROBLEM = re.compile(r"^(FAIL|ERROR): (\w+) \(([\w.]+)\)")
RESULT = re.compile(r"^(?:OK|FAILED)(?: \(.*\))?\s*$")
RAN = re.compile(r"^Ran (\d+) tests? in ")


def summarize(path):
    path = Path(path)
    if not path.is_file():
        return [f"### {path.name}", "", "No log: the step did not run.", ""]
    ran = result = current = None
    skipped, problems = [], []
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:  # A Windows console pipe writes the ANSI code page.
        text = data.decode(locale.getpreferredencoding(False), errors="replace")
    for line in text.splitlines():
        if match := TEST.match(line):
            current = match[2]
        if (match := SKIPPED.search(line)) and current:
            reason = match[2] if len(match[2]) <= 200 else match[2][:200] + "…"
            skipped.append(f"- `{current}`: {reason}")
        if match := PROBLEM.match(line):
            problems.append(f"- {match[1]}: `{match[3]}`")
        if match := RAN.match(line):
            ran = match[1]
        elif RESULT.match(line):
            result = line.strip()
    lines = [f"### {path.name}", "", f"Ran {ran or '?'} tests: {result or 'no result line'}", ""]
    if problems:
        lines += [f"Failed ({len(problems)}):", "", *dict.fromkeys(problems), ""]
    lines += [f"Skipped ({len(skipped)}):", "", *(skipped or ["- none"]), ""]
    return lines


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # The job summary file is UTF-8 Markdown.
    for name in sys.argv[1:]:
        print("\n".join(summarize(name)))
