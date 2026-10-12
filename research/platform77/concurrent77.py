"""Evidence policy for concurrent native sessions; portable validation."""

IDENTITY_SHA = "c89e3a51e1655ffb046386b844679aced2bb766cc3c0a384b89b065979a1b163"


def validate_proxy(identity, run_id, server):
    if not isinstance(identity, dict) or identity.get("run_id") != run_id:
        raise ValueError("foreign proxy identity")
    if type(identity.get("pid")) is not int or identity["pid"] != server["pid"]:
        raise ValueError("OLE proxy does not point at owned server")
    if type(identity.get("tid")) is not int or identity["tid"] <= 0 or identity["tid"] == 65535:
        raise ValueError("OLE proxy has no verifiable STA thread")


def unexpected_processes(current, baseline, server=None):
    allowed = list(baseline)
    if server:
        allowed.append({"pid": server["pid"], "parent_pid": server["parent_pid"]})
    return [process for process in current if process not in allowed]


def concurrency_issues(report):
    issues = []
    if report.get("concurrent_mode") != "verified-proxy-v1":
        return ["unknown concurrent mode"]
    try:
        validate_proxy(report.get("proxy_identity"), report.get("run_id"), report.get("server", {}))
    except (ValueError, KeyError) as error:
        issues.append(str(error))
    for key in ("proxy_verified_before_initialize", "baseline_preserved", "server_desktop_verified"):
        if report.get(key) is not True:
            issues.append(key + " not verified")
    if not report.get("private_desktop") or report.get("desktop_switch_requested") is not False:
        issues.append("private desktop not verified")
    if report.get("identity_registration", {}).get("removed") is not True:
        issues.append("identity registration not removed")
    if report.get("identity_hash_before") != report.get("identity_hash_after") or not report.get("identity_hash_before"):
        issues.append("identity inspector changed or missing")
    if (report.get("identity_observer_hashes_before") != report.get("identity_observer_hashes_after")
            or not report.get("identity_observer_hashes_before")):
        issues.append("identity observer changed or missing")
    before, after = report.get("processes_before"), report.get("processes_after")
    if (not isinstance(before, list) or not isinstance(after, list)
            or sorted(before, key=lambda p: p["pid"]) != sorted(after, key=lambda p: p["pid"])):
        issues.append("baseline process inventory changed")
    baseline = report.get("baseline_identity", [])
    if ({p["pid"] for p in baseline} != {p["pid"] for p in (before or [])}
            or any(not p.get("creation_filetime") or not p.get("image") for p in baseline)):
        issues.append("baseline creation identities missing")
    return issues
