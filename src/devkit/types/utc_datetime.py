"""UTC-aware datetime annotation and its shared normalizer.

``UTCDateTime`` validates model fields as aware datetimes and normalizes them to
UTC. The database column type in ``devkit.db.types`` uses the same normalizer.
"""

import datetime as dt
from typing import Annotated, Final

import pydantic

__all__: Final[tuple[str, ...]] = ("UTCDateTime", "to_utc")


def to_utc(value: dt.datetime) -> dt.datetime:
    """Return an aware UTC datetime, rejecting naive inputs."""
    if value.tzinfo is None or value.utcoffset() is None:
        message: Final[str] = "Using datetime without timezone is not allowed."
        raise ValueError(message)

    return value.astimezone(dt.UTC)


UTCDateTime = Annotated[dt.datetime, pydantic.AfterValidator(to_utc)]
