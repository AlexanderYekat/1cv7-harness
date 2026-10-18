"""Turn native probe evidence of task 009 into the portable fixture of tests/test_triage77.py.

Only the synthetic probe modules and what 1C 7.7 reported for them are exported:
line, message, column and source line of each diagnostic, with the run_id and the
SHA-256 of the native protocol as provenance. Machine paths are not exported; the
KUDiR corpus (P1n, P2n) stays local.

Usage:
  python research/protocol77/export_fixtures77.py --evidence .artifacts/protocol/probes-20261018.json
      --evidence .artifacts/protocol/probes-20261018-k14.json --output tests/fixtures/triage77/probes.json
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_cascade77 as probes  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    cases = {c["id"]: c for c in probes.CASES}
    exported = {}
    for path in args.evidence:
        for row in json.loads(path.read_text(encoding="utf-8"))["cases"]:
            if row["id"] not in cases:
                continue
            if row["verdict"] not in ("confirmed", "observed"):
                raise SystemExit(f"{row['id']}: verdict {row['verdict']}, not exported")
            diagnostics = []
            for pair in row["observed"]["diagnostics"]:
                item = {"line": pair["line"], "message": pair["message"]}
                if pair["source"] is not None and pair["source"].count("<<?>>") == 1:
                    item.update(column=pair["source"].index("<<?>>") + 1,
                                source_line=pair["source"].replace("<<?>>", "", 1))
                diagnostics.append(item)
            exported[row["id"]] = {"run_id": row["run_id"], "protocol_sha256": row["observed"]["protocol"]["sha256"],
                                   "module": probes.module_text(cases[row["id"]]), "diagnostics": diagnostics}
    fixture = {"schema_version": 1, "scope": "task 009 native probes on 1C 7.70.027 (base-for-test, FIO.ERT)",
               "source": "research/protocol77/probe_cascade77.py",
               "cases": dict(sorted(exported.items(), key=lambda item: int(item[0][1:])))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "x", encoding="utf-8", newline="\n") as stream:
        json.dump(fixture, stream, ensure_ascii=False, indent=1)
        stream.write("\n")
    print(f"{len(exported)} cases -> {args.output}")


if __name__ == "__main__":
    main()
