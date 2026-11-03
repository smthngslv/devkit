"""PostgreSQL column types with validated JSON and UTC datetime conversion.

Migration revisions using these types import ``devkit.db.types`` so their
rendered type paths resolve.
"""

import datetime as dt
from enum import StrEnum
from typing import Any, ClassVar, Final, Self, final, override

import pydantic
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from devkit.types.utc_datetime import to_utc

__all__: Final[tuple[str, ...]] = ("JSONB", "UTCDateTime", "get_enum_values")


def get_enum_values[EnumType: StrEnum](values: type[EnumType]) -> list[str]:
    """Return StrEnum values for SQLAlchemy's PostgreSQL enum.

    Use `postgresql.ENUM(Status, name="status", values_callable=get_enum_values)`.
    For `Status.READY.value == "ready"`, the database stores "ready" instead of "READY".
    """
    return [item.value for item in values]


@final
class JSONB[Value](sa.TypeDecorator[Value]):
    """Store a Pydantic-validated value in PostgreSQL JSONB.

    Pass a model type or ``TypeAdapter``. Values are validated and dumped to
    JSON-compatible data on writes, then restored to the declared Python type
    on reads. ``None`` passes through for nullable columns.
    """

    # SQLAlchemy's EventTarget types __slots__ as an instance variable, but this is class configuration.
    __slots__: ClassVar[tuple[str, ...]] = ()  # type: ignore[misc]
    # SQLAlchemy's type declarations mark class configuration as instance attributes.
    cache_ok: ClassVar[bool | None] = True  # type: ignore[misc]  # pyright: ignore[reportIncompatibleVariableOverride]
    # SQLAlchemy constructs the dialect type from this class.
    impl: ClassVar[sa.types.TypeEngine[Any] | type[sa.types.TypeEngine[Any]]] = postgresql.JSONB  # type: ignore[misc]  # pyright: ignore[reportIncompatibleVariableOverride]

    def __init__(self: Self, /, model: type[Value] | pydantic.TypeAdapter[Value]) -> None:
        # SQLAlchemy reads constructor-named public attributes when building its statement cache key.
        self.model: Final[type[Value] | pydantic.TypeAdapter[Value]] = model
        self.__adapter: Final[pydantic.TypeAdapter[Value]] = (
            model if isinstance(model, pydantic.TypeAdapter) else pydantic.TypeAdapter(model)
        )
        super().__init__(none_as_null=True)

    @override
    def process_bind_param(self: Self, /, value: Value | None, dialect: sa.Dialect) -> Any:
        """Validate and serialize a value for PostgreSQL JSONB."""
        return (
            self.__adapter.dump_python(self.__adapter.validate_python(value), mode="json", by_alias=True)
            if value is not None
            else None
        )

    @override
    def process_result_value(self: Self, /, value: Any, dialect: sa.Dialect) -> Value | None:
        """Restore a JSONB value to its declared Python type."""
        return self.__adapter.validate_python(value) if value is not None else None


@final
class UTCDateTime(sa.TypeDecorator[dt.datetime]):
    """Store aware datetimes as UTC without timezone information.

    Naive inputs are rejected. Reads restore ``datetime.UTC``. ``None`` passes
    through for nullable columns. For model fields and annotations, use
    ``devkit.types.UTCDateTime`` instead of this SQLAlchemy column type.
    """

    # SQLAlchemy's EventTarget types __slots__ as an instance variable, but this is class configuration.
    __slots__: ClassVar[tuple[str, ...]] = ()  # type: ignore[misc]
    # SQLAlchemy's type declarations mark class configuration as instance attributes.
    cache_ok: ClassVar[bool | None] = True  # type: ignore[misc]  # pyright: ignore[reportIncompatibleVariableOverride]
    # SQLAlchemy constructs the dialect type from this class.
    impl: ClassVar[sa.types.TypeEngine[Any] | type[sa.types.TypeEngine[Any]]] = postgresql.TIMESTAMP  # type: ignore[misc]  # pyright: ignore[reportIncompatibleVariableOverride]

    @override
    def process_bind_param(self: Self, /, value: dt.datetime | None, dialect: sa.Dialect) -> dt.datetime | None:
        """Normalize an aware value and store it without timezone data."""
        if value is None:
            return None

        return to_utc(value).replace(tzinfo=None)

    @override
    def process_result_value(self: Self, /, value: dt.datetime | None, dialect: sa.Dialect) -> dt.datetime | None:
        """Restore UTC timezone information on a database value."""
        return value.replace(tzinfo=dt.UTC) if value is not None else None
