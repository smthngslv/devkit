"""Check definition order and constructor assignment order."""

import ast
import pathlib
from collections.abc import Sequence, Set as AbstractSet
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "test_attributes_are_assigned_in_parameter_order",
    "test_class_members_are_ordered",
    "test_module_definitions_are_ordered",
)

# The ordering rule's module order, as the rank each kind of definition sorts to. Visibility is the outer key for
# functions and the inner one for everything else, which is the rule's numbered list verbatim.
_PUBLIC_TYPE_ALIAS: Final[int] = 0
_PRIVATE_TYPE_ALIAS: Final[int] = 1
_PUBLIC_CONSTANT: Final[int] = 2
_PRIVATE_CONSTANT: Final[int] = 3
_PUBLIC_SYNC_FUNCTION: Final[int] = 4
_PUBLIC_ASYNC_FUNCTION: Final[int] = 5
_PRIVATE_SYNC_FUNCTION: Final[int] = 6
_PRIVATE_ASYNC_FUNCTION: Final[int] = 7
_PUBLIC_CLASS: Final[int] = 8
_PRIVATE_CLASS: Final[int] = 9

# The ordering rule's class order: attributes by visibility, then factories, `__init__`, properties, sync, async,
# protected, private, and `__del__` last. Subgroups leave room so abstract-before-concrete fits
# inside each one as `_CONCRETE_OFFSET`.
_MAGIC_ATTRIBUTE: Final[int] = 0
_PUBLIC_ATTRIBUTE: Final[int] = 20
_PROTECTED_ATTRIBUTE: Final[int] = 40
_PRIVATE_ATTRIBUTE: Final[int] = 60
_PUBLIC_FACTORY: Final[int] = 80
_PROTECTED_FACTORY: Final[int] = 100
_PRIVATE_FACTORY: Final[int] = 120
_INITIALIZER: Final[int] = 140
_PUBLIC_PROPERTY: Final[int] = 160
_PUBLIC_STATIC_METHOD: Final[int] = 180
_PUBLIC_MAGIC_METHOD: Final[int] = 200
_PUBLIC_SYNC_METHOD: Final[int] = 220
_PUBLIC_ASYNC_STATIC_METHOD: Final[int] = 240
_PUBLIC_ASYNC_MAGIC_METHOD: Final[int] = 260
_PUBLIC_ASYNC_METHOD: Final[int] = 280
_PROTECTED_PROPERTY: Final[int] = 300
_PROTECTED_SYNC_METHOD: Final[int] = 320
_PROTECTED_ASYNC_METHOD: Final[int] = 340
_PRIVATE_PROPERTY: Final[int] = 360
_PRIVATE_SYNC_METHOD: Final[int] = 380
_PRIVATE_ASYNC_METHOD: Final[int] = 400
_DELETER: Final[int] = 420

# Added inside a subgroup, so an abstract member precedes the concrete ones it shares the subgroup with.
_CONCRETE_OFFSET: Final[int] = 1

# Construction, whatever the layout mechanism spells it. `__post_init__` is a dataclass's `__init__` and
# `__new__` is a hand-written one, so both sort where the rule puts initialization rather than among the
# magic methods; all three participate in initialization.
_INITIALIZERS: Final[frozenset[str]] = frozenset({"__init__", "__new__", "__post_init__"})

_STATIC_DECORATORS: Final[frozenset[str]] = frozenset({"classmethod", "staticmethod"})

# The ordering rule orders class attributes magic, then public, then private. Protected sits between the two:
# it is reachable from a subclass and so is less hidden than private, and no further from the top than
# that. Total over `Visibility`, so a new visibility cannot be added without answering where it sorts.
_ATTRIBUTE_RANKS: Final[dict[source.Visibility, int]] = {
    source.Visibility.MAGIC: _MAGIC_ATTRIBUTE,
    source.Visibility.PUBLIC: _PUBLIC_ATTRIBUTE,
    source.Visibility.PROTECTED: _PROTECTED_ATTRIBUTE,
    source.Visibility.PRIVATE: _PRIVATE_ATTRIBUTE,
}

