"""Project and stand profile loading, validation, path resolution and secrets."""

import tempfile
import unittest
from pathlib import Path

from harness77.config77 import (ConfigError, load_project, load_stand, path_tag,
                                resolve_deadlines)
from harness77.deadlines77 import DeadlineError


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness77-cfg-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def minimal_project(self, extra=""):
        return self.write("project.toml", "schema_version = 1\n[project]\nid = 'p'\n"
                          "[build]\ntemplate = 'f.ert'\nsource = 'm.1s'\n" + extra)

    def minimal_stand(self, extra="", base_extra=""):
        return self.write("stand.toml", "schema_version = 1\n[stand]\nname = 's'\n"
                          "backend = 'simulation'\nscenario = 'scn.json'\n" + extra +
                          "[stand.base]\npath = 'base-for-test'\nuser = 'ВВВ'\n" + base_extra)

    def test_project_resolves_relative_paths_from_profile_dir(self):
        project = load_project(self.minimal_project())
        self.assertEqual(project.template, self.root / "f.ert")
        self.assertEqual(project.source, self.root / "m.1s")

    def test_project_requires_schema_version(self):
        path = self.write("bad.toml", "[project]\nid='p'\n[build]\ntemplate='f'\nsource='m'\n")
        with self.assertRaises(ConfigError):
            load_project(path)

    def test_test_expect_is_validated(self):
        path = self.minimal_project("[[platform.tests]]\nname='t'\nexpect='maybe'\n")
        with self.assertRaises(ConfigError):
            load_project(path)

    def test_stand_rejects_stored_password(self):
        with self.assertRaises(ConfigError):
            load_stand(self.minimal_stand(base_extra="password = 'secret'\n"))

    def test_stand_public_has_no_raw_paths_or_user(self):
        stand = load_stand(self.minimal_stand(extra="platform_version = '7.70.027'\n"
                                              "[stand.pinned]\n'1Cv7.MD' = 'abc'\n"))
        public = stand.public()
        text = str(public)
        self.assertNotIn("ВВВ", text)  # the user name is not echoed
        self.assertEqual(public["base"]["name"], "base-for-test")  # basename only
        self.assertNotIn(str(stand.base), text)  # no full machine path
        self.assertEqual(public["pinned_hashes"], {"1Cv7.MD": "abc"})

    def test_simulation_requires_scenario(self):
        path = self.write("s.toml", "schema_version=1\n[stand]\nname='s'\nbackend='simulation'\n"
                          "[stand.base]\npath='b'\n")
        with self.assertRaises(ConfigError):
            load_stand(path)

    def test_import_requires_protocol(self):
        path = self.write("s.toml", "schema_version=1\n[stand]\nname='s'\nbackend='import'\n"
                          "[stand.base]\npath='b'\n")
        with self.assertRaises(ConfigError):
            load_stand(path)

    def test_path_tag_is_name_and_hash(self):
        tag = path_tag("C:/x/y/база.ert")
        self.assertEqual(tag["name"], "база.ert")
        self.assertEqual(len(tag["sha256"]), 64)

    def test_deadline_precedence_cli_over_project_over_stand(self):
        project = load_project(self.minimal_project(
            "[deadlines]\ncalculation_timeout_s = 500\nopen_timeout_s = 30\n"))
        stand = load_stand(self.minimal_stand(
            "[deadlines]\nopen_timeout_s = 10\ncancel_timeout_s = 5\n"
            "shutdown_timeout_s = 5\ntotal_timeout_s = 1000\ncalculation_timeout_s = 1\n"))
        deadlines = resolve_deadlines(project, stand, {"calculation_timeout_s": 900})
        self.assertEqual(deadlines.calculation_s, 900)  # CLI wins
        self.assertEqual(deadlines.open_s, 30)          # project over stand
        self.assertEqual(deadlines.cancel_s, 5)         # stand only
        sources = deadlines.effective()["sources"]
        self.assertEqual((sources["calculation"], sources["open"], sources["cancel"]),
                         ("cli", "project", "stand"))

    def test_missing_deadline_is_rejected_without_prototype_default(self):
        project = load_project(self.minimal_project())
        stand = load_stand(self.minimal_stand())
        with self.assertRaises(ConfigError):
            resolve_deadlines(project, stand, {})

    def test_inconsistent_deadline_rejected(self):
        project = load_project(self.minimal_project(
            "[deadlines]\nopen_timeout_s=50\ncalculation_timeout_s=100\ncancel_timeout_s=10\n"
            "shutdown_timeout_s=10\ntotal_timeout_s=100\n"))
        stand = load_stand(self.minimal_stand())
        with self.assertRaises(DeadlineError):
            resolve_deadlines(project, stand, {})


if __name__ == "__main__":
    unittest.main()
