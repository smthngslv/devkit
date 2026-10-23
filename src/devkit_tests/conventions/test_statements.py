import ast
import pathlib
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "test_removal_goes_through_a_method_rather_than_del",
    "test_the_type_of_an_object_is_read_through_its_class",
)


# Section 37: `obj.__class__` reads the type through the object, so it follows an override and a proxy
# where `type(obj)` reads whatever the runtime object literally is. The one-argument call is the type
# *query*; the three-argument form builds a class and is a different function wearing the same name.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_the_type_of_an_object_is_read_through_its_class(path: pathlib.Path) -> None:
    offenders: Final[list[int]] = []
    node: ast.AST
    for node in ast.walk(source.parse(path)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue

        if node.func.id == "type" and len(node.args) == 1 and len(node.keywords) == 0:
            offenders.append(node.lineno)

    assert offenders == [], (
        f"{source.get_module_id(path)} calls `type(...)` on lines {offenders}. Section 37 reads an "
        f"object's type as `obj.__class__`."
    )


# Section 38: `pop` and `remove` are calls that say what they do and hand back what they removed, where
# `del` is a statement whose effect is invisible at the call site. Deleting a bare name has no method
# form, so only subscripts and attributes are asked to use one.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_removal_goes_through_a_method_rather_than_del(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = []
    node: ast.AST
    for node in ast.walk(source.parse(path)):
        if not isinstance(node, ast.Delete):
            continue

        target: ast.expr
        for target in node.targets:
            if isinstance(target, ast.Attribute | ast.Subscript):
                offenders.append(f"  line {node.lineno}: del {ast.unparse(target)}")

    assert offenders == [], f"{source.get_module_id(path)} deletes through `del` (section 38):\n" + "\n".join(offenders)
