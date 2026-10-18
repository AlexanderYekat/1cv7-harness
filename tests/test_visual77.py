"""Visual form tests (task 010): PNG, comparison, baselines, approval and the run stage.

Portable: images are drawn in the test or by the simulation backend; a fake
launcher stands for the native one. No 1C is started.
"""

import json
from pathlib import Path
import struct
import sys
import tempfile
import textwrap
import unittest
import zlib

from harness77 import visual77 as visual
from harness77.config77 import ConfigError, load_project

from stage4_fixtures import base_scenario, run, write_project, write_sim_stand

ENVIRONMENT = {"platform_version": "7.70.027", "configuration": "c" * 64, "windows_build": "10.0.26200",
               "system_dpi": 96, "window_dpi": 96, "theme": {"active": True, "name": "Aero.msstyles"},
               "font": {"dialog_base_units": [8, 16]}, "locale": {"user_lcid": 1049, "ansi_cp": 1251},
               "capture": {"method": "PrintWindow", "flags": 2}}
GREY, BLUE, BLACK = (240, 240, 240), (0, 0, 255), (0, 0, 0)


def image(width=20, height=10, fill=GREY, rects=()):
    pixels = bytearray(bytes(fill) * (width * height))
    for x, y, w, h, colour in rects:
        for row in range(y, y + h):
            pixels[(row * width + x) * 3:(row * width + x + w) * 3] = bytes(colour) * w
    return visual.Image(width, height, bytes(pixels))


def png_with_filters(img, channels=3, colour_type=2, filters=(0, 1, 2, 3, 4)):
    """A PNG whose rows use the given filter types in turn (to exercise the reader)."""
    stride = img.width * channels
    rows = []
    for y in range(img.height):
        line = img.rgb[y * img.width * 3:(y + 1) * img.width * 3]
        if channels == 4:
            line = b"".join(line[i:i + 3] + b"\xff" for i in range(0, len(line), 3))
        elif channels == 1:
            line = line[::3]
        rows.append(line)
    raw, previous = bytearray(), bytes(stride)
    for y, line in enumerate(rows):
        kind = filters[y % len(filters)]
        out = bytearray()
        for i, value in enumerate(line):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            predictor = (0, left, up, (left + up) >> 1, visual._paeth(left, up, corner))[kind]
            out.append((value - predictor) & 0xFF)
        raw += bytes((kind,)) + out
        previous = line
    header = struct.pack(">IIBBBBB", img.width, img.height, 8, colour_type, 0, 0, 0)
    return (visual.PNG_SIGNATURE + visual._chunk(b"IHDR", header)
            + visual._chunk(b"IDAT", zlib.compress(bytes(raw))) + visual._chunk(b"IEND", b""))


class PngTests(unittest.TestCase):
    def test_round_trip_is_deterministic(self):
        picture = image(rects=[(3, 2, 5, 4, BLUE)])
        data = visual.encode_png(picture)
        self.assertEqual(visual.decode_png(data), picture)
        self.assertEqual(visual.encode_png(visual.decode_png(data)), data)

    def test_all_row_filters_rgb_rgba_grey(self):
        picture = image(7, 6, rects=[(1, 1, 3, 2, (10, 200, 30)), (4, 3, 2, 3, BLACK)])
        self.assertEqual(visual.decode_png(png_with_filters(picture)), picture)
        self.assertEqual(visual.decode_png(png_with_filters(picture, channels=4, colour_type=6)), picture)
        grey = image(5, 4, fill=(90, 90, 90), rects=[(1, 1, 2, 2, (200, 200, 200))])
        self.assertEqual(visual.decode_png(png_with_filters(grey, channels=1, colour_type=0)), grey)

    def test_unreadable_images_are_refused(self):
        data = visual.encode_png(image())
        for bad, text in ((b"GIF89a" + data[6:], "not a PNG"),
                          (data[:-12], "no IEND"),
                          (data[:-20], "truncated"),
                          (data[:33] + data[33:40] + bytes([data[40] ^ 1]) + data[41:], "checksum")):
            with self.subTest(text), self.assertRaisesRegex(visual.VisualError, text):
                visual.decode_png(bad)
        sixteen = visual.PNG_SIGNATURE + visual._chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 16, 2, 0, 0, 0))
        sixteen += visual._chunk(b"IDAT", zlib.compress(b"\0" + bytes(6))) + visual._chunk(b"IEND", b"")
        with self.assertRaisesRegex(visual.VisualError, "unsupported PNG"):
            visual.decode_png(sixteen)

    def test_uniform_image_has_one_colour(self):
        self.assertEqual(image().colours(), 1)
        self.assertEqual(image(rects=[(0, 0, 1, 1, BLUE)]).colours(), 2)


