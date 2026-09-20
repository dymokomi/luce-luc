"""Native luc key enrollment against the native persistent registry, no production state.

Usage: keys_registry.py LUC REGISTRY ACCOUNT_FIXTURE
"""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

luc, registry, fixture = [Path(arg).resolve() for arg in sys.argv[1:4]]
signing_fixture = Path(sys.argv[4]).resolve() if len(sys.argv) == 5 else None
with tempfile.TemporaryDirectory(prefix='luc-key-registry-', dir='/tmp') as temporary:
    root = Path(temporary)
    database = root / 'registry.db'
    subprocess.run([str(fixture), str(database)], check=True, capture_output=True, timeout=60)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    env = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN='integration-store-token', LUCE_REGISTRY_ORIGIN=origin)
    session, key = root / 'session.vault', root / 'key.vault'
    def command(args, data, success=True):
        result = subprocess.run([str(luc), *map(str, args)], input=data, cwd=root,
                                env=env, capture_output=True, timeout=60)
        assert result.returncode >= 0 and b'Sanitizer' not in result.stderr and b'runtime error:' not in result.stderr, result.stderr
        assert (result.returncode == 0) == success, result.stderr
        return result
    with (root / 'registry.log').open('w+') as log:
        def start():
            process = subprocess.Popen([str(registry), str(database), str(port)], env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    assert process.poll() is None, 'registry exited'
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
                    try:
                        connection.request('GET', '/health')
                        response = connection.getresponse()
                        if response.status == 200 and response.read() == b'ok': return process
                    except OSError:
                        pass
                    finally:
                        connection.close()
                    time.sleep(.05)
                raise AssertionError('registry startup timeout')
            except BaseException:
                stop(process)
                raise
        def stop(process):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise AssertionError('registry failed to stop')
            if process.returncode != 0:
                log.seek(0)
                raise AssertionError(log.read())
        process = start()
        try:
            command(['login', origin, 'testadmin', session, '--passwords-stdin'], b'fixture-password\nvault-password\n')
            command(['key-create', origin, 'testadmin', key, '--password-stdin'], b'signing-password\n')
            before = key.read_bytes()
            enroll = ['key-enroll', origin, 'testadmin', '--vault', session, '--key-vault', key, '--passwords-stdin']
            passwords = b'vault-password\nsigning-password\n'
            command(enroll, passwords)
            assert key.read_bytes() == before
            command(enroll, passwords)
            assert key.read_bytes() == before
        finally:
            stop(process)
        process = start()
        try:
            check_key = list(enroll)
            check_key[0] = 'key-check'
            result = command(check_key, passwords)
            assert b'Confirmed registry signing key' in result.stdout
            assert key.read_bytes() == before
            other_key = root / 'other.vault'
            command(['key-create', origin, 'testadmin', other_key, '--password-stdin'], b'signing-password\n')
            different = list(enroll)
            different[6] = other_key
            result = command(different, passwords, False)
            assert b'remote signing key differs' in result.stderr
            # Bound signing keys do not break the session/repository workflow.
            command(['repo-create', origin, 'signed-account', '--vault', session, '--password-stdin'], b'vault-password\n')
            if signing_fixture is not None:
                def request(method, path, body=b'', headers=None):
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
                    try:
                        connection.request(method, path, body, headers or {})
                        response = connection.getresponse()
                        return response.status, response.read()
                    finally:
                        connection.close()
                status, token = request('POST', '/v1/sessions', json.dumps({'name': 'testadmin', 'password': 'fixture-password'}))
                assert status == 200
                headers = {'Authorization': 'Bearer ' + token.decode(), 'Content-Type': 'application/octet-stream'}
                def scoped(scope):
                    status, value = request('POST', '/v1/credentials', json.dumps({
                        'scope': scope, 'repository': 'signed-account', 'lifetime_seconds': 3600,
                    }).encode(), {'Authorization': 'Bearer ' + token.decode(), 'Content-Type': 'application/json'})
                    assert status == 201 and len(value) == 64
                    return {'Authorization': 'Bearer ' + value.decode()}
                package_publish_headers = scoped('package:publish')
                package_publish_binary = dict(package_publish_headers, **{'Content-Type': 'application/octet-stream'})
                package_read_headers = scoped('package:read')
                subprocess.run([str(signing_fixture), str(root)], check=True, timeout=30)
                metadata = (root / 'metadata').read_bytes()
                fields, at = [], 6
                for _ in range(6):
                    size = int.from_bytes(metadata[at:at + 2], 'little')
                    at += 2
                    fields.append(metadata[at:at + size])
                    at += size
                fields[0], fields[1] = origin.encode(), b'testadmin/signed-account'
                metadata = metadata[:6] + b''.join(len(v).to_bytes(2, 'little') + v for v in fields) + metadata[at:]
                (root / 'metadata').write_bytes(metadata)
                objects = root / 'objects.git'
                subprocess.run(['git', 'init', '--bare', str(objects)], check=True, capture_output=True, timeout=30)
                source = (root / 'source').read_bytes()
                subprocess.run(['git', '-C', str(objects), 'unpack-objects'], input=source,
                               check=True, capture_output=True, timeout=30)
                commit = subprocess.check_output(['git', '-C', str(objects), 'cat-file', 'commit', fields[3].decode()], timeout=30)
                wire = b'commit ' + str(len(commit)).encode() + b'\0' + commit
                assert request('PUT', '/v1/repositories/testadmin/signed-account/objects/' + fields[3].decode(), wire, headers)[0] == 200
                artifact = root / 'signed-upload'
                sign = ['release-sign', root / 'metadata', root / 'source', artifact, '--key-vault', key, '--password-stdin']
                command(sign, b'signing-password\n')
                upload = artifact.read_bytes()
                endpoint = '/v1/releases/testadmin/signed-account'
                publish = ['release-upload', origin, artifact, '--vault', session, '--password-stdin']
                reconcile = list(publish)
                reconcile[0] = 'release-check'
                command(reconcile, b'vault-password\n', False)
                command(publish, b'wrong-password\n', False)
                command(publish, b'vault-password\n')
                command(reconcile, b'vault-password\n')
                command(publish, b'vault-password\n')
                assert request('POST', endpoint, upload, package_publish_binary) == (200, b'unchanged')
                listed = command(['versions', origin, 'testadmin/signed-account', '--vault', session,
                                  '--password-stdin'], b'vault-password\n')
                assert listed.stdout == b'1.2.3\n'
                selected = command(['resolve', origin, 'testadmin/signed-account', '^1.0.0', '--vault', session,
                                    '--password-stdin'], b'vault-password\n')
                assert selected.stdout == b'1.2.3\n'
                size = int.from_bytes(upload[4:6], 'little')
                for part, expected in (('metadata', metadata), ('signature', upload[8 + size:3317 + size]), ('source', source)):
                    assert request('GET', endpoint + '/1.2.3/' + part, headers=package_read_headers) == (200, expected)
                # Test-only trust provisioning from the already reconciled account;
                # the client itself never fetches/accepts a publisher key implicitly.
                status, public_key = request('GET', '/v1/identity/key', headers=headers)
                assert status == 200 and len(public_key) == 1952
                (root / 'trusted-key').write_bytes(public_key)
                command(['release-download', origin, 'testadmin/signed-account', '1.2.3', root / 'downloaded',
                         '--trusted-key', root / 'trusted-key', '--vault', session, '--password-stdin'], b'vault-password\n')
                assert (root / 'downloaded').is_dir() and not list((root / 'downloaded').iterdir())
                assert artifact.read_bytes() == upload and key.read_bytes() == before
                print('PASS luc vault-signed artifact accepted by native registry; exact retry, catalog selection and verified downloads', flush=True)
        finally:
            stop(process)
print('PASS native luc encrypted signing key -> registry ML-DSA enrollment, replay and restart', flush=True)
