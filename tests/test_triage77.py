"""Root/cascade/link marking (task 009): native probe outcomes, rule boundaries, CLI.

The fixture holds what 1C 7.70.027 reported for the synthetic probe modules
(research/protocol77); the expected marks below are written from the rule table
of docs/tasks/009-protocol-root-cascade.md, not from the marker's own output.
"""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness77 import catalog77
from harness77.triage77 import read_protocol, triage

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROBES = json.loads((FIXTURES / "triage77" / "probes.json").read_text(encoding="utf-8"))["cases"]

# Per case: (line, role, cause line or None, rule) for every diagnostic, in order.
EXPECTED = {
    "K0": [(4, "root", None, "root"), (8, "link", None, "link")],
    "K1": [(2, "link", None, "link")],
    "K2": [(28, "root", None, "root")],
    "K3": [(4, "root", None, "root"), (8, "root", None, "root"), (12, "link", None, "link")],
    "K4": [(5, "root", None, "root"), (9, "root", None, "root"), (13, "link", None, "link")],
    "K5": [(4, "root", None, "root"), (8, "root", None, "root"), (12, "link", None, "link")],
    "K6": [(4, "root", None, "root"), (9, "root", None, "root"), (13, "link", None, "link")],
    "K7": [(7, "root", None, "root"), (10, "root", None, "root"), (14, "link", None, "link")],
    "K8": [(5, "root", None, "root"), (11, "root", None, "root"), (15, "link", None, "link")],
    "K9": [(3, "root", None, "root"), (5, "cascade", 3, "header-swallowed"), (6, "cascade", 3, "header-parameter"),
           (11, "root", None, "root"), (15, "link", None, "link")],
    "K10": [(11, "root", None, "root"), (15, "link", None, "link")],
    "K11": [(3, "root", None, "root"), (5, "cascade", 3, "header-swallowed"), (11, "root", None, "root"),
            (15, "link", None, "link")],
    "K12": [(3, "root", None, "root"), (4, "cascade", 3, "header-end"), (8, "cascade", 3, "header-redefined"),
            (8, "cascade", 3, "logical-end"), (10, "cascade", 3, "stopped")],
    "K13": [(6, "root", None, "root"), (11, "root", None, "root"), (15, "link", None, "link")],
    "K14": [(3, "root", None, "root"), (7, "cascade", 3, "header-call"), (11, "root", None, "root"),
            (15, "link", None, "link")],
    "K15": [(3, "root", None, "root"), (9, "root", None, "root"), (13, "link", None, "link")],
    "K16": [(3, "root", None, "root"), (5, "cascade", 3, "header-swallowed"), (6, "cascade", 3, "header-swallowed"),
            (8, "cascade", 3, "header-swallowed"), (10, "cascade", 3, "header-parameter"),
            (10, "cascade", 3, "same-line"), (10, "cascade", 3, "header-end"), (11, "cascade", 3, "logical-end"),
            (12, "cascade", 3, "stopped")],
}
STOPPED = {"K12": 10, "K16": 12}


def marks(result):
    lines = {d["index"]: d["line"] for d in result["diagnostics"]}
    return [(d["line"], d["role"], lines.get(d["cause"]), d["rule"]) for d in result["diagnostics"]]


def diag(line, message, source=None):
    """A diagnostic as the parser gives it; `source` holds the <<?>> marker."""
    item = {"line": line, "message": message}
    if source is not None:
        item.update(column=source.index("<<?>>") + 1, source_line=source.replace("<<?>>", "", 1))
    return item


class NativeProbeTests(unittest.TestCase):
    def test_every_probe_is_marked_by_the_rule_table(self):
        self.assertEqual(set(PROBES), set(EXPECTED))
        for case, data in PROBES.items():
            with self.subTest(case=case):
                result = triage(data["diagnostics"], module_text=data["module"])
                self.assertEqual(marks(result), EXPECTED[case])
                # K2 reports only at the end of the text, where there is no source line to compare.
                self.assertEqual(result["module"], {"used": True, "verified": case != "K2", "reason": None})
                self.assertEqual(result["summary"]["complete"], case not in STOPPED)
                self.assertEqual(result["summary"]["compiled_through_line"], STOPPED.get(case))
                self.assertTrue(all(d["confidence"] == "high" for d in result["diagnostics"]))

    def test_nothing_is_removed_or_reordered_and_input_is_not_changed(self):
        data = PROBES["K16"]
        original = copy.deepcopy(data["diagnostics"])
        result = triage(data["diagnostics"], module_text=data["module"])
        self.assertEqual(data["diagnostics"], original)
        self.assertEqual([(d["line"], d["message"]) for d in result["diagnostics"]],
                         [(d["line"], d["message"]) for d in original])
        self.assertEqual(result["summary"]["to_fix"], [1])

    def test_messages_are_identified_with_their_argument(self):
        result = triage(PROBES["K9"]["diagnostics"], module_text=PROBES["K9"]["module"])
        self.assertEqual([(d["message_id"], d["argument"]) for d in result["diagnostics"]],
                         [(1488, None), (1535, "Ф77"), (1445, None), (1535, "Неизвестная77"), (1531, "НетТакой77")])


