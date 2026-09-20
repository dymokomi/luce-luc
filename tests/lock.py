#!/usr/bin/env python3
"""Read-only lock checking through the actual luc executable."""
from pathlib import Path
import subprocess
import sys
import tempfile

binary = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='luc-lock-') as temporary:
    root = Path(temporary)
    manifest = root / 'luce.toml'
    manifest.write_text('[package]\nname = "fixture"\nlanguage = "luce-base"\n')
    nested = root / 'src/nested'
    nested.mkdir(parents=True)
    lock = root / 'luc.lock'

    def check(success, *arguments):
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        result = subprocess.run([str(binary), 'lock', *arguments], cwd=nested,
                                capture_output=True, text=True, timeout=15)
        assert (result.returncode == 0) == success, (arguments, result.stdout, result.stderr)
        after = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        assert before == after, 'lock check changed project files'
        if success:
            assert 'signatures not verified' in result.stdout

    check(False, '--check')  # Missing lock must not create one.
    lock.write_text('schema_version = 1\norigin = "https://pkg.luciaos.com"\n')
    check(True, '--check')
    lock.write_text('schema_version = 3\norigin = "https://pkg.luciaos.com"\n')
    check(True, '--check')
    lock.write_text('schema_version = 1\norigin = "https://pkg.luciaos.com"\n'
                    '[[package]]\nname = "acme/demo"\nversion = "1.2.3"\n'
                    'digest = "' + 'ab' * 32 + '"\ncompiler = "luce-base"\n')
    check(True, '--check')
    for args in ((), ('--unknown',), ('--check', 'extra'), ('--check', '--', 'extra')):
        check(False, *args)
    for text in ('# origin = "spoof"\n',
                 'schema_version = 1\norigin = "a"\norigin = "b"\n',
                 'schema_version = 1\norigin = "a"\n[[package]]\n',
                 '#' * (1048576 + 1)):
        lock.write_text(text)
        check(False, '--check')
print('PASS luc lock --check: nested discovery, strict syntax, bounded input, no writes')
