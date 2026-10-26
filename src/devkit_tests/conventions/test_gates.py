import ast
import dataclasses
import pathlib
import re
from collections.abc import Callable
from typing import Final, final

import pytest

from devkit_tests.conventions import (
    source,
    test_annotations,
    test_calls,
    test_comments,
    test_exports,
    test_layout,
    test_naming,
    test_ordering,
    test_privacy,
    test_signatures,
    test_size,
    test_statements,
)

__all__: Final[tuple[str, ...]] = ()

# A common prefix for fixtures that need a module export declaration. Fixtures are parsed, not executed,
# and need to satisfy only the checker selected by their case.
_HEADER: Final[str] = "from typing import IO, Final, Self\n\n__all__: Final[tuple[str, ...]] = ()\n"


def test_every_other_gate_is_covered() -> None:
    """Require a positive and negative fixture for every convention checker.

    Discover checker functions from the other test modules rather than trusting
    a manually maintained export list. Compare module-qualified names so two
    functions with the same short name do not hide missing coverage. This catches
    a newly added checker that was never tested against intentionally bad code.
    """
    covered: Final[frozenset[str]] = frozenset(
        f"{case.gate.__module__.rpartition('.')[2]}.{case.gate.__name__}" for case in _CASES
    )
    declared: Final[frozenset[str]] = frozenset(
        f"{path.stem}.{node.name}"
        for path in pathlib.Path(__file__).parent.glob("test_*.py")
        if path.name != pathlib.Path(__file__).name
        for node in source.parse(path).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_")
    )

    assert declared == covered, (
        f"Gates with no firing case: {sorted(declared - covered)}. Cases naming no gate: "
        f"{sorted(covered - declared)}. Every checker carries both halves."
    )


@pytest.mark.parametrize(
    ("names", "ranks", "requires", "expected"),
    [
        pytest.param(["a", "b"], {"a": 1, "b": 0}, {"a": set[str](), "b": set[str]()}, ["b", "a"], id="rank"),
        pytest.param(["a", "b"], {"a": 1, "b": 0}, {"a": set[str](), "b": {"a"}}, ["a", "b"], id="dependency"),
        pytest.param(["b", "a"], {"a": 0, "b": 0}, {"a": set[str](), "b": set[str]()}, ["b", "a"], id="stable-tie"),
        pytest.param(
            ["a", "a", "b"], {"a": 1, "b": 0}, {"a": set[str](), "b": set[str]()}, ["b", "a", "a"], id="duplicates"
        ),
        pytest.param(["a"], {"a": 0}, {"a": {"external"}}, ["a"], id="external-reference"),
        pytest.param([], {}, {}, [], id="empty"),
    ],
)
def test_definition_sorting_preserves_dependencies_and_duplicates(
    names: list[str], ranks: dict[str, int], requires: dict[str, set[str]], expected: list[str]
) -> None:
    """Check the shared sorter independently of any particular syntax checker.

    Lower ranks go first unless a dependency must precede them. Equal ranks keep
    their input order, repeated names are retained, and outside references do not
    block sorting. These cases prevent a partial or reordered result from hiding
    a convention violation in every checker that relies on the sorter.
    """
    assert source.get_canonical_order(names, ranks=ranks, requires=requires) == expected


def test_definition_sorting_rejects_cycles() -> None:
    """Reject contradictory dependencies instead of silently accepting the input.

    If a requires b and b requires a, neither order is valid. Returning the
    original list would make the caller believe that invalid input was canonical.
    """
    with pytest.raises(ValueError, match="require each other"):
        source.get_canonical_order(["a", "b"], ranks={"a": 0, "b": 1}, requires={"a": {"b"}, "b": {"a"}})


@pytest.mark.parametrize("extra_lines", [0, 1], ids=("at-limit", "over-limit"))
def test_module_size_boundary(tmp_path: pathlib.Path, extra_lines: int) -> None:
    """Accept exactly the module line limit and reject one additional line.

    A large failing fixture alone cannot reveal an off-by-one comparison. Count
    physical lines here, including comments, to pin down the documented boundary.
    """
    path: Final[pathlib.Path] = _write(
        "# A line.\n" * (test_size.MAXIMUM_MODULE_LINES + extra_lines), path=tmp_path, name="probe.py"
    )
    if extra_lines == 0:
        test_size.test_no_module_exceeds_its_line_limit(path)

    else:
        with pytest.raises(AssertionError, match=re.escape(str(path))):
            test_size.test_no_module_exceeds_its_line_limit(path)


