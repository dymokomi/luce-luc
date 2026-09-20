#!/usr/bin/env python3
"""Release verification CLI in six compiler modes and generated-C sanitizers."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base', type=Path, required=True)
args = parser.parse_args()
base = args.base.resolve()
out = ROOT / 'build/release-modes'
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ)
env.setdefault('LUCE_STD', str(ROOT.parent / 'luce-base/src/std'))
env.setdefault('LUCE_CACHE', str(ROOT / 'build/cache'))

def run(command):
    print('RUN', ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), env=env, cwd=ROOT, check=True, timeout=600)

fixture = out / 'fixture'
run([base, 'build', 'tests/release_fixture.lucb', '--native', '-o', fixture])
signed_fixture = out / 'checkout-release-fixture'
run([base, 'build', 'tests/checkout_release_fixture.lucb', '--native', '-o', signed_fixture])
signing_verifier = out / 'signing-verifier'
run([base, 'build', 'tests/signing_verify.lucb', '--native', '-o', signing_verifier])
modes = [(f'native{i}', ['--native', '--opt', str(i)]) for i in range(4)]
modes += [('c', ['--backend=c']), ('c-release', ['--backend=c', '--release'])]
for name, flags in modes:
    binary = out / name
    run([base, 'build', 'src/luc/main.lucb', *flags, '-o', binary])
    run([sys.executable, 'tests/release.py', binary, fixture])
    run([sys.executable, 'tests/version_bounds.py', binary, fixture])
    run([sys.executable, 'tests/remote.py', binary])
    run([sys.executable, 'tests/credentials.py', binary])
    run([sys.executable, 'tests/login.py', binary])
    run([sys.executable, 'tests/register.py', binary])
    run([sys.executable, 'tests/repository.py', binary])
    run([sys.executable, 'tests/keys.py', binary])
    run([sys.executable, 'tests/signing.py', binary, signed_fixture, signing_verifier])
    run([sys.executable, 'tests/fetch.py', binary])
    run([sys.executable, 'tests/checkout.py', binary, base])
    run([sys.executable, 'tests/checkout_release.py', binary, signed_fixture])
runtime = ROOT.parent / 'luce-base/runtime'
generated = out / 'sanitize.c'
binary = out / 'sanitize'
run([base, 'build', 'src/luc/main.lucb', '--emit=c', '-o', generated])
run([os.environ.get('CC', 'cc'), '-std=gnu11', '-O1', '-g', '-w',
     '-fno-strict-aliasing', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
     '-I', runtime, generated, runtime / 'lucb_rt.c', '-pthread', '-lm', '-o', binary])
env['ASAN_OPTIONS'] = 'halt_on_error=1:abort_on_error=1'
env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
run([sys.executable, 'tests/release.py', binary, fixture])
run([sys.executable, 'tests/version_bounds.py', binary, fixture])
run([sys.executable, 'tests/remote.py', binary])
run([sys.executable, 'tests/credentials.py', binary])
run([sys.executable, 'tests/login.py', binary])
run([sys.executable, 'tests/register.py', binary])
run([sys.executable, 'tests/repository.py', binary])
run([sys.executable, 'tests/keys.py', binary])
run([sys.executable, 'tests/signing.py', binary, signed_fixture, signing_verifier])
run([sys.executable, 'tests/fetch.py', binary])
run([sys.executable, 'tests/checkout.py', binary, base])
run([sys.executable, 'tests/checkout_release.py', binary, signed_fixture])
print('PASS release verification: six compiler modes and ASan/UBSan', flush=True)
