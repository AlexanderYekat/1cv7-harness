"""Reference-typed form fields (tasks 012, 013): names by the ERT's copy, the target base by names."""

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
from harness77.metadata77 import Metadata
from stage4_fixtures import base_scenario, run, write_project, write_sim_stand
from harness77.metadata77 import STREAM
from test_ert_dialog import DIALOG, MODULE, make_ert, streams
from test_form77 import TALL, described, records
from test_metadata77 import EMPTY_TEXT, MD_TEXT, make_ert_with_copy, make_md, other_md

# (identifier, code, number) of the template's reference fields: a kind, any, and
# «Тарифы» of an earlier release of the configuration (25507, as Договор_Оргтехники.ert
# in the corpus; the base has 26051).
FIELDS = (("Контрагент", "B", "133"), ("ЛюбойСправочник", "B", "0"), ("Документ", "O", "0"),
          ("Пол", "E", "21439"), ("Счет", "T", "809"), ("ВидСубконто", "K", "0"), ("Тариф", "B", "25507"))
STAFF = '{"208","Сотрудники","","Сотрудники","0"}}'
# The target base: «Тарифы» under 26051 and «ТипыЦен», which the template's copy lacks.
BASE_TEXT = MD_TEXT.replace(STAFF, STAFF[:-1] + ',\r\n{"26051","Тарифы","","","0"},\r\n{"26080","ТипыЦен","","","0"}}')
# The template's copy: the earlier release.
COPY_TEXT = MD_TEXT.replace(STAFF, STAFF[:-1] + ',\r\n{"25507","Тарифы","","","0"}}').replace(
    "Тестовая конфигурация", "Тестовая конфигурация, прежний выпуск")
# The same names under other numbers.
OTHER_TEXT = (BASE_TEXT.replace('"133","Контрагенты"', '"150","Контрагенты"').replace('"809","Основной"', '"901","Основной"')
              .replace('"26051","Тарифы"', '"30000","Тарифы"').replace("Тестовая", "Другая"))
# Another configuration, as Торговля+Склад 9.2: «Контрагенты» under 172, no «Пол», «Тарифы» or plans.
FOREIGN_TEXT = ('{\r\n{"MainDataContDef","48514","10011","7120"},\r\n{"TaskItem",\r\n{"1","Другая конфигурация",'
                '"7.70.027","","","1","493","0","0","493"}},\r\n{"SbCnts",\r\n{"172","Контрагенты","","","0"},\r\n'
                '{"219","ТипыЦен","","","0"}},\r\n{"Documents"},\r\n{"EnumList"},\r\n{"Buh",\r\n{"2","","",\r\n'
                '{"Plans"}}}}')


def reference_dialog(fields=FIELDS):
    """The test dialog plus a BMASKED field per FIELDS, 4155 onwards, in a 320×260 form."""
    tree = ert.parse_dialog(DIALOG)
    frame = [s for s in tree[1:] if s[:1] == ["Frame"]][0][1]
    frame[form77.FRAME_HEIGHT] = "260"
    section = [s for s in tree[1:] if s[:1] == ["Controls"]][0]
    for number, (name, code, object_id) in enumerate(fields):
        record = list(section[3])
        record[form77.CAPTION], record[form77.IDENTIFIER] = "", name
        record[form77.ID], record[form77.Y] = str(4155 + number), str(20 + 16 * number)
        record[form77.X], record[form77.WIDTH] = "200", "100"
        record[14:18] = [code, "0", "0", object_id]
        section.append(record)
    return form77.serialize_dialog(tree)


def copy_of(text):
    """The copy of the metadata an ERT carries, as metadata77 reads it."""
    return Metadata.of_ert(ert.CompoundFile(make_ert_with_copy('{"Dialogs"}', text)))


TEXT = reference_dialog()
NAMED = ["Справочник.Контрагенты", "Справочник", "Документ", "Перечисление.Пол", "Счет.Основной",
         "ВидСубконто", "Справочник.Тарифы"]
NUL = bytes(1)
FIELD = {"class": "BMASKED", "identifier": "Новое77", "x": 14, "y": 170, "width": 120, "height": 13}


