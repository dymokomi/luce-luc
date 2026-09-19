#!/bin/sh
# Build luc with the exact Base commit in bootstrap/BASE. An isolated build/luce-base checkout
# keeps the build independent of any working tree. LUCE_BASE_SOURCE selects the repository
# (default ../luce-base); LUCE_BASE_COMPILER selects an already-built compiler.
set -eu
cd "$(dirname "$0")"
mkdir -p build
for dependency in PKG CRYPTO GIT HTTP_CLIENT TLS COMPRESS; do
    case "$dependency" in PKG) repo=luce-pkg ;; CRYPTO) repo=luce-crypto ;; GIT) repo=luce-git ;; HTTP_CLIENT) repo=luce-http-client ;; TLS) repo=luce-tls ;; COMPRESS) repo=luce-compress ;; esac
    expected=$(cat "bootstrap/$dependency")
    actual=$(git -C "../$repo" rev-parse HEAD 2>/dev/null || true)
    [ "$actual" = "$expected" ] || { echo "FAIL: ../$repo must be checked out at $expected"; exit 1; }
done
if [ -n "${LUCE_BASE_COMPILER:-}" ]; then
    case "$LUCE_BASE_COMPILER" in /*) base=$LUCE_BASE_COMPILER ;; *) base=$PWD/$LUCE_BASE_COMPILER ;; esac
    [ -x "$base" ] || { echo "FAIL: LUCE_BASE_COMPILER is not executable: $base"; exit 1; }
else
    revision=$(cat bootstrap/BASE)
    [ "${#revision}" -eq 40 ] || { echo "FAIL: bootstrap/BASE must name a full commit SHA"; exit 1; }
    source=${LUCE_BASE_SOURCE:-../luce-base}
    base=build/luce-base/build/luce-base
    if [ ! -x "$base" ] || [ "$(git -C build/luce-base rev-parse HEAD 2>/dev/null || true)" != "$revision" ]; then
        rm -rf build/luce-base
        git init -q build/luce-base
        git --git-dir=build/luce-base/.git fetch -q --depth 1 "$source" "$revision"
        git -C build/luce-base checkout -q --detach FETCH_HEAD
        (cd build/luce-base && ./build.sh > /dev/null)
    fi
fi
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) out=build/luc.exe ;; *) out=build/luc ;; esac
"$base" build src/luc/main.lucb --native -o "$out"
echo "built $out"
