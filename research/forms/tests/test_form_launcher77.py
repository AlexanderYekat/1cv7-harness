"""Form adapter of the stage-4 launcher (tasks 008, 010, 011): portable, no 1C is started."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import form_launcher77 as form  # noqa: E402
import form_window77 as window  # noqa: E402

launcher = form.launcher
EXPECTED = {4152: (120, 106, 54, 13), 4153: (64, 106, 54, 13), 4160: (10, 20, 54, 8)}
DESCRIPTION = {"controls": [{"id": i, "class": "STATIC", "caption": f"Надпись {i}", "x": x, "y": y, "width": w,
                             "height": h} for i, (x, y, w, h) in EXPECTED.items()]}
# FIO.ERT records (ID, x, y, width, height) and the windows measured natively in F0
# (run 4633a2d0): window ID → (left, top, width, height) in the dialog's client area.
FIO = [(4152, 120, 106, 54, 13), (4153, 64, 106, 54, 13), (4154, 7, 106, 54, 13), (4155, 7, 85, 208, 13),
       (4156, 10, 74, 54, 8), (4157, 7, 58, 208, 13), (4158, 10, 47, 54, 8), (4159, 7, 31, 208, 13),
       (4160, 10, 20, 54, 8)]
F0 = {4152: (9, 8, 81, 13), 4153: (4, 25, 314, 23), 4154: (9, 52, 81, 13), 4155: (4, 69, 314, 23),
      4156: (9, 96, 81, 13), 4157: (4, 113, 314, 23), 4158: (5, 148, 81, 21), 4159: (90, 148, 81, 21),
      4160: (174, 148, 81, 21)}
FIO_DESCRIPTION = {"controls": [{"id": i, "x": x, "y": y, "width": w, "height": h} for i, x, y, w, h in FIO]}


def scaled(sx, sy, ox=0, oy=0, rounding=round):
    return {i: (rounding(ox + sx * x), rounding(oy + sy * y), rounding(sx * w), rounding(sy * h))
            for i, (x, y, w, h) in EXPECTED.items()}


def row(command, diagnostics=()):
    return {"name": command, "status": "blocked", "value": None, "diagnostics": list(diagnostics)}


class UnitsTests(unittest.TestCase):
    def test_pixels(self):
        fit = window.fit_units(EXPECTED, scaled(1, 1))
        self.assertEqual((fit["consistent"], fit["units"], fit["max_residual_px"]), (True, "pixels", 0))

    def test_dialog_units_with_offset(self):
        # MS Sans Serif 8 at 96 DPI: dialog base units 6×13 → 1.5 and 1.625 px per unit.
        fit = window.fit_units(EXPECTED, scaled(1.5, 1.625, 3, 5))
        self.assertTrue(fit["consistent"])
        self.assertEqual(fit["units"], "scaled")
        # Sizes rounded to whole pixels: the fitted scale is close, not exact.
        self.assertAlmostEqual(fit["scale_x"], 1.5, delta=0.02)
        self.assertAlmostEqual(fit["scale_y"], 1.625, delta=0.02)
        self.assertLessEqual(fit["max_residual_px"], 1)

    def test_one_control_out_of_place(self):
        measured = scaled(1, 1)
        measured[4160] = (40, 20, 54, 8)
        fit = window.fit_units(EXPECTED, measured)
        self.assertFalse(fit["consistent"])
        self.assertGreater(fit["residuals_px"]["4160"], window.TOLERANCE_PX)

    def test_no_common_controls(self):
        self.assertFalse(window.fit_units(EXPECTED, {1: (0, 0, 1, 1)})["consistent"])

    def test_window_ids_are_given_in_reverse_record_order(self):
        self.assertEqual(window.window_ids(FIO_DESCRIPTION)[4152], 4160)
        self.assertEqual(window.window_ids(FIO_DESCRIPTION)[4160], 4152)
        with_button = {"controls": FIO_DESCRIPTION["controls"] + [{"id": 4161}]}
        self.assertEqual(window.window_ids(with_button)[4161], 4152)
        self.assertEqual(window.window_ids(with_button)[4152], 4161)

    def test_f0_measurements_follow_one_mapping(self):
        fit = window.fit_units(window.expected_geometry(FIO_DESCRIPTION), F0)
        self.assertTrue(fit["consistent"], fit)
        self.assertEqual(fit["units"], "scaled")
        self.assertAlmostEqual(fit["scale_x"], 1.5, delta=0.05)
        self.assertAlmostEqual(fit["scale_y"], 1.625, delta=0.05)
        # Matching record ID to window ID directly, as first assumed, does not fit.
        direct = {i: (x, y, w, h) for i, x, y, w, h in FIO}
        self.assertFalse(window.fit_units(direct, F0)["consistent"])

    def test_inside_client_area(self):
        self.assertTrue(window.inside([222, 2, 99, 21], [329, 174]))
        self.assertFalse(window.inside([222, -17, 99, 21], [329, 174]))
        self.assertFalse(window.inside([240, 2, 99, 21], [329, 174]))

    def test_editor_is_the_single_inner_window(self):
        wrapper = {"hwnd": 1, "class": "1CEDIT", "children": [{"hwnd": 2, "class": "Edit", "id": 0, "text": ""}]}
        self.assertEqual(window.editor(wrapper)["hwnd"], 2)
        self.assertEqual(window.editor({"hwnd": 3, "class": "BMASKED", "children": []})["hwnd"], 3)
        self.assertEqual(window.editor({"hwnd": 4, "class": "BMASKED"})["hwnd"], 4)
        self.assertEqual(window.editor(dict(wrapper, children=wrapper["children"] * 2))["hwnd"], 1)

    def test_judge_layout(self):
        ids = window.window_ids(DESCRIPTION)
        inspection = {"found": True, "controls": [{"id": ids[i]} for i in EXPECTED],
                      "units": window.fit_units(EXPECTED, scaled(1, 1))}
        self.assertEqual(window.judge_layout(DESCRIPTION, inspection), [])
        self.assertIn("not found", window.judge_layout(DESCRIPTION, {"found": False, "reason": "x"})[0])
        inspection["controls"].pop()
        self.assertIn("missing: 4152", window.judge_layout(DESCRIPTION, inspection)[0])


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="h77-form-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = 0

    def adapter(self, parameters=None, inspection=None):
        self.runs += 1
        self.run_dir = self.root / f"run{self.runs}"
        self.run_dir.mkdir()
        adapter = form.FormAdapter()
        self.assertEqual(adapter.prepare(self.run_dir, parameters or {}), {})
        if inspection is not None:
            (self.run_dir / "form" / "form-window.json").write_text(json.dumps(inspection), encoding="utf-8")
            (self.run_dir / "form" / "description.json").write_text(json.dumps(DESCRIPTION), encoding="utf-8")
        return adapter

    def judge(self, adapter, command, lines, diagnostics=()):
        item = row(command, diagnostics)
        issue = adapter.operation(command, lines, "\n".join(lines), item)
        return item, issue

    def inspection(self, **extra):
        return dict({"found": True, "controls": [{"id": i} for i in window.window_ids(DESCRIPTION).values()],
                     "units": window.fit_units(EXPECTED, scaled(1.5, 1.625, 3, 5))}, **extra)

    def test_commands_and_parameters(self):
        adapter = form.FormAdapter()
        self.assertEqual(adapter.commands({}, ["result", "open"]), ["check", "open", "result"])
        self.assertEqual(adapter.commands({"click_id": 4161}, []), ["check", "open", "result"])
        for parameters, requested in (({}, ["execute"]), ({"click_id": "4161"}, []),
                                      ({"click_id": 0}, []), ({"click_id": True}, [])):
            with self.subTest(parameters=parameters, requested=requested), self.assertRaises(ValueError):
                adapter.commands(parameters, requested)

    def test_client_waits_for_the_click_before_result(self):
        client = (Path(launcher.probe.__file__).with_name("ert_probe77.vbs")).read_text(encoding="utf-8")
        changed = form.FormAdapter().client(client)
        self.assertIn('If command = "result" Then AwaitClick\n' + form.CALL, changed)
        self.assertIn('"form-click-done"', changed)
        self.assertIn("Sub AwaitClick()", changed)
        with self.assertRaises(ValueError):
            form.FormAdapter().client("no call here")

    def test_default_adapter_hooks_change_nothing(self):
        default = launcher.Harness77Adapter()
        self.assertEqual(default.client("text"), "text")
        with default.watch(self.root, {}, "desktop"):
            pass

    def test_check_open_and_close(self):
        adapter = self.adapter(inspection=self.inspection())
        item, issue = self.judge(adapter, "check", ["selected:x", "open-return:1", "loaded:harness77-form", "closed:1"])
        self.assertEqual((item["status"], item["value"], issue), ("passed", "1", None))
        item, _ = self.judge(adapter, "open", ["selected:x", "open-return:1", "loaded:harness77-form"])
        self.assertEqual((item["status"], item["value"], item["form_issues"]), ("passed", "1", []))
        item, _ = self.judge(adapter, "result", ["selected:x", "loaded:harness77-form", "closed:1"])
        self.assertEqual((item["status"], item["value"]), ("passed", None))

    def test_open_fails_on_layout_or_missing_evidence(self):
        bad = self.inspection(units={"consistent": False, "max_residual_px": 9})
        item, _ = self.judge(self.adapter(inspection=bad), "open", ["open-return:1", "loaded:harness77-form"])
        self.assertEqual(item["status"], "failed")
        self.assertIn("max residual 9", item["form_issues"][0])
        item, _ = self.judge(self.adapter(), "open", ["open-return:1", "loaded:harness77-form"])
        self.assertIn("no form inspection evidence", item["form_issues"])

    def test_click_outcomes(self):
        lines = ["loaded:harness77-form", "clicked:1", "closed:1"]
        clicked = self.inspection(click={"control_id": 4152, "record_id": 4161, "found": True, "returned": True,
                                         "button": {"inside_client": True}})
        item, _ = self.judge(self.adapter({"click_id": 4161}, clicked), "result", lines)
        self.assertEqual((item["status"], item["value"]), ("passed", "clicked:1"))
        # F3: the handler wrote nothing.
        item, _ = self.judge(self.adapter({"click_id": 4161}, clicked), "result", lines[:1] + lines[2:])
        self.assertEqual(item["status"], "failed")
        self.assertIn("exactly once", item["form_issues"][0])
        # Twice is not once.
        item, _ = self.judge(self.adapter({"click_id": 4161}, clicked), "result", lines[:2] + ["clicked:2"] + lines[2:])
        self.assertEqual(item["status"], "failed")
        # F2 (y 4): under the caption, the click alone is not enough.
        hidden = self.inspection(click={"control_id": 4152, "record_id": 4161, "found": True, "returned": True,
                                        "button": {"inside_client": False}})
        item, _ = self.judge(self.adapter({"click_id": 4161}, hidden), "result", lines)
        self.assertEqual(item["form_issues"], ["button 4161 is not wholly inside the form's client area"])
        # F4: no such button, nothing was sent.
        missing = self.inspection(click={"control_id": 4161, "record_id": 4161, "found": False, "requested": False})
        item, _ = self.judge(self.adapter({"click_id": 4161}, missing), "result", lines[:1] + lines[2:])
        self.assertEqual(item["form_issues"][:1], ["button 4161 not found"])

    def test_actions_parameter(self):
        self.assertEqual(form.actions({}), [])
        self.assertEqual(form.actions({"click_id": 4161}), [{"action": "click", "id": 4161}])
        self.assertEqual(form.actions({"actions": "type:4167=Тест77, click:4164,click:4161"}), [
            {"action": "type", "id": 4167, "text": "Тест77"}, {"action": "click", "id": 4164},
            {"action": "click", "id": 4161}])
        self.assertEqual(form.actions({"actions": "type:4167=a=b"})[0]["text"], "a=b")
        for bad in ({"actions": ""}, {"actions": 5}, {"actions": "press:4161"}, {"actions": "click:0"},
                    {"actions": "click:x"}, {"actions": "type:4167"}, {"actions": "type:4167="},
                    {"actions": "type:4167=✓"}, {"actions": "click:4161", "click_id": 4161}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                form.FormAdapter().commands(bad, [])

    def test_actions_outcomes(self):
        parameters = {"actions": "type:4167=Тест77,click:4164,click:4161"}
        lines = ["selected:x", "loaded:harness77-form", "flag:0", "clicked:1", "value:Строка77=Строка|Тест77",
                 "label:Надпись 77", "closed:1"]
        typed = {"action": "type", "record_id": 4167, "found": True, "returned": True, "message": "WM_CHAR",
                 "field": {"inside_client": True}}
        flag = {"action": "click", "record_id": 4164, "found": True, "returned": True, "message": "BM_CLICK",
                "button": {"inside_client": True}}
        button = dict(flag, record_id=4161)
        item, _ = self.judge(self.adapter(parameters, self.inspection(actions=[typed, flag, button], click=button)),
                             "result", lines)
        self.assertEqual((item["status"], item["value"], item["form_issues"]), (
            "passed", "flag:0;clicked:1;value:Строка77=Строка|Тест77;label:Надпись 77", []))
        self.assertEqual([a["record_id"] for a in item["actions"]], [4167, 4164, 4161])
        # The sequence stops at a message that did not return; the rest never happened.
        stuck = dict(typed, returned=False)
        item, _ = self.judge(self.adapter(parameters, self.inspection(actions=[stuck])), "result",
                             lines[:2] + lines[-1:])
        self.assertEqual(item["form_issues"][0], "WM_CHAR to field 4167 did not return")
        self.assertIn("exactly once", item["form_issues"][-1])
        outside = dict(flag, button={"inside_client": False})
        item, _ = self.judge(self.adapter(parameters, self.inspection(actions=[typed, outside, button])),
                             "result", lines)
        self.assertEqual(item["form_issues"], ["button 4164 is not wholly inside the form's client area"])
        item, _ = self.judge(self.adapter(parameters, self.inspection(actions=[])), "result", lines)
        self.assertEqual(item["form_issues"][0], "field 4167 not found")

    def test_representations_are_kept_apart_from_the_value(self):
        parameters = {"actions": "click:4161"}
        lines = ["selected:x", "loaded:harness77-form", "clicked:1", "value:Пол77=Перечисление|Пол|same:1|empty:0",
                 "repr:Пол77=Женский", "repr:Контрагент77=ООО \"Ромашка\" = 1", "closed:1"]
        button = {"action": "click", "record_id": 4161, "found": True, "returned": True, "message": "BM_CLICK",
                  "button": {"inside_client": True}}
        item, _ = self.judge(self.adapter(parameters, self.inspection(actions=[button], click=button)),
                             "result", lines)
        self.assertEqual((item["status"], item["value"]),
                         ("passed", "clicked:1;value:Пол77=Перечисление|Пол|same:1|empty:0"))
        self.assertEqual(item["representations"], {"Пол77": "Женский", "Контрагент77": 'ООО "Ромашка" = 1'})

    def test_judge_captions(self):
        ids = window.window_ids(DESCRIPTION)
        controls = [{"id": ids[i], "text": f"Надпись {i}"} for i in EXPECTED]
        self.assertEqual(window.judge_captions(DESCRIPTION, {"found": True, "controls": controls}), [])
        controls[0]["text"] = "Другое"
        self.assertEqual(window.judge_captions(DESCRIPTION, {"found": True, "controls": controls}),
                         ["control 4152 (STATIC) shows 'Другое', described 'Надпись 4152'"])
        field = {"controls": [dict(DESCRIPTION["controls"][0], **{"class": "1CEDIT"})]}
        self.assertEqual(window.judge_captions(field, {"found": True, "controls": [
            {"id": window.window_ids(field)[4152], "text": "значение"}]}), [])
        self.assertEqual(window.judge_captions(DESCRIPTION, {"found": False}), [])
        # A label with a formula shows the formula's value (task 022, f-doc of series 2).
        computed = {"controls": [dict(DESCRIPTION["controls"][0], caption="", formula="глПредставлениеРасчСчета(Контекст)")]}
        self.assertEqual(window.judge_captions(computed, {"found": True, "controls": [
            {"id": window.window_ids(computed)[4152], "text": "Р/с № 40702810716110100220"}]}), [])
        item, _ = self.judge(self.adapter(inspection=self.inspection(controls=controls)), "open",
                             ["open-return:1", "loaded:harness77-form"])
        self.assertEqual(item["status"], "failed")
        self.assertIn("shows 'Другое'", item["form_issues"][-1])

    def test_not_loaded(self):
        adapter = self.adapter(inspection=self.inspection())
        item, issue = self.judge(adapter, "check", ["selected:x", "open-error:compile"], diagnostics=[{"line": 2}])
        self.assertEqual((item["status"], issue), ("failed", None))
        item, issue = self.judge(adapter, "open", ["selected:x"])
        self.assertEqual(item["status"], "blocked")
        self.assertIn("no form loaded marker", issue)

    def test_capture_requests(self):
        requests = [{"state": "open", "window": "form"}, {"state": "clicked", "window": "dialog"},
                    {"state": "open", "window": "form"}]
        self.assertEqual(form.capture_requests(requests), requests[:2])
        self.assertEqual(form.capture_requests([]), [])
        for bad in ({"state": "open"}, [{"state": "closed", "window": "form"}], [{"state": "open", "window": "main"}],
                    [{"state": "open", "window": "form", "extra": 1}], ["open"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                form.capture_requests(bad)

    def test_clicked_state_needs_a_click(self):
        adapter = form.FormAdapter()
        adapter.request_captures([{"state": "clicked", "window": "form"}])
        (self.root / "noclick").mkdir()
        with self.assertRaisesRegex(ValueError, "click_id or actions"):
            adapter.prepare(self.root / "noclick", {})
        self.assertFalse((self.root / "noclick" / "form").exists())

    def test_captures_come_from_the_watcher_evidence(self):
        self.assertIsNone(self.adapter(inspection=self.inspection()).captures(self.run_dir))
        adapter = form.FormAdapter()
        adapter.request_captures([{"state": "open", "window": "form"}])
        (self.root / "cap").mkdir()
        adapter.prepare(self.root / "cap", {})
        self.assertEqual(adapter.captures(self.root / "cap"), [])  # the watcher recorded nothing
        shot = {"state": "open", "window": "form", "stable": True, "file": {"path": "form/capture-open-form.png"}}
        (self.root / "cap" / "form" / "form-window.json").write_text(json.dumps({"captures": [shot, "junk"]}),
                                                                    encoding="utf-8")
        self.assertEqual(adapter.captures(self.root / "cap"), [shot])

    def test_default_adapter_refuses_captures(self):
        default = launcher.Harness77Adapter()
        default.request_captures([])
        self.assertIsNone(default.captures(self.root))
        with self.assertRaisesRegex(ValueError, "does not capture"):
            default.request_captures([{"state": "open", "window": "form"}])

    def test_result_files_and_platform_status(self):
        adapter = self.adapter(inspection=self.inspection())
        files = adapter.result_files(self.run_dir, [])
        self.assertEqual([f["path"] for f in files], ["form/description.json", "form/form-window.json"])
        self.assertTrue(all(f["complete"] and len(f["sha256"]) == 64 for f in files))
        self.assertEqual(adapter.platform_status([{"status": "failed"}]), "passed")


class ConfigurationFormTests(unittest.TestCase):
    """Task 022: the controller opens a form of the configuration; its dialog comes from the opened base."""

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
        import test_md77_forms as fixtures
        self.fixtures = fixtures
        self.temp = tempfile.TemporaryDirectory(prefix="h77-cform-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / "1Cv7.MD").write_bytes(fixtures.forms_md())

    def test_the_controller_opens_the_named_form(self):
        self.assertEqual(form.controller_text({}), form.CONTROLLER)
        text = form.controller_text({"form_object": "Обработка.ВводАдреса"})
        self.assertIn('Открыта77 = ОткрытьФорму("Обработка.ВводАдреса", Контекст77);', text)
        self.assertNotIn('"Отчет", Контекст77, Путь', text)
        self.assertEqual(text.replace('"Обработка.ВводАдреса", Контекст77', '"Отчет", Контекст77, Путь'),
                         form.CONTROLLER)

    def test_the_controller_opens_the_forms_of_catalogs_and_journals(self):
        # Task 023: the syntax helper's calls, a new element or group as a new document in task 022.
        for name, call in (("Справочник.Банки.ФормаЭлемента", '"Элемент.Банки", Контекст77'),
                           ("справочник.банки.формагруппы", '"Элемент.банки", Контекст77, , 1'),
                           ("Справочник.Банки.ФормаСписка.Основная", '"Справочник.Банки.Основная", Контекст77'),
                           ("Журнал.Доверенности.ФормаСписка.ФормаСписка", '"Журнал.Доверенности.ФормаСписка", Контекст77'),
                           ("Отчет.КурсыВалют", '"Отчет.КурсыВалют", Контекст77')):
            with self.subTest(name=name):
                self.assertIn(f"Открыта77 = ОткрытьФорму({call});", form.controller_text({"form_object": name}))
        self.assertEqual(form.form_target("Справочник.Банки.ФормаГруппы")[:2], ("Справочник.Банки", "ФормаГруппы"))
        self.assertEqual(form.form_target("Журнал.Банк.ФормаСписка.Основная")[:2], ("Журнал.Банк", "ФормаСписка.Основная"))

    def test_the_expected_form_of_a_catalog_or_a_journal(self):
        (self.base / "1Cv7.MD").write_bytes(self.fixtures.catalog_md())
        element, source = form.configuration_description(self.base / "1Cv7.MD", "Справочник.Контрагенты.ФормаЭлемента")
        self.assertEqual((source["file"], element.get("browser")), (self.fixtures.ELEMENT_FORM, None))
        group, source = form.configuration_description(self.base / "1Cv7.MD", "Справочник.Контрагенты.ФормаГруппы")
        self.assertEqual(source["file"], self.fixtures.GROUP_FORM)
        listed, source = form.configuration_description(self.base / "1Cv7.MD",
                                                        "Справочник.Контрагенты.ФормаСписка.ФормаСписка")
        self.assertEqual((source["path"], listed["browser"]), (self.fixtures.LIST, {"position": 26, "columns": 1}))
        journal, source = form.configuration_description(self.base / "1Cv7.MD", "Журнал.Банк.ФормаСписка.ФормаСписка")
        self.assertEqual((source["path"], journal["browser"]), (self.fixtures.JOURNAL, {"position": 26, "columns": 1}))

    def test_a_subordinate_catalog_and_a_catalog_edited_in_its_list_are_refused(self):
        md = self.base / "1Cv7.MD"
        md.write_bytes(self.fixtures.catalog_md(edit="0"))
        with self.assertRaisesRegex(ValueError, "edited in its list; 1C opens no element form"):
            form.configuration_description(md, "Справочник.Контрагенты.ФормаЭлемента")
        # Its group form is not refused: no probe opened the group form of a catalog edited in its list.
        form.configuration_description(md, "Справочник.Контрагенты.ФормаГруппы")
        md.write_bytes(self.fixtures.catalog_md(edit="0").replace(
            "Subconto_Number133".encode("utf-16-le"), "Subconto_Number112".encode("utf-16-le")))
        with self.assertRaisesRegex(ValueError, r"the catalog has an owner \(Контрагенты\)"):
            form.configuration_description(md, "Справочник.Договоры.ФормаЭлемента")
        with self.assertRaisesRegex(ValueError, "no form of Справочник.Контрагенты.ФормаЭлемента"):
            form.configuration_description(md, "Справочник.Контрагенты.ФормаЭлемента")

    def test_parameters_are_checked(self):
        for parameters, message in (({"form_object": "Справочник.Контрагенты"}, "form_object is"),
                                    ({"form_object": "Справочник.Контрагенты.Форма"}, "form_object is"),
                                    ({"form_object": "Справочник.Контрагенты.ФормаСписка"}, "form_object is"),
                                    ({"form_object": "Журнал.Банк.ФормаЭлемента"}, "form_object is"),
                                    ({"form_object": "Обработка.Ввод Адреса"}, "form_object is"),
                                    ({"form_object": 1}, "form_object is")):
            with self.subTest(parameters=parameters), self.assertRaisesRegex(ValueError, message):
                form.FormAdapter().commands(parameters, ["open"])

    def test_the_expected_form_is_the_dialog_in_the_opened_base(self):
        description, source = form.configuration_description(self.base / "1Cv7.MD", "обработка.вводадреса")
        self.assertEqual(description, form77().describe(self.fixtures.DIALOG))
        self.assertEqual((source["path"], source["file"]), (self.fixtures.PROCESSING, self.fixtures.PROCESSING_FORM))
        document, _ = form.configuration_description(self.base / "1Cv7.MD", "Документ.Выписка")
        self.assertEqual(document["browser"], {"position": 26, "columns": 1})
        self.assertEqual({k: v for k, v in document.items() if k != "browser"},
                         form77().describe(self.fixtures.DOCUMENT_TEXT))
        with self.assertRaisesRegex(ValueError, "no form of Отчет.Нет"):
            form.configuration_description(self.base / "1Cv7.MD", "Отчет.Нет")

    def test_select_base(self):
        from shutdown77 import PINNED
        adapter = form.FormAdapter()
        adapter.commands({"form_object": "Документ.Выписка"}, ["open"])
        adapter.select_base(self.base, "f" * 64)
        self.assertEqual(adapter.configuration, PINNED["1Cv7.MD"])
        self.assertEqual(adapter.form[1]["path"], self.fixtures.DOCUMENT)
        plain = form.FormAdapter()
        plain.commands({}, ["open"])
        plain.select_base(self.base)
        self.assertIsNone(plain.form)
        self.assertIsNone(launcher.Harness77Adapter().select_base(self.base))


class TablePartWindowTests(unittest.TestCase):
    """Task 022: window IDs of a form with a table part, and the border of a field's window."""

    def test_window_ids_skip_the_columns_of_the_table_part(self):
        # f-doc (series 1): 41 records, table part after 26 windows, 4 columns.
        description = {"controls": [{"id": 4152 + i, "class": "STATIC"} for i in range(41)],
                       "browser": {"position": 26, "columns": 4}}
        ids = window.window_ids(description)
        self.assertEqual(sorted(ids.values()), list(range(4152, 4178)) + list(range(4182, 4197)))
        self.assertEqual((ids[4192], ids[4167], ids[4166], ids[4152]), (4152, 4177, 4182, 4196))
        del description["browser"]
        self.assertEqual(sorted(window.window_ids(description).values()), list(range(4152, 4193)))

    def test_the_tree_of_groups_of_a_list_form(self):
        # Task 023, l-button: new button, tree, then the list's 5 columns; the tree's window is 4679.
        description = {"controls": [{"id": 4152 + i, "class": "BUTTON"} for i in range(3)]
                       + [{"id": 4155, "class": "SysTreeView32"}, {"id": 4156, "class": "BUTTON"}],
                       "browser": {"position": 2, "columns": 5}}
        self.assertEqual(window.window_ids(description), {4156: 4152, 4155: 4679, 4154: 4159, 4153: 4160, 4152: 4161})
        # l-tree-third: two new buttons first, the tree third.
        description = {"controls": [{"id": 4152 + i, "class": "BUTTON"} for i in range(3)]
                       + [{"id": 4155, "class": "SysTreeView32"}, {"id": 4156, "class": "BUTTON"},
                          {"id": 4157, "class": "BUTTON"}], "browser": {"position": 3, "columns": 4}}
        self.assertEqual(sorted(window.window_ids(description).values()), [4152, 4153, 4159, 4160, 4161, 4679])
        # Without a list (an ERT) the class means nothing to the numbering.
        del description["browser"]
        self.assertEqual(sorted(window.window_ids(description).values()), list(range(4152, 4158)))

    def test_the_scale_comes_from_the_positions_and_the_sizes(self):
        # l-tree (run a761025b): two distinct x positions; the positions alone gave 1.4912 and 2.63 px.
        expected = {4157: (7, 163, 300, 26), 4158: (7, 191, 54, 13), 4159: (64, 191, 159, 13),
                    4679: (7, 19, 92, 141)}
        measured = {4157: (5, 241, 450, 42), 4158: (5, 286, 81, 21), 4159: (90, 286, 239, 21),
                    4679: (5, 7, 138, 229)}
        fit = window.fit_units(expected, measured)
        self.assertTrue(fit["consistent"], fit)
        self.assertAlmostEqual(fit["scale_x"], 1.5, delta=0.003)
        self.assertLess(fit["max_residual_px"], 1)

    def test_a_field_is_compared_without_its_border(self):
        # f-elements (series 1): fields are one pixel larger on every side; buttons and labels are exact.
        description = {"controls": [
            {"id": 4152, "class": "BUTTON", "x": 7, "y": 142, "width": 54, "height": 13},
            {"id": 4153, "class": "TABLE", "x": 7, "y": 19, "width": 314, "height": 120},
            {"id": 4154, "class": "STATIC", "x": 7, "y": 161, "width": 55, "height": 8},
            {"id": 4155, "class": "CHECKBOX", "x": 70, "y": 159, "width": 70, "height": 10},
            {"id": 4156, "class": "1CEDIT", "x": 150, "y": 158, "width": 80, "height": 13},
            {"id": 4157, "class": "BMASKED", "x": 240, "y": 158, "width": 60, "height": 13},
            {"id": 4158, "class": "BMASKED", "x": 7, "y": 176, "width": 100, "height": 13},
            {"id": 4159, "class": "BUTTON", "x": 120, "y": 176, "width": 54, "height": 13}]}
        measured = {4159: (5, 206, 81, 21), 4158: (5, 7, 471, 195), 4157: (5, 237, 83, 13), 4156: (99, 234, 105, 16),
                    4155: (218, 231, 122, 23), 4154: (353, 231, 92, 23), 4153: (4, 261, 152, 23),
                    4152: (174, 262, 81, 21)}
        expected = window.expected_geometry(description)
        edged = window.edged_ids(description)
        self.assertEqual(edged, {4153, 4154, 4155})
        # Without the border every field is ~2 px off (the fit of positions and sizes, task 023, keeps it just
        # inside the tolerance here; the fit of positions alone did not).
        plain = window.fit_units(expected, measured)
        self.assertTrue(all(plain["residuals_px"][str(i)] > 1.8 for i in edged), plain)
        fit = window.fit_units(expected, measured, edged=edged)
        self.assertTrue(fit["consistent"], fit)
        self.assertLess(fit["max_residual_px"], 1)
        self.assertEqual(fit["edged"], [4153, 4154, 4155])


def form77():
    from harness77 import form77 as module
    return module


if __name__ == "__main__":
    unittest.main()