@pytest.mark.parametrize("prefix", ["def", "async def"], ids=("sync", "async"))
@pytest.mark.parametrize("extra_lines", [0, 1], ids=("at-limit", "over-limit"))
def test_function_size_boundary(tmp_path: pathlib.Path, prefix: str, extra_lines: int) -> None:
    """Count function size from the definition through its final body statement.

    Both sync and async functions may occupy exactly the configured limit. One
    additional body line must fail. This checks the boundary independently of
    the broad repository scan and avoids accidentally excluding async functions.
    """
    path: Final[pathlib.Path] = _write(
        f"{prefix} read():\n" + "    pass\n" * (test_size.MAXIMUM_FUNCTION_LINES - 1 + extra_lines),
        path=tmp_path,
        name="probe.py",
    )
    if extra_lines == 0:
        test_size.test_no_function_exceeds_its_line_limit(path)

    else:
        with pytest.raises(AssertionError, match=re.escape(str(path))):
            test_size.test_no_function_exceeds_its_line_limit(path)


@pytest.mark.parametrize("imported_module", ["events", "other"], ids=("actual-export", "unrelated-export"))
def test_namespace_exemption_belongs_to_the_exported_module(tmp_path: pathlib.Path, imported_module: str) -> None:
    """Apply a package namespace only to the class that the package actually exports.

    Exporting events.EventBus lets callers read it as package.EventBus. Importing
    a different EventBus from another module must not excuse the redundant name
    in events.py. This prevents an unrelated import from disabling the name check.
    """
    _write(f"from .{imported_module} import EventBus\n", path=tmp_path, name="__init__.py")
    path: Final[pathlib.Path] = _write(source="class EventBus:\n    pass\n", path=tmp_path, name="events.py")
    if imported_module == "events":
        test_naming.test_class_names_do_not_repeat_their_namespace(path)

    else:
        with pytest.raises(AssertionError, match=re.escape(str(path))):
            test_naming.test_class_names_do_not_repeat_their_namespace(path)


@pytest.mark.parametrize(
    "argument", ["30", "-30", "+30", "1.5", "-1.5", "1j", "'host'", "b'host'", "True", "None", "[]", "{}", "()", "{1}"]
)
def test_literal_call_gate_rejects_literal_forms(tmp_path: pathlib.Path, argument: str) -> None:
    """Reject scalar, signed, and container literals when the known parameter accepts a keyword.

    Negative numbers are unary expressions in Python's AST, so checking only
    constant nodes would miss `connect(-30)`. The error must identify both the
    source file and the parameter to name at the call site.
    """
    path: Final[pathlib.Path] = _write(
        source=f"def connect(timeout_s):\n    pass\n\nconnect({argument})\n", path=tmp_path, name="probe.py"
    )
    captured: pytest.ExceptionInfo[AssertionError]
    with pytest.raises(AssertionError) as captured:
        test_calls.test_literal_arguments_use_keywords(path)

    assert str(path) in str(captured.value)
    assert "timeout_s=..." in str(captured.value)


