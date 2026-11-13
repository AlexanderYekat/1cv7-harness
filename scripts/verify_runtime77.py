"""092: installed runtime damage controls and explicit-launcher compatibility.

Run after the main native kit acceptance, with the kit's clean venv Python.
Damage is confined to a second disposable installation. The healthy kit and
the stand are independently snapshotted and preserved.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

import harness77
from harness77 import basecopy77
from harness77.config77 import load_stand
from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
from verify_doctor77 import digest, registry_tree, table
from verify_startup77 import startup_evidence


def write(path, data):
    path.write_text('\n'.join(json.dumps(k) + ' = ' + table(v) for k, v in data.items()) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--installer-python', type=Path, default=Path(sys.base_prefix) / 'python.exe')
    args = parser.parse_args()
    if os.name != 'nt' or sys.prefix == sys.base_prefix or os.environ.get('PYTHONPATH') or os.environ.get('PYTHONHOME'):
        parser.error('requires a clean Windows venv')
    if not Path(harness77.__file__).is_relative_to(Path(sys.prefix)):
        parser.error('harness77 must be installed in this venv')
    kit, out = args.kit.resolve(strict=True), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    working = out / 'working'
    working.mkdir()
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    kit_manifest = json.loads((kit / 'kit.json').read_text(encoding='utf-8'))
    isolated = out / 'venv'
    venv.EnvBuilder(with_pip=False).create(isolated)
    python = isolated / 'Scripts/python.exe'
    result = subprocess.run([str(args.installer_python), '-m', 'pip', '--python', str(python), 'install',
                             '--no-index', '--no-deps', str(kit / kit_manifest['wheel'])],
                            cwd=working, env=env, capture_output=True, timeout=90)
    (out / 'install.log').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0
    payload = isolated / 'Lib/site-packages/harness77/_native'
    project = kit / 'headless/project.toml'
    import tomllib
    settings = tomllib.loads((kit / 'stand-headless.toml').read_text(encoding='utf-8'))
    stand = load_stand(kit / 'stand-headless.toml')
    for role in ('exe', 'cdb', 'helper', 'identity'):
        settings['stand']['paths'][role] = getattr(stand, role).as_posix()
    settings['stand']['base'].update(path=stand.base.as_posix(), copy_path=stand.copy_path.as_posix())
    profile = out / 'stand.toml'
    write(profile, settings)
    inspector = WindowsInspector()
    lock = basecopy77.lock_path(stand.copy_path)
    guard = lock.with_name(lock.name + '.guard')
    guard_before = guard.read_bytes() if guard.exists() else None

    def snapshot():
        return {'source': basecopy77.listing(stand.base),
                'hashes': {n: digest(stand.base / n) for n in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                'registry': {key: registry_tree(key) for key in (TITLES, *COM_KEYS)}, 'processes': inspector.processes(),
                'copy': stand.copy_path.exists(), 'lock': lock.exists(), 'guard': digest(guard) if guard.exists() else None,
                'kit': {n: digest(kit / n) for n in kit_manifest['files']}}

    before = snapshot()
    evidence = {'status': 'running', 'checks': [], 'environment': {'python': str(python), 'healthy_module': harness77.__file__}}

    def execute(name, operation, expected, *, stand_path=profile):
        root = out / name
        command = [str(python), '-B', '-m', 'harness77', operation, '--project', str(project),
                   '--stand', str(stand_path), '--output-root', str(root)]
        if operation == 'doctor':
            command += ['--format', 'json']
        result = subprocess.run(command, cwd=working, env=env, capture_output=True, timeout=400)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
        assert result.returncode == expected, (name, result.returncode)
        if operation == 'doctor':
            report = json.loads(result.stdout)
            assert not root.exists() and not report['launch_performed'] and not report['platform_checked']
            if expected == 2:
                assert next(row for row in report['checks'] if row['id'] == 'stand.runtime')['status'] == 'blocked'
        else:
            reports = list(root.glob('*/run.json'))
            assert len(reports) == 1
            report = json.loads(reports[0].read_text(encoding='utf-8'))
            if expected == 2:
                assert report['status'] == 'blocked' and not report['platform_checked']
                assert 'native_preflight' in report['reason']
                folder = reports[0].parent
                assert not (folder / 'launcher-environment.json').exists()
                assert not (folder / 'native-launcher-stdout.txt').exists()
                assert not (folder / 'native').exists()
                stage = next(s for s in report['stages'] if s['stage'] == 'platform_check')
                copy = stage['base_copy']
                assert copy['source_check']['unchanged'] and copy['removal']['removed'] and copy['lock']['released']
            else:
                checked = startup_evidence(reports[0].parent, True)
                assert not checked['issues']
                evidence['legacy'] = checked
        if guard_before is None and not inspector.processes() and not stand.copy_path.exists() and not lock.exists():
            guard.unlink(missing_ok=True)
        assert snapshot() == before, name + ': stand changed'
        evidence['checks'].append({'case': name, 'operation': operation, 'exit_code': result.returncode,
                                   'status': report['status'], 'reason': report.get('reason'),
                                   'log_sha256': digest(out / (name + '.log'))})

    try:
        assert not before['processes'] and not before['copy'] and not before['lock']
        execute('healthy', 'doctor', 0)
        for name, file in (('missing', 'platform77/ert_probe77.vbs'), ('changed', 'platform77/session77.py'),
                           ('version', 'manifest.json')):
            target = payload / file
            original = target.read_bytes()
            try:
                if name == 'missing':
                    target.unlink()
                elif name == 'changed':
                    target.write_bytes(original + b'\n# controlled damaged installation\n')
                else:
                    manifest = json.loads(original)
                    manifest['runtime_version'] = 'wrong-version'
                    target.write_text(json.dumps(manifest), encoding='utf-8')
                execute(name + '-doctor', 'doctor', 2)
                execute(name + '-run', 'run', 2)
            finally:
                target.write_bytes(original)
        execute('restored', 'doctor', 0)
        legacy = out / 'legacy-launcher.py'
        legacy.write_text("import sys\nfrom harness77.native_runtime77 import main\nraise SystemExit(main(['--adapter', 'headless', *sys.argv[1:]]))\n", encoding='utf-8')
        settings['stand'].pop('runtime')
        settings['stand']['launcher'] = legacy.as_posix()
        old_profile = out / 'legacy-stand.toml'
        write(old_profile, settings)
        execute('explicit-launcher', 'run', 0, stand_path=old_profile)
        evidence['status'] = 'passed'
    except Exception as error:
        evidence.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        after = snapshot()
        evidence['unchanged'] = {key: value == after[key] for key, value in before.items()}
        if not all(evidence['unchanged'].values()):
            evidence['status'] = 'failed'
        (out / 'verified.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(out / 'verified.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
