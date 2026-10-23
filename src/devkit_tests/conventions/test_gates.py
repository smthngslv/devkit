import dataclasses
import pathlib
from collections.abc import Callable
from typing import Final, final

import pytest

from devkit_tests.conventions import (
    test_annotations,
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

# Enough of a module for the gate under test to have something to read, and nothing else. Every fixture
# below starts from this, so a case shows only the line it is about.
_HEADER: Final[str] = "from typing import IO, Final, Self\n\n__all__: Final[tuple[str, ...]] = ()\n"


def test_every_other_gate_is_covered() -> None:
    covered: Final[frozenset[str]] = frozenset(case.gate.__name__ for case in _CASES)
    declared: Final[frozenset[str]] = frozenset(
        name
        for module in (
            test_annotations,
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
        for name in module.__all__
        if name.startswith("test_")
    )

    assert declared == covered, (
        f"Gates with no firing case: {sorted(declared - covered)}. Cases naming no gate: "
        f"{sorted(covered - declared)}. Every checker carries both halves."
    )


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


_CASES: Final[tuple[_Case, ...]] = (
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
)


# The case section 40 calls mandatory and the suite had no coverage of at all. Every other module here
# asserts over this repository, which is green by construction -- so a checker whose match logic is
# broken reports nothing, and reporting nothing is indistinguishable from passing. Three defects lived in
# exactly that blind spot: an unreachable exemption in the section 39 gate, and two routes by which
# `get_canonical_order` returned its input and read as "already ordered".
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.gate.__name__)
def test_the_gate_reports_a_violation(case: _Case, tmp_path: pathlib.Path) -> None:
    with pytest.raises(AssertionError):
        case.gate(_write(case.violating, path=tmp_path, name=case.name))


# The other half: a gate that fires on everything is as useless as one that fires on nothing, and it is
# the half that catches a false positive -- which is how the section 39 exemption was found.
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.gate.__name__)
def test_the_gate_passes_compliant_source(case: _Case, tmp_path: pathlib.Path) -> None:
    case.gate(_write(case.clean, path=tmp_path, name=case.name))
