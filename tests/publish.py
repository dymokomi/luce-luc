"""One-command native publish against an independent bounded HTTP oracle."""
import base64
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from fetch import identity, pack, pkt


def check(binary):
    manifest = b'''[package]
name = "demo_lib"
language = "luce-base"

[registry.dependencies]
"alice/core" = "^1.0.0"
"alice/render-kit" = "2.1.0"
'''
    source_file = b'pub let published = 1\n'
    manifest_id = identity(b'blob', manifest)
    source_id = identity(b'blob', source_file)
    tree_payload = (b'100644 luce.toml\0' + bytes.fromhex(manifest_id.decode()) +
                    b'100644 main.lucb\0' + bytes.fromhex(source_id.decode()))
    tree_id = identity(b'tree', tree_payload)
    commit_payload = (b'tree ' + tree_id +
                      b'\nauthor Publisher <publisher@example.test> 1 +0000\n'
                      b'committer Publisher <publisher@example.test> 1 +0000\n\nrelease\n')
    commit_id = identity(b'commit', commit_payload)
    source_pack = pack([('commit', commit_payload), ('tree', tree_payload),
                        ('blob', manifest), ('blob', source_file)])
    advertisement = (pkt(b'# service=git-upload-pack\n') + b'0000' +
                     pkt(commit_id + b' refs/heads/main\0ofs-delta\n') + b'0000')
    session_token = b'a' * 32
    git_token = b'b' * 64
    publish_token = b'c' * 64
    state = {'bound': None, 'artifact': None, 'calls': []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def reply(self, status, body):
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def session(self):
            assert self.headers['Authorization'] == 'Bearer ' + session_token.decode()

        def do_GET(self):
            state['calls'].append(('GET', self.path))
            if self.path == '/v1/identity':
                self.session()
                return self.reply(200, b'alice')
            if self.path == '/v1/identity/key':
                self.session()
                if state['bound'] is None:
                    return self.reply(404, b'')
                return self.reply(200, state['bound'])
            if self.path == '/git/alice/demo/info/refs?service=git-upload-pack':
                expected = 'Basic ' + base64.b64encode(b'alice:' + git_token).decode()
                assert self.headers['Authorization'] == expected
                return self.reply(200, advertisement)
            assert self.path.startswith('/v1/releases/alice/demo/1.2.3/')
            assert self.headers['Authorization'] == 'Bearer ' + publish_token.decode()
            artifact = state['artifact']
            assert artifact is not None
            metadata_size = int.from_bytes(artifact[4:6], 'little')
            part = self.path.rsplit('/', 1)[1]
            values = {
                'metadata': artifact[8:8 + metadata_size],
                'signature': artifact[8 + metadata_size:3317 + metadata_size],
                'source': artifact[3317 + metadata_size:],
            }
            self.reply(200, values[part])

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            state['calls'].append(('POST', self.path))
            if self.path == '/v1/identity/key-challenge':
                self.session()
                assert body == b''
                return self.reply(200, b'n' * 32)
            if self.path == '/v1/identity/key':
                self.session()
                assert self.headers['Content-Type'] == 'application/octet-stream'
                assert len(body) == 5261
                state['bound'] = body[:1952]
                return self.reply(201, b'enrolled')
            if self.path == '/v1/credentials':
                self.session()
                value = json.loads(body)
                assert value['repository'] == 'demo' and value['lifetime_seconds'] == 300
                assert value['scope'] in ('git:read', 'package:publish')
                return self.reply(201, git_token if value['scope'] == 'git:read' else publish_token)
            if self.path == '/v1/credentials/revoke':
                self.session()
                value = json.loads(body)
                assert value['token'] in (git_token.decode(), publish_token.decode())
                return self.reply(200, b'revoked')
            if self.path == '/git/alice/demo/git-upload-pack':
                expected = 'Basic ' + base64.b64encode(b'alice:' + git_token).decode()
                assert self.headers['Authorization'] == expected
                assert self.headers['Content-Type'] == 'application/x-git-upload-pack-request'
                assert body == pkt(b'want ' + commit_id + b'\n') + b'00000009done\n'
                return self.reply(200, b'0008NAK\n' + source_pack)
            assert self.path == '/v1/releases/alice/demo'
            assert self.headers['Authorization'] == 'Bearer ' + publish_token.decode()
            assert self.headers['Content-Type'] == 'application/octet-stream'
            existed = state['artifact'] is not None
            if existed:
                assert body == state['artifact']
            else:
                state['artifact'] = body
            self.reply(200 if existed else 201, b'unchanged' if existed else b'published')

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-publish-') as temporary:
            root = Path(temporary)
            origin = f'http://127.0.0.1:{server.server_port}'
            session, key, artifact = root / 'session.vault', root / 'key.vault', root / 'demo.lrp1'

            def run(args, data, success=False):
                result = subprocess.run([str(binary), *map(str, args)], input=data,
                                        cwd=root, capture_output=True, timeout=120)
                assert result.returncode >= 0 and b'Sanitizer' not in result.stderr
                assert b'runtime error:' not in result.stderr, result.stderr
                assert (result.returncode == 0) == success, result.stderr
                for secret in (b'session-pass', b'key-pass', session_token, git_token, publish_token):
                    assert secret not in result.stdout + result.stderr
                assert not list(root.glob('.luce-*'))
                return result

            run(['auth-store', origin, 'alice', session, '--secrets-stdin'],
                b'session-pass\n' + session_token + b'\n', True)
            run(['key-create', origin, 'alice', key, '--password-stdin'], b'key-pass\n', True)
            run(['key-enroll', origin, 'alice', '--vault', session, '--key-vault', key,
                 '--passwords-stdin'], b'session-pass\nkey-pass\n', True)
            state['calls'].clear()
            command = ['publish', origin, 'alice/demo', '1.2.3', commit_id.decode(), '0.20.0',
                       artifact, '--vault', session, '--key-vault', key, '--passwords-stdin']
            result = run(command, b'session-pass\nkey-pass\n', True)
            assert b'Confirmed exact signed release bytes' in result.stdout
            saved = artifact.read_bytes()
            assert saved == state['artifact'] and artifact.stat().st_mode & 0o777 == 0o600
            metadata_size = int.from_bytes(saved[4:6], 'little')
            metadata = saved[8:8 + metadata_size]
            assert saved[:4] == b'LRP1' and metadata[:6] == b'LRS2\2\0'
            fields, at = [], 6
            for _ in range(7):
                size = int.from_bytes(metadata[at:at + 2], 'little')
                at += 2
                fields.append(metadata[at:at + size])
                at += size
            assert fields == [origin.encode(), b'alice/demo', b'1.2.3', commit_id,
                              b'luce-base', b'0.20.0', b'demo_lib']
            assert int.from_bytes(metadata[at + 32:at + 34], 'little') == 2
            assert saved[3317 + metadata_size:] == source_pack
            before_calls = list(state['calls'])
            rejected = run(command, b'session-pass\nkey-pass\n')
            assert b'artifact destination already exists' in rejected.stderr
            assert state['calls'] == before_calls and artifact.read_bytes() == saved
            run(['release-check', origin, artifact, '--vault', session, '--password-stdin'],
                b'session-pass\n', True)
            run(['release-upload', origin, artifact, '--vault', session, '--password-stdin'],
                b'session-pass\n', True)
            assert artifact.read_bytes() == saved and state['artifact'] == saved
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    print('PASS luc one-command remote-commit LRS2 publication and immutable reconciliation', flush=True)


if __name__ == '__main__':
    check(Path(sys.argv[1]).resolve())
