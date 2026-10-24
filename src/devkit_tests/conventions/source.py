import ast
import dataclasses
import io
import pathlib
import tokenize
from collections.abc import Iterable, Iterator, Mapping, Sequence, Set as AbstractSet
from enum import StrEnum, unique
from typing import Final, Never, final

import devkit
import devkit_tests

__all__: Final[tuple[str, ...]] = (
    "PACKAGE_ROOT",
    "PRAGMA_PREFIXES",
    "PROPERTY_DECORATORS",
    "SCRIPTS_ROOT",
    "SOURCE_ROOT",
    "TESTS_ROOT",
    "Comment",
    "LogicalLine",
    "Scope",
    "Visibility",
    "get_bound_names",
    "get_canonical_order",
    "get_comments",
    "get_decorator_names",
    "get_defined_name",
    "get_functions",
    "get_import_time_expressions",
    "get_logical_lines",
    "get_module_id",
    "get_module_level_names",
    "get_module_paths",
    "get_nested_statements",
    "get_parameters",
    "get_referenced_names",
    "get_scope_statements",
    "get_visibility",
    "is_protocol",
    "parse",
    "read",
)

# The scopes a name can be bound in. A class body is deliberately absent: its names are members, reached
# through the class rather than bound alongside the code that reads them.
type Scope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef

# The directory each package occupies, read off the package rather than spelled again as a path. Both are
# walked, because the conventions are not narrower inside the tests: `devkit_tests` declares what it
# offers and hides what it does not, exactly like the code it exercises.
PACKAGE_ROOT: Final[pathlib.Path] = pathlib.Path(next(iter(devkit.__path__)))

TESTS_ROOT: Final[pathlib.Path] = pathlib.Path(devkit_tests.__file__).parent

# What both sit in, and what every path in a failure message is reported relative to.
SOURCE_ROOT: Final[pathlib.Path] = TESTS_ROOT.parent

# The operator scripts, which the src layout keeps out of the wheel. Walked like the two packages: ruff
# and mypy already read them, and a rule that stops at the package boundary is a rule the next module
# written outside it will break -- which is what happened to the module privacy rule, in a script
# nothing was checking.
SCRIPTS_ROOT: Final[pathlib.Path] = SOURCE_ROOT.parent / "scripts"

# The pragmas a tool reads positionally, and therefore the only comments allowed to sit inline. Spelled
# once, so the comment rule and the suppression rule cannot drift apart.
#
# These three and no others, one per tool: noqa is ruff's, type is mypy's, pyright is pyright's. The
# file-level forms are absent deliberately -- nothing here uses one, and a file-wide suppression is not
# something to wave through as an inline pragma. Spelled without their leading hash, because ruff reads
# a directive out of any comment that carries one, including this one.
PRAGMA_PREFIXES: Final[tuple[str, ...]] = ("# noqa", "# pyright:", "# type:")

# What the receiver and ordering checks both have to recognise. Spelled once, so the
# two gates cannot drift apart on what a property is.
PROPERTY_DECORATORS: Final[frozenset[str]] = frozenset({"cached_property", "property", "setter"})

# Tokens that carry no statement of their own, so none of them starts a logical line.
_IGNORED_TOKENS: Final[frozenset[int]] = frozenset(
    {tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER, tokenize.ENCODING}
)


def get_module_paths() -> list[pathlib.Path]:
    # No annotation on `root`: a comprehension owns its own scope, so one declared out here would be dead
    # (the annotation rule asks for the annotation once per scope, and this is not that scope).
    return sorted(path for root in (PACKAGE_ROOT, TESTS_ROOT, SCRIPTS_ROOT) for path in root.rglob("*.py"))


def get_module_id(path: pathlib.Path) -> str:
    if path.is_relative_to(SOURCE_ROOT):
        return str(path.relative_to(SOURCE_ROOT))

    # A script is named from the repository root, so it reads as `scripts/bump_deps.py` rather than as
    # the bare file name a second package could also have.
    if path.is_relative_to(SCRIPTS_ROOT.parent):
        return str(path.relative_to(SCRIPTS_ROOT.parent))

    # A fixture written to `tmp_path` is outside the tree, and naming it in a failure message is not
    # worth an exception; the absolute path is the best identifier there is for one.
    return str(path)


def read(path: pathlib.Path) -> str:
    return path.read_text()


def parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text())


def get_bound_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}

    if isinstance(target, ast.Starred):
        return get_bound_names(target.value)

    if isinstance(target, ast.Tuple | ast.List):
        return {name for element in target.elts for name in get_bound_names(element)}

    return set()


def get_defined_name(node: ast.stmt) -> str | None:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name

    if isinstance(node, ast.TypeAlias):
        return node.name.id

    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id

    if isinstance(node, ast.Assign):
        target: ast.expr
        for target in node.targets:
            if isinstance(target, ast.Name):
                return target.id

    return None


