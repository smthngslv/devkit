# devkit

<!-- template:start -->
A template for a Python project: the coding rules, the tests that gate them, and the tooling configuration that
enforces the rest. Clone it, run `make init <name>`, and start writing code under the same rules as every other
project.
<!-- template:end -->

## Layout

```
.claude/
  CLAUDE.md                  # project instructions for AI assistants; points at the rules
  coding.md                  # the coding rules: design, correctness, style, practice
.zed/settings.json           # Zed: ruff, pyright and pylsp from the project venv, format on save
Makefile                     # format, lint, test, install-hooks, bump-deps, bump, version
pyproject.toml               # ruff, mypy, pyright (strict) and pytest configuration
scripts/bump_deps.py         # raises the `>=` floors in pyproject.toml to the installed versions
src/
  devkit/                    # the package
  devkit_tests/
    conventions/             # the convention gates: parse every module and fail on a broken rule
```

## Commands

```sh
uv sync                      # create .venv with the lint and test groups
make format                  # ruff --fix and ruff format
make lint                    # ruff check, ruff format --check, mypy, pyright
make test                    # pytest, which includes the convention gates
make install-hooks           # pre-commit hook running `make lint test`
make bump-deps               # upgrade every dependency and rewrite the floors in pyproject.toml
make bump VERSION=x.y.z      # set the project version and refresh the lockfile
```

<!-- template:start -->
## Starting a project from this template

```sh
git clone <this repository> your_project
cd your_project
make init your_project
```

`scripts/init.py` turns the template into a project named `your_project`: it renames `src/devkit` and
`src/devkit_tests`, rewrites every `devkit` reference in the rules, the configuration, the gates and this file,
drops the template-only sections (this one, and the `init` section of the Makefile), removes itself, and runs
`uv sync`. The name must be a package name: lowercase letters, digits and underscores. Nothing in git is
touched, so review the result with `git status`, point `origin` at your own repository and commit.
<!-- template:end -->

## The convention gates

`src/devkit_tests/conventions/` walks the package, the tests and `scripts/`, and fails on any file breaking a rule
marked `[gated]` in `.claude/coding.md`. `source.py` holds the shared parsing helpers; each `test_*.py` module holds
one family of rules, and `test_gates.py` proves each gate fires on a fixture that breaks it, so a gate that stops
checking anything fails too.
