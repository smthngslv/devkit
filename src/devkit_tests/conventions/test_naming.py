import ast
import pathlib
import re
from collections.abc import Iterator
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "test_boolean_names_say_what_true_means",
    "test_callback_parameters_are_named_as_callbacks",
    "test_class_names_do_not_repeat_their_namespace",
)

# Section 23's boolean prefixes. Every one of them turns a name into a yes/no question, which is what
# makes `is_enabled=False` readable at a call site where `enabled=False` needs the signature to decode.
_BOOLEAN_PREFIXES: Final[tuple[str, ...]] = ("allow_", "can_", "has_", "is_", "should_", "use_")

# What a boolean is annotated as, once `Final`/`ClassVar` and any namespace are stripped off. A wider
# union is a different question -- `bool | Set[str]` on `include_args_` is a mode, not a yes/no -- and an
# unannotated `RETRY = True` is outside the gate entirely, since nothing requires an annotation there.
_BOOLEAN_ANNOTATIONS: Final[frozenset[str]] = frozenset({"bool", "bool | None"})

_WRAPPERS: Final[tuple[str, ...]] = ("ClassVar", "Final")

# Section 23's callback spelling: the `on_` prefix says a callback is what it is, and the `_callback`
# postfix says a parameter is holding one rather than being handed ordinary data.
_CALLBACK_PARAMETER: Final[re.Pattern[str]] = re.compile(r"^_?on_[a-z0-9_]*_callback$")

# A name is a candidate for that spelling when it already claims to be half of it.
_CALLBACK_HINT: Final[re.Pattern[str]] = re.compile(r"^_?on_|callback")

# Below this, a depluralized module name is too short to repeat meaningfully: `io` and `api` turn up
# inside ordinary words, and matching them would report a name that reads perfectly well. Four is the
# shortest stem this package has (`data`), so the exemption is one character from mattering -- a shorter
# package added later loses the check, and this constant is where that trade-off is visible.
_MINIMUM_STEM_LENGTH: Final[int] = 4


# Section 23: every boolean name carries a prefix that makes the yes/no meaning unambiguous. Nothing in
# ruff reads a name against its type -- `FBT` only forces a boolean to be keyword-only -- so `retry=True`
# passes every check while leaving a reader to guess whether it retries or reports having retried.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_boolean_names_say_what_true_means(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = []
    row: int
    name: str
    for row, name in _get_boolean_names(source.parse(path)):
        if name.lower().lstrip("_").startswith(_BOOLEAN_PREFIXES):
            continue

        offenders.append(f"  line {row}: `{name}`")

    assert offenders == [], (
        f"{source.get_module_id(path)} names booleans without a prefix from {list(_BOOLEAN_PREFIXES)} "
        f"(section 23):\n" + "\n".join(offenders)
    )


# Section 23 again, for the parameter that holds a callback. Both halves of the spelling carry meaning --
# `on_event` alone reads as an event, `event_callback` alone does not say when it is called -- so a name
# claiming either half has to carry both.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_callback_parameters_are_named_as_callbacks(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = []
    function: ast.FunctionDef | ast.AsyncFunctionDef
    for function in source.get_functions(source.parse(path)):
        argument: ast.arg
        for argument in source.get_parameters(function):
            if _CALLBACK_HINT.search(argument.arg) is None or _CALLBACK_PARAMETER.match(argument.arg) is not None:
                continue

            offenders.append(f"  line {argument.lineno}: {function.name}({argument.arg})")

    assert offenders == [], (
        f"{source.get_module_id(path)} names callback parameters against section 23 -- the spelling is "
        f"`on_<event>_callback`:\n" + "\n".join(offenders)
    )


# Section 23's namespace-aware naming: a name is read with the namespace it is reached through, so
# repeating that namespace in the name says everything twice. The namespace is the package when the
# package lifts the symbol into its `__init__` (section 22), and the module otherwise -- which is why
# `catalog.Catalog` is `data.Catalog` at every call site and reads once there.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_class_names_do_not_repeat_their_namespace(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = []
    node: ast.stmt
    for node in source.parse(path).body:
        if not isinstance(node, ast.ClassDef) or _is_exception(node):
            continue

        namespace: str = _get_namespace(path, name=node.name)
        if _is_repeating(node.name, namespace=namespace):
            offenders.append(f"  line {node.lineno}: `{node.name}` reads as {namespace}.{node.name}")

    assert offenders == [], (
        f"{source.get_module_id(path)} repeats its namespace in a class name (section 23):\n" + "\n".join(offenders)
    )


def _get_boolean_names(tree: ast.Module) -> Iterator[tuple[int, str]]:
    node: ast.AST
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and _is_boolean(node.annotation):
            yield node.lineno, ast.unparse(node.target).rpartition(".")[2]

        # Unannotated, but `= True` says what the type is as plainly as an annotation would. `ANN` does
        # not reach an assignment, so without this a boolean dodges section 23 by dropping its type.
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
            target: ast.expr
            for target in node.targets:
                yield node.lineno, ast.unparse(target).rpartition(".")[2]

        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        argument: ast.arg
        for argument in source.get_parameters(node):
            if argument.annotation is not None and _is_boolean(argument.annotation):
                yield argument.lineno, argument.arg


def _is_boolean(annotation: ast.expr) -> bool:
    # Through `Final[...]` / `ClassVar[...]` and past any namespace, so `typing.Final[bool]` is the same
    # question as `bool` -- the spelling of the wrapper says nothing about whether the name is a yes/no.
    inner: ast.expr = annotation
    if isinstance(inner, ast.Subscript) and _get_head(inner.value) in _WRAPPERS:
        inner = inner.slice

    return ast.unparse(inner) in _BOOLEAN_ANNOTATIONS


def _get_head(expression: ast.expr) -> str:
    return expression.attr if isinstance(expression, ast.Attribute) else ast.unparse(expression)


def _get_namespace(path: pathlib.Path, *, name: str) -> str:
    if path.name == "__init__.py":
        return path.parent.name

    # A symbol the package lifts into its `__init__` is read through the package, never through the
    # submodule it happens to live in -- which is the whole point of lifting it (section 22, case 1).
    marker: Final[pathlib.Path] = path.parent / "__init__.py"
    if marker.exists() and name in _get_lifted_names(marker):
        return path.parent.name

    return path.stem


def _get_lifted_names(marker: pathlib.Path) -> frozenset[str]:
    return frozenset(
        alias.asname if alias.asname is not None else alias.name
        for node in source.parse(marker).body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    )


def _is_exception(node: ast.ClassDef) -> bool:
    # An exception class is spelled `<Something>Error` by `N818`, so a module of them repeats itself by
    # rule rather than by choice, and the two rules cannot both be satisfied.
    base: ast.expr
    for base in node.bases:
        name: str = base.attr if isinstance(base, ast.Attribute) else ast.unparse(base)
        if name.endswith(("Error", "Exception")):
            return True

    return False


def _is_repeating(name: str, *, namespace: str) -> bool:
    # Depluralized, because `market.splits` holds a `Split` and that is the name repeating, not `Splits`.
    stem: Final[str] = namespace.removesuffix("s")
    lowered: Final[str] = name.lower()
    # An exact match is the case section 22 repairs by lifting the symbol: `catalog.Catalog` becomes
    # `data.Catalog`, and the namespace it is read through is then not the one it repeats.
    if lowered in (namespace, stem) or len(stem) < _MINIMUM_STEM_LENGTH:
        return False

    return lowered.startswith(stem) or lowered.endswith(stem)