# Property, sync, async -- the three subgroups the ordering rule gives a member that is not public, in order.
_RESTRICTED_RANKS: Final[dict[source.Visibility, tuple[int, int, int]]] = {
    source.Visibility.PROTECTED: (_PROTECTED_PROPERTY, _PROTECTED_SYNC_METHOD, _PROTECTED_ASYNC_METHOD),
    source.Visibility.PRIVATE: (_PRIVATE_PROPERTY, _PRIVATE_SYNC_METHOD, _PRIVATE_ASYNC_METHOD),
}

_FACTORY_RANKS: Final[dict[source.Visibility, int]] = {
    source.Visibility.MAGIC: _PUBLIC_FACTORY,
    source.Visibility.PUBLIC: _PUBLIC_FACTORY,
    source.Visibility.PROTECTED: _PROTECTED_FACTORY,
    source.Visibility.PRIVATE: _PRIVATE_FACTORY,
}


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_module_definitions_are_ordered(path: pathlib.Path) -> None:
    """Keep module definitions in the documented groups without breaking dependencies.

    Type aliases precede constants, functions, and classes, with visibility and
    async subgroups inside those groups. A constant constructed from a class must
    follow that class. Equal-ranked definitions keep their original order, so
    alphabetical or semantic order within a group remains a review concern.
    """
    body: Final[Sequence[ast.stmt]] = source.parse(path).body
    actual: Final[list[str]] = _get_module_names(body)
    canonical: Final[list[str]] = source.get_canonical_order(
        actual, ranks=_get_module_ranks(body), requires=_get_module_requirements(body)
    )

    assert actual == canonical, (
        f"{source.get_module_id(path)} defines its module members out of order. Expected:\n"
        f"  {' -> '.join(canonical)}\ngot:\n  {' -> '.join(actual)}"
    )


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_class_members_are_ordered(path: pathlib.Path) -> None:
    """Keep class attributes and methods in the documented reading order.

    Attributes precede factories and initialization, then public properties and
    methods, protected members, private members, and finally the destructor.
    Preserve dependencies between class-body expressions. Check async subgroups
    and abstract members too, so a less common method cannot bypass the style rule.
    """
    tree: Final[ast.Module] = source.parse(path)
    offenders: Final[list[str]] = []
    node: ast.AST
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        actual: list[str] = _get_member_names(node)
        canonical: list[str] = source.get_canonical_order(
            actual, ranks=_get_member_ranks(node), requires=_get_member_requirements(node)
        )
        if actual != canonical:
            offenders.append(f"  {node.name} (line {node.lineno}): expected {canonical}, got {actual}")

    assert offenders == [], f"{source.get_module_id(path)} orders class members incorrectly:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_attributes_are_assigned_in_parameter_order(path: pathlib.Path) -> None:
    """Keep direct attribute assignments in the same order as their input parameters.

    For `(first, second)`, assigning `self.second = second` before
    `self.first = first` fails. Check direct assignments in the function body;
    transformed values and assignments inside branches are outside this check.
    This makes the signature easy to compare with the values stored by the method.
    """
    offenders: Final[list[str]] = []
    function: ast.FunctionDef | ast.AsyncFunctionDef
    for function in source.get_functions(source.parse(path)):
        positions: list[int] = _get_assigned_positions(function)
        if positions != sorted(positions):
            offenders.append(f"  {function.name} (line {function.lineno}) stores parameters as {positions}")

    assert offenders == [], f"{source.get_module_id(path)} assigns attributes out of parameter order:\n" + "\n".join(
        offenders
    )


def _get_module_names(body: Sequence[ast.stmt]) -> list[str]:
    return [
        name
        for node in body
        if (name := source.get_defined_name(node)) is not None and _get_module_rank(node) is not None
    ]


def _get_module_ranks(body: Sequence[ast.stmt]) -> dict[str, int]:
    return {
        name: rank
        for node in body
        if (name := source.get_defined_name(node)) is not None and (rank := _get_module_rank(node)) is not None
    }


def _get_module_requirements(body: Sequence[ast.stmt]) -> dict[str, set[str]]:
    # Minus the definition's own name: a `@dataclass` annotating a field with its own class is ordinary
    # under PEP 649, and left in, it would require itself and no order could ever be computed.
    return {
        name: source.get_referenced_names(source.get_import_time_expressions(node)) - {name}
        for node in body
        if (name := source.get_defined_name(node)) is not None and _get_module_rank(node) is not None
    }


