"""Synthetic ERT construction and strict evidence checks; no native launch."""
import json
import math
from pathlib import Path
import re
import sys
import uuid

from module_suite77 import vb_assignment, vb_literal
from shutdown77 import atomic_json, prepare_shutdown, sha256

ROOT = Path(__file__).resolve().parents[2]
# The package's copy of the devtools reader (same code), so a plain checkout is enough.
sys.path.insert(0, str(ROOT / "src"))
from harness77 import ert_module as ert

TEMPLATE_SHA = "096e1a05f871158b9ec5adaafa397adca87cee4aae8cd6f28f130080ac318b4a"
CASES = ("ok", "syntax", "unused-syntax", "unused-name", "runtime", "wait")
PROTOCOL_DIRECTORY = "Протоколы проверки"


def protocol_path(out, manifest, command):
    paths = manifest.get("protocol_paths")
    if paths is None:
        return out / (command + ".txt")  # Historical evidence remains readable.
    expected = {name: PROTOCOL_DIRECTORY + "/" + name + ".txt" for name in manifest["commands"]}
    if paths != expected or command not in paths:
        raise ValueError("unexpected protocol path mapping")
    return out / paths[command]


def prepare(out, template, case, *, concurrent=False):
    if case not in CASES:
        raise ValueError("unknown ERT case")
    if sha256(template) != TEMPLATE_SHA:
        raise ValueError("unverified ERT layout template")
    run_id = str(uuid.uuid4())
    identity = run_id + ":" + case
    source = Path(__file__).with_name("ert_fixture77.1s").read_text(encoding="utf-8")
    source = source.replace("__IDENTITY__", identity).replace("__ARGUMENT__", "0" if case == "runtime" else "22")
    if case == "syntax":
        source = source.replace("Возврат А + Б;", "Возврат А + ;")
    if case == "unused-syntax":
        source = source.replace("Локальное77 = 1;", "Локальное77 = ;")
    if case == "unused-name":
        source = source.replace("Локальное77 = 1;", "Harness77UndefinedProcedure();")
    if case == "runtime":
        source = source.replace("Возврат А + Б;", "Возврат А / Б;")
    source = ert.normalize_newlines(source)
    data = template.read_bytes()
    original = ert.CompoundFile(data)
    module = original.find_stream(ert.MODULE_STREAM)
    replacement = ert.compress_module(source.encode("cp1251"))
    rebuilt = original.rebuild({module.entry_id: replacement})
    checked = ert.CompoundFile(rebuilt)
    streams = []
    for entry in original.directory_entries:
        if entry.object_type != 2:
            continue
        before = original.read_stream(entry)
        after = checked.read_stream(checked.find_stream(entry.name))
        if after != (replacement if entry.entry_id == module.entry_id else before):
            raise ValueError("unexpected container change: " + entry.name)
        streams.append({"name": entry.name, "changed": before != after})
    # Keep original dialog bytes, including length and formulas. No form edits.
    ert.decode_dialog(checked.read_stream(checked.find_stream(ert.DIALOG_STREAM)))
    folder = out / "Тестовые обработки"
    folder.mkdir()
    target = folder / ("Проверка " + case + ".ert")
    target.write_bytes(rebuilt)
    if ert.extract_text(target) != source:
        raise ValueError("module round trip failed")
    (out / "fixture.1s").write_text(source, encoding="utf-8", newline="")
    controller = Path(__file__).with_name("ert_controller77.1s").read_text(encoding="utf-8")
    (out / "ert-controller.1s").write_text(controller, encoding="utf-8")
    commands = ["check", "wait"] if case == "wait" else ["check", "execute"]
    protocol_root = out / PROTOCOL_DIRECTORY
    protocol_root.mkdir()
    client = Path(__file__).with_suffix(".vbs").read_text(encoding="utf-8")
    client = client.replace("__PROXY_IDENTITY__", Path(__file__).with_name("proxy_identity77.vbs").read_text(encoding="utf-8") if concurrent else "")
    suite_template = Path(__file__).with_name("module_suite77.vbs").read_text(encoding="utf-8")
    utilities = suite_template[suite_template.index("Function Quote"):suite_template.index("Sub CompileCase")]
    shutdown, shutdown_manifest = prepare_shutdown(out, run_id)
    for key, value in {"RUN_ID": vb_literal(run_id), "ERT_PATH": vb_literal(str(target)),
        "IDENTITY": vb_literal(identity), "SOURCES": vb_assignment("sourceController", controller),
        "UTILITIES": utilities, "COMMANDS": ", ".join(vb_literal(c) for c in commands), "SHUTDOWN": shutdown}.items():
        client = client.replace("__" + key + "__", value)
    client = client.replace("__PROTOCOL_ROOT__", vb_literal(str(protocol_root)))
    (out / "client.vbs").write_text(client, encoding="utf-16")
    shutdown_manifest["sources"]["client.vbs"] = sha256(out / "client.vbs")
    manifest = {"schema_version": 1, "run_id": run_id, "identity": identity, "case": case,
        "commands": commands, "protocol_paths": {c: PROTOCOL_DIRECTORY + "/" + c + ".txt" for c in commands},
        "ert_path": str(target), "template_sha256": TEMPLATE_SHA,
        "streams": streams, "expected_error_line": 2 if case == "syntax" else 6 if case.startswith("unused-") else None,
        "sources": {str(p.relative_to(out)): sha256(p) for p in (target, out / "fixture.1s", out / "ert-controller.1s", out / "client.vbs")}}
    atomic_json(out / "ert-manifest.json", manifest)
    atomic_json(out / "shutdown-manifest.json", shutdown_manifest)
    return manifest, shutdown_manifest


