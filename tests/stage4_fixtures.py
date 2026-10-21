"""Portable builders for stage-4 run tests. Not collected as tests itself."""

import json
import os
from pathlib import Path
import unittest

from harness77 import ert_module as ert
from harness77.config77 import load_project, load_stand, resolve_deadlines
from harness77.deadlines77 import ManualClock
from harness77.run77 import execute

from test_ert_dialog import make_ert, DIALOG

# The native backend refuses before its launcher off Windows (native_preflight),
# so the launcher contract is checked only there.
windows_only = unittest.skipUnless(os.name == "nt", "native backend: 1C 7.7 runs only on Windows")

DEFAULT_DEADLINES = {"open_timeout_s": 30, "calculation_timeout_s": 60,
                     "cancel_timeout_s": 10, "shutdown_timeout_s": 20, "total_timeout_s": 200}


def write_project(directory, *, tests=(("control-42", "passed"),), deadlines=DEFAULT_DEADLINES,
                  project_id="t", source_text="Сообщить(42);\n"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "form.ert").write_bytes(make_ert(ert.encode_dialog(DIALOG)))
    (directory / "module.1s").write_text(source_text, encoding="utf-8")
    lines = ["schema_version = 1", "[project]", f'id = "{project_id}"',
             "[build]", 'template = "form.ert"', 'source = "module.1s"', "[platform]"]
    for item in tests:
        spec = {"name": item[0], "expect": item[1]} if isinstance(item, tuple) else dict(item)
        lines.append("[[platform.tests]]")
        lines += [f'{key} = "{value}"' for key, value in spec.items()]
    if deadlines:
        lines.append("[deadlines]")
        lines += [f"{key} = {value}" for key, value in deadlines.items()]
    path = directory / "project.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_sim_stand(directory, scenario, *, name="sim", screenshots=False, base="C:/fake/base-for-test"):
    directory = Path(directory)
    (directory / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    path = directory / "stand.toml"
    path.write_text("\n".join([
        "schema_version = 1", "[stand]", f'name = "{name}"', 'backend = "simulation"',
        'scenario = "scenario.json"', 'platform_version = "sim-7.70.027"',
        f"screenshots = {'true' if screenshots else 'false'}",
        "[stand.base]", f'path = "{base}"', 'user = "ВВВ"']) + "\n", encoding="utf-8")
    return path


def base_scenario(**calc):
    calculation = {"duration_s": 2.0, "samples": 2, "load": {"status": "passed", "diagnostics": []},
                   "operations": [{"name": "control-42", "status": "passed", "value": "42"}],
                   "result_files": []}
    calculation.update(calc)
    return {"platform_identity": {"platform_version": "sim-7.70.027"},
            "open": {"duration_s": 1.0, "samples": 1},
            "calculation": calculation,
            "shutdown": {"duration_s": 1.0, "status": "ok", "server_exit_code": 0,
                         "cleanup_verified": True, "others_preserved": True}}


def run(project_path, stand_path, output_root, *, overrides=None, clock=None, run_id=None, cancel=None):
    project = load_project(project_path)
    stand = load_stand(stand_path)
    deadlines = resolve_deadlines(project, stand, overrides or {})
    return execute(project, stand, deadlines, output_root=output_root,
                   clock=clock or ManualClock(), run_id=run_id, cancel=cancel)
