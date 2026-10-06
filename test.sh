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
# The version luc prints is the one package.prisma declares.
expected=$(sed -n 's/^    str version = "\(.*\)"$/\1/p' package.prisma | head -1)
[ "$("$luc" --version)" = "luc $expected" ] || { echo "FAIL: version"; exit 1; }
# update/upgrade run the official installer into the release tree luc runs from, reached
# through a link as ~/.local/bin/luc would be (dry-run so nothing is installed); a luc
# outside a release tree has nothing to update in place
tree="$PWD/build/release-tree"
rm -rf "$tree"; mkdir -p "$tree/bin" "$tree/share/luce" "$tree/links"
cp "$luc" "$tree/bin/luc"; echo 0.0.0 > "$tree/share/luce/VERSION"; ln -s "$tree/bin/luc" "$tree/links/luc"
real_tree=$(cd "$tree" && pwd -P)
[ "$(env -u LUC_HOME "$tree/links/luc" update --dry-run)" = "curl -fsSL https://luce.luciaos.com/install.sh | LUCE_INSTALL_DIR='$real_tree' sh" ] || { echo "FAIL: update --dry-run"; exit 1; }
[ "$(env -u LUC_HOME "$tree/bin/luc" upgrade --dry-run | tail -1)" = "curl -fsSL https://luce.luciaos.com/install.sh | LUCE_INSTALL_DIR='$real_tree' sh" ] || { echo "FAIL: upgrade alias"; exit 1; }
# a LUC_HOME other than ~/.luce is named in the command, which a fresh shell would not have
[ "$(LUC_HOME="$tree/home" "$tree/links/luc" update --dry-run)" = "curl -fsSL https://luce.luciaos.com/install.sh | LUCE_INSTALL_DIR='$real_tree' LUC_HOME='$tree/home' sh" ] || { echo "FAIL: update --dry-run with LUC_HOME"; exit 1; }
[ "$(LUC_HOME="$HOME/.luce" "$tree/links/luc" update --dry-run)" = "curl -fsSL https://luce.luciaos.com/install.sh | LUCE_INSTALL_DIR='$real_tree' sh" ] || { echo "FAIL: update --dry-run with the default LUC_HOME"; exit 1; }
if "$luc" update --dry-run > /dev/null 2>&1; then echo "FAIL: update outside a release tree"; exit 1; fi
rm -rf "$tree"
# with no LUCE_BASE, the compiler installed beside luc wins over one earlier on the path, so
# an old luce-base built from source never stands in for the release's own
sib="$PWD/build/sibling"
rm -rf "$sib"; mkdir -p "$sib/bin" "$sib/path"
cp "$luc" "$sib/bin/luc"
printf '#!/bin/sh\necho beside\n' > "$sib/bin/luce-base"; printf '#!/bin/sh\necho path\n' > "$sib/path/luce-base"
chmod +x "$sib/bin/luce-base" "$sib/path/luce-base"
( cd "$sib" && env -u LUCE_BASE PATH="$sib/path:$PATH" "$sib/bin/luc" new demo > /dev/null ) || { echo "FAIL: sibling scaffold"; exit 1; }
[ "$( cd "$sib/demo" && env -u LUCE_BASE PATH="$sib/path:$PATH" "$sib/bin/luc" check )" = "beside" ] || { echo "FAIL: luc prefers the luce-base beside it"; exit 1; }
rm "$sib/bin/luce-base"
[ "$( cd "$sib/demo" && env -u LUCE_BASE PATH="$sib/path:$PATH" "$sib/bin/luc" check )" = "path" ] || { echo "FAIL: luc falls back to the path"; exit 1; }
export LUCE_BASE="$base"
# scaffolding: a new app builds and runs; a new package checks
scaff="build/scaffold"
rm -rf "$scaff"; mkdir -p "$scaff"
( cd "$scaff" && "$luc" new demo ) > /dev/null || { echo "FAIL: new app"; exit 1; }
[ -f "$scaff/demo/package.prisma" ] && [ -f "$scaff/demo/src/main.lucb" ] || { echo "FAIL: new app layout"; exit 1; }
[ "$( cd "$scaff/demo" && "$luc" run )" = "hello from demo" ] || { echo "FAIL: scaffolded app run"; exit 1; }
( cd "$scaff" && "$luc" new mylib --package ) > /dev/null || { echo "FAIL: new package"; exit 1; }
[ -f "$scaff/mylib/src/mylib.lucb" ] || { echo "FAIL: new package layout"; exit 1; }
# a hyphenated package name scaffolds a module named by its last word, and checks
( cd "$scaff" && "$luc" new my-kit --package ) > /dev/null || { echo "FAIL: new hyphenated package"; exit 1; }
[ -f "$scaff/my-kit/src/kit.lucb" ] && grep -q 'public = \["kit"\]' "$scaff/my-kit/package.prisma" || { echo "FAIL: hyphenated package layout"; exit 1; }
( cd "$scaff/my-kit" && "$luc" check ) || { echo "FAIL: hyphenated package check"; exit 1; }
( cd "$scaff/mylib" && "$luc" check ) || { echo "FAIL: package check"; exit 1; }
( cd "$scaff/demo" && "$luc" init ) 2>/dev/null && { echo "FAIL: init over an existing manifest should refuse"; exit 1; } || true
# dependencies: an app depends on the scaffolded local package and imports its public module
( cd "$scaff" && "$luc" new app1 ) > /dev/null || { echo "FAIL: new app1"; exit 1; }
( cd "$scaff/app1" && "$luc" add ../mylib ) > /dev/null || { echo "FAIL: add"; exit 1; }
grep -q 'def dependency "mylib"' "$scaff/app1/package.prisma" || { echo "FAIL: dependency not written"; cat "$scaff/app1/package.prisma"; exit 1; }
[ ! -e "$scaff/app1/luce.toml" ] || { echo "FAIL: luce.toml must not be generated"; exit 1; }
printf 'import mylib.mylib\npub func main(arguments: str[]) -> i32:\n    print(mylib.greeting())\n    return 0\n' > "$scaff/app1/src/main.lucb"
[ "$( cd "$scaff/app1" && "$luc" run )" = "hello from mylib" ] || { echo "FAIL: dependency import/run"; exit 1; }
( cd "$scaff/app1" && "$luc" remove mylib ) > /dev/null || { echo "FAIL: remove"; exit 1; }
grep -q 'mylib' "$scaff/app1/package.prisma" && { echo "FAIL: dependency not removed"; exit 1; } || true
rm -rf "$scaff"
work="build/luctest"
rm -rf "$work"; mkdir -p "$work/src"
cat > "$work/package.prisma" <<'PRISMA'
#prisma 4.0
def package "hello" {
    str owner = "dymokomi"
    str version = "0.1.0"
    str kind = "tool"
    str language = "luce-base"
    str entry = "src/main.lucb"
    def task "greet" {
        str cmd = "echo hi from a task"
    }
    def task "chain" {
        str cmd = "echo a && echo b"
    }
    def task "first" {
        str cmd = "echo one"
    }
    def task "second" {
        str cmd = "echo two"
        str[] depends = ["first"]
    }
    def task "all" {
        str description = "run both"
        str cmd = "echo got"
        str[] depends = ["second", "first"]
    }
}
PRISMA
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
# --diagnostic builds with the diagnostic profile into build/<name>-diagnostic, beside the
# normal build: unwritten storage reads as 0xAA, in the program and in its tests
cat > "$work/src/main.lucb" <<'BASE'
pub func main(arguments: str[]) -> i32!:
    let raw = try new u8[4] ---
    print(f"{raw[3]:x}")
    free(raw)
    return 0

