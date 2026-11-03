# devkit

<!-- template:start -->
A template for a Python project: the coding rules, the tests that gate them, and the tooling configuration that
enforces the rest. Clone it, run `make init <name>`, and start writing code under the same rules as every other
project.
<!-- template:end -->

## Layout

```
AGENTS.md                    # agent instructions; points at the coding guide
.pre-commit-config.yaml      # source checks and Conventional Commit validation
docs/coding.md               # house style and conventions beyond standard tooling
docs/tracing.md              # Logfire tracing, decorators, and context propagation
docs/database.md             # PostgreSQL and Alembic template
.zed/settings.json           # Zed: ruff, pyright and pylsp from the project venv, format on save
Makefile                     # format, lint, test, install-hooks, bump-deps, bump, version
pyproject.toml               # ruff, mypy, pyright (strict) and pytest configuration
scripts/bump_deps.py         # raises the `>=` floors in pyproject.toml to the installed versions
src/
  devkit/                    # the package
    tracing/                 # Logfire tracing helpers
    types/                   # shared Pydantic entity and UTC datetime types
    db/                      # async PostgreSQL template
  devkit_tests/
    conventions/             # the convention gates: parse every module and fail on a broken rule
```

## Commands

```sh
uv sync                      # create .venv with the lint and test groups
make format                  # ruff --fix and ruff format
make lint                    # ruff check, ruff format --check, mypy, pyright
make test                    # pytest with readable TestDox output and convention gates
make install-hooks           # install pre-commit and commit-msg hooks
make bump-deps               # upgrade every dependency and rewrite the floors in pyproject.toml
make bump VERSION=x.y.z      # set the project version and refresh the lockfile
```

Run `make install-hooks` once per clone. The pre-commit hook runs `make format lint test`; if formatting changes files,
review and stage them before retrying the commit. The commit-msg hook requires Conventional Commits, for example
`fix: handle empty input` or `feat(parser): support quoted values`. Strict validation also rejects merge and fixup messages.

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

## Tracing

The package includes Logfire helpers for logs, spans, sync and async decorators, and portable trace contexts.
See [docs/tracing.md](docs/tracing.md) for configuration, examples, and lifecycle behavior.

## Database

The [PostgreSQL template](docs/database.md) provides typed settings, an async SQLAlchemy session boundary,
a declarative base, and Alembic migrations configured in `pyproject.toml`.

## The convention gates

`src/devkit_tests/conventions/` walks the package, the tests and `scripts/`, and checks the mechanical conventions summarized in
`docs/coding.md`. `source.py` holds the shared parsing helpers; each `test_*.py` module holds
one family of rules, and `test_gates.py` proves each gate fires on a fixture that breaks it, so a gate that stops
checking anything fails too.
