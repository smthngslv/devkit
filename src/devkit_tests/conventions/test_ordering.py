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

# Section 33's module order, as the rank each kind of definition sorts to. Visibility is the outer key for
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

# Section 33's class order: attributes by visibility, then factories, `__init__`, properties, sync, async,
# protected, private, and `__del__` last. Subgroups are spaced by two so abstract-before-concrete fits
# inside each one as `_CONCRETE_OFFSET`.
_MAGIC_ATTRIBUTE: Final[int] = 0
_PUBLIC_ATTRIBUTE: Final[int] = 2
_PROTECTED_ATTRIBUTE: Final[int] = 4
_PRIVATE_ATTRIBUTE: Final[int] = 6
_PUBLIC_FACTORY: Final[int] = 8
_PROTECTED_FACTORY: Final[int] = 10
_PRIVATE_FACTORY: Final[int] = 12
_INITIALIZER: Final[int] = 14
_PUBLIC_PROPERTY: Final[int] = 16
_PUBLIC_STATIC_METHOD: Final[int] = 18
_PUBLIC_MAGIC_METHOD: Final[int] = 20
_PUBLIC_SYNC_METHOD: Final[int] = 22
_PUBLIC_ASYNC_METHOD: Final[int] = 24
_PROTECTED_PROPERTY: Final[int] = 26
_PROTECTED_SYNC_METHOD: Final[int] = 28
_PROTECTED_ASYNC_METHOD: Final[int] = 30
_PRIVATE_PROPERTY: Final[int] = 32
_PRIVATE_SYNC_METHOD: Final[int] = 34
_PRIVATE_ASYNC_METHOD: Final[int] = 36
_DELETER: Final[int] = 38

# Added inside a subgroup, so an abstract member precedes the concrete ones it shares the subgroup with.
_CONCRETE_OFFSET: Final[int] = 1

# Construction, whatever the layout mechanism spells it. `__post_init__` is a dataclass's `__init__` and
# `__new__` is a hand-written one, so both sort where the rule puts initialization rather than among the
# magic methods -- section 33 names only `__init__` because it does not discuss the other two.
_INITIALIZERS: Final[frozenset[str]] = frozenset({"__init__", "__new__", "__post_init__"})

_STATIC_DECORATORS: Final[frozenset[str]] = frozenset({"classmethod", "staticmethod"})

# Section 33 orders class attributes magic, then public, then private. Protected sits between the two:
# it is reachable from a subclass and so is less hidden than private, and no further from the top than
# that. Total over `Visibility`, so a new visibility cannot be added without answering where it sorts.
_ATTRIBUTE_RANKS: Final[dict[source.Visibility, int]] = {
    source.Visibility.MAGIC: _MAGIC_ATTRIBUTE,
    source.Visibility.PUBLIC: _PUBLIC_ATTRIBUTE,
    source.Visibility.PROTECTED: _PROTECTED_ATTRIBUTE,
    source.Visibility.PRIVATE: _PRIVATE_ATTRIBUTE,
}

# Property, sync, async -- the three subgroups section 33 gives a member that is not public, in order.
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


# Section 33's module order: type aliases, then constants, then functions (sync before async), then
# classes, public before private. Deviation is allowed only where Python's execution order requires it,
# which is exactly what the canonical order models -- so a file passes when it already is what the rule
# would produce (section 7).
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_module_definitions_are_ordered(path: pathlib.Path) -> None:
    body: Final[Sequence[ast.stmt]] = source.parse(path).body
    actual: Final[list[str]] = _get_module_names(body)
    canonical: Final[list[str]] = source.get_canonical_order(
        actual, ranks=_get_module_ranks(body), requires=_get_module_requirements(body)
    )

    assert actual == canonical, (
        f"{source.get_module_id(path)} defines its module members out of order (section 33). Expected:\n"
        f"  {' -> '.join(canonical)}\ngot:\n  {' -> '.join(actual)}"
    )


# The same rule one scope down. A class body executes at class creation, so the same two forces apply: the
# rule's order wherever Python permits it, and what the body actually evaluates where it does not --
# `Tracer.logfire` is a property whose name is also the module `logfire` that `__init__`'s default reads,
# so it cannot be defined before `__init__` without changing what that default resolves to.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_class_members_are_ordered(path: pathlib.Path) -> None:
    tree: Final[ast.Module] = source.parse(path)
    shadowed: Final[frozenset[str]] = frozenset(source.get_module_level_names(tree))
    offenders: Final[list[str]] = []
    node: ast.AST
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        actual: list[str] = _get_member_names(node, shadowed=shadowed)
        canonical: list[str] = source.get_canonical_order(
            actual,
            ranks=_get_member_ranks(node, shadowed=shadowed),
            requires=_get_member_requirements(node, shadowed=shadowed),
        )
        if actual != canonical:
            offenders.append(f"  {node.name} (line {node.lineno}): expected {canonical}, got {actual}")

    assert offenders == [], f"{source.get_module_id(path)} orders class members against section 33:\n" + "\n".join(
        offenders
    )


