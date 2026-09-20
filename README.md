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
luc lock <origin> --trusted-key <key> --vault <session> --password-stdin
luc install <origin> <owner/package> <version> --trusted-key <key> (--vault <session> --password-stdin | --offline) [--locked]
luc sync --trusted-key <key> (--vault <session> --password-stdin | --offline)
luc versions <origin> <owner/package> --vault <session> --password-stdin
luc resolve <origin> <owner/package> <version|^version> --vault <session> --password-stdin
luc remote-refs <url>     list remote Git refs (verified production HTTPS or loopback HTTP)
luc remote-fetch <url> <commit-id> <new-pack-path>  fetch a validated full Git pack
luc checkout-pack <pack> <commit-id> <new-directory>  materialize source files
luc checkout-release <metadata> <signature> <key> <pack> <new-directory> [--locked]
luc publish <origin> <owner/package> <version> <commit> <toolchain> <new-artifact> --vault <session> --key-vault <key> --passwords-stdin
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

`luc remote-refs <origin>/git/<owner>/<name>` performs native
authenticated upload-pack discovery without a project manifest or file writes.
Set `LUCE_REGISTRY_TOKEN` only for the vaultless form, to a disposable 64-character
hex `git:read` credential bound to the URL's repository. luc sends it with canonical
HTTP Basic authentication using the URL owner as the username; it is never printed
or accepted as a command-line argument.
The command validates the complete bounded advertisement before printing any refs,
including HEAD and peeled tags. Invalid responses produce no partial ref output.
The accepted origins are exactly `https://pkg.luciaos.com` and canonical numeric
loopback HTTP used by isolated tests. Production requests use native TLS 1.3 and
validate the complete bounded Caddy/Let's Encrypt path under the pinned ISRG Root
X2 P-384 key. This is not a general system CA store and currently has no OCSP/CRL
revocation check. Git discovery is not login, clone, installation or release
signature verification, and environment-token delivery is not production custody.

Encrypted session-token storage is available for either accepted origin:

```text
luc auth-store <origin> <account> <new-vault> --secrets-stdin
luc login <origin> <account> <new-vault> --passwords-stdin
luc register <origin> <account> --secrets-stdin
luc repo-create <origin> <name> --vault <vault> --password-stdin
luc key-create <origin> <account> <new-key-vault> --password-stdin
luc key-enroll <origin> <account> --vault <session-vault> --key-vault <key-vault> --passwords-stdin
luc key-check <origin> <account> --vault <session-vault> --key-vault <key-vault> --passwords-stdin
luc release-sign <metadata> <pack> <new-upload> --key-vault <key-vault> --password-stdin
luc release-upload <origin> <artifact> --vault <session-vault> --password-stdin
luc release-check <origin> <artifact> --vault <session-vault> --password-stdin
luc publish <origin> <owner/package> <version> <commit> <toolchain> <new-artifact> --vault <session-vault> --key-vault <key-vault> --passwords-stdin
luc release-download <origin> <owner/package> <version> <new-directory> --trusted-key <key> --vault <session-vault> --password-stdin [--locked]
luc remote-refs <git-url> --vault <vault> --password-stdin
luc remote-fetch <git-url> <commit> <new-pack-path> --vault <vault> --password-stdin
```

`auth-store` reads exactly a password line, a 32-lowercase-hex token line, then
EOF from a private pipe. Remote commands read one password line and EOF. Terminal
stdin is refused so these commands cannot echo a password accidentally; interactive
hidden-entry prompts remain unfinished. Do not put secrets in shell command text
or history. No password environment variable or secret command argument is used.
The parent directory must already be private, owned, trusted and stable. The
native auth vault uses Argon2id/XChaCha20-Poly1305, mode0600 no-clobber publication,
and authenticated reads. Optional vault flags take precedence over the legacy
token environment variable; failure never falls back to it. Vault-authenticated Git
and package commands use the session only to mint a five-minute credential for the
exact repository and scope, then best-effort revoke it. Git requests use Basic;
package requests use Bearer. The session token is never sent to either data plane.

