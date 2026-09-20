"""Verified online/offline package install, cache relocation and Base build/run."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

binary, fixture, compiler = [Path(value).resolve() for value in sys.argv[1:]]
standard = Path(__file__).resolve().parents[2] / 'luce-base/src/std'
token = b'a' * 32
scoped = b'b' * 64
state = {'calls': []}
parts = {}

class Handler(http.server.BaseHTTPRequestHandler):
    def reply(self, status, body):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        state['calls'].append(self.path)
        assert self.headers['Authorization'] == 'Bearer ' + scoped.decode()
        prefix = '/v1/releases/acme/demo/1.2.3/'
        assert self.path.startswith(prefix), self.path
        part = self.path[len(prefix):]
        assert part in parts
        self.reply(200, parts[part])
    def do_POST(self):
        assert self.headers['Authorization'] == 'Bearer ' + token.decode()
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/v1/credentials':
            assert value == {'scope': 'package:read', 'repository': 'demo', 'lifetime_seconds': 300}
            self.reply(201, scoped)
        else:
            assert self.path == '/v1/credentials/revoke' and value == {'token': scoped.decode()}
            self.reply(200, b'revoked')
    def log_message(self, *args): pass

def project(path):
    path.mkdir()
    manifest = ('[package]\nname = "consumer"\nlanguage = "luce-base"\n'
                'entry = "main.lucb"\n')
    (path / 'luce.toml').write_text(manifest)
    (path / 'main.lucb').write_text('from demo_dep import answer\n\npub func main(arguments: str[]) -> i32:\n    discard(arguments)\n    assert(answer() == 42)\n    return 0\n')
    return manifest.encode()

server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix='luc-install-') as temporary:
        root = Path(temporary)
        origin = f'http://127.0.0.1:{server.server_port}'
        fixture_root = root / 'fixture'
        fixture_root.mkdir()
        subprocess.run([fixture, fixture_root, origin, 'luce-base'], check=True, timeout=30)
        for part in ('metadata', 'signature', 'source'): parts[part] = (fixture_root / part).read_bytes()
        trusted = fixture_root / 'key'
        vault = root / 'session.vault'
        def run(args, cwd, data=b'', success=False, extra_env=None):
            env = dict(os.environ, LUCE_BASE=str(compiler), LUCE_STD=str(standard))
            if extra_env: env.update(extra_env)
            result = subprocess.run([binary, *map(str, args)], cwd=cwd, env=env, input=data,
                                    capture_output=True, timeout=120)
            assert result.returncode >= 0 and (result.returncode == 0) == success, result.stderr
            for forbidden in (b'Sanitizer', b'runtime error:', b'trap:', b'vault-pass', token):
                assert forbidden not in result.stdout + result.stderr, result.stderr
            return result
        run(['auth-store', origin, 'acme', vault, '--secrets-stdin'], root,
            b'vault-pass\n' + token + b'\n', True)
        original_vault = vault.read_bytes()
        cache = root / 'relocated cache'
        first = root / 'first project'
        original_manifest = project(first)
        online = ['install', origin, 'acme/demo', '1.2.3', '--trusted-key', trusted,
                  '--vault', vault, '--password-stdin']
        env = {'LUC_PACKAGE_CACHE': str(cache)}
        run(online, first, b'vault-pass\n', True, env)
        assert state['calls'] == [f'/v1/releases/acme/demo/1.2.3/{p}' for p in ('metadata', 'signature', 'source')]
        artifacts = list(cache.glob('release-*.lrp1'))
        assert len(artifacts) == 1 and artifacts[0].stat().st_mode & 0o777 == 0o600
        artifact = artifacts[0].read_bytes()
        size = int.from_bytes(artifact[4:6], 'little')
        assert artifact[:4] == b'LRP1' and artifact[6:8] == b'\0\0'
        assert artifact[8:8 + size] == parts['metadata']
        assert artifact[8 + size:3317 + size] == parts['signature']
        assert artifact[3317 + size:] == parts['source']
        installed = list((first / '.luc/packages').glob('release-*'))
        assert len(installed) == 1 and (installed[0] / 'luce.toml').is_file()
        manifest_after = (first / 'luce.toml').read_text()
        assert 'demo_dep = ".luc/packages/release-' in manifest_after
        run(['build'], first, success=True)
        subprocess.run([first / 'build/consumer'], check=True, timeout=10)

        # A relocated shared cache is sufficient for a new project with no HTTP.
        second = root / 'offline project'
        project(second)
        before_calls = list(state['calls'])
        offline = ['install', origin, 'acme/demo', '1.2.3', '--trusted-key', trusted, '--offline']
        run(offline, second, success=True, extra_env=env)
        assert state['calls'] == before_calls
        run(['build'], second, success=True)
        subprocess.run([second / 'build/consumer'], check=True, timeout=10)
        installed_second = next((second / '.luc/packages').glob('release-*'))
        marker = installed_second / 'demo.lucb'
        original_source = marker.read_bytes()
        marker.write_bytes(b'user modification')
        run(offline, second, extra_env=env)
        assert marker.read_bytes() == b'user modification'
        marker.write_bytes(original_source)

        # Lock v2 mismatch rejects before checkout; the exact lock succeeds offline.
        metadata, at, fields = parts['metadata'], 6, []
        for _ in range(6):
            length = int.from_bytes(metadata[at:at + 2], 'little')
            at += 2
            fields.append(metadata[at:at + length].decode())
            at += length
        third = root / 'locked project'
        base_manifest = project(third)
        lock = (f'schema_version = 2\norigin = "{origin}"\n[[package]]\nname = "acme/demo"\n'
                'version = "1.2.3"\ncompiler = "luce-base"\n'
                f'digest = "{hashlib.sha256(parts["source"]).hexdigest()}"\n'
                f'commit = "{fields[3]}"\ntoolchain = "{fields[5]}"\n')
        (third / 'luc.lock').write_text(lock.replace(fields[3], '1' * 40))
        run(offline + ['--locked'], third, extra_env=env)
        assert (third / 'luce.toml').read_bytes() == base_manifest
        assert not list((third / '.luc/packages').iterdir())
        (third / 'luc.lock').write_text(lock)
        run(offline + ['--locked'], third, success=True, extra_env=env)

        # Corrupt files and final-entry symlinks are rejected without a checkout.
        for kind in ('corrupt', 'symlink'):
            bad_cache = root / f'{kind} cache'
            bad_cache.mkdir()
            bad = bad_cache / artifacts[0].name
            if kind == 'corrupt':
                damaged = bytearray(artifact)
                damaged[-1] ^= 1
                bad.write_bytes(damaged)
            else:
                bad.symlink_to(artifacts[0])
            target = root / f'{kind} project'
            unchanged = project(target)
            run(offline, target, extra_env={'LUC_PACKAGE_CACHE': str(bad_cache)})
            assert (target / 'luce.toml').read_bytes() == unchanged
            assert not list((target / '.luc/packages').iterdir())

        # Wrong trust stops before the source request and leaves no installed tree.
        wrong = root / 'wrong.key'
        wrong.write_bytes(b'\0' * 1952)
        target = root / 'wrong key project'
        unchanged = project(target)
        state['calls'].clear()
        bad_online = list(online)
        bad_online[5] = wrong
        run(bad_online, target, b'vault-pass\n', extra_env={'LUC_PACKAGE_CACHE': str(root / 'wrong cache')})
        assert state['calls'] == [f'/v1/releases/acme/demo/1.2.3/{p}' for p in ('metadata', 'signature')], state['calls']
        assert (target / 'luce.toml').read_bytes() == unchanged
        assert not list((target / '.luc/packages').iterdir())

        # Two online projects can race to publish the same immutable cache entry.
        race_cache = root / 'race cache'
        race_projects = [root / 'race one', root / 'race two']
        for item in race_projects: project(item)
        race_env = dict(os.environ, LUCE_BASE=str(compiler), LUCE_STD=str(standard), LUC_PACKAGE_CACHE=str(race_cache))
        processes = [subprocess.Popen([binary, *map(str, online)], cwd=item, env=race_env,
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for item in race_projects]
        for process in processes:
            stdout, stderr = process.communicate(b'vault-pass\n', timeout=120)
            assert process.returncode == 0, (stdout, stderr)
        assert len(list(race_cache.glob('release-*.lrp1'))) == 1
        assert all(len(list((item / '.luc/packages').glob('release-*'))) == 1 for item in race_projects)
        assert vault.read_bytes() == original_vault
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
print('PASS verified package install: online/offline, relocated cache, lock v2, build/run, tamper and concurrent publication', flush=True)