class CompareTests(unittest.TestCase):
    def test_equal_images_pass(self):
        result, diff = visual.compare(image(), image())
        self.assertEqual((result["status"], result["diff_pixels"], result["diff_box"]), ("passed", 0, None))
        self.assertEqual((diff.width, diff.height), (20, 10))

    def test_moved_rectangle_fails_with_its_box(self):
        before, after = image(rects=[(2, 2, 4, 3, BLUE)]), image(rects=[(10, 2, 4, 3, BLUE)])
        result, diff = visual.compare(before, after)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["diff_pixels"], 24)
        self.assertEqual(result["diff_box"], {"x": 2, "y": 2, "width": 12, "height": 3})
        self.assertEqual(result["max_channel_delta"], 240)
        self.assertEqual(diff.pixel(2, 2), (255, 0, 0))
        self.assertNotEqual(diff.pixel(0, 0), (255, 0, 0))

    def test_mask_excludes_and_is_drawn_blue(self):
        before, after = image(), image(rects=[(5, 5, 1, 3, BLACK)])
        mask = {"x": 5, "y": 5, "width": 1, "height": 3, "reason": "caret"}
        result, diff = visual.compare(before, after, masks=[mask])
        self.assertEqual((result["status"], result["diff_pixels"], result["masked_pixels"]), ("passed", 0, 3))
        self.assertEqual(diff.pixel(5, 6)[2], 255)

    def test_tolerances(self):
        before, after = image(), image(rects=[(0, 0, 2, 1, (236, 240, 244))])
        self.assertEqual(visual.compare(before, after)[0]["diff_pixels"], 2)
        self.assertEqual(visual.compare(before, after, channel_tolerance=4)[0]["status"], "passed")
        self.assertEqual(visual.compare(before, after, max_diff_pixels=2)[0]["status"], "passed")
        self.assertEqual(visual.compare(before, after, max_diff_pixels=1)[0]["status"], "failed")

    def test_size_change_fails_even_within_tolerance(self):
        result, diff = visual.compare(image(20, 10), image(22, 10), max_diff_pixels=1000)
        self.assertEqual((result["status"], result["reason"]), ("failed", "image size differs"))
        self.assertEqual(result["diff_pixels"], 20)
        self.assertEqual((diff.width, diff.height), (22, 10))

    def test_environment(self):
        self.assertEqual(visual.environment_issues(ENVIRONMENT, dict(ENVIRONMENT)), [])
        issues = visual.environment_issues(ENVIRONMENT, dict(ENVIRONMENT, window_dpi=120))
        self.assertEqual(issues, ["window_dpi: baseline 96, capture 120"])
        partial = {k: v for k, v in ENVIRONMENT.items() if k != "locale"}
        self.assertEqual(visual.environment_issues(ENVIRONMENT, partial), ["locale: not recorded for the capture"])
        self.assertEqual(visual.environment_issues(partial, ENVIRONMENT), ["locale: not recorded for the baseline"])


class ConfigTests(unittest.TestCase):
    def parse(self, **table):
        return visual.parse_config(table, Path("C:/p"))

    def test_defaults(self):
        config = self.parse(baselines="b", checks=[{"name": "form-open", "state": "open"}])
        check = config.checks[0]
        self.assertEqual(config.baselines, Path("C:/p/b"))
        self.assertEqual((check.window, check.channel_tolerance, check.max_diff_pixels, check.mask_caret, check.masks),
                         ("form", 0, 0, True, ()))
        self.assertEqual(config.captures(), [{"state": "open", "window": "form"}])

    def test_refusals(self):
        good = {"name": "a", "state": "open"}
        cases = [({"checks": [good]}, "baselines"),
                 ({"baselines": "b", "checks": []}, "хотя бы одна"),
                 ({"baselines": "b", "checks": [dict(good, name="я")]}, "name"),
                 ({"baselines": "b", "checks": [good, good]}, "повтор"),
                 ({"baselines": "b", "checks": [dict(good, state="closed")]}, "state"),
                 ({"baselines": "b", "checks": [dict(good, window="main")]}, "window"),
                 ({"baselines": "b", "checks": [dict(good, channel_tolerance=256)]}, "channel_tolerance"),
                 ({"baselines": "b", "checks": [dict(good, max_diff_pixels=True)]}, "max_diff_pixels"),
                 ({"baselines": "b", "checks": [dict(good, masks=[{"x": 0, "y": 0, "width": 1, "height": 1}])]},
                  "причина"),
                 ({"baselines": "b", "checks": [dict(good, masks=[{"x": 0, "y": 0, "width": 0, "height": 1,
                                                                   "reason": "r"}])]}, "width"),
                 ({"baselines": "b", "checks": [dict(good, tolerance=1)]}, "неизвестные"),
                 ({"baselines": "b", "checks": [good], "auto_approve": True}, "неизвестные")]
        for table, text in cases:
            with self.subTest(text), self.assertRaisesRegex(visual.VisualError, text):
                visual.parse_config(table, Path("C:/p"))