@pytest.mark.parametrize(
    ("snippet", "should_fail"),
    [
        pytest.param("def connect(timeout_s): pass\nconnect(timeout_s=30)\n", False, id="keyword"),
        pytest.param("def connect(timeout_s): pass\nconnect(Timeouts.DEFAULT)\n", False, id="enum"),
        pytest.param("def connect(timeout_s): pass\nconnect(timeout)\n", False, id="named-value"),
        pytest.param("def connect(timeout_s, /): pass\nconnect(30)\n", False, id="positional-only"),
        pytest.param("def connect(*values): pass\nconnect(30)\n", False, id="variadic"),
        pytest.param("def connect(host, /, timeout_s): pass\nconnect('host', 30)\n", True, id="mixed-parameters"),
        pytest.param("def connect(host, /, timeout_s): pass\nconnect('host', timeout_s=30)\n", False, id="mixed-valid"),
        pytest.param("def connect(timeout_s, *values): pass\nconnect(30, 40)\n", True, id="fixed-before-variadic"),
        pytest.param("def connect(timeout_s): pass\nconnect(30, *values)\n", False, id="starred-call"),
        pytest.param("def connect(timeout_s): pass\nconnect(*values, 30)\n", False, id="after-starred"),
        pytest.param("def connect(timeout_s, **kwargs): pass\nconnect(30, **options)\n", True, id="keyword-unpacking"),
        pytest.param("async def connect(timeout_s): pass\nasync def run():\n    await connect(30)\n", True, id="async"),
        pytest.param("def run():\n    def connect(timeout_s): pass\n    connect(30)\n", True, id="nested-function"),
        pytest.param("def connect(timeout_s): pass\ndef run():\n    connect(30)\n", True, id="outer-binding"),
        pytest.param(
            "def connect(timeout_s): pass\ndef run(connect):\n    connect(30)\n", False, id="parameter-shadow"
        ),
        pytest.param(
            "def connect(timeout_s): pass\ndef run():\n    connect = other\n    connect(30)\n",
            False,
            id="local-rebinding",
        ),
        pytest.param("def connect(timeout_s): pass\nconnect = other\nconnect(30)\n", False, id="module-rebinding"),
        pytest.param(
            "def connect(timeout_s): pass\ndef connect(timeout_s, /): pass\nconnect(30)\n", False, id="redefinition"
        ),
        pytest.param("@wrapper\ndef connect(timeout_s): pass\nconnect(30)\n", False, id="decorated-function"),
        pytest.param("from external import connect\nconnect(30)\n", False, id="import"),
        pytest.param(
            "def connect(timeout_s): pass\nfrom external import connect\nconnect(30)\n", False, id="import-shadow"
        ),
        pytest.param(
            "def connect(timeout_s): pass\nfrom external import *\nconnect(30)\n", False, id="wildcard-import"
        ),
        pytest.param("def connect(timeout_s): pass\nclient.connect(30)\n", False, id="method"),
        pytest.param("range(10)\n", False, id="builtin"),
        pytest.param(
            "def connect(timeout_s): pass\nclass Client:\n    def run(self):\n        connect(30)\n",
            True,
            id="call-in-method",
        ),
        pytest.param(
            "def connect(timeout_s): pass\nclass Client:\n    def connect(self, value): pass\n"
            "    def run(self):\n        connect(30)\n",
            True,
            id="class-members-are-not-closures",
        ),
        pytest.param(
            "def connect(timeout_s): pass\ndef run[connect]():\n    connect(30)\n", False, id="type-parameter-shadow"
        ),
        pytest.param(
            "def connect(timeout_s): pass\nclass Client[connect]:\n    def run(self):\n        connect(30)\n",
            False,
            id="class-type-parameter-shadow",
        ),
        pytest.param("def connect(timeout_s): pass\n(lambda connect: connect(30))(other)\n", False, id="lambda-scope"),
        pytest.param(
            "def connect(timeout_s): pass\n[connect(30) for connect in clients]\n", False, id="comprehension-scope"
        ),
        pytest.param(
            "def connect(timeout_s): pass\ndef run():\n    global connect\n    connect(30)\n",
            False,
            id="global-binding",
        ),
        pytest.param(
            "def run():\n    def connect(timeout_s): pass\n"
            "    def inner():\n        nonlocal connect\n        connect(30)\n",
            False,
            id="nonlocal-binding",
        ),
        pytest.param(
            "def connect(timeout_s): pass\ntry: pass\nexcept Error as connect:\n    connect(30)\n",
            False,
            id="exception-binding",
        ),
        pytest.param(
            "def connect(timeout_s): pass\nmatch value:\n    case {'client': connect}:\n        connect(30)\n",
            False,
            id="pattern-binding",
        ),
        pytest.param("def connect(timeout_s): pass\ndef run(value=connect(30)): pass\n", True, id="default-expression"),
        pytest.param("def connect(timeout_s): pass\n@connect(30)\ndef run(): pass\n", True, id="decorator-expression"),
    ],
)
def test_literal_call_gate_respects_signature_and_scope(
    tmp_path: pathlib.Path, snippet: str, *, should_fail: bool
) -> None:
    """Check literal calls only when their parameter names and function bindings are known.

    Cover positional-only and variadic APIs, readable enum members, nested and
    async functions, defaults, and decorators. Shadowing and unknown signatures
    must not borrow a same-named function's signature and report a false failure.
    These boundaries keep the checker safe without executing application code.
    """
    path: Final[pathlib.Path] = _write(source=snippet, path=tmp_path, name="probe.py")
    if should_fail:
        with pytest.raises(AssertionError, match="timeout_s"):
            test_calls.test_literal_arguments_use_keywords(path)

    else:
        test_calls.test_literal_arguments_use_keywords(path)


def _write(source: str, *, path: pathlib.Path, name: str) -> pathlib.Path:
    written: Final[pathlib.Path] = path / name
    written.write_text(source, encoding="utf-8")
    return written


