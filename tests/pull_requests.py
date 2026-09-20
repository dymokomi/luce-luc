"""Same-repository pull-request CLI, encrypted session and strict request oracle."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


def check(binary):
    token = b'a' * 32
    password = b'disposable pull request vault password'
    seen = []
    record = {
        'number': 1, 'author': 'alice', 'title': 'Review "native"',
        'body': 'line one\nline two', 'base': 'main', 'head': 'review/topic',
        'base_commit': '1' * 40, 'head_commit': '2' * 40, 'merge_commit': '',
        'state': 'open', 'created_at': 1, 'updated_at': 1, 'closed_by': ''
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def respond(self, status, value):
            payload = json.dumps(value, separators=(',', ':')).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def authorize(self):
            assert self.headers['Authorization'] == 'Bearer ' + token.decode()

        def do_GET(self):
            self.authorize()
            seen.append(('GET', self.path))
            if self.path.endswith('/pull-requests'):
                self.respond(200, [record])
            else:
                assert self.path.endswith('/pull-requests/1')
                self.respond(200, record)

        def do_POST(self):
            self.authorize()
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append(('POST', self.path, value))
            if self.path.endswith('/pull-requests'):
                assert value == {'base': 'main', 'head': 'review/topic',
                                 'title': 'Review "native"', 'body': 'line one\nline two'}
                self.respond(201, record)
            else:
                assert self.path.endswith('/pull-requests/1')
                assert value == {'state': 'closed'}
                self.respond(200, {**record, 'state': 'closed', 'closed_by': 'alice'})

        def log_message(self, *args): pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-pull-requests-') as temporary:
            root = Path(temporary)
            vault = root / 'session.vault'
            origin = f'http://127.0.0.1:{server.server_port}'

            def run(args, success=False):
                result = subprocess.run([str(binary), *map(str, args)], input=password + b'\n',
                                        cwd=root, env=dict(os.environ), capture_output=True, timeout=60)
                assert (result.returncode == 0) == success, (args, result.stderr)
                assert password not in result.stdout + result.stderr and token not in result.stdout + result.stderr
                return result

            stored = subprocess.run([str(binary), 'auth-store', origin, 'alice', str(vault), '--secrets-stdin'],
                                    input=password + b'\n' + token + b'\n', cwd=root,
                                    capture_output=True, timeout=60)
            assert stored.returncode == 0, stored.stderr
            created = run(['pr-create', origin, 'alice/demo', 'main', 'review/topic',
                           'Review "native"', 'line one\nline two', '--vault', vault,
                           '--password-stdin'], True)
            assert json.loads(created.stdout) == record
            listed = run(['pr-list', origin, 'alice/demo', '--vault', vault, '--password-stdin'], True)
            assert json.loads(listed.stdout) == [record]
            shown = run(['pr-show', origin, 'alice/demo', '1', '--vault', vault, '--password-stdin'], True)
            assert json.loads(shown.stdout) == record
            changed = run(['pr-state', origin, 'alice/demo', '1', 'closed', '--vault', vault,
                           '--password-stdin'], True)
            assert json.loads(changed.stdout)['state'] == 'closed'
            before = len(seen)
            for args in (
                ['pr-create', origin, 'alice/demo', 'main', 'main', 'x', '', '--vault', vault, '--password-stdin'],
                ['pr-list', origin, '../demo', '--vault', vault, '--password-stdin'],
                ['pr-show', origin, 'alice/demo', '0', '--vault', vault, '--password-stdin'],
                ['pr-state', origin, 'alice/demo', '1', 'deleted', '--vault', vault, '--password-stdin'],
                ['pr-list', 'https://example.test', 'alice/demo', '--vault', vault, '--password-stdin'],
            ):
                run(args)
            assert len(seen) == before
            assert seen == [
                ('POST', '/v1/repositories/alice/demo/pull-requests', {
                    'base': 'main', 'head': 'review/topic', 'title': 'Review "native"',
                    'body': 'line one\nline two'}),
                ('GET', '/v1/repositories/alice/demo/pull-requests'),
                ('GET', '/v1/repositories/alice/demo/pull-requests/1'),
                ('POST', '/v1/repositories/alice/demo/pull-requests/1', {'state': 'closed'}),
            ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('PASS luc same-repository pull request create/list/show/state and local rejection', flush=True)


if __name__ == '__main__': check(Path(sys.argv[1]).resolve())
