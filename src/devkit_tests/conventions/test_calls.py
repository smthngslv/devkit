"""Check positional literal arguments when parameter names are known."""

import ast
import pathlib
from collections.abc import Iterable, Iterator, Mapping
from typing import Final

import pytest

from devkit_tests.conventions import source

type _Function = ast.FunctionDef | ast.AsyncFunctionDef

__all__: Final[tuple[str, ...]] = ("test_literal_arguments_use_keywords",)

# These constructs have their own name lookup rules; unresolved calls remain a review concern.
_UNRESOLVED_SCOPES: Final[tuple[type[ast.AST], ...]] = (
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_literal_arguments_use_keywords(path: pathlib.Path) -> None:
    """Name literal arguments when a statically known local function accepts keywords.

    Reject `connect(30)` for `def connect(timeout_s)`, but accept
    `connect(timeout_s=30)`, `connect(Timeouts.DEFAULT)`, and positional-only
    parameters. Check undecorated functions in this file, including nested and
    async functions. Do not guess signatures for imports, methods, decorated or
    rebound callables, or unpacked calls. This catches unlabelled values without
    importing application code or rejecting APIs that require positional values.
    Enum readability and unresolved calls still need human review.
    """
    offenders: Final[list[str]] = []
    call: ast.Call
    function: _Function
    for call, function in _get_scope_calls(source.parse(path), inherited={}):
        if any(isinstance(argument, ast.Starred) for argument in call.args):
            continue

        positional: list[ast.arg] = [*function.args.posonlyargs, *function.args.args]
        index: int
        argument: ast.expr
        parameter: ast.arg
        for index, (argument, parameter) in enumerate(zip(call.args, positional, strict=False)):
            if index < len(function.args.posonlyargs) or not _is_literal(argument):
                continue

            offenders.append(
                f"  line {call.lineno}: pass {ast.unparse(argument)} as `{parameter.arg}=...` in `{function.name}`"
            )

    assert offenders == [], f"{source.get_module_id(path)} passes literals without keyword names:\n" + "\n".join(
        offenders
    )


def _get_scope_calls(
    scope: source.Scope, *, inherited: Mapping[str, _Function | None]
) -> Iterator[tuple[ast.Call, _Function]]:
    """Yield calls whose local function binding is known in this scope."""
    bindings: Final[dict[str, _Function | None]] = dict(inherited) | _get_bindings(scope)
    statement: ast.stmt
    for statement in scope.body:
        yield from _get_calls(statement, bindings=bindings)


def _get_calls(node: ast.AST, *, bindings: Mapping[str, _Function | None]) -> Iterator[tuple[ast.Call, _Function]]:
    if isinstance(node, _UNRESOLVED_SCOPES):
        return

    if isinstance(node, ast.ClassDef):
        yield from _get_method_calls(node, bindings=bindings)
        return

    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        expression: ast.expr | None
        for expression in [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults]:
            if expression is not None:
                yield from _get_calls(expression, bindings=bindings)

        yield from _get_scope_calls(node, inherited=bindings)
        return

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function: _Function | None = bindings.get(node.func.id)
        if function is not None:
            yield node, function

    child: ast.AST
    for child in ast.iter_child_nodes(node):
        yield from _get_calls(child, bindings=bindings)


def _get_method_calls(
    node: ast.ClassDef, *, bindings: Mapping[str, _Function | None]
) -> Iterator[tuple[ast.Call, _Function]]:
    # Methods close over outer functions, not the class namespace; generic class parameters still apply.
    method_bindings: Final[dict[str, _Function | None]] = dict(bindings) | dict.fromkeys(
        (
            parameter.name
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar | ast.ParamSpec | ast.TypeVarTuple)
        ),
        None,
    )
    member: ast.stmt
    for member in node.body:
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _get_scope_calls(member, inherited=method_bindings)


def _get_bindings(scope: source.Scope) -> dict[str, _Function | None]:
    """Track local functions and mark shadowed names as unresolved."""
    bindings: Final[dict[str, _Function | None]] = {}
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        _bind_names(
            bindings,
            names=(
                parameter.name
                for parameter in scope.type_params
                if isinstance(parameter, ast.TypeVar | ast.ParamSpec | ast.TypeVarTuple)
            ),
        )
        _bind_names(bindings, names=(parameter.arg for parameter in source.get_parameters(scope)))
        _bind_names(
            bindings,
            names=(parameter.arg for parameter in (scope.args.vararg, scope.args.kwarg) if parameter is not None),
        )

    pending: Final[list[ast.AST]] = list(scope.body)
    while len(pending) != 0:
        node: ast.AST = pending.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            _bind_names(bindings, names=(node.name,), function=node if len(node.decorator_list) == 0 else None)
            continue

        if isinstance(node, ast.ClassDef):
            _bind_names(bindings, names=(node.name,))
            continue

        if isinstance(node, ast.Lambda):
            continue

        _bind_names(bindings, names=_get_shadowed_names(node))

        pending.extend(ast.iter_child_nodes(node))

    # A wildcard import can overwrite even explicit definitions; there is no safe signature to infer here.
    if "*" in bindings:
        return dict.fromkeys(source.get_module_level_names(scope), None) if isinstance(scope, ast.Module) else {}

    return bindings


def _get_shadowed_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
        return (node.id,)

    if isinstance(node, ast.Import | ast.ImportFrom):
        return tuple(alias.asname or alias.name.split(".")[0] for alias in node.names)

    if isinstance(node, ast.Global | ast.Nonlocal):
        return tuple(node.names)

    if isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and node.name is not None:
        return (node.name,)

    if isinstance(node, ast.MatchMapping) and node.rest is not None:
        return (node.rest,)

    return ()


def _bind_names(
    bindings: dict[str, _Function | None], *, names: Iterable[str], function: _Function | None = None
) -> None:
    name: str
    for name in names:
        bindings[name] = None if name in bindings else function


def _is_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant | ast.List | ast.Tuple | ast.Set | ast.Dict) or (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.UAdd | ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int | float | complex)
    )