class RuleBoundaryTests(unittest.TestCase):
    HEADER = "Процедура Дефект77(Знач Путь77, Знач <<?>>Строка)"

    def module(self, *body, after=()):
        return "\n".join(["Процедура Дефект77(Знач Путь77, Знач Строка)", *body, "КонецПроцедуры", *after]) + "\n"

    def test_swallowed_assignment_needs_the_first_statement_and_no_reassignment(self):
        header = diag(1, "Ожидается имя формального параметра", self.HEADER)
        read = diag(4, "Переменная не определена (Ф77)", "Если Ф77 <<?>>= 1 Тогда")
        swallowed = self.module("    Ф77 = 1;", "    // комментарий", "    Если Ф77 = 1 Тогда", "    КонецЕсли;")
        self.assertEqual(marks(triage([header, read], module_text=swallowed))[1][3], "header-swallowed")
        reassigned = self.module("    Ф77 = 1;", "    Ф77 = 2;", "    Если Ф77 = 1 Тогда", "    КонецЕсли;")
        self.assertEqual(marks(triage([header, read], module_text=reassigned))[1][1], "root")
        not_first = self.module("    Сообщить(1);", "    Ф77 = 1;", "    Если Ф77 = 1 Тогда", "    КонецЕсли;")
        self.assertEqual(marks(triage([header, read], module_text=not_first))[1][1], "root")

    def test_without_module_a_possible_swallow_stays_a_medium_root(self):
        header = diag(1, "Ожидается имя формального параметра", self.HEADER)
        read = diag(4, "Переменная не определена (Ф77)", "Если Ф77 <<?>>= 1 Тогда")
        marked = triage([header, read])["diagnostics"][1]
        self.assertEqual((marked["role"], marked["confidence"]), ("root", "medium"))
        self.assertIn("нужен модуль", marked["explanation"])

    def test_parameter_use_matches_the_whole_name_in_the_same_procedure(self):
        header = diag(1, "Ожидается имя формального параметра", self.HEADER)
        use = diag(2, "Ожидается символ '('", "А77 = Строка<<?>> + 1;")
        longer = diag(2, "Ожидается символ '('", "А77 = МояСтрока<<?>> + 1;")
        module = self.module("    А77 = Строка + 1;", after=["Процедура Другая77()", "    А77 = Строка + 1;",
                                                               "КонецПроцедуры"])
        self.assertEqual(marks(triage([header, use], module_text=module))[1][1:], ("cascade", 1, "header-parameter"))
        self.assertEqual(marks(triage([header, longer]))[1][1], "root")
        elsewhere = diag(5, "Ожидается символ '('", "А77 = Строка<<?>> + 1;")
        self.assertEqual(marks(triage([header, elsewhere], module_text=module))[1][1], "root")
        without_module = triage([header, elsewhere])["diagnostics"][1]
        self.assertEqual((without_module["rule"], without_module["confidence"]), ("header-parameter", "medium"))

    def test_too_many_parameters_only_for_the_failed_procedure(self):
        header = diag(1, "Ожидается имя формального параметра", self.HEADER)
        own = diag(5, "Слишком много фактических параметров", 'Дефект77("a", <<?>>"x");')
        other = diag(5, "Слишком много фактических параметров", 'Другая77(<<?>>"x");')
        self.assertEqual(marks(triage([header, own]))[1][1:], ("cascade", 1, "header-call"))
        self.assertEqual(marks(triage([header, other]))[1][1], "root")

    def test_end_expected_follows_only_a_header_error(self):
        end = diag(2, "Ожидается ключевое слово 'КонецПроцедуры' ('EndProcedure')", "<<?>>Процедура Б() Далее")
        after_header = [diag(1, "Ожидается имя формального параметра", "Процедура А(Знач <<?>>Строка) Далее"), end]
        self.assertEqual(marks(triage(after_header))[1][3], "header-end")
        after_statement = [diag(1, "Ожидается выражение", "А =<<?>> ;"), end]
        self.assertEqual(marks(triage(after_statement))[1][1], "root")

    def test_redefinition_is_a_cascade_only_after_a_failed_forward_declaration(self):
        redefined = diag(5, "Процедура или функция с указанным именем уже определена в текущем модуле (А)",
                         "Процедура <<?>>А(Знач Стр77)")
        forward = diag(1, "Ожидается имя формального параметра", "Процедура А(Знач <<?>>Строка) Далее")
        definition = diag(1, "Ожидается имя формального параметра", "Процедура А(Знач <<?>>Строка)")
        self.assertEqual(marks(triage([forward, redefined]))[1][3], "header-redefined")
        self.assertEqual(marks(triage([definition, redefined]))[1][1], "root")

    def test_same_line_continues_a_cascade_but_not_a_root(self):
        # 59473c46: two undefined variables on one line are both roots.
        two = [diag(4, "Переменная не определена (Тип77)", "Т.П(1, Тип77<<?>>, Длина77);"),
               diag(4, "Переменная не определена (Длина77)", "Т.П(1, Тип77, Длина77<<?>>);")]
        self.assertEqual([m[1] for m in marks(triage(two))], ["root", "root"])
        after_root = [diag(2, "Ожидается выражение", "А =<<?>> + ;"), diag(2, "Неопознанный оператор", "А = <<?>>+ ;")]
        self.assertEqual(marks(triage(after_root))[1][1], "root")

    def test_logical_end_stops_compilation(self):
        alone = triage([diag(3, "Обнаружено логическое завершение исходного текста модуля", "Процедура = 1;<<?>>")])
        self.assertEqual((marks(alone)[0][1], alone["summary"]["compiled_through_line"]), ("root", 3))
        after_root = triage([diag(1, "Ожидается выражение", "А =<<?>> ;"),
                             diag(2, "Обнаружено логическое завершение исходного текста модуля", "Б<<?>>")])
        second = after_root["diagnostics"][1]
        self.assertEqual((second["role"], second["cause"], second["confidence"]), ("cascade", 1, "medium"))
        self.assertFalse(after_root["summary"]["complete"])

    def test_unresolved_forward_declaration(self):
        stop = [diag(1, "Ожидается выражение", "А =<<?>> ;"),
                diag(1, "Процедура или функция с указанным именем объявлена, но не определена в текущем модуле (Б)",
                     "А =<<?>> ;")]
        with_definition = "А = ;\nПроцедура Б()\nКонецПроцедуры\n"
        result = triage(stop, module_text=with_definition)
        self.assertEqual(marks(result)[1][1:], ("cascade", 1, "stopped"))
        self.assertEqual(result["summary"]["compiled_through_line"], 1)
        genuine = triage(stop, module_text="А = ;\n")
        self.assertEqual((marks(genuine)[1][1], genuine["summary"]["complete"]), ("root", True))
        guessed = triage(stop)["diagnostics"][1]
        self.assertEqual((guessed["rule"], guessed["confidence"]), ("stopped", "medium"))
        at_end = triage([stop[0], {"line": 2, "message": stop[1]["message"]}])
        self.assertEqual((marks(at_end)[1][1], at_end["summary"]["complete"]), ("root", True))

    def test_unknown_message_and_root_confidence(self):
        result = triage([diag(2, "Ожидается выражение", "А =<<?>> ;"), {"line": 3, "message": "Сообщение 1С++"},
                         diag(4, "Переменная не определена (Б)", "В = Б<<?>>;")],
                        module_text="Процедура П()\n    А = ;\n    Х = 1;\n    В = Б;\nКонецПроцедуры\n")
        self.assertEqual([(d["role"], d["confidence"]) for d in result["diagnostics"]],
                         [("root", "high"), ("unknown", "low"), ("root", "medium")])
        self.assertEqual(result["summary"]["unknown"], 1)

    def test_a_module_of_other_text_is_not_used(self):
        data = PROBES["K9"]
        other = data["module"].replace("Ф77 = 1;", "Ф78 = 1;")
        result = triage(data["diagnostics"], module_text="\n" + data["module"])
        self.assertFalse(result["module"]["used"])
        self.assertIn("не совпадает", result["module"]["reason"])
        # Only lines with diagnostics are compared: this module is used, and its first
        # statement assigns Ф78, so Ф77 is no longer explained by the header.
        self.assertEqual(marks(triage(data["diagnostics"], module_text=other))[1][1], "root")
        lines_only = [{"line": d["line"], "message": d["message"]} for d in data["diagnostics"]]
        unverified = triage(lines_only, module_text=data["module"])
        self.assertEqual(unverified["module"], {"used": True, "verified": False, "reason": None})
        self.assertEqual(marks(unverified)[1][3], "header-swallowed")

    def test_a_catalog_of_another_layout_is_refused(self):
        catalog = catalog77.load_packaged()
        broken = dict(catalog, messages=[m for m in catalog["messages"] if m["id"] != 1535])
        with self.assertRaises(ValueError):
            triage([diag(1, "Ожидается выражение", "А =<<?>> ;")], catalog=broken)