`login` instead reads the registry-password line, then a separate vault-password
line and EOF. It posts bounded JSON to `/v1/sessions`, checks `/v1/identity` matches
the requested account, and publishes a new encrypted vault. It refuses an existing
destination before contacting the server and still uses atomic no-replace when
publishing. On failure after receiving a valid token but before publication, it
attempts revocation with a five-second timeout; network failure can leave a session
alive until server expiry. A failure after publication does not revoke the stored
token, since a directory-sync error may leave a usable file with uncertain durability.
The registry password and vault password may differ; neither is printed. No raw
server response body is included in error messages. Loopback HTTP is only for
disposable development accounts; use the exact verified HTTPS origin for remote
credentials.

`register` reads an invitation-code line (32 lowercase hex characters), then
a registry-password line and EOF, with the same terminal refusal. It redeems the
invitation through `/v1/invites/redeem` and writes no local files. It does not
automatically log in, retry, or undo registration: a dropped response may leave
an account created and its invitation consumed. Check account state/login before
retrying an ambiguous failure. Invitation issuance remains an administrator-side
operation; no public invitation creation endpoint is introduced.

`repo-create` decrypts the origin-bound vault and posts only the repository name
to `/v1/repositories`; the server assigns ownership from the authenticated
session. Names are 1–64 lowercase letters/digits/underscore/hyphen and start with
a letter or digit. It writes no local files, does not initialize a Git working
tree or configure a remote, and does not publish a signed package release.
Conflicts and other non-success responses fail without automatic retry; an
ambiguous network failure may mean the remote repository was created.

`key-create` is offline: it reads one password line and EOF, generates an OS-random
32-byte ML-DSA-65 seed, and publishes a new encrypted signing-key vault without
replacement. Its LAV1-encrypted payload is `LUK1\norigin\naccount\n` followed by the
32 binary seed bytes. It uses the same private-directory/file policy as session
vaults. Keep a secure backup before enrollment; there is no rotation/recovery yet.
The seed and expanded private-key buffers are wiped when their owners close.

`key-enroll` reads the session-vault password line followed by the signing-key-vault
password line and EOF. Both vaults must already exist and match the exact origin
and account. It verifies the session principal and reads the enrolled key first.
An exact match confirms the existing binding without mutation; a different key or
unavailable readback fails closed. Only404 (unbound) proceeds to a fresh challenge
and native domain-bound ML-DSA-65 possession proof. A201 enrollment response is
followed by exact public-key readback before success is reported. The
registry's `LUCE_REGISTRY_ORIGIN` must equal the requested origin. Neither vault is
modified or deleted, including after a lost response or rejected enrollment. There
is no automatic write retry: errors can occur after remote publication. A conflict
does not prove that this particular key was bound. Preserve the vault and use
`key-check` after uncertain outcomes: it takes the same arguments/passwords but
only verifies identity and compares the remote key to the vault-derived public
key. An unbound account is an error in check-only mode, never an implicit enrollment.
Neither command overwrites a conflicting key. This command
is first-key enrollment, not release publication. Both commands refuse terminal
secret input. The production path uses the same origin-bound encrypted custody
over verified HTTPS; the overall stack remains experimental and not security-reviewed.

`release-sign` is offline: it reads canonical LRS1 or LRS2 metadata and a standalone Git
pack, verifies SHA-256 source binding and typed pack closure for the signed commit,
then unlocks the matching origin/account LUK1 signing vault. It requires an
`owner/package` identity using the registry naming rules and a numeric toolchain
version. LRS2 source-manifest agreement is enforced again by the registry during
publication; offline signing validates the signed declaration and pack closure.
One vault-password line and EOF must come from nonterminal stdin. The vault origin
must be either the exact production registry origin or canonical numeric loopback
HTTP; no arbitrary host, redirect or downgrade is accepted.

It creates a fresh randomized native ML-DSA-65 signature, self-verifies it, and
saves an LRP1 upload:8-byte header (`LRP1`, u16le metadata length, two reserved zero
bytes), metadata,3309-byte signature, exact pack bytes. Publication uses a0600
temporary file, file sync, atomic no-replace and parent-directory sync. Keep the
destination parent/ancestors trusted and stable. An existing entry, including a
symlink, is never replaced. A directory-sync failure can leave a published file;
inspect the destination rather than assuming an error means no file exists.
The artifact contains source and public proof, not the seed or expanded secret
key. Seed/private-key/randomness owners are wiped on close. Preserve the exact
artifact for retries: re-signing produces a different signature, which conflicts
with an already published immutable version. No network request, key enrollment,
registry commit upload, release upload or automatic retry is performed here.
It validates pack graph structure, not checkout path portability or project build
correctness. The lower-level command remains useful for offline custody and
explicitly prepared metadata; `luc publish` provides the integrated path below.