test "unwritten storage is filled":
    let raw = try new u8[4] ---
    assert(raw[3] == 0xAA)
    free(raw)
BASE
( cd "$work" && "$luc" build ) > /dev/null || { echo "FAIL: build before a diagnostic build"; exit 1; }
[ "$( cd "$work" && "$luc" run --diagnostic )" = "aa" ] || { echo "FAIL: run --diagnostic"; exit 1; }
[ -f "$work/build/hello-diagnostic" ] && [ -f "$work/build/hello" ] || { echo "FAIL: build --diagnostic must write build/hello-diagnostic beside build/hello"; exit 1; }
[ "$( "$work/build/hello-diagnostic" )" = "aa" ] || { echo "FAIL: build/hello-diagnostic"; exit 1; }
( cd "$work" && "$luc" build --release --diagnostic ) > /dev/null || { echo "FAIL: build --release --diagnostic"; exit 1; }
( cd "$work" && "$luc" test --diagnostic ) | grep -q "1 passed" || { echo "FAIL: test --diagnostic"; exit 1; }
( cd "$work" && "$luc" build --diagnostics ) 2>/dev/null && { echo "FAIL: an unknown build flag must be refused"; exit 1; } || true
( cd "$work" && "$luc" test --release ) 2>/dev/null && { echo "FAIL: an unknown test flag must be refused"; exit 1; } || true
# `luc test` runs the tests of every module of the project the entry imports, module by module
printf 'pub func two() -> i64:\n    return 2\n\ntest "in helper":\n    assert(two() == 2)\n' > "$work/src/helper.lucb"
printf 'import helper\n\npub func main(arguments: str[]) -> i32:\n    _ = arguments\n    return i32(helper.two())\n\ntest "in main":\n    assert(helper.two() == 2)\n' > "$work/src/main.lucb"
[ "$( cd "$work" && "$luc" test )" = "$(printf 'ok    in helper\nok    in main\n2 passed')" ] || { echo "FAIL: luc test runs every module's tests"; exit 1; }
# a module nothing imports has its tests run too; a false `assert` fails its test alone, the
# run goes on, counts the failure and ends with status 1
printf 'test "in an orphan":\n    assert(1 + 1 == 3, "arithmetic")\n\ntest "after the failure":\n    assert(true)\n' > "$work/src/orphan.lucb"
got=$( cd "$work" && "$luc" test ) && { echo "FAIL: luc test with a failing test exited 0"; exit 1; }
[ "$got" = "$(printf 'ok    in helper\nok    in main\nFAIL  in an orphan\n      src/orphan.lucb:2:5: assert failed: 1 + 1 == 3: arithmetic\nok    after the failure\n3 passed\n1 failed')" ] || { echo "FAIL: luc test runs an unimported module's tests: [$got]"; exit 1; }
rm "$work/src/orphan.lucb"
# the same for a Luce project, through the interpreter
[ -n "${LUCE:-}" ] || { [ -x ../luce/build/luce ] && export LUCE="$PWD/../luce/build/luce"; } || true
if [ -n "${LUCE:-}" ]; then
    luce_work="build/lucetest"
    rm -rf "$luce_work"; mkdir -p "$luce_work"
    ( cd "$luce_work" && "$luc" new demo --tool --luce ) > /dev/null || { echo "FAIL: new Luce tool"; exit 1; }
    printf 'test "in main":\n    assert(true)\n' >> "$luce_work/demo/src/main.luc"
    printf 'test "in an orphan":\n    assert(1 + 1 == 3)\n\ntest "after the failure":\n    assert(true)\n' > "$luce_work/demo/src/orphan.luc"
    real_demo=$(cd "$luce_work/demo" && pwd -P)
    got=$( cd "$luce_work/demo" && "$luc" test ) && { echo "FAIL: luc test of a Luce project with a failing test exited 0"; exit 1; }
    [ "$got" = "$(printf 'ok    in main\nFAIL  in an orphan\n      %s/src/orphan.luc:2:5: assert failed\nok    after the failure\n2 passed\n1 failed' "$real_demo")" ] || { echo "FAIL: luc test of a Luce project: [$got]"; exit 1; }
    rm -rf "$luce_work"
fi
# a package may state its license as an SPDX expression; a property set twice is refused
licensed() { awk -v line="    str license = \"$1\"" '{ print } /^    str kind = "tool"$/ { print line }' "$work/package.prisma" > "$work/package.next" && mv "$work/package.next" "$work/package.prisma"; }
licensed "MIT OR Apache-2.0"
( cd "$work" && "$luc" check ) || { echo "FAIL: a license is a package property"; exit 1; }
licensed "MIT"
twice=$( cd "$work" && "$luc" check 2>&1 ) && { echo "FAIL: a property set twice was accepted"; exit 1; }
case "$twice" in *"package.prisma:"*" set twice in one element"*) ;; *) echo "FAIL: a property set twice: [$twice]"; exit 1;; esac
rm -rf "$work"
# registry packages: anonymous add/lock/sync against static release files
# LUCE names the high-level compiler whose sandbox runs install scripts
python3 tests/packages.py "$luc"
echo "ok luc: new/init, add/remove, task DAG, clean, --diagnostic, every module's tests and failures, license, update with LUC_HOME, cross-platform tasks, and a project-local cache"
