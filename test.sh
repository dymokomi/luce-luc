#!/bin/sh
# The luc gate: build luc, then drive a throwaway project through its commands. Set
# LUCE_BASE_COMPILER (or have luce-base on PATH) to the Base compiler that builds both.
set -eu
cd "$(dirname "$0")"
base=${LUCE_BASE_COMPILER:-../luce-base/build/luce-base}
[ -x "$base" ] || base=$(command -v luce-base 2>/dev/null || true)
[ -n "$base" ] && [ -x "$base" ] || { echo "FAIL: no luce-base compiler (set LUCE_BASE_COMPILER)"; exit 1; }
case "$base" in /*) ;; *) base=$PWD/$base ;; esac   # absolute, so LUCE_BASE survives the cd into a scaffolded project
LUCE_BASE_COMPILER="$base" ./build.sh > /dev/null
luc="$PWD/build/luc"
python3 tests/lock.py "$luc"
"$base" build tests/release_fixture.lucb --native -o build/release-fixture
python3 tests/release.py "$luc" build/release-fixture
[ "$("$luc" --version)" = "luc 0.7.0" ] || { echo "FAIL: version"; exit 1; }
# update/upgrade name the official installers (dry-run so nothing is installed)
[ "$("$luc" update --dry-run | head -1)" = "curl -fsSL https://luce-base.luciaos.com/install.sh | sh" ] || { echo "FAIL: update --dry-run"; exit 1; }
[ "$("$luc" upgrade --dry-run | tail -1)" = "curl -fsSL https://luce.luciaos.com/install.sh | sh" ] || { echo "FAIL: upgrade alias"; exit 1; }
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
# dependencies: an app depends on the scaffolded local package and imports its export
( cd "$scaff" && "$luc" new app1 ) > /dev/null || { echo "FAIL: new app1"; exit 1; }
( cd "$scaff/app1" && "$luc" add ../mylib ) > /dev/null || { echo "FAIL: add"; exit 1; }
grep -q '^mylib = "../mylib"' "$scaff/app1/luce.toml" || { echo "FAIL: dependency not written"; cat "$scaff/app1/luce.toml"; exit 1; }
printf 'import mylib\npub func main(arguments: str[]) -> i32:\n    print(mylib.greeting())\n    return 0\n' > "$scaff/app1/src/main.lucb"
[ "$( cd "$scaff/app1" && "$luc" run )" = "hello from mylib" ] || { echo "FAIL: dependency import/run"; exit 1; }
( cd "$scaff/app1" && "$luc" remove mylib ) > /dev/null || { echo "FAIL: remove"; exit 1; }
grep -q 'mylib =' "$scaff/app1/luce.toml" && { echo "FAIL: dependency not removed"; exit 1; } || true
rm -rf "$scaff"
work="build/luctest"
rm -rf "$work"; mkdir -p "$work/src"
{
  printf '[package]\nname = "hello"\nlanguage = "luce-base"\n\n[tasks]\ngreet = "echo hi from a task"\nchain = "echo a && echo b"\n\n'
  printf '[tasks.first]\ncmd = "echo one"\n\n[tasks.second]\ncmd = "echo two"\ndepends = ["first"]\n\n'
  printf '[tasks.all]\ndescription = "run both"\ncmd = "echo got"\ndepends = ["second", "first"]\n'
} > "$work/luce.toml"
printf 'pub func main(arguments: str[]) -> i32:\n    print("ok run")\n    return 0\n' > "$work/src/main.lucb"
export LUCE_BASE="$base"
( cd "$work" && "$luc" check ) || { echo "FAIL: check"; exit 1; }
[ "$( cd "$work" && "$luc" run )" = "ok run" ] || { echo "FAIL: run app"; exit 1; }
[ "$( cd "$work" && "$luc" run greet )" = "hi from a task" ] || { echo "FAIL: run task"; exit 1; }
[ "$( cd "$work" && "$luc" run chain )" = "$(printf 'a\nb')" ] || { echo "FAIL: shell task"; exit 1; }
( cd "$work" && "$luc" run missing ) 2>/dev/null && { echo "FAIL: missing task should error"; exit 1; } || true
# a task DAG: deps run first (once, in order) and args pass through to the target
[ "$( cd "$work" && "$luc" run all -- X Y )" = "$(printf 'one\ntwo\ngot X Y')" ] || { echo "FAIL: task DAG / passthrough: got [$( cd "$work" && "$luc" run all -- X Y )]"; exit 1; }
[ -d "$work/build/.cache" ] || { echo "FAIL: default cache is not project-local build/.cache"; exit 1; }
# clean cache keeps the binary; a full clean removes build/
( cd "$work" && "$luc" clean cache ) > /dev/null || { echo "FAIL: clean cache"; exit 1; }
[ ! -d "$work/build/.cache" ] && [ -f "$work/build/hello" ] || { echo "FAIL: clean cache should drop the cache but keep the binary"; exit 1; }
( cd "$work" && "$luc" clean ) > /dev/null || { echo "FAIL: clean"; exit 1; }
[ ! -d "$work/build" ] || { echo "FAIL: clean should remove build/"; exit 1; }
rm -rf "$work"
echo "ok luc: new/init, add/remove, task DAG, clean, update, cross-platform tasks, and a project-local cache"