class KudirProtocolTests(unittest.TestCase):
    """P1/P2 of the KUDiR corpus without the module (the module stays local)."""

    def protocol(self, name):
        return read_protocol((FIXTURES / "compiler_protocol77" / name).read_bytes())

    def test_p1_without_module(self):
        parsed = self.protocol("p1.txt")
        self.assertEqual(parsed["kind"], "configurator")
        result = triage(parsed["diagnostics"])
        roots = [(d["line"], d["confidence"]) for d in result["diagnostics"] if d["role"] == "root"]
        # Header errors are certain; 306-309 need the module to be recognised as swallowed.
        self.assertEqual(roots, [(63, "high"), (66, "high"), (101, "medium"), (107, "medium"), (304, "high"),
                                 (306, "medium"), (307, "medium"), (309, "medium")])
        summary = result["summary"]
        self.assertEqual((summary["cascade"], summary["complete"], summary["compiled_through_line"]), (52, False, 311))
        rules = [d["rule"] for d in result["diagnostics"] if d["line"] == 311]
        self.assertEqual(rules[:2], ["header-parameter", "same-line"])
        self.assertEqual(set(rules[2:]), {"stopped"})

    def test_p2_is_seven_links(self):
        result = triage(self.protocol("p2.txt")["diagnostics"])
        self.assertEqual((result["summary"]["link"], result["summary"]["root"], result["summary"]["complete"]),
                         (7, 0, True))


