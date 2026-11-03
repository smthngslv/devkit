# PostgreSQL template

The database API and shared types live in `src/devkit/db/` and `src/devkit/types/`. Their docstrings describe
configuration, session modes, pooling, column types, and tracing. Add application tables under
`src/devkit/db/tables/`.

## Example

```python
from typing import ClassVar, Final, final

import logfire
import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
from sqlalchemy.dialects import postgresql

from devkit import db
from devkit.db.settings import Settings
from devkit.types import Entity, UTCDateTime


@final
class ItemData(Entity):
    label: str


@final
class Item(db.tables.Table):
    # SQLAlchemy types __slots__ as an instance variable, but this is class configuration.
    __slots__: ClassVar[tuple[str, ...]] = ()  # type: ignore[misc]
    __tablename__: str = "items"

    id: sa_orm.Mapped[int] = sa_orm.mapped_column(postgresql.INTEGER, primary_key=True)
    name: sa_orm.Mapped[str] = sa_orm.mapped_column(postgresql.TEXT, nullable=False)
    data: sa_orm.Mapped[ItemData] = sa_orm.mapped_column(db.types.JSONB(ItemData), nullable=False)
    created_at: sa_orm.Mapped[UTCDateTime] = sa_orm.mapped_column(
        db.types.UTCDateTime, nullable=False, server_default=sa.func.timezone("UTC", sa.func.now())
    )


async def add_item(service: db.Service, item_id: int, name: str) -> None:
    session: db.Session[db.TX]
    async with service.tx() as session:
        await session.execute(sa.insert(Item).values(id=item_id, name=name))


async def main() -> None:
    logfire.configure(send_to_logfire="if-token-present")
    # Pydantic Settings supplies this required field from the environment at runtime.
    settings: Final[Settings] = Settings()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
    service: db.Service
    async with db.Service(str(settings.url), options=settings.options) as service:
        await add_item(service, item_id=1, name="example")
```

## Migrations

Import each application table module in `src/devkit/db/migrations/env.py` before generating a revision. From the
repository root, run:

```sh
uv run alembic -c pyproject.toml revision --autogenerate -m "describe change"
uv run alembic -c pyproject.toml upgrade head
```

Review generated migrations before applying them. The template has no schema revision until an application adds
its tables. Revisions that use custom column types import `devkit.db.types`.

## Tests

The default unit and smoke tests compile PostgreSQL DDL and inspect packaging without opening a network connection.
Add integration tests against a disposable PostgreSQL instance when adding tables or migrations.
