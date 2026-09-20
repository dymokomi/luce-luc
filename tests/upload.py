"""Native upload: exact retries, uncertain outcomes and read-only reconciliation."""
import http.server
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

binary, fixture = [Path(v).resolve() for v in sys.argv[1:]]
state = dict(calls=[], stored=False, mode='normal', corrupt='', key=b'')
parts = {}
token = b'a' * 32
publish_token = b'b' * 64
read_token = b'c' * 64
class Handler(http.server.BaseHTTPRequestHandler):
    def reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        state['calls'].append(('GET', self.path))
        if self.path == '/v1/identity/key':
            assert self.headers['Authorization'] == 'Bearer ' + token.decode()
            return self.reply(200, state['key'])
        assert self.headers['Authorization'] in ('Bearer ' + publish_token.decode(), 'Bearer ' + read_token.decode())
        assert self.path.startswith('/v1/releases/acme/demo/1.2.3/')
        part = self.path.rsplit('/', 1)[1]
        data = parts[part]
        if state['corrupt'] == part: data += b'x'
        self.reply(200 if state['stored'] else 404, data if state['stored'] else b'')
    def do_POST(self):
        if self.path == '/v1/credentials':
            assert self.headers['Authorization'] == 'Bearer ' + token.decode()
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert value['repository'] == 'demo' and value['lifetime_seconds'] == 300
            assert value['scope'] in ('package:read', 'package:publish')
            return self.reply(201, read_token if value['scope'] == 'package:read' else publish_token)
        if self.path == '/v1/credentials/revoke':
            assert self.headers['Authorization'] == 'Bearer ' + token.decode()
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert value['token'] in (publish_token.decode(), read_token.decode())
            return self.reply(200, b'revoked')
        state['calls'].append(('POST', self.path))
        assert self.path == '/v1/releases/acme/demo'
        assert self.headers['Authorization'] == 'Bearer ' + publish_token.decode()
        assert self.headers['Content-Type'] == 'application/octet-stream'
        assert self.rfile.read(int(self.headers['Content-Length'])) == artifact_bytes
        existed = state['stored']
        if state['mode'] == 'reject': return self.reply(409, b'conflict')
        state['stored'] = True
        if state['mode'] == 'drop':
            self.close_connection = True
            return
        self.reply(200 if existed else 201, b'unchanged' if existed else b'published')
    def log_message(self, *args): pass

server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix='luc-upload-') as temporary:
        root = Path(temporary)
        origin = f'http://127.0.0.1:{server.server_port}'
        subprocess.run([fixture, root, origin], check=True, timeout=30)
        for part in ('metadata', 'signature', 'source'): parts[part] = (root / part).read_bytes()
        state['key'] = (root / 'key').read_bytes()
        artifact_bytes = b'LRP1' + len(parts['metadata']).to_bytes(2, 'little') + b'\0\0' + b''.join(parts.values())
        artifact = root / 'artifact'
        artifact.write_bytes(artifact_bytes)
        vault = root / 'session'
        def run(args, data=b'vault-pass\n', success=False):
            result = subprocess.run([binary, *map(str, args)], input=data, capture_output=True, timeout=60, cwd=root)
            assert result.returncode >= 0 and (result.returncode == 0) == success, result.stderr
            for forbidden in (b'Sanitizer', b'runtime error:', b'trap:', b'vault-pass', token):
                assert forbidden not in result.stdout + result.stderr, result.stderr
            return result
        run(['auth-store', origin, 'acme', vault, '--secrets-stdin'], b'vault-pass\n' + token + b'\n', True)
        before = vault.read_bytes()
        upload = ['release-upload', origin, artifact, '--vault', vault, '--password-stdin']
        check = list(upload)
        check[0] = 'release-check'
        run(check)
        assert not state['stored'] and all(method == 'GET' for method, _ in state['calls'])
        state['calls'].clear()
        for invalid in (b'', b'LRP1', b'NOPE' + artifact_bytes[4:], artifact_bytes[:6] + b'\1\0' + artifact_bytes[8:]):
            artifact.write_bytes(invalid)
            run(upload)
            assert not state['calls']
        artifact.write_bytes(artifact_bytes)
        wrong_origin = list(upload)
        wrong_origin[1] = 'http://127.0.0.1:1'
        run(wrong_origin)
        run(upload, b'wrong\n')
        assert not state['calls']
        artifact.write_bytes(artifact_bytes[:-1] + bytes([artifact_bytes[-1] ^ 1]))
        run(upload)
        assert all(method == 'GET' for method, _ in state['calls'])
        artifact.write_bytes(artifact_bytes)
        state['mode'] = 'reject'
        run(upload)
        assert not state['stored']
        state['mode'] = 'drop'
        state['calls'].clear()
        result = run(upload)
        assert b'outcome uncertain' in result.stderr
        assert sum(method == 'POST' for method, _ in state['calls']) == 1
        state['calls'].clear()
        run(check, success=True)
        assert all(method == 'GET' for method, _ in state['calls'])
        state['mode'] = 'normal'
        run(upload, success=True)
        for part in parts:
            state['corrupt'] = part
            run(check)
        state['corrupt'] = ''
        state['stored'] = False
        run(upload, success=True)
        assert artifact.read_bytes() == artifact_bytes and vault.read_bytes() == before
        destination = root / 'checkout'
        download = ['release-download', origin, 'acme/demo', '1.2.3', destination,
                    '--trusted-key', root / 'key', '--vault', vault, '--password-stdin']
        state['calls'].clear()
        for part in parts:
            state['corrupt'] = part
            run(download)
            assert not destination.exists() and not list(root.glob('.luc-checkout-*'))
        state['corrupt'] = ''
        (root / 'key').write_bytes(b'\0' * 1952)
        state['calls'].clear()
        run(download)
        assert not destination.exists()
        assert not any(path.endswith('/source') for _, path in state['calls'])
        (root / 'key').write_bytes(state['key'])
        run(download + ['--locked'])
        assert not destination.exists()
        at, values = 6, []
        for _ in range(6):
            size = int.from_bytes(parts['metadata'][at:at + 2], 'little')
            at += 2
            values.append(parts['metadata'][at:at + size].decode())
            at += size
        (root / 'luce.toml').write_text('[package]\nname = "consumer"\nlanguage = "luce-base"\n')
        lock = (f'schema_version = 2\norigin = "{origin}"\n[[package]]\n'
                'name = "acme/demo"\nversion = "1.2.3"\ncompiler = "luce-base"\n'
                f'digest = "{hashlib.sha256(parts["source"]).hexdigest()}"\n'
                f'commit = "{values[3]}"\ntoolchain = "{values[5]}"\n')
        (root / 'luc.lock').write_text(lock.replace(values[3], '1' * 40))
        run(download + ['--locked'])
        assert not destination.exists()
        (root / 'luc.lock').write_text(lock)
        run(download + ['--locked'], success=True)
        assert destination.is_dir() and list(destination.iterdir()) == []
        (destination / 'keep').write_bytes(b'preserve me')
        run(download)
        assert (destination / 'keep').read_bytes() == b'preserve me'
        assert all(method == 'GET' for method, _ in state['calls'])
        assert not list(root.glob('.luc-checkout-*'))
        assert artifact.read_bytes() == artifact_bytes and vault.read_bytes() == before
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
print('PASS native release upload/reconciliation and trusted-key download, lock binding, tamper/no-clobber failures', flush=True)
