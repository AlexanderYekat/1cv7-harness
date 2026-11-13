"""097: assemble a standalone suite/MCP qualification kit from accepted 096."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--structured', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, out = args.structured.resolve(), args.output.resolve()
    manifest = json.loads((source / 'kit.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((source / n).read_bytes()).hexdigest() == sha for n, sha in manifest['files'].items())
    out.mkdir(parents=True, exist_ok=False)
    names = ['inputs.json', 'expected.json', manifest['wheel'], 'inputs/template.ert',
             'inputs/form-module.1s', 'inputs/scenario.json', 'dependencies/helper.dll',
             'dependencies/identity.dll', 'verification/verify_document_form77.py', 'verification/verify_suite77.py']
    for name in names:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    shutil.copy2(source / 'run.py', out / 'verification/support96.py')
    for name in ('run.py', 'verify.py', 'mcp_client.py', 'README.md'):
        shutil.copy2(HERE / name, out / name)
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'kit.json').write_text(json.dumps({'schema_version': 1, 'wheel': manifest['wheel'],
                                             'parent_kit_sha256': hashlib.sha256((source / 'kit.json').read_bytes()).hexdigest(),
                                             'files': files}, indent=2) + '\n', encoding='utf-8')
    print(out / 'kit.json')


if __name__ == '__main__':
    main()
