#!/usr/bin/env python3
"""Anonymous registry packages: add, lock, sync, transitive graphs, offline use and tamper refusal.

The registry is a directory of static files, so this test builds one with stock Git and
serves it over loopback HTTP. No account, credential or registry server is involved."""
import functools
import hashlib
import http.server
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

luc = str(Path(sys.argv[1]).resolve())
GIT_ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.test',
               GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.test')


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


def git(repo, *args, input=None):
    return subprocess.run(['git', '-C', str(repo), *args], env=GIT_ENV, input=input, check=True,
                          capture_output=True, timeout=60).stdout


def release(site, work, name, version, module_source, dependencies=''):
    """Publish one history-free release exactly as the registry does on a tag push."""
    repo = work / f'{name}-{version}'
    module = name.replace('-', '_')
    (repo / 'src' / module).mkdir(parents=True)
    definition = (f'#prisma 4.0\ndef package "{name}" {{\n    str owner = "acme"\n    str version = "{version}"\n'
                  f'    str language = "luce-base"\n    def export "{module}" {{\n        str module = "{module}.{module}"\n    }}\n'
                  f'{dependencies}}}\n')
    (repo / 'package.prisma').write_text(definition)
    (repo / 'src' / module / f'{module}.lucb').write_text(module_source)
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', f'{name} {version}')
    commit = git(repo, 'rev-parse', 'HEAD').decode().strip()
    pack = git(repo, 'pack-objects', '--stdout', input=git(repo, 'rev-list', '--objects', 'HEAD'))
    target = site / 'acme' / name
    target.mkdir(parents=True, exist_ok=True)
    (target / f'{version}.pack').write_bytes(pack)
    (target / f'{version}.prisma').write_text(definition)
    with (target / 'versions').open('a') as listing:
        listing.write(f'{version} {hashlib.sha256(pack).hexdigest()} {commit}\n')


def main():
    with tempfile.TemporaryDirectory(prefix='luc-packages-') as temporary:
        root = Path(temporary)
        site, work, cache = root / 'site', root / 'work', root / 'cache'
        for directory in (site, work, cache): directory.mkdir()
        release(site, work, 'greeter', '0.1.0', 'pub func greeting() -> str:\n    return "hello 0.1.0"\n')
        release(site, work, 'greeter', '0.1.1', 'pub func greeting() -> str:\n    return "hello 0.1.1"\n')
        release(site, work, 'greeter', '0.2.0', 'pub func greeting() -> str:\n    return "hello 0.2.0"\n')
        release(site, work, 'polite-kit', '1.0.0', 'import greeter\n\npub func welcome() -> str:\n    return greeter.greeting()\n',
                '    def dependency "greeter" {\n        str owner = "acme"\n        str version = "^0.1.0"\n'
                '        str path = "../author-only-checkout"\n    }\n')
        handler = functools.partial(Quiet, directory=str(site))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        online = dict(os.environ, LUC_REGISTRY=f'http://127.0.0.1:{server.server_port}', LUC_CACHE=str(cache))
        offline = dict(online, LUC_REGISTRY='http://127.0.0.1:1')

        def run(*args, env=online, success=True):
            result = subprocess.run([luc, *args], cwd=app, env=env, capture_output=True, text=True, timeout=300)
            assert (result.returncode == 0) == success, (args, result.stdout, result.stderr)
            return result.stdout + result.stderr

        app = root
        run('new', 'app')
        app = root / 'app'
        assert 'added dependency acme/polite-kit ^1.0.0' in run('add', 'acme/polite-kit')
        (app / 'src' / 'main.lucb').write_text('import polite_kit\n\npub func main(arguments: str[]) -> i32:\n'
                                               '    print(polite_kit.welcome())\n    return 0\n')
        lock = (app / 'luc.lock').read_text()
        # ^0.1.0 takes the newest 0.1.x and never 0.2.0; the author's path override is ignored.
        assert 'def package "greeter"' in lock and 'str version = "0.1.1"' in lock and '0.2.0' not in lock
        assert hashlib.sha256((site / 'acme/greeter/0.1.1.pack').read_bytes()).hexdigest() in lock
        assert run('run').strip().endswith('hello 0.1.1')
        assert 'no such package' in run('add', 'acme/missing', success=False)

        # A fresh checkout rebuilds from the lock and the cache alone.
        for leftover in ('.luc', 'build'): subprocess.run(['rm', '-rf', str(app / leftover)], check=True)
        assert 'synced 2' in run('sync', '--offline', env=offline)
        assert run('run', env=offline).strip().endswith('hello 0.1.1')

        # The lock's SHA-256 is the integrity check: a changed cache or download is refused.
        cached = cache / 'acme/greeter/0.1.1.pack'
        cached.write_bytes(cached.read_bytes() + b'x')
        subprocess.run(['rm', '-rf', str(app / '.luc')], check=True)
        assert 'does not match luc.lock' in run('sync', '--offline', env=offline, success=False)
        assert 'synced 2' in run('sync')
        published = site / 'acme/greeter/0.1.1.pack'
        published.write_bytes(published.read_bytes() + b'x')
        cached.unlink()
        subprocess.run(['rm', '-rf', str(app / '.luc')], check=True)
        assert 'does not match the SHA-256' in run('sync', success=False)
        server.shutdown()
    print('PASS anonymous add/lock/sync, caret selection, transitive graph, offline rebuild and SHA-256 refusal', flush=True)


if __name__ == '__main__':
    main()
