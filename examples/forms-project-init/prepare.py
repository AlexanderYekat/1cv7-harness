"""098: package explicit forms inputs, a new wheel and independent qualification tools."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-suite', type=Path, required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, wheel, out = args.application_suite.resolve(), args.wheel.resolve(), args.output.resolve()
    manifest = json.loads((source / 'kit.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((source / n).read_bytes()).hexdigest() == sha for n, sha in manifest['files'].items())
    with zipfile.ZipFile(wheel) as archive:
        metadata_name, = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
        metadata = archive.read(metadata_name).decode('utf-8')
        assert 'Name: harness77' in metadata.splitlines() and wheel.name.startswith('harness77-')
    out.mkdir(parents=True, exist_ok=False)
    for name in ('inputs.json', 'expected.json', 'inputs/template.ert', 'inputs/form-module.1s',
                 'inputs/scenario.json', 'dependencies/helper.dll', 'dependencies/identity.dll',
                 'verification/verify_document_form77.py', 'verification/verify_suite77.py',
                 'verification/support96.py'):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    shutil.copy2(HERE.parent / 'application-suite/mcp_client.py', out / 'mcp_client.py')
    shutil.copy2(source / 'verify.py', out / 'suite_verify.py')
    for name in ('run.py', 'verify.py', 'README.md'):
        shutil.copy2(HERE / name, out / name)
    shutil.copy2(wheel, out / wheel.name)
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'kit.json').write_text(json.dumps({'schema_version': 1, 'wheel': wheel.name,
        'parent_kit_sha256': hashlib.sha256((source / 'kit.json').read_bytes()).hexdigest(),
        'files': files}, indent=2) + '\n', encoding='utf-8')
    print(out / 'kit.json')


if __name__ == '__main__':
    main()