`release-upload` consumes that saved artifact and an explicit matching origin.
It unlocks an origin/account-bound session vault from one password line plus EOF,
reads the authenticated account's enrolled key, and verifies the signature, source
digest and Git pack closure. It then mints a bounded `package:publish` credential
for the signed repository before sending one POST and exact readback requests.
Success requires a201
`published` or200 `unchanged` reply followed by exact metadata/signature/source
readback. A failed request or readback can still mean publication happened. Retain
the artifact and use `release-check`, which performs GETs only, before deciding
whether to retry the exact artifact. Neither command changes local vaults or
artifacts. Conflicts are never overwritten and redirects are not followed.

These commands use verified production HTTPS or canonical loopback HTTP. The enrolled key is obtained
from the authenticated registry, not an independent publisher trust source; this
is publication reconciliation, not public package discovery or trust bootstrap.
The repository and signed commit must already exist remotely. Release uploads
are bounded to 64 MiB source plus envelope; readback loads source in memory. The
lower-level upload does not generate metadata or install dependencies. Publisher
trust provisioning remains separate.

`publish` is the safe end-to-end convenience path. It reads the session-vault
password followed by the signing-key-vault password and EOF from a private pipe.
The named commit must already be advertised by the package's registry Git remote.
luc mints a short-lived `git:read` credential, fetches and validates the complete
commit graph, and derives package name, compiler and canonical registry dependency
declarations from that commit's regular root `luce.toml`—never from a mutable
working tree. It constructs LRS2 metadata for the explicit version and numeric
toolchain version, saves a new mode-0600 signed LRP1 artifact, then publishes and
reads back the exact bytes with a separate short-lived `package:publish`
credential. The artifact destination is checked before any network work and is
never replaced. If upload or readback is uncertain, the signed artifact remains;
use `release-check` and, only if absent, `release-upload` with those exact bytes.

`versions` unlocks the encrypted session vault, mints a bounded `package:read`
credential for the exact repository, and fetches its LPV1 catalog. It validates the complete canonical,
unique, descending numeric-semver list before printing any server-controlled
version text. `resolve` applies either an exact requirement or the package
library's caret compatibility rule and prints only the highest match. Discovery
and selection are advisory: neither command downloads a release, changes project
files, establishes publisher-key trust or proves freshness. A later install must
still verify signed metadata, the explicit trusted ML-DSA key, source digest and
Git graph. Both commands remain owner-authenticated and use the same strict
production-HTTPS/loopback transport boundary.

`release-download` fetches an exact release into a new source directory. Supply
an independently trusted1952-byte ML-DSA-65 publisher key; the command never
accepts a key fetched from the registry as trust. It checks the requested origin,
package and version, verifies signed metadata before fetching source, verifies
the source digest, then validates and materializes the signed Git commit through
the same no-clobber checkout path as `checkout-release`. `--locked` also requires
the existing project lock to match (v2 includes commit/toolchain pins). Signature,
digest, identity or lock failure creates no checkout. Existing destinations are
never replaced; checkout path restrictions still apply. No project manifest or
lock is edited, no build runs, and this is not yet dependency installation/cache.
Caller-supplied trust does not establish freshness or key ownership automatically.
The endpoint is owner-authenticated rather than anonymous public catalog access;
production HTTPS is implemented, while publisher trust provisioning remains explicit.

`install` turns the verified release into a compiler-native local dependency.
Online mode downloads and verifies the exact release, then atomically saves its
LRP1 bytes in the cache. Offline mode performs no credential read and no network
request: it reopens and reverifies those same bytes against the explicit trusted
key. `--locked` requires the existing lock entry, including v2 commit/toolchain
pins, before checkout. Both modes validate the signed Git graph, atomically create
`.luc/packages/release-<request-hash>`, check its root `luce.toml` package name and
language, and atomically add that relative path under the consumer's
`[dependencies]`. Both compilers therefore use their existing local dependency
contract; no language repository change or generated import shim is involved.