def _get_module_rank(node: ast.stmt) -> int | None:
    name: Final[str | None] = source.get_defined_name(node)
    # `__all__` is the module declaring itself, not one of the definitions being ordered.
    if name is None or name == "__all__":
        return None

    is_private: Final[bool] = name.startswith("_")
    if isinstance(node, ast.TypeAlias):
        return _PRIVATE_TYPE_ALIAS if is_private else _PUBLIC_TYPE_ALIAS

    if isinstance(node, ast.ClassDef):
        return _PRIVATE_CLASS if is_private else _PUBLIC_CLASS

    if isinstance(node, ast.AsyncFunctionDef):
        return _PRIVATE_ASYNC_FUNCTION if is_private else _PUBLIC_ASYNC_FUNCTION

    if isinstance(node, ast.FunctionDef):
        return _PRIVATE_SYNC_FUNCTION if is_private else _PUBLIC_SYNC_FUNCTION

    return _PRIVATE_CONSTANT if is_private else _PUBLIC_CONSTANT


def _get_member_names(node: ast.ClassDef) -> list[str]:
    return [
        name
        for member in node.body
        if (name := source.get_defined_name(member)) is not None and _get_member_rank(member) is not None
    ]


def _get_member_ranks(node: ast.ClassDef) -> dict[str, int]:
    names: Final[frozenset[str]] = frozenset(_get_member_names(node))
    ranks: Final[dict[str, int]] = {}
    writable: Final[set[str]] = {
        member.name
        for member in node.body
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and "setter" in source.get_decorator_names(member)
    }
    member: ast.stmt
    for member in node.body:
        name: str | None = source.get_defined_name(member)
        rank: int | None = _get_member_rank(member)
        if name is None or name not in names or rank is None:
            continue

        # A setter shares its getter's rank; replacing the rank would lose abstract/read-only distinctions.
        if name in ranks:
            continue

        if name in writable and _PUBLIC_PROPERTY <= rank < _PUBLIC_STATIC_METHOD:
            rank += 2

        ranks[name] = rank

    return ranks


def _get_member_requirements(node: ast.ClassDef) -> dict[str, set[str]]:
    """Preserve the binding order required by member defaults and annotations."""
    # An edge in the direction the file already has it, because both directions are real: a member read by
    # an earlier member's decorator or default must precede it, and a member whose name shadows a module
    # global that an earlier member reads must follow it. At most one of the two holds for any pair, and
    # the file is what says which -- reordering against either changes what a name resolves to.
    #
    # Annotations count here where they do not at module scope: a signature inside a class body resolves
    # its names against that body, so `Tracer.span` returning a `logfire.LogfireSpan` is what pins the
    # `Tracer.logfire_instance` field below it, whatever PEP 649 defers at runtime.
    names: Final[list[str]] = _get_member_names(node)
    requirements: Final[dict[str, set[str]]] = {name: set() for name in names}
    member: ast.stmt
    for member in node.body:
        name: str | None = source.get_defined_name(member)
        if name is None or name not in requirements:
            continue

        expressions: list[ast.expr] = source.get_import_time_expressions(member, is_annotation_forced=True)
        referenced: str
        for referenced in source.get_referenced_names(expressions) & set(names):
            if referenced == name:
                continue

            if names.index(referenced) < names.index(name):
                requirements[name].add(referenced)

            else:
                requirements[referenced].add(name)

    return requirements


def _get_member_rank(member: ast.stmt) -> int | None:
    name: Final[str | None] = source.get_defined_name(member)
    if name is None:
        return None

    visibility: Final[source.Visibility] = source.get_visibility(name)
    if isinstance(member, ast.AnnAssign | ast.Assign):
        return _ATTRIBUTE_RANKS[visibility]

    if not isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
        return None

    return _get_method_rank(member, name=name, visibility=visibility)


