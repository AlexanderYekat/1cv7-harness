"""Qualify the created ERT through run, CLI suite and stdio MCP."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples/application-suite"))
from mcp_client import Client


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(folder, status):
    report, platform = read(folder / "run.json"), read(folder / "platform-result.json")
    assert report["status"] == status and report["platform_checked"], report
    assert not platform["shutdown"]["forced_cleanup"]
    opened = next(o for o in platform["operations"] if o["name"] == "open")
    assert opened["form"]["units"]["consistent"]
    assert opened["form"]["units"]["max_residual_px"] <= 2
    window = read(folder / "form/form-window.json")
    steps = window["steps"]
    probes = [s for s in steps if s["kind"] == "inspect_combo"]
    assert len(probes) == (1 if status == "failed" else 2)
    snapshots = []
    for step in probes:
        ref = step["inspection_file"]
        path = folder / ref["path"]
        assert digest(path) == ref["sha256"] and path.stat().st_size == ref["size"]
        snap = read(path)
        assert snap["items"] == ["Первый", "Второй", "", "Второй"]
        assert snap["read_only_verified"]
        assert snap["selected_index"] == (0 if len(snapshots) == 0 else 2)
        snapshots.append(snap)
    if status == "failed":
        assert steps[-1]["kind"] == "message" and steps[-1]["status"] == "failed"
    else:
        assert all(s["status"] == "passed" for s in steps)
        selections = [s["action"] for s in steps if s["kind"] == "select"]
        assert selections[0]["unchanged"] and not selections[0]["notification_sent"]
        assert selections[1]["notification_sent"] and selections[1]["selection_verified"]
    return {"folder": str(folder), "status": status, "snapshots": len(snapshots)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--stand", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    project, stand = args.project.resolve(), args.stand.resolve()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    from harness77 import basecopy77
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    spec = importlib.util.spec_from_file_location("audit107", ROOT / "examples/structured-checks/run.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    base = tomllib.loads(stand.read_text(encoding="utf-8-sig"))["stand"]["base"]
    def snapshot():
        return {"listing": basecopy77.listing(Path(base["path"])),
                "registry": {key: helper.registry_tree(key) for key in (TITLES, *COM_KEYS)},
                "processes": WindowsInspector().processes(),
                "copy": Path(base["copy_path"]).exists(),
                "lock": basecopy77.lock_path(Path(base["copy_path"])).exists()}
    before = snapshot()
    assert not before["copy"] and not before["lock"]
    source = project.with_name("module.1s")
    original = source.read_bytes()
    # Only the handler's counter increment changes. All expectations stay literal.
    bad = original.replace(b' + 1;', b' + 2;', 1)
    assert bad != original
    profiles = []
    for phase in ("baseline", "regression", "fixed", "repeat-fixed"):
        folder = out / phase
        folder.mkdir()
        (folder / "configuration").mkdir()
        for name in ("form.json", "steps.json"):
            (folder / name).write_bytes(project.with_name(name).read_bytes())
        (folder / "module.1s").write_bytes(bad if phase == "regression" else original)
        (folder / "project.toml").write_bytes(project.read_bytes())
        profiles.append(folder / "project.toml")
    expected = ["passed", "failed", "passed", "passed"]
    results = []
    def execute(arguments, label, code):
        r = subprocess.run([sys.executable, "-B", "-m", "harness77", *map(str, arguments)],
                           cwd=ROOT, env=env, capture_output=True, timeout=1800)
        (out / (label + ".stdout.json")).write_bytes(r.stdout)
        (out / (label + ".stderr.log")).write_bytes(r.stderr)
        assert r.returncode == code, r.stdout.decode("utf-8")
        return json.loads(r.stdout)
    for index, (profile, status) in enumerate(zip(profiles, expected)):
        summary = execute(["run", "--project", profile, "--stand", stand,
                           "--output-root", out / "runs"], f"run-{index}", int(status == "failed"))
        results.append(audit(Path(summary["run_dir"]), status))
        assert snapshot() == before
        print("run", index, status, flush=True)
    suite = out / "suite.toml"
    suite.write_text('schema_version=1\n[suite]\nid="combo107"\n' + ''.join(
        '\n[[scenarios]]\nid=' + json.dumps(p.parent.name) + '\nproject=' + json.dumps(p.as_posix()) + '\n'
        for p in profiles), encoding="utf-8")
    for transport in ("cli", "mcp"):
        if transport == "cli":
            summary = execute(["suite", "--suite", suite, "--stand", stand,
                               "--output-root", out / "cli-suite"], "suite-cli", 1)
        else:
            client = Client(ROOT, out / "mcp-traffic.json", env)
            try:
                response, progress = client.suite({"suite": str(suite), "stand": str(stand),
                    "suite_id": "combo107", "output_root": str(out / "mcp-suite")})
                assert progress["ping_during"] and progress["ping_after"]
                summary = response["structuredContent"]["stdout"]
            finally:
                assert client.close() == 0
        folder = Path(summary["suite_dir"])
        data = read(folder / "suite.json")
        assert data["complete"] and data["status"] == "failed"
        cases = ET.parse(folder / "junit.xml").getroot().findall("testsuite/testcase")
        assert len(cases) == 4
        assert [bool(c.find("failure") is not None) for c in cases] == [False, True, False, False]
        for row, status in zip(data["scenarios"], expected):
            report = folder / row["report"]["path"]
            assert digest(report) == row["report"]["sha256"]
            results.append(audit(report.parent, status))
        assert snapshot() == before
        print(transport, "suite verified", flush=True)
    (out / "verified.json").write_text(json.dumps({"status": "passed", "runs": results,
        "stand_preserved": snapshot() == before, "inputs": {n: digest(project.with_name(n))
        for n in ("form.json", "steps.json", "module.1s")}}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
