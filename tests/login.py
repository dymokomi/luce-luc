"""Independent login, identity verification and failed-publication cleanup oracle."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from remote import pkt

def check(binary):
    token = b'c' * 32
    password = 'quote" slash\\ tab\t café'.encode()
    vault_password = b'local vault password'
    state = {'status': 200, 'identity': b'alice', 'token': token, 'calls': [], 'collision': None}
    body = pkt(b'# service=git-upload-pack\n') + b'0000' + pkt(b'0' * 40 + b' capabilities^{}\0ofs-delta') + b'0000'
    class Handler(http.server.BaseHTTPRequestHandler):
        def respond(self, status, payload):
            self.send_response(status)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def do_POST(self):
            state['calls'].append(self.path)
            if self.path == '/v1/sessions':
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert value == {'name': 'alice', 'password': password.decode()}, value
                if state['collision'] is not None: state['collision'].write_bytes(b'preserve')
                self.respond(state['status'], state['token'])
            else:
                assert self.path == '/v1/sessions/revoke'
                assert self.headers['Authorization'] == 'Bearer ' + token.decode()
                self.respond(200, b'revoked')
        def do_GET(self):
            state['calls'].append(self.path)
            assert self.headers['Authorization'] == 'Bearer ' + token.decode()
            self.respond(200, state['identity'] if self.path == '/v1/identity' else body)
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-login-') as temporary:
            root = Path(temporary)
            origin = f'http://127.0.0.1:{server.server_port}'
            data = password + b'\n' + vault_password + b'\n'
            def run(name, success=False, incoming=data):
                result = subprocess.run([str(binary), 'login', origin, 'alice', str(root/name), '--passwords-stdin'],
                                        input=incoming, capture_output=True, timeout=60)
                assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
                assert (result.returncode == 0) == success, result.stderr
                for secret in (token, password, vault_password): assert secret not in result.stdout + result.stderr
                assert not list(root.glob('.luce-*'))
            for malformed in (b'', b'\nsecond\n', b'one\n\n', b'one\ntwo\nthree\n', b'x'*1025+b'\nvault\n'):
                run('malformed', incoming=malformed)
                assert not state['calls'] and not (root/'malformed').exists()
            state['status'] = 401
            run('denied')
            assert state['calls'] == ['/v1/sessions'] and not (root/'denied').exists()
            state.update(status=200, calls=[], token=b'bad')
            run('bad-token')
            assert state['calls'] == ['/v1/sessions'] and not (root/'bad-token').exists()
            state.update(token=token, identity=b'bob', calls=[])
            run('wrong-principal')
            assert state['calls'] == ['/v1/sessions', '/v1/identity', '/v1/sessions/revoke']
            assert not (root/'wrong-principal').exists()
            state.update(identity=b'alice', calls=[], collision=root/'collision')
            run('collision')
            assert state['calls'][-1] == '/v1/sessions/revoke'
            assert (root/'collision').read_bytes() == b'preserve'
            state.update(collision=None, calls=[])
            run('credential', True)
            assert state['calls'] == ['/v1/sessions', '/v1/identity']
            wire = (root/'credential').read_bytes()
            run('credential')
            assert state['calls'] == ['/v1/sessions', '/v1/identity']
            assert (root/'credential').read_bytes() == wire
            result = subprocess.run([str(binary), 'remote-refs', origin+'/git/alice/demo', '--vault',
                                     str(root/'credential'), '--password-stdin'], input=vault_password+b'\n',
                                    capture_output=True, timeout=60, env=dict(os.environ, LUCE_REGISTRY_TOKEN='wrong'))
            assert result.returncode == 0, result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('PASS luc login JSON, identity binding, encrypted persistence, no-clobber and session cleanup', flush=True)

if __name__ == '__main__': check(Path(sys.argv[1]).resolve())
