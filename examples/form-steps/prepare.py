"""Prepare the task 025 example for the pinned 7.70.027 stand; does not start 1C.

Usage: python examples/form-steps/prepare.py --stand .local/stage21-native/stand.toml
           --output .local/stage25-example
Then run the emitted project.toml and stand.toml with harness77 run. The scenario is
scenario.toml as written; this script adds the machine part of the profile only.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# The run's ERT is required by [build]; the scenario opens a form of the configuration instead.
TEMPLATE = ROOT / ".local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT"
SOURCE = ROOT / "research/forms/probe_module77.1s"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new directory for the example")
    args = parser.parse_args()
    stand_path = args.stand.resolve(strict=True)
    source = stand_path.read_text(encoding="utf-8")
    raw = tomllib.loads(source)["stand"]
    if not raw["base"].get("copy_path"):
        parser.error("the stand needs the registered copy_path (task 021)")
    paths = [raw.get("launcher"), *raw.get("paths", {}).values(), raw["base"].get("path"), raw["base"].get("copy_path")]
    if any(value and not Path(value).is_absolute() for value in paths):
        parser.error("this example requires absolute paths in the stand profile")
    scenario = (HERE / "scenario.toml").read_text(encoding="utf-8")
    tomllib.loads(scenario)  # the scenario is a valid TOML document on its own
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "configuration").mkdir()  # nothing changed: the base's own forms and modules
    header = "\n".join([
        "schema_version = 1", "", "[project]", 'id = "example-form-steps"', "", "[build]",
        f"template = {json.dumps(TEMPLATE.as_posix())}", f"source = {json.dumps(SOURCE.as_posix())}",
        'encoding = "utf-8"', "", "[configuration]", f"modules = {json.dumps((output / 'configuration').as_posix())}",
        "", "[deadlines]", "open_timeout_s = 120", "calculation_timeout_s = 120", "cancel_timeout_s = 15",
        "shutdown_timeout_s = 30", "total_timeout_s = 600", "", ""])
    (output / "project.toml").write_text(header + scenario, encoding="utf-8")
    source, count = re.subn(r"(?m)^launcher = .*$", "launcher = " + json.dumps(
        (ROOT / "research/forms/form_launcher77.py").as_posix()), source)
    if count != 1:
        parser.error("stand must contain one launcher line")
    (output / "stand.toml").write_text(source, encoding="utf-8")
    print(json.dumps({"project": str(output / "project.toml"), "stand": str(output / "stand.toml")}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