def write_visual_project(directory, checks, baselines="baselines", tests=(("control-42", "passed"),)):
    path = write_project(directory, tests=tests)
    lines = ["", "[visual]", f'baselines = "{baselines}"']
    for check in checks:
        lines.append("[[visual.checks]]")
        for key, value in check.items():
            lines.append(f"{key} = {json.dumps(value) if not isinstance(value, list) else value_list(value)}")
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return path


def value_list(masks):
    return "[" + ", ".join("{" + ", ".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in m.items()) + "}"
                           for m in masks) + "]"


def capture(state="open", window="form", rects=(), **extra):
    spec = {"state": state, "window": window, "environment": dict(ENVIRONMENT),
            "image": {"width": 30, "height": 20, "fill": list(GREY), "rects": [list(r[:4]) + [list(r[4])]
                                                                               for r in rects]}}
    spec.update(extra)
    return spec


BUTTON = (20, 2, 8, 4, BLUE)
CHECKS = [{"name": "form-open", "state": "open"}, {"name": "form-clicked", "state": "clicked"}]


class VisualRunCase(unittest.TestCase):
    """A project with two visual checks on the simulation stand."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-visual-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = write_visual_project(self.root, CHECKS)
        self.baselines = self.root / "baselines"

    def go(self, captures, name, **calc):
        scenario = base_scenario(result_files=[], **calc)
        scenario["captures"] = captures
        stand = write_sim_stand(self.root, scenario)
        return run(self.project, stand, self.root / "runs" / name)

    def stage(self, report, name="visual"):
        return next(s for s in report["stages"] if s["stage"] == name)

    def approved(self, captures=None):
        report = self.go(captures or [capture(rects=[BUTTON]), capture("clicked", rects=[BUTTON])], "first")
        visual.approve(load_project(self.project).visual, report["run_dir"], approved_by="tester")
        return report


class RunStageTests(VisualRunCase):
    def test_no_baseline_blocks_and_creates_none(self):
        report = self.go([capture(rects=[BUTTON]), capture("clicked", rects=[BUTTON])], "first")
        self.assertEqual((report["status"], report["exit_code"]), ("blocked", 2))
        stage = self.stage(report)
        self.assertEqual(stage["status"], "blocked")
        self.assertIn("no approved baseline", stage["reason"])
        self.assertEqual(self.stage(report, "tests")["status"], "passed")
        self.assertFalse(self.baselines.exists())
        self.assertEqual([c["state"] for c in self.stage(report, "platform_check")["captures"]], ["open", "clicked"])

    def test_approved_baseline_passes_and_writes_evidence(self):
        self.approved()
        report = self.go([capture(rects=[BUTTON]), capture("clicked", rects=[BUTTON])], "second")
        self.assertEqual((report["status"], report["exit_code"]), ("passed", 0))
        rows = self.stage(report)["checks"]
        self.assertEqual([(r["name"], r["status"], r["diff_pixels"]) for r in rows],
                         [("form-open", "passed", 0), ("form-clicked", "passed", 0)])
        folder = Path(report["run_dir"]) / "visual" / "form-open"
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["actual.png", "baseline.png", "diff.png", "result.json"])
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["baseline"]["approved"]["by"], "tester")
        self.assertTrue(all(f["complete"] for f in rows[0]["files"].values()))

    def test_moved_button_fails_and_keeps_the_baseline(self):
        self.approved()
        before = {p.name: p.read_bytes() for p in self.baselines.iterdir()}
        moved = (12, 2, 8, 4, BLUE)
        report = self.go([capture(rects=[moved]), capture("clicked", rects=[moved])], "moved")
        self.assertEqual((report["status"], report["exit_code"]), ("failed", 1))
        row = self.stage(report)["checks"][0]
        self.assertEqual((row["status"], row["diff_box"]), ("failed", {"x": 12, "y": 2, "width": 16, "height": 4}))
        self.assertEqual({p.name: p.read_bytes() for p in self.baselines.iterdir()}, before)

    def test_missing_button_fails(self):
        self.approved()
        report = self.go([capture(), capture("clicked")], "missing")
        self.assertEqual(self.stage(report)["status"], "failed")
        self.assertEqual(self.stage(report)["checks"][0]["diff_pixels"], 32)

    def test_missing_unstable_or_failed_capture_blocks(self):
        self.approved()
        for name, captures, text in (
                ("absent", [capture(rects=[BUTTON])], "no capture of this state"),
                ("unstable", [capture(rects=[BUTTON]), capture("clicked", rects=[BUTTON], stable=False, attempts=6)],
                 "not stable after 6"),
                ("error", [capture(rects=[BUTTON]), {"state": "clicked", "window": "form",
                                                      "error": "the click did not happen"}], "capture failed")):
            with self.subTest(name):
                report = self.go(captures, name)
                stage = self.stage(report)
                self.assertEqual((report["exit_code"], stage["status"]), (2, "blocked"))
                self.assertIn(text, stage["checks"][1]["reason"])

    def test_environment_difference_blocks_without_comparing(self):
        self.approved()
        other = dict(ENVIRONMENT, system_dpi=120)
        report = self.go([capture(rects=[BUTTON], environment=other),
                          capture("clicked", rects=[BUTTON], environment=other)], "dpi")
        row = self.stage(report)["checks"][0]
        self.assertEqual((row["status"], row["environment_issues"]),
                         ("blocked", ["system_dpi: baseline 96, capture 120"]))
        self.assertNotIn("diff_pixels", row)

    def test_altered_baseline_blocks(self):
        self.approved()
        (self.baselines / "form-open.png").write_bytes(visual.encode_png(image(30, 20)))
        report = self.go([capture(rects=[BUTTON]), capture("clicked", rects=[BUTTON])], "altered")
        self.assertIn("does not match its record", self.stage(report)["checks"][0]["reason"])
        self.assertEqual(report["exit_code"], 2)

    def test_caret_masked_in_capture_and_baseline(self):
        caret_a, caret_b = {"x": 3, "y": 3, "width": 1, "height": 5}, {"x": 5, "y": 3, "width": 1, "height": 5}
        self.approved([capture(rects=[BUTTON, (3, 3, 1, 5, BLACK)], caret=caret_a),
                       capture("clicked", rects=[BUTTON])])
        report = self.go([capture(rects=[BUTTON, (5, 3, 1, 5, BLACK)], caret=caret_b),
                          capture("clicked", rects=[BUTTON])], "caret")
        row = self.stage(report)["checks"][0]
        self.assertEqual((row["status"], row["masked_pixels"]), ("passed", 10))
        self.assertEqual([m["reason"] for m in row["masks"]], ["system caret (capture)", "system caret (baseline)"])

    def test_profile_mask_and_tolerance(self):
        self.project = write_visual_project(self.root / "masked", [
            {"name": "form-open", "state": "open", "max_diff_pixels": 3,
             "masks": [{"x": 0, "y": 0, "width": 30, "height": 1, "reason": "строка состояния"}]}])
        self.baselines = self.root / "masked" / "baselines"
        self.approved([capture(rects=[BUTTON])])
        report = self.go([capture(rects=[BUTTON, (0, 0, 30, 1, BLACK), (0, 10, 3, 1, BLACK)])], "tolerated")
        row = self.stage(report)["checks"][0]
        self.assertEqual((row["status"], row["diff_pixels"], row["masked_pixels"]), ("passed", 3, 30))

    def test_evidence_write_error_blocks_with_a_report(self):
        self.approved()
        from unittest import mock
        with mock.patch.object(visual, "write_png", side_effect=OSError("disk full")):
            report = self.go([capture(rects=[BUTTON]), capture("clicked", rects=[BUTTON])], "full")
        self.assertEqual(report["exit_code"], 2)
        self.assertIn("visual evidence not written: OSError: disk full", self.stage(report)["reason"])
        self.assertTrue((Path(report["run_dir"]) / "run.json").is_file())

    def test_platform_failure_skips_visual(self):
        scenario_load = {"status": "failed", "diagnostics": [{"line": 1, "message": "Ошибка"}]}
        report = self.go([capture(rects=[BUTTON])], "broken", load=scenario_load)
        self.assertEqual((report["exit_code"], self.stage(report)["status"]), (1, "skipped"))

    def test_without_visual_section_no_stage(self):
        project = write_project(self.root / "plain")
        report = run(project, write_sim_stand(self.root / "plain", base_scenario(result_files=[])),
                     self.root / "runs" / "plain")
        self.assertNotIn("visual", [s["stage"] for s in report["stages"]])
        self.assertNotIn("captures", self.stage(report, "platform_check"))


class ApproveTests(VisualRunCase):
    """Approval is explicit and refuses anything it cannot vouch for."""

    def config(self):
        return load_project(self.project).visual

    def test_replace_is_explicit_and_recorded(self):
        first = self.approved()
        with self.assertRaisesRegex(visual.VisualError, "--replace"):
            visual.approve(self.config(), first["run_dir"], approved_by="tester")
        old = (self.baselines / "form-open.json").read_text(encoding="utf-8")
        second = self.go([capture(rects=[(12, 2, 8, 4, BLUE)]), capture("clicked", rects=[BUTTON])], "second")
        done = visual.approve(self.config(), second["run_dir"], checks=["form-open"], approved_by="owner", replace=True)
        record = json.loads((self.baselines / "form-open.json").read_text(encoding="utf-8"))
        self.assertEqual(done[0]["replaced"], json.loads(old)["image"]["sha256"])
        self.assertEqual((record["approved"]["by"], record["approved"]["run_id"]), ("owner", second["run_id"]))
        self.assertEqual(json.loads((self.baselines / "form-clicked.json").read_text(encoding="utf-8"))
                         ["approved"]["by"], "tester")

    def test_refusals_write_nothing(self):
        broken = self.go([capture(rects=[BUTTON])], "broken", load={"status": "failed", "diagnostics": []})
        unstable = self.go([capture(rects=[BUTTON]), capture("clicked", stable=False)], "unstable")
        bare = self.go([capture(rects=[BUTTON], environment={"platform_version": "7.70.027"}),
                        capture("clicked")], "bare")
        changed = self.go([capture(rects=[BUTTON]), capture("clicked")], "changed")
        (Path(changed["run_dir"]) / "form" / "capture-open-form.png").write_bytes(visual.encode_png(image(30, 20)))
        for report, kwargs, text in ((broken, {}, "did not pass its platform check"),
                                     (unstable, {}, "not stable"),
                                     (bare, {}, "environment not recorded"),
                                     (changed, {}, "changed after the run"),
                                     (unstable, {"checks": ["nope"]}, "no such visual check")):
            with self.subTest(text), self.assertRaisesRegex(visual.VisualError, text):
                visual.approve(self.config(), report["run_dir"], approved_by="tester", **kwargs)
        self.assertFalse(self.baselines.exists())

    def test_baseline_for_another_state_is_refused(self):
        self.approved()
        record = json.loads((self.baselines / "form-open.json").read_text(encoding="utf-8"))
        record["state"] = "clicked"
        (self.baselines / "form-open.json").write_text(json.dumps(record), encoding="utf-8")
        check = self.config().checks[0]
        with self.assertRaisesRegex(visual.VisualError, "another state or window"):
            visual.load_baseline(self.config(), check)


class CliTests(unittest.TestCase):
    def test_compare_and_approve_commands(self):
        from harness77.cli import main
        with tempfile.TemporaryDirectory(prefix="harness77-vcli-") as temp:
            root = Path(temp)
            visual.write_png(root / "a.png", image(rects=[BUTTON[:4] + (BLUE,)]))
            visual.write_png(root / "b.png", image())
            from contextlib import redirect_stdout, redirect_stderr
            import io
            with redirect_stdout(io.StringIO()) as out:
                code = main(["visual", "compare", str(root / "a.png"), str(root / "a.png"),
                             "--output", str(root / "same")])
            self.assertEqual((code, json.loads(out.getvalue())["status"]), (0, "passed"))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["visual", "compare", str(root / "a.png"), str(root / "b.png"),
                                       "--output", str(root / "moved")]), 1)
            self.assertTrue((root / "moved" / "diff.png").is_file())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["visual", "compare", str(root / "a.png"), str(root / "b.png"),
                                       "--mask", "0,0,20,10", "--output", str(root / "masked")]), 0)
            with redirect_stderr(io.StringIO()) as err:
                self.assertEqual(main(["visual", "compare", str(root / "a.png"), str(root / "none.png"),
                                       "--output", str(root / "missing")]), 2)
            self.assertEqual(json.loads(err.getvalue())["status"], "blocked")
            project = write_visual_project(root / "p", CHECKS)
            with redirect_stderr(io.StringIO()) as err:
                self.assertEqual(main(["visual", "approve", "--project", str(project), "--run", str(root / "nope"),
                                       "--by", "x"]), 2)
            self.assertIn("run report is unreadable", err.getvalue())

    def test_profile_errors_are_config_errors(self):
        with tempfile.TemporaryDirectory(prefix="harness77-vcfg-") as temp:
            path = write_visual_project(Path(temp), [{"name": "x", "state": "later"}])
            with self.assertRaisesRegex(ConfigError, "state"):
                load_project(path)


FAKE_LAUNCHER = textwrap.dedent('''
    import argparse, hashlib, json, sys
    from pathlib import Path
    sys.path.insert(0, __SRC__)
    from harness77.visual77 import Image, encode_png
    parser = argparse.ArgumentParser()
    for name in ("--run-dir", "--ert", "--ert-sha256", "--run-id", "--base", "--user", "--exe", "--result",
                 "--deadlines-json", "--cdb", "--helper", "--identity", "--captures-json"):
        parser.add_argument(name)
    args, _ = parser.parse_known_args()
    run_dir = Path(args.run_dir)
    (run_dir / "form").mkdir(parents=True)
    captures = []
    for request in json.loads(args.captures_json or "[]"):
        path = run_dir / "form" / ("capture-" + request["state"] + "-" + request["window"] + ".png")
        path.write_bytes(encode_png(Image(4, 3, bytes(36))))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        captures.append(dict(request, stable=True, attempts=2, environment=__ENV__,
                             file={"path": path.relative_to(run_dir).as_posix(),
                                   "sha256": "__TAMPER__" or digest, "complete": True}))
    out = {"run_id": args.run_id, "ert_sha256": args.ert_sha256, "platform_checked": True, "status": "passed",
           "load": {"status": "passed", "diagnostics": []},
           "operations": [{"name": "control-42", "status": "passed", "value": "42"}], "result_files": [],
           "captures": captures,
           "shutdown": {"status": "ok", "cleanup_verified": True, "server_exit_code": 0, "others_preserved": True}}
    Path(args.result).write_text(json.dumps(out), encoding="utf-8")
''')


class NativeContractTests(unittest.TestCase):
    """The native backend asks the launcher for captures and re-evidences them from disk."""

    def go(self, tamper):
        with tempfile.TemporaryDirectory(prefix="harness77-vnat-") as temp:
            root = Path(temp)
            (root / "base").mkdir()
            body = (FAKE_LAUNCHER.replace("__SRC__", repr(str(Path(visual.__file__).parents[1])))
                    .replace("__ENV__", repr(ENVIRONMENT)).replace("__TAMPER__", "0" * 64 if tamper else ""))
            (root / "launcher.py").write_text(body, encoding="utf-8")
            stand = root / "stand.toml"
            stand.write_text("\n".join([
                "schema_version = 1", "[stand]", 'name = "fake"', 'backend = "native"',
                f'launcher = "{(root / "launcher.py").as_posix()}"', "[stand.paths]",
                f'exe = "{Path(sys.executable).as_posix()}"', "[stand.base]",
                f'path = "{(root / "base").as_posix()}"', 'user = "ВВВ"']) + "\n", encoding="utf-8")
            project = write_visual_project(root, [{"name": "form-open", "state": "open", "window": "dialog"}])
            report = run(project, stand, root / "runs")
            platform = next(s for s in report["stages"] if s["stage"] == "platform_check")
            return report, platform["captures"]

    def test_captures_are_requested_and_checked(self):
        report, captures = self.go(tamper=False)
        self.assertEqual([(c["state"], c["window"], c["file"]["sha256_matches"]) for c in captures],
                         [("open", "dialog", True)])
        self.assertIn("no approved baseline", report["reason"])

    def test_a_capture_with_a_wrong_hash_is_incomplete(self):
        report, captures = self.go(tamper=True)
        self.assertFalse(captures[0]["file"]["complete"])
        self.assertIn("capture file missing or incomplete", report["reason"])


if __name__ == "__main__":
    unittest.main()
