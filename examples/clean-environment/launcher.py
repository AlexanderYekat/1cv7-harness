"""Kit-local adapter entry point, recording the actual launcher's imports."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "native/forms"))
import form_launcher77 as form
import harness77

if __name__ == "__main__":
    native = Path(sys.argv[sys.argv.index("--run-dir") + 1])
    provenance = {"python": sys.executable, "prefix": sys.prefix,
                  "module": harness77.__file__, "sys_path": sys.path}
    if not Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("launcher must use the installed package in its venv")
    (native / "launcher-environment.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(form.launcher.main(adapter=form.FormAdapter()))
