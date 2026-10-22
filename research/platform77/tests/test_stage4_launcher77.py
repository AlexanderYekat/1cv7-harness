"""Task 007: the open deadline knows whether 1C will reindex; portable, no 1C."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage4_launcher77 as launcher  # noqa: E402

DEADLINES = {"open_timeout_s": 120, "reindex_timeout_s": 600, "calculation_timeout_s": 3600,
             "cancel_timeout_s": 15, "shutdown_timeout_s": 30, "total_timeout_s": 4400}


def users_table(count):
    """1SUSERS.DBF as 1C 7.7 writes it: USRSCNT N(4), NETCHGCN N(10), one record."""
    fields = b""
    for name, length in ((b"USRSCNT", 4), (b"NETCHGCN", 10)):
        fields += name.ljust(11, b"\0") + b"N" + bytes(4) + bytes([length, 0]) + bytes(14)
    header = 32 + len(fields) + 1
    head = (bytes([3, 122, 8, 18]) + (1).to_bytes(4, "little") + header.to_bytes(2, "little")
            + (1 + 4 + 10).to_bytes(2, "little") + bytes(20))
    return head + fields + b"\r" + b" " + str(count).rjust(4).encode() + b"0".rjust(10) + b"\x1a"


class BaseTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h77-trace-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_clean_base(self):
        (self.base / "1SUSERS.DBF").write_bytes(users_table(0))
        self.assertEqual(launcher.base_trace(self.base),
                         {"lock_file": False, "users_readable": True, "active_users": 0, "interrupted": False})

    def test_trace_of_an_interrupted_session(self):
        (self.base / "1SUSERS.DBF").write_bytes(users_table(1))
        (self.base / "1Cv7.LCK").write_bytes(b"")
        trace = launcher.base_trace(self.base)
        self.assertEqual((trace["interrupted"], trace["active_users"]), (True, 1))

    def test_a_working_1c_locks_the_users_table(self):
        # R1: while 1C works, 1Cv7.LCK exists unheld, but 1SUSERS.DBF cannot be read.
        (self.base / "1SUSERS.DBF").write_bytes(users_table(1))
        (self.base / "1Cv7.LCK").write_bytes(b"")
        with patch.object(Path, "read_bytes", side_effect=PermissionError("locked region")):
            trace = launcher.base_trace(self.base)
        self.assertEqual((trace["interrupted"], trace["users_readable"]), (False, False))

    def test_lock_without_active_users_or_users_without_lock_is_not_an_interruption(self):
        (self.base / "1Cv7.LCK").write_bytes(b"")
        (self.base / "1SUSERS.DBF").write_bytes(users_table(0))
        self.assertFalse(launcher.base_trace(self.base)["interrupted"])
        (self.base / "1Cv7.LCK").unlink()
        (self.base / "1SUSERS.DBF").write_bytes(users_table(1))
        self.assertFalse(launcher.base_trace(self.base)["interrupted"])

    def test_open_deadline_adds_the_allowance_only_after_an_interruption(self):
        self.assertEqual(launcher.open_deadline(DEADLINES, {"interrupted": False}), 120)
        self.assertEqual(launcher.open_deadline(DEADLINES, {"interrupted": True}), 720)
        self.assertEqual(launcher.open_deadline(dict(DEADLINES, reindex_timeout_s=0), {"interrupted": True}), 120)

    def test_open_phase_maps_to_section_8_5(self):
        self.assertEqual(launcher.PHASES["open"], "open")
        # Task 015: starting CDB and 1C is part of opening.
        self.assertEqual(launcher.PHASES["ownership"], "open")
        self.assertEqual(launcher.PHASES["debugger-ready"], "open")

    def test_client_waits_for_the_initialize_permission_within_the_open_deadline(self):
        # L6: under load cdb reported the proxy identity after the research 10 s.
        out = Path(self.temp.name) / "native"
        ert = Path(self.temp.name) / "built.ert"
        ert.write_bytes(b"ert")
        launcher.scaffold(out, ert, "0b6d6c8e-6a52-4f8e-9e0c-3a1f5d2b7c40", permit_timeout_s=180)
        client = (out / "client.vbs").read_text(encoding="utf-16")
        self.assertIn("If Elapsed(proxyStart) > 180000 Then", client)
        self.assertNotIn(launcher.PERMIT_WAIT, client)
        # The research client (and kudir, which embeds the file) keeps its 10 s.
        self.assertIn(launcher.PERMIT_WAIT, launcher.proxy_client())
        with patch.object(launcher.Path, "read_text", return_value="no wait here"):
            with self.assertRaisesRegex(ValueError, "permission wait was not found"):
                launcher.proxy_client(180)

    def test_stale_registrations_of_both_roots_reach_the_open_report(self):
        evidence = {"run_id": "killed", "processes": [{"role": "registrar", "pid": 1, "gone": "absent"}], "keys": ["k"]}
        lifecycle = {"identity_registration": {"roots": ["a", "b"], "stale_removed": evidence},
                     "temporary_com_registration": {"roots": ["c", "d"]}}
        self.assertEqual(launcher.stale_registrations(lifecycle), [dict(evidence, roots=["a", "b"])])
        self.assertEqual(launcher.stale_registrations({"error": "refused before registration"}), [])



class BuiltConfigurationTests(unittest.TestCase):
    """Task 021: a run's copy of the base passes only with the configuration the run built."""

    def setUp(self):
        import hashlib
        import shutdown77
        self.temp = tempfile.TemporaryDirectory(prefix="h77-built-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.base, self.out = root / "run" / "base", root / "run" / "native"
        self.base.mkdir(parents=True)
        files = {name: self.base / name for name in ("1Cv7.MD", "1Cv7.DD", "1CPP.dll", "FormEx.dll")}
        files.update(exe=root / "1cv7l.exe", helper=root / "helper.dll")
        for name, path in files.items():
            path.write_bytes(name.encode() + b" bytes")
        self.cdb = root / "cdb.exe"
        self.cdb.write_bytes(b"MZ" + bytes(0x3a) + (0x40).to_bytes(4, "little") + b"PE\0\0\x4c\x01")
        (self.base / "1SJOURN.DBF").write_bytes(b"journal")
        self.exe, self.helper = files["exe"], files["helper"]
        self.built = hashlib.sha256(b"1Cv7.MD bytes").hexdigest()
        # The stand pins its own configuration; the copy carries the built one.
        pins = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
        pins["1Cv7.MD"] = "0" * 64
        patcher = patch.dict(shutdown77.PINNED, pins, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def preflight(self, configuration):
        launcher.preflight_copy(self.base, self.exe, self.cdb, self.helper, self.out, configuration_sha256=configuration)

    def test_pinned_for_replaces_only_the_configuration(self):
        import shutdown77
        self.assertEqual(launcher.pinned_for(), shutdown77.PINNED)
        self.assertEqual(launcher.pinned_for(self.built), dict(shutdown77.PINNED, **{"1Cv7.MD": self.built}))

    def test_the_built_configuration_passes(self):
        self.preflight(self.built)

    def test_another_configuration_or_none_is_unqualified(self):
        for configuration in ("1" * 64, None):
            with self.subTest(configuration=configuration), self.assertRaisesRegex(ValueError, "1Cv7.MD"):
                self.preflight(configuration)

    def test_only_the_registered_copy_made_for_this_run(self):
        import json
        marker = self.base / launcher.COPY_MARKER
        with patch.object(launcher, "registered", return_value=True):
            with self.assertRaisesRegex(ValueError, "the product made"):
                launcher.built_copy(self.base, "run-1")
            for written, message in (({"run_id": "run-0", "complete": True}, "not made for this run"),
                                     ({"run_id": "run-1", "complete": False}, "not made for this run")):
                marker.write_text(json.dumps(written), encoding="utf-8")
                with self.subTest(written=written), self.assertRaisesRegex(ValueError, message):
                    launcher.built_copy(self.base, "run-1")
            marker.write_text(json.dumps({"run_id": "run-1", "complete": True}), encoding="utf-8")
            launcher.built_copy(self.base, "run-1")
        # 1C would wait on «Регистрация Информационной Базы» for an unregistered path.
        with patch.object(launcher, "registered", return_value=False):
            with self.assertRaisesRegex(ValueError, "not in the 1C list of bases"):
                launcher.built_copy(self.base, "run-1")

    def test_the_stand_base_never_gets_a_built_configuration(self):
        import run_shutdown77
        root = Path(self.temp.name).resolve()  # the test's own directory, parent of run/base
        with patch.object(run_shutdown77, "ROOT", root), \
                patch.object(launcher, "preflight") as stand_preflight:
            stand = root / ".local" / "bases" / "base-for-test"
            stand.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "never on the stand base"):
                launcher.preflight_copy(stand, self.exe, self.cdb, self.helper, self.out, configuration_sha256=self.built)
            stand_preflight.assert_not_called()


class ProtocolDiagnosticsTests(unittest.TestCase):
    """Task 009: the load protocol keeps column and source line for the marking."""

    def test_marker_line_gives_column_and_source(self):
        protocol = ("HARNESS77-BEGIN:r:check\r\n"
                    "Ф77 = Строка<<?>> + \"x\";\r\n"
                    "{C:\\X\\ОБРАБОТКА.ERT(6)}: Ожидается символ '('\r\n"
                    "{C:\\X\\ОБРАБОТКА.ERT(28)}: Процедура или функция объявлена (Поздняя77)\r\n"
                    "HARNESS77-END:r:check")
        self.assertEqual(launcher.protocol_diagnostics(protocol), [
            {"line": 6, "message": "Ожидается символ '('", "column": 13, "source_line": 'Ф77 = Строка + "x";'},
            {"line": 28, "message": "Процедура или функция объявлена (Поздняя77)"}])

    def test_no_marker_or_two_markers_keep_line_and_message_only(self):
        protocol = "А<<?>> Б<<?>>\n{(2)}: Ошибка в выражении\n{(3)}: Неопознанный оператор"
        self.assertEqual(launcher.protocol_diagnostics(protocol),
                         [{"line": 2, "message": "Ошибка в выражении"}, {"line": 3, "message": "Неопознанный оператор"}])


if __name__ == "__main__":
    unittest.main()
