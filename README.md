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
luc remove <name>         remove a dependency from luce.toml
luc build [--release]     build the project into build/<name>
luc run [--release]       build and run the project
luc run <task>            run a named [tasks] workflow from luce.toml
luc test                  build and run the project's tests
luc check                 type-check without producing a binary
luc fmt [--check]         format the project's sources
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
dev  = "luc run"
lint = "luc fmt --check"
ci   = "luc fmt --check && luc test"
```

`luc run <name>` runs a `[tasks]` entry through the system shell, so `&&`, pipes and redirects
work. The build cache is the project's own `build/.cache`, cleared by `rm -rf build`.

## Build and test

`./build.sh` builds luc with the Base commit pinned in `bootstrap/BASE` (fetched into an
isolated `build/luce-base`); `LUCE_BASE_COMPILER=/path/to/luce-base ./build.sh` uses an
existing compiler instead. `./test.sh` runs the gate.

## Not yet (next slices)

Task dependency graphs + object task form + arg passthrough to tasks,
task input/output caching, a built-in cross-platform shell, workspaces, an ephemeral tool
runner (`luc x`) and shell completions.

## License

Dual-licensed under Apache-2.0 or MIT, at your option.
