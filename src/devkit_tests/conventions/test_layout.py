import io
import pathlib
import tokenize
from collections.abc import Sequence
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "test_a_dedent_is_preceded_by_a_blank_line",
    "test_split_strings_keep_the_space_on_the_line_above",
)

# Tokens that neither end a run of concatenated strings nor start a statement, so a run reads across them.
_IGNORED_TOKENS: Final[frozenset[int]] = frozenset({tokenize.COMMENT, tokenize.DEDENT, tokenize.INDENT, tokenize.NL})

_QUOTES: Final[str] = "\"'"

_TRIPLE_QUOTES: Final[tuple[str, ...]] = ('"""', "'''")

# How a string part ends when the next one may legitimately open with a space: written as an escape or as
# the character itself, since a raw or triple-quoted literal carries the real one.
_TRAILING_WHITESPACE: Final[tuple[str, ...]] = (" ", "\t", "\n", "\\n", "\\t")


# Section 28: a blank line wherever the indentation decreases -- leaving any indented block, and between
# an `if` body and its `else` or a `try` body and its `except`. Nothing in ruff or the formatter checks
# it, and without it the eye reads a dedented statement as the last line of the block it just left.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_a_dedent_is_preceded_by_a_blank_line(path: pathlib.Path) -> None:
    text: Final[str] = source.read(path)
    lines: Final[Sequence[str]] = text.splitlines()
    logical: Final[Sequence[source.LogicalLine]] = source.get_logical_lines(text)
    offenders: Final[list[str]] = []
    index: int
    for index in range(1, len(logical)):
        if logical[index].column >= logical[index - 1].column:
            continue

        if not _is_preceded_by_a_blank_line(lines, row=logical[index].row):
            offenders.append(f"  line {logical[index].row}: {lines[logical[index].row - 1].strip()}")

    assert offenders == [], (
        f"{source.get_module_id(path)} dedents without a blank line above (section 28):\n" + "\n".join(offenders)
    )


# Section 39: when a string is split across lines by implicit concatenation, the space goes at the end of
# the line that owns it. Led with, it hides at the left margin against the indentation, and the two
# halves read as though the words had run together.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_split_strings_keep_the_space_on_the_line_above(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = [
        f"  line {row}" for row in _get_continuations_leading_with_a_space(source.read(path))
    ]

    assert offenders == [], (
        f"{source.get_module_id(path)} starts a continued string with a space (section 39):\n" + "\n".join(offenders)
    )


def _is_preceded_by_a_blank_line(lines: Sequence[str], *, row: int) -> bool:
    # Past any comment block sitting on the statement: a comment belongs to what follows it, so the blank
    # line the rule asks for goes above the comment rather than between it and its statement.
    scan: int = row - 1
    while scan >= 1 and lines[scan - 1].strip().startswith("#"):
        scan -= 1

    return scan < 1 or len(lines[scan - 1].strip()) == 0


def _get_continuations_leading_with_a_space(text: str) -> list[int]:
    rows: Final[list[int]] = []
    # Where the previous string literal started and how it ended, or `None` for "the last token was not
    # a string", which is what makes two adjacent literals a concatenation rather than two expressions.
    previous: int | None = None
    ending: str = ""
    depth: int = 0
    start: int = 0
    content: str = ""
    tail: str = ""
    # Whether the next token opens an f-string's text, and whether the last one seen closed it. An
    # f-string is a run of tokens rather than one, and its interpolations are tokens too, so only the
    # first and last literal pieces say anything about how the string begins and ends.
    is_leading: bool = False
    is_tail_literal: bool = False
    token: tokenize.TokenInfo
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.FSTRING_START:
            depth += 1
            if depth == 1:
                start, content, tail = token.start[0], "", ""
                is_leading, is_tail_literal = True, False

        elif token.type == tokenize.FSTRING_END:
            depth -= 1
            if depth == 0:
                rows.extend(_get_offending_row(content, previous=previous, start=start, ending=ending))
                # A part closing on an interpolation ends in a value nobody reading the source can see,
                # so it is taken as already separated rather than guessed at.
                previous, ending = start, tail if is_tail_literal else " "

        elif depth > 0:
            if token.type == tokenize.FSTRING_MIDDLE:
                content = token.string if is_leading else content
                tail, is_tail_literal = token.string, True

            else:
                is_tail_literal = False

            is_leading = False

        elif token.type == tokenize.STRING:
            content, start = _get_content(token.string), token.start[0]
            rows.extend(_get_offending_row(content, previous=previous, start=start, ending=ending))
            previous, ending = start, content

        elif token.type not in _IGNORED_TOKENS:
            previous = None

    return rows


def _get_offending_row(content: str, *, previous: int | None, start: int, ending: str) -> list[int]:
    # Only a literal continuing one that ended on an earlier line: a space inside a single-line pair is
    # the space between two words, and a list of strings is no concatenation at all.
    if previous is None or previous >= start or not content.startswith(" "):
        return []

    # A part that already ends in whitespace is not the case the rule is about: the space at the start of
    # this one is then indentation inside the text rather than the separator between two words.
    return [] if ending.endswith(_TRAILING_WHITESPACE) else [start]


def _get_content(text: str) -> str:
    index: int = 0
    while index < len(text) and text[index] not in _QUOTES:
        index += 1

    opening: Final[str] = text[index : index + 3]
    quote: Final[str] = opening if opening in _TRIPLE_QUOTES else text[index : index + 1]
    # Both quotes, not just the opening one: the closing quote left on the end made `ending` never look
    # like whitespace, so the exemption for a part that already ends in a space was dead for every plain
    # string and the gate fired on legal code.
    return text[index + len(quote) : len(text) - len(quote)]
