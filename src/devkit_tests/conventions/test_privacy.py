import ast
import pathlib
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = ("test_no_module_level_name_is_double_underscored",)

# `__all__` is the one module-level dunder a module is required to define (section 21).
_PERMITTED: Final[frozenset[str]] = frozenset({"__all__"})


# A module-level `__name` is not private the way a class-level one is. Mangling applies inside a class body
# only, so at module scope the second underscore buys nothing over `_name` -- and it actively breaks: a
# method that later references the module-level `__WINDOWS` compiles to `_Window__WINDOWS` and raises
# `NameError` at runtime, under a name nobody typed. Nothing in ruff or pyright reports it, so this is the
# gate (sections 7, 24).
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_no_module_level_name_is_double_underscored(path: pathlib.Path) -> None:
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
