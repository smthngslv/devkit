import ast
import pathlib
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "test_removal_goes_through_a_method_rather_than_del",
    "test_the_type_of_an_object_is_read_through_its_class",
)


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_the_type_of_an_object_is_read_through_its_class(path: pathlib.Path) -> None:
    """Enforce the project spelling for an object type lookup.

    Reject a direct one-argument `type(value)` call in favor of `value.__class__`.
    Allow the three-argument type constructor. This is a syntax convention, not
    proof that the two expressions behave identically for proxies or overridden
    attribute access; aliases and shadowed builtin names are not resolved here.
    """
    offenders: Final[list[int]] = []
    node: ast.AST
    for node in ast.walk(source.parse(path)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue

        if node.func.id == "type" and len(node.args) == 1 and len(node.keywords) == 0:
            offenders.append(node.lineno)

    assert offenders == [], (
        f"{source.get_module_id(path)} calls `type(...)` on lines {offenders}. The class-lookup rule reads an "
        f"object's type as `obj.__class__`."
    )


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_removal_goes_through_a_method_rather_than_del(path: pathlib.Path) -> None:
    """Reject del statements that remove items or object attributes.

    Prefer `items.pop(key)` or `items.remove(value)` for collections. Deleting a
    bare local name is allowed because it has no corresponding collection method.
    Inspect unpacked deletion targets too, so parentheses cannot bypass the rule.
    This enforces the preferred explicit method-call style.
    """
    offenders: Final[list[str]] = []
    node: ast.AST
    for node in ast.walk(source.parse(path)):
        if not isinstance(node, ast.Delete):
            continue

        pending: list[ast.expr] = list(node.targets)
        target: ast.expr
        while len(pending) > 0:
            target = pending.pop()
            if isinstance(target, ast.Tuple | ast.List):
                pending.extend(target.elts)

            elif isinstance(target, ast.Attribute | ast.Subscript):
                offenders.append(f"  line {node.lineno}: del {ast.unparse(target)}")

    assert offenders == [], f"{source.get_module_id(path)} deletes through `del`:\n" + "\n".join(offenders)
