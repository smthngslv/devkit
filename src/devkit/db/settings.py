"""Pydantic Settings model for the database service's environment values."""

from typing import ClassVar, Final, final

import pydantic
import pydantic_settings

from devkit.db.service import Options

__all__: Final[tuple[str, ...]] = ("Settings",)


@final
# Pydantic initializes BaseModel's generated internals when it creates the subclass.
class Settings(pydantic_settings.BaseSettings):  # pyright: ignore[reportUninitializedInstanceVariable]
    """Read the PostgreSQL URL and nested options from environment variables.

    Use ``DATABASE_URL`` and ``DATABASE_OPTIONS__...`` directly. An outer
    settings model can declare ``database: Settings`` and use
    ``env_nested_delimiter="__"`` to read ``DATABASE__URL`` and
    ``DATABASE__OPTIONS__...``. Keep credentials out of code and logs.
    """

    model_config: ClassVar[pydantic_settings.SettingsConfigDict] = pydantic_settings.SettingsConfigDict(
        env_prefix="DATABASE_", env_nested_delimiter="__"
    )

    url: pydantic.PostgresDsn = pydantic.Field(description="Async PostgreSQL URL.")
    options: Options = pydantic.Field(default_factory=Options, description="Connection and pool options.")
