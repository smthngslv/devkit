"""Check first-party package import boundaries."""

import ast
import pathlib
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = ("test_package_imports_respect_boundaries",)

_PACKAGE_ROOTS: Final[frozenset[str]] = frozenset({"devkit", "devkit_tests"})


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_package_imports_respect_boundaries(path: pathlib.Path) -> None:
    """Allow child modules but reject object re-exports through an ancestor facade.

    `from devkit import tracing` loads a real subpackage without a root re-export.
    `from devkit import Level` needs a root re-export and may see it unfinished
    while an import in a descendant runs. Object imports from other packages
    must be declared in their export list. Initializers may define exports.
    """
    if path.name == "__init__.py":
        return

    current_package: Final[str | None] = _get_package_name(path)
    if current_package is None:
        return

    offenders: Final[list[str]] = [
        error for node in ast.walk(source.parse(path)) for error in _get_import_errors(node, current_package)
    ]

    assert offenders == [], f"{path} crosses package import boundaries:\n" + "\n".join(offenders)


def _get_import_errors(node: ast.AST, current_package: str) -> list[str]:
    if not isinstance(node, ast.ImportFrom):
        return []

    imported_module: Final[str | None] = _resolve_import_module(node, current_package)
    if imported_module is None:
        return []

    exports: Final[frozenset[str] | None] = _get_exports(imported_module)
    if exports is None:
        return []

    return [
        f"  line {node.lineno}: {imported_module}.{imported.name} uses an ancestor object re-export"
        if _is_parent_package(current_package, imported_module)
        else f"  line {node.lineno}: {imported_module}.{imported.name} is not exported by its package"
        for imported in node.names
        if not _is_child_module(imported_module, imported.name)
        and (_is_parent_package(current_package, imported_module) or imported.name not in exports)
    ]


def _resolve_import_module(node: ast.ImportFrom, current_package: str) -> str | None:
    """Resolve an absolute or relative ``from`` import to its module path."""
    if node.level == 0:
        return node.module

    parts: Final[list[str]] = current_package.split(".")
    if node.level > len(parts):
        return None

    base: Final[list[str]] = parts[: len(parts) - node.level + 1]
    if node.module is not None:
        base.extend(node.module.split("."))

    return ".".join(base)


def _get_package_name(path: pathlib.Path) -> str | None:
    """Find the source package for a repository file or a gate fixture."""
    if path.is_relative_to(source.SCRIPTS_ROOT):
        return None

    parts: tuple[str, ...] = (
        path.relative_to(source.SOURCE_ROOT).parts if path.is_relative_to(source.SOURCE_ROOT) else path.parts
    )
    if parts[0] not in _PACKAGE_ROOTS:
        indices: Final[list[int]] = [index for index, part in enumerate(parts) if part in _PACKAGE_ROOTS]
        if len(indices) == 0:
            return None

        parts = parts[indices[-1] :]

    return ".".join(parts[:-1]) if len(parts) > 1 else None


def _get_exports(package: str) -> frozenset[str] | None:
    """Read explicit object exports from a first-party package initializer."""
    if package.split(".", maxsplit=1)[0] not in _PACKAGE_ROOTS:
        return None

    marker: Final[pathlib.Path] = source.SOURCE_ROOT.joinpath(*package.split("."), "__init__.py")
    if not marker.is_file():
        return None

    node: ast.stmt
    for node in source.parse(marker).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
            and isinstance(node.value, ast.Tuple)
        ):
            return frozenset(
                item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )

    return frozenset()


def _is_child_module(package: str, name: str) -> bool:
    """Match a real child module by exact spelling, even on case-insensitive disks."""
    parent: Final[pathlib.Path] = source.SOURCE_ROOT.joinpath(*package.split("."))
    return any(
        (entry.name == f"{name}.py" and entry.is_file())
        or (entry.name == name and entry.is_dir() and (entry / "__init__.py").is_file())
        for entry in parent.iterdir()
    )


def _is_parent_package(current_package: str, imported_module: str) -> bool:
    return current_package == imported_module or current_package.startswith(f"{imported_module}.")
