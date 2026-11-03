"""Transport trace parents and baggage across execution boundaries."""

import contextlib
import functools
import re
from collections.abc import Callable, Coroutine, Generator, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Self, cast, final

import logfire
import msgpack

if TYPE_CHECKING:
    from devkit.tracing.tracer import Tracer

__all__: Final[tuple[str, ...]] = ("Context",)


@final
class Context:
    """Capture a trace parent and baggage for transport or reattachment."""

    __slots__: ClassVar[tuple[str, ...]] = ("baggage", "parent")

    @classmethod
    def get_current(cls: type[Self], /) -> Self:
        """Capture the active Logfire trace parent and baggage."""
        return cls(parent=logfire.get_context().get("traceparent"), baggage=logfire.get_baggage())

    @classmethod
    def from_bytes(cls: type[Self], /, packed: bytes) -> Self:
        """Decode a MessagePack context and reject malformed payloads."""
        try:
            unpacked: object = msgpack.unpackb(packed, raw=False)

        except (msgpack.UnpackException, ValueError, TypeError) as exception:
            message: str = f"Invalid packed tracing context of {len(packed)} bytes."
            raise ValueError(message) from exception

        if not isinstance(unpacked, dict):
            message = f"Expected a packed context mapping, got {unpacked.__class__.__name__}."
            raise TypeError(message)

        return cls.from_json_dict(cast("Mapping[str, object]", unpacked))

    @classmethod
    def from_json_dict(cls: type[Self], /, json_dict: Mapping[str, object]) -> Self:
        """Validate a mapping with optional traceparent and baggage."""
        parent: Final[object] = json_dict.get("traceparent")
        if parent is not None and not isinstance(parent, str):
            message: str = f"Expected a traceparent string, got {parent.__class__.__name__}."
            raise ValueError(message)

        baggage: Final[object] = json_dict.get("baggage", {})
        if not isinstance(baggage, Mapping):
            message = f"Expected a baggage mapping, got {baggage.__class__.__name__}."
            raise TypeError(message)

        entries: Final[Mapping[object, object]] = cast("Mapping[object, object]", baggage)
        key: object
        for key in entries:
            if not isinstance(key, str):
                message = "Baggage keys must be strings."
                raise TypeError(message)

        return cls(parent=parent, baggage=cast("Mapping[str, object]", baggage))

    def __init__(self: Self, /, *, parent: str | None = None, baggage: Mapping[str, object] | None = None) -> None:
        if parent is not None and (
            re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", parent) is None
            or int(parent[3:35], 16) == 0
            or int(parent[36:52], 16) == 0
        ):
            message: str = f"Invalid version-00 traceparent: {parent!r}."
            raise ValueError(message)

        self.parent: Final[str | None] = parent
        values: Final[dict[str, str]] = {}
        if baggage is not None:
            key: str
            value: object
            for key, value in baggage.items():
                if not isinstance(value, str):
                    message = "Baggage values must be strings."
                    raise TypeError(message)

                values[key] = value

        self.baggage: Final[Mapping[str, str]] = MappingProxyType(values)

    @property
    def is_empty(self: Self, /) -> bool:
        """Report whether both the trace parent and baggage are absent."""
        return self.parent is None and len(self.baggage) == 0

    def to_bytes(self: Self, /) -> bytes:
        """Encode this context as MessagePack."""
        return msgpack.packb(self.to_json_dict(), use_bin_type=True)

    def to_json_dict(self: Self, /) -> dict[str, str | dict[str, str]]:
        """Return a JSON-compatible mapping of parent and baggage."""
        payload: Final[dict[str, str | dict[str, str]]] = {"baggage": dict(self.baggage)}
        if self.parent is not None:
            payload["traceparent"] = self.parent

        return payload

    @contextlib.contextmanager
    def attach(self: Self, /, *, tracer: Tracer, is_remote: bool = False) -> Generator[None]:
        """Attach this context for a block and restore the prior context afterward.

        With ``is_remote=True``, record exceptions as child events of the remote parent.
        """
        carrier: Final[dict[str, str]] = {"traceparent": self.parent} if self.parent is not None else {}
        with logfire.attach_context(carrier), logfire.set_baggage(**self.baggage):
            try:
                yield

            except Exception as exception:
                if is_remote:
                    # A propagated context has no writable span, so record failures as child events.
                    tracer.error("error", exception_=exception, stack_depth_=2)

                raise

    def attach_sync[**P, R](
        self: Self, /, *, tracer: Tracer, is_remote: bool = False
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorate a synchronous function with this context."""

        def decorator(function: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(function)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                with self.attach(tracer=tracer, is_remote=is_remote):
                    return function(*args, **kwargs)

            return wrapper

        return decorator

    def attach_async[**P, R](
        self: Self, /, *, tracer: Tracer, is_remote: bool = False
    ) -> Callable[[Callable[P, Coroutine[None, None, R]]], Callable[P, Coroutine[None, None, R]]]:
        """Decorate an asynchronous function with this context."""

        def decorator(function: Callable[P, Coroutine[None, None, R]]) -> Callable[P, Coroutine[None, None, R]]:
            @functools.wraps(function)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                with self.attach(tracer=tracer, is_remote=is_remote):
                    return await function(*args, **kwargs)

            return wrapper

        return decorator
