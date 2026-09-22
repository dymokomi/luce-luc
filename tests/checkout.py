"""Pack checkout oracle: byte/mode fidelity, hostile paths and no-clobber rollback."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from fetch import identity, pack


def fixture(entries):
    objects = []
    tree = b''
    for mode, name, payload in entries:
        kind = 'tree' if mode == b'40000' else 'blob'
        objects.append((kind, payload))
        tree += mode + b' ' + name + b'\0' + bytes.fromhex(identity(kind.encode(), payload).decode())
    objects.append(('tree', tree))
    commit = b'tree ' + identity(b'tree', tree) + b'\nauthor A <a@b> 1 +0000\ncommitter A <a@b> 1 +0000\n\ncheckout\n'
    objects.append(('commit', commit))
    # Empty tree may appear both as a child and root; deduplicate canonical objects.
    return pack(list(dict.fromkeys(objects))), identity(b'commit', commit)


def check(binary, compiler):
    with tempfile.TemporaryDirectory(prefix='luc-checkout-') as temporary:
        root = Path(temporary)
        source = root / 'input.pack'
        output = root / 'project'
        manifest = (b'#prisma 4.0\ndef package "hello" {\n    str owner = "acme"\n    str version = "0.1.0"\n'
                    b'    str kind = "tool"\n    str language = "luce-base"\n    str entry = "main.lucb"\n}\n')
        main = b'pub func main(arguments: str[]) -> i32:\n    discard(arguments)\n    return 0\n'
        wire, oid = fixture([(b'100644', b'main.lucb', main), (b'100644', b'package.prisma', manifest),
                             (b'100755', b'run.sh', b'#!/bin/sh\nexit 0\n')])
        source.write_bytes(wire)

        def run(success=False):
            result = subprocess.run([str(binary), 'checkout-pack', str(source), oid.decode(), str(output)],
                                    cwd=root, capture_output=True, timeout=40)
            assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
            assert (result.returncode == 0) == success, result.stderr
            if not success: assert result.stdout == b''
            assert not list(root.glob('.luc-checkout-*')), 'staging directory leaked'

        run(True)
        assert (output / 'package.prisma').read_bytes() == manifest
        assert (output / 'main.lucb').read_bytes() == main
        assert (output / 'run.sh').stat().st_mode & 0o100
        assert not (output / '.git').exists()
        run()  # Existing destination stays untouched.
        assert (output / 'main.lucb').read_bytes() == main
        env = dict(os.environ, LUCE_BASE=str(compiler))
        built = subprocess.run([str(binary), 'build'], cwd=output, env=env, capture_output=True, timeout=90)
        assert built.returncode == 0, (built.stdout, built.stderr)
        subprocess.run([str(output / 'build/hello')], check=True, timeout=10)
        # Keep the first checkout; test each rejection against a fresh destination.
        for i, (mode, name, payload) in enumerate([
            (b'100644', b'.git', b'hostile'), (b'100644', b'..', b'escape'),
            (b'100644', b'CON.txt', b'device'), (b'100644', b'bad\\name', b'escape'),
            (b'100644', b'trailing.', b'alias'), (b'120000', b'link', b'../../escape'),
            (b'100644', 'café'.encode(), b'unsupported')]):
            output = root / f'rejected-{i}'
            wire, oid = fixture([(mode, name, payload)])
            source.write_bytes(wire)
            run()
            assert not output.exists()
        output = root / 'link-destination'
        output.symlink_to(root / 'project', target_is_directory=True)
        wire, oid = fixture([(b'100644', b'ok', b'unchanged')])
        source.write_bytes(wire)
        run()
        assert output.is_symlink() and not (root / 'project/ok').exists()
        output = root / 'empty-directory-project'
        wire, oid = fixture([(b'40000', b'empty', b'')])
        source.write_bytes(wire)
        run(True)
        assert (output / 'empty').is_dir()
    print('PASS checkout byte/mode fidelity, Luce Base build/run, hostile paths and no-clobber rollback', flush=True)


if __name__ == '__main__':
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
