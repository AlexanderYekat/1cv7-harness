"""Reference-typed form fields (task 012): names by the metadata, numbers in the dialog."""

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

# (identifier, code, number) of the template's reference fields: a kind, any, an
# unknown number (a form of another configuration, as 25507 in the corpus).
FIELDS = (("Контрагент", "B", "133"), ("ЛюбойСправочник", "B", "0"), ("Документ", "O", "0"),
          ("Пол", "E", "21439"), ("Счет", "T", "809"), ("ВидСубконто", "K", "0"), ("Чужой", "B", "25507"))


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


TEXT = reference_dialog()
NAMED = ["Справочник.Контрагенты", "Справочник", "Документ", "Перечисление.Пол", "Счет.Основной",
         "ВидСубконто"]
NUL = bytes(1)
FIELD = {"class": "BMASKED", "identifier": "Новое77", "x": 14, "y": 170, "width": 120, "height": 13}


def field(name, **extra):
    return dict(FIELD, type={"kind": "reference", "object": name}, **extra)


class DescribeTests(unittest.TestCase):
    def setUp(self):
        self.metadata = Metadata(make_md())

    def types(self, description):
        return [c["type"] for c in description["controls"][3:]]

    def test_without_metadata_kinds_are_numbers_and_any_is_named(self):
        self.assertEqual(self.types(form77.describe(TEXT)), [
            {"kind": "reference", "code": "B", "object_id": 133}, {"kind": "reference", "object": "Справочник"},
            {"kind": "reference", "object": "Документ"}, {"kind": "reference", "code": "E", "object_id": 21439},
            {"kind": "reference", "code": "T", "object_id": 809}, {"kind": "reference", "object": "ВидСубконто"},
            {"kind": "reference", "code": "B", "object_id": 25507}])

    def test_metadata_names_the_kinds_it_has(self):
        types = self.types(form77.describe(TEXT, self.metadata))
        self.assertEqual([t.get("object") for t in types], NAMED + [None])
        self.assertEqual(types[-1], {"kind": "reference", "code": "B", "object_id": 25507})
        self.assertEqual(form77.by_number(form77.describe(TEXT, self.metadata)),
                         [{"control": 4161, "code": "B", "object_id": 25507}])

    def test_version_2_keeps_other_with_code(self):
        self.assertEqual(self.types(form77.describe(TEXT, version=2))[0], {"kind": "other", "code": "B"})

    def test_every_form_rebuilds_byte_for_byte(self):
        for metadata in (None, self.metadata):
            for version in (2, 3):
                with self.subTest(metadata=bool(metadata), version=version):
                    description = form77.loads(form77.dumps(
                        form77.describe(TEXT, metadata, version)).encode("utf-8"))
                    self.assertEqual(form77.apply(TEXT, description, MODULE, metadata), (TEXT, []))

    def test_needs_metadata_only_for_a_named_kind(self):
        self.assertTrue(form77.needs_metadata(form77.describe(TEXT, self.metadata)))
        self.assertFalse(form77.needs_metadata(form77.describe(TEXT)))

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


class ExistingFieldTests(unittest.TestCase):
    def test_named_kind_without_metadata_is_refused_with_a_hint(self):
        description = form77.describe(TEXT, Metadata(make_md()))
        with self.assertRaisesRegex(ert.ErtError, "Справочник.Контрагенты.*1Cv7.MD"):
            form77.apply(TEXT, description, MODULE)

    def test_other_configuration_numbers_differ_and_are_refused(self):
        description = form77.describe(TEXT, Metadata(make_md()))
        with self.assertRaisesRegex(ert.ErtError, r"изменение типа.*B/133.*Справочник.Контрагенты \(B/150"):
            form77.apply(TEXT, description, MODULE, Metadata(other_md()))

    def test_type_change_of_a_reference_refused(self):
        for value in ({"kind": "reference", "object": "Справочник.Сотрудники"},
                      {"kind": "reference", "object": "Справочник"}, {"kind": "reference", "code": "B", "object_id": 1},
                      {"kind": "string"}):
            description = form77.describe(TEXT)
            description["controls"][3]["type"] = value
            with self.subTest(value), self.assertRaisesRegex(ert.ErtError, "изменение типа данных"):
                form77.apply(TEXT, description, MODULE, Metadata(make_md()))


