"""Message: ${message}

Revision ID: ${up_revision}
Revises: ${down_revision if down_revision else "-"}
Create Date: ${create_date}
"""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
${imports if imports else ""}

import devkit.db.types


__all__: Final[tuple[str, ...]] = ("branch_labels", "depends_on", "down_revision", "downgrade", "revision", "upgrade")

# Revision identifiers, used by Alembic.
revision: Final[str] = ${repr(up_revision)}
down_revision: Final[str | None] = ${repr(down_revision)}
branch_labels: Final[str | Sequence[str] | None] = ${repr(branch_labels)}
depends_on: Final[str | Sequence[str] | None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
