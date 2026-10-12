"""Portable, fail-closed policy for the one synthetic modal warning."""
import math

# Native snapshot on pinned 7.70.027: warning's sole "OK" uses control ID 2.
WARNING_BUTTON_ID = 2


def modal_text(run_id):
    return "HARNESS77 controlled modal wait " + run_id + ":wait"


def select_dialog(windows, run_id, pid, tid, desktop):
    matches = []
    for window in windows:
        if (window.get("pid") != pid or window.get("tid") != tid
                or window.get("desktop") != desktop or window.get("class") != "#32770"
                or window.get("visible") is not True):
            continue
        children = window.get("children", [])
        if any(c.get("pid") != pid or c.get("tid") != tid for c in children):
            continue
        texts = [c for c in children if c.get("class") == "Static" and c.get("text") == modal_text(run_id)]
        buttons = [c for c in children if c.get("class") == "Button"]
        if (len(texts) == 1 and len(buttons) == 1 and buttons[0].get("id") == WARNING_BUTTON_ID
                and buttons[0].get("text") == "OK"
                and buttons[0].get("enabled") is True and buttons[0].get("visible") is True
                and window.get("owner") and window.get("owner_enabled") is False
                and window.get("owner_pid") == pid and window.get("owner_tid") == tid):
            matches.append(window)
    if len(matches) != 1:
        raise ValueError("expected exactly one owned UUID modal warning with the pinned OK button")
    return matches[0]


def wait_issues(out, manifest, lifecycle):
    """A dismissed warning is still a timed-out operation, never ordinary success."""
    import json
    issues = []
    try:
        evidence = json.loads((out / "wait-timeout.json").read_text(encoding="utf-8"))
        if evidence != lifecycle.get("wait_timeout") or evidence.get("run_id") != manifest["run_id"]:
            issues.append("timeout snapshot identity mismatch")
        elapsed = evidence.get("elapsed_seconds")
        if (type(elapsed) not in (int, float) or not math.isfinite(elapsed)
                or not 30 <= elapsed <= 35 or lifecycle.get("ert_operation_timeout_seconds") != 30):
            issues.append("operation deadline not verified")
        if evidence.get("call_finished") is not False or evidence.get("protocol_finished") is not False:
            issues.append("wait returned before timeout")
        pending = evidence.get("events", [])
        if ([(e.get("kind"), e.get("name")) for e in pending] !=
                [("phase", "base"), ("phase", "controller"), ("ert", "check")]
                or any(e.get("run_id") != manifest["run_id"] for e in pending)):
            issues.append("pending COM call not verified")
        proxy = lifecycle["proxy_identity"]
        chosen = select_dialog(evidence["windows"], manifest["run_id"],
                               lifecycle["server"]["pid"], proxy["tid"], lifecycle["private_desktop"])
        dismissal = lifecycle.get("modal_dismissal", {})
        if (dismissal.get("dialog") != chosen or dismissal.get("requested") is not True
                or dismissal.get("message") != "WM_COMMAND/BN_CLICKED"
                or dismissal.get("control_id") != WARNING_BUTTON_ID
                or dismissal.get("identity_rechecked") is not True):
            issues.append("owned modal dismissal not verified")
        for name in ("ert-wait-started", "ert-wait-finished"):
            if (out / name).read_text(encoding="ascii").strip() != manifest["run_id"]:
                issues.append("wait call marker mismatch")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        issues.append("missing/invalid timeout evidence: " + str(error))
    if lifecycle.get("timeout_phase") != "ert-operation" or lifecycle.get("timeout_operation") != "wait":
        issues.append("wait timeout not recorded")
    if lifecycle.get("wait_call_returned_after_dismissal") is not True:
        issues.append("COM call did not return after dismissal")
    if lifecycle.get("cleanup_verified") is not True:
        issues.append("cleanup not verified")
    return issues
