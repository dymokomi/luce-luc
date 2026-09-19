#!/usr/bin/env python3
"""Actual CLI signature checks, isolated fixtures, no network or real credentials."""
from pathlib import Path
import subprocess
import sys
import tempfile

binary, fixture = (Path(arg).resolve() for arg in sys.argv[1:])
with tempfile.TemporaryDirectory(prefix='luc-release-') as temporary:
    root = Path(temporary)
    subprocess.run([str(fixture), str(root)], check=True, timeout=30)
    names = ['metadata', 'signature', 'key', 'source']

    def check(success, arguments=None):
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        result = subprocess.run([str(binary), 'verify-release', *(names if arguments is None else arguments)],
                                cwd=root, capture_output=True, text=True, timeout=30)
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
print('PASS luc verify-release: signature, digest, tampering, bounds, missing files, no writes')
