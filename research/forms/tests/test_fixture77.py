"""Task 024: copy-only fixture contract and observable failures; real 1C is tested separately."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fixture77
import form_launcher77 as form


class FixtureTests(unittest.TestCase):
    def parameters(self, **changes):
        return dict(form_object="Справочник.Банки.ФормаЭлемента", fixture_setup="Возврат 0;", **changes)

    def test_invalid_combinations_are_refused_before_a_session(self):
        cases = [{"fixture_setup": "Возврат 0;"}, {"fixture_mode": "existing"},
                 dict(self.parameters(), fixture_setup=""), dict(self.parameters(), fixture_setup=1),
                 self.parameters(fixture_mode="anything"), self.parameters(fixture_verify=""),
                 dict(self.parameters(), form_object="Журнал.Банк.ФормаСписка.Основная"),
                 dict(self.parameters(fixture_mode="owner"), form_object="Документ.Платеж"),
                 dict(self.parameters(), fixture_setup="Возврат 0;\0")]
        for parameters in cases:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                form.FormAdapter().commands(parameters, [])

    def test_original_base_is_refused_before_reading_or_preparing_data(self):
        adapter = form.FormAdapter()
        adapter.commands(self.parameters(), [])
        with self.assertRaisesRegex(ValueError, "verified base copy"):
            adapter.select_base(Path("does-not-exist"))

    def test_verify_must_be_an_explicit_test(self):
        adapter = form.FormAdapter()
        parameters = self.parameters(fixture_verify='Возврат "done";')
        with self.assertRaisesRegex(ValueError, "declared platform test"):
            adapter.commands(parameters, ["open", "result"])
        self.assertEqual(adapter.commands(parameters, ["verify"]), ["check", "open", "result", "verify"])
        with self.assertRaisesRegex(ValueError, "unknown form command"):
            adapter.commands(self.parameters(), ["verify"])

    def test_reference_contract_comes_from_selected_form_and_owner_metadata(self):
        metadata = Mock()
        metadata.catalog.return_value = {"owner": "Контрагенты"}
        self.assertEqual(fixture77.context("Справочник.Договоры.ФормаЭлемента", {"mode": "owner"}, metadata),
                         {"type": "Справочник", "kind": "Контрагенты", "group": 0})
        self.assertEqual(fixture77.context("Справочник.Банки.ФормаГруппы", {"mode": "existing"}, metadata)["group"], 1)
        self.assertEqual(fixture77.context("Документ.Платеж", {"mode": "existing"}, metadata)["type"], "Документ")
        metadata.catalog.return_value = {"owner": None}
        with self.assertRaisesRegex(ValueError, "subordinate catalog"):
            fixture77.context("Справочник.Банки.ФормаЭлемента", {"mode": "owner"}, metadata)

    def test_posting_requires_document_copy_verification_and_explicit_test(self):
        parameters = dict(form_object="Документ.ГотоваяПродукция", fixture_setup="Возврат 0;",
                          fixture_verify='Возврат "0";', fixture_post=True)
        for changes in ({"fixture_post": False}, {"fixture_post": 1}, {"fixture_verify": None},
                        {"form_object": "Справочник.Банки.ФормаЭлемента"}, {"fixture_mode": "owner"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                form.FormAdapter().commands(dict(parameters, **changes), ["post", "verify"])
        adapter = form.FormAdapter()
        with self.assertRaisesRegex(ValueError, "command post"):
            adapter.commands(parameters, ["verify"])
        self.assertEqual(adapter.commands(parameters, ["post", "verify"]),
                         ["check", "open", "result", "post", "verify"])
        with self.assertRaisesRegex(ValueError, "verified base copy"):
            adapter.select_base(Path("does-not-exist"))
        context = {"type": "Документ", "kind": "ГотоваяПродукция", "group": 0}
        # Controller generation runs here too: catches invalid code composition before a native session.
        self.assertIn('Док77Проверки.Проведен()', form.controller_text(parameters, context))

    def test_posting_checks_return_and_fresh_state_and_preserves_refusal(self):
        for returned, posted, status in ((1, 1, "passed"), (0, 0, "failed"),
                                          (1, 0, "failed"), (0, 1, "failed")):
            row = {"diagnostics": []}
            handled, issue = fixture77.operation("post", [f"post-return:{returned}", f"post-posted:{posted}"], row)
            self.assertTrue(handled)
            self.assertIsNone(issue)
            self.assertEqual((row["status"], row["value"]), (status, f"{returned}|{posted}"))
            self.assertEqual(row["posting"], {"returned": returned, "posted": posted, "errors": []})
        row = {"diagnostics": []}
        self.assertEqual(fixture77.operation("post", ["post-error:division by zero"], row), (True, None))
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["posting"]["errors"], ["division by zero"])
        row = {"diagnostics": [{"message": "ошибка модуля"}]}
        fixture77.operation("post", ["post-return:1", "post-posted:1"], row)
        self.assertEqual(row["status"], "failed")

    def test_missing_or_ambiguous_posting_evidence_is_blocked(self):
        for lines in ([], ["post-return:1"], ["post-return:yes", "post-posted:1"],
                      ["post-return:1", "post-posted:1", "post-posted:1"],
                      ["post-return:1", "post-posted:1", "unknown:1"]):
            with self.subTest(lines=lines):
                row = {"diagnostics": []}
                handled, issue = fixture77.operation("post", lines, row)
                self.assertTrue(handled)
                self.assertIn("protocol_invalid", issue)
                self.assertEqual(row["status"], "blocked")

    def test_setup_failure_cannot_turn_into_successful_form_test(self):
        adapter = form.FormAdapter()
        for command in ("check", "open", "result", "verify"):
            row = {"diagnostics": []}
            error = adapter.operation(command, ["fixture-error:empty reference"], "", row)
            self.assertEqual(row["status"], "blocked")
            self.assertIn("fixture_setup_failed", error)

    def test_verification_is_not_a_form_marker_and_errors_fail(self):
        adapter = form.FormAdapter()
        for lines, status, value in [(["selected:x", "fixture-value:saved"], "passed", "saved"),
                                     (["fixture-verify-error:read failed"], "failed", None),
                                     ([], "failed", None),
                                     (["fixture-value:a", "fixture-value:b"], "failed", None),
                                     (["fixture-value:a", "extra line"], "failed", "a")]:
            row = {"name": "verify", "diagnostics": [], "value": None}
            self.assertIsNone(adapter.operation("verify", lines, "", row))
            self.assertEqual((row["status"], row["value"]), (status, value))
            # The required declared test judges verify, just as the form/result operations.
            # This also allows an explicitly expected failed verification as a negative test.
            self.assertEqual(adapter.platform_status([row]), "passed")


if __name__ == "__main__":
    unittest.main()
