"""Check module and function size ceilings."""

import ast
import pathlib
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "MAXIMUM_FUNCTION_LINES",
    "MAXIMUM_MODULE_LINES",
    "test_no_function_exceeds_its_line_limit",
    "test_no_module_exceeds_its_line_limit",
)

# The size limit's hard limits. The targets below them -- 500 lines for a module, 50 for a function -- are
# pressure to extract rather than a failure, so only the ceilings are gated: a check that fires at the
# target would be a check nobody could keep green, and one nobody keeps green stops being read.
MAXIMUM_MODULE_LINES: Final[int] = 1000

MAXIMUM_FUNCTION_LINES: Final[int] = 150


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_no_module_exceeds_its_line_limit(path: pathlib.Path) -> None:
    """Reject modules longer than the configured physical-line ceiling.

    Count code, comments, and blank lines; allow exactly the limit. This is a
    coarse prompt to split oversized modules, not a measurement of code quality.
    The limit is defined beside this test so its enforcement has one source.
    """
    lines: Final[int] = len(source.read(path).splitlines())

    assert lines <= MAXIMUM_MODULE_LINES, (
        f"{source.get_module_id(path)} is {lines} lines, over the size limit's hard limit of "
        f"{MAXIMUM_MODULE_LINES}. Extract, or write down why this module cannot be split."
    )


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_no_function_exceeds_its_line_limit(path: pathlib.Path) -> None:
    """Reject sync or async functions longer than the configured line ceiling.

    Count from the def line through the final body statement, including intervening
    comments, docstrings, and blank lines. Decorators and trailing blank lines are
    excluded. Include methods and nested functions, and allow exactly the limit.
    This keeps large bodies visible even when they are nested in another definition.
    """
    offenders: Final[list[str]] = []
    function: ast.FunctionDef | ast.AsyncFunctionDef
    for function in source.get_functions(source.parse(path)):
        lines: int = (function.end_lineno if function.end_lineno is not None else function.lineno) - function.lineno + 1
        if lines > MAXIMUM_FUNCTION_LINES:
            offenders.append(f"  {function.name} (line {function.lineno}) is {lines} lines")

    assert offenders == [], (
        f"{source.get_module_id(path)} defines functions over the size limit's hard limit of "
        f"{MAXIMUM_FUNCTION_LINES} lines:\n" + "\n".join(offenders)
    )
