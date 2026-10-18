"""Lossless form round trip over a local ERT corpus (task 008, static acceptance).

For every unique ERT: ``form-extract`` to a description, then ``build --form``
with that unchanged description and a fixed small module, and compare the
built Dialog Stream with the original byte for byte. ``build`` itself verifies
the other streams and the directory metadata. Refusals are recorded with their
reason; nothing in the corpus is written.

    python -B research/forms/verify_corpus77.py .local/bases/base-for-test/ExtForms \
        --output .artifacts/forms/corpus-YYYYMMDD
"""

import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from harness77 import ert_module as ert  # noqa: E402
from harness77 import form77  # noqa: E402
from harness77.artifacts import build  # noqa: E402

MODULE = "Процедура Harness77Пусто()\r\nКонецПроцедуры\r\n"


def dialog_bytes(path):
    compound = ert.CompoundFile(Path(path).read_bytes())
    return compound.read_stream(form77.dialog_entry(compound))


def check(path, work):
    """One ERT: ("exact" | "refused" | "different", detail)."""
    description = work / "form.json"
    try:
        form77.extract(path, description)
    except (OSError, ValueError, ert.ErtError) as error:
        return "refused", "form-extract: " + str(error)
    try:
        build(path, work / "module.1s", work / "built.ert", form=description)
    except (OSError, ValueError, ert.ErtError) as error:
        return "refused", "build: " + str(error)
    same = dialog_bytes(path) == dialog_bytes(work / "built.ert")
    return ("exact", None) if same else ("different", "dialog bytes differ")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="new directory for result.json")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    files = sorted(p for p in args.corpus.rglob("*") if p.suffix.lower() == ".ert")
    seen, rows = {}, []
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    for path in files:
        digest = before[path]
        name = str(path.relative_to(args.corpus))
        if digest in seen:
            rows.append({"path": name, "sha256": digest, "outcome": "duplicate", "of": seen[digest]})
            continue
        seen[digest] = name
        with tempfile.TemporaryDirectory(prefix="harness77-corpus-") as temp:
            work = Path(temp)
            (work / "module.1s").write_text(MODULE, encoding="utf-8")
            outcome, detail = check(path, work)
        rows.append({"path": name, "sha256": digest, "outcome": outcome, "detail": detail})
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    counts = collections.Counter(row["outcome"] for row in rows)
    result = {"schema_version": 1, "scope": "task 008 lossless form round trip", "files": len(files),
              "counts": dict(counts), "corpus_unchanged": before == after,
              "module": MODULE, "rows": rows}
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("files", "counts", "corpus_unchanged")}, ensure_ascii=False))
    for row in rows:
        if row["outcome"] in ("refused", "different"):
            print(row["outcome"], row["path"], row["detail"])
    return 0 if not counts["different"] and result["corpus_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
