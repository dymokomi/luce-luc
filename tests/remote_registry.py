"""Run luc against the sibling registry's disposable full integration fixture.

Usage: remote_registry.py LUC REGISTRY ACCOUNT_FIXTURE NATIVE_TRANSFER
Uses already-built binaries; no production credentials or deployment.
"""
import os
from pathlib import Path
import runpy
import subprocess
import sys

luc, registry, fixture, client = [Path(arg).resolve() for arg in sys.argv[1:]]
tests = Path(__file__).resolve().parents[2] / 'luce-pkg-server/tests'
sys.path.insert(0, str(tests))
import git_http

original = git_http.check


def check(port, headers, git_token, git_read_token, root, request):
    token = headers['Authorization'].removeprefix('Bearer ')
    env = dict(os.environ, LUCE_REGISTRY_TOKEN=token)
    url = f'http://127.0.0.1:{port}/git/testuser/git-wire'
    output = root / 'luc-source.pack'
    vault = root / 'luc-credential.vault'
    password = b'disposable integration vault password'
    stored = subprocess.run([str(luc), 'login', f'http://127.0.0.1:{port}',
                             'testuser', str(vault), '--passwords-stdin'],
                            input=b'fixture-pass\n' + password + b'\n',
                            cwd=root, env=env, capture_output=True, timeout=60)
    assert stored.returncode == 0, stored.stderr
    assert token.encode() not in stored.stdout + stored.stderr
    assert vault.stat().st_mode & 0o777 == 0o600
    env.pop('LUCE_REGISTRY_TOKEN')
    def create_repository(name):
        created = subprocess.run([str(luc), 'repo-create', f'http://127.0.0.1:{port}', name,
                                  '--vault', str(vault), '--password-stdin'], input=password + b'\n',
                                 cwd=root, env=env, capture_output=True, timeout=60)
        assert created.returncode == 0, created.stderr
        assert token.encode() not in created.stdout + created.stderr
        print('PASS luc vault-authenticated native repository creation', flush=True)
    latest = original(port, headers, git_token, git_read_token, root, request,
                      create_repository=create_repository)
    result = subprocess.run([str(luc), 'remote-refs', url, '--vault', str(vault), '--password-stdin'],
                            input=password + b'\n', cwd=root, env=env, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert latest + b'\tHEAD\n' in result.stdout
    assert latest + b'\trefs/heads/main\n' in result.stdout
    assert b'\trefs/tags/nested-tag^{}\n' in result.stdout
    assert token.encode() not in result.stdout + result.stderr
    result = subprocess.run([str(luc), 'remote-fetch', url, latest.decode(), str(output),
                             '--vault', str(vault), '--password-stdin'], input=password + b'\n',
                            cwd=root, env=env, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    repo = root / 'git-clone'
    subprocess.run(['git', '-C', str(repo), 'index-pack', '--stdin', '--strict'],
                   input=output.read_bytes(), check=True, capture_output=True, timeout=30)
    assert token.encode() not in result.stdout + result.stderr
    print('PASS luc encrypted-vault native remote fetch, independently checked by stock Git', flush=True)
    checkout = root / 'luc-checkout'
    result = subprocess.run([str(luc), 'checkout-pack', str(output), latest.decode(), str(checkout)],
                            cwd=root, env=env, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    for name in ('main.lucb', 'extra.lucb', 'large.txt'):
        assert (checkout / name).read_bytes() == (repo / name).read_bytes()
    assert not (checkout / '.git').exists()
    print('PASS native registry fetch-to-checkout bytes match stock Git working tree', flush=True)
    print('PASS luc remote-refs against actual native authenticated registry', flush=True)
    return latest


git_http.check = check
sys.argv = [str(tests / 'check_accounts.py'), str(registry), str(fixture), str(client), str(luc)]
runpy.run_path(str(tests / 'check_accounts.py'), run_name='__main__')
