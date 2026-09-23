#!/bin/sh
# Build luc with the exact commits in bootstrap/. Missing package siblings are fetched by
# commit from their public repositories; an existing checkout is never changed and must
# already be at the pinned revision. An isolated build/luce-base checkout keeps the compiler
# build independent of any working tree. LUCE_BASE_SOURCE selects the Base repository
# (default ../luce-base); LUCE_BASE_COMPILER selects an already-built compiler.
set -eu
cd "$(dirname "$0")"
mkdir -p build
for dependency in STD PKG CRYPTO GIT HTTP_CLIENT TLS COMPRESS PRISM; do
    case "$dependency" in STD) repo=luce-std ;; PKG) repo=luce-pkg ;; CRYPTO) repo=luce-crypto ;; GIT) repo=luce-git ;; HTTP_CLIENT) repo=luce-http-client ;; TLS) repo=luce-tls ;; COMPRESS) repo=luce-compress ;; PRISM) repo=luce-prism ;; esac
    expected=$(cat "bootstrap/$dependency")
    actual=$(git -C "../$repo" rev-parse HEAD 2>/dev/null || true)
    if [ "$actual" != "$expected" ]; then
        [ ! -e "../$repo" ] || { echo "FAIL: ../$repo must be checked out at $expected"; exit 1; }
        git init -q "../$repo"
        git -C "../$repo" remote add origin "https://github.com/dymokomi/$repo.git"
        git -C "../$repo" fetch -q --depth 1 origin "$expected"
        git -C "../$repo" checkout -q --detach FETCH_HEAD
        actual=$(git -C "../$repo" rev-parse HEAD)
        [ "$actual" = "$expected" ] || { echo "FAIL: fetched ../$repo at $actual, expected $expected"; exit 1; }
    fi
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
        # Base's own package depends on luce-std beside it, at the commit Base pins
        rm -rf build/luce-std
        git init -q build/luce-std
        git --git-dir=build/luce-std/.git fetch -q --depth 1 "${LUCE_STD_SOURCE:-https://github.com/dymokomi/luce-std.git}" "$(cat build/luce-base/bootstrap/STD)"
        git -C build/luce-std checkout -q --detach FETCH_HEAD
        (cd build/luce-base && ./build.sh > /dev/null)
    fi
fi
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) out=build/luc.exe ;; *) out=build/luc ;; esac
"$base" build src/luc/main.lucb --native -o "$out"
echo "built $out"
