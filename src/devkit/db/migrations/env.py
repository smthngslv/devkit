"""Run online Alembic migrations against the configured async database.

Import each application table module here before autogeneration so its metadata
is registered. Alembic reads ``[tool.alembic]`` from ``pyproject.toml``; this
template does not use ``alembic.ini`` or support offline migrations.
"""

import asyncio
from typing import Final

import alembic.context
import sqlalchemy as sa
import sqlalchemy.ext.asyncio as sa_async

from devkit.db import tables
from devkit.db.service import Service
from devkit.db.settings import Settings

__all__: Final[tuple[str, ...]] = ()


def _on_run_migrations_callback(connection: sa.engine.Connection, /) -> None:
    alembic.context.configure(
        connection=connection, target_metadata=tables.Table.metadata, sqlalchemy_module_prefix="sa."
    )
    with alembic.context.begin_transaction():
        alembic.context.run_migrations()


async def _run_migrations_online() -> None:
    # Pydantic Settings obtains this required value from the environment at runtime.
    settings: Final[Settings] = Settings()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]

    db_service: Service
    db_connection: sa_async.AsyncConnection
    async with (
        Service(str(settings.url), options=settings.options) as db_service,
        db_service.get_engine().begin() as db_connection,
    ):
        await db_connection.run_sync(_on_run_migrations_callback)


if alembic.context.is_offline_mode():
    message: Final[str] = "Offline migrations are not supported."
    raise NotImplementedError(message)

asyncio.run(_run_migrations_online())
