"""093: checkout-free stand-init example, using the accepted application inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def prepare(args):
    from harness77.config77 import load_stand
    source = args.inputs.resolve(strict=True)
    manifest = json.loads((source / 'kit.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == sha for name, sha in manifest['files'].items())
    stand = load_stand(source / 'stand.toml')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)

    def copy(path, name):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    for name in ('inputs/template.ert', 'inputs/module.1s', 'inputs/headless.1s',
                 'headless/project.toml', 'success/project.toml',
                 'verification/verify_document_form77.py', 'verification/verify_suite77.py'):
        copy(source / name, name)
    for name in ('headless', 'success'):
        (out / name / 'configuration').mkdir()
    for role in ('helper', 'identity'):
        copy(getattr(stand, role), 'dependencies/' + role + '.dll')
    copy(args.wheel, args.wheel.name)
    for name in ('run.py', 'README.md'):
        copy(Path(__file__).with_name(name), name)
    inputs = {'exe': stand.exe.as_posix(), 'cdb': stand.cdb.as_posix(), 'base': stand.base.as_posix(),
              'copy_path': stand.copy_path.as_posix(), 'user': stand.user, 'copy_exclude': list(stand.copy_exclude)}
    (out / 'inputs.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'kit.json').write_text(json.dumps({'schema_version': 1, 'wheel': args.wheel.name, 'files': files}, indent=2) + '\n', encoding='utf-8')
    print(out / 'kit.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True, help='verified task-092 input kit')
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args())
