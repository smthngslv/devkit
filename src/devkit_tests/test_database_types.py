"""Exercise PostgreSQL JSON, datetime, and enum types."""

import datetime as dt
from enum import StrEnum
from typing import Final, cast, final

import pydantic
import pytest
import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
from sqlalchemy.dialects import postgresql

import devkit.db.types as db_types
from devkit.db import tables

__all__: Final[tuple[str, ...]] = ()


def test_jsonb_validates_and_restores_pydantic_model() -> None:
    """Serialize a model with field aliases and restore its declared Python type after a JSONB read."""
    column: Final[db_types.JSONB[Payload]] = db_types.JSONB(Payload)
    dialect: Final[sa.Dialect] = postgresql.dialect()
    payload: Final[Payload] = Payload(itemId=7, count=2)
    assert column.process_bind_param(payload, dialect) == {"itemId": 7, "count": 2}
    assert column.process_result_value({"itemId": 7, "count": 2}, dialect) == payload
    assert column.process_bind_param(None, dialect) is None
    assert column.process_result_value(None, dialect) is None


def test_jsonb_accepts_adapter_for_parameterized_type() -> None:
    """Use a TypeAdapter to store and restore a typed list, which cannot be passed as a plain model class."""
    adapter: Final[pydantic.TypeAdapter[list[Payload]]] = pydantic.TypeAdapter(list[Payload])
    column: Final[db_types.JSONB[list[Payload]]] = db_types.JSONB(adapter)
    dialect: Final[sa.Dialect] = postgresql.dialect()
    payload: Final[list[Payload]] = [Payload(itemId=7, count=2)]
    assert column.process_bind_param(payload, dialect) == [{"itemId": 7, "count": 2}]
    assert column.process_result_value([{"itemId": 7, "count": 2}], dialect) == payload


def test_jsonb_rejects_invalid_values() -> None:
    """Reject invalid input before writing and invalid database JSON when reading it back."""
    column: Final[db_types.JSONB[Payload]] = db_types.JSONB(Payload)
    dialect: Final[sa.Dialect] = postgresql.dialect()
    with pytest.raises(pydantic.ValidationError, match="count"):
        column.process_bind_param(cast("Payload", {"itemId": 7, "count": "bad"}), dialect)

    with pytest.raises(pydantic.ValidationError, match="count"):
        column.process_result_value({"itemId": 7, "count": "bad"}, dialect)


def test_utc_datetime_normalizes_and_restores_timezone() -> None:
    """Store an aware +04:00 value as naive UTC and restore the UTC timezone on a database read."""
    column: Final[db_types.UTCDateTime] = db_types.UTCDateTime()
    dialect: Final[sa.Dialect] = postgresql.dialect()
    source: Final[dt.datetime] = dt.datetime(2026, 1, 2, 12, 30, tzinfo=dt.timezone(dt.timedelta(hours=4)))
    stored: Final[dt.datetime | None] = column.process_bind_param(source, dialect)
    assert stored == dt.datetime(2026, 1, 2, 8, 30, tzinfo=dt.UTC).replace(tzinfo=None)
    assert column.process_result_value(stored, dialect) == dt.datetime(2026, 1, 2, 8, 30, tzinfo=dt.UTC)
    assert column.process_bind_param(None, dialect) is None
    assert column.process_result_value(None, dialect) is None


def test_utc_datetime_rejects_naive_input() -> None:
    """Fail before writing a datetime whose timezone is unknown, avoiding a silent offset error."""
    column: Final[db_types.UTCDateTime] = db_types.UTCDateTime()
    aware: Final[dt.datetime] = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    with pytest.raises(ValueError, match="without timezone"):
        column.process_bind_param(aware.replace(tzinfo=None), postgresql.dialect())


def test_custom_types_compile_to_postgresql_columns() -> None:
    """Compile both custom types into PostgreSQL DDL without opening a database connection."""

    class Example(tables.Table):
        __tablename__ = "typed_examples"

        id: sa_orm.Mapped[int] = sa_orm.mapped_column(postgresql.INTEGER, primary_key=True)
        payload: sa_orm.Mapped[Payload] = sa_orm.mapped_column(db_types.JSONB(Payload), nullable=False)
        created_at: sa_orm.Mapped[dt.datetime] = sa_orm.mapped_column(db_types.UTCDateTime, nullable=False)

    table: Final[sa.Table] = cast("sa.Table", Example.__table__)
    sql: Final[str] = str(sa.schema.CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "JSONB" in sql
    assert "TIMESTAMP WITHOUT TIME ZONE" in sql


def test_enum_values_callable_uses_values_instead_of_member_names() -> None:
    """Make SQLAlchemy persist StrEnum values such as 'ready' rather than Python member names such as 'READY'."""

    @final
    # Enum supplies its internal value field when it creates each member.
    class Status(StrEnum):  # pyright: ignore[reportUninitializedInstanceVariable]
        READY = "ready"
        DONE = "done"

    column_type: Final[postgresql.ENUM] = postgresql.ENUM(
        Status, name="status", values_callable=db_types.get_enum_values
    )
    assert db_types.get_enum_values(Status) == ["ready", "done"]
    assert column_type.enums == ["ready", "done"]


@final
# Pydantic initializes BaseModel's generated internals when it creates the subclass.
class Payload(pydantic.BaseModel):  # pyright: ignore[reportUninitializedInstanceVariable]
    """Sample aliased model for JSONB serialization tests."""

    item_id: int = pydantic.Field(alias="itemId")
    count: int
