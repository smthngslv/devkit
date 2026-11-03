"""Check comment placement, punctuation, and suppression reasons."""

import pathlib
import re
from collections.abc import Sequence
from typing import Final

import pytest

from devkit_tests.conventions import source

__all__: Final[tuple[str, ...]] = (
    "test_comment_blocks_end_in_a_period",
    "test_every_suppression_carries_its_reason",
    "test_no_reason_is_chained_onto_a_pragma",
    "test_only_pragmas_are_written_inline",
)

# Each `#`-introduced run inside one comment token. A pragma is machine syntax and a reason is prose, so
# a line carrying both has to be split before either can be read.
_SEGMENTS: Final[re.Pattern[str]] = re.compile(r"#[^#]*")

# A shebang is the kernel's, not a reader's: it is machine syntax that has to be the first line of a file
# and nowhere else, so it is exempt from the prose rule for exactly the reason a pragma is.
_SHEBANG: Final[str] = "#!"

_SHEBANG_ROW: Final[int] = 1


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_only_pragmas_are_written_inline(path: pathlib.Path) -> None:
    """Keep explanatory comments above the code they describe.

    Reject `value = 1  # Explanation.` but allow inline tool directives such as
    `# noqa: E501`. Tokenization distinguishes comments from hash characters in
    strings. This makes prose readable before the code while preserving tool syntax.
    """
    offenders: Final[list[str]] = [
        f"  line {comment.row}: {comment.text}"
        for comment in source.get_comments(source.read(path))
        if not comment.is_own_line and not comment.is_pragma
    ]

    assert offenders == [], f"{source.get_module_id(path)} writes comments inline:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_comment_blocks_end_in_a_period(path: pathlib.Path) -> None:
    """Require a period at the end of each standalone prose comment block.

    A wrapped comment needs a period only on its final line. Ignore empty comments,
    tool directives, and a first-line shebang. This applies the house punctuation
    style without treating machine-readable directives as prose.
    """
    rows: Final[frozenset[int]] = frozenset(
        comment.row
        for comment in source.get_comments(source.read(path))
        if comment.is_own_line and not comment.is_pragma
    )
    offenders: Final[list[str]] = []
    comment: source.Comment
    for comment in source.get_comments(source.read(path)):
        if not comment.is_own_line or comment.is_pragma or comment.row + 1 in rows:
            continue

        if comment.row == _SHEBANG_ROW and comment.text.startswith(_SHEBANG):
            continue

        text: str = comment.text.lstrip("#").strip()
        if len(text) > 0 and not text.endswith("."):
            offenders.append(f"  line {comment.row}: {comment.text}")

    assert offenders == [], f"{source.get_module_id(path)} ends comment blocks without a period:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_every_suppression_carries_its_reason(path: pathlib.Path) -> None:
    """Require an explanation immediately above each diagnostic suppression.

    A blank comment or another pragma is not an explanation. For a decorated
    function, place the reason between the last decorator and the definition if
    the suppression is on the definition. The check verifies placement and that
    text exists; a reviewer must still judge whether the reason is convincing.
    """
    lines: Final[Sequence[str]] = source.read(path).splitlines()
    offenders: Final[list[str]] = []
    comment: source.Comment
    for comment in source.get_comments(source.read(path)):
        if not comment.is_pragma:
            continue

        above: str = lines[comment.row - 2].strip() if comment.row >= 2 else ""
        if (
            not above.startswith("#")
            or above.startswith((*source.PRAGMA_PREFIXES, _SHEBANG))
            or len(above.lstrip("#").strip()) == 0
        ):
            offenders.append(f"  line {comment.row}: {comment.text}")

    assert offenders == [], (
        f"{source.get_module_id(path)} suppresses a diagnostic without a reason above it:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_no_reason_is_chained_onto_a_pragma(path: pathlib.Path) -> None:
    """Reject prose appended to an inline tool directive.

    For example, `# noqa: E501  # Explanation` must move its explanation above
    the code. A second tool directive is allowed so mypy and Pyright can each
    suppress their own diagnostic. This separates human explanations from tool syntax.
    """
    offenders: Final[list[str]] = []
    comment: source.Comment
    for comment in source.get_comments(source.read(path)):
        if not comment.is_pragma:
            continue

        chained: list[str] = [segment for segment in _SEGMENTS.findall(comment.text)[1:] if len(segment.strip()) > 1]
        if any(not segment.strip().startswith(source.PRAGMA_PREFIXES) for segment in chained):
            offenders.append(f"  line {comment.row}: {comment.text}")

    assert offenders == [], f"{source.get_module_id(path)} chains prose onto a pragma:\n" + "\n".join(offenders)