The default artifact cache is `.luc/cache`; set `LUC_PACKAGE_CACHE` to an existing
or creatable cache directory whose parent already exists. Installed sources stay
project-local even with a relocated shared cache, so moving the project preserves
its manifest paths. New projects ignore `.luc/` in Git. Cache entries are0600,
file- and directory-synchronized, immutable/no-replace, and reconciled byte for
byte if concurrent installers publish the same entry. Final cache symlinks,
malformed/tampered artifacts, mismatched trust/identity/lock, unsafe checkout
paths, missing manifests, language mismatches and existing install destinations
fail without changing `luce.toml`; a verified cache artifact may remain after a
later install failure. Installed source is ordinary local project state and is not
continuously revalidated after installation. `install` remains the explicit
single-package operation; use `lock` and `sync` for a complete declared dependency
graph. Publisher trust provisioning remains explicit and single-key.

The encrypted LUC1 payload is `LUC1\norigin\naccount\ntoken\n`. Origin must be exact
`https://pkg.luciaos.com` or `http://127.0.0.1:<nonzero-port>` without leading port
zeroes or a trailing slash; it is checked before any request. Account names follow native auth syntax.
The stored account label is not proof of server identity or account ownership.
Wrong password, malformed vault or origin mismatch stops the request without
exposing the token. `auth-store` only imports an existing session; `login` obtains
one and checks its principal. Neither renews expired tokens or rotates credentials.

Build dependencies also include pinned siblings `luce-git`, `luce-compress`,
`luce-http-client`, `luce-tls`, `luce-auth` and `luce-prism`; `build.sh` and CI check their exact revisions.
The remote oracle runs in every compiler mode and under sanitizers via
`tests/release_modes.py`. `tests/remote_registry.py` accepts built luc, registry,
account-fixture and native-transfer binaries to exercise the actual sibling registry
with disposable accounts; this larger cross-repository test is run separately.
`tests/keys_registry.py LUC REGISTRY ACCOUNT_FIXTURE` separately verifies native
key enrollment, replay rejection and persistent binding after registry restart.
An optional fourth `CHECKOUT_RELEASE_FIXTURE` argument adds CLI artifact signing
with the enrolled random key, native registry acceptance, exact retries and
downloaded-byte verification. The test harness performs HTTP upload for now.

`luc remote-fetch <url> <commit-id> <new-pack-path>` uses the same strict
production-HTTPS/loopback token policy, requires the requested ID to be advertised, and performs native Git
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

`luc checkout-pack` validates the full pack and commit graph, plans the selected
tree before filesystem writes, then materializes it beneath a private temporary
sibling directory and publishes via atomic no-replace rename. Existing directories
or symlinks are never replaced. Only entries created by this operation are removed
on rollback. Files preserve binary bytes and Git's executable bit (subject to umask).
The result is a source directory, **not** a `.git` working repository; there is no
automatic execution or release-signature verification. Destination parents must
be trusted; parent-directory fsync and power-loss durability are not promised.

Current portable checkout profile: regular files/directories, ASCII names,
4096 entries including root, depth 64, paths up to 4096 bytes, 64 MiB expanded file
bytes, and bounded object searches. Traversal names, `.git` aliases, Windows device
names and reserved characters are rejected. Unicode names, symlinks and submodules
are explicitly unsupported pending their complete portability/security policy.
Tests cover extracted bytes/modes, rejection and rollback, existing destinations,
and building/running an extracted Luce Base project. The real-registry fixture
compares native fetch-to-checkout files against a stock Git working tree.

`checkout-release` gates the same materializer on native ML-DSA-65 release
verification and the signed SHA-256 source digest. It selects the commit from
signed LRS1/LRS2 metadata, rather than a separate untrusted argument. Verification and
checkout use the same retained source bytes, with no path reopening between them.
`--locked` additionally requires the current restricted lock entry to match
origin/package/version/digest/compiler before any publication. All checkout
limits and filename restrictions still apply. The key is explicitly supplied and
must already be trusted; publisher ownership, key distribution/revocation,
freshness remain unfinished. V2 also compares the signed commit and toolchain to
the lock; v1 retains its weaker compatibility contract. This is not automatic
dependency resolution or installation and does not establish registry-wide trust.