def field(name, **extra):
    return dict(FIELD, type={"kind": "reference", "object": name}, **extra)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.base = Metadata(make_md(BASE_TEXT))
        self.copy = copy_of(COPY_TEXT)
        self.foreign = Metadata(make_md(FOREIGN_TEXT))


class DescribeTests(Fixture):
    def types(self, description):
        return [c["type"] for c in description["controls"][3:]]

    def test_without_names_kinds_are_numbers_and_any_is_named(self):
        self.assertEqual(self.types(form77.describe(TEXT)), [
            {"kind": "reference", "code": "B", "object_id": 133}, {"kind": "reference", "object": "Справочник"},
            {"kind": "reference", "object": "Документ"}, {"kind": "reference", "code": "E", "object_id": 21439},
            {"kind": "reference", "code": "T", "object_id": 809}, {"kind": "reference", "object": "ВидСубконто"},
            {"kind": "reference", "code": "B", "object_id": 25507}])

    def test_the_copy_names_the_kinds_it_has(self):
        self.assertEqual([t.get("object") for t in self.types(form77.describe(TEXT, self.copy))], NAMED)
        self.assertEqual(form77.by_number(form77.describe(TEXT, self.copy)), [])
        # A copy without 25507 leaves it a number.
        types = self.types(form77.describe(TEXT, copy_of(MD_TEXT)))
        self.assertEqual(types[-1], {"kind": "reference", "code": "B", "object_id": 25507})

    def test_version_2_keeps_other_with_code(self):
        self.assertEqual(self.types(form77.describe(TEXT, version=2))[0], {"kind": "other", "code": "B"})

    def test_every_form_rebuilds_byte_for_byte(self):
        for name, metadata in (("none", None), ("base", self.base), ("other numbers", Metadata(make_md(OTHER_TEXT)))):
            for version in (2, 3):
                with self.subTest(metadata=name, version=version):
                    description = form77.loads(form77.dumps(
                        form77.describe(TEXT, self.copy, version)).encode("utf-8"))
                    self.assertEqual(form77.apply(TEXT, description, MODULE, metadata, self.copy), (TEXT, []))

    def test_needs_metadata_for_a_kind_by_name_or_number(self):
        self.assertTrue(form77.needs_metadata(form77.describe(TEXT, self.copy)))
        self.assertTrue(form77.needs_metadata(form77.describe(TEXT)))
        any_only = reference_dialog(FIELDS[1:3])
        self.assertFalse(form77.needs_metadata(form77.describe(any_only)))

    def test_kinds_by_the_copy_and_the_target(self):
        rows = form77.kinds(TEXT, self.copy, self.base)
        self.assertEqual([(r["control"], r["object"], r["object_id"], r["target_object_id"]) for r in rows], [
            (4155, "Справочник.Контрагенты", 133, 133), (4158, "Перечисление.Пол", 21439, 21439),
            (4159, "Счет.Основной", 809, 809), (4161, "Справочник.Тарифы", 25507, 26051)])
        rows = form77.kinds(TEXT, self.copy, self.foreign)
        self.assertEqual([r["target_object_id"] for r in rows], [172, None, None, None])
        self.assertNotIn("target_object_id", form77.kinds(TEXT, self.copy)[0])
        self.assertIsNone(form77.kinds(TEXT, copy_of(MD_TEXT))[-1]["object"])

    def test_loads_refuses_bad_reference_types(self):
        good = form77.describe(TEXT)
        cases = {"задаётся object": {"kind": "reference", "object": "Справочник", "length": 1},
                 "code — один из": {"kind": "reference", "code": "S", "object_id": 1},
                 "номер ≥ 0": {"kind": "reference", "code": "B", "object_id": -1},
                 "без длины": {"kind": "reference", "code": "B"},
                 "неизвестный ссылочный тип": {"kind": "reference", "object": "Склад.Главный"},
                 "только у вида reference": {"kind": "number", "length": 3, "object_id": 1},
                 "object_id: нужен тип int": {"kind": "reference", "code": "B", "object_id": "133"}}
        for message, value in cases.items():
            description = copy.deepcopy(good)
            description["controls"][3]["type"] = value
            with self.subTest(message), self.assertRaisesRegex(ert.ErtError, message):
                form77.loads(json.dumps(description).encode("utf-8"))
        description = dict(copy.deepcopy(good), schema_version=2)
        with self.assertRaisesRegex(ert.ErtError, "неизвестные свойства object"):
            form77.loads(json.dumps(description).encode("utf-8"))


