#!/usr/bin/env python3
"""Actual CLI signature checks, isolated fixtures, no network or real credentials."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import tempfile
import heap_process

binary, fixture = (Path(arg).resolve() for arg in sys.argv[1:])
leaks = os.environ.get('LUCE_TEST_LEAKS') == '1'
prefix = ['/usr/bin/leaks', '--quiet', '--noContent', '--atExit', '--'] if leaks else []

def invoke(arguments, cwd):
    command = [str(binary), 'verify-release', *arguments]
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=30)
    if leaks:
        # leaks reports its own result, not the child's exit status: check both.
        heap = heap_process.run([*prefix, *command], cwd=cwd, timeout=30)
        assert heap.returncode == 0 and '0 leaks for 0 total leaked bytes' in heap.stdout, (heap.stdout, heap.stderr)
        # Require the instrumented command to reach the same observable result.
        assert heap.stdout.startswith(result.stdout), (result.stdout, heap.stdout)
        assert result.stderr in heap.stderr, (result.stderr, heap.stderr)
    return result
with tempfile.TemporaryDirectory(prefix='luc-release-') as temporary:
    root = Path(temporary)
    subprocess.run([str(fixture), str(root)], check=True, timeout=30)
    names = ['metadata', 'signature', 'key', 'source']

    def check(success, arguments=None):
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        result = invoke(names if arguments is None else arguments, root)
        assert result.returncode >= 0, ('verification crashed', result.stderr)
        assert 'Sanitizer' not in result.stderr and 'runtime error:' not in result.stderr, result.stderr
        assert (result.returncode == 0) == success, (result.stdout, result.stderr)
        assert before == {p.name: p.read_bytes() for p in root.iterdir()}, 'verification wrote files'
        if success:
            assert 'verified acme/demo@1.2.3' in result.stdout
            assert 'origin ownership not verified' in result.stdout

    check(True)  # No project manifest is required.
    for arguments in ([], names[:-1], names + ['extra'], names + ['--', 'extra'], ['missing', *names[1:]]):
        check(False, arguments)
    for name in names:
        path = root / name
        original = path.read_bytes()
        for data in (b'', original[:-1], original + b'X', bytes([original[0] ^ 1]) + original[1:]):
            path.write_bytes(data)
            check(False)
        path.write_bytes(original)
    # Valid framing but modified signed package identity.
    path = root / 'metadata'
    original = path.read_bytes()
    path.write_bytes(original.replace(b'acme/demo', b'acme/evil'))
    check(False)
    path.write_bytes(original)
    check(True)
    # A valid signature is insufficient when a project requested another release.
    def snapshot():
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def locked(success, cwd=root, extra=None):
        before = snapshot()
        arguments = [str(root / name) for name in names] + ['--locked']
        result = invoke([*arguments, *(extra or [])], cwd)
        assert result.returncode >= 0, result.stderr
        assert 'Sanitizer' not in result.stderr and 'runtime error:' not in result.stderr, result.stderr
        assert (result.returncode == 0) == success, (result.stdout, result.stderr)
        assert before == snapshot(), 'locked verification wrote files'
        if success:
            assert 'release matches luc.lock' in result.stdout
            assert 'commit and toolchain are not pinned' in result.stdout
            assert 'origin ownership not verified' in result.stdout

    locked(False)  # No project.
    (root / 'luce.toml').write_text('[package]\nname = "consumer"\nlanguage = "luce-base"\n')
    locked(False)  # Missing lock.
    digest = hashlib.sha256((root / 'source').read_bytes()).hexdigest()
    valid_lock = ('schema_version = 1\norigin = "https://pkg.luciaos.com"\n'
                  '[[package]]\nname = "acme/demo"\nversion = "1.2.3"\n'
                  f'digest = "{digest}"\ncompiler = "luce-base"\n')
    lock = root / 'luc.lock'
    lock.write_text(valid_lock)
    locked(True)
    nested = root / 'nested'
    nested.mkdir()
    locked(True, cwd=nested)
    locked(False, extra=['--locked'])
    for content in ('', valid_lock[:valid_lock.index('[[package]]')],
                    valid_lock.replace('https://pkg.luciaos.com', 'https://other.example'),
                    valid_lock.replace('acme/demo', 'acme/other'),
                    valid_lock.replace('1.2.3', '1.2.4'),
                    valid_lock.replace('1.2.3', '1.3.3'),
                    valid_lock.replace('1.2.3', '2.2.3'),
                    valid_lock.replace(digest, '0' * 64),
                    valid_lock.replace('luce-base', 'luce'),
                    valid_lock + valid_lock[valid_lock.index('[[package]]'):],
                    valid_lock + '#' * 1048576):
        lock.write_text(content)
        locked(False)
    lock.write_text(valid_lock)
    source = root / 'source'
    source.write_bytes(source.read_bytes() + b'tampered')
    locked(False)
print('PASS luc verify-release: signature, digest, tampering, bounds, missing files, no writes')
print('PASS luc --locked: origin/package/version/digest/compiler binding, nested discovery, no writes')
