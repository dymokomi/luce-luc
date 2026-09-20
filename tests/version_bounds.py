"""Hostile numeric versions must produce CLI validation errors, never traps."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

binary, fixture = (Path(arg).resolve() for arg in sys.argv[1:])
with tempfile.TemporaryDirectory(prefix='luc-version-bounds-') as temporary:
    root = Path(temporary)
    subprocess.run([str(fixture), str(root)], check=True, timeout=30)
    names = ['metadata', 'signature', 'key', 'source']
    original = (root / 'metadata').read_bytes()
    fields, at = [], 6
    for _ in range(6):
        size = int.from_bytes(original[at:at + 2], 'little')
        at += 2
        fields.append(original[at:at + size])
        at += size
    digest = original[at:]
    assert len(digest) == 32

    def reject(locked=False):
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        result = subprocess.run([str(binary), 'verify-release', *names, *(['--locked'] if locked else [])],
                                cwd=root, capture_output=True, timeout=30)
        assert result.returncode > 0, (result.stdout, result.stderr)
        assert b'version part overflow' in result.stderr, result.stderr
        for crash in (b'trap:', b'Sanitizer', b'runtime error:'):
            assert crash not in result.stderr, result.stderr
        assert before == {p.name: p.read_bytes() for p in root.iterdir()}

    for component in range(3):
        version = [b'0', b'0', b'0']
        version[component] = b'30000000000000000000'
        changed = list(fields)
        changed[2] = b'.'.join(version)
        encoded = original[:6] + b''.join(len(value).to_bytes(2, 'little') + value for value in changed) + digest
        (root / 'metadata').write_bytes(encoded)
        reject()
    (root / 'metadata').write_bytes(original)
    (root / 'luce.toml').write_text('[package]\nname = "consumer"\nlanguage = "luce-base"\n')
    source_digest = hashlib.sha256((root / 'source').read_bytes()).hexdigest()
    for invalid_field in ('version', 'toolchain'):
        version = '30000000000000000000.0.0' if invalid_field == 'version' else '1.2.3'
        toolchain = '30000000000000000000.0.0' if invalid_field == 'toolchain' else '0.20.0'
        (root / 'luc.lock').write_text(
            'schema_version = 2\norigin = "https://pkg.luciaos.com"\n[[package]]\n'
            f'name = "acme/demo"\nversion = "{version}"\ndigest = "{source_digest}"\n'
            'compiler = "luce-base"\ncommit = "0123456789012345678901234567890123456789"\n'
            f'toolchain = "{toolchain}"\n')
        reject(True)
print('PASS CLI release/lock numeric overflow returns errors without traps or writes', flush=True)
