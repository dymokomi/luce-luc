"""Invitation registration oracle: exact JSON, secret handling and no local writes."""
import http.server
import json
from pathlib import Path
import pty
import os
import subprocess
import sys
import tempfile
import threading

def check(binary):
    code = b'd' * 32
    password = 'quote" slash\\ tab\t café'.encode()
    state = {'status': 201, 'body': b'registered', 'calls': 0}
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            state['calls'] += 1
            assert self.path == '/v1/invites/redeem'
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert value == {'code': code.decode(), 'name': 'alice', 'password': password.decode()}
            self.send_response(state['status'])
            self.send_header('Content-Length', str(len(state['body'])))
            self.end_headers()
            self.wfile.write(state['body'])
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-register-') as temporary:
            root = Path(temporary)
            command = [str(binary), 'register', f'http://127.0.0.1:{server.server_port}', 'alice', '--secrets-stdin']
            def run(data, success=False):
                result = subprocess.run(command, input=data, cwd=root, capture_output=True, timeout=40)
                assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr
                assert (result.returncode == 0) == success, result.stderr
                assert code not in result.stdout + result.stderr and password not in result.stdout + result.stderr
                assert not list(root.iterdir())
                if not success: assert not result.stdout
            for malformed in (b'', code+b'\n\n', b'X'*32+b'\npass\n', code+b'\npassword',
                              code+b'\npass\nextra\n', code+b'\n'+b'p'*1025+b'\n'):
                run(malformed)
                assert state['calls'] == 0
            master, slave = pty.openpty()
            try:
                result = subprocess.run(command, stdin=slave, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                assert result.returncode > 0 and b'refusing secret input' in result.stderr
                assert state['calls'] == 0
            finally:
                os.close(slave)
                os.close(master)
            data = code+b'\n'+password+b'\n'
            for status in (400, 401, 409, 500, 503):
                state['status'] = status
                run(data)
            state.update(status=201, body=b'unexpected')
            run(data)
            state['body'] = b'registered'
            run(data, True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('PASS luc invitation registration, JSON escaping, stdin/TTY rejection and no local writes', flush=True)

if __name__ == '__main__': check(Path(sys.argv[1]).resolve())
