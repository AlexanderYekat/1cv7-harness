"""P05: native Initialize against a UUID path that must never be created."""
import json
import math
from pathlib import Path
import uuid

from concurrent77 import concurrency_issues
from module_suite77 import vb_literal
from shutdown77 import atomic_json, PINNED, sha256


def select_registration(windows, run_id, pid, tid, desktop, target):
    """Pinned registration dialog observed in P05; only Cancel is authorized."""
    if not str(target).endswith("absent-base-" + str(uuid.UUID(run_id))):
        raise ValueError("registration path does not contain this run UUID")
    matches = []
    for window in windows:
        children = window.get("children", [])
        if (window.get("pid") != pid or window.get("tid") != tid or window.get("desktop") != desktop
                or window.get("class") != "#32770" or window.get("text") != "Регистрация Информационной Базы"
                or window.get("visible") is not True or window.get("enabled") is not True
                or window.get("owner") or window.get("owner_pid") != 0 or window.get("owner_tid") != 0):
            continue
        if (len(children) != 7 or any(c.get("pid") != pid or c.get("tid") != tid
                or c.get("visible") is not True or c.get("enabled") is not True for c in children)):
            continue
        controls = [(c.get("class"), c.get("id"), c.get("text")) for c in children]
        fixed = [("Static", 65535, "&Название:"), ("Static", 65535, "&Путь:"),
                 ("Edit", 4359, str(target) + "\\"), ("Button", 4360, "..."),
                 ("Button", 1, "OK"), ("Button", 2, "Отмена")]
        names = [c for c in children if c.get("class") == "Edit" and c.get("id") == 4361 and c.get("text")]
        if all(controls.count(control) == 1 for control in fixed) and len(names) == 1:
            matches.append(window)
    if len(matches) != 1:
        raise ValueError("expected exactly one owned registration dialog for the absent UUID path")
    return matches[0]


def select_launcher(windows, run_id, pid, tid, desktop, target, prior):
    """Cancel the fallback chooser only after this run's UUID registration."""
    if (prior.get("requested") is not True or prior.get("control_id") != 2
            or prior.get("identity_rechecked") is not True or prior.get("message") != "WM_COMMAND/BN_CLICKED"):
        raise ValueError("launcher cancellation requires the verified prior registration cancellation")
    select_registration([prior.get("dialog", {})], run_id, pid, tid, desktop, target)
    matches = []
    fixed = [("Static", 65535, "&В режиме:", True), ("ComboBox", 4356, "8", True),
             ("Button", 4357, "&Монопольно", False), ("Static", 65535, "Информационные &Базы:", True),
             ("ListBox", 4355, "", True), ("Button", 1, "OK", True), ("Button", 2, "Отмена", True),
             ("Button", 4353, "&Изменить", True), ("Button", 4352, "&Добавить", True),
             ("Button", 4354, "&Удалить", True), ("Button", 57670, "Помощь", True)]
    for window in windows:
        children = window.get("children", [])
        if (window.get("pid") != pid or window.get("tid") != tid or window.get("desktop") != desktop
                or window.get("class") != "#32770" or window.get("text") != "Запуск 1С:Предприятия"
                or window.get("visible") is not True or window.get("enabled") is not True
                or window.get("owner") or window.get("owner_pid") != 0 or window.get("owner_tid") != 0
                or len(children) != 12 or any(c.get("pid") != pid or c.get("tid") != tid
                                             or c.get("enabled") is not True for c in children)):
            continue
        controls = [(c.get("class"), c.get("id"), c.get("text"), c.get("visible")) for c in children]
        paths = [c for c in children if c.get("class") == "Static" and c.get("id") == 4358
                 and isinstance(c.get("text"), str) and c["text"] and c.get("visible") is True]
        if all(controls.count(control) == 1 for control in fixed) and len(paths) == 1:
            matches.append(window)
    if len(matches) != 1:
        raise ValueError("expected exactly one owned fallback launcher after UUID registration cancellation")
    return matches[0]


def prepare(out):
    run_id = str(uuid.uuid4())
    target = out / ("absent-base-" + run_id)
    if target.exists():
        raise ValueError("missing-base target already exists")
    source = Path(__file__).with_suffix(".vbs").read_text(encoding="utf-8")
    template = Path(__file__).with_name("module_suite77.vbs").read_text(encoding="utf-8")
    utilities = template[template.index("Function Quote"):template.index("Sub CompileCase")]
    for key, value in {"RUN_ID": vb_literal(run_id), "MISSING_BASE": vb_literal(str(target)),
            "UTILITIES": utilities,
            "PROXY_IDENTITY": Path(__file__).with_name("proxy_identity77.vbs").read_text(encoding="utf-8")}.items():
        source = source.replace("__" + key + "__", value)
    client = out / "client.vbs"
    client.write_text(source, encoding="utf-16")
    manifest = {"run_id": run_id, "case": "missing-base", "target": str(target),
                "absent_before": not target.exists(), "sources": {client.name: sha256(client)}}
    atomic_json(out / "open-manifest.json", manifest)
    return manifest


