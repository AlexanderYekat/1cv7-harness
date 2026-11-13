"""Installed native runtime selection and read-only integrity inspection.

The qualified controller is loaded only in its own Windows subprocess, after
inspection. Importing this module (including doctor on another OS) is inert.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from . import __version__

ADAPTERS = ('headless', 'forms')
HERE = Path(__file__).resolve().parent


class RuntimeUnavailable(ValueError):
    pass


def inspect_runtime(adapter, *, root=None):
    """Validate the shipped file set, matching core version, and every SHA-256."""
    if adapter not in ADAPTERS:
        raise RuntimeUnavailable('unknown native runtime adapter: ' + str(adapter))
    payload = Path(root) if root is not None else HERE / '_native'
    try:
        catalog = json.loads((HERE / 'native_catalog77.json').read_text(encoding='utf-8'))
        manifest_path = payload / 'manifest.json'
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
        if manifest.get('schema_version') != 1 or manifest.get('runtime_version') != __version__:
            raise RuntimeUnavailable('native runtime schema/version differs from installed harness77 ' + __version__)
        if manifest.get('platform_version') != '7.70.027':
            raise RuntimeUnavailable('native runtime platform is not qualified')
        files = manifest.get('files')
        if not isinstance(files, dict) or set(files) != set(catalog['files']):
            raise RuntimeUnavailable('native runtime file set differs from the catalog')
        actual = {p.relative_to(payload).as_posix() for p in payload.rglob('*')
                  if p.is_file() and '__pycache__' not in p.relative_to(payload).parts}
        if actual != {*files, 'manifest.json'}:
            raise RuntimeUnavailable('native runtime has missing or unexpected files')
        for name, expected in files.items():
            if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
                raise RuntimeUnavailable('invalid native runtime hash: ' + name)
            if hashlib.sha256((payload / name).read_bytes()).hexdigest() != expected:
                raise RuntimeUnavailable('native runtime hash mismatch: ' + name)
        return {'adapter': adapter, 'runtime_version': manifest['runtime_version'],
                'platform_version': manifest['platform_version'], 'files_checked': len(files),
                'manifest_sha256': hashlib.sha256(raw).hexdigest()}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        if isinstance(error, RuntimeUnavailable):
            raise
        raise RuntimeUnavailable('native runtime inspection failed: ' + str(error)) from error


def launch_prefix(stand):
    adapter = stand.extra.get('runtime')
    if adapter is not None:
        return [sys.executable, '-B', '-m', 'harness77.native_runtime77', '--adapter', adapter]
    return [sys.executable, '-B', str(stand.extra['launcher'])]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--adapter', required=True, choices=ADAPTERS)
    args, remaining = parser.parse_known_args(argv)
    try:
        info = inspect_runtime(args.adapter)
        if os.name != 'nt':
            raise RuntimeUnavailable('native runtime requires Windows')
        if '--configuration-sha256' not in remaining:
            raise RuntimeUnavailable('packaged runtime requires a configuration built on a verified base copy')
        payload = HERE / '_native'
        sys.path[:0] = [str(payload / 'forms'), str(payload / 'platform77')]
        # Keep provenance separate from the controller's native evidence.
        out = Path(remaining[remaining.index('--run-dir') + 1])
        (out / 'launcher-environment.json').write_text(json.dumps({
            'python': sys.executable, 'prefix': sys.prefix, 'module': str(HERE / '__init__.py'),
            'runtime': info, 'payload': str(payload)}, indent=2) + '\n', encoding='utf-8')
        if args.adapter == 'forms':
            import form_launcher77 as form
            return form.launcher.main(remaining, adapter=form.FormAdapter())
        import stage4_launcher77 as launcher
        return launcher.main(remaining)
    except (RuntimeUnavailable, OSError, ValueError, IndexError) as error:
        print('native runtime: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
