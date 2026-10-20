"""Lossless form round trip over a local ERT corpus (tasks 008, 011–013; static acceptance).

For every unique ERT: ``form-extract`` to a description, then ``build --form``
with that unchanged description and a fixed small module, and compare the
built Dialog Stream with the original byte for byte. ``build`` itself verifies
the other streams and the directory metadata. Refusals are recorded with their
reason; nothing in the corpus is written. Kinds of reference fields are named
by the ERT's own copy of the metadata. With ``--metadata`` both steps take that
1Cv7.MD as the target base (task 013): ``form-extract`` reports the kinds it
lacks by name, and the build refuses a form with such a kind.

    python -B research/forms/verify_corpus77.py .local/bases/base-for-test/ExtForms \
        [--metadata .local/bases/base-for-test/1Cv7.MD] --output .artifacts/forms/corpus-YYYYMMDD
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


def check(path, work, metadata=None):
    """One ERT: ("exact" | "refused" | "different", detail, reference counts)."""
    description = work / "form.json"
    try:
        report = form77.extract(path, description, metadata)
    except (OSError, ValueError, ert.ErtError) as error:
        return "refused", "form-extract: " + str(error), None
    types = [c.get("type", {}) for c in form77.loads(description.read_bytes())["controls"]]
    references = {"named": sum(1 for t in types if "object" in t), "by_number": report["references_by_number"],
                  "kinds": len(report["kinds"]), "missing": report.get("missing_in_metadata", []),
                  "other_number": sum(1 for k in report["kinds"]
                                      if k.get("target_object_id") not in (None, k["object_id"]))}
    try:
        build(path, work / "module.1s", work / "built.ert", form=description, metadata=metadata)
    except (OSError, ValueError, ert.ErtError) as error:
        return "refused", "build: " + str(error), references
    same = dialog_bytes(path) == dialog_bytes(work / "built.ert")
    return ("exact", None, references) if same else ("different", "dialog bytes differ", references)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="new directory for result.json")
    parser.add_argument("--metadata", type=Path, help="1Cv7.MD naming the kinds of reference fields")
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
            outcome, detail, references = check(path, work, args.metadata)
        rows.append({"path": name, "sha256": digest, "outcome": outcome, "detail": detail,
                     "references": references})
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    counts = collections.Counter(row["outcome"] for row in rows)
    references = [row["references"] for row in rows if row.get("references")]
    result = {"schema_version": 1, "scope": "tasks 008, 011–013: lossless form round trip",
              "description_schema_version": form77.SCHEMA_VERSION, "files": len(files),
              "counts": dict(counts), "corpus_unchanged": before == after,
              "metadata": ({"path": str(args.metadata.resolve()),
                            "sha256": hashlib.sha256(args.metadata.read_bytes()).hexdigest()}
                           if args.metadata else None),
              "references": {"named": sum(r["named"] for r in references),
                             "by_number": sum(len(r["by_number"]) for r in references),
                             "kinds": sum(r["kinds"] for r in references),
                             "missing": sum(len(r["missing"]) for r in references),
                             "other_number": sum(r["other_number"] for r in references),
                             "forms_missing": sum(1 for r in references if r["missing"])},
              "module": MODULE, "rows": rows}
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("files", "counts", "corpus_unchanged", "references")},
                     ensure_ascii=False))
    for row in rows:
        if row["outcome"] in ("refused", "different"):
            print(row["outcome"], row["path"], row["detail"])
    return 0 if not counts["different"] and result["corpus_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
