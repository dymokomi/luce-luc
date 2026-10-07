#!/usr/bin/env python3
"""luc login / repo-create / git-token against a stub registry: one password in, a private
session file out, and every later command reads it without asking. LUC_HOME isolates the
test from the developer's own session."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


def check(binary):
    token = b'c' * 32
    password = 'quote" slash\\ tab\t café'.encode()
    state = {'status': 200, 'calls': [], 'repositories': set()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def respond(self, status, payload):
            self.send_response(status)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            state['calls'].append(self.path)
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path == '/v1/sessions':
                assert body == {'name': 'alice', 'password': password.decode()}, body
                self.respond(state['status'], token if state['status'] == 200 else b'denied')
            elif self.path == '/v1/repositories':
                assert self.headers['Authorization'] == 'Bearer ' + token.decode()
                exists = body['name'] in state['repositories']
                state['repositories'].add(body['name'])
                self.respond(409 if exists else 201, b'conflict' if exists else b'created')
            elif self.path == '/v1/credentials':
                assert self.headers['Authorization'] == 'Bearer ' + token.decode()
                assert body == {'scope': 'git:write', 'repository': 'demo', 'lifetime_seconds': 300}, body
                self.respond(201, b'd' * 64)
            else:
                self.respond(404, b'')

        def log_message(self, *args): pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-session-') as temporary:
            home = Path(temporary) / 'home'
            origin = f'http://127.0.0.1:{server.server_port}'
            env = dict(os.environ, LUC_HOME=str(home), LUC_REGISTRY=origin)

            def run(args, stdin=b'', success=True):
                result = subprocess.run([str(binary), *args], input=stdin, capture_output=True, timeout=60, env=env)
                assert b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
                assert (result.returncode == 0) == success, (args, result.stderr)
                for secret in (token, password): assert secret not in result.stdout + result.stderr
                return result

            assert b'not logged in' in run(['repo-create', 'demo'], success=False).stderr
            state['status'] = 401
            assert b'wrong account or password' in run(['login', 'alice'], password + b'\n', success=False).stderr
            assert not (home / 'session').exists()
            state['status'] = 200
            assert b'Logged in as alice' in run(['login', 'alice'], password + b'\n').stdout
            session = home / 'session'
            assert session.stat().st_mode & 0o777 == 0o600
            assert session.read_bytes().startswith(b'LUC1\n' + origin.encode() + b'\nalice\n')
            state['calls'].clear()
            assert b'Created remote repository' in run(['repo-create', 'demo']).stdout
            run(['repo-create', 'demo'], success=False)             # 409: already exists
            assert state['calls'] == ['/v1/repositories', '/v1/repositories'], 'no password prompt, no login'
            assert run(['git-token', 'demo', 'write']).stdout.strip() == b'd' * 64
            # The saved session belongs to this registry only.
            other = dict(env, LUC_REGISTRY='http://127.0.0.1:9')
            result = subprocess.run([str(binary), 'repo-create', 'demo'], capture_output=True, timeout=60, env=other)
            assert result.returncode != 0
    finally:
        server.shutdown()
    print('PASS luc login saves a private session; repo-create and git-token use it without prompting', flush=True)


if __name__ == '__main__':
    check(Path(sys.argv[1]).resolve())