class ExistingFieldTests(Fixture):
    def test_named_kind_is_compared_by_the_templates_copy(self):
        # 25507 «Тарифы» of the copy is 26051 in the base: 1C finds it by name, not a refusal.
        description = form77.describe(TEXT, self.copy)
        form = form77.rebuild(TEXT, description, MODULE, self.base, self.copy)
        self.assertEqual((form.text, form.changes, form.ert_metadata), (TEXT, [], "kept"))
        self.assertEqual(form.kinds[-1], {"control": 4161, "object": "Справочник.Тарифы", "code": "B",
                                          "object_id": 25507, "target_object_id": 26051})
        # Without the target's metadata nothing is checked by name.
        self.assertEqual(form77.apply(TEXT, description, MODULE, None, self.copy), (TEXT, []))

    def test_other_numbers_of_the_same_kinds_pass(self):
        form = form77.rebuild(TEXT, form77.describe(TEXT, self.copy), MODULE, Metadata(make_md(OTHER_TEXT)), self.copy)
        self.assertEqual((form.text, form.changes), (TEXT, []))
        self.assertEqual([r["target_object_id"] for r in form.kinds], [150, 21439, 901, 30000])
        self.assertEqual([r["object_id"] for r in form.kinds], [133, 21439, 809, 25507])

    def test_kinds_the_target_lacks_are_refused_together(self):
        with self.assertRaisesRegex(ert.ErtError, r"Другая конфигурация.*нет видов полей формы: "
                                    r"элемент 4158 Перечисление.Пол, элемент 4159 Счет.Основной, "
                                    r"элемент 4161 Справочник.Тарифы; .*молча потеряют вид: "
                                    r"справочник, документ или счёт станет «любым», перечисление — строкой"):
            form77.apply(TEXT, form77.describe(TEXT, self.copy), MODULE, self.foreign, self.copy)

    def test_a_number_outside_the_copy_is_refused(self):
        description = form77.describe(TEXT)
        # With another copy 1C makes such a field one of any object (task 013: K5, K5b).
        cases = ((copy_of(MD_TEXT), "Элемент 4161: номера B/25507 нет в копии метаданных шаблона.*"
                                    "становится «любым» \\(Справочник без вида\\)"),
                 (copy_of(EMPTY_TEXT), "Элемент 4155: номера B/133 нет в копии метаданных шаблона, копия"),
                 (None, "Элемент 4155: поле вида B/133, а в шаблоне нет копии метаданных"))
        for template, message in cases:
            for metadata in (None, self.base):
                with self.subTest(message, metadata=bool(metadata)), self.assertRaisesRegex(ert.ErtError, message):
                    form77.apply(TEXT, description, MODULE, metadata, template)

    def test_type_change_of_a_reference_refused(self):
        for value in ({"kind": "reference", "object": "Справочник.Сотрудники"},
                      {"kind": "reference", "object": "Справочник"}, {"kind": "reference", "code": "B", "object_id": 1},
                      {"kind": "reference", "object": "Справочник.ТипыЦен"}, {"kind": "string"}):
            description = form77.describe(TEXT, self.copy)
            description["controls"][3]["type"] = value
            with self.subTest(value), self.assertRaisesRegex(ert.ErtError, "изменение типа данных"):
                form77.apply(TEXT, description, MODULE, self.base, self.copy)
        description["controls"][3]["type"] = {"kind": "reference", "object": "Справочник.ТипыЦен"}
        with self.assertRaisesRegex(ert.ErtError, r"в шаблоне B/133 = Справочник.Контрагенты, "
                                    r"в описании Справочник.ТипыЦен \(нет в копии метаданных шаблона\)"):
            form77.apply(TEXT, description, MODULE, self.base, self.copy)


