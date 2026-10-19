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


if __name__ == "__main__":
    unittest.main()
