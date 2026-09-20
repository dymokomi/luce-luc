"""Disposable vault CLI and origin-bound authenticated discovery oracle."""
import http.server
import os
import pty
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from remote import pkt

def check(binary):
    token = b'a' * 32
    password = b'disposable vault password'
    requests = []
    body = pkt(b'# service=git-upload-pack\n') + b'0000' + pkt(b'0' * 40 + b' capabilities^{}\0ofs-delta') + b'0000'
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.headers.get('Authorization'))
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-credentials-') as temporary:
            root = Path(temporary)
            vault = root / 'credential.vault'
            origin = f'http://127.0.0.1:{server.server_port}'
            env = dict(os.environ, LUCE_REGISTRY_TOKEN='b' * 32)
            def run(args, data, success=False):
                result = subprocess.run([str(binary), *map(str, args)], input=data, cwd=root,
                                        env=env, capture_output=True, timeout=60)
                assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
                assert (result.returncode == 0) == success, result.stderr
                assert password not in result.stdout + result.stderr and token not in result.stdout + result.stderr
                assert not list(root.glob('.luce-*'))
                return result
            store = ['auth-store', origin, 'alice', vault, '--secrets-stdin']
            master, slave = pty.openpty()
            try:
                tty = subprocess.run([str(binary), *map(str, store)], stdin=slave,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=env, cwd=root, timeout=10)
                assert tty.returncode > 0 and b'refusing secret input' in tty.stderr
                assert not vault.exists()
            finally:
                os.close(slave)
                os.close(master)
            for data in (b'', b'\n' + token + b'\n', password + b'\n', password + b'\n' + token,
                         password + b'\n' + token + b'\nextra', b'x' * 1025 + b'\n' + token + b'\n'):
                run(store, data)
                assert not vault.exists()
            run(store, password + b'\n' + token + b'\n', True)
            original = vault.read_bytes()
            assert vault.stat().st_mode & 0o777 == 0o600
            run(store, password + b'\n' + token + b'\n')
            assert vault.read_bytes() == original
            fetch = ['remote-refs', origin + '/git/alice/demo', '--vault', vault, '--password-stdin']
            run(fetch, password + b'\n', True)
            assert requests == ['Bearer ' + token.decode()], requests
            previous = len(requests)
            empty = list(fetch)
            empty[3] = ''
            run(empty, password + b'\n')
            run(['remote-fetch', origin + '/git/alice/demo', '1' * 40, root / 'absent.pack',
                 '--vault', '', '--password-stdin'], password + b'\n')
            assert not (root / 'absent.pack').exists()
            run(fetch, b'wrong\n')
            run(fetch, password + b'\nextra\n')
            other = list(fetch)
            other[1] = 'http://127.0.0.1:1/git/alice/demo'
            rejected = run(other, password + b'\n')
            assert b'origin mismatch' in rejected.stderr
            assert len(requests) == previous
            assert vault.read_bytes() == original
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('PASS luc encrypted credentials, explicit stdin, no-clobber and origin-bound no-network rejection', flush=True)

if __name__ == '__main__': check(Path(sys.argv[1]).resolve())