def read_results(out, manifest, lifecycle, shutdown_result):
    issues = []
    waiting = manifest["case"] == "wait"
    report = {"status": "blocked", "run_id": manifest["run_id"], "case": manifest["case"],
              "scope": "native loading/compilation of this synthetic ERT and its explicit function call; no visible form checks",
              "issues": issues, "operations": []}
    for name, digest in manifest["sources"].items():
        try:
            if sha256(out / name) != digest:
                issues.append("artifact changed: " + name)
        except OSError:
            issues.append("artifact missing: " + name)
    if lifecycle.get("run_id") != manifest["run_id"]:
        issues.append("lifecycle run_id mismatch")
    if waiting:
        from modal_wait77 import wait_issues
        issues.extend(wait_issues(out, manifest, lifecycle))
        if (shutdown_result.get("status") != "blocked"
                or shutdown_result.get("issues") != ["timeout_phase: ert-operation"]):
            issues.append("shutdown after timeout not verified")
    elif shutdown_result.get("status") != "passed":
        issues.append("shutdown contract not met")
    if not lifecycle.get("private_desktop") or lifecycle.get("desktop_closed") is not True:
        issues.append("private desktop lifecycle not verified")
    try:
        events = [json.loads(line) for line in (out / "ert-events.jsonl").read_text(encoding="utf-16").splitlines()]
    except (OSError, UnicodeError, ValueError) as error:
        issues.append("missing/malformed events: " + str(error))
        events = []
    expected = [("phase", "base"), ("phase", "controller"), *[("ert", c) for c in manifest["commands"]], ("complete", "ert")]
    if [(e.get("kind"), e.get("name")) if isinstance(e, dict) else None for e in events] != expected:
        issues.append("event set/order mismatch")
    if waiting and lifecycle.get("wait_timeout", {}).get("events") != events[:3]:
        issues.append("events before timeout differ from final evidence")
    for event in events:
        if not isinstance(event, dict) or event.get("run_id") != manifest["run_id"] or not isinstance(event.get("value"), str):
            issues.append("invalid event or foreign run_id")
        elif (type(event.get("elapsed_ms")) not in (int, float)
              or not math.isfinite(event["elapsed_ms"]) or not 0 <= event["elapsed_ms"] <= 145000):
            issues.append("invalid elapsed time")
    if issues:
        return report
    for event in events:
        if event["kind"] != "ert":
            if event["value"] != ("done" if event["kind"] == "complete" else "ok"):
                issues.append("failed lifecycle phase")
            continue
        name, actual = event["name"], event["value"]
        protocol = ""
        try:
            data = protocol_path(out, manifest, name).read_bytes()
            protocol = data.decode("utf-16" if data.startswith(b"\xff\xfe") else "cp1251")
        except (OSError, UnicodeError, ValueError) as error:
            issues.append("protocol unavailable: " + str(error))
        marker = manifest["run_id"] + ":" + name
        lines = protocol.splitlines()
        if (not lines or lines[0] != "HARNESS77-BEGIN:" + marker or lines[-1] != "HARNESS77-END:" + marker
                or lines.count("HARNESS77-BEGIN:" + marker) != 1 or lines.count("HARNESS77-END:" + marker) != 1):
            issues.append("incomplete/foreign protocol: " + name)
        actual_lines = actual.splitlines()
        if not actual_lines or actual_lines[0] != "selected:" + manifest["ert_path"]:
            issues.append("selected ERT mismatch")
        loaded = "loaded:" + manifest["identity"] in actual.splitlines()
        complete = "completed:" + manifest["identity"] in actual.splitlines()
        diagnostics = [{"line": int(m[1]), "message": m[2]} for m in re.finditer(
            r"^\{[^\r\n]*\(([0-9]{1,9})\)\}:[ \t]*([^\r\n]*)", protocol, re.MULTILINE)]
        row = {"name": name, "actual": actual, "protocol": protocol, "diagnostics": diagnostics,
               "loaded": loaded, "completed": complete, "status": "blocked", "expectation_met": False}
        if loaded and complete and actual_lines.count("loaded:" + manifest["identity"]) == 1 and actual_lines.count("completed:" + manifest["identity"]) == 1 and "unexpected-visible-form" not in actual and "open-error:" not in actual and actual_lines.count("open-return:0") == 1:
            row["status"] = "failed" if "runtime-error:" in actual else "passed"
            if name == "check":
                row["expectation_met"] = "value:" not in actual and "runtime-error:" not in actual and manifest["case"] in ("ok", "runtime", "wait")
            elif name == "execute":
                row["expectation_met"] = ("value:42" in actual.splitlines() if manifest["case"] == "ok"
                    else "runtime-error:" in actual and manifest["case"] == "runtime")
            elif name == "wait" and waiting:
                row["status"] = "blocked"
                row["outcome"] = "timeout"
                row["expectation_met"] = ("value:" not in actual and "runtime-error:" not in actual
                                          and 30000 <= event["elapsed_ms"] <= 45000)
        elif not loaded and any(d["line"] == manifest["expected_error_line"] for d in diagnostics):
            row["status"] = "failed"
            row["expectation_met"] = manifest["case"] in ("syntax", "unused-syntax", "unused-name")
        report["operations"].append(row)
    report["expectations_met"] = all(row["expectation_met"] for row in report["operations"])
    if waiting:
        report["timeout_verified"] = not issues and report["expectations_met"]
    report["status"] = "blocked" if issues or any(r["status"] == "blocked" for r in report["operations"]) else "passed" if report["expectations_met"] else "failed"
    return report
