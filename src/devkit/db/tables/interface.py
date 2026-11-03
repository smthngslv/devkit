"""Declarative base for application-owned PostgreSQL tables."""

from typing import ClassVar, Final

import sqlalchemy.ext.asyncio as sa_async
import sqlalchemy.orm as sa_orm

__all__: Final[tuple[str, ...]] = ("Table",)


class Table(sa_async.AsyncAttrs, sa_orm.DeclarativeBase):
    """Base for async ORM tables whose columns use PostgreSQL dialect types.

    Define mapped subclasses in ``devkit.db.tables`` and import them in the
    Alembic environment before comparing metadata for autogeneration.
    """

    # SQLAlchemy's Inspectable types __slots__ as an instance variable, but this is class configuration.
    __slots__: ClassVar[tuple[str, ...]] = ()  # type: ignore[misc]
