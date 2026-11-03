"""Exercise shared model and datetime validation."""

import datetime as dt
from types import SimpleNamespace
from typing import Final, final

import pydantic
import pytest

from devkit.types import Entity, UTCDateTime, utc_datetime

__all__: Final[tuple[str, ...]] = ()


def test_entity_validates_defaults_and_attribute_input() -> None:
    """Reject an invalid default and read fields from an object when parsing an existing record."""
    with pytest.raises(pydantic.ValidationError, match="count"):
        _Example()

    parsed: Final[_Example] = _Example.model_validate(SimpleNamespace(count=2))
    assert parsed.count == 2


def test_entity_rejects_extra_fields_and_mutation() -> None:
    """Reject unexpected input and prevent changes to a validated entity after construction."""
    with pytest.raises(pydantic.ValidationError, match="extra_forbidden"):
        _Example.model_validate({"count": 2, "unknown": True})

    parsed: Final[_Example] = _Example(count=2)
    with pytest.raises(pydantic.ValidationError, match="frozen_instance"):
        parsed.count = 3


def test_utc_datetime_annotation_normalizes_aware_input() -> None:
    """Convert an aware +04:00 datetime to UTC during Pydantic validation."""
    adapter: Final[pydantic.TypeAdapter[dt.datetime]] = pydantic.TypeAdapter(UTCDateTime)
    source: Final[dt.datetime] = dt.datetime(2026, 1, 2, 12, 30, tzinfo=dt.timezone(dt.timedelta(hours=4)))
    assert adapter.validate_python(source) == dt.datetime(2026, 1, 2, 8, 30, tzinfo=dt.UTC)


def test_utc_datetime_rejects_naive_input() -> None:
    """Reject a datetime without timezone in both the shared converter and its Pydantic annotation."""
    adapter: Final[pydantic.TypeAdapter[dt.datetime]] = pydantic.TypeAdapter(UTCDateTime)
    naive: Final[dt.datetime] = dt.datetime(2026, 1, 2, 8, 30, tzinfo=dt.UTC).replace(tzinfo=None)
    with pytest.raises(ValueError, match="without timezone"):
        utc_datetime.to_utc(naive)

    with pytest.raises(pydantic.ValidationError, match="without timezone"):
        adapter.validate_python(naive)


@final
# Pydantic initializes BaseModel's generated internals when it creates the subclass.
class _Example(Entity):  # pyright: ignore[reportUninitializedInstanceVariable]
    count: int = pydantic.Field(default=0, gt=0)
