"""Authenticated transitive graph lock generation over disposable loopback HTTP."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

binary, fixture = [Path(value).resolve() for value in sys.argv[1:]]
token = b'a' * 32
scoped = {'a': b'b' * 64, 'b': b'c' * 64, 'c': b'd' * 64}
state = {'root': None, 'calls': [], 'tamper': False}
catalogs = {
    'acme/a': ['1.1.0', '1.0.0'],
    'acme/b': ['2.0.0', '1.5.0'],
    'acme/c': ['1.0.0'],
}


def catalog(values):
    return b'LPV1' + len(values).to_bytes(2, 'little') + b''.join(
        bytes([len(value)]) + value.encode() for value in values)


class Handler(http.server.BaseHTTPRequestHandler):
    def reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        assert self.headers['Authorization'] == 'Bearer ' + token.decode()
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/v1/credentials':
            assert value['scope'] == 'package:read' and value['repository'] in scoped and value['lifetime_seconds'] == 300
            self.reply(201, scoped[value['repository']])
        else:
            assert self.path == '/v1/credentials/revoke'
            assert value['token'] in {item.decode() for item in scoped.values()}
            self.reply(200, b'revoked')

    def do_GET(self):
        state['calls'].append(self.path)
        pieces = self.path.removeprefix('/v1/releases/').split('/')
        assert self.headers['Authorization'] == 'Bearer ' + scoped[pieces[1]].decode()
        if len(pieces) == 2:
            package = '/'.join(pieces)
            body = catalog(catalogs[package])
        else:
            owner, name, version, part = pieces
            assert part in ('metadata', 'signature')
            stem = f'{name}-{version}-{part}'
            body = (state['root'] / stem).read_bytes()
            if state['tamper'] and name == 'a' and version == '1.1.0' and part == 'metadata':
                body = body[:-1] + bytes([body[-1] ^ 1])
        self.reply(200, body)

    def log_message(self, *_):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix='luc-graph-lock-') as temporary:
        root = Path(temporary)
        origin = f'http://127.0.0.1:{server.server_port}'
        signed = root / 'signed'
        signed.mkdir()
        subprocess.run([fixture, signed, origin], check=True, timeout=30)
        state['root'] = signed
        project = root / 'project'
        project.mkdir()
        manifest = ('[package]\nname = "consumer"\nlanguage = "luce-base"\n\n'
                    '[registry.dependencies]\n"acme/c" = "1.0.0"\n"acme/a" = "^1.0.0"\n')
        (project / 'luce.toml').write_text(manifest)
        vault = root / 'session.vault'

        def run(args, data=b'vault-pass\n', success=True):
            result = subprocess.run([binary, *map(str, args)], cwd=project, input=data,
                                    capture_output=True, timeout=60)
            assert (result.returncode == 0) == success, (result.stdout, result.stderr)
            for forbidden in (b'Sanitizer', b'runtime error:', b'trap:', b'vault-pass', token):
                assert forbidden not in result.stdout + result.stderr, (forbidden, result.stdout, result.stderr)
            return result

        run(['auth-store', origin, 'acme', vault, '--secrets-stdin'],
            b'vault-pass\n' + token + b'\n')
        command = ['lock', origin, '--trusted-key', signed / 'key', '--vault', vault, '--password-stdin']
        result = run(command)
        assert result.stdout == b'locked 3 authenticated packages in luc.lock v3\n'
        wire = (project / 'luc.lock').read_text()
        fingerprint = hashlib.sha256((signed / 'key').read_bytes()).hexdigest()
        assert wire.startswith(f'schema_version = 3\norigin = "{origin}"\n')
        assert wire.count('[[package]]') == 3
        assert wire.count(f'publisher_key_sha256 = "{fingerprint}"') == 3
        assert 'name = "acme/a"\nversion = "1.0.0"' in wire
        assert 'name = "acme/b"\nversion = "1.5.0"' in wire
        assert 'name = "acme/c"\nversion = "1.0.0"' in wire
        assert 'package = "acme/b"\nrequirement = "^1.0.0"\nversion = "1.5.0"' in wire
        assert 'package = "acme/b"\nrequirement = "1.5.0"\nversion = "1.5.0"' in wire
        assert all(not call.endswith('/source') for call in state['calls'])
        assert run(['lock', '--check']).stdout == b'valid luc.lock syntax: 3 packages (signatures not verified)\n'
        first = (project / 'luc.lock').read_bytes()
        run(command)
        assert (project / 'luc.lock').read_bytes() == first

        # Signature or root-constraint failure preserves the previous exact lock.
        state['tamper'] = True
        run(command, success=False)
        state['tamper'] = False
        assert (project / 'luc.lock').read_bytes() == first
        (project / 'luce.toml').write_text(manifest.replace('"^1.0.0"', '"2.0.0"'))
        run(command, success=False)
        assert (project / 'luc.lock').read_bytes() == first
        (project / 'luce.toml').write_text(manifest)

        wrong = root / 'wrong.key'
        wrong.write_bytes(b'\0' * 1952)
        bad_key = list(command)
        bad_key[3] = wrong
        run(bad_key, success=False)
        assert (project / 'luc.lock').read_bytes() == first
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

print('PASS authenticated graph lock: transitive backtracking, canonical v3, tamper/no-clobber', flush=True)
