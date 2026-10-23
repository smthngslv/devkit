#!/usr/bin/env -S uv run --active --with tomlkit python

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Any, Final, cast

import tomlkit
import tomlkit.items

__all__: Final[tuple[str, ...]] = ()


def uv_sync() -> None:
    print("Running `uv sync --active --all-extras --all-groups --upgrade`...")
    sync_result: Final[subprocess.CompletedProcess[str]] = subprocess.run(
        args=("uv", "sync", "--active", "--all-extras", "--all-groups", "--upgrade"),
        stdout=sys.stdout,
        stderr=sys.stderr,
        check=False,
        text=True,
    )

    if sync_result.returncode != 0:
        message: Final[str] = "Command `uv sync` failed."
        raise RuntimeError(message)


def get_packages() -> dict[str, str]:
    print("Running `uv pip list --format json`...")
    result: Final[subprocess.CompletedProcess[str]] = subprocess.run(
        args=("uv", "pip", "list", "--format", "json"), capture_output=True, check=False, text=True
    )

    if result.returncode != 0:
        message: Final[str] = f"Command `uv pip list` failed:\n{result.stdout}\n{result.stderr}"
        raise RuntimeError(message)

    return {package["name"]: package["version"] for package in json.loads(result.stdout)}


def get_updated_package(package: str, versions: Mapping[str, str]) -> str:
    parts: Final[list[str]] = package.split(sep=">=", maxsplit=1)
    # Name can contain extras. Update only `>=`, do not update others.
    return f"{parts[0]}>={versions[parts[0].split(sep='[', maxsplit=1)[0]]}" if len(parts) != 1 else package


def update_packages(array: tomlkit.items.Array, versions: Mapping[str, str]) -> bool:
    is_updated: bool = False
    index: int
    package: Any
    for index, package in enumerate(cast("list[Any]", array)):
        if not isinstance(package, str):
            continue

        try:
            updated_package: str = get_updated_package(package, versions)

        except KeyError:
            print(f"Warning: package `{package}` not found in installed packages.", file=sys.stderr)
            continue

        if updated_package != package:
            print(f"Updating package `{package}` to `{updated_package}`...")
            array[index] = updated_package
            is_updated = True

        else:
            print(f"Package `{package}` already up-to-date!")

    return is_updated


def update_pyproject(pyproject: tomlkit.TOMLDocument, versions: Mapping[str, str]) -> bool:
    is_updated: bool = False

    if "project" in pyproject and isinstance(pyproject["project"], tomlkit.items.Table):
        project: Final[tomlkit.items.Table] = pyproject["project"]

        if "dependencies" in project and isinstance(project["dependencies"], tomlkit.items.Array):
            print("Updating `dependencies`...")
            is_updated |= update_packages(project["dependencies"], versions)

        if "optional-dependencies" in project and isinstance(project["optional-dependencies"], tomlkit.items.Table):
            print("Updating `optional-dependencies`...")
            name: str
            group: Any
            for name, group in project["optional-dependencies"].items():
                if isinstance(group, tomlkit.items.Array):
                    print(f"Updating `{name}`...")
                    is_updated |= update_packages(group, versions)

    if "dependency-groups" in pyproject and isinstance(pyproject["dependency-groups"], tomlkit.items.Table):
        print("Updating `dependency-groups`...")
        for name, group in pyproject["dependency-groups"].items():
            if isinstance(group, tomlkit.items.Array):
                print(f"Updating `{name}`...")
                is_updated |= update_packages(group, versions)

    return is_updated


def main() -> int:
    pyproject_path: Final[Path] = Path("pyproject.toml")
    if not pyproject_path.exists():
        print("File `pyproject.toml` not found in current directory.", file=sys.stderr)
        return 1

    try:
        uv_sync()

    except RuntimeError as exception:
        print(exception, file=sys.stderr)
        return 1

    try:
        versions: Final[dict[str, str]] = get_packages()

    except RuntimeError as exception:
        print(exception, file=sys.stderr)
        return 1

    file: IO[str]
    with pyproject_path.open() as file:
        pyproject: Final[tomlkit.TOMLDocument] = tomlkit.load(file)

    if update_pyproject(pyproject, versions):
        with pyproject_path.open(mode="wt") as file:
            tomlkit.dump(pyproject, file)

        print("Updated pyproject.toml with new minimum versions.")

    else:
        print("No version changes needed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
