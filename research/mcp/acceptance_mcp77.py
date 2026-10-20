"""Task 014 acceptance: the recorded expectations checked against the probe evidence.

Reads the JSON written by verify_mcp77.py (C1, N1, N1-cli, N2, N3, N1b, N1c, N1d),
claude_probe77.py (C2, C3, C3b, C4) and claude_esc77.py (C5) and writes one summary
with a row per check. C4, C5, N1c and N1d are the owner's manual check done by the probes.
C3 has no expectation (it records how Claude Code ends a server); its facts are
copied into the summary without a verdict.
"""

import argparse
import json
from pathlib import Path
import re


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_json(native, run_id):
    return load(Path(native) / "runs" / run_id / "run.json")


def tests_of(native, run_id):
    """Test rows from run.json itself (N1 was recorded before the probe summary carried them)."""
    stage = next(s for s in run_json(native, run_id)["stages"] if s["stage"] == "tests")
    return [{k: t.get(k) for k in ("name", "status", "value")} for t in stage.get("tests") or []]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--c1", type=Path, required=True, help="Каталог пробы C1")
    parser.add_argument("--claude", type=Path, required=True, help="Каталог проб C2 и C3")
    parser.add_argument("--c3b", type=Path, required=True, help="Каталог пробы C3b")
    parser.add_argument("--native", type=Path, required=True, help="Каталог проб N1–N3")
    parser.add_argument("--c4", type=Path, help="Каталог пробы C4 (сервер из claude mcp add)")
    parser.add_argument("--c5", type=Path, help="Каталог пробы C5 (Esc в интерактивном Claude Code)")
    parser.add_argument("--n1c", type=Path, help="Каталог проб N1c и N1d (сеансы после C5)")
    parser.add_argument("--output", type=Path, required=True, help="Новый файл JSON")
    args = parser.parse_args()
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    c1 = load(args.c1 / "C1.json")
    check("C1 protocol", c1["protocol_version"] == "2025-11-25" and c1["outcome"]["discover_fallback"],
          {"protocol_version": c1["protocol_version"], "discover_fallback": c1["outcome"]["discover_fallback"]})
    check("C1 tools", len(c1["tools"]) == 8, c1["tools"])
    check("C1 equal to CLI", all(c["equal_to_cli"] for c in c1["cases"]) and len(c1["cases"]) == 13,
          [(c["tool"], c["exit_code"], c["is_error"], c["equal_to_cli"]) for c in c1["cases"]])
    check("C1 invalid arguments", c1["invalid_arguments"]["is_error"] and c1["invalid_arguments"]["structured"] is None,
          c1["invalid_arguments"]["text"])
    check("C1 unknown tool", c1["unknown_tool"].get("code") == -32602, c1["unknown_tool"])

    c2 = load(args.claude / "C2.json")["outcome"]
    servers = {s["name"]: s["status"] for s in c2["mcp_servers"] or []}
    lint_results = [r["text"] for r in c2["tool_results"] if '"tool":"lint"' in r["text"].replace(" ", "")]
    check("C2 Claude Code", c2["exit_code"] == 0 and servers.get("harness77") == "connected"
          and any(c["name"] == "mcp__harness77__lint" for c in c2["tool_calls"])
          and any('"exit_code":0' in t.replace(" ", "") and '"diagnostics":[]' in t.replace(" ", "")
                  for t in lint_results),
          {"servers": servers, "calls": [c["name"] for c in c2["tool_calls"]], "answer": c2["answer"]})

    facts = {}
    for name, folder in (("C3", args.claude), ("C3b", args.c3b)):
        outcome = load(folder / "C3.json")["outcome"]
        log = [json.loads(line) for line in (folder / "C3-stub.jsonl").read_text(encoding="utf-8").splitlines()]
        closed = next((r["at_s"] for r in log if r["event"] == "stdin-closed"), None)
        facts[name] = {"methods": [r["method"] for r in log if r["event"] == "message"],
                       "server_windir": outcome["server_windir"], "server_env_names": outcome["server_env_names"],
                       "stdin_closed_at_s": closed, "last_event": outcome["server_last_event"],
                       "child_alive": outcome["child_alive_now"],
                       **{k: outcome.get(k) for k in ("orphan_alive_now", "breakaway_alive_now", "breakaway_error")}}

    n1 = load(args.native / "N1.json")
    n1_run = dict(n1["run"], tests=tests_of(args.native, n1["arguments"]["run_id"]))
    check("N1 run through MCP", n1_run["status"] == "passed" and n1_run["platform_checked"]
          and n1_run["tests"] == [{"name": "control-42", "status": "passed", "value": "42"}]
          and n1["result"]["structured"]["exit_code"] == 0 and not n1_run["shutdown"]["forced_cleanup"]
          and n1["outcome"]["one_c_left"] == [] and not n1["full_env"],
          {"run": n1_run, "full_env": n1["full_env"]})
    check("N1 progress and pings", len(n1["progress"]) >= 1 and n1["pings"]
          and all(p["latency_s"] < 1 for p in n1["pings"]), {"progress": n1["progress"], "pings": n1["pings"]})
    cli = load(args.native / "N1-cli.json")
    cli_tests = tests_of(args.native, cli["cli"]["stdout"]["run_id"])
    check("N1 equal to CLI", cli["run"]["stages"] == n1_run["stages"] and cli_tests == n1_run["tests"]
          and cli["cli"]["exit_code"] == 0, {"cli": cli["run"]})

    n2 = load(args.native / "N2.json")
    deadlines = run_json(args.native, n2["arguments"]["run_id"])["deadlines"]
    limit = deadlines["cancel_timeout_s"] + deadlines["shutdown_timeout_s"] + 10
    marker = Path(n2["arguments"]["output_root"]) / n2["arguments"]["run_id"] / "native" / "ert-execute-started"
    check("N2 cancelled through MCP", n2["run"]["cancelled"] and n2["run"]["status"] == "blocked"
          and n2["run"]["exit_code"] == 2 and "result" not in n2 and n2["ping_after_cancel_s"] < 1
          and n2["child_exit_after_cancel_s"] <= limit and n2["outcome"]["one_c_left"] == []
          and n2["run"]["shutdown"]["others_preserved"] and n2["run"]["shutdown"]["cleanup_verified"]
          and any("cancelled by the client" in line for line in n2["server_log"]) and marker.exists(),
          {"cancelled_at_s": n2["cancelled_at_s"], "child_exit_after_cancel_s": n2["child_exit_after_cancel_s"],
           "limit_s": limit, "calculation_started": marker.exists(), "shutdown": n2["run"]["shutdown"]})

    n3 = load(args.native / "N3.json")
    check("N3 closed input", n3["server_exit_code"] == 0 and n3["outcome"]["response_exit_code"] == 2
          and n3["outcome"]["response_cancelled"] and n3["run"]["cancelled"] and n3["outcome"]["one_c_left"] == []
          and n3.get("marker_at_s") is not None and n3["run"]["shutdown"]["cleanup_verified"]
          and n3["run"]["shutdown"]["others_preserved"],
          {k: n3.get(k) for k in ("marker_at_s", "closed_at_s", "server_exit_after_close_s", "outcome")})

    n1b = load(args.native / "N1b.json")
    opened = load(Path(n1b["arguments"]["output_root"]) / n1b["arguments"]["run_id"] / "platform-result.json")["open"]
    check("N1b clean session after forced stops", n1b["run"]["status"] == "passed"
          and opened["reindex_expected"] and not opened["base_trace_after"]["interrupted"]
          and not n1b["run"]["shutdown"]["forced_cleanup"], {"open": opened})

    if args.c4:
        c4 = load(args.c4 / "C4.json")["outcome"]
        servers = {s["name"]: (s["status"], s.get("source")) for s in c4["mcp_servers"] or []}
        results = [json.loads(r["text"]) for r in c4["tool_results"] if r["text"].startswith('{"tool"')]
        root = Path(__file__).resolve().parents[2]
        check("C4 registered server", c4["exit_code"] == 0 and servers.get("harness77") == ("connected", "local")
              and [r["tool"] for r in results] == ["lint", "form-extract", "build"]
              and all(r["exit_code"] == 0 and Path(r["cwd"]) == root for r in results)
              and all(not Path(p).is_absolute() for c in c4["tool_calls"] for p in
                      [*(c["input"] or {}).get("paths", []), *[v for k, v in (c["input"] or {}).items()
                                                               if k != "paths" and isinstance(v, str)]]
                      if c["name"].startswith("mcp__harness77__"))
              and c4["new_ert_bytes"],
              {"servers": servers, "calls": [(r["tool"], r["argv"], r["exit_code"]) for r in results],
               "answer": c4["answer"]})

    if args.c5:
        c5 = load(args.c5 / "C5.json")
        deadlines = load(args.c5 / "runs" / c5["arguments"]["run_id"] / "run.json")["deadlines"]
        limit = deadlines["cancel_timeout_s"] + deadlines["shutdown_timeout_s"] + 10
        run, events = c5["run"] or {}, c5["events"]
        # Judged on the recorded screen: the first C5 looked for "lint (MCP)", which 2.1.304 does not show.
        lint_screen = re.sub(r"\s", "", c5.get("lint_screen", ""))
        lint_called = "Callingharness77" in lint_screen
        check("C5 Esc cancels run", run.get("status") == "blocked" and run.get("cancelled")
              and run.get("exit_code") == 2 and any(e.get("marker") for e in events)
              and c5["run_json_after_esc_s"] is not None and c5["run_json_after_esc_s"] <= limit
              and run["shutdown"]["cleanup_verified"] and run["shutdown"]["others_preserved"]
              and c5["outcome"]["one_c_left"] == [] and c5["com_keys_after"] == []
              and lint_called and c5["client_exited"],
              {"events": events, "run_json_after_esc_s": c5["run_json_after_esc_s"], "limit_s": limit,
               "run": run, "com_keys_after": c5["com_keys_after"], "lint_called": lint_called,
               "lint_answer": lint_screen[lint_screen.rfind("Callingharness77"):][-200:]})

    if args.n1c:
        # N1c removes the trace C5 leaves; its verdict "blocked" came from the stage 4 launcher
        # (it missed the 0.4 s shutdown under load), so the check is the trace and a normal exit.
        n1c = load(args.n1c / "N1c.json")
        opened = load(Path(n1c["arguments"]["output_root"]) / n1c["arguments"]["run_id"]
                      / "platform-result.json")["open"]
        shutdown = n1c["run"]["shutdown"]
        check("N1c base trace removed after Esc", opened["reindex_expected"]
              and not opened["base_trace_after"]["interrupted"] and not shutdown["forced_cleanup"]
              and shutdown["cleanup_verified"] and shutdown["server_exit_code"] == 0
              and n1c["outcome"]["one_c_left"] == [],
              {"open": opened, "status": n1c["run"]["status"], "shutdown": shutdown})
        facts["N1c launcher verdict"] = {"status": n1c["run"]["status"], "reason": n1c["run"]["reason"],
                                         "issues": shutdown["issues"]}
        n1d = load(args.n1c / "N1d.json")
        check("N1d run through MCP after Esc", n1d["run"]["status"] == "passed" and n1d["run"]["platform_checked"]
              and n1d["run"]["tests"] == [{"name": "control-42", "status": "passed", "value": "42"}]
              and not n1d["run"]["shutdown"]["forced_cleanup"] and n1d["outcome"]["one_c_left"] == [],
              {"run": n1d["run"]})

    summary = {"task": "014", "passed": sum(c["passed"] for c in checks), "total": len(checks), "checks": checks,
               "claude_code_shutdown": facts}
    if args.output.exists():
        raise SystemExit(f"exists: {args.output}")
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"passed": summary["passed"], "total": summary["total"],
                      "failed": [c["check"] for c in checks if not c["passed"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
