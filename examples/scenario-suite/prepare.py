"""Prepare a suite of examples 025–028 for the pinned stand; does not start 1C."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
EXAMPLES = ("form-steps", "modal-dialogs", "table-part", "reference-choice")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    stand = args.stand.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in EXAMPLES:
        subprocess.run([sys.executable, str(HERE.parent / name / "prepare.py"),
                        "--stand", str(stand), "--output", str(output / name)], check=True,
                       stdout=subprocess.PIPE)
    lines = ['schema_version = 1', '', '[suite]', 'id = "forms-025-028"']
    for name in EXAMPLES:
        lines.extend(['', '[[scenarios]]', f'id = "{name}"', f'project = "{name}/project.toml"'])
    (output / "suite.toml").write_text('\n'.join(lines) + '\n', encoding="utf-8")
    print(json.dumps({"suite": str(output / "suite.toml"),
                      "stand": str(output / EXAMPLES[0] / "stand.toml")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
