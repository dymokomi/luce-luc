"""Offline artifact signing, native independent verification, no-clobber failures."""
import os
from pathlib import Path
import pty
import subprocess
import sys
import tempfile

binary, fixture, verifier = [Path(arg).resolve() for arg in sys.argv[1:]]
with tempfile.TemporaryDirectory(prefix='luc-signing-') as temporary:
    root = Path(temporary)
    subprocess.run([str(fixture), str(root)], check=True, timeout=30)
    origin = 'http://127.0.0.1:1'
    original = (root / 'metadata').read_bytes()
    fields, at = [], 6
    for _ in range(6):
        size = int.from_bytes(original[at:at + 2], 'little')
        at += 2
        fields.append(original[at:at + size])
        at += size
    fields[0], fields[1] = origin.encode(), b'alice/demo'
    digest = original[at:]
    def metadata(values):
        return original[:6] + b''.join(len(v).to_bytes(2, 'little') + v for v in values) + digest
    valid = metadata(fields)
    (root / 'metadata').write_bytes(valid)
    key, output = root / 'signer.vault', root / 'upload'
    def run(args, password=b'signer-test-password\n', success=False):
        result = subprocess.run([str(binary), *map(str, args)], input=password, cwd=root,
                                capture_output=True, timeout=60)
        assert result.returncode >= 0, result.stderr
        assert (result.returncode == 0) == success, result.stderr
        for bad in (b'trap:', b'Sanitizer', b'runtime error:', b'signer-test-password'):
            assert bad not in result.stdout + result.stderr, result.stderr
        assert not list(root.glob('.luce-*'))
        return result
    run(['key-create', origin, 'alice', key, '--password-stdin'], success=True)
    key_bytes = key.read_bytes()
    args = ['release-sign', 'metadata', 'source', output, '--key-vault', key, '--password-stdin']
    master, slave = pty.openpty()
    try:
        result = subprocess.run([str(binary), *map(str, args)], stdin=slave, cwd=root,
                                capture_output=True, timeout=10)
        assert result.returncode > 0 and b'refusing secret input' in result.stderr
    finally:
        os.close(slave)
        os.close(master)
    for bad in (b'', b'wrong\n', b'\n', b'x' * 1025 + b'\n', b'signer-test-password\nextra\n'):
        run(args, bad)
        assert not output.exists()
    for index, value in ((0, b'http://127.0.0.1:2'), (1, b'bob/demo'), (1, b'alice/../demo'),
                         (1, b'alice/UPPER'), (3, b'1' * 40), (5, b'30000000000000000000.0.0')):
        changed = list(fields)
        changed[index] = value
        (root / 'metadata').write_bytes(metadata(changed))
        run(args)
        assert not output.exists()
    (root / 'metadata').write_bytes(valid)
    source = (root / 'source').read_bytes()
    (root / 'source').write_bytes(source + b'x')
    run(args)
    assert not output.exists()
    (root / 'source').write_bytes(source)
    run(args, success=True)
    artifact = output.read_bytes()
    assert artifact[:4] == b'LRP1' and artifact[6:8] == b'\0\0'
    size = int.from_bytes(artifact[4:6], 'little')
    assert artifact[8:8 + size] == valid and artifact[3317 + size:] == source
    assert output.stat().st_mode & 0o777 == 0o600
    subprocess.run([str(verifier), str(key), str(output)], check=True, timeout=60)
    run(args)
    assert output.read_bytes() == artifact
    second = list(args)
    second[3] = root / 'second-upload'
    run(second, success=True)
    second_bytes = second[3].read_bytes()
    assert second_bytes[:8 + size] == artifact[:8 + size] and second_bytes[3317 + size:] == source
    assert second_bytes[8 + size:3317 + size] != artifact[8 + size:3317 + size]
    subprocess.run([str(verifier), str(key), str(second[3])], check=True, timeout=60)
    link = root / 'link'
    link.symlink_to(output)
    second[3] = link
    run(second)
    assert link.is_symlink() and output.read_bytes() == artifact and key.read_bytes() == key_bytes
print('PASS luc offline release signing, vault identity, randomized proofs, no-clobber and failure cleanup', flush=True)
