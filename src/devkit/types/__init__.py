"""Shared validated models and UTC datetime types."""

from typing import Final

from devkit.types import utc_datetime
from devkit.types.entity import Entity
from devkit.types.utc_datetime import UTCDateTime

__all__: Final[tuple[str, ...]] = ("Entity", "UTCDateTime", "utc_datetime")
