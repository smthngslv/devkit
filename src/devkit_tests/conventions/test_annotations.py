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
# stating, and annotating it would be the only reason anyone read it (section 3 -- one spelling, here).
_DUMMY_NAME: Final[re.Pattern[str]] = re.compile(r"^_+$")


# Section 14: a loop variable is annotated once per scope, before the loop. Nothing types it otherwise --
# `ANN` covers parameters and returns, and a `for` target is neither -- so an untyped loop over an
# untyped iterable is how `Any` gets into a function that looks fully annotated.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_loop_variables_are_annotated(path: pathlib.Path) -> None:
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

    assert offenders == [], (
        f"{source.get_module_id(path)} loops over unannotated variables (section 14):\n" + "\n".join(offenders)
    )


# Section 14 again, for the other binding a statement makes without a signature to carry the type. A
# `with` target is what the context manager returns, which is exactly where the reader most wants the
# type spelled out rather than inferred from a call three modules away.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_with_targets_are_annotated(path: pathlib.Path) -> None:
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

    assert offenders == [], (
        f"{source.get_module_id(path)} binds unannotated `with` targets (section 14):\n" + "\n".join(offenders)
    )


# Section 14's placement rule: a bare declaration sits directly above the statement it annotates, in the
# same block. Hoisted out of a `try`, an `if` or a `with`, it reads as if it described that block, and
# leaves the statement it belongs to looking unannotated. A loop is the one statement it may sit above
# without being inside, because a name the loop rebinds cannot be declared in the body it is rebound in.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_bare_declarations_sit_above_what_they_annotate(path: pathlib.Path) -> None:
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
        f"{source.get_module_id(path)} parks bare declarations away from what they annotate (section 14):\n"
        + "\n".join(offenders)
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
            declared[argument.arg] = 0

    node: ast.stmt
    for node in source.get_scope_statements(scope):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            declared.setdefault(node.target.id, node.lineno)

    return declared


def _get_unannotated(target: ast.expr, *, declared: Mapping[str, int], row: int) -> list[str]:
    return [
        name.id
        for name in ast.walk(target)
        if isinstance(name, ast.Name) and _DUMMY_NAME.match(name.id) is None and declared.get(name.id, row + 1) > row
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

    return any(isinstance(nested, ast.stmt) and name in _get_bindings(nested) for nested in ast.walk(node))


def _get_bindings(node: ast.stmt) -> set[str]:
    if isinstance(node, ast.For | ast.AsyncFor):
        return _get_names(node.target)

    if isinstance(node, ast.With | ast.AsyncWith):
        return {
            name for item in node.items if item.optional_vars is not None for name in _get_names(item.optional_vars)
        }

    if isinstance(node, ast.Assign):
        return {name for target in node.targets for name in _get_names(target)}

    if isinstance(node, ast.AnnAssign | ast.AugAssign):
        return _get_names(node.target)

    return set()


def _get_names(target: ast.expr) -> set[str]:
    return {node.id for node in ast.walk(target) if isinstance(node, ast.Name)}