# One gate, the smallest source that breaks it, and the smallest source that does not. The clean form has
# to satisfy *this* gate only -- it is fed to nothing else -- which is what keeps each pair to one idea.
@final
@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class _Case:
    gate: Callable[[pathlib.Path], None]
    violating: str
    clean: str
    # Only the namespace rule reads it, and for that rule the module name *is* the input.
    name: str = "probe.py"
    scenario: str = "basic"


_CASES: Final[tuple[_Case, ...]] = (
    _Case(
        gate=test_calls.test_literal_arguments_use_keywords,
        violating="def connect(timeout_s): pass\nconnect(30)\n",
        clean="def connect(timeout_s): pass\nconnect(timeout_s=30)\n",
    ),
    _Case(
        gate=test_annotations.test_loop_variables_are_annotated,
        violating=_HEADER + "\n\ndef read(rows: list[str]) -> None:\n    for row in rows:\n        print(row)\n",
        clean=_HEADER
        + "\n\ndef read(rows: list[str]) -> None:\n"
        + "    row: str\n    for row in rows:\n        print(row)\n",
    ),
    _Case(
        gate=test_annotations.test_with_targets_are_annotated,
        violating=_HEADER + '\n\ndef read() -> None:\n    with open("x") as handle:\n        print(handle)\n',
        clean=_HEADER
        + "\n\ndef read() -> None:\n    handle: IO[str]\n"
        + '    with open("x") as handle:\n        print(handle)\n',
    ),
    _Case(
        gate=test_annotations.test_bare_declarations_sit_above_what_they_annotate,
        violating=_HEADER
        + "\n\ndef read() -> None:\n    value: int\n    try:\n        value = 1\n\n"
        + "    except ValueError:\n        return\n\n    print(value)\n",
        clean=_HEADER
        + "\n\ndef read() -> None:\n    try:\n        value: int = 1\n\n"
        + "    except ValueError:\n        return\n\n    print(value)\n",
    ),
    _Case(
        gate=test_comments.test_only_pragmas_are_written_inline,
        violating=_HEADER + "\nVALUE: Final[int] = 1  # Counts the rows.\n",
        clean=_HEADER + "\n# Counts the rows.\nVALUE: Final[int] = 1\n",
    ),
    _Case(
        gate=test_comments.test_comment_blocks_end_in_a_period,
        violating=_HEADER + "\n# Counts the rows\nVALUE: Final[int] = 1\n",
        clean=_HEADER + "\n# Counts the rows.\nVALUE: Final[int] = 1\n",
    ),
    _Case(
        gate=test_comments.test_every_suppression_carries_its_reason,
        violating=_HEADER + "\nVALUE: Final[int] = 1  # noqa: E501\n",
        clean=_HEADER + "\n# The upstream stub is wrong about this one.\nVALUE: Final[int] = 1  # noqa: E501\n",
    ),
    _Case(
        gate=test_comments.test_no_reason_is_chained_onto_a_pragma,
        violating=_HEADER + "\n# The reason.\nVALUE: Final[int] = 1  # noqa: E501  # and a second thought\n",
        clean=_HEADER + "\n# The reason.\nVALUE: Final[int] = 1  # noqa: E501\n",
    ),
    _Case(gate=test_exports.test_every_module_declares_its_exports, violating="VALUE: int = 1\n", clean=_HEADER),
    _Case(
        gate=test_layout.test_a_dedent_is_preceded_by_a_blank_line,
        violating=_HEADER
        + "\n\ndef read(*, is_ready: bool) -> None:\n    if is_ready:\n        print(1)\n    print(2)\n",
        clean=_HEADER
        + "\n\ndef read(*, is_ready: bool) -> None:\n    if is_ready:\n        print(1)\n\n    print(2)\n",
    ),
    _Case(
        gate=test_layout.test_split_strings_keep_the_space_on_the_line_above,
        violating=_HEADER + '\nVALUE: Final[str] = (\n    "the space belongs"\n    " on the line above"\n)\n',
        clean=_HEADER + '\nVALUE: Final[str] = (\n    "the space belongs "\n    "on the line above"\n)\n',
    ),
    _Case(
        gate=test_naming.test_boolean_names_say_what_true_means,
        violating=_HEADER + "\n\ndef read(*, retry: bool = False) -> None:\n    print(retry)\n",
        clean=_HEADER + "\n\ndef read(*, should_retry: bool = False) -> None:\n    print(should_retry)\n",
    ),
    _Case(
        gate=test_naming.test_boolean_names_say_what_true_means,
        violating=_HEADER + "\nRETRY = True\n",
        clean=_HEADER + "\nSHOULD_RETRY = True\n",
    ),
    _Case(
        gate=test_naming.test_callback_parameters_are_named_as_callbacks,
        violating=_HEADER + "\n\ndef read(*, event_callback: object) -> None:\n    print(event_callback)\n",
        clean=_HEADER + "\n\ndef read(*, on_event_callback: object) -> None:\n    print(on_event_callback)\n",
    ),
    _Case(
        gate=test_naming.test_class_names_do_not_repeat_their_namespace,
        violating=_HEADER + "\n\nclass EventBus:\n    pass\n",
        clean=_HEADER + "\n\nclass Bus:\n    pass\n",
        name="events.py",
    ),
    _Case(
        gate=test_ordering.test_module_definitions_are_ordered,
        violating=_HEADER + "\n\nclass Record:\n    pass\n\n\nVALUE: Final[int] = 1\n",
        clean=_HEADER + "\nVALUE: Final[int] = 1\n\n\nclass Record:\n    pass\n",
    ),
    _Case(
        gate=test_ordering.test_class_members_are_ordered,
        violating=_HEADER
        + "\n\nclass Record:\n    def read(self: Self, /) -> None:\n        pass\n\n    VALUE: int = 1\n",
        clean=_HEADER + "\n\nclass Record:\n    VALUE: int = 1\n\n    def read(self: Self, /) -> None:\n        pass\n",
    ),
    _Case(
        gate=test_ordering.test_attributes_are_assigned_in_parameter_order,
        violating=_HEADER
        + "\n\nclass Record:\n    def __init__(self: Self, /, first: int, second: int) -> None:\n"
        + "        self.__second = second\n        self.__first = first\n",
        clean=_HEADER
        + "\n\nclass Record:\n    def __init__(self: Self, /, first: int, second: int) -> None:\n"
        + "        self.__first = first\n        self.__second = second\n",
    ),
    _Case(
        gate=test_privacy.test_no_module_level_name_is_double_underscored,
        violating=_HEADER + "\n__SECRET: Final[int] = 1\n",
        clean=_HEADER + "\n_SECRET: Final[int] = 1\n",
    ),
    _Case(
        gate=test_signatures.test_the_receiver_of_a_method_is_typed,
        violating=_HEADER + "\n\nclass Record:\n    def read(self, /) -> None:\n        pass\n",
        clean=_HEADER + "\n\nclass Record:\n    def read(self: Self, /) -> None:\n        pass\n",
    ),
    _Case(
        gate=test_signatures.test_methods_mark_their_receiver_positional_only,
        violating=_HEADER + "\n\nclass Record:\n    def read(self: Self) -> None:\n        pass\n",
        clean=_HEADER + "\n\nclass Record:\n    def read(self: Self, /) -> None:\n        pass\n",
    ),
    _Case(
        gate=test_signatures.test_positional_only_markers_earn_their_place,
        violating=_HEADER + "\n\ndef scale(value: int, /) -> int:\n    return value\n",
        clean=_HEADER + "\n\ndef scale(value: int) -> int:\n    return value\n",
    ),
    _Case(
        gate=test_size.test_no_module_exceeds_its_line_limit,
        violating=_HEADER + "# Filler.\n" * (test_size.MAXIMUM_MODULE_LINES + 1),
        clean=_HEADER + "# Filler.\n",
    ),
    _Case(
        gate=test_size.test_no_function_exceeds_its_line_limit,
        violating=_HEADER + "\n\ndef read() -> None:\n" + "    print(1)\n" * (test_size.MAXIMUM_FUNCTION_LINES + 1),
        clean=_HEADER + "\n\ndef read() -> None:\n    print(1)\n",
    ),
    _Case(
        gate=test_statements.test_the_type_of_an_object_is_read_through_its_class,
        violating=_HEADER + "\n\ndef name_of(value: object) -> str:\n    return type(value).__name__\n",
        clean=_HEADER + "\n\ndef name_of(value: object) -> str:\n    return value.__class__.__name__\n",
    ),
    _Case(
        gate=test_statements.test_removal_goes_through_a_method_rather_than_del,
        violating=_HEADER + "\n\ndef drop(rows: list[str]) -> None:\n    del rows[0]\n",
        clean=_HEADER + "\n\ndef drop(rows: list[str]) -> None:\n    rows.pop(0)\n",
    ),
    _Case(
        gate=test_signatures.test_methods_mark_their_receiver_positional_only,
        violating=("class Record:\n    def read(self):\n        pass\n"),
        clean=("class Record:\n    @staticmethod\n    def read(value: str):\n        pass\n"),
        name="probe.py",
        scenario="static-receiver",
    ),
    _Case(
        gate=test_signatures.test_the_receiver_of_a_method_is_typed,
        violating=("class Record:\n    def read(self, /):\n        pass\n"),
        clean=("class Record:\n    @staticmethod\n    def read(value: str):\n        pass\n"),
        name="probe.py",
        scenario="static-type",
    ),
    _Case(
        gate=test_signatures.test_the_receiver_of_a_method_is_typed,
        violating=("class Record:\n    @classmethod\n    def create(cls: Self, /):\n        pass\n"),
        clean=("class Record:\n    @classmethod\n    def create(cls: type[Self], /):\n        pass\n"),
        name="probe.py",
        scenario="class-receiver",
    ),
    _Case(
        gate=test_signatures.test_the_receiver_of_a_method_is_typed,
        violating=(
            "class Record(Protocol):\n"
            "    @property\n"
            "    def name(self: Self, /) -> str:\n"
            "        raise NotImplementedError\n"
        ),
        clean=(
            "class Record(Protocol):\n    @property\n    def name(self, /) -> str:\n        raise NotImplementedError\n"
        ),
        name="probe.py",
        scenario="protocol-property",
    ),
    _Case(
        gate=test_signatures.test_positional_only_markers_earn_their_place,
        violating=("class Record:\n    @staticmethod\n    def read(value: str, /):\n        pass\n"),
        clean=("class Record:\n    @staticmethod\n    def on_read(value: str, /):\n        pass\n"),
        name="probe.py",
        scenario="static-marker",
    ),
    _Case(
        gate=test_signatures.test_positional_only_markers_earn_their_place,
        violating=("def read(value: str, /):\n    pass\n"),
        clean=("def read(value: str, /, **attributes):\n    pass\n"),
        name="probe.py",
        scenario="kwargs-marker",
    ),
    _Case(
        gate=test_annotations.test_loop_variables_are_annotated,
        violating=("def read(rows):\n    for row in rows:\n        pass\n"),
        clean=("def read(rows):\n    for cache[index] in rows:\n        pass\n"),
        name="probe.py",
        scenario="target-expressions",
    ),
    _Case(
        gate=test_annotations.test_loop_variables_are_annotated,
        violating=("def read(row, rows):\n    for row in rows:\n        pass\n"),
        clean=("def read(row: str, rows):\n    for row in rows:\n        pass\n"),
        name="probe.py",
        scenario="annotated-parameter",
    ),
    _Case(
        gate=test_annotations.test_loop_variables_are_annotated,
        violating=("def read(rows):\n    for row in rows:\n        row: str\n"),
        clean=("def read(rows):\n    row: str\n    for row in rows:\n        row: str\n"),
        name="probe.py",
        scenario="first-declaration",
    ),
    _Case(
        gate=test_annotations.test_loop_variables_are_annotated,
        violating=("async def read(rows):\n    key: str\n    async for key, value in rows:\n        pass\n"),
        clean=(
            "async def read(rows):\n    key: str\n    value: int\n    async for key, value in rows:\n        pass\n"
        ),
        name="probe.py",
        scenario="unpacked-async",
    ),
    _Case(
        gate=test_annotations.test_bare_declarations_sit_above_what_they_annotate,
        violating=(
            "def read(rows):\n    value: int\n    for row in rows:\n        def inner():\n            value = 1\n"
        ),
        clean=("def read(rows):\n    value: int\n    for row in rows:\n        value = 1\n"),
        name="probe.py",
        scenario="nested-scope",
    ),
    _Case(
        gate=test_annotations.test_bare_declarations_sit_above_what_they_annotate,
        violating=('def read():\n    record: object\n    record.name = "x"\n'),
        clean=("def read():\n    record: object\n    record = object()\n"),
        name="probe.py",
        scenario="attribute-not-binding",
    ),
    _Case(
        gate=test_annotations.test_with_targets_are_annotated,
        violating=("async def read():\n    async with acquire() as handle:\n        pass\n"),
        clean=("async def read():\n    handle: object\n    async with acquire() as handle:\n        pass\n"),
        name="probe.py",
        scenario="async-context",
    ),
    _Case(
        gate=test_comments.test_every_suppression_carries_its_reason,
        violating=("#\nx = 1  # noqa: E501\n"),
        clean=("# The external format fixes this width.\nx = 1  # noqa: E501\n"),
        name="probe.py",
        scenario="empty-reason",
    ),
    _Case(
        gate=test_comments.test_comment_blocks_end_in_a_period,
        violating=("# Missing punctuation\nx = 1\n"),
        clean=("# This directive is required by the external tool.\n# type: ignore[assignment]\nx = 1\n"),
        name="probe.py",
        scenario="directive-not-prose",
    ),
    _Case(
        gate=test_privacy.test_no_module_level_name_is_double_underscored,
        violating=("if True:\n    def __read():\n        pass\n"),
        clean=("if True:\n    def _read():\n        pass\n"),
        name="probe.py",
        scenario="conditional-private",
    ),
    _Case(
        gate=test_privacy.test_no_module_level_name_is_double_underscored,
        violating=("__first, second = (1, 2)\n"),
        clean=("_first, second = (1, 2)\n"),
        name="probe.py",
        scenario="unpacked-private",
    ),
    _Case(
        gate=test_privacy.test_no_module_level_name_is_double_underscored,
        violating=("for __row in rows:\n    pass\n"),
        clean=("for _row in rows:\n    pass\n"),
        name="probe.py",
        scenario="loop-private",
    ),
    _Case(
        gate=test_privacy.test_no_module_level_name_is_double_underscored,
        violating=("type __Item = str\n"),
        clean=("type _Item = str\n"),
        name="probe.py",
        scenario="alias-private",
    ),
    _Case(
        gate=test_naming.test_boolean_names_say_what_true_means,
        violating=("retry: None | bool = None\n"),
        clean=("should_retry: None | bool = None\n"),
        name="probe.py",
        scenario="optional-bool",
    ),
    _Case(
        gate=test_naming.test_boolean_names_say_what_true_means,
        violating=("retry: ClassVar[Final[bool]] = False\n"),
        clean=("should_retry: ClassVar[Final[bool]] = False\n"),
        name="probe.py",
        scenario="nested-bool",
    ),
    _Case(
        gate=test_naming.test_boolean_names_say_what_true_means,
        violating=("retry = True\n"),
        clean=('settings["retry"] = True\n'),
        name="probe.py",
        scenario="indexed-bool",
    ),
    _Case(
        gate=test_statements.test_removal_goes_through_a_method_rather_than_del,
        violating=("def read(items):\n    del (items[0], (items[1],))\n"),
        clean=("def read(items):\n    del temporary\n"),
        name="probe.py",
        scenario="nested-deletion",
    ),
    _Case(
        gate=test_statements.test_the_type_of_an_object_is_read_through_its_class,
        violating=("value = type(item)\n"),
        clean=('value = type("Record", (), {})\n'),
        name="probe.py",
        scenario="constructor-type",
    ),
    _Case(
        gate=test_layout.test_a_dedent_is_preceded_by_a_blank_line,
        violating=("if ready:\n    read()\n# Finish the batch.\nfinish()\n"),
        clean=("if ready:\n    read()\n\n# Finish the batch.\nfinish()\n"),
        name="probe.py",
        scenario="comment-dedent",
    ),
    _Case(
        gate=test_layout.test_a_dedent_is_preceded_by_a_blank_line,
        violating=("if ready:\n    read()\nelse:\n    finish()\n"),
        clean=("if ready:\n    read()\n\nelse:\n    finish()\n"),
        name="probe.py",
        scenario="else-spacing",
    ),
    _Case(
        gate=test_layout.test_split_strings_keep_the_space_on_the_line_above,
        violating=('value = (\n    "hello"\n    " world"\n)\n'),
        clean=('value = (\n    "hello\\n"\n    "    world"\n)\n'),
        name="probe.py",
        scenario="string-indentation",
    ),
    _Case(
        gate=test_layout.test_split_strings_keep_the_space_on_the_line_above,
        violating=('value = (\n    f"hello"\n    f" world"\n)\n'),
        clean=('value = [\n    "hello",\n    " world",\n]\n'),
        name="probe.py",
        scenario="string-containers",
    ),
    _Case(
        gate=test_exports.test_every_module_declares_its_exports,
        violating=("value = 1\n"),
        clean=(""),
        name="__init__.py",
        scenario="empty-marker",
    ),
    _Case(
        gate=test_ordering.test_class_members_are_ordered,
        violating=(
            "class Record:\n"
            "    async def run(self):\n"
            "        pass\n"
            "\n"
            "    @staticmethod\n"
            "    async def parse():\n"
            "        pass\n"
        ),
        clean=(
            "class Record:\n"
            "    @staticmethod\n"
            "    async def parse():\n"
            "        pass\n"
            "\n"
            "    async def run(self):\n"
            "        pass\n"
        ),
        name="probe.py",
        scenario="async-order",
    ),
    _Case(
        gate=test_ordering.test_class_members_are_ordered,
        violating=(
            "class Record:\n"
            "    def _run(self):\n"
            "        pass\n"
            "\n"
            "    @abstractmethod\n"
            "    def _parse(self):\n"
            "        pass\n"
        ),
        clean=(
            "class Record:\n"
            "    @abstractmethod\n"
            "    def _parse(self):\n"
            "        pass\n"
            "\n"
            "    def _run(self):\n"
            "        pass\n"
        ),
        name="probe.py",
        scenario="protected-abstract",
    ),
    _Case(
        gate=test_ordering.test_class_members_are_ordered,
        violating=(
            "class Record:\n"
            "    def run(self):\n"
            "        pass\n"
            "\n"
            "    def parse(self):\n"
            '        """Parse the source."""\n'
            "        raise NotImplementedError\n"
        ),
        clean=(
            "class Record:\n"
            "    def parse(self):\n"
            '        """Parse the source."""\n'
            "        raise NotImplementedError\n"
            "\n"
            "    def run(self):\n"
            "        pass\n"
        ),
        name="probe.py",
        scenario="documented-abstract",
    ),
    _Case(
        gate=test_ordering.test_module_definitions_are_ordered,
        violating=("class Record:\n    pass\n\nVALUE = 1\n"),
        clean=("class Record:\n    pass\n\nVALUE = Record()\n"),
        name="probe.py",
        scenario="definition-dependency",
    ),
    _Case(
        gate=test_ordering.test_class_members_are_ordered,
        violating=(
            "class Record:\n"
            "    @property\n"
            "    def writable(self):\n"
            "        return 1\n"
            "\n"
            "    @writable.setter\n"
            "    def writable(self, value):\n"
            "        pass\n"
            "\n"
            "    @property\n"
            "    def readonly(self):\n"
            "        return 2\n"
        ),
        clean=(
            "class Record:\n"
            "    @property\n"
            "    def readonly(self):\n"
            "        return 2\n"
            "\n"
            "    @property\n"
            "    def writable(self):\n"
            "        return 1\n"
            "\n"
            "    @writable.setter\n"
            "    def writable(self, value):\n"
            "        pass\n"
        ),
        scenario="property-order",
    ),
    _Case(
        gate=test_ordering.test_class_members_are_ordered,
        violating=("value = 1\n\nclass Record:\n    def read(self):\n        pass\n\n    value = 2\n"),
        clean=("value = 1\n\nclass Record:\n    value = 2\n\n    def read(self):\n        pass\n"),
        scenario="shadowed-member",
    ),
    _Case(
        gate=test_ordering.test_class_members_are_ordered,
        violating=("value = 1\n\nclass Record:\n    def read(self):\n        pass\n\n    value = 2\n"),
        clean=("value = 1\n\nclass Record:\n    def read(self, item=value):\n        pass\n\n    value = 2\n"),
        scenario="shadow-dependency",
    ),
    _Case(
        gate=test_annotations.test_loop_variables_are_annotated,
        violating=("def read(rows):\n    key: str\n    for key, *values in rows:\n        pass\n"),
        clean=("def read(rows):\n    key: str\n    values: list[str]\n    for key, *values in rows:\n        pass\n"),
        scenario="nested-unpacking",
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: f"{case.gate.__name__}-{case.scenario}")
def test_the_gate_reports_a_violation(case: _Case, tmp_path: pathlib.Path) -> None:
    """Verify that each checker rejects its deliberately invalid example.

    Write a tiny Python file and call only the selected checker. Require its own
    assertion message to identify that file, so an unrelated internal assertion
    cannot masquerade as a successful rejection. These examples guard against
    checks that silently stop detecting the convention they are meant to enforce.
    """
    path: Final[pathlib.Path] = _write(case.violating, path=tmp_path, name=case.name)
    captured: pytest.ExceptionInfo[AssertionError]
    with pytest.raises(AssertionError) as captured:
        case.gate(path)

    assert str(path) in str(captured.value), "The checker must identify the file that violates the convention."


@pytest.mark.parametrize("case", _CASES, ids=lambda case: f"{case.gate.__name__}-{case.scenario}")
def test_the_gate_passes_compliant_source(case: _Case, tmp_path: pathlib.Path) -> None:
    """Verify that each checker accepts its matching valid example.

    Run only the selected checker: the example need not satisfy unrelated style
    rules. Pairing this with an invalid example catches checkers that reject
    everything, including documented exceptions and exact size boundaries.
    """
    case.gate(_write(case.clean, path=tmp_path, name=case.name))