# Section 33's attribute assignment: what a method stores follows the order it was handed the values in.
# Reading a signature against the body it fills should never mean jumping around.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_attributes_are_assigned_in_parameter_order(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = []
    function: ast.FunctionDef | ast.AsyncFunctionDef
    for function in source.get_functions(source.parse(path)):
        positions: list[int] = _get_assigned_positions(function)
        if positions != sorted(positions):
            offenders.append(f"  {function.name} (line {function.lineno}) stores parameters as {positions}")

    assert offenders == [], (
        f"{source.get_module_id(path)} assigns attributes out of parameter order (section 33):\n" + "\n".join(offenders)
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


# A member whose name is also a module-level name in the same file is placed by what that shadowing
# allows rather than by section 33: from its definition onwards the class body reads the member, so every
# default and every annotation naming the module has to be evaluated above it. `Tracer.logfire` is the
# case -- the position is forced by `__init__`'s default and by every signature returning a
# `logfire.LogfireSpan`, and no ordering rule can be stated over a name that means two things.
def _get_member_names(node: ast.ClassDef, *, shadowed: AbstractSet[str]) -> list[str]:
    return [
        name
        for member in node.body
        if (name := source.get_defined_name(member)) is not None
        and name not in shadowed
        and _get_member_rank(member) is not None
    ]


def _get_member_ranks(node: ast.ClassDef, *, shadowed: AbstractSet[str]) -> dict[str, int]:
    names: Final[frozenset[str]] = frozenset(_get_member_names(node, shadowed=shadowed))
    return {
        name: rank
        for member in node.body
        if (name := source.get_defined_name(member)) in names and (rank := _get_member_rank(member)) is not None
    }


def _get_member_requirements(node: ast.ClassDef, *, shadowed: AbstractSet[str]) -> dict[str, set[str]]:
    # An edge in the direction the file already has it, because both directions are real: a member read by
    # an earlier member's decorator or default must precede it, and a member whose name shadows a module
    # global that an earlier member reads must follow it. At most one of the two holds for any pair, and
    # the file is what says which -- reordering against either changes what a name resolves to.
    #
    # Annotations count here where they do not at module scope: a signature inside a class body resolves
    # its names against that body, so `Tracer.span` returning a `logfire.LogfireSpan` is what pins the
    # `Tracer.logfire` property below it, whatever PEP 649 defers at runtime.
    names: Final[list[str]] = _get_member_names(node, shadowed=shadowed)
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
    # Protected and private members go properties, then sync, then async, with no abstract split: section
    # 33 asks for one only above them, and nothing here declares an abstract member that is not public.
    property_rank, sync_rank, async_rank = _RESTRICTED_RANKS[visibility]
    if len(decorators & source.PROPERTY_DECORATORS) > 0:
        return property_rank

    return async_rank if isinstance(member, ast.AsyncFunctionDef) else sync_rank


def _get_public_rank(
    member: ast.FunctionDef | ast.AsyncFunctionDef, *, visibility: source.Visibility, decorators: AbstractSet[str]
) -> int:
    # Abstract before concrete inside the subgroup, per section 33.
    offset: Final[int] = 0 if _is_abstract(member, decorators=decorators) else _CONCRETE_OFFSET
    if len(decorators & source.PROPERTY_DECORATORS) > 0:
        return _PUBLIC_PROPERTY + offset

    # A public async method sorts by nothing finer than async: section 33 gives it the same subgroups as
    # sync, but no async static or async magic method exists here for that split to discriminate.
    if isinstance(member, ast.AsyncFunctionDef):
        return _PUBLIC_ASYNC_METHOD + offset

    if len(decorators & _STATIC_DECORATORS) > 0:
        return _PUBLIC_STATIC_METHOD + offset

    if visibility is source.Visibility.MAGIC:
        return _PUBLIC_MAGIC_METHOD + offset

    return _PUBLIC_SYNC_METHOD + offset


def _is_factory(member: ast.FunctionDef | ast.AsyncFunctionDef, *, decorators: AbstractSet[str]) -> bool:
    if member.returns is None or ast.unparse(member.returns) != "Self":
        return False

    return "classmethod" in decorators or member.name == "__new__"


def _is_abstract(member: ast.FunctionDef | ast.AsyncFunctionDef, *, decorators: AbstractSet[str]) -> bool:
    if "abstractmethod" in decorators:
        return True

    # A `Protocol` member declares itself by raising: section 36 spells an unimplemented body
    # `raise NotImplementedError`, never `...`.
    if len(member.body) != 1:
        return False

    statement: Final[ast.stmt] = member.body[0]
    if not isinstance(statement, ast.Raise) or statement.exc is None:
        return False

    # The raised type itself, not a substring of the rendered source (section 6): a concrete method whose
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
