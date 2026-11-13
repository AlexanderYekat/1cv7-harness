"""Assemble an offline task-088 kit; preparation never starts 1C."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# Runtime of the form adapter, including its optional step handlers. No probes,
# tests, product sources, sibling repositories or databases are transferred.
FORMS = "choice77 fixture77 form_launcher77 form_window77 journal77 journal_basis77 journal_children77 journal_copy77 journal_deletion77 scenario77 step_exchange77 tabs77".split()
PLATFORM = "concurrent77 desktop77 ert_probe77 marker_read77 modal_wait77 module_suite77 open_failure77 proxy_debug77 run_shutdown77 session77 shutdown77 stage4_launcher77 startup77 win32_modal77 win32_session77".split()
ASSETS = "ert_controller77.1s ert_probe77.vbs module_suite77.vbs open_failure77.vbs proxy_identity77.vbs shutdown77.vbs".split()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(k)} = {table(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(map(table, value)) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def prepare(stand_path, template, wheel, output):
    stand_path, template, wheel = [p.resolve(strict=True) for p in (stand_path, template, wheel)]
    stand = tomllib.loads(stand_path.read_text(encoding="utf-8"))["stand"]
    if stand["backend"] != "native" or not stand["base"].get("copy_path"):
        raise ValueError("a native stand with a registered copy_path is required")
    external = {"base": stand["base"]["path"], "copy_path": stand["base"]["copy_path"],
                **{k: stand["paths"][k] for k in ("exe", "cdb", "helper", "identity")}}
    if not all(Path(p).is_absolute() for p in external.values()):
        raise ValueError("stand paths must be absolute")
    if wheel.suffix != ".whl":
        raise ValueError("--wheel must be a built wheel")
    output = output.resolve()
    # CDB command files cannot quote arbitrary output paths.
    if not str(output).isascii() or any(c in str(output) for c in '"; \r\n'):
        raise ValueError("kit path must be ASCII without spaces or debugger separators")
    output.mkdir(parents=True, exist_ok=False)

    def copy(source, name):
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    for folder, names in (("forms", FORMS), ("platform77", PLATFORM)):
        for name in names:
            copy(ROOT / f"research/{folder}/{name}.py", f"native/{folder}/{name}.py")
    for name in ASSETS:
        copy(ROOT / "research/platform77" / name, "native/platform77/" + name)
    for name in ("run.py", "launcher.py", "README.md"):
        copy(HERE / name, name)
    for name in ("verify_document_form77.py", "verify_suite77.py"):
        copy(ROOT / "scripts" / name, "verification/" + name)
    copy(template, "inputs/template.ert")
    copy(ROOT / "research/forms/probe_module77.1s", "inputs/module.1s")
    copy(wheel, wheel.name)
    # DLLs are transferred as explicit pinned dependencies of this adapter.
    for key in ("helper", "identity"):
        copy(Path(external[key]), f"native/{key}.dll")
        stand["paths"][key] = f"native/{key}.dll"
    stand["launcher"] = "launcher.py"
    (output / "stand.toml").write_text("schema_version = 1\nstand = " + table(stand) + "\n", encoding="utf-8")
    scenario = (ROOT / "examples/document-form-cycle/scenario.toml").read_text(encoding="utf-8")
    for name in ("success", "wrong"):
        folder = output / name
        (folder / "configuration").mkdir(parents=True)
        content = scenario
        if name == "wrong":
            old, new = "|2|3:10:30;2:20:40;|", "|2|999:10:30;2:20:40;|"
            if content.count(old) != 1:
                raise ValueError("scenario negative control no longer matches")
            content = content.replace(old, new)
        header = '\n'.join([
            'schema_version = 1', '[project]', f'id = "clean-{name}"', '[build]',
            'template = "../inputs/template.ert"', 'source = "../inputs/module.1s"',
            'encoding = "utf-8"', '[configuration]', 'modules = "configuration"',
            '[deadlines]', 'open_timeout_s = 240', 'calculation_timeout_s = 120',
            'cancel_timeout_s = 15', 'shutdown_timeout_s = 30', 'total_timeout_s = 600', '',
        ])
        tomllib.loads(header + content)
        (folder / "project.toml").write_text(header + content, encoding="utf-8")
    for name, cases in (("suite", [("success", "success"), ("repeat", "success")]),
                        ("suite-failure", [("wrong", "wrong"), ("after-failure", "success")])):
        manifest = 'schema_version = 1\n[suite]\nid = "clean-document"\n'
        for case, project in cases:
            manifest += f'[[scenarios]]\nid = "{case}"\nproject = "{project}/project.toml"\n'
        (output / (name + ".toml")).write_text(manifest, encoding="utf-8")
    files = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "kit.json").write_text(json.dumps({"schema_version": 1, "files": files,
        "external": {k: v for k, v in external.items() if k not in ("helper", "identity")},
        "wheel": wheel.name}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output / "kit.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stand", "template", "wheel", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    prepare(args.stand, args.template, args.wheel, args.output)
