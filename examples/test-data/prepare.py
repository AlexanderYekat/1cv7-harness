"""Prepare the task 024 example for the pinned 7.70.027 stand; does not start 1C.

Usage: python examples/test-data/prepare.py --stand .local/stage21-native/stand.toml
           --output .local/stage24-example
Then run the emitted project.toml and stand.toml with harness77 run.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research/forms"))
import probe_test_data77 as probes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stand", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new directory for the example")
    args = parser.parse_args()
    stand_path = args.stand.resolve(strict=True)
    stand = probes.base.load_stand(stand_path)
    if not stand.copy_path:
        parser.error("the stand needs the registered copy_path (task 021)")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    probes.base.md77.extract(Path(stand.base) / "1Cv7.MD", output / "extraction")
    case = copy.deepcopy(next(c for c in probes.CASES if c["id"] == "example"))
    case["parameters"]["fixture_setup"] = (HERE / "setup.1s").read_text(encoding="utf-8")
    case["parameters"]["fixture_verify"] = (HERE / "verify.1s").read_text(encoding="utf-8")
    project = probes.base.prepare(case, output / "extraction", output)
    # A copied profile must keep relative paths relative to its original directory.
    # This example uses the pinned stand whose paths are absolute; refuse accidental relocation.
    import tomllib
    source = stand_path.read_text(encoding="utf-8")
    raw = tomllib.loads(source)["stand"]
    paths = [raw.get("launcher"), *raw.get("paths", {}).values(),
             raw["base"].get("path"), raw["base"].get("copy_path")]
    if any(value and not Path(value).is_absolute() for value in paths):
        parser.error("this example requires absolute paths in the stand profile")
    source, count = re.subn(r"(?m)^launcher = .*$", "launcher = " + json.dumps(
        (ROOT / "research/forms/form_launcher77.py").as_posix()), source)
    if count != 1:
        parser.error("stand must contain one launcher line")
    (output / "stand.toml").write_text(source, encoding="utf-8")
    print(json.dumps({"project": str(project), "stand": str(output / "stand.toml")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
