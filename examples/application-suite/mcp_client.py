"""Small stdio JSON-RPC client; records the real installed MCP server's traffic."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


class Client:
    def __init__(self, cwd, output, env):
        self.output = Path(output)
        self.process = subprocess.Popen([sys.executable, '-B', '-m', 'harness77', 'mcp'], cwd=cwd, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.counter = 0
        self.messages = queue.Queue()
        self.traffic = []
        self.stderr = []

        def receive():
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
            self.messages.put(None)

        self.reader = threading.Thread(target=receive, daemon=True)
        self.errors = threading.Thread(target=lambda: self.stderr.extend(self.process.stderr), daemon=True)
        self.reader.start()
        self.errors.start()
        initialized, _ = self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                   'clientInfo': {'name': 'application-suite097', 'version': '1'}})
        assert 'result' in initialized
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def save(self):
        self.output.write_text(json.dumps(self.traffic, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def send(self, message):
        self.traffic.append({'direction': 'send', 'message': message})
        self.process.stdin.write(json.dumps(message, ensure_ascii=False).encode('utf-8') + b'\n')
        self.process.stdin.flush()

    def request(self, method, params=None, timeout=1800, ping_during=False):
        self.counter += 1
        identifier = self.counter
        self.send({'jsonrpc': '2.0', 'id': identifier, 'method': method, **({'params': params} if params is not None else {})})
        until = time.monotonic() + timeout
        progress, ping_id, ping_ok, result = [], None, False, None
        while result is None or (ping_id is not None and not ping_ok):
            remaining = until - time.monotonic()
            if remaining <= 0:
                self.send({'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': identifier}})
                self.save()
                raise TimeoutError(method)
            message = self.messages.get(timeout=remaining)
            assert message is not None, 'MCP stdout closed before response'
            self.traffic.append({'direction': 'receive', 'message': message})
            if message.get('method') == 'notifications/progress':
                progress.append(message['params'])
                if ping_during and ping_id is None:
                    self.counter += 1
                    ping_id = self.counter
                    self.send({'jsonrpc': '2.0', 'id': ping_id, 'method': 'ping'})
            elif message.get('id') == identifier:
                result = message
            elif ping_id is not None and message.get('id') == ping_id:
                assert message.get('result') == {}
                ping_ok = True
        self.save()
        return result, {'events': progress, 'ping_during': ping_ok}

    def suite(self, arguments):
        response, progress = self.request('tools/call', {'name': 'suite', 'arguments': arguments,
                                                        '_meta': {'progressToken': arguments['suite_id']}}, ping_during=True)
        assert 'error' not in response, response
        ping, _ = self.request('ping', timeout=30)
        assert ping.get('result') == {}
        progress['ping_after'] = True
        return response['result'], progress

    def close(self):
        self.process.stdin.close()
        code = self.process.wait(timeout=180)
        self.reader.join(timeout=5)
        self.errors.join(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()
        self.output.with_suffix('.stderr.log').write_bytes(b''.join(self.stderr))
        self.save()
        return code