class NewFieldTests(unittest.TestCase):
    def setUp(self):
        self.metadata = Metadata(make_md())

    def apply(self, *controls, metadata="default"):
        description = described()
        description["form"] = dict(TALL)
        description["controls"] += [copy.deepcopy(c) for c in controls]
        return form77.apply(DIALOG, description, MODULE, self.metadata if metadata == "default" else metadata)

    def test_each_code_gets_its_number_and_default_record(self):
        expected = {"Справочник.Контрагенты": ("B", "133", "0"), "Справочник": ("B", "0", "0"),
                    "Документ.Выписка": ("O", "238", "16777248"), "Документ": ("O", "0", "16777248"),
                    "Перечисление.Пол": ("E", "21439", "0"), "Счет.Основной": ("T", "809", "0"),
                    "Счет": ("T", "0", "0"), "ВидСубконто": ("K", "0", "32")}
        number = form77.DEFAULTS["BMASKED", "number"]
        for name, (code, object_id, flags) in expected.items():
            with self.subTest(name=name):
                text, changes = self.apply(field(name))
                record = records(text)[-1]
                self.assertEqual(record[14:18], [code, "0", "0", object_id])
                self.assertEqual(record[19], flags)
                differs = [i for i, (a, b) in enumerate(zip(record, number)) if a != b and b is not None]
                self.assertTrue(set(differs) <= {14, 15, 16, 17, 19}, differs)
                self.assertEqual(changes[-1], {"control": 4155, "added": "BMASKED", "type": {
                    "object": name, "code": code, "object_id": int(object_id)}})
                again = form77.describe(text, self.metadata)["controls"][-1]["type"]
                self.assertEqual(again, {"kind": "reference", "object": name})

    def test_name_is_case_insensitive_and_written_canonical(self):
        _, changes = self.apply(field("справочник.контрагенты"))
        self.assertEqual(changes[-1]["type"]["object"], "Справочник.Контрагенты")

    def test_any_object_needs_no_metadata(self):
        text, _ = self.apply(field("Документ"), metadata=None)
        self.assertEqual(records(text)[-1][14:18], ["O", "0", "0", "0"])

    def test_refusals(self):
        cases = {"нет объекта Справочник.Номенклатура": field("Справочник.Номенклатура"),
                 "без вида": field("Перечисление"),
                 "ПланСчетов не поддерживается": field("ПланСчетов"),
                 "не номером": dict(FIELD, type={"kind": "reference", "code": "B", "object_id": 133}),
                 "не подходит элементу 1CEDIT": field("Справочник", **{"class": "1CEDIT"}),
                 "нет свойств identifier": {k: v for k, v in field("Справочник").items() if k != "identifier"}}
        for message, control in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ert.ErtError, message):
                self.apply(control)
        with self.assertRaisesRegex(ert.ErtError, "метаданных целевой базы"):
            self.apply(field("Справочник.Контрагенты"), metadata=None)

    def test_identifier_still_checked_against_the_module(self):
        with self.assertRaisesRegex(ert.ErtError, "совпадает с процедурой"):
            self.apply(field("Справочник", identifier="ВыгрузкаЭ02"))


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-ref-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = self.root / "form.ert"
        self.template.write_bytes(make_ert_with_copy(TEXT, MD_TEXT, MODULE))
        self.source = self.root / "module.1s"
        self.source.write_bytes(MODULE.encode("cp1251"))
        self.md = self.root / "1Cv7.MD"
        self.md.write_bytes(make_md())

    def cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli([str(a) for a in args])
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_extract_with_metadata_and_build_by_names(self):
        code, report = self.cli("form-extract", self.template, "--output", self.root / "form.json",
                                "--metadata", self.md)
        self.assertEqual(code, 0)
        self.assertEqual(report["metadata"]["sha256"], form77.sha256(make_md()))
        self.assertEqual(report["metadata"]["configuration"], "Тестовая конфигурация")
        self.assertEqual(report["references_by_number"], [{"control": 4161, "code": "B", "object_id": 25507}])
        description = form77.loads((self.root / "form.json").read_bytes())
        description["form"]["height"] = 300
        description["controls"].append(field("Справочник.Сотрудники", y=280))
        (self.root / "new.json").write_text(form77.dumps(description), encoding="utf-8")
        code, report = self.cli("build", "--template", self.template, "--source", self.source,
                                "--form", self.root / "new.json", "--metadata", self.md,
                                "--output", self.root / "out.ert")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["form"]["metadata"]["sha256"], form77.sha256(make_md()))
        self.assertEqual(report["form"]["changes"][-1]["type"],
                         {"object": "Справочник.Сотрудники", "code": "B", "object_id": 208})
        built = form77.describe(ert.extract_dialog(self.root / "out.ert"), Metadata(make_md()))
        self.assertEqual(built["controls"][-1]["type"], {"kind": "reference", "object": "Справочник.Сотрудники"})
        # The template's own copy has Сотрудники under 208, as the base: it stays.
        self.assertEqual(report["form"]["ert_metadata"]["action"], "kept")
        self.assertEqual(streams(self.root / "out.ert")[STREAM], streams(self.template)[STREAM])

    def test_extract_without_metadata_names_by_the_erts_copy(self):
        code, report = self.cli("form-extract", self.template, "--output", self.root / "form.json")
        self.assertEqual(code, 0)
        self.assertNotIn("metadata", report)
        self.assertEqual((report["names_from"], report["ert_metadata"]["configuration"]),
                         ("ert", "Тестовая конфигурация"))
        self.assertEqual(report["references_by_number"], [{"control": 4161, "code": "B", "object_id": 25507}])
        self.assertTrue(form77.needs_metadata(form77.loads((self.root / "form.json").read_bytes())))
        # Unchanged, it builds without the target's metadata: the template's copy numbers the names.
        code, report = self.cli("build", "--template", self.template, "--source", self.source,
                                "--form", self.root / "form.json", "--output", self.root / "out.ert")
        self.assertEqual(code, 0, report)
        self.assertTrue(report["form"]["dialog_unchanged"])
        self.assertEqual(streams(self.root / "out.ert"), streams(self.template))

    def test_refusals_publish_nothing(self):
        description = form77.describe(TEXT, Metadata(make_md()))
        (self.root / "named.json").write_text(form77.dumps(description), encoding="utf-8")
        description["form"]["height"] = 300
        description["controls"].append(field("Справочник.Сотрудники", y=280))
        (self.root / "new.json").write_text(form77.dumps(description), encoding="utf-8")
        cases = {"метаданных целевой базы": ("new.json",),
                 "изменение типа": ("named.json", "--metadata", self.root / "other.MD"),
                 "не читаются как 1Cv7.MD": ("named.json", "--metadata", self.source)}
        (self.root / "other.MD").write_bytes(other_md())
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
    """The ERT's own copy of the metadata, where 1C finds the kind of a field (task 012, R1–R1c)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-copy-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "module.1s"
        self.source.write_bytes(MODULE.encode("cp1251"))
        self.md = self.root / "1Cv7.MD"
        self.md.write_bytes(make_md())

    def build(self, template_bytes, edit, metadata=True):
        template = self.root / "form.ert"
        template.write_bytes(template_bytes)
        description = form77.describe(ert.extract_dialog(template))
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
            "sha256": form77.sha256(ert.encode_dialog(MD_TEXT) + NUL), "configuration": "Тестовая конфигурация"})
        self.assertEqual(after[STREAM], ert.encode_dialog(MD_TEXT) + NUL)
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

    def test_copy_of_another_meaning_is_not_replaced(self):
        # The template's copy calls 133 «Поставщики»; the base calls it «Контрагенты».
        text = reference_dialog(FIELDS[:1])
        copy_text = MD_TEXT.replace('"133","Контрагенты"', '"133","Поставщики"')
        with self.assertRaisesRegex(ert.ErtError, "Элемент 4155: шаблон ссылается на B/133 "
                                    "[(]Справочник.Поставщики[)].*Справочник.Контрагенты"):
            self.build(make_ert_with_copy(text, copy_text, MODULE),
                       lambda d: d["controls"].append(field("Справочник.Контрагенты", y=280)))
        self.assertFalse((self.root / "out.ert").exists())

    def test_template_without_a_copy_is_refused(self):
        with self.assertRaisesRegex(ert.ErtError, "нет своей копии метаданных"):
            self.build(make_ert(ert.encode_dialog(DIALOG)),
                       lambda d: d["controls"].append(field("Справочник.Контрагенты", y=280)))


class RunTests(unittest.TestCase):
    """The run takes the stand base's 1Cv7.MD and refuses to check an ERT built for other metadata."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-ref-run-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        (self.base / "1Cv7.MD").write_bytes(make_md())
        (self.root / "other.MD").write_bytes(other_md())

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
        report, stages = self.go(TEXT, form77.describe(TEXT, Metadata(make_md())), copy_text=MD_TEXT)
        self.assertEqual(stages["build"]["status"], "passed", stages["build"]["reason"])
        self.assertEqual(stages["build"]["form"]["metadata"], {
            "sha256": form77.sha256(make_md()), "configuration": "Тестовая конфигурация", "source": "stand"})
        self.assertEqual(stages["platform_check"]["status"], "passed")
        self.assertEqual(report["exit_code"], 0)

    def test_ert_built_for_other_metadata_is_not_checked(self):
        report, stages = self.go(DIALOG, self.new_field("Справочник.Контрагенты"), "other.MD")
        self.assertEqual(stages["build"]["status"], "passed", stages["build"]["reason"])
        self.assertEqual(stages["build"]["form"]["metadata"]["source"], "project")
        self.assertEqual(stages["build"]["form"]["changes"][-1]["type"]["object_id"], 150)
        self.assertEqual(stages["platform_check"]["status"], "blocked")
        self.assertIn("metadata_mismatch", stages["platform_check"]["reason"])
        self.assertEqual(stages["tests"]["status"], "skipped")
        self.assertEqual(report["exit_code"], 2)

    def test_template_of_another_configuration_is_refused_at_build(self):
        report, stages = self.go(TEXT, form77.describe(TEXT, Metadata(make_md())), "other.MD", copy_text=MD_TEXT)
        self.assertEqual(stages["build"]["status"], "blocked")
        self.assertIn("B/133", stages["build"]["reason"])
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
        self.assertEqual(report["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
