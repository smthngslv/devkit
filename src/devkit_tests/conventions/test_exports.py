import ast
import pathlib
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = ("test_every_module_declares_its_exports",)


# Section 21 asks for `__all__` in every module, and prose alone does not survive a new file being added
# (section 7). The one carve-out is a package marker with no statements: it declares nothing, so it has
# nothing to declare.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_every_module_declares_its_exports(path: pathlib.Path) -> None:
    tree: Final[ast.Module] = source.parse(path)
    if path.name == "__init__.py" and len(tree.body) == 0:
        return

    assert "__all__" in source.get_module_level_names(tree), (
        f"{source.get_module_id(path)} declares no `__all__`. Every module states what crosses its file "
        f"boundary, even when the answer is `()`."
    )
