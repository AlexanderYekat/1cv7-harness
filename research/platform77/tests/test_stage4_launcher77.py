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
