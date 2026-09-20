"""Independent native luc fetch oracle and atomic no-clobber publication checks."""
import hashlib
import base64
import http.server
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import zlib


def pkt(data):
    return f'{len(data) + 4:04x}'.encode() + data


def identity(kind, payload):
    return hashlib.sha1(kind + b' ' + str(len(payload)).encode() + b'\0' + payload).hexdigest().encode()


def pack(objects):
    wire = b'PACK' + struct.pack('>II', 2, len(objects))
    for kind, payload in objects:
        size = len(payload)
        header = bytearray([({'commit': 1, 'tree': 2, 'blob': 3, 'tag': 4}[kind] << 4) | (size & 15)])
        size >>= 4
        while size:
            header[-1] |= 128
            header.append(size & 127)
            size >>= 7
        wire += header + zlib.compress(payload)
    return wire + hashlib.sha1(wire).digest()


def check(binary):
    tree = identity(b'tree', b'')
    commit = b'tree ' + tree + b'\nauthor A <a@b> 1 +0000\ncommitter A <a@b> 1 +0000\n\nfixture\n'
    oid = identity(b'commit', commit)
    valid = pack([('commit', commit), ('tree', b'')])
    state = {'response': b'0008NAK\n' + valid, 'posts': 0}
    advertisement = pkt(b'# service=git-upload-pack\n') + b'0000' + pkt(oid + b' refs/heads/main\0ofs-delta\n') + b'0000'

    class Handler(http.server.BaseHTTPRequestHandler):
        def respond(self, data):
            expected = 'Basic ' + base64.b64encode(b'alice:' + b'a' * 64).decode()
            assert self.headers['Authorization'] == expected
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.respond(advertisement)

        def do_POST(self):
            state['posts'] += 1
            request = self.rfile.read(int(self.headers['Content-Length']))
            assert request == pkt(b'want ' + oid + b'\n') + b'00000009done\n'
            assert self.headers['Content-Type'] == 'application/x-git-upload-pack-request'
            self.respond(state['response'])

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix='luc-fetch-') as temporary:
            root = Path(temporary)
            env = dict(os.environ, LUCE_REGISTRY_TOKEN='a' * 64)
            url = f'http://127.0.0.1:{server.server_port}/git/alice/demo'
            output = root / 'source.pack'

            def run(wanted=oid, success=False):
                result = subprocess.run([str(binary), 'remote-fetch', url, wanted.decode(), str(output)],
                                        env=env, cwd=root, capture_output=True, timeout=40)
                assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
                assert (result.returncode == 0) == success, result.stderr
                if not success: assert result.stdout == b''
                assert not list(root.glob('.luce-*')), 'temporary file leaked'

            run(success=True)
            assert output.read_bytes() == valid
            run()  # Never overwrite an existing destination.
            assert output.read_bytes() == valid
            output.unlink()
            protected = root / 'protected'
            protected.write_bytes(b'keep')
            output.symlink_to(protected)
            run()
            assert protected.read_bytes() == b'keep' and output.is_symlink()
            output.unlink()
            previous = state['posts']
            run(b'f' * 40)
            assert state['posts'] == previous and not output.exists()
            for response in (b'', b'0008NAK\n', b'0008NAK\n' + valid[:-1],
                             b'0008NAK\n' + valid[:-1] + bytes([valid[-1] ^ 1]),
                             pkt(b'ACK ' + oid + b'\n') + valid,
                             b'0008NAK\n' + pack([('tree', b'')]),
                             b'0008NAK\n' + pack([('commit', commit)]),
                             b'0008NAK\n' + pack([('commit', commit), ('tree', b''), ('tree', b'')])):
                state['response'] = response
                run()
                assert not output.exists()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    print('PASS luc native fetch, graph closure, checksum, identity and atomic no-clobber publication', flush=True)


if __name__ == '__main__':
    check(Path(sys.argv[1]).resolve())
