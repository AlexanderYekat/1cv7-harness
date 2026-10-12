"""Prepare a separate source candidate; never build, install, or start 1C."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil


ARCHIVE_SHA256 = "b43f0dad2803c2dd9aefaf175da368659b8d2ced732eca90a02a24bc7bfbeeb4"
OLD = b"\tif (hLibBasic != NULL)\r\n\t\tFreeLibrary(hLibBasic);\r\n"
NEW = (b"\t// GetModuleHandle returns a borrowed handle, without a loader reference.\r\n"
       b"\t// BASIC.dll lifetime belongs to the host and the import loader.\r\n")


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = root / "third_party/sources/1cpp-2.5.0.7"
    inventory_path = root / "third_party/inventories/1cpp-2.5.0.7.json"
    manifest = json.loads((root / "third_party/manifest.json").read_text(encoding="utf-8"))
    package = next(p for p in manifest["packages"] if p["id"] == "1cpp-2.5.0.7")
    inventory_bytes = inventory_path.read_bytes()
    if hashlib.sha256(inventory_bytes).hexdigest() != package["inventory_sha256"]:
        parser.error("upstream inventory changed")
    inventory = json.loads(inventory_bytes)
    if inventory["archive_sha256"] != ARCHIVE_SHA256:
        parser.error("unexpected upstream snapshot")
    out = args.output.resolve()
    # Candidates live in a dedicated build tree, never in an infobase or snapshot.
    build_root = (root / ".local/builds").resolve()
    if (not build_root.is_relative_to(root) or not out.is_relative_to(build_root)
            or out == build_root or out.exists()):
        parser.error("output must be a new directory below .local/builds")
    expected_files = {entry["path"] for entry in inventory["files"]}
    actual_files = {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}
    if actual_files != expected_files:
        parser.error("upstream snapshot has missing or unexpected files")
    for entry in inventory["files"]:
        path = source / entry["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            parser.error(f"unexpected source link: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            parser.error(f"upstream file changed: {path}")
    cpp = source / "Source/ADDIN.CPP"
    original = cpp.read_bytes()
    if original.count(OLD) != 1:
        parser.error("expected exactly one borrowed-handle release")
    patched = original.replace(OLD, NEW, 1)
    patch_path = Path(__file__).resolve().parent / "patches/1cpp-2.5.0.7-borrowed-basic.patch"
    generated = "".join(difflib.unified_diff(
        original.decode("cp1251").splitlines(keepends=True),
        patched.decode("cp1251").splitlines(keepends=True),
        fromfile="a/Source/ADDIN.CPP", tofile="b/Source/ADDIN.CPP", n=1,
    )).replace("\r\n", "\n")
    if generated != patch_path.read_text(encoding="ascii"):
        parser.error("recorded patch does not match candidate transformation")
    shutil.copytree(source, out)
    (out / "Source/ADDIN.CPP").write_bytes(patched)
    record = {
        "status": "source_candidate_not_built_or_installed",
        "upstream_archive_sha256": ARCHIVE_SHA256,
        "changed_file": "Source/ADDIN.CPP",
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "candidate_sha256": hashlib.sha256(patched).hexdigest(),
        "patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(),
        "text_encoding": "cp1251", "line_endings": "CRLF",
    }
    (out / "harness77-candidate.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
