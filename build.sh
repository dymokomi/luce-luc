#!/bin/sh
# Build luc with the packages checked out beside this one, as they are (CI checks out main;
# a missing one: `python3 ../luce-base/tools/checkout_main.py .`). The Base compiler is
# ../luce-base's, built there when it is missing or older than its sources;
# LUCE_BASE_COMPILER selects an already-built compiler instead.
set -eu
cd "$(dirname "$0")"
mkdir -p build
if [ -n "${LUCE_BASE_COMPILER:-}" ]; then
    case "$LUCE_BASE_COMPILER" in /*) base=$LUCE_BASE_COMPILER ;; *) base=$PWD/$LUCE_BASE_COMPILER ;; esac
    [ -x "$base" ] || { echo "FAIL: LUCE_BASE_COMPILER is not executable: $base"; exit 1; }
else
    if [ ! -d ../luce-base ]; then
        echo "FAIL: luc builds with the luce-base checkout beside it; clone it and the packages:"
        echo "  git clone https://github.com/dymokomi/luce-base ../luce-base && python3 ../luce-base/tools/checkout_main.py ."
        exit 1
    fi
    base=../luce-base/build/luce-base
    if [ ! -x "$base" ] || [ -n "$(find ../luce-base/src ../luce-base/runtime ../luce-base/bootstrap -newer "$base" -type f | head -n 1)" ]; then
        (cd ../luce-base && ./build.sh > /dev/null)
    fi
fi
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) out=build/luc.exe ;; *) out=build/luc ;; esac
"$base" build src/main.lucb --native -o "$out"
echo "built $out"
