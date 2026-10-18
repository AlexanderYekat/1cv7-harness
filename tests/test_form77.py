"""Form description (task 008): lossless extract, supported changes and explicit refusals."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from harness77 import ert_module as ert
from harness77 import form77
from harness77.artifacts import build
from harness77.cli import main as cli
from harness77.config77 import load_project
from harness77.lint77 import dialog_context
from test_ert_dialog import DIALOG, MODULE, make_ert, streams

# The unnamed section some 1C forms have before Controls (57 of 416 in the survey).
SECTION_DIALOG = DIALOG.replace('\r\n{"Controls",', '\r\n{\r\n{\r\n{}},\r\n{}},\r\n{"Controls",', 1)
FRAME = ['0'] * 14 + ['40', '40', 'x'] + ['0'] * 11
SMALL = '{"Dialogs",\r\n{"Frame",\r\n{' + ','.join(f'"{v}"' for v in FRAME) + \
        ',\r\n{"0",\r\n{"L","1"}}}},\r\n{"Controls"}}  '
BUTTON = {"class": "BUTTON", "caption": "Проверка", "x": 200, "y": 16, "width": 66, "height": 13,
          "formula": "ВыгрузкаЭ02()"}


def described(text=DIALOG):
    return form77.describe(text)


def apply(description, text=DIALOG, module=MODULE):
    return form77.apply(text, description, module)


def records(text):
    root = ert.parse_dialog(text)
    return [s for s in root[1:] if s[:1] == ["Controls"]][0][1:]


class LayoutTests(unittest.TestCase):
    def test_canonical_layout_round_trips(self):
        for text in (DIALOG, SECTION_DIALOG, SMALL):
            with self.subTest(text=text[-30:]):
                self.assertEqual(form77.serialize_dialog(ert.parse_dialog(text)), text)

    def test_other_layout_refused(self):
        for text in (DIALOG.replace('\r\n', '\n'), DIALOG.rstrip(), DIALOG.replace(',\r\n{"Cnt_Ver"', ',{"Cnt_Ver"')):
            with self.subTest(text=text[-30:]), self.assertRaisesRegex(ert.ErtError, 'разметке'):
                form77.describe(text)

    def test_unknown_structure_refused(self):
        for text in ('{"Other"}  ', '{"Dialogs",\r\n{"Controls"}}  ', '{"Dialogs",\r\n{"Frame",\r\n{"0"}},\r\n{"Controls"}}  '):
            with self.subTest(text=text), self.assertRaises(ert.ErtError):
                form77.describe(text)


class DescribeTests(unittest.TestCase):
    def test_properties(self):
        description = described()
        self.assertEqual(description["form"], {"caption": " ", "width": 320, "height": 165, "layers": ["Основной"]})
        self.assertEqual(description["controls"][2], {
            "id": 4154, "class": "BMASKED", "caption": 'Дата "с"', "x": 70, "y": 142, "width": 54, "height": 14,
            "formula": "", "identifier": "выбДатаНач", "layer": "Основной"})
        self.assertEqual(description["template_dialog_sha256"], form77.sha256(DIALOG.encode("cp1251")))

    def test_json_round_trip_and_unchanged_apply(self):
        description = form77.loads(form77.dumps(described(SECTION_DIALOG)).encode("utf-8"))
        self.assertEqual(apply(description, SECTION_DIALOG), (SECTION_DIALOG, []))

    def test_dumps_is_stable_utf8_lf(self):
        text = form77.dumps(described())
        self.assertEqual(text, form77.dumps(described()))
        self.assertNotIn("\r", text)
        self.assertIn("Закрыть", text)

    def test_loads_refuses_bad_shapes(self):
        good = described()
        cases = {
            "schema": dict(good, schema="other"),
            "schema_version": dict(good, schema_version=2),
            "неизвестные свойства": dict(good, extra=1),
            "form": dict(good, form=dict(good["form"], color="red")),
            "нужен тип int": dict(good, controls=[dict(good["controls"][0], x=True)]),
            "нужен тип str": dict(good, controls=[dict(good["controls"][0], caption=5)]),
            "нет свойств class": dict(good, controls=[{"caption": "x"}]),
        }
        for message, description in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ert.ErtError, message):
                form77.loads(json.dumps(description).encode("utf-8"))
        with self.assertRaisesRegex(ert.ErtError, "JSON"):
            form77.loads(b"{")


class ChangeTests(unittest.TestCase):
    def test_new_button_uses_the_default_record(self):
        description = described()
        description["controls"].append(dict(BUTTON))
        text, changes = apply(description)
        self.assertEqual(changes, [{"control": 4155, "added": "BUTTON"}])
        record = records(text)[-1]
        expected = list(form77.DEFAULT_BUTTON)
        for index, value in ((0, "Проверка"), (3, "200"), (4, "16"), (5, "66"), (6, "13"), (9, "4155"),
                             (11, "ВыгрузкаЭ02()"), (12, ""), (41, "Основной")):
            expected[index] = value
        self.assertEqual(record, expected)
        self.assertEqual(records(text)[:3], records(DIALOG))
        self.assertEqual(form77.serialize_dialog(ert.parse_dialog(text)), text)

    def test_default_record_matches_the_corpus_button(self):
        # The "Закрыть" record of the test dialog follows the most frequent corpus button.
        close = records(DIALOG)[0]
        default = list(form77.DEFAULT_BUTTON)
        for index in (0, 3, 4, 5, 6, 9, 11, 12, 41):
            default[index] = close[index]
        self.assertEqual(default, close)

    def test_explicit_id_and_global_function_formula(self):
        description = described()
        description["controls"].append(dict(BUTTON, id=4155, formula='Сообщить("Проверка")', identifier="кнПроверка"))
        description["controls"].append(dict(BUTTON, x=100))
        text, _ = apply(description)
        self.assertEqual([(r[9], r[12]) for r in records(text)[3:]], [("4155", "кнПроверка"), ("4156", "")])

    def test_existing_properties_change(self):
        description = described()
        description["form"]["caption"] = "Новая"
        button = description["controls"][1]
        button.update(caption="Набор", x=10, y=20, formula="ВыгрузкаЭ02( )", identifier="кнНабор")
        text, changes = apply(description)
        self.assertEqual([(c["control"], c["property"]) for c in changes], [
            (None, "caption"), (4153, "caption"), (4153, "x"), (4153, "y"), (4153, "formula"), (4153, "identifier")])
        record = records(text)[1]
        self.assertEqual((record[0], record[3], record[4], record[11], record[12]),
                         ("Набор", "10", "20", "ВыгрузкаЭ02( )", "кнНабор"))
        self.assertEqual(form77.describe(text)["form"]["caption"], "Новая")

    def test_refusals(self):
        def change(edit, text=DIALOG, module=MODULE):
            description = described(text)
            edit(description)
            return lambda: form77.apply(text, description, module)

        def new(**values):
            return lambda d: d["controls"].append(dict(BUTTON, **values))

        def control(number, **values):
            return lambda d: d["controls"][number].update(values)

        cases = {
            "другого шаблона": change(lambda d: d.update(template_dialog_sha256="0" * 64)),
            "Удаление": change(lambda d: d["controls"].pop()),
            "перестановка": change(lambda d: d["controls"].reverse()),
            "смена ID": change(control(0, id=4999)),
            "ID/класса": change(control(2, **{"class": "1CEDIT"})),
            "класса STATIC не поддерживается": change(new(**{"class": "STATIC"})),
            "только следующий по порядку 4155, получено 4152": change(new(id=4152)),
            "получено 5000": change(new(id=5000)),
            "не идут подряд": change(new(), text=DIALOG.replace('"4153"', '"4999"', 1)),
            "выходит за клиентскую область": change(new(x=300)),
            r"\[4, 317\]×\[15, 162\] \(форма 320×165\)": change(control(1, y=150)),
            "клиентскую область формы": change(new(y=14)),
            "за клиентскую": change(new(x=3)),
            "вызовом Имя": change(new(formula="#Закрыть")),
            "НетТакой": change(new(formula="НетТакой()")),
            "элемента BMASKED не поддерживается": change(control(2, formula="ВыгрузкаЭ02()")),
            "вне Windows-1251": change(new(caption="✓")),
            "слоя 'Нет'": change(new(layer="Нет")),
            "уже есть": change(new(identifier="ВыбДатаНач")),
            "не годится": change(new(identifier="1кн")),
            "'Если' не годится": change(new(identifier="Если")),
            "слоёв": change(lambda d: d["form"]["layers"].append("Второй")),
            "больше нуля": change(lambda d: d["form"].update(width=0)),
            "при сборке с модулем": change(new(), module=None),
            "прежнего формата": change(new(), text=DIALOG.replace(',"{""0"",""0""}"}', '}', 1)),
            "нет свойств": change(lambda d: d["controls"].append({"class": "BUTTON", "caption": "x"})),
        }
        for message, call in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ert.ErtError, message):
                call()

    def test_template_names_are_not_revalidated(self):
        # A corpus form names a field "Дата" (a reserved word); 1C accepted it, so only
        # identifiers and layers the description sets are checked.
        text = DIALOG.replace('"выбДатаНач"', '"Дата"')
        text = text.replace(',"Основной","{""0"",""0""}"}', ',"Старый","{""0"",""0""}"}', 1)
        description = described(text)
        self.assertEqual(form77.apply(text, description, MODULE), (text, []))
        description["controls"][0]["caption"] = "Выход"
        self.assertEqual(len(form77.apply(text, description, MODULE)[1]), 1)
        for edit, message in ((lambda d: d["controls"][1].update(identifier="Дата"), "не годится"),
                              (lambda d: d["controls"][1].update(identifier="дата2"), None),
                              (lambda d: d["controls"][0].update(layer="Нет"), "слоя 'Нет'")):
            changed = described(text)
            edit(changed)
            with self.subTest(message):
                if message:
                    with self.assertRaisesRegex(ert.ErtError, message):
                        form77.apply(text, changed, MODULE)
                else:
                    form77.apply(text, changed, MODULE)

    def test_duplicate_of_template_identifier_refused(self):
        description = described()
        description["controls"][1]["identifier"] = "ВЫБДАТАНАЧ"
        with self.assertRaisesRegex(ert.ErtError, "уже есть у элемента 4154"):
            apply(description)

    def test_prefix_kind_change_refused(self):
        description = described(SMALL)
        description["controls"].append(dict(BUTTON, x=4, y=15, width=5, height=5, formula="Сообщить(1)", layer="L"))
        text, _ = form77.apply(SMALL, description, MODULE)
        with self.assertRaisesRegex(ert.ErtError, "сменил бы вид"):
            form77.dialog_payload(text, ert.encode_dialog(SMALL))


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-form-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = self.root / "form.ert"
        self.template.write_bytes(make_ert(ert.encode_dialog(DIALOG)))
        self.source = self.root / "module.1s"
        self.source.write_bytes(MODULE.encode("cp1251"))

    def description(self, edit=None, name="form.json"):
        description = described()
        if edit:
            edit(description)
        path = self.root / name
        path.write_text(form77.dumps(description), encoding="utf-8")
        return path

    def test_unchanged_form_keeps_every_stream(self):
        report = build(self.template, self.source, self.root / "out.ert", form=self.description())
        self.assertEqual(streams(self.root / "out.ert"), streams(self.template))
        self.assertTrue(report["form"]["dialog_unchanged"])
        self.assertEqual(report["form"]["changes"], [])
        self.assertTrue(report["verification"]["dialog"])
        self.assertNotIn(ert.DIALOG_STREAM, [s["path"] for s in report["preserved_streams"]])

    def test_new_button_build_is_verified_and_reproducible(self):
        form = self.description(lambda d: d["controls"].append(dict(BUTTON)))
        before = {p: p.read_bytes() for p in (self.template, self.source, form)}
        first = build(self.template, self.source, self.root / "a.ert", form=form)
        second = build(self.template, self.source, self.root / "b.ert", form=form)
        self.assertEqual((self.root / "a.ert").read_bytes(), (self.root / "b.ert").read_bytes())
        self.assertEqual(first["output"]["sha256"], second["output"]["sha256"])
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        controls = ert.dialog_controls(ert.extract_dialog(self.root / "a.ert"))
        self.assertEqual((controls[-1].control_id, controls[-1].caption, controls[-1].formula),
                         ("4155", "Проверка", "ВыгрузкаЭ02()"))
        old, new = streams(self.template), streams(self.root / "a.ert")
        self.assertEqual(old["Container.Contents"], new["Container.Contents"])
        self.assertEqual(old[ert.MODULE_STREAM], new[ert.MODULE_STREAM])
        self.assertEqual(first["form"]["changes"], [{"control": 4155, "added": "BUTTON"}])

    def test_refused_form_publishes_nothing(self):
        form = self.description(lambda d: d["controls"].append(dict(BUTTON, formula="НетТакой()")))
        with self.assertRaisesRegex(ert.ErtError, "НетТакой"):
            build(self.template, self.source, self.root / "out.ert", form=form)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["form.ert", "form.json", "module.1s"])

    def test_cli_form_extract_and_build(self):
        output = self.root / "extracted.json"
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli(["form-extract", str(self.template), "--output", str(output)]), 0)
        self.assertEqual(json.loads(out.getvalue())["controls"], 3)
        self.assertEqual(form77.loads(output.read_bytes()), described())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli(["form-extract", str(self.template), "--output", str(output)]), 2)
        self.assertIn("уже существует", json.loads(err.getvalue())["error"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli(["build", "--template", str(self.template), "--source", str(self.source),
                                  "--form", str(output), "--output", str(self.root / "cli.ert")]), 0)
        self.assertTrue(json.loads(out.getvalue())["form"]["dialog_unchanged"])

    def test_lint_and_profile_take_the_description(self):
        form = self.description(lambda d: d["controls"].append(dict(BUTTON, identifier="кнПроверка")))
        self.assertEqual(dialog_context(form), frozenset({"выбдатанач", "кнпроверка"}))
        profile = self.root / "project.toml"
        profile.write_text("schema_version = 1\n[project]\nid = 'p'\n[build]\ntemplate = 'form.ert'\n"
                           "source = 'module.1s'\nform = 'form.json'\n", encoding="utf-8")
        project = load_project(profile)
        self.assertEqual(project.form, self.root / "form.json")
        self.assertEqual(project.public()["form"]["name"], "form.json")


if __name__ == "__main__":
    unittest.main()
