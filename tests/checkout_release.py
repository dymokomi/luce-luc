"""Signed checkout must verify exact bytes and signed commit before publication."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile


def check(binary, fixture):
    with tempfile.TemporaryDirectory(prefix='luc-signed-checkout-') as temporary:
        root = Path(temporary)
        subprocess.run([str(fixture), str(root)], check=True, timeout=30)
        output = root / 'checkout'
        names = ['metadata', 'signature', 'key', 'source']

        def snapshot():
            return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob('*')}

        def run(success=False, selected=names, flags=()):
            before = snapshot()
            result = subprocess.run([str(binary), 'checkout-release',
                                     *(str(root / name) for name in selected), str(output), *flags],
                                    cwd=root, capture_output=True, timeout=40)
            assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
            assert (result.returncode == 0) == success, result.stderr
            if success:
                assert output.is_dir() and not list(output.iterdir())
                assert b'origin ownership and freshness not verified' in result.stdout
                output.rmdir()
            else:
                assert result.stdout == b''
            assert snapshot() == before, 'failed publication or fixture bytes changed'

        run(True)
        for name in names:
            path = root / name
            original = path.read_bytes()
            for bad in (b'', original[:-1], original + b'x', bytes([original[0] ^ 1]) + original[1:]):
                path.write_bytes(bad)
                run()
            path.write_bytes(original)
        # Signature and source digest are valid, but the signed commit is absent.
        run(selected=['wrong-metadata', 'wrong-signature', 'key', 'source'])
        output.mkdir()
        (output / 'keep').write_bytes(b'unchanged')
        run()
        (output / 'keep').unlink()
        output.rmdir()
        run(flags=['--locked'])
        (root / 'luce.toml').write_text('[package]\nname = "consumer"\nlanguage = "luce-base"\n')
        run(flags=['--locked'])
        digest = hashlib.sha256((root / 'source').read_bytes()).hexdigest()
        lock = ('schema_version = 1\norigin = "https://pkg.luciaos.com"\n'
                '[[package]]\nname = "acme/demo"\nversion = "1.2.3"\n'
                f'digest = "{digest}"\ncompiler = "luce-base"\n')
        (root / 'luc.lock').write_text(lock)
        run(True, flags=['--locked'])
        # Independently recover the commit from the native writer's full pack.
        metadata = (root / 'metadata').read_bytes()
        import zlib
        source = (root / 'source').read_bytes()
        at = 12
        commit_id = None
        for _ in range(int.from_bytes(source[8:12], 'big')):
            header = source[at]
            kind = (header >> 4) & 7
            at += 1
            while header & 128:
                header = source[at]
                at += 1
            decoder = zlib.decompressobj()
            payload = decoder.decompress(source[at:-20])
            assert decoder.eof
            at = len(source) - 20 - len(decoder.unused_data)
            if kind == 1:
                commit_id = hashlib.sha1(b'commit ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
        assert commit_id and commit_id.encode() in metadata
        v2 = lock.replace('schema_version = 1', 'schema_version = 2') + f'commit = "{commit_id}"\ntoolchain = "0.20.0"\n'
        (root / 'luc.lock').write_text(v2)
        run(True, flags=['--locked'])
        for bad in (v2.replace(commit_id, '1' * 40), v2.replace('0.20.0', '0.21.0'),
                    v2.replace(f'commit = "{commit_id}"\n', ''), v2.replace('toolchain = "0.20.0"\n', '')):
            (root / 'luc.lock').write_text(bad)
            run(flags=['--locked'])
        for bad in (lock.replace('1.2.3', '1.2.4'), lock.replace(digest, '0' * 64),
                    lock.replace('acme/demo', 'other/demo'), lock.replace('luce-base', 'luce')):
            (root / 'luc.lock').write_text(bad)
            run(flags=['--locked'])
        run(flags=['--unknown'])
    print('PASS signed checkout: ML-DSA, digest, signed commit, lock binding and no-write failures', flush=True)


if __name__ == '__main__':
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