def _get_method_rank(
    member: ast.FunctionDef | ast.AsyncFunctionDef, *, name: str, visibility: source.Visibility
) -> int:
    decorators: Final[AbstractSet[str]] = source.get_decorator_names(member)
    if name == "__del__":
        return _DELETER

    if _is_factory(member, decorators=decorators):
        return _FACTORY_RANKS[visibility]

    if name in _INITIALIZERS:
        return _INITIALIZER

    if visibility in _RESTRICTED_RANKS:
        return _get_restricted_rank(member, visibility=visibility, decorators=decorators)

    return _get_public_rank(member, visibility=visibility, decorators=decorators)


def _get_restricted_rank(
    member: ast.FunctionDef | ast.AsyncFunctionDef, *, visibility: source.Visibility, decorators: AbstractSet[str]
) -> int:
    # Protected abstract members precede concrete ones within each kind; private members retain their order.
    property_rank, sync_rank, async_rank = _RESTRICTED_RANKS[visibility]
    offset: Final[int] = (
        _CONCRETE_OFFSET
        if visibility is source.Visibility.PROTECTED and not _is_abstract(member, decorators=decorators)
        else 0
    )
    if len(decorators & source.PROPERTY_DECORATORS) > 0:
        return property_rank + offset

    return (async_rank if isinstance(member, ast.AsyncFunctionDef) else sync_rank) + offset


def _get_public_rank(
    member: ast.FunctionDef | ast.AsyncFunctionDef, *, visibility: source.Visibility, decorators: AbstractSet[str]
) -> int:
    # Abstract before concrete inside the subgroup, per the ordering rule.
    offset: Final[int] = 0 if _is_abstract(member, decorators=decorators) else _CONCRETE_OFFSET
    if len(decorators & source.PROPERTY_DECORATORS) > 0:
        return _PUBLIC_PROPERTY + offset

    static_rank, magic_rank, instance_rank = (
        (_PUBLIC_ASYNC_STATIC_METHOD, _PUBLIC_ASYNC_MAGIC_METHOD, _PUBLIC_ASYNC_METHOD)
        if isinstance(member, ast.AsyncFunctionDef)
        else (_PUBLIC_STATIC_METHOD, _PUBLIC_MAGIC_METHOD, _PUBLIC_SYNC_METHOD)
    )
    if len(decorators & _STATIC_DECORATORS) > 0:
        return static_rank + offset

    if visibility is source.Visibility.MAGIC:
        return magic_rank + offset

    return instance_rank + offset


def _is_factory(member: ast.FunctionDef | ast.AsyncFunctionDef, *, decorators: AbstractSet[str]) -> bool:
    if member.returns is None or ast.unparse(member.returns) != "Self":
        return False

    return "classmethod" in decorators or member.name == "__new__"


def _is_abstract(member: ast.FunctionDef | ast.AsyncFunctionDef, *, decorators: AbstractSet[str]) -> bool:
    if "abstractmethod" in decorators:
        return True

    # A `Protocol` member declares itself by raising: the stub rule spells an unimplemented body
    # `raise NotImplementedError`, never `...`.
    body: Final[list[ast.stmt]] = member.body[1:] if ast.get_docstring(member) is not None else member.body
    if len(body) != 1:
        return False

    statement: Final[ast.stmt] = body[0]
    if not isinstance(statement, ast.Raise) or statement.exc is None:
        return False

    # The raised type itself, not a substring of the rendered source: a concrete method whose
    # message merely quotes the name is not abstract, and a search would have called it one.
    raised: Final[ast.expr] = statement.exc.func if isinstance(statement.exc, ast.Call) else statement.exc
    return isinstance(raised, ast.Name) and raised.id == "NotImplementedError"


def _get_assigned_positions(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[int]:
    parameters: Final[list[str]] = [argument.arg for argument in source.get_parameters(function)]
    positions: Final[list[int]] = []
    statement: ast.stmt
    for statement in function.body:
        value: ast.expr | None = statement.value if isinstance(statement, ast.AnnAssign | ast.Assign) else None
        if _get_attribute_target(statement) is None or not isinstance(value, ast.Name):
            continue

        if value.id in parameters:
            positions.append(parameters.index(value.id))

    return positions


def _get_attribute_target(statement: ast.stmt) -> ast.Attribute | None:
    if isinstance(statement, ast.AnnAssign):
        return statement.target if isinstance(statement.target, ast.Attribute) else None

    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        return statement.targets[0] if isinstance(statement.targets[0], ast.Attribute) else None

    return None