def get_scope_statements(scope: Scope) -> Iterator[ast.stmt]:
    # Everything the scope executes, stopping where a nested scope begins. An `if` or a `try` is not a
    # scope -- a name bound inside one is bound out here -- but a `def` and a `class` are.
    #
    # `Scope` rather than `ast.AST`: reaching `body` by `getattr` with an empty default made a node this
    # function did not understand yield nothing, and nothing is indistinguishable from a clean scope
    # (the gate policy -- when a check cannot be performed, refuse). The union is a type error at the call site.
    pending: Final[list[ast.stmt]] = list(scope.body)
    node: ast.stmt
    while len(pending) > 0:
        node = pending.pop(0)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue

        yield node
        pending.extend(get_nested_statements(node))


def get_nested_statements(node: ast.stmt) -> list[ast.stmt]:
    # `ast.ExceptHandler` and `ast.match_case` are not `ast.stmt` -- they descend from `ast.excepthandler`
    # and `ast.AST` -- so filtering children on `stmt` silently drops every statement under an `except`
    # or a `case`. They are reached through their own `body` instead.
    statements: Final[list[ast.stmt]] = []
    child: ast.AST
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            statements.append(child)

        elif isinstance(child, ast.ExceptHandler | ast.match_case):
            statements.extend(child.body)

    return statements


def get_module_level_names(tree: ast.Module) -> Iterator[str]:
    pending: Final[list[ast.stmt]] = list(tree.body)
    node: ast.stmt
    while len(pending) > 0:
        node = pending.pop(0)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield node.name
            continue

        yield from _get_statement_names(node)
        pending.extend(get_nested_statements(node))


def get_import_time_expressions(node: ast.stmt, *, is_annotation_forced: bool = False) -> list[ast.expr]:
    # What actually runs when this statement executes. A function body does not, so a helper may be
    # defined below its caller; a constant's value does, so a constant built from a class follows it.
    if isinstance(node, ast.AnnAssign):
        expressions: list[ast.expr] = [] if node.value is None else [node.value]
        # `@dataclasses.dataclass` reads `__annotations__`, which evaluates the field annotations.
        if is_annotation_forced:
            expressions.append(node.annotation)

        return expressions

    if isinstance(node, ast.Assign):
        return [node.value]

    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        expressions = [*node.decorator_list, *_get_defaults(node.args)]
        # A decorator may introspect the signature -- `include_args_` on the tracing decorators calls
        # `inspect.signature`, and pytest's fixture machinery does the same -- and under PEP 649 that
        # forces the annotations to be evaluated right there, at decoration time.
        if is_annotation_forced or len(node.decorator_list) > 0:
            expressions.extend(_get_annotations(node))

        return expressions

    if isinstance(node, ast.ClassDef):
        # A class body runs at class creation, so what its members evaluate runs with it. Their
        # annotations do not: a method's decorator forces its own signature at decoration time, but only
        # a class-level decorator that reads `__annotations__` -- `@dataclasses.dataclass` -- forces the
        # field annotations, and that is the one this has to model.
        expressions = [*node.bases, *node.decorator_list, *(keyword.value for keyword in node.keywords)]
        member: ast.stmt
        for member in node.body:
            if isinstance(member, ast.AnnAssign | ast.Assign):
                expressions.extend(get_import_time_expressions(member, is_annotation_forced=_is_dataclass(node)))

            elif isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                expressions.extend([*member.decorator_list, *_get_defaults(member.args)])

        return expressions

    return []


def get_referenced_names(expressions: Iterable[ast.expr]) -> set[str]:
    return {
        referenced.id
        for expression in expressions
        for referenced in ast.walk(expression)
        if isinstance(referenced, ast.Name)
    }


def get_canonical_order(
    names: Sequence[str], *, ranks: Mapping[str, int], requires: Mapping[str, AbstractSet[str]]
) -> list[str]:
    # Lowest rank first, original position as the tie-break, but never before something it needs. This is
    # the ordering rule's order wherever Python permits it, and only ever deviates where it does not.
    #
    # Positions rather than names, because a name can appear twice -- a `@property` and its `@x.setter`
    # bind one -- and a set of placed *names* can never select the second of a pair. The loop then ran
    # dry with the answer half-built, and returning the input verbatim read as "already canonical",
    # switching the gate off for the whole scope.
    declared: Final[AbstractSet[str]] = set(names)
    canonical: Final[list[str]] = []
    placed: Final[set[int]] = set()
    satisfied: Final[set[str]] = set()
    # Not `Final`: both are rebound on every pass, and mypy rejects a `Final` declared inside a loop.
    ready: list[int]
    chosen: int
    while len(canonical) < len(names):
        ready = [
            index
            for index in range(len(names))
            if index not in placed and (requires[names[index]] & declared) <= satisfied
        ]
        # Fail closed: a cycle means the order cannot be computed, and a gate that green-lights
        # what it could not answer is worse than one that stops.
        if len(ready) == 0:
            _refuse_cycle(names, placed=placed)

        chosen = min(ready, key=lambda index: (ranks[names[index]], index))
        canonical.append(names[chosen])
        placed.add(chosen)
        satisfied.add(names[chosen])

    return canonical


