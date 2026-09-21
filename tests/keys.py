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
             'body': b'enrolled', 'calls': [], 'proofs': [], 'bound': None, 'read_status': None}
    token = b'd' * 32
    class Handler(http.server.BaseHTTPRequestHandler):
        def reply(self, code, body):
            self.send_response(code)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            state['calls'].append(self.path)
            assert self.headers['Authorization'] == 'Bearer ' + token.decode()
            if self.path == '/v1/identity':
                self.reply(200, state['identity'])
            else:
                assert self.path == '/v1/identity/key'
                self.reply(state['read_status'] or (404 if state['bound'] is None else 200), state['bound'] or b'')
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
                if state['status'] == 0 or (state['status'] == 201 and state['body'] == b'enrolled'):
                    state['bound'] = body[:1952]
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
            key, public, session = root / 'key.vault', root / 'key.pub', root / 'session.vault'
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
            run(create, b'key-pass\n', True)
            original = key.read_bytes()
            assert original[:4] == b'LAV1' and key.stat().st_mode & 0o777 == 0o600
            run(create, b'key-pass\n')
            assert key.read_bytes() == original and not state['calls']
            export = ['key-export', origin, 'alice', public, '--key-vault', key, '--password-stdin']
            for invalid in (b'', b'\n', b'key-pass', b'key-pass\nextra\n', b'wrong\n'):
                run(export, invalid)
                assert not public.exists() and not state['calls']
            for index, value in ((1, 'http://127.0.0.1:1'), (2, 'bob'), (3, ''), (5, '')):
                bad = list(export)
                bad[index] = value
                run(bad, b'key-pass\n')
                assert not public.exists() and not state['calls']
            link = root / 'key-link.pub'
            link.symlink_to(key)
            bad = list(export)
            bad[3] = link
            run(bad, b'key-pass\n')
            assert link.is_symlink() and key.read_bytes() == original and not state['calls']
            link.unlink()
            run(export, b'key-pass\n', True)
            public_bytes = public.read_bytes()
            assert len(public_bytes) == 1952 and public.stat().st_mode & 0o777 == 0o600
            run(export, b'')
            assert public.read_bytes() == public_bytes and not state['calls']
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
            check_key = list(enroll)
            check_key[0] = 'key-check'
            before_calls = len(state['calls'])
            run(check_key, b'session-pass\nkey-pass\n')
            assert state['calls'][before_calls:] == ['/v1/identity', '/v1/identity/key']
            run(enroll, b'session-pass\nkey-pass\n', True)
            assert state['bound'] == public_bytes
            before_calls = len(state['calls'])
            run(check_key, b'session-pass\nkey-pass\n', True)
            run(enroll, b'session-pass\nkey-pass\n', True)
            assert state['calls'][before_calls:] == ['/v1/identity', '/v1/identity/key'] * 2
            assert len(state['proofs']) == 1
            for bound, status in ((b'x' * 1952, None), (b'x' * 1951, None), (b'x' * 1953, None), (None, 503), (None, 401)):
                state.update(bound=bound, read_status=status)
                run(enroll, b'session-pass\nkey-pass\n')
                assert len(state['proofs']) == 1
            state['read_status'] = None
            for status, body in ((400, b'bad'), (409, b'conflict'), (503, b'unavailable'), (201, b'wrong'), (0, b'')):
                state.update(status=status, body=body, bound=None)
                result = run(enroll, b'session-pass\nkey-pass\n')
                assert b'retain signing-key vault' in result.stderr
                assert key.read_bytes() == original and session.read_bytes() == session_bytes
            # Last request was committed but its response was dropped: explicit read-only recovery.
            before_calls = len(state['calls'])
            run(check_key, b'session-pass\nkey-pass\n', True)
            assert state['calls'][before_calls:] == ['/v1/identity', '/v1/identity/key']
            assert len(state['proofs']) == 6
            assert len({proof[:1952] for proof in state['proofs']}) == 1
            assert len({proof[1952:] for proof in state['proofs']}) == 6
            assert sorted(p.name for p in root.iterdir()) == ['key.pub', 'key.vault', 'session.vault']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('PASS luc encrypted key custody, bound enrollment, no-clobber and uncertain-response retention', flush=True)


if __name__ == '__main__': check(Path(sys.argv[1]).resolve())
