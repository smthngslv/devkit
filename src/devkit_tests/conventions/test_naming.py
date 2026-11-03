"""Check callback names and class namespace repetition."""

import ast
import pathlib
import re
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "test_callback_parameters_are_named_as_callbacks",
    "test_class_names_do_not_repeat_their_namespace",
)

# The naming rule's callback spelling: the `on_` prefix says a callback is what it is, and the `_callback`
# postfix says a parameter is holding one rather than being handed ordinary data.
_CALLBACK_PARAMETER: Final[re.Pattern[str]] = re.compile(r"^_?on_[a-z0-9_]*_callback$")

# A name is a candidate for that spelling when it already claims to be half of it.
_CALLBACK_HINT: Final[re.Pattern[str]] = re.compile(r"^_?on_|callback")

# Below this, a depluralized module name is too short to repeat meaningfully: `io` and `api` turn up
# inside ordinary words, and matching them would report a name that reads perfectly well. Four is the
# shortest stem this package has (`data`), so the exemption is one character from mattering -- a shorter
# package added later loses the check, and this constant is where that trade-off is visible.
_MINIMUM_STEM_LENGTH: Final[int] = 4


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_callback_parameters_are_named_as_callbacks(path: pathlib.Path) -> None:
    """Require callback-like parameter names to use both naming markers.

    A parameter named `on_event` or `event_callback` must become
    `on_event_callback`. This is a spelling heuristic: it checks names that already
    claim to be callbacks, not every callable type or function passed at runtime.
    The two markers explain both when the callback runs and what the argument holds.
    """
    offenders: Final[list[str]] = []
    function: ast.FunctionDef | ast.AsyncFunctionDef
    for function in source.get_functions(source.parse(path)):
        argument: ast.arg
        for argument in source.get_parameters(function):
            if _CALLBACK_HINT.search(argument.arg) is None or _CALLBACK_PARAMETER.match(argument.arg) is not None:
                continue

            offenders.append(f"  line {argument.lineno}: {function.name}({argument.arg})")

    assert offenders == [], (
        f"{source.get_module_id(path)} names callback parameters against the naming rule -- the spelling is "
        f"`on_<event>_callback`:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_class_names_do_not_repeat_their_namespace(path: pathlib.Path) -> None:
    """Reject class names with redundant module prefixes or suffixes.

    For example, prefer `events.Bus` over `events.EventBus`. Use the package
    namespace for a symbol re-exported from that module. Exempt exception classes,
    short namespace stems, and exact class/module matches. This is a conservative
    spelling check; deciding whether a name is meaningful still requires review.
    """
    offenders: Final[list[str]] = []
    node: ast.stmt
    for node in source.parse(path).body:
        if not isinstance(node, ast.ClassDef) or _is_exception(node):
            continue

        namespace: str = _get_namespace(path, name=node.name)
        if _is_repeating(node.name, namespace=namespace):
            offenders.append(f"  line {node.lineno}: `{node.name}` reads as {namespace}.{node.name}")

    assert offenders == [], f"{source.get_module_id(path)} repeats its namespace in a class name:\n" + "\n".join(
        offenders
    )


def _get_namespace(path: pathlib.Path, *, name: str) -> str:
    if path.name == "__init__.py":
        return path.parent.name

    # A symbol the package lifts into its `__init__` is read through the package, never through the
    # submodule it happens to live in -- which is the whole point of lifting it (the import rule, case 1).
    marker: Final[pathlib.Path] = path.parent / "__init__.py"
    if marker.exists() and name in _get_lifted_names(marker, module=path.stem):
        return path.parent.name

    return path.stem


def _get_lifted_names(marker: pathlib.Path, *, module: str) -> frozenset[str]:
    return frozenset(
        alias.asname if alias.asname is not None else alias.name
        for node in source.parse(marker).body
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and (
            (node.level == 1 and node.module == module)
            or (node.level == 0 and node.module.endswith(f"{marker.parent.name}.{module}"))
        )
        for alias in node.names
        if alias.asname is None or alias.asname == alias.name
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
    # An exact match is the case the import rule repairs by lifting the symbol: `catalog.Catalog` becomes
    # `data.Catalog`, and the namespace it is read through is then not the one it repeats.
    if lowered in (namespace, stem) or len(stem) < _MINIMUM_STEM_LENGTH:
        return False

    return lowered.startswith(stem) or lowered.endswith(stem)
