"""Check explicit module export declarations."""

import ast
import pathlib
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = ("test_every_module_declares_its_exports",)


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_every_module_declares_its_exports(path: pathlib.Path) -> None:
    """Require each nonempty module to declare its public exports.

    A package marker with only a docstring is allowed; other modules need `__all__`,
    even when it is an empty tuple. This checks the declaration, not that every
    entry matches all consumers. Export correctness remains a review concern.
    """
    tree: Final[ast.Module] = source.parse(path)
    if path.name == "__init__.py" and (len(tree.body) == 0 or (len(tree.body) == 1 and ast.get_docstring(tree))):
        return

    assert "__all__" in source.get_module_level_names(tree), (
        f"{source.get_module_id(path)} declares no `__all__`. Every module states what crosses its file "
        f"boundary, even when the answer is `()`."
    )
