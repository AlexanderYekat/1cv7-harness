"""099: real wheel acquisition and standalone run/suite/MCP from foreign CWD.

Uses a real loopback HTTP wheel source unless --url names an existing release.
No public release is created by this verifier. Simulation exercises transport;
the forms-project-init runner --local-activation qualifies the native cycle.
"""
import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import zipfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--installed-python', type=Path, required=True)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url')
    args = parser.parse_args()
    out, wheel = args.output.resolve(), args.wheel.resolve()
    args.installed_python = args.installed_python.resolve()
    args.template = args.template.resolve()
    out.mkdir(parents=True, exist_ok=False)
    working = out / 'foreign cwd'
    working.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'HARNESS77_LOCAL_CONFIG')}
    env.update(PYTHONIOENCODING='utf-8', PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    with zipfile.ZipFile(wheel) as archive:
        name, = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
        version, = [line.split(': ', 1)[1] for line in archive.read(name).decode().splitlines() if line.startswith('Version: ')]
    evidence = {'status': 'running', 'wheel': str(wheel), 'version': version, 'sha256': digest(wheel),
                'commands': [], 'modes': [], 'negative': [], 'http_requests': []}
    server = None
    client = None

    def save():
        (out / 'verified.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def execute(name, argv, expected=0):
        response = subprocess.run(list(map(str, argv)), cwd=working, env=env, capture_output=True, timeout=600)
        (out / (name + '.stdout.log')).write_bytes(response.stdout)
        (out / (name + '.stderr.log')).write_bytes(response.stderr)
        evidence['commands'].append({'name': name, 'argv': list(map(str, argv)), 'exit_code': response.returncode})
        save()
        assert response.returncode == expected, (name, response.returncode, expected, response.stdout, response.stderr)
        return json.loads(response.stdout)

    def fixture(root):
        root.mkdir(parents=True)
        shutil.copyfile(args.template, root / 'template.ert')
        (root / 'module.1s').write_text('Процедура Проверка() Экспорт\n Сообщить(42);\nКонецПроцедуры\n', encoding='utf-8')
        (root / 'AGENTS.md').write_bytes(b'# Existing application instructions\r\nKeep these.\r\n')
        (root / 'project.toml').write_text('''schema_version=1
[project]
id="activation099"
[build]
template="template.ert"
source="module.1s"
encoding="utf-8"
[[platform.tests]]
name="control-42"
expect="passed"
expect_value="42"
[deadlines]
open_timeout_s=30
calculation_timeout_s=60
cancel_timeout_s=10
shutdown_timeout_s=20
total_timeout_s=200
''', encoding='utf-8')
        (root / 'stand.toml').write_text('''schema_version=1
[stand]
name="sim099"
backend="simulation"
scenario="simulation.json"
platform_version="sim-7.70.027"
[stand.base]
path="existing-base"
user="ВВВ"
''', encoding='utf-8')
        (root / 'suite.toml').write_text('''schema_version=1
[suite]
id="local099"
[[scenarios]]
id="baseline"
project="project.toml"
''', encoding='utf-8')
        scenario = {'platform_identity': {'platform_version': 'sim-7.70.027'},
                    'open': {'duration_s': 1, 'samples': 1},
                    'calculation': {'duration_s': 2, 'samples': 2, 'load': {'status': 'passed', 'diagnostics': []},
                        'operations': [{'name': 'control-42', 'status': 'passed', 'value': '42'}], 'result_files': []},
                    'shutdown': {'duration_s': 1, 'status': 'ok', 'server_exit_code': 0,
                                 'cleanup_verified': True, 'others_preserved': True}}
        (root / 'simulation.json').write_text(json.dumps(scenario), encoding='utf-8')
        return {str(p): digest(p) for p in root.iterdir() if p.name != 'AGENTS.md'}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *items):
            evidence['http_requests'].append(format % items)

    try:
        if args.url:
            url = args.url
            evidence['download_scope'] = 'configured-release'
        else:
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(wheel.parent)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = f'http://127.0.0.1:{server.server_port}/{wheel.name}'
            evidence['download_scope'] = 'real-loopback-http; no published GitHub release claimed'
        evidence['download_url'] = url
        prefix = [args.installed_python, '-I', '-B', '-m', 'harness77', 'connect']
        for mode in ('external-installed', 'external-wheel', 'bundled-wheel', 'download'):
            root = out / ('проект с пробелами ' + mode)
            frozen = fixture(root)
            options = ['--external-python', args.installed_python] if mode == 'external-installed' else (
                ['--wheel', wheel, '--bundle'] if mode == 'bundled-wheel' else ['--wheel', wheel] if mode == 'external-wheel'
                else ['--version', version, '--url', url, '--sha256', evidence['sha256']])
            connect_cmd = [*prefix, '--directory', root, *options, '--format', 'json']
            execute(mode + '-connect', connect_cmd)
            managed = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            assert not execute(mode + '-reconnect', connect_cmd)['changed']
            assert managed == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            launcher = [sys.executable, '-I', '-B', root / '.harness77/launch.py']
            marker = root / 'harness77.txt'
            marker.unlink()
            request_count = len(evidence['http_requests'])
            assert execute(mode + '-disabled-prepare', [*launcher, 'prepare', '--format', 'json'])['status'] == 'disabled'
            assert execute(mode + '-disabled-run', [*launcher, 'run', '--format', 'json'], 2)['status'] == 'disabled'
            assert not (root / '.harness77/cache').exists()
            assert len(evidence['http_requests']) == request_count
            marker.touch()
            status = execute(mode + '-status', [*launcher, 'status', '--format', 'json'])
            assert status['source'] == mode
            assert len(evidence['http_requests']) == request_count
            if mode == 'download':
                config = root / '.harness77/config.json'
                original = config.read_bytes()
                wrong = json.loads(original)
                wrong['sha256'] = '0' * 64
                config.write_text(json.dumps(wrong), encoding='utf-8')
                rejected = execute('download-wrong-sha', [*launcher, 'prepare', '--format', 'json'], 2)
                assert 'SHA-256' in rejected['reason'], rejected
                assert not list((root / '.harness77/cache').iterdir())
                config.write_bytes(original)
                evidence['negative'].append('real HTTP download with wrong SHA-256 rejected before installation')
            prepared = execute(mode + '-prepare', [*launcher, 'prepare', '--format', 'json'])
            assert prepared['ready'] and prepared['version'] == version
            if mode == 'download' and server is not None:
                assert len(evidence['http_requests']) > request_count
                server.shutdown()
                server.server_close()
                server = None
            cache_files = {str(p): (digest(p), p.stat().st_mtime_ns) for p in (root / '.harness77/cache').rglob('*')
                           if p.is_file() and '__pycache__' not in p.parts}
            repeated = execute(mode + '-repeat-prepare', [*launcher, 'prepare', '--format', 'json'])
            assert repeated['ready'] and repeated['python'] == prepared['python']
            assert cache_files == {p: (digest(p), Path(p).stat().st_mtime_ns) for p in cache_files}
            assert execute(mode + '-doctor', [*launcher, 'doctor', '--format', 'json'])['status'] == 'ready'
            assert execute(mode + '-run', [*launcher, 'run'])['status'] == 'passed'
            assert execute(mode + '-suite', [*launcher, 'suite'])['status'] == 'passed'
            # Import only a qualification client, never harness implementation.
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples/application-suite'))
            from mcp_client import Client
            client = Client(working, out / (mode + '-mcp.json'), env, command=[*map(str, launcher), 'mcp'])
            result, _ = client.request('tools/call', {'name': 'suite', 'arguments': {'suite_id': 'mcp-suite'}})
            assert result['result']['structuredContent']['stdout']['status'] == 'passed', result
            marker.unlink()
            result, _ = client.request('tools/call', {'name': 'suite', 'arguments': {}})
            assert result['result']['isError'] and 'disabled' in result['result']['content'][0]['text']
            ping, _ = client.request('ping')
            assert ping['result'] == {}
            assert client.close() == 0
            client = None
            assert execute(mode + '-disabled-after', [*launcher, 'run', '--format', 'json'], 2)['status'] == 'disabled'
            marker.touch()
            assert all(digest(p) == sha for p, sha in frozen.items())
            evidence['modes'].append({'mode': mode, 'root': str(root), 'prepared': prepared,
                                      'repeat': repeated, 'doctor_run_suite_mcp': 'passed', 'profiles_unchanged': True})
            save()
            print(mode + ': verified', flush=True)
        # Copy only portable files; no old environment or author directory needed.
        bundle_root = Path(next(r['root'] for r in evidence['modes'] if r['mode'] == 'bundled-wheel'))
        clone = out / 'перенесённый проект'
        shutil.copytree(bundle_root, clone, ignore=shutil.ignore_patterns('cache', 'results', '__pycache__'))
        moved = [sys.executable, '-I', '-B', clone / '.harness77/launch.py']
        competing = [subprocess.Popen([*map(str, moved), 'prepare', '--format', 'json'], cwd=working, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        parallel = []
        for process in competing:
            stdout, stderr = process.communicate(timeout=600)
            result = json.loads(stdout)
            assert process.returncode in (0, 2), stderr
            assert result['status'] in ('ready', 'blocked'), result
            parallel.append({'exit_code': process.returncode, 'result': result})
        assert any(row['result']['status'] == 'ready' for row in parallel)
        evidence['parallel_preparation'] = parallel
        assert execute('clone-prepare-offline', [*moved, 'prepare', '--format', 'json'])['ready']
        assert execute('clone-run-offline', [*moved, 'run'])['status'] == 'passed'
        # Real damage of a verified environment must fail without rebuilding it.
        installed = Path(next(r['prepared']['package'] for r in evidence['modes'] if r['mode'] == 'bundled-wheel'))
        target = installed / 'cli.py'
        original = target.read_bytes()
        try:
            target.write_bytes(original + b'\n# injected corruption\n')
            damaged = execute('damaged-cache', [sys.executable, '-I', bundle_root / '.harness77/launch.py', 'run'], 2)
            assert damaged['status'] == 'blocked' and any(word in damaged['reason'] for word in ('integrity', 'damaged'))
        finally:
            target.write_bytes(original)
        evidence['negative'].append('corrupt installed cache refused, no silent reinstall')
        download_root = Path(next(r['root'] for r in evidence['modes'] if r['mode'] == 'download'))
        config = download_root / '.harness77/config.json'
        original_config = config.read_bytes()
        data = json.loads(original_config)
        data['sha256'] = '0' * 64
        if args.url:
            data['url'] = 'http://127.0.0.1:1/' + wheel.name
        # Server is now offline, and this pin has no cache.
        try:
            config.write_text(json.dumps(data), encoding='utf-8')
            missing = execute('offline-no-cache', [sys.executable, '-I', download_root / '.harness77/launch.py', 'prepare'], 2)
            assert missing['status'] == 'blocked' and not list((download_root / '.harness77/cache').glob('*.lock'))
        finally:
            config.write_bytes(original_config)
        restored = execute('cache-restored-offline', [sys.executable, '-I', download_root / '.harness77/launch.py', 'status', '--format', 'json'])
        assert restored['ready'] and restored['sha256'] == evidence['sha256']
        evidence['negative_controls_restored'] = True
        evidence['negative'].append('network unavailable and no matching cache refused')
        evidence['status'] = 'passed'
    except BaseException as exc:
        evidence.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        if client is not None:
            client.close()
        if server is not None:
            server.shutdown()
            server.server_close()
        save()
    print(out / 'verified.json')


if __name__ == '__main__':
    main()
