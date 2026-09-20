#!/usr/bin/env python3
"""Authenticated bounded version discovery and semantic selection."""
import http.server
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

binary = Path(sys.argv[1]).resolve()
token = b'a' * 32
scoped = b'b' * 64
state = {'calls': [], 'status': 200, 'wire': b''}


def encode(versions):
    return b'LPV1' + len(versions).to_bytes(2, 'little') + b''.join(
        bytes([len(value)]) + value.encode() for value in versions)


class Handler(http.server.BaseHTTPRequestHandler):
    def respond(self, status, body):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        assert self.headers['Authorization'] == 'Bearer ' + token.decode()
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/v1/credentials':
            assert value == {'scope': 'package:read', 'repository': 'demo', 'lifetime_seconds': 300}
            self.respond(201, scoped)
        else:
            assert self.path == '/v1/credentials/revoke' and value == {'token': scoped.decode()}
            self.respond(200, b'revoked')

    def do_GET(self):
        state['calls'].append((self.command, self.path))
        assert self.path == '/v1/releases/acme/demo'
        assert self.headers['Authorization'] == 'Bearer ' + scoped.decode()
        body = state['wire'] if state['status'] == 200 else b'unavailable'
        self.respond(state['status'], body)

    def log_message(self, *_):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix='luc-catalog-') as temporary:
        root = Path(temporary)
        origin = f'http://127.0.0.1:{server.server_port}'
        vault = root / 'session'

        def run(args, success=True, password=b'vault-pass\n'):
            result = subprocess.run([binary, *map(str, args)], input=password,
                                    capture_output=True, timeout=30, cwd=root)
            assert (result.returncode == 0) == success, result.stderr
            for forbidden in (b'Sanitizer', b'runtime error:', b'trap:', b'vault-pass', token):
                assert forbidden not in result.stdout + result.stderr, result.stderr
            return result

        run(['auth-store', origin, 'acme', vault, '--secrets-stdin'],
            password=b'vault-pass\n' + token + b'\n')
        before = vault.read_bytes()
        state['wire'] = encode(['2.0.0', '1.9.3', '1.2.5', '1.2.0', '0.8.1'])
        versions = ['versions', origin, 'acme/demo', '--vault', vault, '--password-stdin']
        result = run(versions)
        assert result.stdout == b'2.0.0\n1.9.3\n1.2.5\n1.2.0\n0.8.1\n'
        assert state['calls'] == [('GET', '/v1/releases/acme/demo')]
        state['calls'].clear()
        resolve = ['resolve', origin, 'acme/demo', '^1.2.0', '--vault', vault, '--password-stdin']
        assert run(resolve).stdout == b'1.9.3\n'
        resolve[3] = '1.2.5'
        assert run(resolve).stdout == b'1.2.5\n'
        resolve[3] = '^3.0.0'
        run(resolve, False)

        # Authentication/argument failures happen before HTTP, and the vault is immutable.
        state['calls'].clear()
        run(versions, False, b'wrong\n')
        assert not state['calls']
        run(['versions', origin, '../bad', '--vault', vault, '--password-stdin'], False)
        assert not state['calls']

        # Every malformed or non-success response is rejected without printing versions.
        for wire in (b'', b'LPV1', b'NOPE\0\0', encode(['1.0.0']) + b'x',
                     encode(['1.0.0', '2.0.0']), b'LPV1\1\0\x3e1'):
            state['wire'] = wire
            result = run(versions, False)
            assert result.stdout == b''
        state['status'] = 503
        run(versions, False)
        assert vault.read_bytes() == before
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

print('PASS authenticated canonical version catalog and exact/caret selection', flush=True)
