"""098: reject altered generated projects on private copies; preserve native evidence."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    kit, native, out = args.kit.resolve(), args.native.resolve(), args.output.resolve()
    sys.path.insert(0, str(kit))
    spec = importlib.util.spec_from_file_location('forms_verifier098', kit / 'verify.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    original = verifier.verify_output(native)
    record = verifier.read(native / 'verified.json')
    import harness77
    from harness77 import basecopy77, native_runtime77 as runtime
    from harness77.doctor_windows77 import WindowsInspector, TITLES, COM_KEYS
    from support96 import md_difference, registry_tree, POSTING, CORRECT, REGRESSION
    assert Path(harness77.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    inputs = verifier.read(kit / 'inputs.json')
    base = Path(inputs['base'])
    baseline = record['baseline']
    assert basecopy77.listing(base) == baseline['source']
    assert {n: verifier.digest(base / n) for n in baseline['hashes']} == baseline['hashes']
    assert {key: registry_tree(key) for key in (TITLES, *COM_KEYS)} == baseline['registry']
    assert WindowsInspector().processes() == baseline['processes']
    assert not Path(inputs['copy_path']).exists() and not basecopy77.lock_path(Path(inputs['copy_path'])).exists()
    native_runtime = runtime.inspect_runtime('forms')
    assert native_runtime == baseline['runtime']
    index = verifier.read(native / 'extraction/modules.json')
    target_path, = [m['path'] for m in index['modules'] if m['file'] == POSTING]
    # Retain original newlines for exact MD comparison.
    module = (native / 'extraction' / POSTING).read_bytes().decode('utf-8')
    assert module.count(CORRECT) == 1 and REGRESSION not in module
    md_checks = {}
    for name, plan in record['plans'].items():
        path = Path(plan['md'])
        assert verifier.digest(path) == plan['md_sha256']
        source = module.replace(CORRECT, REGRESSION) if name == 'regression' else module
        md_checks[name] = md_difference(base / '1Cv7.MD', path, target_path, source)
        assert md_checks[name] == plan['audit']
        profile = Path(plan['project'])
        assert verifier.digest(profile) == plan['project_sha256']
        assert (profile.parent / 'configuration' / POSTING).read_bytes() == source.encode('utf-8')
    children = [Path(row['folder']) for row in record['runs']]
    children += [Path(row['report']).parent for group in record['suites'] for row in group['verification']['scenarios']]
    for folder in children:
        environment = verifier.read(folder / 'launcher-environment.json')
        assert environment['module'] == harness77.__file__ and environment['prefix'] == sys.prefix
        assert environment['runtime'] == native_runtime
    kit_manifest = verifier.read(kit / 'kit.json')
    with zipfile.ZipFile(kit / kit_manifest['wheel']) as archive:
        names = [n for n in archive.namelist() if n.startswith('harness77/') and not n.startswith('harness77/_native/')]
        for name in names:
            relative = name.removeprefix('harness77/')
            assert (runtime.HERE / relative).read_bytes() == archive.read(name)
        payload = json.loads(archive.read('harness77/_native/manifest.json'))
        assert len(payload['files']) == 33
        for name, sha in payload['files'].items():
            assert verifier.digest(runtime.HERE / '_native' / name) == sha
    seed = next(row for row in record['created'] if row['case'] == 'baseline')
    out.mkdir(parents=True, exist_ok=False)
    results = []

    def perform(name, mutate, rehash=None):
        row = copy.deepcopy(seed)
        folder = out / name
        assert folder.is_relative_to(out)
        shutil.copytree(Path(seed['report']['directory']), folder)
        row['report'].update(directory=str(folder), project=str(folder / 'project.toml'))
        verifier.creation(row)
        mutate(row, folder)
        if rehash:
            path = folder / rehash
            row['report']['files'][rehash] = {'sha256': verifier.digest(path), 'size_bytes': path.stat().st_size}
        try:
            verifier.creation(row)
        except (AssertionError, ValueError, OSError):
            results.append({'case': name, 'rejected': True, 'coordinated_hash': bool(rehash)})
        else:
            raise AssertionError('accepted alteration: ' + name)

    for name in ('module.1s', 'template.ert', 'scenario.json', 'project.toml'):
        perform('bytes-' + name, lambda row, folder, name=name: (folder / name).write_bytes(b'altered'))
    for name in ('module.1s', 'scenario.json'):
        perform('rehashed-' + name, lambda row, folder, name=name: (folder / name).write_bytes(b'altered'), name)

    def profile_change(old, new):
        def change(row, folder):
            path = folder / 'project.toml'
            raw = path.read_text(encoding='utf-8')
            assert old in raw
            path.write_text(raw.replace(old, new, 1), encoding='utf-8')
        return change

    for name, old, new in [('relative-source', 'source = "module.1s"', 'source = "../module.1s"'),
                           ('labels', 'Проводка 1, сумма', 'другая подпись'),
                           ('deadlines', 'total_timeout_s = 600.0', 'total_timeout_s = 601.0')]:
        perform(name, profile_change(old, new), 'project.toml')
    perform('runtime', lambda row, folder: row['report'].update(runtime='headless'))
    perform('launch', lambda row, folder: row['report'].update(launch_performed=True))
    perform('platform', lambda row, folder: row['report'].update(platform_checked=True))
    perform('input-sha', lambda row, folder: row['report']['inputs'][0].update(sha256='0' * 64))
    perform('file-size', lambda row, folder: row['report']['files']['module.1s'].update(size_bytes=0))
    perform('case', lambda row, folder: row.update(case='regression'))

    assert verifier.verify_output(native) == original
    evidence = {'status': 'passed', 'rejected': len(results), 'controls': results,
                'native_unchanged': True, 'verification': original,
                'md_checks': md_checks, 'installed_core_files': len(names), 'installed_native_files': 33,
                'native_children_checked': len(children), 'stand_preserved': True,
                'verifier_sha256': hashlib.sha256((kit / 'verify.py').read_bytes()).hexdigest()}
    (out / 'controls.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(out / 'controls.json')


if __name__ == '__main__':
    main()
