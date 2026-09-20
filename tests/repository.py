"""Vault-authenticated repository creation against an independent HTTP oracle."""
import http.server
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

def check(binary):
    token = b'e' * 32
    password = b'disposable repository vault'
    state = {'calls': 0, 'status': 201, 'body': b'created'}
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            state['calls'] += 1
            assert self.path == '/v1/repositories'
            assert self.headers['Authorization'] == 'Bearer ' + token.decode()
            assert json.loads(self.rfile.read(int(self.headers['Content-Length']))) == {'name': 'example-package'}
            self.send_response(state['status'])
            self.send_header('Content-Length', str(len(state['body'])))
            self.end_headers()
            self.wfile.write(state['body'])
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-repository-') as temporary:
            root = Path(temporary)
            vault = root/'credential'
            origin = f'http://127.0.0.1:{server.server_port}'
            created = subprocess.run([str(binary), 'auth-store', origin, 'alice', str(vault), '--secrets-stdin'],
                                     input=password+b'\n'+token+b'\n', capture_output=True, timeout=60)
            assert created.returncode == 0, created.stderr
            original = vault.read_bytes()
            def run(name='example-package', success=False, supplied=password, selected_origin=origin, selected_vault=vault):
                result = subprocess.run([str(binary), 'repo-create', selected_origin, name, '--vault',
                                         str(selected_vault), '--password-stdin'], input=supplied+b'\n',
                                        cwd=root, capture_output=True, timeout=60)
                assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr
                assert (result.returncode == 0) == success, result.stderr
                assert token not in result.stdout+result.stderr and password not in result.stdout+result.stderr
                assert vault.read_bytes() == original and set(root.iterdir()) == {vault}
            for name in ('', '../escape', '-bad', '_bad', 'Upper', 'a/b', 'a?b', 'a'*65): run(name)
            run(supplied=b'wrong')
            run(selected_origin='http://127.0.0.1:1')
            run(selected_vault='')
            assert state['calls'] == 0
            for status in (400, 401, 403, 409, 503):
                state['status'] = status
                run()
            state.update(status=201, body=b'unexpected')
            run()
            state['body'] = b'created'
            run(success=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('PASS luc repository creation, vault authorization, origin/name validation and no local writes', flush=True)

if __name__ == '__main__': check(Path(sys.argv[1]).resolve())