def get_visibility(name: str) -> Visibility:
    if name.startswith("__") and name.endswith("__"):
        return Visibility.MAGIC

    if name.startswith("__"):
        return Visibility.PRIVATE

    if name.startswith("_"):
        return Visibility.PROTECTED

    return Visibility.PUBLIC


def get_decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> frozenset[str]:
    # The trailing attribute only: `@dataclasses.dataclass(...)` and `@dataclass` name the same decorator
    # to every rule that asks about one, and the call arguments never carry its identity.
    return frozenset(_get_decorator_name(decorator) for decorator in node.decorator_list)


def get_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    return [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]


def get_functions(tree: ast.AST) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    node: ast.AST
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def is_protocol(node: ast.ClassDef) -> bool:
    base: ast.expr
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True

        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True

    return False


def get_comments(source: str) -> list[Comment]:
    lines: Final[Sequence[str]] = source.splitlines()
    comments: Final[list[Comment]] = []
    token: tokenize.TokenInfo
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue

        comments.append(
            Comment(
                row=token.start[0],
                text=token.string,
                is_own_line=len(lines[token.start[0] - 1][: token.start[1]].strip()) == 0,
                is_pragma=token.string.startswith(PRAGMA_PREFIXES),
            )
        )

    return comments


def get_logical_lines(source: str) -> list[LogicalLine]:
    # Where each statement or clause header starts. A continuation inside brackets emits `NL` rather than
    # `NEWLINE`, so a wrapped call stays one logical line, while `else` and `except` head their own --
    # which is what lets the spacing rule see the dedent into them.
    logical: Final[list[LogicalLine]] = []
    is_line_pending: bool = True
    token: tokenize.TokenInfo
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.NEWLINE:
            is_line_pending = True

        elif token.type not in _IGNORED_TOKENS:
            if is_line_pending:
                logical.append(LogicalLine(row=token.start[0], column=token.start[1]))

            is_line_pending = False

    return logical


def _get_statement_names(node: ast.stmt) -> Iterator[str]:
    if isinstance(node, ast.Import | ast.ImportFrom):
        yield from (alias.asname if alias.asname is not None else alias.name.partition(".")[0] for alias in node.names)

    elif isinstance(node, ast.TypeAlias):
        yield node.name.id

    elif isinstance(node, ast.AnnAssign | ast.AugAssign | ast.For | ast.AsyncFor):
        yield from get_bound_names(node.target)

    elif isinstance(node, ast.Assign):
        yield from (name for target in node.targets for name in get_bound_names(target))

    elif isinstance(node, ast.With | ast.AsyncWith):
        yield from (
            name
            for item in node.items
            if item.optional_vars is not None
            for name in get_bound_names(item.optional_vars)
        )

    elif isinstance(node, ast.Try | ast.TryStar):
        yield from (handler.name for handler in node.handlers if handler.name is not None)

    elif isinstance(node, ast.Match):
        yield from _get_pattern_names(node)


def _get_pattern_names(node: ast.Match) -> Iterator[str]:
    case: ast.match_case
    for case in node.cases:
        pattern: ast.AST
        for pattern in ast.walk(case.pattern):
            if isinstance(pattern, ast.MatchAs | ast.MatchStar) and pattern.name is not None:
                yield pattern.name

            elif isinstance(pattern, ast.MatchMapping) and pattern.rest is not None:
                yield pattern.rest


def _refuse_cycle(names: Sequence[str], *, placed: AbstractSet[int]) -> Never:
    remaining: Final[list[str]] = [names[index] for index in range(len(names)) if index not in placed]
    message: Final[str] = f"Definitions {remaining} require each other, so no order satisfies them."
    raise ValueError(message)


def _is_dataclass(node: ast.ClassDef) -> bool:
    return "dataclass" in get_decorator_names(node)


def _get_decorator_name(decorator: ast.expr) -> str:
    expression: Final[ast.expr] = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(expression, ast.Attribute):
        return expression.attr

    return expression.id if isinstance(expression, ast.Name) else ast.unparse(expression)


def _get_annotations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    annotations: Final[list[ast.expr]] = [] if node.returns is None else [node.returns]
    # `ast.walk` is typed as yielding `AST`; the narrowing below is what makes each one an `arg`.
    element: ast.AST
    for element in ast.walk(node.args):
        if isinstance(element, ast.arg) and element.annotation is not None:
            annotations.append(element.annotation)

    return annotations


def _get_defaults(arguments: ast.arguments) -> list[ast.expr]:
    return [default for default in [*arguments.defaults, *arguments.kw_defaults] if default is not None]


@final
@unique
# pyright does not see that `StrEnum` initializes `_value_` for its members, so a `@final` StrEnum reads
# to it as a final class with an uninitialized inherited attribute.
class Visibility(StrEnum):  # pyright: ignore[reportUninitializedInstanceVariable]
    MAGIC = "magic"
    PUBLIC = "public"
    PROTECTED = "protected"
    PRIVATE = "private"


@final
@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class Comment:
    row: int
    text: str
    is_own_line: bool
    is_pragma: bool


@final
@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class LogicalLine:
    row: int
    column: int