class NewFieldTests(Fixture):
    def rebuild(self, *controls, metadata="base", template=None, text=DIALOG):
        description = form77.describe(text, template or copy_of(MD_TEXT))
        description["form"] = dict(TALL, height=300)
        description["controls"] += [copy.deepcopy(c) for c in controls]
        return form77.rebuild(text, description, MODULE, self.base if metadata == "base" else metadata,
                              template or copy_of(MD_TEXT))

    def test_each_code_gets_its_number_and_default_record(self):
        expected = {"Справочник.Контрагенты": ("B", "133", "0"), "Справочник": ("B", "0", "0"),
                    "Документ.Выписка": ("O", "238", "16777248"), "Документ": ("O", "0", "16777248"),
                    "Перечисление.Пол": ("E", "21439", "0"), "Счет.Основной": ("T", "809", "0"),
                    "Счет": ("T", "0", "0"), "ВидСубконто": ("K", "0", "32")}
        number = form77.DEFAULTS["BMASKED", "number"]
        for name, (code, object_id, flags) in expected.items():
            with self.subTest(name=name):
                form = self.rebuild(field(name))
                self.assertEqual(form.ert_metadata, "kept")
                record = records(form.text)[-1]
                self.assertEqual(record[14:18], [code, "0", "0", object_id])
                self.assertEqual(record[19], flags)
                differs = [i for i, (a, b) in enumerate(zip(record, number)) if a != b and b is not None]
                self.assertTrue(set(differs) <= {14, 15, 16, 17, 19}, differs)
                self.assertEqual(form.changes[-1], {"control": 4155, "added": "BMASKED", "type": {
                    "object": name, "code": code, "object_id": int(object_id)}})
                again = form77.describe(form.text, copy_of(MD_TEXT))["controls"][-1]["type"]
                self.assertEqual(again, {"kind": "reference", "object": name})

    def test_name_is_case_insensitive_and_written_canonical(self):
        form = self.rebuild(field("справочник.контрагенты"))
        self.assertEqual(form.changes[-1]["type"]["object"], "Справочник.Контрагенты")

    def test_any_object_needs_no_metadata_nor_copy(self):
        description = described()
        description["form"] = dict(TALL)
        description["controls"].append(field("Документ"))
        text, _ = form77.apply(DIALOG, description, MODULE)
        self.assertEqual(records(text)[-1][14:18], ["O", "0", "0", "0"])

    def test_a_kind_in_the_copy_takes_the_copys_number(self):
        # The copy has «Тарифы» under 25507, the base under 26051: the copy stays, 1C finds it by name.
        form = self.rebuild(field("Справочник.Тарифы"), template=self.copy)
        self.assertEqual(form.ert_metadata, "kept")
        self.assertEqual(records(form.text)[-1][17], "25507")
        self.assertEqual(form.kinds, [{"control": 4155, "object": "Справочник.Тарифы", "code": "B",
                                       "object_id": 25507, "target_object_id": 26051}])

    def test_a_kind_outside_the_copy_replaces_it_and_renumbers_the_old_fields(self):
        form = self.rebuild(field("Справочник.ТипыЦен", y=280), template=self.copy, text=TEXT)
        self.assertEqual(form.ert_metadata, "replaced")
        self.assertEqual([r[17] for r in records(form.text)[3:]],
                         ["133", "0", "0", "21439", "809", "0", "26051", "26080"])
        self.assertEqual(form.changes[-1], {"control": 4161, "property": "object_id", "from": 25507, "to": 26051,
                                            "object": "Справочник.Тарифы"})
        self.assertEqual(form.changes[-2]["type"], {"object": "Справочник.ТипыЦен", "code": "B", "object_id": 26080})
        self.assertEqual([(r["object"], r["object_id"]) for r in form.kinds][-2:],
                         [("Справочник.Тарифы", 26051), ("Справочник.ТипыЦен", 26080)])
        # Only field 17 of the renumbered record changed.
        before, after = records(TEXT)[-1], records(form.text)[-2]
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, after)) if a != b], [17])

    def test_refusals(self):
        cases = {"нет видов полей формы: новый элемент 4155 Справочник.Номенклатура": field("Справочник.Номенклатура"),
                 "без вида": field("Перечисление"),
                 "ПланСчетов не поддерживается": field("ПланСчетов"),
                 "не номером": dict(FIELD, type={"kind": "reference", "code": "B", "object_id": 133}),
                 "не подходит элементу 1CEDIT": field("Справочник", **{"class": "1CEDIT"}),
                 "нет свойств identifier": {k: v for k, v in field("Справочник").items() if k != "identifier"}}
        for message, control in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ert.ErtError, message):
                self.rebuild(control)
        with self.assertRaisesRegex(ert.ErtError, "сверяется по именам с метаданными целевой базы"):
            self.rebuild(field("Справочник.Контрагенты"), metadata=None)
        # The copy has «Пол», the other configuration has not.
        with self.assertRaisesRegex(ert.ErtError, "Другая конфигурация.*новый элемент 4155 Перечисление.Пол"):
            self.rebuild(field("Перечисление.Пол"), metadata=self.foreign)

    def test_identifier_still_checked_against_the_module(self):
        with self.assertRaisesRegex(ert.ErtError, "совпадает с процедурой"):
            self.rebuild(field("Справочник", identifier="ВыгрузкаЭ02"))


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-ref-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = self.root / "form.ert"
        self.template.write_bytes(make_ert_with_copy(TEXT, COPY_TEXT, MODULE))
        self.source = self.root / "module.1s"
        self.source.write_bytes(MODULE.encode("cp1251"))
        self.md = self.root / "1Cv7.MD"
        self.md.write_bytes(make_md(BASE_TEXT))
        (self.root / "foreign.MD").write_bytes(make_md(FOREIGN_TEXT))

    def cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli([str(a) for a in args])
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_extract_checks_the_metadata_by_names_and_build_keeps_the_copys_numbers(self):
        code, report = self.cli("form-extract", self.template, "--output", self.root / "form.json",
                                "--metadata", self.md)
        self.assertEqual(code, 0)
        self.assertEqual(report["metadata"]["sha256"], form77.sha256(make_md(BASE_TEXT)))
        self.assertEqual(report["names_from"], "ert")
        self.assertEqual(report["references_by_number"], [])
        self.assertEqual(report["missing_in_metadata"], [])
        self.assertEqual(report["kinds"][-1], {"control": 4161, "object": "Справочник.Тарифы", "code": "B",
                                               "object_id": 25507, "target_object_id": 26051})
        description = form77.loads((self.root / "form.json").read_bytes())
        self.assertEqual(description["controls"][-1]["type"], {"kind": "reference", "object": "Справочник.Тарифы"})
        description["form"]["height"] = 300
        description["controls"].append(field("Справочник.Сотрудники", y=280))
        (self.root / "new.json").write_text(form77.dumps(description), encoding="utf-8")
        code, report = self.cli("build", "--template", self.template, "--source", self.source,
                                "--form", self.root / "new.json", "--metadata", self.md,
                                "--output", self.root / "out.ert")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["form"]["metadata"]["sha256"], form77.sha256(make_md(BASE_TEXT)))
        self.assertEqual(report["form"]["changes"][-1]["type"],
                         {"object": "Справочник.Сотрудники", "code": "B", "object_id": 208})
        self.assertEqual([(k["object_id"], k["target_object_id"]) for k in report["form"]["kinds"]][-2:],
                         [(25507, 26051), (208, 208)])
        # The template's own copy has Сотрудники: it stays.
        self.assertEqual(report["form"]["ert_metadata"]["action"], "kept")
        self.assertEqual(streams(self.root / "out.ert")[STREAM], streams(self.template)[STREAM])

    def test_extract_reports_kinds_the_metadata_lack(self):
        code, report = self.cli("form-extract", self.template, "--output", self.root / "form.json",
                                "--metadata", self.root / "foreign.MD")
        self.assertEqual(code, 0)
        self.assertEqual(report["missing_in_metadata"], [
            {"control": 4158, "object": "Перечисление.Пол"}, {"control": 4159, "object": "Счет.Основной"},
            {"control": 4161, "object": "Справочник.Тарифы"}])
        self.assertEqual(report["kinds"][0]["target_object_id"], 172)

    def test_extract_without_metadata_names_by_the_erts_copy(self):
        code, report = self.cli("form-extract", self.template, "--output", self.root / "form.json")
        self.assertEqual(code, 0)
        self.assertNotIn("metadata", report)
        self.assertNotIn("missing_in_metadata", report)
        self.assertEqual((report["names_from"], report["ert_metadata"]["configuration"]),
                         ("ert", "Тестовая конфигурация, прежний выпуск"))
        self.assertTrue(form77.needs_metadata(form77.loads((self.root / "form.json").read_bytes())))
        # Unchanged, it builds without the target's metadata: the template's copy names the kinds.
        code, report = self.cli("build", "--template", self.template, "--source", self.source,
                                "--form", self.root / "form.json", "--output", self.root / "out.ert")
        self.assertEqual(code, 0, report)
        self.assertTrue(report["form"]["dialog_unchanged"])
        self.assertNotIn("target_object_id", report["form"]["kinds"][0])
        self.assertEqual(streams(self.root / "out.ert"), streams(self.template))

    def test_refusals_publish_nothing(self):
        description = form77.describe(TEXT, copy_of(COPY_TEXT))
        (self.root / "named.json").write_text(form77.dumps(description), encoding="utf-8")
        description["form"]["height"] = 300
        description["controls"].append(field("Справочник.Сотрудники", y=280))
        (self.root / "new.json").write_text(form77.dumps(description), encoding="utf-8")
        cases = {"метаданными целевой базы": ("new.json",),
                 "элемент 4161 Справочник.Тарифы": ("named.json", "--metadata", self.root / "foreign.MD"),
                 "не читаются как 1Cv7.MD": ("named.json", "--metadata", self.source)}
        for message, (form, *extra) in cases.items():
            with self.subTest(message):
                code, report = self.cli("build", "--template", self.template, "--source", self.source,
                                        "--form", self.root / form, "--output", self.root / "out.ert",
                                        *extra)
                self.assertEqual(code, 2)
                self.assertIn(message, report["error"])
                self.assertFalse((self.root / "out.ert").exists())
        code, report = self.cli("build", "--template", self.template, "--source", self.source,
                                "--metadata", self.md, "--output", self.root / "out.ert")
        self.assertEqual(code, 2)
        self.assertIn("вместе с --form", report["error"])