class ProtocolFileTests(unittest.TestCase):
    NATIVE = ("HARNESS77-BEGIN:r:check\r\n"
              "А =<<?>> ; // probe\r\n"
              "{C:\\R\\ОБРАБОТКА.ERT(4)}: Ожидается выражение\r\n"
              "HARNESS77-END:r:check\r\n")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-triage-")
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def test_native_protocol_has_no_terminator(self):
        for data in (self.NATIVE.encode("cp1251"), b"\xff\xfe" + self.NATIVE.encode("utf-16-le")):
            with self.subTest(size=len(data)):
                parsed = read_protocol(data)
                self.assertEqual((parsed["kind"], parsed["issues"]), ("platform_load", []))
                self.assertEqual(parsed["diagnostics"][0]["column"], 4)

    def test_unreadable_protocol_is_blocked(self):
        parsed = read_protocol("не протокол\r\n".encode("cp1251"))
        self.assertTrue(parsed["issues"])

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "harness77", "triage", *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8")

    def test_command_writes_a_new_file_only(self):
        protocol = self.dir / "check.txt"
        protocol.write_bytes(self.NATIVE.encode("cp1251"))
        source = self.dir / "module.1s"
        source.write_text("Процедура П()\n\n\n    А = ; // probe\nКонецПроцедуры\n", encoding="utf-8")
        printed = self.cli(protocol, "--source", source)
        self.assertEqual(printed.returncode, 1, printed.stderr)
        report = json.loads(printed.stdout)
        self.assertEqual((report["operation"], report["status"], report["protocol"]["kind"]),
                         ("triage", "failed", "platform_load"))
        self.assertEqual(report["protocol"]["sha256"], hashlib.sha256(protocol.read_bytes()).hexdigest())
        self.assertEqual((report["module"]["used"], report["module"]["kind"]), (True, "source"))
        self.assertEqual(report["summary"]["to_fix"], [1])
        output = self.dir / "triage.json"
        self.assertEqual(self.cli(protocol, "--output", output).returncode, 1)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["summary"]["root"], 1)
        output.write_text("keep", encoding="utf-8")
        refused = self.cli(protocol, "--output", output)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_blocked_protocol_has_no_marking(self):
        protocol = self.dir / "bad.txt"
        protocol.write_bytes("не протокол\r\n".encode("cp1251"))
        result = self.cli(protocol)
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "blocked")
        self.assertNotIn("diagnostics", report)


if __name__ == "__main__":
    unittest.main()
