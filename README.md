# luc

The unified project tool for the [Luce](https://github.com/dymokomi/luce) languages — one
command to build, run, test and format a project and to run the workflows declared in its
`luce.toml`. Written in Luce Base. In the spirit of cargo and uv; see the design in
[`~/dev/luc-design.md`] for the full roadmap (scaffolding, dependencies, task graphs, workspaces).

## Commands

```
luc new <dir> [opts]      scaffold a new project (--package|--app, --luce|--luce-base)
luc init [opts]           scaffold a project in the current directory
luc add <path>            add a local package dependency to luce.toml
luc lock --check          validate luc.lock syntax without fetching or changing files
luc remote-refs <url>     list remote Git refs (loopback HTTP development transport)
luc remote-fetch <url> <commit-id> <new-pack-path>  fetch a validated full Git pack
luc remove <name>         remove a dependency from luce.toml
luc build [--release]     build the project into build/<name>
luc run [--release]       build and run the project
luc run <task>            run a named [tasks] workflow from luce.toml
luc test                  build and run the project's tests
luc check                 type-check without producing a binary
luc fmt [--check]         format the project's sources
luc clean [cache]         remove build/ (or, with cache, only the build cache)
luc update | upgrade      reinstall the latest luc, luce-base and luce
luc --version | help
```

`build`, `run`, `test`, `check` and `fmt` forward to the Luce compiler (its output and exit
code pass straight through). `-- args` after a command are forwarded: `luc run -- --verbose`
runs the app with `--verbose`; `luc test -- --filter parse` filters tests.

## The project

luc walks up from the current directory to the nearest `luce.toml`:

```toml
[package]
name = "hello"
language = "luce-base"   # or "luce"; picks the compiler (override with LUCE_BASE / LUCE)
# entry = "src/main.lucb"  # optional; defaults to src/main.<ext> then main.<ext>

[tasks]
dev  = "luc run"                       # string form: a shell command

[tasks.lint]
description = "check formatting"        # shown by `luc run <unknown>`
cmd = "luc fmt --check"

[tasks.ci]
cmd = "luc test"
depends = ["lint"]                     # deps run first (a DAG: each once, topological)
```

`luc run <name>` runs a `[tasks]` entry through the host shell (`sh -c` on POSIX, `cmd /c` on
Windows), so `&&`, pipes and redirects work; `depends` run first (each at most once; a cycle is an error). Args after `--` pass to the
target task through `"$@"`: `luc run ci -- --filter parse`. The build cache is the project's own
`build/.cache`, cleared by `rm -rf build`.

## Build and test

`luc remote-refs http://127.0.0.1:<port>/git/<owner>/<name>` performs native
authenticated upload-pack discovery without a project manifest or file writes.
Set `LUCE_REGISTRY_TOKEN` to a disposable 32-character hex session token from the
native test registry; it is never printed or accepted as a command-line argument.
The command validates the complete bounded advertisement before printing any refs,
including HEAD and peeled tags. Invalid responses produce no partial ref output.
Only explicit numeric loopback HTTP is enabled: public HTTPS trust and credential
vaults remain unfinished. This is not login, clone, installation or signature
verification, and environment-token delivery is not a production custody solution.

Build dependencies also include pinned siblings `luce-git`, `luce-compress`,
`luce-http-client` and `luce-tls`; `build.sh` and CI check their exact revisions.
The remote oracle runs in every compiler mode and under sanitizers via
`tests/release_modes.py`. `tests/remote_registry.py` accepts built luc, registry,
account-fixture and native-transfer binaries to exercise the actual sibling registry
with disposable accounts; this larger cross-repository test is run separately.

`luc remote-fetch <url> <commit-id> <new-pack-path>` uses the same loopback/token
policy, requires the requested ID to be advertised, and performs native Git
upload-pack negotiation without haves. It accepts a complete self-contained pack,
checks its checksum, requires the requested object to be a commit, rejects duplicate
objects, and validates all tree/commit/tag references and expected types. Gitlinks
are external repositories and are not downloaded. Limits include 64 MiB response,
the Git decoder's 4096 objects/64 MiB expansion bounds, and 16,777,216 graph-search
comparisons. No extraction, checkout, dependency installation or release signature
verification is implied by Git's SHA-1 object checks.

Only after validation does it write a private temporary sibling, sync the file,
and atomically publish without replacing any existing destination (including a
symlink). Errors clean up that temporary; the parent directory is not fsynced, so
power-loss durability is not promised. A caller must choose a trusted destination
directory. This command is the pack-transfer primitive for later checkout/cache
integration, not the finished package-install workflow.

Check out sibling `luce-pkg` and `luce-crypto` at `bootstrap/PKG` and
`bootstrap/CRYPTO` before building. The build verifies their revisions. These
native dependencies supply shared lock parsing and, for later remote integration,
package cryptography. `luc lock --check` discovers the project from nested
directories, reads at most 1 MiB, and rejects malformed restricted-v1 lockfiles.
It does not verify signatures, compare the manifest, resolve packages or install
anything; its success output explicitly states that signatures are not verified.

`luc verify-release <metadata> <signature> <trusted-key> <source>` verifies local
LRS1 metadata with native ML-DSA-65 and binds the exact source bytes with SHA-256.
The signature and public key are raw binary (3309 and 1952 bytes). Metadata is
bounded to 1600 bytes and source input to 64 MiB for this initial buffered command.
Paths are relative to the working directory; no project manifest is required.
It performs no network requests, extraction, installation or file writes.
The supplied key must already be trusted: success does not prove origin ownership,
publisher authorization, freshness or that the release matches a project request.
Remote installation and registry-root/key-distribution policy are not implemented.
Add `--locked` after the four paths to require an existing project and `luc.lock`:
the signed origin, package, version, SHA-256 source digest and compiler must match
the lock. Project discovery walks upward from the current directory; input paths
still refer to the current directory. Missing/malformed locks and mismatches fail
without writes. Lock v1 does **not** pin a Git commit or toolchain version; this
check does not claim those protections, freshness, or publisher authorization.
Tests generate deterministic **test-only** keys in a temporary directory and check
tampering, truncation, extra bytes, missing files, argument errors and no writes.
The macOS heap gate checks ordinary command exit status independently and requires
the instrumented output plus a zero-leak report. It captures output in regular
files and cleans up only its launched process group: macOS 15's leak tool can
finish while leaving its child stopped with inherited output descriptors open.
Actual tool timeouts remain failures. `python3 tests/test_heap_process.py` covers
status preservation, stopped children and genuine timeouts. This test helper is
adapted from the same author's dual-licensed `luce-auth` heap harness.

`./build.sh` builds luc with the Base commit pinned in `bootstrap/BASE` (fetched into an
isolated `build/luce-base`); `LUCE_BASE_COMPILER=/path/to/luce-base ./build.sh` uses an
existing compiler instead. `./test.sh` runs the gate.

## Not yet (next slices)

task input/output caching, workspaces, an ephemeral tool
runner (`luc x`) and shell completions.

## License

Dual-licensed under Apache-2.0 or MIT, at your option.
