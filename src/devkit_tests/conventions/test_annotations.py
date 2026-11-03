"""Check annotations on local bindings and method targets."""

import ast
import pathlib
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "test_bare_declarations_sit_above_what_they_annotate",
    "test_loop_variables_are_annotated",
    "test_with_targets_are_annotated",
)

# Ruff's `dummy-variable-rgx`: a name that exists only because the syntax needs one carries no type worth
# stating, and annotating it would be the only reason anyone read it (the shared definition -- one spelling, here).
_DUMMY_NAME: Final[re.Pattern[str]] = re.compile(r"^_+$")


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_loop_variables_are_annotated(path: pathlib.Path) -> None:
    """Require a declared type for each named loop target.

    For example, put `row: str` before `for row in rows`. Check sync and async
    loops, including unpacked targets, without borrowing declarations from nested
    functions. Ignore `_` placeholders and comprehensions, whose targets cannot
    carry a separate annotation. This keeps the type visible at the binding.
    """
    offenders: Final[list[str]] = []
    scope: source.Scope
    for scope in _get_scopes(source.parse(path)):
        declared: dict[str, int] = _get_declared_rows(scope)
        node: ast.stmt
        for node in source.get_scope_statements(scope):
            if not isinstance(node, ast.For | ast.AsyncFor):
                continue

            offenders.extend(
                f"  line {node.lineno}: `for {name}`"
                for name in _get_unannotated(node.target, declared=declared, row=node.lineno)
            )

    assert offenders == [], f"{source.get_module_id(path)} loops over unannotated variables:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_with_targets_are_annotated(path: pathlib.Path) -> None:
    """Require a declared type for names bound by context managers.

    For example, put `handle: IO[str]` before `with path.open() as handle`.
    Check sync and async contexts and unpacked targets. A context without `as`
    binds nothing and needs no declaration. The annotation explains what the
    context manager returns without making the reader inspect its implementation.
    """
    offenders: Final[list[str]] = []
    scope: source.Scope
    for scope in _get_scopes(source.parse(path)):
        declared: dict[str, int] = _get_declared_rows(scope)
        node: ast.stmt
        for node in source.get_scope_statements(scope):
            if not isinstance(node, ast.With | ast.AsyncWith):
                continue

            item: ast.withitem
            for item in node.items:
                if item.optional_vars is None:
                    continue

                offenders.extend(
                    f"  line {node.lineno}: `as {name}`"
                    for name in _get_unannotated(item.optional_vars, declared=declared, row=node.lineno)
                )

    assert offenders == [], f"{source.get_module_id(path)} binds unannotated `with` targets:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_bare_declarations_sit_above_what_they_annotate(path: pathlib.Path) -> None:
    """Keep standalone annotations beside the statement that binds their names.

    Reject a declaration stranded above an unrelated statement or outside a try
    block. Allow stacked declarations for unpacking and declarations before a loop
    that assigns the names in its body. Class fields are excluded because they
    describe the class, not a following statement. This prevents misleading placement.
    """
    offenders: Final[list[str]] = []
    block: Sequence[ast.stmt]
    for block in _get_blocks(source.parse(path)):
        index: int
        declaration: ast.stmt
        for index, declaration in enumerate(block):
            name: str | None = _get_bare_declaration(declaration)
            if name is None:
                continue

            annotated: ast.stmt | None = _get_annotated_statement(block[index + 1 :])
            if annotated is None:
                offenders.append(f"  line {declaration.lineno}: `{name}` declares a type nothing below it binds")

            elif not _is_bound_by(annotated, name=name):
                offenders.append(
                    f"  line {declaration.lineno}: `{name}` is declared above a "
                    f"{annotated.__class__.__name__.lower()} that does not bind it"
                )

    assert offenders == [], (
        f"{source.get_module_id(path)} parks bare declarations away from what they annotate:\n" + "\n".join(offenders)
    )


def _get_scopes(tree: ast.Module) -> Iterator[source.Scope]:
    # A comprehension owns a scope too, but its target cannot carry an annotation, so it is not one of
    # the scopes this rule can ask anything of.
    yield tree
    yield from source.get_functions(tree)


def _get_declared_rows(scope: source.Scope) -> dict[str, int]:
    # The row a name first acquires a type on. Parameters count from the signature they arrive in, which
    # is line zero as far as anything below them is concerned.
    declared: Final[dict[str, int]] = {}
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        argument: ast.arg
        for argument in source.get_parameters(scope):
            if argument.annotation is not None:
                declared[argument.arg] = 0

    node: ast.stmt
    for node in source.get_scope_statements(scope):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            declared[node.target.id] = min(declared.get(node.target.id, node.lineno), node.lineno)

    return declared


def _get_unannotated(target: ast.expr, *, declared: Mapping[str, int], row: int) -> list[str]:
    return [
        name
        for name in sorted(source.get_bound_names(target))
        if _DUMMY_NAME.fullmatch(name) is None and declared.get(name, row + 1) > row
    ]


def _get_blocks(tree: ast.Module) -> Iterator[list[ast.stmt]]:
    # Every run of statements that shares an indentation level, which is what "the same block" means. A
    # class body is not one of them: a bare declaration there is a field, and the statement it describes
    # is the class itself rather than anything below it.
    node: ast.AST
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.With | ast.AsyncWith | ast.ExceptHandler
        ):
            yield node.body

        elif isinstance(node, ast.If | ast.For | ast.AsyncFor | ast.While):
            yield node.body
            yield node.orelse

        elif isinstance(node, ast.Try | ast.TryStar):
            yield node.body
            yield node.orelse
            yield node.finalbody

        # `ast.match_case` is not an `ast.stmt`, so it is reached here rather than through the walk above.
        elif isinstance(node, ast.match_case):
            yield node.body


def _get_bare_declaration(node: ast.stmt) -> str | None:
    if not isinstance(node, ast.AnnAssign) or node.value is not None:
        return None

    return node.target.id if isinstance(node.target, ast.Name) else None


def _get_annotated_statement(rest: Sequence[ast.stmt]) -> ast.stmt | None:
    # Declarations stack: several names bound by the same statement are declared one after another, and
    # the statement they all annotate is the first thing that is not another declaration.
    node: ast.stmt
    for node in rest:
        if _get_bare_declaration(node) is None:
            return node

    return None


def _is_bound_by(node: ast.stmt, *, name: str) -> bool:
    if name in _get_bindings(node):
        return True

    # A loop rebinds on every pass, so its declaration cannot live in the body that rebinds it.
    if not isinstance(node, ast.For | ast.AsyncFor | ast.While):
        return False

    pending: Final[list[ast.stmt]] = source.get_nested_statements(node)
    nested: ast.stmt
    while len(pending) > 0:
        nested = pending.pop(0)
        if isinstance(nested, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue

        if name in _get_bindings(nested):
            return True

        pending.extend(source.get_nested_statements(nested))

    return False


def _get_bindings(node: ast.stmt) -> set[str]:
    if isinstance(node, ast.For | ast.AsyncFor):
        return source.get_bound_names(node.target)

    if isinstance(node, ast.With | ast.AsyncWith):
        return {
            name
            for item in node.items
            if item.optional_vars is not None
            for name in source.get_bound_names(item.optional_vars)
        }

    if isinstance(node, ast.Assign):
        return {name for target in node.targets for name in source.get_bound_names(target)}

    if isinstance(node, ast.AnnAssign | ast.AugAssign):
        return source.get_bound_names(node.target)

    return set()
