"""094: kit with explicit stand inputs and a template, without a ready project."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def prepare(args):
    source = args.inputs.resolve(strict=True)
    manifest = json.loads((source / 'kit.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((source / n).read_bytes()).hexdigest() == sha for n, sha in manifest['files'].items())
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)

    def copy(path, name):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    for name in ('inputs.json', 'inputs/template.ert', 'dependencies/helper.dll', 'dependencies/identity.dll'):
        copy(source / name, name)
    copy(args.wheel, args.wheel.name)
    for name in ('run.py', 'README.md'):
        copy(Path(__file__).with_name(name), name)
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'kit.json').write_text(json.dumps({'schema_version': 1, 'wheel': args.wheel.name, 'files': files}, indent=2) + '\n', encoding='utf-8')
    print(out / 'kit.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True, help='verified task-093 kit')
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args())
