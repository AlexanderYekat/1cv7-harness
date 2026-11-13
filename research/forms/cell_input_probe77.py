"""090 control: expose one stale wrapper-focus snapshot to a chosen adapter.

The injected observation is explicitly recorded. Actual focus, window ownership,
input delivery and all subsequent observations remain the real Win32 ones.
This launcher is for the bounded old/new comparison, not the exported runtime.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import tomllib

import harness77


def prepare():
    from harness77.config77 import load_stand
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--old-kit", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    kit, old, out = args.kit.resolve(strict=True), args.old_kit.resolve(strict=True), args.output.resolve()
    stand = load_stand(kit / "stand.toml")
    settings = tomllib.loads((kit / "stand.toml").read_text(encoding="utf-8"))
    settings["stand"]["launcher"] = Path(__file__).resolve().as_posix()
    for role in ("exe", "cdb", "helper", "identity"):
        settings["stand"]["paths"][role] = getattr(stand, role).as_posix()
    settings["stand"]["base"].update(path=stand.base.as_posix(), copy_path=stand.copy_path.as_posix())

    def value(item):
        if isinstance(item, dict):
            return "{ " + ", ".join(json.dumps(k) + " = " + value(v) for k, v in item.items()) + " }"
        if isinstance(item, list):
            return "[" + ", ".join(map(value, item)) + "]"
        return json.dumps(item, ensure_ascii=False, allow_nan=False)

    def write(path, data):
        path.write_text("\n".join(json.dumps(k) + " = " + value(v) for k, v in data.items()) + "\n", encoding="utf-8")

    out.mkdir(parents=True, exist_ok=False)
    write(out / "stand.toml", settings)
    for name, runtime in (("old", old), ("fixed", kit)):
        folder = out / name
        (folder / "configuration").mkdir(parents=True)
        project = tomllib.loads((kit / "success/project.toml").read_text(encoding="utf-8"))
        for role in ("template", "source"):
            project["build"][role] = (kit / "success" / project["build"][role]).resolve(strict=True).as_posix()
        project["configuration"]["modules"] = "configuration"
        project["platform"]["parameters"]["cell_probe_runtime"] = runtime.as_posix()
        write(folder / "project.toml", project)
    write(out / "suite.toml", {"schema_version": 1, "suite": {"id": "wrapper-focus-ab"},
                               "scenarios": [{"id": name, "project": name + "/project.toml"} for name in ("old", "fixed")]})
    print(out / "suite.toml")


if "--prepare" in sys.argv:
    prepare()
    raise SystemExit(0)

parameters = json.loads(sys.argv[sys.argv.index("--parameters-json") + 1])
runtime = Path(parameters["cell_probe_runtime"]).resolve(strict=True)
sys.path.insert(0, str(runtime / "native/forms"))
import form_launcher77 as adapter

begin_table = adapter.FormWatcher.begin_table


def stale_focus_once(self, form, inspection, step, table, seen):
    if step["kind"] != "cell":
        return begin_table(self, form, inspection, step, table, seen)
    focused = form.focused
    observations = []

    def observe():
        actual = focused()
        if observations:
            return actual
        until = time.monotonic() + 1
        while True:
            control = form.editor_of(actual, table["hwnd"])
            if control and control["id"] == step["column_window"]:
                break
            if time.monotonic() >= until or self.stopped.wait(0.02):
                raise RuntimeError("probe could not locate the expected wrapper")
            actual = focused()
        if control["class"] != "1CEDIT":
            raise RuntimeError("probe is restricted to a 1CEDIT column")
        supplied = {"hwnd": control["hwnd"], "id": control["id"], "parent_id": 4151}
        observations.append({"actual": actual, "supplied": supplied})
        return supplied

    form.focused = observe
    try:
        chain = begin_table(self, form, inspection, step, table, seen)
        chain.record["cell_probe"] = {"mode": "one-stale-wrapper-snapshot", "runtime": str(runtime),
                                      "observations": observations}
        return chain
    finally:
        form.focused = focused


adapter.FormWatcher.begin_table = stale_focus_once
raise SystemExit(adapter.launcher.main(adapter=adapter.FormAdapter()))
