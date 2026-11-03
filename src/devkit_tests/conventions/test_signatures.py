"""Check method receivers and positional-only markers."""

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


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_the_receiver_of_a_method_is_typed(path: pathlib.Path) -> None:
    """Require the documented type on instance and class receivers.

    Instance methods use `self: Self`; classmethods and implicit class receivers
    use `cls: type[Self]`. Protocol properties use bare self. Static methods are
    skipped because Python supplies no receiver. This keeps fluent interfaces typed
    without rejecting the deliberate protocol-property exception.
    """
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
        if actual != expected and not _is_specialized_receiver(node, method=method, received=received):
            offenders.append(
                f"  {node.name}.{method.name} (line {method.lineno}) types `{received.arg}` as "
                f"{actual}, expected {expected}"
            )

    assert offenders == [], f"{source.get_module_id(path)} leaves method receivers mistyped:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_methods_mark_their_receiver_positional_only(path: pathlib.Path) -> None:
    """Require a positional-only receiver on instance and class methods.

    Accept `def read(self: Self, /)` and reject the same signature without `/`.
    Skip static methods, which have no implicit receiver. This prevents callers
    from depending on the receiver name or colliding with it through keyword arguments.
    """
    offenders: Final[list[str]] = []
    node: ast.ClassDef
    method: ast.FunctionDef | ast.AsyncFunctionDef
    for node, method in _get_methods(source.parse(path)):
        if len(method.args.posonlyargs) == 0:
            offenders.append(f"  {node.name}.{method.name} (line {method.lineno})")

    assert offenders == [], f"{source.get_module_id(path)} defines methods without a `/`:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_positional_only_markers_earn_their_place(path: pathlib.Path) -> None:
    """Reject unnecessary positional-only markers on ordinary helpers.

    A module function or static method may use `/` when it is an `on_` callback
    or accepts `**kwargs`; otherwise it should keep named arguments available.
    Instance and class receivers are checked separately. This avoids decorative
    restrictions that make callers less flexible without protecting a contract.
    """
    offenders: Final[list[str]] = []
    tree: Final[ast.Module] = source.parse(path)
    candidates: Final[list[ast.stmt]] = list(tree.body)
    class_node: ast.AST
    for class_node in ast.walk(tree):
        if isinstance(class_node, ast.ClassDef):
            candidates.extend(
                member
                for member in class_node.body
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
                and "staticmethod" in source.get_decorator_names(member)
            )

    node: ast.stmt
    for node in candidates:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        if len(node.args.posonlyargs) == 0 or node.args.kwarg is not None:
            continue

        if not node.name.lstrip("_").startswith("on_"):
            offenders.append(f"  {node.name} (line {node.lineno})")

    assert offenders == [], (
        f"{source.get_module_id(path)} marks arguments positional-only on a function or static method that "
        f"takes no `**kwargs` and is no callback:\n" + "\n".join(offenders)
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


def _is_specialized_receiver(
    node: ast.ClassDef, *, method: ast.FunctionDef | ast.AsyncFunctionDef, received: ast.arg
) -> bool:
    # A generic type-state method can restrict itself to one mode, as Session[TX].commit does.
    if len(node.type_params) == 0 or received.annotation is None:
        return False

    if "classmethod" in source.get_decorator_names(method) or method.name in _IMPLICIT_CLASS_METHODS:
        return False

    annotation: Final[ast.expr] = received.annotation
    return (
        isinstance(annotation, ast.Subscript)
        and isinstance(annotation.value, ast.Name)
        and annotation.value.id == node.name
    )
