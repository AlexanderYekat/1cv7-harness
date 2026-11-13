"""095: assemble project inputs; runtime, MD extraction and execution stay installed."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def verified(path):
    path = path.resolve(strict=True)
    manifest = json.loads((path / 'kit.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((path / n).read_bytes()).hexdigest() == sha for n, sha in manifest['files'].items())
    return path, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application', type=Path, required=True)
    parser.add_argument('--stand-inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    app, _ = verified(args.application)
    stand, manifest = verified(args.stand_inputs)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)

    def copy(source, name):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    for name in ('inputs.json', 'inputs/template.ert', 'dependencies/helper.dll', 'dependencies/identity.dll'):
        copy(stand / name, name)
    copy(stand / manifest['wheel'], manifest['wheel'])
    copy(app / 'inputs/module.1s', 'inputs/form-module.1s')
    scenario = tomllib.loads((app / 'success/project.toml').read_text(encoding='utf-8'))['platform']
    (out / 'inputs/scenario.json').write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name in ('run.py', 'README.md'):
        copy(Path(__file__).with_name(name), name)
    for name in ('verify_document_form77.py', 'verify_suite77.py'):
        copy(ROOT / 'scripts' / name, 'verification/' + name)
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'kit.json').write_text(json.dumps({'schema_version': 1, 'wheel': manifest['wheel'], 'files': files}, indent=2) + '\n', encoding='utf-8')
    print(out / 'kit.json')


if __name__ == '__main__':
    main()
