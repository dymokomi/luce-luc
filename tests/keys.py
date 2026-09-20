"""Signing seed custody and fail-closed HTTP enrollment; no real credentials."""
import http.server
import os
from pathlib import Path
import pty
import subprocess
import sys
import tempfile
import threading


def check(binary):
    state = {'identity': b'alice', 'challenge': b'n' * 32, 'status': 201,
             'body': b'enrolled', 'calls': [], 'proofs': []}
    token = b'd' * 32
    class Handler(http.server.BaseHTTPRequestHandler):
        def reply(self, code, body):
            self.send_response(code)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            state['calls'].append(self.path)
            assert self.path == '/v1/identity'
            assert self.headers['Authorization'] == 'Bearer ' + token.decode()
            self.reply(200, state['identity'])
        def do_POST(self):
            state['calls'].append(self.path)
            assert self.headers['Authorization'] == 'Bearer ' + token.decode()
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            if self.path.endswith('/key-challenge'):
                assert body == b''
                self.reply(200, state['challenge'])
            else:
                assert self.path == '/v1/identity/key'
                assert self.headers['Content-Type'] == 'application/octet-stream'
                assert len(body) == 5261
                state['proofs'].append(body)
                if state['status'] == 0:
                    self.close_connection = True
                    return
                self.reply(state['status'], state['body'])
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-keys-') as temporary:
            root = Path(temporary)
            origin = f'http://127.0.0.1:{server.server_port}'
            key, session = root / 'key.vault', root / 'session.vault'
            env = dict(os.environ, LUCE_REGISTRY_TOKEN='e' * 32)
            def run(args, data, success=False):
                result = subprocess.run([str(binary), *map(str, args)], input=data,
                                        cwd=root, env=env, capture_output=True, timeout=60)
                assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
                assert (result.returncode == 0) == success, result.stderr
                for secret in (b'session-pass', b'key-pass', token):
                    assert secret not in result.stdout + result.stderr
                assert not list(root.glob('.luce-*'))
                return result
            create = ['key-create', origin, 'alice', key, '--password-stdin']
            for invalid in (b'', b'\n', b'x' * 1025 + b'\n', b'key-pass', b'key-pass\nextra\n'):
                run(create, invalid)
                assert not key.exists()
            master, slave = pty.openpty()
            try:
                rejected = subprocess.run([str(binary), *map(str, create)], stdin=slave,
                                          capture_output=True, timeout=10)
                assert rejected.returncode > 0 and not key.exists()
            finally:
                os.close(slave)
                os.close(master)
            run(create, b'key-pass\n', True)
            original = key.read_bytes()
            assert original[:4] == b'LAV1' and key.stat().st_mode & 0o777 == 0o600
            run(create, b'key-pass\n')
            assert key.read_bytes() == original and not state['calls']
            run(['auth-store', origin, 'alice', session, '--secrets-stdin'], b'session-pass\n' + token + b'\n', True)
            session_bytes = session.read_bytes()
            enroll = ['key-enroll', origin, 'alice', '--vault', session, '--key-vault', key, '--passwords-stdin']
            for bad in (b'', b'\nkey-pass\n', b'session-pass\n', b'session-pass\n\n',
                        b'session-pass\nkey-pass\nextra\n', b'wrong\nkey-pass\n', b'session-pass\nwrong\n'):
                run(enroll, bad)
                assert not state['calls']
            for index, value in ((1, 'http://127.0.0.1:1'), (2, 'bob'), (4, ''), (6, ''), (6, session)):
                bad = list(enroll)
                bad[index] = value
                run(bad, b'session-pass\nkey-pass\n')
                assert not state['calls']
            # Correct password, but the encrypted seed belongs to another context.
            for key_origin, key_account in ((origin, 'bob'), ('http://127.0.0.1:1', 'alice')):
                other_key = root / 'other-key.vault'
                run(['key-create', key_origin, key_account, other_key, '--password-stdin'], b'key-pass\n', True)
                bad = list(enroll)
                bad[6] = other_key
                rejected = run(bad, b'session-pass\nkey-pass\n')
                assert b'signing key origin/account mismatch' in rejected.stderr
                assert not state['calls']
                other_key.unlink()
            # Successfully decrypted session data is not a signing-key payload.
            bad = list(enroll)
            bad[6] = session
            run(bad, b'session-pass\nsession-pass\n')
            assert not state['calls']
            state['identity'] = b'bob'
            run(enroll, b'session-pass\nkey-pass\n')
            assert state['calls'] == ['/v1/identity']
            state['identity'] = b'alice'
            for nonce in (b'', b'n' * 31, b'n' * 33):
                state['challenge'] = nonce
                run(enroll, b'session-pass\nkey-pass\n')
                assert not state['proofs']
            state['challenge'] = b'n' * 32
            run(enroll, b'session-pass\nkey-pass\n', True)
            for status, body in ((400, b'bad'), (409, b'conflict'), (503, b'unavailable'), (201, b'wrong'), (0, b'')):
                state.update(status=status, body=body)
                result = run(enroll, b'session-pass\nkey-pass\n')
                assert b'retain signing-key vault' in result.stderr
                assert key.read_bytes() == original and session.read_bytes() == session_bytes
            assert len(state['proofs']) == 6
            assert len({proof[:1952] for proof in state['proofs']}) == 1
            assert len({proof[1952:] for proof in state['proofs']}) == 6
            assert sorted(p.name for p in root.iterdir()) == ['key.vault', 'session.vault']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('PASS luc encrypted key custody, bound enrollment, no-clobber and uncertain-response retention', flush=True)


if __name__ == '__main__': check(Path(sys.argv[1]).resolve())
