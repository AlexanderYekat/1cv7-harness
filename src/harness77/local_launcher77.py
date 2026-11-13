"""Standalone project launcher. Copied verbatim by connect; uses only Python 3.11+.

No imports from harness77: a cloned project can bootstrap its pinned wheel.
"""
import sys
if sys.version_info < (3, 11):
    print('{"status":"blocked","reason":"Python >=3.11 is required"}')
    raise SystemExit(2)

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
import urllib.parse
import urllib.request
import zipfile


class ActivationError(ValueError):
    pass


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def python_at(directory):
    return Path(directory) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def clean_env():
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    return env


def command(argv, *, cwd=None):
    result = subprocess.run(list(map(str, argv)), cwd=cwd, env=clean_env(), capture_output=True,
                            timeout=300, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        # pip output may contain credentials from a user configuration. Never echo it.
        if 'download' in argv:
            details = (result.stdout + result.stderr).decode('utf-8', errors='replace')
            if 'DO NOT MATCH THE HASHES' in details:
                raise ActivationError('Downloaded wheel SHA-256 mismatch; package was not installed')
            filename = urllib.parse.urlsplit(str(argv[-1])).path.rsplit('/', 1)[-1]
            raise ActivationError('Cannot download pinned wheel ' + filename + '; check network and release availability')
        raise ActivationError(f'Command failed (exit {result.returncode}): {Path(str(argv[0])).name}; '
                              'check Python >=3.11 and pip with --python support')
    # Isolated Python on Windows may emit pip's path diagnostics in an ANSI
    # code page. Inspection JSON is ASCII; installer output is not interpreted.
    return result.stdout.decode('utf-8', errors='replace')


INSPECT = r'''
import base64, hashlib, importlib.metadata as m, json, pathlib, sys
d=m.distribution('harness77')
root=pathlib.Path(d.locate_file('harness77')).resolve()
files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
       for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
record={}
for p in d.files or []:
    if p.parts[0] == 'harness77' and p.hash and '__pycache__' not in p.parts and p.suffix != '.pyc':
        raw=pathlib.Path(d.locate_file(p)).read_bytes()
        assert base64.urlsafe_b64encode(hashlib.new(p.hash.mode, raw).digest()).rstrip(b'=').decode() == p.hash.value, 'RECORD integrity mismatch'
        record[pathlib.PurePosixPath(*p.parts[1:]).as_posix()]=hashlib.sha256(raw).hexdigest()
assert record == files, 'RECORD package file set mismatch'
print(json.dumps({'version':d.version,'files':files,'package':str(root),
                  'python':sys.executable,'python_version':list(sys.version_info[:2])}))
'''


def inspect(python):
    try:
        data = json.loads(command([python, '-I', '-B', '-c', INSPECT]))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ActivationError('Installed harness77 unavailable or damaged; check the configured Python') from exc
    if data['python_version'] < [3, 11]:
        raise ActivationError('Python >=3.11 is required')
    return data


def wheel_files(path, version, sha):
    if digest(path) != sha:
        raise ActivationError('Wheel SHA-256 mismatch: ' + str(path))
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        metadata = [n for n in names if re.fullmatch(r'harness77-[^/]+\.dist-info/METADATA', n)]
        headers = wheel.read(metadata[0]).decode('utf-8').splitlines() if len(metadata) == 1 else []
        if len(metadata) != 1 or 'Version: ' + version not in headers or 'Name: harness77' not in headers:
            raise ActivationError('Wheel version differs from pinned version ' + version)
        files = {n.removeprefix('harness77/'): hashlib.sha256(wheel.read(n)).hexdigest()
                 for n in names if n.startswith('harness77/') and not n.endswith('/')}
        if not files or len(set(names)) != len(names) or any('..' in Path(n).parts for n in names):
            raise ActivationError('Invalid wheel payload')
        return files


def validate_install(python, version, files):
    installed = inspect(python)
    if installed['version'] != version:
        raise ActivationError('Installed version differs from pinned version ' + version)
    if installed['files'] != files:
        raise ActivationError('Installed package integrity mismatch; do not use this environment')
    return installed


class Local:
    def __init__(self, config):
        self.config_path = Path(config).resolve()
        self.home = self.config_path.parent
        self.root = self.home.parent
        self.marker = self.root / 'harness77.txt'

    def enabled(self):
        return self.marker.is_file()

    def load(self):
        self.data = json.loads(self.config_path.read_text(encoding='utf-8'))
        if self.data.get('schema_version') != 1:
            raise ActivationError('Unsupported activation configuration')
        if not re.fullmatch(r'[0-9a-f]{64}', self.data.get('sha256', '')):
            raise ActivationError('A pinned SHA-256 is required')
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', self.data.get('version', '')):
            raise ActivationError('A concrete version is required')
        # Full digest is always verified; a short directory component also keeps
        # native payload paths usable on Windows installations without long paths.
        self.cache = self.home / 'cache' / (self.data['version'] + '-' + self.data['sha256'][:16])
        return self.data

    def path(self, value):
        return (self.home / value).resolve()

    def bindings(self):
        result = {key: str(self.path(value)) for key, value in self.data['bindings'].items()}
        for key, value in result.items():
            if not Path(value).is_file():
                raise ActivationError('Missing bound ' + key + ' profile: ' + value)
        if 'stand' not in result or not ({'project', 'suite'} & result.keys()):
            raise ActivationError('Bind a stand and a project or suite profile with connect')
        # Parse without importing or launching harness. Do not expose arbitrary profile contents.
        stand_path = Path(result['stand'])
        with stand_path.open('rb') as stream:
            stand = tomllib.load(stream)['stand']
        base = stand.get('base', {}).get('path')
        self.base = str((stand_path.parent / base).resolve()) if base else None
        self.backend = stand.get('backend')
        return result

    def select(self):
        data = self.data
        if data.get('external_python'):
            return 'external-installed', self.path(data['external_python'])
        if data.get('external_wheel'):
            path = self.path(data['external_wheel'])
            if not path.is_file():
                raise ActivationError('Explicit wheel path is unavailable: ' + str(path))
            wheel_files(path, data['version'], data['sha256'])
            return 'external-wheel', path
        if data.get('bundled_wheel'):
            path = self.path(data['bundled_wheel'])
            if path.exists():
                wheel_files(path, data['version'], data['sha256'])
                return 'bundled-wheel', path
        wheel = self.cache / data['wheel_name']
        if self.cache.exists():
            if not (self.cache / 'ready.json').is_file() or not wheel.is_file():
                raise ActivationError('Incomplete or damaged cache; remove this project cache explicitly')
            wheel_files(wheel, data['version'], data['sha256'])
            return 'cache', wheel
        if data.get('url'):
            return 'download', None
        raise ActivationError('Pinned wheel unavailable: ' + data['wheel_name'] + '; configure a path, bundle or URL')

    def cached(self, files):
        if not self.cache.exists():
            return None
        if not (self.cache / 'ready.json').is_file():
            raise ActivationError('Incomplete cache: ' + str(self.cache))
        try:
            receipt = json.loads((self.cache / 'ready.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ActivationError('Damaged cache receipt: ' + str(self.cache)) from exc
        if receipt != {'version': self.data['version'], 'sha256': self.data['sha256']}:
            raise ActivationError('Cache receipt differs from pinned version/SHA-256')
        cached_wheel = self.cache / self.data['wheel_name']
        if wheel_files(cached_wheel, self.data['version'], self.data['sha256']) != files:
            raise ActivationError('Cached wheel payload differs')
        return validate_install(python_at(self.cache / 'venv'), self.data['version'], files)

    def status(self, prepare=False):
        result = {'status': 'disabled', 'enabled': self.enabled(), 'ready': False,
                  'launch_performed': False, 'platform_checked': False}
        if not result['enabled']:
            result['reason'] = 'harness77.txt is absent; project integration disabled'
            return result
        self.load()
        result.update(version=self.data['version'], sha256=self.data['sha256'])
        bindings = self.bindings()
        result.update(bindings=bindings, base=self.base, backend=self.backend)
        source, wheel = self.select()
        result.update(source=source, wheel=str(wheel) if wheel else None)
        if source == 'external-installed':
            installed = validate_install(wheel, self.data['version'], self.data['installed_files'])
        else:
            files = wheel_files(wheel, self.data['version'], self.data['sha256']) if wheel else None
            installed = self.cached(files) if files else None
            if installed is None and prepare:
                self.prepare(wheel)
                files = wheel_files(self.cache / self.data['wheel_name'], self.data['version'], self.data['sha256'])
                installed = self.cached(files)
        if installed:
            result.update(status='ready', ready=True, python=installed['python'], package=installed['package'],
                          reason='Integration ready; use doctor to check the native stand')
        else:
            result.update(status='unprepared', reason='Run prepare or an enabled harness command to install the pinned wheel')
        return result

    def prepare(self, wheel):
        # The lock is fail-fast, never stolen on PID guesses. All processes use the
        # final venv location (venvs contain absolute paths and cannot be renamed).
        cache_parent = self.cache.parent
        cache_parent.mkdir(parents=True, exist_ok=True)
        lock = cache_parent / (self.cache.name + '.lock')
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ActivationError('Preparation in progress (or stale lock): ' + str(lock)) from exc
        try:
            os.close(fd)
            if not self.enabled():
                raise ActivationError('Integration disabled before preparation')
            if self.cache.exists():
                # A competing prepare may have finished between select and lock.
                files = wheel_files(self.cache / self.data['wheel_name'], self.data['version'], self.data['sha256'])
                self.cached(files)
                return
            command([sys.executable, '-I', '-m', 'pip', '--version'])
            self.cache.mkdir()
            try:
                target = self.cache / self.data['wheel_name']
                if wheel:
                    shutil.copyfile(wheel, target)
                else:
                    url = self.data['url']
                    parsed = urllib.parse.urlsplit(url)
                    if parsed.username or parsed.password or parsed.query or parsed.fragment:
                        raise ActivationError('Use a credential-free pinned wheel URL')
                    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
                        raise ActivationError('Wheel URL requires HTTPS (HTTP allowed only on loopback for qualification)')
                    # pip is the downloader; no index, dependencies or arbitrary package selection.
                    command([sys.executable, '-I', '-m', 'pip', '--isolated', 'download', '--no-deps', '--no-index',
                             '--dest', self.cache, url + '#sha256=' + self.data['sha256']])
                    if not target.is_file():
                        raise ActivationError('Download did not produce pinned wheel ' + self.data['wheel_name'])
                files = wheel_files(target, self.data['version'], self.data['sha256'])
                if not self.enabled():
                    raise ActivationError('Integration disabled before installation')
                command([sys.executable, '-I', '-m', 'venv', '--without-pip', self.cache / 'venv'])
                python = python_at(self.cache / 'venv')
                command([sys.executable, '-I', '-m', 'pip', '--isolated', '--python', python, 'install',
                         '--no-index', '--no-deps', '--no-compile', target])
                validate_install(python, self.data['version'], files)
                (self.cache / 'ready.json').write_text(json.dumps({'version': self.data['version'],
                    'sha256': self.data['sha256']}), encoding='utf-8')
            except BaseException:
                # Only our newly created cache, proven under this config's cache dir.
                if self.cache.resolve().parent != cache_parent.resolve() or self.cache.is_symlink():
                    raise ActivationError('Unsafe cache cleanup path')
                shutil.rmtree(self.cache)
                raise
        finally:
            lock.unlink()

    def invoke(self, argv):
        status = self.status(prepare=True)
        if not status['enabled']:
            return status, 2
        if not self.enabled():
            raise ActivationError('Integration disabled before invocation')
        bindings = self.bindings()
        operation = argv[0]
        arguments = list(argv[1:])
        for key in ('project', 'stand') if operation in ('doctor', 'run') else ('suite', 'stand') if operation == 'suite' else ():
            if not any(a == '--' + key or a.startswith('--' + key + '=') for a in arguments):
                if key not in bindings:
                    raise ActivationError('No bound ' + key + ' profile')
                arguments += ['--' + key, bindings[key]]
        if operation in ('doctor', 'run', 'suite') and not any(a == '--output-root' or a.startswith('--output-root=') for a in arguments):
            arguments += ['--output-root', str(self.home / 'results')]
        env = clean_env()
        env['HARNESS77_LOCAL_CONFIG'] = str(self.config_path)
        code = subprocess.call([status['python'], '-I', '-B', '-m', 'harness77', operation, *arguments],
                               cwd=self.root, env=env)
        return None, code


def main(argv=None, config=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = list(sys.argv[1:] if argv is None else argv)
    local = Local(config or Path(__file__).with_name('config.json'))
    try:
        if not args or args[0] in ('status', 'prepare'):
            parser = argparse.ArgumentParser(description=__doc__)
            parser.add_argument('command', choices=('status', 'prepare'), nargs='?', default='status')
            parser.add_argument('--format', choices=('json', 'text'), default='text')
            options = parser.parse_args(args)
            result = local.status(prepare=options.command == 'prepare')
            code = 0 if result['status'] in ('ready', 'disabled', 'unprepared') else 2
        else:
            result, code = local.invoke(args)
        if result is not None:
            if '--format' in args and len(args) > args.index('--format') + 1:
                json_output = args[args.index('--format') + 1] == 'json'
            else:
                json_output = False
            print(json.dumps(result, ensure_ascii=False, indent=2) if json_output else
                  '\n'.join(f'{key}: {value}' for key, value in result.items()))
        return code
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile):
        # Keep config/profile/URL secrets out of exception text and stdout.
        error = sys.exc_info()[1]
        reason = str(error) if isinstance(error, ActivationError) else 'Invalid or unavailable activation files; check config and Python/pip'
        result = {'status': 'blocked', 'ready': False, 'reason': reason,
                  'enabled': local.enabled(), 'launch_performed': False, 'platform_checked': False}
        if hasattr(local, 'data'):
            result.update(version=local.data.get('version'), sha256=local.data.get('sha256'),
                          wheel_name=local.data.get('wheel_name'))
        print(json.dumps(result, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
