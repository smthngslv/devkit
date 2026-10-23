import ast
import pathlib
from collections.abc import Iterator, Set as AbstractSet
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "test_methods_mark_their_receiver_positional_only",
    "test_positional_only_markers_earn_their_place",
    "test_the_receiver_of_a_method_is_typed",
)

# Methods Python hands the class rather than an instance, without anyone writing `@classmethod`.
_IMPLICIT_CLASS_METHODS: Final[frozenset[str]] = frozenset({"__class_getitem__", "__init_subclass__", "__new__"})


# Section 16. Ruff removed `ANN101`/`ANN102`, so nothing flags a bare `self` any more, and an unannotated
# `self` is what makes a fluent method return the base class instead of the subclass a caller called it
# on. The exception is a property on a `Protocol`: `Self` there resolves to the protocol, and pyright then
# wants a getter taking the protocol as its first argument -- which no implementation can provide.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_the_receiver_of_a_method_is_typed(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = []
    node: ast.ClassDef
    method: ast.FunctionDef | ast.AsyncFunctionDef
    for node, method in _get_methods(source.parse(path)):
        expected: str | None = _get_expected_receiver(node, method=method)
        received: ast.arg | None = _get_receiver(method)
        if received is None:
            offenders.append(f"  {node.name}.{method.name} (line {method.lineno}) takes no receiver")
            continue

        actual: str | None = None if received.annotation is None else ast.unparse(received.annotation)
        if actual != expected:
            offenders.append(
                f"  {node.name}.{method.name} (line {method.lineno}) types `{received.arg}` as "
                f"{actual}, expected {expected}"
            )

    assert offenders == [], (
        f"{source.get_module_id(path)} leaves method receivers mistyped (section 16):\n" + "\n".join(offenders)
    )


# Section 18's first case: a method carrying `Self` marks its positional arguments positional-only. The
# marker does mechanical work rather than decoration -- without it, a caller passing a keyword that
# happens to match a positional parameter gets `TypeError: got multiple values for argument`.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_methods_mark_their_receiver_positional_only(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = []
    node: ast.ClassDef
    method: ast.FunctionDef | ast.AsyncFunctionDef
    for node, method in _get_methods(source.parse(path)):
        if len(method.args.posonlyargs) == 0:
            offenders.append(f"  {node.name}.{method.name} (line {method.lineno})")

    assert offenders == [], f"{source.get_module_id(path)} defines methods without a `/` (section 18):\n" + "\n".join(
        offenders
    )


# Section 18's other half: do not add `/` decoratively. On a module-level function with no `**kwargs` it
# removes a name dependency no caller had, and a file where half the helpers carry it and half do not is
# worse than either convention applied throughout. A callback is the exception -- it is called
# positionally by whoever holds it -- and section 23 is what makes a callback recognisable by name.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_positional_only_markers_earn_their_place(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = []
    node: ast.stmt
    for node in source.parse(path).body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        if len(node.args.posonlyargs) == 0 or node.args.kwarg is not None:
            continue

        if not node.name.lstrip("_").startswith("on_"):
            offenders.append(f"  {node.name} (line {node.lineno})")

    assert offenders == [], (
        f"{source.get_module_id(path)} marks arguments positional-only on a module-level function that "
        f"takes no `**kwargs` and is no callback (section 18):\n" + "\n".join(offenders)
    )


def _get_methods(tree: ast.Module) -> Iterator[tuple[ast.ClassDef, ast.FunctionDef | ast.AsyncFunctionDef]]:
    node: ast.AST
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        member: ast.stmt
        for member in node.body:
            if not isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                continue

            # A static method is handed nothing, so it has no receiver to type or to mark.
            if "staticmethod" not in source.get_decorator_names(member):
                yield node, member


def _get_expected_receiver(node: ast.ClassDef, *, method: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    decorators: Final[AbstractSet[str]] = source.get_decorator_names(method)
    if source.is_protocol(node) and len(decorators & source.PROPERTY_DECORATORS) > 0:
        return None

    if "classmethod" in decorators or method.name in _IMPLICIT_CLASS_METHODS:
        return "type[Self]"

    return "Self"


def _get_receiver(method: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.arg | None:
    positional: Final[list[ast.arg]] = [*method.args.posonlyargs, *method.args.args]
    return positional[0] if len(positional) > 0 else None