class CopyTests(unittest.TestCase):
    """The ERT's own copy of the metadata, where 1C finds the kind of a field (tasks 012, 013)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-copy-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "module.1s"
        self.source.write_bytes(MODULE.encode("cp1251"))
        self.md = self.root / "1Cv7.MD"
        self.md.write_bytes(make_md(BASE_TEXT))

    def build(self, template_bytes, edit, metadata=True):
        template = self.root / "form.ert"
        template.write_bytes(template_bytes)
        own = Metadata.of_ert(ert.CompoundFile(template_bytes))
        description = form77.describe(ert.extract_dialog(template), own)
        description["form"]["height"] = 300
        edit(description)
        form = self.root / "form.json"
        form.write_text(form77.dumps(description), encoding="utf-8")
        output = self.root / "out.ert"
        report = build(template, self.source, output, form=form, metadata=self.md if metadata else None)
        return report, streams(template), streams(output)

    def test_empty_copy_is_replaced_by_the_targets_metadata(self):
        report, before, after = self.build(make_ert_with_copy(DIALOG, EMPTY_TEXT, MODULE),
                                           lambda d: d["controls"].append(field("Справочник.Контрагенты", y=280)))
        self.assertEqual(report["form"]["ert_metadata"], {
            "action": "replaced", "template_sha256": form77.sha256(before[STREAM]), "template_configuration": "Задача",
            "sha256": form77.sha256(ert.encode_dialog(BASE_TEXT) + NUL), "configuration": "Тестовая конфигурация"})
        self.assertEqual(after[STREAM], ert.encode_dialog(BASE_TEXT) + NUL)
        self.assertNotIn(STREAM, [s["path"] for s in report["preserved_streams"]])
        own = Metadata.of_ert(ert.CompoundFile((self.root / "out.ert").read_bytes()))
        self.assertEqual(form77.describe(ert.extract_dialog(self.root / "out.ert"), own)["controls"][-1]["type"],
                         {"kind": "reference", "object": "Справочник.Контрагенты"})

    def test_copy_with_the_kind_is_kept(self):
        report, before, after = self.build(make_ert_with_copy(DIALOG, MD_TEXT, MODULE),
                                           lambda d: d["controls"].append(field("Перечисление.Пол", y=280)))
        self.assertEqual(report["form"]["ert_metadata"]["action"], "kept")
        self.assertEqual(after[STREAM], before[STREAM])

    def test_any_object_keeps_the_copy_and_needs_no_metadata(self):
        report, before, after = self.build(make_ert_with_copy(DIALOG, EMPTY_TEXT, MODULE),
                                           lambda d: d["controls"].append(field("Документ", y=280)), metadata=False)
        self.assertEqual(report["form"]["ert_metadata"]["action"], "kept")
        self.assertEqual(after[STREAM], before[STREAM])

    def test_replaced_copy_renumbers_the_old_fields_by_name(self):
        report, _, after = self.build(make_ert_with_copy(TEXT, COPY_TEXT, MODULE),
                                      lambda d: d["controls"].append(field("Справочник.ТипыЦен", y=280)))
        self.assertEqual(report["form"]["ert_metadata"]["action"], "replaced")
        self.assertEqual(after[STREAM], ert.encode_dialog(BASE_TEXT) + NUL)
        self.assertIn({"control": 4161, "property": "object_id", "from": 25507, "to": 26051,
                       "object": "Справочник.Тарифы"}, report["form"]["changes"])
        own = Metadata.of_ert(ert.CompoundFile((self.root / "out.ert").read_bytes()))
        types = [c.get("type", {}).get("object") for c in
                 form77.describe(ert.extract_dialog(self.root / "out.ert"), own)["controls"][3:]]
        self.assertEqual(types, NAMED + ["Справочник.ТипыЦен"])

    def test_old_kind_the_target_lacks_is_refused_before_the_copy_is_replaced(self):
        # The template's copy calls 133 «Поставщики», the base has no such catalog.
        text = reference_dialog(FIELDS[:1])
        copy_text = MD_TEXT.replace('"133","Контрагенты"', '"133","Поставщики"')
        with self.assertRaisesRegex(ert.ErtError, "нет видов полей формы: элемент 4155 Справочник.Поставщики"):
            self.build(make_ert_with_copy(text, copy_text, MODULE),
                       lambda d: d["controls"].append(field("Справочник.Контрагенты", y=280)))
        self.assertFalse((self.root / "out.ert").exists())

    def test_template_without_a_copy_is_refused(self):
        with self.assertRaisesRegex(ert.ErtError, "нет своей копии метаданных"):
            self.build(make_ert(ert.encode_dialog(DIALOG)),
                       lambda d: d["controls"].append(field("Справочник.Контрагенты", y=280)))


class RunTests(unittest.TestCase):
    """The run takes the stand base's 1Cv7.MD; another base is checked by the names of the kinds (task 013)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-ref-run-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        (self.base / "1Cv7.MD").write_bytes(make_md(BASE_TEXT))
        (self.root / "other.MD").write_bytes(other_md())
        self.foreign = self.root / "foreign"
        self.foreign.mkdir()
        (self.foreign / "1Cv7.MD").write_bytes(make_md(FOREIGN_TEXT))

    def go(self, template, description, project_metadata=None, base=None, copy_text=EMPTY_TEXT):
        project = write_project(self.root, project_id="ref")
        (self.root / "form.ert").write_bytes(make_ert_with_copy(template, copy_text, MODULE))
        (self.root / "module.1s").write_bytes(MODULE.encode("cp1251"))
        (self.root / "form.json").write_text(form77.dumps(description), encoding="utf-8")
        lines = ['form = "form.json"'] + ([f'metadata = "{project_metadata}"'] if project_metadata else [])
        text = project.read_text(encoding="utf-8").replace(
            'source = "module.1s"', "\n".join(['source = "module.1s"'] + lines))
        project.write_text(text, encoding="utf-8")
        stand = write_sim_stand(self.root, base_scenario(), base=(base or self.base).as_posix())
        report = run(project, stand, self.root / "runs")
        return report, {s["stage"]: s for s in report["stages"]}

    def new_field(self, name):
        description = described()
        description["form"] = dict(TALL)
        description["controls"].append(field(name))
        return description

    def test_stand_metadata_is_used_and_recorded(self):
        report, stages = self.go(TEXT, form77.describe(TEXT, copy_of(COPY_TEXT)), copy_text=COPY_TEXT)
        self.assertEqual(stages["build"]["status"], "passed", stages["build"]["reason"])
        self.assertEqual(stages["build"]["form"]["metadata"], {
            "sha256": form77.sha256(make_md(BASE_TEXT)), "configuration": "Тестовая конфигурация",
            "source": "stand"})
        self.assertEqual(stages["build"]["form"]["kinds"][-1]["target_object_id"], 26051)
        self.assertEqual(stages["platform_check"]["status"], "passed")
        self.assertEqual(stages["platform_check"]["metadata_check"], {
            "sha256": form77.sha256(make_md(BASE_TEXT)), "same_as_build": True, "missing": []})
        self.assertEqual(report["exit_code"], 0)

    def test_other_numbers_on_the_stand_are_checked_by_name_and_pass(self):
        # Built for other numbers of the same names; the stand base has its own numbers.
        report, stages = self.go(DIALOG, self.new_field("Справочник.Контрагенты"), "other.MD")
        self.assertEqual(stages["build"]["status"], "passed", stages["build"]["reason"])
        self.assertEqual(stages["build"]["form"]["metadata"]["source"], "project")
        self.assertEqual(stages["build"]["form"]["changes"][-1]["type"]["object_id"], 150)
        self.assertEqual(stages["platform_check"]["status"], "passed", stages["platform_check"]["reason"])
        self.assertEqual(stages["platform_check"]["metadata_check"]["missing"], [])
        self.assertFalse(stages["platform_check"]["metadata_check"]["same_as_build"])
        self.assertEqual(report["exit_code"], 0)

    def test_kind_the_stand_lacks_blocks_the_platform_check(self):
        report, stages = self.go(DIALOG, self.new_field("Перечисление.Пол"), (self.base / "1Cv7.MD").as_posix(),
                                 base=self.foreign)
        self.assertEqual(stages["build"]["status"], "passed", stages["build"]["reason"])
        self.assertEqual(stages["platform_check"]["status"], "blocked")
        self.assertIn("metadata_missing_kinds", stages["platform_check"]["reason"])
        self.assertIn("Перечисление.Пол (control 4155)", stages["platform_check"]["reason"])
        self.assertFalse(stages["platform_check"]["platform_checked"])
        self.assertEqual(stages["platform_check"]["metadata_check"]["missing"],
                         [{"control": 4155, "object": "Перечисление.Пол"}])
        self.assertEqual(stages["tests"]["status"], "skipped")
        self.assertEqual(report["exit_code"], 2)

    def test_unreadable_stand_metadata_blocks_the_platform_check(self):
        broken = self.root / "broken"
        broken.mkdir()
        (broken / "1Cv7.MD").write_bytes(b"not a compound file")
        report, stages = self.go(DIALOG, self.new_field("Перечисление.Пол"), (self.base / "1Cv7.MD").as_posix(),
                                 base=broken)
        self.assertEqual(stages["build"]["status"], "passed", stages["build"]["reason"])
        self.assertEqual(stages["platform_check"]["status"], "blocked")
        self.assertIn("metadata_unreadable", stages["platform_check"]["reason"])
        self.assertEqual(report["exit_code"], 2)

    def test_kind_the_stand_lacks_blocks_the_build_by_default(self):
        report, stages = self.go(TEXT, form77.describe(TEXT, copy_of(COPY_TEXT)), base=self.foreign,
                                 copy_text=COPY_TEXT)
        self.assertEqual(stages["build"]["status"], "blocked")
        self.assertIn("элемент 4158 Перечисление.Пол", stages["build"]["reason"])
        self.assertEqual(report["exit_code"], 2)

    def test_missing_stand_metadata_blocks_the_build(self):
        report, stages = self.go(DIALOG, self.new_field("Справочник.Контрагенты"), base=self.root / "nowhere")
        self.assertEqual(stages["build"]["status"], "blocked")
        self.assertIn("nowhere", stages["build"]["reason"])
        self.assertEqual(report["exit_code"], 2)

    def test_any_object_needs_no_metadata(self):
        report, stages = self.go(DIALOG, self.new_field("Справочник"), base=self.root / "nowhere")
        self.assertEqual(stages["build"]["status"], "passed", stages["build"]["reason"])
        self.assertNotIn("metadata", stages["build"]["form"])
        self.assertNotIn("metadata_check", stages["platform_check"])
        self.assertEqual(report["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
