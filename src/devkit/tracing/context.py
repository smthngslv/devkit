import contextlib
import functools
import re
from collections.abc import Callable, Coroutine, Generator, Mapping
from typing import TYPE_CHECKING, ClassVar, Final, Self, final

import logfire

if TYPE_CHECKING:
    from devkit.tracing import tracer as tracing_tracer

__all__: Final[tuple[str, ...]] = ("Context",)

_PACKED_SIZE: Final[int] = 26


@final
class Context:
    __slots__: ClassVar[tuple[str, ...]] = ("parent",)

    @classmethod
    def get_current(cls: type[Self], /) -> Self:
        return cls(parent=logfire.get_context().get("traceparent"))

    @classmethod
    def from_bytes(cls: type[Self], /, packed: bytes) -> Self:
        if len(packed) == 0:
            return cls()

        if len(packed) != _PACKED_SIZE:
            message: Final[str] = f"Expected 26 traceparent bytes, got {len(packed)}."
            raise ValueError(message)

        unpacked: Final[str] = packed.hex()
        return cls(parent=f"{unpacked[:2]}-{unpacked[2:34]}-{unpacked[34:50]}-{unpacked[50:]}")

    @classmethod
    def from_json_dict(cls: type[Self], /, json_dict: Mapping[str, object]) -> Self:
        parent: Final[object] = json_dict.get("traceparent")
        if parent is not None and not isinstance(parent, str):
            message: Final[str] = f"Expected a traceparent string, got {parent.__class__.__name__}."
            raise ValueError(message)

        return cls(parent=parent)

    def __init__(self: Self, /, *, parent: str | None = None) -> None:
        if parent is not None and (
            re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", parent) is None
            or int(parent[3:35], 16) == 0
            or int(parent[36:52], 16) == 0
        ):
            message: Final[str] = f"Invalid version-00 traceparent: {parent!r}."
            raise ValueError(message)

        self.parent: Final[str | None] = parent

    @property
    def is_empty(self: Self, /) -> bool:
        return self.parent is None

    def to_bytes(self: Self, /) -> bytes:
        return bytes.fromhex(self.parent.replace("-", "")) if self.parent is not None else b""

    def to_json_dict(self: Self, /) -> dict[str, str]:
        return {"traceparent": self.parent} if self.parent is not None else {}

    @contextlib.contextmanager
    def attach(self: Self, /, *, tracer: tracing_tracer.Tracer, is_remote: bool = False) -> Generator[None]:
        with logfire.attach_context(self.to_json_dict()):
            try:
                yield

            except Exception as exception:
                if is_remote:
                    # A propagated context has no writable span, so record failures as child events.
                    tracer.error("error", exception_=exception, stack_depth_=2)

                raise

    def attach_sync[**P, R](
        self: Self, /, *, tracer: tracing_tracer.Tracer, is_remote: bool = False
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        def decorator(function: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(function)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                with self.attach(tracer=tracer, is_remote=is_remote):
                    return function(*args, **kwargs)

            return wrapper

        return decorator

    def attach_async[**P, R](
        self: Self, /, *, tracer: tracing_tracer.Tracer, is_remote: bool = False
    ) -> Callable[[Callable[P, Coroutine[None, None, R]]], Callable[P, Coroutine[None, None, R]]]:
        def decorator(function: Callable[P, Coroutine[None, None, R]]) -> Callable[P, Coroutine[None, None, R]]:
            @functools.wraps(function)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                with self.attach(tracer=tracer, is_remote=is_remote):
                    return await function(*args, **kwargs)

            return wrapper

        return decorator
