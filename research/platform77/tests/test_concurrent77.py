"""Reject wrong-process and incomplete concurrent-run evidence."""
import copy
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from concurrent77 import concurrency_issues, unexpected_processes, validate_proxy
from proxy_debug77 import challenge_name, observed_identity, observer_retired


class ConcurrentTests(unittest.TestCase):
    def setUp(self):
        self.server = {"pid": 200, "parent_pid": 100}
        self.baseline = [{"pid": 50, "parent_pid": 10}]
        self.report = {"concurrent_mode": "verified-proxy-v1", "run_id": "fresh",
            "server": self.server, "proxy_identity": {"run_id": "fresh", "pid": 200, "tid": 300},
            "proxy_verified_before_initialize": True, "baseline_preserved": True,
            "server_desktop_verified": True, "private_desktop": "private", "desktop_switch_requested": False,
            "identity_registration": {"removed": True}, "identity_hash_before": "hash", "identity_hash_after": "hash",
            "identity_observer_hashes_before": {"script": "hash"}, "identity_observer_hashes_after": {"script": "hash"},
            "processes_before": self.baseline, "processes_after": self.baseline,
            "baseline_identity": [{"pid": 50, "parent_pid": 10, "image": "1cv7l.exe", "creation_filetime": 123}]}

    def test_complete_evidence(self):
        self.assertEqual(concurrency_issues(self.report), [])

    def test_never_accept_baseline_pid_as_test_server(self):
        with self.assertRaisesRegex(ValueError, "owned server"):
            validate_proxy({"run_id": "fresh", "pid": 50, "tid": 300}, "fresh", self.server)

    def test_reject_foreign_run_or_missing_sta(self):
        for change in ({"run_id": "old"}, {"pid": "200"}, {"tid": 0}, {"tid": 65535}, {"tid": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_proxy(dict(self.report["proxy_identity"], **change), "fresh", self.server)

    def test_no_unexplained_extra_process(self):
        new = {"pid": 500, "parent_pid": 10}
        self.assertEqual(unexpected_processes([self.server, *self.baseline, new], self.baseline, self.server), [new])

    def test_no_missing_identity_or_skipped_verification(self):
        for key in ("proxy_identity", "baseline_identity", "baseline_preserved", "server_desktop_verified",
                    "proxy_verified_before_initialize", "identity_registration", "processes_after"):
            report = copy.deepcopy(self.report)
            del report[key]
            with self.subTest(key=key):
                self.assertTrue(concurrency_issues(report))

    def test_gate_is_before_first_platform_method(self):
        source = Path(__file__).resolve().parents[1]
        client = (source / "ert_probe77.vbs").read_text(encoding="utf-8")
        self.assertLess(client.index("__PROXY_IDENTITY__"), client.index("v.Initialize"))
        gate = (source / "proxy_identity77.vbs").read_text(encoding="utf-8")
        self.assertIn("proxyPid = proxyInspector.Challenge(v,", gate)
        self.assertIn('proxyPermit <> runId', gate)
        self.assertNotIn('v.Initialize', gate)

    def test_observer_needs_exact_nonce_and_owned_pid(self):
        run_id = str(uuid.uuid4())
        name = challenge_name(run_id)
        line = f"HARNESS77_LOOKUP:{name}:c8:12c\n"
        identity = observed_identity(line, run_id, self.server)
        self.assertEqual(identity["pid"], 200)
        self.assertEqual(identity["tid"], 300)
        self.assertIsNone(observed_identity(line, str(uuid.uuid4()), self.server))
        self.assertIsNone(observed_identity("0:000> " + line, run_id, self.server))
        for invalid in (line + line, line.replace(":c8:", ":32:")):
            with self.assertRaises(ValueError):
                observed_identity(invalid, run_id, self.server)

    def test_retirement_requires_empty_list_after_exact_lookup(self):
        run_id = str(uuid.uuid4())
        lookup = f"HARNESS77_LOOKUP:{challenge_name(run_id)}:c8:12c\n"
        begin = "HARNESS77_OBSERVER_EMPTY_BEGIN:" + run_id + "\n"
        end = "HARNESS77_OBSERVER_EMPTY_END:" + run_id + "\n"
        log = lookup + begin + end
        self.assertTrue(observer_retired(log, run_id, self.server))
        for partial in (lookup, lookup + begin, begin + end, log.replace(run_id, "old")):
            self.assertFalse(observer_retired(partial, run_id, self.server))
        for invalid in (lookup + begin + "15 e active breakpoint\n" + end,
                        begin + end + lookup, log + begin + end,
                        log + "HARNESS77_LOOKUP:EvalExpr:c8:12c\n"):
            with self.subTest(log=invalid), self.assertRaises(ValueError):
                observer_retired(invalid, run_id, self.server)

    def test_new_profile_cannot_accept_legacy_or_partial_retirement(self):
        self.report["identity_observer_profile"] = "challenge-only-v2"
        self.assertTrue(concurrency_issues(self.report))
        self.report["identity_observer_retired_before_initialize"] = True
        self.assertTrue(concurrency_issues(self.report))
        self.report["identity_observer_retired_verified"] = True
        self.assertEqual(concurrency_issues(self.report), [])
        self.report["identity_observer_profile"] = "unknown"
        self.assertTrue(concurrency_issues(self.report))


if __name__ == "__main__":
    unittest.main()
