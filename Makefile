###--INIT--#############################################################################################################

# `make init <name>` turns the template into a project named <name>: renames the packages, rewrites every reference,
# drops this section and the script, then syncs the environment.
init:
	uv run ./scripts/init.py $(filter-out $@,$(MAKECMDGOALS))

# Lets the name after `init` pass as an argument instead of failing as an unknown target. Goes with the section.
%:
	@:

########################################################################################################################

###--CODE--#############################################################################################################

format:
	uv run ruff check --fix && uv run ruff format

lint:
	uv run ruff check && uv run ruff format --check && uv run mypy && uv run pyright

########################################################################################################################

###--TESTS--############################################################################################################

test:
	uv run pytest

########################################################################################################################

###--HOOKS--############################################################################################################

# Install source checks and Conventional Commit validation from the shared configuration.
install-hooks:
	uv run pre-commit install --install-hooks

########################################################################################################################

###--DEPENDENCIES--#####################################################################################################

# Upgrades every dependency to its latest release and raises the `>=` floors in `pyproject.toml` to match.
bump-deps:
	uv run ./scripts/bump_deps.py

########################################################################################################################

###--VERSION--#########################################################################################################

bump:
	@test -n "$(VERSION)" || { echo "usage: make bump VERSION=x.y.z"; exit 2; }
	uv version "$(VERSION)"
	uv lock

version:
	@uv version --short

########################################################################################################################
