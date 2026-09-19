#!/bin/sh
# The luc gate: build luc, then drive a throwaway project through its commands. Set
# LUCE_BASE_COMPILER (or have luce-base on PATH) to the Base compiler that builds both.
set -eu
cd "$(dirname "$0")"
base=${LUCE_BASE_COMPILER:-../luce-base/build/luce-base}
[ -x "$base" ] || base=$(command -v luce-base 2>/dev/null || true)
[ -n "$base" ] && [ -x "$base" ] || { echo "FAIL: no luce-base compiler (set LUCE_BASE_COMPILER)"; exit 1; }
LUCE_BASE_COMPILER="$base" ./build.sh > /dev/null
luc="$PWD/build/luc"
[ "$("$luc" --version)" = "luc 0.2.0" ] || { echo "FAIL: version"; exit 1; }
export LUCE_BASE="$base"
# scaffolding: a new app builds and runs; a new package checks
scaff="build/scaffold"
rm -rf "$scaff"; mkdir -p "$scaff"
( cd "$scaff" && "$luc" new demo ) > /dev/null || { echo "FAIL: new app"; exit 1; }
[ -f "$scaff/demo/luce.toml" ] && [ -f "$scaff/demo/src/main.lucb" ] || { echo "FAIL: new app layout"; exit 1; }
[ "$( cd "$scaff/demo" && "$luc" run )" = "hello from demo" ] || { echo "FAIL: scaffolded app run"; exit 1; }
( cd "$scaff" && "$luc" new mylib --package ) > /dev/null || { echo "FAIL: new package"; exit 1; }
[ -f "$scaff/mylib/src/mylib/mylib.lucb" ] || { echo "FAIL: new package layout"; exit 1; }
( cd "$scaff/mylib" && "$luc" check ) || { echo "FAIL: package check"; exit 1; }
( cd "$scaff/demo" && "$luc" init ) 2>/dev/null && { echo "FAIL: init over an existing manifest should refuse"; exit 1; } || true
rm -rf "$scaff"
work="build/luctest"
rm -rf "$work"; mkdir -p "$work/src"
printf '[package]\nname = "hello"\nlanguage = "luce-base"\n\n[tasks]\ngreet = "echo hi from a task"\nchain = "echo a && echo b"\n' > "$work/luce.toml"
printf 'pub func main(arguments: str[]) -> i32:\n    print("ok run")\n    return 0\n' > "$work/src/main.lucb"
export LUCE_BASE="$base"
( cd "$work" && "$luc" check ) || { echo "FAIL: check"; exit 1; }
[ "$( cd "$work" && "$luc" run )" = "ok run" ] || { echo "FAIL: run app"; exit 1; }
[ "$( cd "$work" && "$luc" run greet )" = "hi from a task" ] || { echo "FAIL: run task"; exit 1; }
[ "$( cd "$work" && "$luc" run chain )" = "$(printf 'a\nb')" ] || { echo "FAIL: shell task"; exit 1; }
( cd "$work" && "$luc" run missing ) 2>/dev/null && { echo "FAIL: missing task should error"; exit 1; } || true
[ -d "$work/build/.cache" ] || { echo "FAIL: default cache is not project-local build/.cache"; exit 1; }
rm -rf "$work"
echo "ok luc: new/init scaffolding, version, check, run, tasks, shell tasks, and a project-local cache"
