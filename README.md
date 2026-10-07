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
| `luc test [--diagnostic]` | runs the tests of every module of the project, imported or not |
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

`luc test` hands the `.luc` modules under the source root to `luce test --package` and the
`.lucb` modules to `luce-base test --package`, so a package that mixes the two runs both and
ends with one total (`Luce and Base together: 5 passed, 0 failed`). Each run starts from the
entry when it is in that language, and otherwise from the first module, the way pytest
collects every test file without a starting point: a library needs no module named after
the package to be tested. If the sources declare tests and no run reported any, `luc test`
says so and fails rather than passing on `0 passed`.

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
