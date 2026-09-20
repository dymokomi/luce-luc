"""Whole-graph verified sync, compiler wiring, offline cache and relocation."""
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
scoped = {'a': b'b' * 64, 'b': b'c' * 64, 'c': b'd' * 64}
state = {'root': None, 'calls': []}
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
            body = catalog(catalogs['/'.join(pieces)])
        else:
            _, name, version, part = pieces
            assert part in ('metadata', 'signature', 'source')
            body = (state['root'] / f'{name}-{version}-{part}').read_bytes()
        self.reply(200, body)

    def log_message(self, *_):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix='luc-graph-sync-') as temporary:
        root = Path(temporary)
        origin = f'http://127.0.0.1:{server.server_port}'
        signed = root / 'signed'
        signed.mkdir()
        subprocess.run([fixture, signed, origin], check=True, timeout=30)
        state['root'] = signed
        pristine = ('[package]\nname = "consumer"\nlanguage = "luce-base"\nentry = "main.lucb"\n\n'
                    '[registry.dependencies]\n"acme/c" = "1.0.0"\n"acme/a" = "^1.0.0"\n')
        source = ('import a_lib\nimport c_lib\n\npub func main(arguments: str[]) -> i32:\n'
                  '    discard(arguments)\n    assert(a_lib.value() + c_lib.value() == 83)\n    return 0\n')

        def project(path, manifest=pristine):
            path.mkdir()
            (path / 'luce.toml').write_text(manifest)
            (path / 'main.lucb').write_text(source)

        def run(args, cwd, data=b'', success=True, cache=None):
            env = dict(os.environ, LUCE_BASE=str(compiler), LUCE_STD=str(standard))
            if cache is not None: env['LUC_PACKAGE_CACHE'] = str(cache)
            result = subprocess.run([binary, *map(str, args)], cwd=cwd, env=env, input=data,
                                    capture_output=True, timeout=180)
            assert (result.returncode == 0) == success, (result.stdout, result.stderr)
            for forbidden in (b'Sanitizer', b'runtime error:', b'trap:', b'vault-pass', token):
                assert forbidden not in result.stdout + result.stderr, (forbidden, result.stdout, result.stderr)
            return result

        online = root / 'online'
        project(online)
        vault = root / 'session.vault'
        run(['auth-store', origin, 'acme', vault, '--secrets-stdin'], online,
            b'vault-pass\n' + token + b'\n')
        lock_command = ['lock', origin, '--trusted-key', signed / 'key', '--vault', vault, '--password-stdin']
        run(lock_command, online, b'vault-pass\n')
        lock = (online / 'luc.lock').read_bytes()
        relocated_cache = root / 'relocated cache'
        state['calls'].clear()
        sync = ['sync', '--trusted-key', signed / 'key', '--vault', vault, '--password-stdin']
        result = run(sync, online, b'vault-pass\n', cache=relocated_cache)
        assert result.stdout == b'synchronized 3 locked packages from registry and verified cache\n'
        expected = []
        for name, version in (('a', '1.0.0'), ('b', '1.5.0'), ('c', '1.0.0')):
            expected.extend(f'/v1/releases/acme/{name}/{version}/{part}' for part in ('metadata', 'signature', 'source'))
        assert state['calls'] == expected, state['calls']
        artifacts = list(relocated_cache.glob('release-*.lrp1'))
        assert len(artifacts) == 3 and all(item.stat().st_mode & 0o777 == 0o600 for item in artifacts)
        generations = list((online / '.luc/packages').glob('graph-*'))
        assert len(generations) == 1
        generation = generations[0]
        assert sorted(item.name for item in generation.iterdir() if item.is_dir()) == ['a_lib', 'b_lib', 'c_lib']
        assert (generation / '.luc-generation').read_text() == generation.name.removeprefix('graph-')
        assert 'b_lib = "../b_lib"' in (generation / 'a_lib/luce.toml').read_text()
        assert 'b_lib = "../b_lib"' in (generation / 'c_lib/luce.toml').read_text()
        root_manifest = (online / 'luce.toml').read_text()
        assert f'a_lib = ".luc/packages/{generation.name}/a_lib"' in root_manifest
        assert f'c_lib = ".luc/packages/{generation.name}/c_lib"' in root_manifest
        assert 'b_lib = ".luc/packages/' not in root_manifest
        run(['build'], online)
        subprocess.run([online / 'build/consumer'], check=True, timeout=10)

        # Re-sync replaces the deterministic generation with freshly verified bytes
        # and leaves the managed manifest byte-identical.
        first_manifest = (online / 'luce.toml').read_bytes()
        run(sync, online, b'vault-pass\n', cache=relocated_cache)
        assert (online / 'luce.toml').read_bytes() == first_manifest
        assert len(list((online / '.luc/packages').glob('graph-*'))) == 1

        # A fresh project can use only the relocated immutable cache; no HTTP occurs.
        offline = root / 'offline'
        project(offline)
        (offline / 'luc.lock').write_bytes(lock)
        before_calls = list(state['calls'])
        offline_command = ['sync', '--trusted-key', signed / 'key', '--offline']
        run(offline_command, offline, cache=relocated_cache)
        assert state['calls'] == before_calls
        run(['build'], offline)
        subprocess.run([offline / 'build/consumer'], check=True, timeout=10)

        # The compiler-local paths remain valid after relocating the whole project.
        moved = root / 'moved project'
        shutil.copytree(offline, moved)
        shutil.rmtree(moved / 'build')
        run(['build'], moved)
        subprocess.run([moved / 'build/consumer'], check=True, timeout=10)

        # Stale root constraints and damaged cache bytes fail before manifest mutation.
        stale = root / 'stale'
        project(stale, pristine.replace('"^1.0.0"', '"2.0.0"'))
        (stale / 'luc.lock').write_bytes(lock)
        unchanged = (stale / 'luce.toml').read_bytes()
        run(offline_command, stale, success=False, cache=relocated_cache)
        assert (stale / 'luce.toml').read_bytes() == unchanged and not (stale / '.luc').exists()

        damaged_cache = root / 'damaged cache'
        shutil.copytree(relocated_cache, damaged_cache)
        damaged = next(damaged_cache.glob('release-*.lrp1'))
        wire = bytearray(damaged.read_bytes())
        wire[-1] ^= 1
        damaged.write_bytes(wire)
        damaged_project = root / 'damaged'
        project(damaged_project)
        (damaged_project / 'luc.lock').write_bytes(lock)
        unchanged = (damaged_project / 'luce.toml').read_bytes()
        run(offline_command, damaged_project, success=False, cache=damaged_cache)
        assert (damaged_project / 'luce.toml').read_bytes() == unchanged
        assert not list((damaged_project / '.luc/packages').iterdir())

        wrong = root / 'wrong.key'
        wrong.write_bytes(b'\0' * 1952)
        wrong_project = root / 'wrong'
        project(wrong_project)
        (wrong_project / 'luc.lock').write_bytes(lock)
        bad = ['sync', '--trusted-key', wrong, '--offline']
        run(bad, wrong_project, success=False, cache=relocated_cache)
        assert (wrong_project / 'luce.toml').read_text() == pristine
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

print('PASS graph sync: exact sources, compiler wiring, online/offline cache and relocation', flush=True)
