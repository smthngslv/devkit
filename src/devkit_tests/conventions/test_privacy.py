import ast
import pathlib
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = ("test_no_module_level_name_is_double_underscored",)

# `__all__` is the one module-level dunder a module is required to define.
_PERMITTED: Final[frozenset[str]] = frozenset({"__all__"})


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_no_module_level_name_is_double_underscored(path: pathlib.Path) -> None:
    """Reject class-style private names at module scope.

    Use `_cache`, not `__cache`, for a module-private name. Include bindings inside
    conditional blocks and unpacking, but do not inspect class-local or function-local
    names as module names. Ordinary dunders such as `__all__` remain allowed.
    This avoids accidental name mangling when a class references a module variable.
    """
    tree: Final[ast.Module] = source.parse(path)
    offenders: Final[list[str]] = [
        name
        for name in source.get_module_level_names(tree)
        if name.startswith("__") and not name.endswith("__") and name not in _PERMITTED
    ]

    assert offenders == [], (
        f"{source.get_module_id(path)} declares {offenders} at module scope. Module-level privacy is a "
        f"single underscore; a double underscore mangles inside any class body in the same file."
    )
