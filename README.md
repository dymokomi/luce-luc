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

`luc init` does the same as `luc new` in the current directory. Every project file
is described in [luce-pkg/docs/PACKAGE_PRISMA.md](https://github.com/dymokomi/luce-pkg/blob/main/docs/PACKAGE_PRISMA.md).

## Building and running

| Command | Does |
| --- | --- |
| `luc build [--release]` | builds into `build/<name>`; an application also gets `build/Name.app` |
| `luc run [--release] [-- args]` | builds and runs the program |
| `luc test` | builds and runs the project's tests |
| `luc check` | type-checks without building |
| `luc fmt [--check]` | formats the sources |
| `luc clean [cache]` | removes `build/`, or only its cache |
| `luc run <task>` | runs a named task from `package.prisma`, after the tasks it depends on |

A task is a `def task "name" { str cmd = "..." }` entry, optionally with `str[]
depends`. `luc run <task> -- a b` passes `a b` through to the command.

## Dependencies

| Command | Does |
| --- | --- |
| `luc add owner/name` | adds the newest release of a registry package and locks it |
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
| `luc install owner/name[@version]` | downloads, builds and installs a tool or application |
| `luc list` | shows what is installed |
| `luc uninstall name` | removes it, including whatever was placed for the desktop |

Everything installs under `~/.luce/apps/<name>/<version>/`, with commands linked
into `~/.luce/bin` (put it on your PATH). An application is also copied to
`~/Applications` on macOS, or given a desktop entry on Linux, so it opens like any
other program.

An application may ship an `install.luc` that runs in the Luce sandbox and prints
extra `copy` and `link` steps; the format is in the package.prisma document above.

## Configuration

| Variable | Meaning |
| --- | --- |
| `LUCE_BASE`, `LUCE` | the compilers to use instead of the ones on your PATH |
| `LUC_HOME` | where installs and commands live (default `~/.luce`) |
| `LUC_CACHE` | the download cache (default `~/.luce/cache`) |
| `LUC_REGISTRY` | another registry, for testing (default `https://pkg.luciaos.com`) |

`luc update` reinstalls the latest `luce`, `luce-base` and `luc` from luciaos.com.

## License

MIT OR Apache-2.0.
