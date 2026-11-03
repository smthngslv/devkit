"""Validated immutable model base for shared entities."""

from typing import ClassVar, Final

import pydantic

__all__: Final[tuple[str, ...]] = ("Entity",)


class Entity(pydantic.BaseModel):
    """Base model with validated defaults, attribute parsing, and frozen values.

    Unknown fields are forbidden. Use this for database-related data and options
    that should be validated at their boundary.
    """

    model_config: ClassVar[pydantic.ConfigDict] = pydantic.ConfigDict(
        validate_default=True, from_attributes=True, frozen=True, extra="forbid"
    )
