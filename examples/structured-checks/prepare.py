"""096: assemble a standalone application kit using accepted 095 inputs and a new wheel."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=Path, required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    pilot, wheel, out = args.pilot.resolve(), args.wheel.resolve(), args.output.resolve()
    manifest = json.loads((pilot / 'kit.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((pilot / n).read_bytes()).hexdigest() == sha for n, sha in manifest['files'].items())
    assert wheel.name == 'harness77-0.5.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel) as zipped:
        assert 'harness77/structured77.py' in zipped.namelist()
    out.mkdir(parents=True, exist_ok=False)

    def copy(source, name):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    for name in ('inputs.json', 'inputs/template.ert', 'inputs/form-module.1s',
                 'dependencies/helper.dll', 'dependencies/identity.dll'):
        copy(pilot / name, name)
    for name in ('verify_document_form77.py', 'verify_suite77.py'):
        copy(ROOT / 'scripts' / name, 'verification/' + name)
    for name in ('expected.json', 'fixture-verify.1s', 'run.py', 'README.md'):
        copy(HERE / name, name)
    copy(wheel, wheel.name)
    scenario = json.loads((pilot / 'inputs/scenario.json').read_text(encoding='utf-8'))
    scenario['parameters']['fixture_verify'] = (HERE / 'fixture-verify.1s').read_text(encoding='utf-8')
    test = next(t for t in scenario['tests'] if t['command'] == 'verify')
    del test['expect_value']
    test['expect_json'] = (HERE / 'expected.json').read_text(encoding='utf-8')
    test['json_labels'] = {'/entries/0/amount': 'Проводка 1, сумма', '/entries/1/amount': 'Проводка 2, сумма'}
    (out / 'inputs/scenario.json').write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'kit.json').write_text(json.dumps({'schema_version': 1, 'wheel': wheel.name, 'files': files}, indent=2) + '\n', encoding='utf-8')
    print(out / 'kit.json')


if __name__ == '__main__':
    main()
