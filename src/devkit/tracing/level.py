from enum import IntEnum
from typing import ClassVar, Final, Literal, Self, cast, final

__all__: Final[tuple[str, ...]] = ("Level",)


@final
class Level(IntEnum):
    __slots__: ClassVar[tuple[str, ...]] = ()

    TRACE = 1
    DEBUG = 5
    INFO = 9
    NOTICE = 10
    WARNING = 13
    ERROR = 17
    FATAL = 21

    @property
    def label(self: Self, /) -> Literal["trace", "debug", "info", "notice", "warn", "error", "fatal"]:
        return cast(
            'Literal["trace", "debug", "info", "notice", "warn", "error", "fatal"]',
            "warn" if self is self.__class__.WARNING else self.name.lower(),
        )
