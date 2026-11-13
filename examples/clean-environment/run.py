"""Run and independently verify the offline kit in a clean installed venv."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new ASCII directory without spaces")
    args = parser.parse_args()
    output = args.output.resolve()
    if not str(output).isascii() or any(c in str(output) for c in '"; \r\n'):
        parser.error("output must be ASCII without spaces or debugger separators")
    if os.name != "nt":
        parser.error("this qualified native kit requires Windows")
    if sys.prefix == sys.base_prefix or os.environ.get("PYTHONPATH") or os.environ.get("PYTHONHOME"):
        parser.error("use a new venv without PYTHONPATH/PYTHONHOME")
    import harness77
    if not Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        parser.error("harness77 must be installed in this venv")
    if sorted(d.metadata["Name"] for d in metadata.distributions()) != ["harness77"]:
        parser.error("venv must contain only harness77 (create it with --without-pip)")
    kit = json.loads((HERE / "kit.json").read_text(encoding="utf-8"))
    for name, expected in kit["files"].items():
        if digest(HERE / name) != expected:
            raise ValueError("kit hash mismatch: " + name)
    output.mkdir(parents=True, exist_ok=False)
    # The working directory is outside the kit; all inputs come from profiles.
    foreign = output / "working"
    foreign.mkdir()
    sys.path[:0] = [str(HERE / "native/forms"), str(HERE / "native/platform77"), str(HERE / "verification")]
    from harness77 import basecopy77
    from harness77.config77 import load_stand
    from win32_session77 import base_titles_fingerprint, processes, read_tree
    from verify_document_form77 import check
    from verify_suite77 import verify
    com_keys = (
        r"Software\Classes\Harness77Diagnostic.ProxyIdentity",
        r"Software\Classes\CLSID\{7E477C71-018E-4C27-9E38-2D5DDA9F6A07}",
        r"Software\Classes\Harness77Diagnostic.ComCleanup",
        r"Software\Classes\CLSID\{16B8A521-07E4-46D1-A8E7-197BD1CE4477}",
    )
    stand = load_stand(HERE / "stand.toml")
    copy = stand.copy_path
    lock = basecopy77.lock_path(copy)
    guard = lock.with_name(lock.name + ".guard")

    def snapshot():
        return {"source": basecopy77.listing(stand.base), "titles": base_titles_fingerprint(),
                "com": [read_tree(key, 0x0200) for key in com_keys], "processes": processes()}

    before = snapshot()
    guard_before = guard.read_bytes() if guard.exists() else None
    evidence = {"status": "running", "environment": {"python": sys.executable, "prefix": sys.prefix,
                "module": harness77.__file__, "cwd": str(foreign), "pythonpath": os.environ.get("PYTHONPATH")},
                "kit_sha256": digest(HERE / "kit.json"), "suites": [], "runs": []}
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    env.update(PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    try:
        if before["processes"] or before["com"] != [None] * 4 or copy.exists() or lock.exists():
            raise RuntimeError("stand must be idle; copy and lock must be absent")
        for name, expected in (("suite", 0), ("suite-failure", 1)):
            result = subprocess.run([sys.executable, "-B", "-m", "harness77", "suite",
                "--suite", str(HERE / (name + ".toml")), "--stand", str(HERE / "stand.toml"),
                "--output-root", str(output / "results"), "--suite-id", name],
                cwd=foreign, env=env, capture_output=True, timeout=1500)
            (output / (name + ".log")).write_bytes(result.stdout + result.stderr)
            if result.returncode != expected:
                raise RuntimeError(f"{name}: exit {result.returncode}, expected {expected}; see log")
            folder = output / "results" / name
            summary = verify(folder, native=True)
            evidence["suites"].append(summary)
            if summary["issues"]:
                raise RuntimeError(str(summary["issues"]))
            report = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
            for row in report["scenarios"]:
                run = (folder / row["report"]["path"]).parent
                record = check(run, "wrong" if row["id"] == "wrong" else "success", row["report"]["sha256"])
                provenance = json.loads((run / "launcher-environment.json").read_text(encoding="utf-8"))
                if provenance["module"] != harness77.__file__ or provenance["prefix"] != sys.prefix:
                    raise RuntimeError("launcher used another Python environment")
                evidence["runs"].append(dict(record, launcher_environment=provenance))
                if record["issues"]:
                    raise RuntimeError(str(record["issues"]))
        evidence["status"] = "passed"
    except Exception as error:
        evidence.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        after = snapshot()
        # Remove only an idle guard created by these runs; preserve pre-existing state.
        if guard_before is None and not before["processes"] and not copy.exists() and not lock.exists() and not after["processes"]:
            if not evidence.get("error"):
                guard.unlink(missing_ok=True)
        evidence["cleanup"] = {key + "_unchanged": before[key] == after[key] for key in before}
        evidence["cleanup"].update(copy_removed=not copy.exists(), lock_removed=not lock.exists(),
                                  guard_restored=(guard.read_bytes() if guard.exists() else None) == guard_before)
        evidence["kit_unchanged"] = all(digest(HERE / n) == h for n, h in kit["files"].items())
        if not all(evidence["cleanup"].values()) or not evidence["kit_unchanged"]:
            evidence["status"] = "failed"
        (output / "verified.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output / "verified.json")
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