def assess(out, manifest, report):
    issues = []
    result = {"status": "blocked", "reason": "open_base_unverified", "expectation_met": False,
              "issues": issues, "scope": "P05 missing database path; no ERT was selected or executed"}
    if manifest.get("run_id") != report.get("run_id") or report.get("case") != "missing-base":
        issues.append("open-failure identity mismatch")
    try:
        target = out / ("absent-base-" + str(uuid.UUID(manifest["run_id"])))
        if str(target) != manifest.get("target") or manifest.get("absent_before") is not True or target.exists():
            issues.append("missing database path not verified absent")
        if manifest.get("sources") != {"client.vbs": sha256(out / "client.vbs")}:
            issues.append("open-failure client changed")
        snapshot = json.loads((out / "base-open-windows.json").read_text(encoding="utf-8"))
        if snapshot.get("run_id") != manifest["run_id"]:
            issues.append("foreign registration snapshot")
        chosen = select_registration(snapshot["windows"], manifest["run_id"], report["server"]["pid"],
                                     report["proxy_identity"]["tid"], report["private_desktop"], target)
        cancelled = report.get("registration_cancel", {})
        if (cancelled.get("dialog") != chosen or cancelled.get("requested") is not True
                or cancelled.get("message") != "WM_COMMAND/BN_CLICKED" or cancelled.get("control_id") != 2
                or cancelled.get("identity_rechecked") is not True):
            issues.append("registration cancellation not verified")
        after_cancel = json.loads((out / "base-open-after-cancel.json").read_text(encoding="utf-8"))
        if after_cancel.get("run_id") != manifest["run_id"]:
            issues.append("foreign fallback launcher snapshot")
        launcher = select_launcher(after_cancel["windows"], manifest["run_id"], report["server"]["pid"],
                                   report["proxy_identity"]["tid"], report["private_desktop"], target, cancelled)
        fallback_cancel = report.get("launcher_cancel", {})
        if (fallback_cancel.get("dialog") != launcher or fallback_cancel.get("requested") is not True
                or fallback_cancel.get("message") != "WM_COMMAND/BN_CLICKED" or fallback_cancel.get("control_id") != 2
                or fallback_cancel.get("identity_rechecked") is not True):
            issues.append("fallback launcher cancellation not verified")
        for state in ("started", "finished"):
            if (out / ("base-open-" + state)).read_text(encoding="ascii").strip() != manifest["run_id"]:
                issues.append("foreign open marker")
        events = [json.loads(line) for line in (out / "open-events.jsonl").read_text(encoding="utf-16").splitlines()]
        expected = [("phase", "open-start"), ("open", "return"), ("open", "variant-type"), ("open", "return-text"), ("open", "error-number"),
                    ("open", "error-description"), ("phase", "released"), ("complete", "open-failure")]
        if [(e.get("kind"), e.get("name")) for e in events] != expected:
            issues.append("open-failure event set/order mismatch")
        elif any(e.get("run_id") != manifest["run_id"] or not isinstance(e.get("value"), str)
                 or type(e.get("elapsed_ms")) not in (int, float) or not math.isfinite(e["elapsed_ms"])
                 or not 0 <= e["elapsed_ms"] <= 30000 for e in events):
            issues.append("invalid open-failure event")
        else:
            value, error, description = events[1]["value"], events[4]["value"], events[5]["value"]
            if (events[0]["value"] != str(target) or events[6]["value"] != "ok"
                    or events[7]["value"] != "done" or error != "0" or value != "0" or description
                    or events[2]["value"] != "11"):
                issues.append("Initialize did not return the qualified false/no-COM-error result")
            result["native_result"] = {"return": value, "error_number": error, "description": description,
                                       "variant_type": events[2]["value"], "return_text": events[3]["value"],
                                       "elapsed_ms": events[1]["elapsed_ms"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        issues.append("missing/invalid open evidence: " + str(error))
    issues.extend(concurrency_issues(report))
    for key in ("error", "cleanup_errors", "timeout_phase"):
        if report.get(key):
            issues.append(key + ": " + str(report[key]))
    for key in ("forced_cleanup", "first_chance_av_observed", "av_dump_saved", "diagnostic_execution_modified"):
        if report.get(key) is not False:
            issues.append(key + " must be false")
    for key in ("server_exit_code", "helper_exit_code", "debugger_exit_code"):
        if type(report.get(key)) is not int or report[key] != 0:
            issues.append(key + " must be zero")
    for key in ("cleanup_verified", "desktop_closed", "debugger_ready", "debugger_stops_at_first_chance_av"):
        if report.get(key) is not True:
            issues.append(key + " not verified")
    if report.get("hashes_before") != PINNED or report.get("hashes_after") != PINNED:
        issues.append("pinned files changed")
    if report.get("temporary_com_registration", {}).get("removed") is not True:
        issues.append("cleanup helper registration not removed")
    if (not report.get("base_titles_before") or report.get("base_titles_before") != report.get("base_titles_after")):
        issues.append("user database list changed or was not observed")
    if not issues:
        result.update(reason="database_path_missing", expectation_met=True)
    return result
