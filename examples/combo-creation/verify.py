"""Independently reread the twelve reports and the created ERT containers."""
import argparse
import hashlib
import json
from pathlib import Path
from harness77 import ert_module as ert, form77
from harness77.lint77 import cfb_paths


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(cycle, template):
    evidence = read(cycle / "verified.json")
    assert evidence["status"] == "passed" and evidence["stand_preserved"]
    rows = evidence["runs"]
    assert len(rows) == 12
    assert [r["status"] for r in rows] == ["passed", "failed", "passed", "passed"] * 3
    original = ert.CompoundFile(template.read_bytes())
    paths = cfb_paths(original)
    original_records = form77._structure(ert.extract_dialog(template))[2][1:]
    snapshots, geometry, checked = [], [], []
    for index, row in enumerate(rows):
        folder = Path(row["folder"])
        report = read(folder / "run.json")
        assert report["status"] == row["status"] and report["platform_checked"]
        platform = read(folder / "platform-result.json")
        opened = next(o for o in platform["operations"] if o["name"] == "open")
        units = opened["form"]["units"]
        assert units["consistent"] and units["tolerance_px"] == 2 and units["max_residual_px"] <= 2
        geometry.append(units["max_residual_px"])
        built, = (folder / "build").glob("*.ert")
        rebuilt = ert.CompoundFile(built.read_bytes())
        assert cfb_paths(rebuilt) == paths
        preserved = 0
        for old, new in zip(original.directory_entries, rebuilt.directory_entries):
            end = 116 if old.object_type in (2, 5) else 128
            assert old.raw[:end] == new.raw[:end]
            if old.object_type == 2 and paths[old.entry_id] not in (ert.MODULE_STREAM, ert.DIALOG_STREAM):
                assert original.read_stream(old) == rebuilt.read_stream(new)
                preserved += 1
        records = form77._structure(ert.extract_dialog(built))[2][1:]
        assert records[:-1] == original_records
        assert records[-1][form77.CLASS] == "COMBOBOX"
        current = []
        for step in read(folder / "form/form-window.json")["steps"]:
            if step["kind"] != "inspect_combo":
                continue
            ref = step["inspection_file"]
            path = folder / ref["path"]
            assert digest(path) == ref["sha256"] and path.stat().st_size == ref["size"] and ref["complete"]
            # Also require the report's ordinary exported-file evidence.
            exported, = [f for f in report["result_files"] if f.get("path") == ref["path"]]
            assert exported["sha256"] == ref["sha256"] and exported["sha256_matches"]
            snap = read(path)
            assert snap["items"] == ["Первый", "Второй", "", "Второй"]
            assert snap["read_only_verified"] and snap["visible"] and snap["enabled"]
            assert snap["selected_index"] == (0 if not current else 2)
            current.append(snap)
        assert len(current) == (1 if row["status"] == "failed" else 2)
        if index >= 4:
            assert current == snapshots[index % 4]
        snapshots.append(current)
        checked.append({"folder": str(folder), "preserved_streams": preserved,
                        "run_json_sha256": digest(folder / "run.json")})
    for phase in ("regression", "fixed", "repeat-fixed"):
        for name in ("form.json", "steps.json"):
            assert (cycle / phase / name).read_bytes() == (cycle / "baseline" / name).read_bytes()
    assert (cycle / "baseline/module.1s").read_bytes() == (cycle / "fixed/module.1s").read_bytes()
    assert (cycle / "fixed/module.1s").read_bytes() == (cycle / "repeat-fixed/module.1s").read_bytes()
    result = {"status": "passed", "runs": checked, "snapshot_count": sum(map(len, snapshots)),
              "snapshots_match_transports": True, "max_geometry_residual_px": max(geometry),
              "literal_expectations_preserved": True}
    (cycle / "independent.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "runs"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    args = parser.parse_args()
    verify(args.cycle.resolve(), args.template.resolve())
