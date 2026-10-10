# luc

The project tool for [Luce](https://luce.luciaos.com) and Luce Base. One command
creates, builds, runs, tests and formats a project, fetches its dependencies from
[pkg.luciaos.com](https://pkg.luciaos.com), and installs applications. It is installed with the Luce compiler.

```sh
luc new hello --tool && cd hello    # a terminal program
luc run                             # build it and run it
luc add dymokomi/luce-json          # use a package from the registry
```

## Projects

A project is a directory with a `package.prisma` that says what it is:

```text
#prisma 4.0
def package "hello" {
    str owner = "dymokomi"
    str version = "0.1.0"
    str kind = "tool"
    str language = "luce"
    str entry = "src/main.luc"
}
```

`kind` is one of three things, and it decides what `luc` builds and installs:

| Kind | What it is | Made by | Installed as |
| --- | --- | --- | --- |
| `package` | a library other projects add | `luc new <dir> --package` | not installable; used with `luc add` |
| `tool` | a program run in a terminal | `luc new <dir> --tool` (the default) | a command on your PATH |
| `application` | a windowed desktop program | `luc new <dir> --application` | `Name.app` on macOS, a desktop entry on Linux |

A package published to the registry can also say what it is for and how it may be used:
`str description = "..."` (one line), `str license = "MIT OR Apache-2.0"` (an SPDX
expression) and `str readme = "README.md"`; the registry shows them on the package's page.
Each property is set once in its element: luc refuses a repeated one at its line and column.

`luc init` does the same as `luc new` in the current directory. Every project file
is described in [luce-pkg/docs/PACKAGE_PRISMA.md](https://github.com/dymokomi/luce-pkg/blob/main/docs/PACKAGE_PRISMA.md).

## Building and running

| Command | Does |
| --- | --- |
| `luc build [--release] [--diagnostic]` | builds into `build/<name>`; an application also gets `build/Name.app` |
| `luc run [--release] [--diagnostic] [-- args]` | builds and runs the program |
| `luc test [--diagnostic] [--jobs N]` | runs the `test` blocks of every module, imported or not, and every test program under `tests/`, N programs at a time |
| `luc test --list` | names the test programs and the test blocks without running them |
| `luc check` | type-checks without building |
| `luc fmt [--check]` | formats the sources |
| `luc clean [cache]` | removes `build/`, or only its cache |
| `luc run <task>` | runs a named task from `package.prisma`, after the tasks it depends on |

`--diagnostic` builds with the compiler's diagnostic profile (`--profile diagnostic`): storage
the program has not written yet (`---`, `new T[n] ---`, `memory.allocate`, `memory.frame`)
reads as `0xAA`, and the allocators trap on a double free or a write after free, so a
half-initialised value or a use after free fails the same way on every run. The build goes
to `build/<name>-diagnostic`, beside the normal one, and is never bundled as an application.
For a Luce project, `luc test --diagnostic` runs the tests as a built program, since the
interpreter has no profile.

### Testing

`luc test` is the one test command of every package. It runs two kinds of test, the way
pytest collects both test functions and test files without being told where they are:

- **`test` blocks** in the modules under the source root and in their test fragments
  (`tests/<module>/TESTS`). `luc test` hands the `.luc` modules to `luce test --package` and
  the `.lucb` modules to `luce-base test --package`, so a package that mixes the two runs
  both. Each run starts from the entry when it is in that language, and otherwise from the
  first module, so a library needs no module named after the package to be tested; a run
  that finds no test block shows nothing, and the total line counts both. A run that
  fails without reporting a failed test, a module that does not build or a crash, is shown
  as `FAIL  the Base test blocks: ...` (or Luce) and counts as one failure in the total, as
  do sources that declare tests when no run reported any, rather than passing on
  `0 passed`.
- **Test programs**: every directory `tests/<name>/` that holds a `main.luc` or `main.lucb`
  (with `pub func main`). It suits a check that needs a process of its own: fixtures read
  from disk, a server, a window or the GPU, a comparison with another tool. `luc test` builds
  each with the package's dependencies and runs it from the package root, as `luc test`
  itself runs, with `LUC_TEST_DIR` naming the program's own directory for the files beside
  it. It counts as passed when it exits 0 and, if its directory has a file named
  `expected`, when its standard output is exactly that file; one that exits 0 after
  printing a line `skip: reason` (no GPU here, say) counts as skipped. A program may import
  any module of the package, private ones too, as code under `src/` does, and the package's
  dependencies; one with a `package.prisma` of its own is a package of its own, with
  dependencies only it needs, and imports the package's public modules as any dependent
  does. Each runs with `HOME` and `LUC_HOME` pointing at a fresh scratch directory that is removed afterwards, so no
  test touches your settings, libraries, crash reports or keychain, and with `LUCE` and
  `LUCE_BASE` naming the compilers `luc test` uses. luc builds each into
  `build/luc-test/<name>/`; `build/tests/<name>/` is the program's own scratch space, which
  luc makes a directory (replacing a file left there) and otherwise leaves to the program.
  A directory under `tests/` without a `main`, or with an `ORDER` or `TESTS` file, is not a
  program and stays as it is.

The test programs build and run in parallel, `--jobs N` at a time, beside the test-block
runs. The default is half the processors (8 on a 16-core machine): each build is itself
parallel inside the compiler, so half as many builds as processors keeps every core busy
without each build waiting on the others. A build or run beside others gets `LUCE_BASE_JOBS`
set to its share, the processors divided by the programs running at once, and the test-block
runs get the same share; set `LUCE_BASE_JOBS` yourself and luc leaves it as it is. Whatever
order the programs finish in, they are reported in the order of their names, so the output
of two runs can be compared line by line.

```text
ok    parses a header
ok    rejects a bad header
2 passed
ok    tests/roundtrip
skip  tests/gpu: no Metal device
FAIL  tests/vectors
      exit status 1
      case 17: expected 3f, got 3e
total: 3 passed, 1 failed, 1 skipped (2 test blocks, 3 programs)
```

A failed program is shown with the end of its output. A package with no test at all, no
`test` block and no test program, fails with "no tests found".

A task is a `def task "name" { str cmd = "..." }` entry, optionally with `str[]
depends`. `luc run <task> -- a b` passes `a b` through to the command.

## Dependencies

| Command | Does |
| --- | --- |
| `luc add owner/name` | adds a registry package with no version (its newest release) and locks it |
| `luc add owner/name@^1.2.0` | the same, held to a caret requirement (or an exact version) |
| `luc add ../path` | adds a package checked out beside this one, for working on both |
| `luc remove name` | removes a dependency |
| `luc lock` | resolves every dependency against the registry and writes `luc.lock` |
| `luc sync [--offline]` | makes `.luc/deps/` match `luc.lock`, downloading what is missing |

`luc.lock` records each package's exact version and the SHA-256 of its source. A
build syncs automatically, so `luc add` followed by `luc run` just works. Downloads
are cached in `~/.luce/cache`; with `--offline` nothing is fetched, and a cached
package whose checksum differs from the lock is refused. Registry access needs no
account.

## Installing applications and tools

| Command | Does |
| --- | --- |
| `luc install owner/name[@version]` | downloads, builds and installs a tool or application, without its development paths |
| `luc install name` | the same for the one registry package called `name`; when several owners publish that name, luc lists them and asks for `owner/name` |
| `luc install owner/name --dev` | the same with the whole release tree: tests, dev and every declared development path |
| `luc update [owner/]name` | brings an installed tool or application to its newest version, replacing the installed one |
| `luc list` | shows what is installed |
| `luc uninstall name` | removes it, including whatever was placed for the desktop |

An install builds a working program, not a development checkout. It leaves out each
package's development paths, for the package itself and for every dependency: `tests/`,
`dev/`, and whatever the package lists in `str[] development` in package.prisma. Keep
tests and test data under `tests/`.

An application installs where the system keeps applications and opens like any other
program:

| System | The application | Found by |
| --- | --- | --- |
| macOS | `/Applications/Name.app` (`~/Applications` when you cannot write to `/Applications`) | Finder, Launchpad, Spotlight |
| Linux | `~/.local/share/luce/apps/Name.AppDir` | a desktop entry in `~/.local/share/applications` |
| Windows | `%LOCALAPPDATA%\Programs\Name` | a Start Menu shortcut |

A tool installs under `~/.luce/apps/<name>/<version>/`, which for an application only
records what was placed. Either way its command is linked into `~/.luce/bin`, which the
Luce installer puts on your PATH. luc never replaces an application of the same name that
it did not install. Installing builds from source, so luc reports each step: fetching,
compiling (with a running time), and where the result went.

An application may ship an `install.luc` that runs in the Luce sandbox and prints
extra `copy` and `link` steps; the format is in the package.prisma document above.

## Configuration

| Variable | Meaning |
| --- | --- |
| `LUCE_BASE`, `LUCE` | the compilers to use instead of the ones on your PATH |
| `LUC_APPLICATIONS` | where applications install instead of the system's place |
| `LUC_START_MENU` | Windows: where the Start Menu shortcut goes |
| `LUC_HOME` | where installs and commands live (default `~/.luce`) |
| `LUC_CACHE` | the download cache (default `~/.luce/cache`) |
| `LUC_REGISTRY` | another registry, for testing (default `https://pkg.luciaos.com`) |

`luc update` reinstalls the latest `luce`, `luce-base` and `luc` together, through the
installer at luce.luciaos.com, into the release tree this `luc` runs from (following a link
to it), so a toolchain installed somewhere else stays there; installed applications stay.
The installer edits the shell's startup file (the user PATH on Windows) only for its default
place, `~/.local/luce` (`%LOCALAPPDATA%\luce`) with `~/.luce`, so an update in another tree, or with `LUC_HOME` set elsewhere, leaves
every startup file alone; its `env` file (`<tree>/env`) puts that tree's `bin` and
`LUC_HOME/bin` on PATH and keeps `LUC_HOME` set. `luc update --dry-run` prints the
installer's command instead of running it; a `LUC_HOME` other than `~/.luce` is named in
it, so it installs the same way from a shell that does not have it set.

## License

MIT OR Apache-2.0.