Check out sibling `luce-pkg` and `luce-crypto` at `bootstrap/PKG` and
`bootstrap/CRYPTO` before building. The build verifies their revisions. These
native dependencies supply shared lock parsing and, for later remote integration,
package cryptography. `luc lock --check` discovers the project from nested
directories, reads at most 1 MiB, and rejects malformed restricted v1/v2/v3 lockfiles.
It does not verify signatures, compare the manifest, resolve packages or install
anything; its success output explicitly states that signatures are not verified.

The networked `luc lock` form reads the same bounded `[registry.dependencies]`
declaration enforced during publication, unlocks the session once, recursively
fetches canonical catalogs and signed LRS2 metadata with separately minted and
revoked repository-bound `package:read` credentials, and uses the shared bounded
backtracking solver. It atomically writes canonical graph-complete lock v3 only
after every candidate declaration authenticates. It does not fetch source bodies;
the lock pins their signed SHA-256 digests for subsequent verified installation.
For this first trust profile, one explicit ML-DSA-65 public key must authenticate
the complete graph. Cross-publisher trust maps remain pending; transport uses the
verified production HTTPS profile when the lock origin is `https://pkg.luciaos.com`.

`luc sync` requires that graph-complete v3 lock and revalidates every current
manifest root against it before creating any project state. Online mode unlocks
one session, mints a separate bounded read credential for each locked repository,
downloads each exact release, verifies its LRS2 signature,
publisher-key fingerprint, source digest, commit, compiler identity and signed
dependency declaration, then reconciles immutable LRP1 cache bytes. Offline mode
performs no credential read and no network request; it applies the same checks to
the cache. Both modes validate the Git graph and source manifest before checkout.

All packages are first materialized in a private staging generation named by the
SHA-256 digest of `luc.lock`. luc writes only its marked block inside each checked-out
package's `[dependencies]`, wiring signed transitive dependencies by compiler package
name and sibling-relative path. It then atomically publishes the whole generation
and atomically updates the root manifest with only its declared roots. Repeated sync
of the same lock replaces that deterministic generation with freshly verified bytes
without changing the resulting manifest. A project remains buildable after moving
the complete tree, and a relocated shared cache can seed a fresh offline project.
Validation, download, checkout, or cache failures leave `luce.toml` unchanged; a
successfully verified cache artifact may remain after a later failure. The current
single-key trust profile deliberately rejects graphs requiring different publishers.

`luc verify-release <metadata> <signature> <trusted-key> <source>` verifies local
LRS1 or LRS2 metadata with native ML-DSA-65 and binds the exact source bytes with SHA-256.
The signature and public key are raw binary (3309 and 1952 bytes). Metadata is
bounded to 24,576 bytes and source input to 64 MiB for this buffered command.
Paths are relative to the working directory; no project manifest is required.
It performs no network requests, extraction, installation or file writes.
The supplied key must already be trusted: success does not prove origin ownership,
publisher authorization, freshness or that the release matches a project request.
Remote installation transport is implemented; registry publisher-key distribution,
rotation/revocation and multi-publisher trust policy remain explicit unfinished work.
Add `--locked` after the four paths to require an existing project and `luc.lock`:
the signed origin, package, version, SHA-256 source digest and compiler must match
the lock. Project discovery walks upward from the current directory; input paths
still refer to the current directory. Missing/malformed locks and mismatches fail
without writes. Lock v1 does **not** pin a Git commit or toolchain version; this
check does not claim those protections, freshness, or publisher authorization.
Lock v2 requires `commit` (40 lowercase hex digits) and `toolchain` (numeric
semantic version) on every package. Both `verify-release --locked` and
`checkout-release --locked` enforce these against signed metadata. A version string
does not yet pin the compiler executable's content; binary toolchain pinning remains.
Lock v3 additionally requires LRS2, matching compiler package identity and signed
dependency declarations, plus the SHA-256 fingerprint of the exact public key
that performed verification. Its decoder validates the complete exact dependency
graph before the command can use an entry. The fingerprint records an independently
trusted key; the lock does not make an untrusted downloaded key authoritative.
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
