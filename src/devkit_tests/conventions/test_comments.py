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
# a line carrying both has to be split before either can be read (section 17).
_SEGMENTS: Final[re.Pattern[str]] = re.compile(r"#[^#]*")

# A shebang is the kernel's, not a reader's: it is machine syntax that has to be the first line of a file
# and nowhere else, so it is exempt from the prose rule for exactly the reason a pragma is (section 32).
_SHEBANG: Final[str] = "#!"

_SHEBANG_ROW: Final[int] = 1


# Section 32: the only inline comments permitted are tool pragmas, because a tool reads them positionally
# and they have nowhere else to go. Everything a human wrote sits on its own line, where it is read
# before the code rather than after it has already scrolled past the right margin.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_only_pragmas_are_written_inline(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = [
        f"  line {comment.row}: {comment.text}"
        for comment in source.get_comments(source.read(path))
        if not comment.is_own_line and not comment.is_pragma
    ]

    assert offenders == [], f"{source.get_module_id(path)} writes comments inline (section 32):\n" + "\n".join(
        offenders
    )


# Section 32: a comment ends with a period. The rule is about the block rather than the line -- a comment
# wrapped over four lines is one sentence -- so it is the last line of each run that has to close it.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_comment_blocks_end_in_a_period(path: pathlib.Path) -> None:
    rows: Final[frozenset[int]] = frozenset(
        comment.row for comment in source.get_comments(source.read(path)) if comment.is_own_line
    )
    offenders: Final[list[str]] = []
    comment: source.Comment
    for comment in source.get_comments(source.read(path)):
        if not comment.is_own_line or comment.row + 1 in rows:
            continue

        if comment.row == _SHEBANG_ROW and comment.text.startswith(_SHEBANG):
            continue

        text: str = comment.text.lstrip("#").strip()
        if len(text) > 0 and not text.endswith("."):
            offenders.append(f"  line {comment.row}: {comment.text}")

    assert offenders == [], (
        f"{source.get_module_id(path)} ends comment blocks without a period (section 32):\n" + "\n".join(offenders)
    )


# Section 17: every suppression carries its reason on the line above it. `RUF100` deletes the ones that
# stopped being needed, but only a reason tells a reader whether the rest are still true -- a bare pragma
# is indistinguishable from a rule nobody understood. For a decorated definition the reason sits between
# the last decorator and the `def`, which is the line above the pragma there too.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_every_suppression_carries_its_reason(path: pathlib.Path) -> None:
    lines: Final[Sequence[str]] = source.read(path).splitlines()
    offenders: Final[list[str]] = []
    comment: source.Comment
    for comment in source.get_comments(source.read(path)):
        if not comment.is_pragma:
            continue

        above: str = lines[comment.row - 2].strip() if comment.row >= 2 else ""
        if not above.startswith("#") or above.startswith(source.PRAGMA_PREFIXES):
            offenders.append(f"  line {comment.row}: {comment.text}")

    assert offenders == [], (
        f"{source.get_module_id(path)} suppresses a diagnostic without a reason above it (section 17):\n"
        + "\n".join(offenders)
    )


# Section 17's other half: never chain a second `#` comment onto a pragma. Mixing machine syntax and
# prose on one line makes both harder to read and pushes the line past the width limit.
@pytest.mark.parametrize("path", source.get_module_paths(), ids=source.get_module_id)
def test_no_reason_is_chained_onto_a_pragma(path: pathlib.Path) -> None:
    offenders: Final[list[str]] = []
    comment: source.Comment
    for comment in source.get_comments(source.read(path)):
        if not comment.is_pragma:
            continue

        chained: list[str] = [segment for segment in _SEGMENTS.findall(comment.text)[1:] if len(segment.strip()) > 1]
        if any(not segment.strip().startswith(source.PRAGMA_PREFIXES) for segment in chained):
            offenders.append(f"  line {comment.row}: {comment.text}")

    assert offenders == [], f"{source.get_module_id(path)} chains prose onto a pragma (section 17):\n" + "\n".join(
        offenders
    )
