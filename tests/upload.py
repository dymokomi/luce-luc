"""Native upload: exact retries, uncertain outcomes and read-only reconciliation."""
import http.server
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

binary, fixture = [Path(v).resolve() for v in sys.argv[1:]]
state = dict(calls=[], stored=False, mode='normal', corrupt='', key=b'')
parts = {}
token = b'a' * 32
class Handler(http.server.BaseHTTPRequestHandler):
    def reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        state['calls'].append(('GET', self.path))
        assert self.headers['Authorization'] == 'Bearer ' + token.decode()
        if self.path == '/v1/identity/key':
            return self.reply(200, state['key'])
        assert self.path.startswith('/v1/releases/acme/demo/1.2.3/')
        part = self.path.rsplit('/', 1)[1]
        data = parts[part]
        if state['corrupt'] == part: data += b'x'
        self.reply(200 if state['stored'] else 404, data if state['stored'] else b'')
    def do_POST(self):
        state['calls'].append(('POST', self.path))
        assert self.path == '/v1/releases/acme/demo'
        assert self.headers['Authorization'] == 'Bearer ' + token.decode()
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
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
print('PASS native release upload, exact retry, uncertain outcome and read-only reconciliation', flush=True)
