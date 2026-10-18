"""Hash snapshot for task 006: the KUDiR project's packages and the base's files.

  python research/kudir/snapshot_state77.py --kudir <KUDiR project> --base <base dir> --output <new json>

Taken before and after the native runs: the runs write packages only into their
own run directories, so every KUDIR4_* package of the project must be byte-identical
afterwards. Base files are listed for information: 1C itself may touch service files.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def snapshot(kudir, base):
    packages = {d.name: {f.name: digest(f) for f in sorted(d.iterdir()) if f.is_file()}
                for d in sorted((kudir / "exchange").glob("KUDIR4_*")) if d.is_dir()}
    files = {f.name: {"sha256": digest(f), "size": f.stat().st_size,
                      "modified": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
             for f in sorted(base.iterdir()) if f.is_file()}
    return {"taken": datetime.datetime.now().astimezone().isoformat(), "packages": packages, "base_files": files}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kudir", required=True, type=Path)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.path.lexists(args.output):
        parser.error(f"output exists: {args.output}")
    data = snapshot(args.kudir, args.base)
    with open(args.output, "x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=1)
    print(len(data["packages"]), "packages,", len(data["base_files"]), "base files")


if __name__ == "__main__":
    main()
