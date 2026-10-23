# devkit

A template for a Python project: the coding rules, the tests that gate them, and the tooling configuration that
enforces the rest. Copy it, rename the packages, and start writing code under the same rules as every other project.

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
  devkit/                    # the package; empty in the template
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

## Starting a project from this template

1. Copy the repository and rename `src/devkit` and `src/devkit_tests` to `<package>` and `<package>_tests`.
2. Replace `devkit` in `pyproject.toml`: `name`, `packages.find.include`, `per-file-ignores`, `known-first-party`
   and `testpaths`.
3. Replace `devkit` in `src/<package>_tests/conventions/source.py` (the two imports) and `devkit_tests` in the
   `from devkit_tests.conventions import source` line of every gate.
4. Replace `devkit_tests` in `.claude/CLAUDE.md` and `.claude/coding.md`.
5. Run `uv sync` and `make format lint test`.

## The convention gates

`src/devkit_tests/conventions/` walks the package, the tests and `scripts/`, and fails on any file breaking a rule
marked `[gated]` in `.claude/coding.md`. `source.py` holds the shared parsing helpers; each `test_*.py` module holds
one family of rules, and `test_gates.py` proves each gate fires on a fixture that breaks it, so a gate that stops
checking anything fails too.
