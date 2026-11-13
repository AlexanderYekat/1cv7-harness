"""Explicit, project-only activation; never writes skills or global configuration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib

from . import __version__
from . import local_launcher77 as launcher

START = '<!-- harness77:begin -->'
END = '<!-- harness77:end -->'
RULE = f'''{START}
## harness77 (project local)

For suitable 1C 7.7 tasks, first check for `harness77.txt` in this project root.
When absent, do not invoke the project harness. When present, use Python >=3.11:
`python .harness77/launch.py status --format json`, then the same launcher with
`doctor`, `run`, `suite` or `mcp`. The launcher uses the existing bound profiles.
Read `.harness77/README.md` when setup or diagnostics are needed. The empty marker
only enables tool use; it does not request downloads, installation or a 1C run.
Check it before each new operation. Keep doctor, stand qualification, base-copy
safety and failed/blocked diagnostics. Do not change global settings or skills.
{END}
'''
IGNORE = 'cache/\nresults/\n__pycache__/\nconnect.lock\n'


def relative(path, home):
    try:
        return Path(os.path.relpath(Path(path).resolve(), home)).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()  # A Windows path on another drive.


def atomic_agents(path, contents):
    fd, name = tempfile.mkstemp(prefix='.harness77-agents-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def discover(root, kind):
    found = []
    for path in sorted(root.glob('*.toml')):
        with path.open('rb') as stream:
            data = tomllib.load(stream)
        if kind in data:
            found.append(path)
    if len(found) > 1:
        raise ValueError('Ambiguous ' + kind + ' profiles; pass --' + kind)
    return found[0] if found else None


def connect(directory, *, version=__version__, wheel=None, external_python=None, sha256=None,
            url=None, bundle=False, project=None, stand=None, suite=None):
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Project directory is required')
    home = root / '.harness77'
    if home.is_symlink():
        raise ValueError('Activation directory must not be a symlink')
    if bool(wheel) + bool(external_python) > 1:
        raise ValueError('Choose --wheel or --external-python')
    if bundle and not wheel:
        raise ValueError('--bundle requires --wheel')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('A concrete --version is required')
    bindings = {}
    for kind, value in (('project', project), ('stand', stand), ('suite', suite)):
        path = Path(value).resolve(strict=True) if value else discover(root, kind)
        if path:
            with path.open('rb') as stream:
                data = tomllib.load(stream)
            if kind not in data:
                raise ValueError('Not a ' + kind + ' profile: ' + str(path))
            bindings[kind] = relative(path, home)
    if 'stand' not in bindings or not ({'project', 'suite'} & bindings.keys()):
        raise ValueError('Bind existing project/suite and stand profiles; use --project/--suite/--stand')
    config = {'schema_version': 1, 'version': version, 'bindings': bindings,
              'wheel_name': f'harness77-{version}-py3-none-any.whl'}
    wheel_path = None
    if wheel:
        wheel_path = Path(wheel).resolve(strict=True)
        if wheel_path.name != config['wheel_name']:
            raise ValueError('Expected wheel ' + config['wheel_name'])
        actual_sha = launcher.digest(wheel_path)
        if sha256 and sha256.lower() != actual_sha:
            raise ValueError('Wheel SHA-256 mismatch')
        sha256 = actual_sha
        launcher.wheel_files(wheel_path, version, sha256)
        config['bundled_wheel' if bundle else 'external_wheel'] = ('packages/' + wheel_path.name
                                                                  if bundle else relative(wheel_path, home))
    elif external_python:
        installed = launcher.inspect(Path(external_python).resolve(strict=True))
        if installed['version'] != version:
            raise ValueError('Installed version differs from --version')
        # An explicit installed distribution is pinned to the exact observed payload.
        config.update(external_python=relative(external_python, home), installed_files=installed['files'])
        sha256 = hashlib.sha256(json.dumps(installed['files'], sort_keys=True).encode()).hexdigest()
    if not sha256 or not re.fullmatch(r'[0-9a-fA-F]{64}', sha256):
        raise ValueError('Provide --wheel, --external-python or a trusted --sha256 with --url')
    config['sha256'] = sha256.lower()
    if url:
        parsed = launcher.urllib.parse.urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use a credential-free pinned URL without query or fragment')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ValueError('URL requires HTTPS; HTTP is allowed only on loopback for tests')
        if Path(parsed.path).name != config['wheel_name']:
            raise ValueError('URL must identify the exact pinned wheel filename')
        config['url'] = url
    if not wheel and not external_python and not url:
        raise ValueError('No package source configured')
    agents = root / 'AGENTS.md'
    if agents.is_symlink():
        raise ValueError('AGENTS.md must not be a symlink')
    original = agents.read_bytes() if agents.exists() else None
    text = (original or b'').decode('utf-8')
    if text.count(START) != text.count(END) or text.count(START) > 1:
        raise ValueError('Incompatible managed AGENTS.md block')
    if START in text:
        begin, end = text.index(START), text.index(END) + len(END)
        if begin > end or text[begin:end] != RULE.rstrip('\n'):
            raise ValueError('Managed rule was edited; reconcile it explicitly before reconnecting')
        new_agents = original
    else:
        new_agents = (original or b'') + (b'\n\n' if original else b'') + RULE.encode('utf-8')
    from importlib.resources import files
    payload = {'config.json': (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode('utf-8'),
               'launch.py': Path(launcher.__file__).read_bytes(), '.gitignore': IGNORE.encode(),
               'README.md': files('harness77').joinpath('local_project77.md').read_bytes()}
    if bundle:
        payload['packages/' + wheel_path.name] = wheel_path.read_bytes()
    marker = root / 'harness77.txt'
    if marker.exists() and not marker.is_file():
        raise ValueError('harness77.txt must be a file')
    if home.exists():
        for name, contents in payload.items():
            path = home / name
            if not path.is_file() or path.is_symlink() or path.read_bytes() != contents:
                raise ValueError('Existing activation differs: ' + name + '; preserve it and reconnect explicitly in a new directory')
        if new_agents != original:
            raise ValueError('Incomplete activation: AGENTS.md block missing')
        return {'status': 'connected', 'directory': str(root), 'enabled': marker.is_file(), 'changed': False}
    # All compatibility checks precede writes. Publish the managed directory last;
    # rollback our rule and marker if publication fails. Serialize competing connects.
    lock = root / '.harness77-connect.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    stage = None
    created_marker = False
    wrote_agents = False
    try:
        os.close(fd)
        if (agents.read_bytes() if agents.exists() else None) != original or home.exists():
            raise ValueError('Project changed during connect; retry')
        stage = Path(tempfile.mkdtemp(prefix='.harness77-connect-', dir=root))
        for name, contents in payload.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        # Exclusive creation preserves an existing marker, including its bytes.
        if not marker.exists():
            with marker.open('xb'):
                pass
            created_marker = True
        atomic_agents(agents, new_agents)
        wrote_agents = True
        from .project_init77 import _rename_new
        _rename_new(stage, home)
        stage = None
    except BaseException:
        if wrote_agents and agents.read_bytes() == new_agents:
            atomic_agents(agents, original) if original is not None else agents.unlink()
        if created_marker and marker.is_file() and marker.read_bytes() == b'':
            marker.unlink()
        raise
    finally:
        if stage is not None:
            if stage.resolve().parent != root or stage.is_symlink() or not stage.name.startswith('.harness77-connect-'):
                raise ValueError('Unsafe connect cleanup path')
            shutil.rmtree(stage)
        lock.unlink()
    return {'status': 'connected', 'directory': str(root), 'enabled': True, 'changed': True,
            'launch_performed': False, 'platform_checked': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--version', default=__version__)
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--external-python', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--url')
    parser.add_argument('--bundle', action='store_true')
    for kind in ('project', 'stand', 'suite'):
        parser.add_argument('--' + kind, type=Path)
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    args = vars(parser.parse_args(argv))
    format_ = args.pop('format')
    try:
        result = connect(**args)
        code = 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result, code = {'status': 'blocked', 'reason': str(exc), 'launch_performed': False, 'platform_checked': False}, 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if format_ == 'json' else
          '\n'.join(f'{key}: {value}' for key, value in result.items()))
    return code
