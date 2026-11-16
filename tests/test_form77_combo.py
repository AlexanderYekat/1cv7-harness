"""Creation of a drop-down list in an ERT template (task 107)."""
import unittest

from harness77 import ert_module as ert, form77
from test_form77 import DIALOG, MODULE, records, tall


COMBO = {"class": "COMBOBOX", "identifier": "Список77", "formula": "ВыгрузкаЭ02()",
         "x": 10, "y": 170, "width": 100, "height": 60}


class ComboTests(unittest.TestCase):
    def description(self, **changes):
        d = tall(dict(COMBO, **changes))
        d["form"]["height"] = 240
        return d

    def test_new_list_round_trip_and_binding(self):
        text, changes = form77.apply(DIALOG, self.description(), MODULE)
        record = records(text)[-1]
        self.assertEqual((record[1], record[2], record[14], record[19]),
                         ("COMBOBOX", "1352663107", "U", "16777216"))
        self.assertEqual((record[11], record[12], record[6]), ("ВыгрузкаЭ02()", "Список77", "60"))
        self.assertEqual(changes[-1], {"control": 4155, "added": "COMBOBOX"})
        self.assertIn("список77", form77.dialog_identifiers(form77.describe(text)))
        self.assertEqual(form77.apply(text, form77.describe(text), MODULE), (text, []))
        # The template's original records remain literal, including unknown properties.
        self.assertEqual(records(text)[:-1], records(DIALOG))

    def test_explicit_undefined_and_optional_handler(self):
        text, _ = form77.apply(DIALOG, self.description(type={"kind": "undefined"}, formula=""), MODULE)
        self.assertEqual(records(text)[-1][11], "")

    def test_refusals(self):
        for changes, message in [
            ({"identifier": ""}, "нет свойств identifier"),
            ({"type": {"kind": "string"}}, "не подходит"),
            ({"type": {"kind": "undefined", "length": 1}}, "без длины"),
            ({"formula": "НетПроцедуры()"}, "которого нет"),
            ({"formula": "Список77 + 1"}, "должна быть вызовом"),
            ({"identifier": "выбДатаНач"}, "уже есть"),
            ({"y": 235}, "клиентскую область"),
            ({"y": 140}, "накладывается"),
        ]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ert.ErtError, message):
                form77.apply(DIALOG, self.description(**changes), MODULE)
        with self.assertRaisesRegex(ert.ErtError, "переменной Перем"):
            form77.apply(DIALOG, self.description(), "Перем Список77;\n" + MODULE)
        with self.assertRaisesRegex(ert.ErtError, "только в форме ERT"):
            form77.apply(DIALOG, self.description(), MODULE, context=form77.FormContext())


if __name__ == "__main__":
    unittest.main()
