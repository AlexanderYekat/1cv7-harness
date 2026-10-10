"""Reproduce compiler-protocol77 acceptance using an isolated local checkout.

No network or application corpus is required. Logs go to an ignored directory;
optional original protocols are read only when --original-corpus is supplied.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(args, cwd, *, expected=0, env=None, log=None):
    result = subprocess.run(list(map(str, args)), cwd=cwd,
                            env=env or {**os.environ, "PYTHONIOENCODING": "utf-8"},
                            capture_output=True, timeout=60, shell=False)
    if log is not None:
        log.write_bytes(result.stdout + result.stderr)
    require(result.returncode == expected,
            f"Command {args!r}: expected exit {expected}, got {result.returncode}.\n"
            + result.stderr.decode("utf-8", errors="replace"))
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def test_summary(result):
    text = result.stderr.decode("utf-8")
    count = re.search(r"Ran ([0-9]+) tests? in", text)
    skipped = re.search(r"OK \(skipped=([0-9]+)\)", text)
    require(count is not None and re.search(r"^OK(?: \(skipped=[0-9]+\))?\r?$", text, re.M),
            "Missing successful unittest summary")
    total, skips = int(count[1]), int(skipped[1]) if skipped else 0
    return {"total": total, "passed": total - skips, "skipped": skips, "failures": 0, "errors": 0}


def short_windows_path(path):
    import ctypes
    get_short = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    get_short.restype = ctypes.c_uint32
    size = get_short(str(path), None, 0)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(size)
    written = get_short(str(path), buffer, size)
    if not written or written >= size:
        raise OSError("GetShortPathNameW could not return the short path")
    return buffer.value


def verify_originals(corpus, checkout, cases):
    if corpus is None:
        return {"status": "not_requested", "cases": []}
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    verified = []
    for case in cases:
        name = case["id"]
        original = corpus / f"{name}-compile-errors/compiler-protocol.txt"
        before = original.read_bytes()
        require(digest(before) == case["original_sha256"]
                == manifest[f"{name}-compile-errors"]["compiler-protocol.txt"],
                f"Original {name}: hash mismatch")
        result = run([sys.executable, "-B", checkout / "compiler_protocol77.py", original],
                     checkout.parent, expected=1)
        report = json.loads(result.stdout)
        require(result.stderr == b"" and report["status"] == "failed"
                and report["issues"] == [] and report["unparsed_lines"] == []
                and report["protocol_sha256"] == digest(before), f"Original {name}: invalid report")
        expected = json.loads((checkout / "tests/fixtures/compiler_protocol77" / case["expected_file"])
                              .read_text(encoding="utf-8"))
        normalized = [{**item, "file": "C:\\project\\" + item["file"].rsplit("\\", 1)[1]}
                      for item in report["diagnostics"]]
        require(normalized == expected["diagnostics"], f"Original {name}: diagnostics mismatch")
        require(original.read_bytes() == before, f"Original {name}: bytes changed")
        verified.append({"id": name, "sha256": digest(before),
                         "diagnostics": len(normalized), "unchanged": True})
    return {"status": "verified", "cases": verified}


def verify(args):
    repo = args.repo.resolve(strict=True)
    evidence = args.output_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    # A failed attempt must not leave an old summary looking like its result.
    summary_path = evidence / "summary.json"
    summary_path.write_text('{"status": "running"}\n', encoding="utf-8")
    revision = run(["git", "rev-parse", "--verify", "--end-of-options", args.revision + "^{commit}"],
                   repo).stdout.decode().strip()
    summary = {"status": "verified", "revision": revision, "os": platform.platform(),
               "python": sys.version, "checkout": {}, "negative_fixture_checks": []}
    with tempfile.TemporaryDirectory(prefix="compiler77-checkout-") as temporary:
        checkout_root = Path(temporary).resolve(strict=True)
        # Bound the disposable tree before TemporaryDirectory's recursive cleanup.
        checkout_root.relative_to(Path(tempfile.gettempdir()).resolve(strict=True))
        checkout = checkout_root / "devtools"
        run(["git", "clone", "--no-hardlinks", "--no-checkout", "-c", "core.autocrlf=true", repo, checkout],
            checkout_root)
        checkout.resolve(strict=True).relative_to(checkout_root)
        run(["git", "checkout", "--detach", revision], checkout)
        require(run(["git", "config", "--get", "core.autocrlf"], checkout).stdout.strip() == b"true",
                "core.autocrlf must be true in the temporary checkout")
        require(not (checkout_root / "research").exists(), "Unexpected application corpus")
        fixtures = checkout / "tests/fixtures/compiler_protocol77"
        cases = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))["cases"]
        hashes = {}
        for case in cases:
            actual = digest((fixtures / case["protocol_file"]).read_bytes())
            require(actual == case["sha256"], f"Checkout fixture {case['id']}: hash mismatch")
            hashes[case["id"]] = actual
        summary["checkout"] = {"core.autocrlf": True, "hashes": hashes, "no_application_corpus": True}
        test_command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", checkout / "tests"]
        for pattern, log in (("test_compiler_protocol77.py", "clean-parser-tests.log"),
                             ("test_lint77.py", "clean-linter-tests.log")):
            result = run([*test_command, "-p", pattern, "-v"], checkout_root, log=evidence / log)
            summary["checkout"][pattern] = test_summary(result)
        fixture = fixtures / "p2.txt"
        pristine = fixture.read_bytes()
        for scenario in ("missing_fixture", "wrong_hash"):
            try:
                if scenario == "missing_fixture":
                    fixture.unlink()
                else:
                    fixture.write_bytes(pristine + b"changed\n")
                result = run([*test_command, "-p", "test_compiler_protocol77.py", "-k", "test_e01_e02", "-v"],
                             checkout_root, expected=1, log=evidence / (scenario + ".log"))
                marker = b"FileNotFoundError" if scenario == "missing_fixture" else b"AssertionError"
                require(b"FAILED" in result.stderr and marker in result.stderr,
                        f"{scenario}: expected a fixture failure, not a skip or unrelated error")
                summary["negative_fixture_checks"].append({"scenario": scenario, "exit": 1,
                                                            "expected_failure": True})
            finally:
                fixture.write_bytes(pristine)
        summary["short_temp"] = {"status": "not_requested"}
        if args.short_temp:
            summary["short_temp"] = {"status": "unavailable", "reason": "Windows 8.3 alias required"}
            if os.name == "nt":
                long_temp = checkout_root / "temporary directory with spaces"
                long_temp.mkdir()
                short_temp = short_windows_path(long_temp)
                if os.path.normcase(short_temp) != os.path.normcase(str(long_temp)):
                    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "TEMP": short_temp,
                           "TMP": short_temp, "TMPDIR": short_temp}
                    observed = run([sys.executable, "-B", "-c", "import tempfile; print(tempfile.gettempdir())"],
                                   checkout_root, env=env).stdout.decode("utf-8").strip()
                    require(os.path.normcase(observed) == os.path.normcase(short_temp),
                            "Child did not use the short temporary path")
                    result = run([*test_command, "-p", "test_compiler_protocol77.py", "-v"],
                                 checkout_root, env=env, log=evidence / "short-temp-tests.log")
                    summary["short_temp"] = {"status": "verified", "tests": test_summary(result)}
        summary["originals"] = verify_originals(args.original_corpus, checkout, cases)
        require(run(["git", "status", "--porcelain"], checkout).stdout == b"", "Checkout changed")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repo", type=Path, default=ROOT / "1cv77-devtools")
    parser.add_argument("--revision", default="HEAD", help="Committed devtools revision (default: HEAD)")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".local/acceptance/compiler_protocol77")
    parser.add_argument("--original-corpus", type=Path, help="Optional local corpus with its original manifest")
    parser.add_argument("--short-temp", action="store_true", help="Also rerun parser tests using a Windows 8.3 TEMP")
    args = parser.parse_args(argv)
    if args.original_corpus is not None:
        args.original_corpus = args.original_corpus.resolve()
    try:
        summary = verify(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"compiler-protocol77 acceptance: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
