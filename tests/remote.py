"""Native luc discovery against an independent, bounded loopback HTTP oracle."""
import http.server
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


def pkt(data):
    return f'{len(data) + 4:04x}'.encode() + data


def check(binary):
    token = 'a' * 32  # Matches current native auth session encoding; fixture only.
    prefix = pkt(b'# service=git-upload-pack\n') + b'0000'
    oid = b'1' * 40
    body = prefix + pkt(oid + b' HEAD\0ofs-delta\n') + pkt(oid + b' refs/heads/main\n') + b'0000'
    state = {'body': body, 'status': 200, 'requests': 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state['requests'] += 1
            assert self.path == '/git/alice/demo/info/refs?service=git-upload-pack'
            assert self.headers['Authorization'] == 'Bearer ' + token
            self.send_response(state['status'])
            self.send_header('Content-Length', str(len(state['body'])))
            self.end_headers()
            self.wfile.write(state['body'])

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-remote-') as temporary:
            root = Path(temporary)
            env = dict(os.environ, LUCE_REGISTRY_TOKEN=token)
            url = f'http://127.0.0.1:{server.server_port}/git/alice/demo'

            def run(args, success=False, environment=env):
                result = subprocess.run([str(binary), *args], cwd=root, env=environment,
                                        capture_output=True, timeout=40)
                assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
                assert (result.returncode == 0) == success, result.stderr
                assert token.encode() not in result.stdout + result.stderr
                if not success: assert result.stdout == b'', result.stdout
                assert not list(root.iterdir()), 'command wrote files'
                return result.stdout

            assert run(['remote-refs', url], True) == oid + b'\tHEAD\n' + oid + b'\trefs/heads/main\n'
            for invalid in ('https://example.test/git/alice/demo', 'http://localhost:80/git/alice/demo',
                            'http://127.0.0.1:0/git/alice/demo', 'http://127.0.0.1:65536/git/alice/demo',
                            url + '?token=secret', url + '/extra', url.replace('/alice/', '/../')):
                previous = state['requests']
                run(['remote-refs', invalid])
                assert state['requests'] == previous
            run(['remote-refs'])
            missing = dict(env)
            missing.pop('LUCE_REGISTRY_TOKEN')
            run(['remote-refs', url], environment=missing)
            production = subprocess.run(
                [str(binary), 'remote-refs', 'https://pkg.luciaos.com/git/alice/demo'],
                cwd=root, env=missing, capture_output=True, timeout=40)
            assert production.returncode > 0
            assert b'LUCE_REGISTRY_TOKEN is required' in production.stderr
            assert production.stdout == b'' and not list(root.iterdir())
            run(['remote-refs', url], environment=dict(env, LUCE_REGISTRY_TOKEN='a\r\nb'))
            state['status'] = 401
            run(['remote-refs', url])
            state['status'] = 200
            for bad in (b'', b'0000', body[:-1], body + b'junk',
                        prefix + pkt(oid + b' HEAD\0x\n') + pkt(oid + b' refs/heads/../bad\n') + b'0000',
                        prefix + pkt(oid + b' HEAD\0x\x1b') + b'0000',
                        prefix + pkt(b'0' * 40 + b' refs/heads/main\0x') + b'0000'):
                state['body'] = bad
                run(['remote-refs', url])
            state['body'] = prefix + pkt(b'0' * 40 + b' capabilities^{}\0ofs-delta') + b'0000'
            assert run(['remote-refs', url], True) == b''
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('PASS luc native remote refs, no partial output, auth failures, URL bounds and no writes', flush=True)


if __name__ == '__main__':
    check(Path(sys.argv[1]).resolve())
