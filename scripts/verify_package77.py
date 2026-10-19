"""Build sdist/wheel and verify an installed distribution without sibling repos.

Requires the pinned build dependency and pip in --build-python. No network is
used. Results are kept in a new directory, including failures and command logs.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def verify(args):
    evidence = args.output.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    temporary = evidence / "temp"
    temporary.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(TEMP=str(temporary), TMP=str(temporary), PYTHONIOENCODING="utf-8",
               PYTHONNOUSERSITE="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    summary = {"schema_version": 1, "status": "running", "command_timeout_s": args.command_timeout_s,
               "commands": []}
    summary_file = evidence / "summary.json"

    def save():
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(name, command, cwd, expected=0):
        command = list(map(str, command))
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=args.command_timeout_s)
        (evidence / f"{name}.log").write_bytes(result.stdout + result.stderr)
        summary["commands"].append({"name": name, "command": command, "exit_code": result.returncode,
                                    "expected_exit_code": expected})
        save()
        if result.returncode != expected:
            raise RuntimeError(f"{name}: exit {result.returncode}, expected {expected}; see {name}.log")
        return result

    save()
    try:
        checkout = evidence / "source"
        checkout.mkdir()
        # Copy an explicit distribution set, never .local, databases or sibling repos.
        for name in ("pyproject.toml", "MANIFEST.in", "README.md", "requirements-build.txt"):
            shutil.copy2(ROOT / name, checkout / name)
        for name in ("src", "tests", "docs", "examples"):
            shutil.copytree(ROOT / name, checkout / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        (checkout / "scripts").mkdir()
        shutil.copy2(Path(__file__), checkout / "scripts/verify_package77.py")
        dist = evidence / "dist"
        dist.mkdir()
        run("build-sdist", [args.build_python, "-c",
            "import importlib.metadata as m; assert m.version('setuptools') == '80.9.0'; "
            "from setuptools.build_meta import build_sdist; import sys; build_sdist(sys.argv[1])", dist], checkout)
        sdist, = dist.glob("*.tar.gz")
        expanded = evidence / "sdist"
        expanded.mkdir()
        with tarfile.open(sdist) as archive:
            archive.extractall(expanded, filter="data")
        source, = expanded.iterdir()
        run("build-wheel-from-sdist", [args.build_python, "-c",
            "from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])", dist], source)
        wheel, = dist.glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            for resource in ("lint77-builtins.json", "lint77-globals.json", "catalog77.json"):
                assert "harness77/" + resource in names, resource
            assert all(n.startswith(("harness77/", "harness77-0.1.0.dist-info/")) for n in names)
        summary["distributions"] = [{"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                    for p in (sdist, wheel)]
        environment = evidence / "venv"
        run("create-venv", [args.runtime_python, "-m", "venv", "--without-pip", environment], evidence)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        console = environment / ("Scripts/harness77.exe" if os.name == "nt" else "bin/harness77")
        run("install", [args.build_python, "-m", "pip", "--python", python, "install",
                        "--no-index", "--no-deps", wheel], evidence)
        foreign = evidence / "чужой каталог"
        foreign.mkdir()
        run("installed-resource", [python, "-c",
            "import sys, pathlib, json, importlib.metadata as m; import harness77; "
            "from harness77.lint77 import load_builtins, load_catalog; "
            "assert pathlib.Path(harness77.__file__).is_relative_to(pathlib.Path(sys.prefix)); "
            "assert len(load_builtins()) > 10; "
            "assert len(load_catalog().reserved) == 162 and load_catalog().readable; "
            "assert [d.metadata['Name'] for d in m.distributions()] == ['harness77']; "
            "print(json.dumps({'python':sys.version,'module':harness77.__file__,'builtins':len(load_builtins())}))"], foreign)
        run("console-version", [console, "--version"], foreign)
        run("module-version", [python, "-m", "harness77", "--version"], foreign)
        cases = evidence / "cases"
        shutil.copytree(source / "tests", cases)
        result = run("installed-tests", [python, "-B", "-m", "unittest", "discover", "-s", cases, "-v"], foreign)
        log = result.stderr.decode("utf-8")
        count = re.search(r"Ran (\d+) tests", log)
        skipped = re.search(r"OK \(skipped=(\d+)\)", log)
        assert count and re.search(r"^OK(?: \(skipped=\d+\))?\r?$", log, re.M)
        summary["tests"] = {"total": int(count[1]), "skipped": int(skipped[1]) if skipped else 0}
        example = foreign / "пример.1s"
        shutil.copy2(source / "examples/hello.1s", example)
        result = run("console-lint", [console, "lint", example, "--format", "json"], foreign)
        assert json.loads(result.stdout)["errors"] == 0
        for case, expected in (("p1", 60), ("p2", 7)):
            result = run(f"console-{case}", [console, "compiler-protocol", cases / f"fixtures/compiler_protocol77/{case}.txt"], foreign, 1)
            report = json.loads(result.stdout)
            assert report["status"] == "failed" and len(report["diagnostics"]) == expected
        summary.update(status="passed", no_sibling_repositories=True, no_pythonpath=True,
                       runtime_dependencies=[], source=str(source), python=str(python))
    except Exception as exc:
        summary.update(status="blocked", error=str(exc))
        raise
    finally:
        save()
        print(summary_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/package77" / str(uuid.uuid4()))
    parser.add_argument("--build-python", default=sys.executable)
    parser.add_argument("--runtime-python", default=sys.executable)
    # Each command's limit; a loaded machine starts processes slowly and the installed tests spawn many.
    parser.add_argument("--command-timeout-s", type=int, default=300)
    verify(parser.parse_args())
