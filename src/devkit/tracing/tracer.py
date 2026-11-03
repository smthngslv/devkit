"""Logfire-backed logs, spans, and context-aware decorators."""

import annotationlib
import contextlib
import functools
import inspect
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Coroutine,
    Generator,
    Iterable,
    Iterator,
    Mapping,
    Set,
)
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from pathlib import Path
from types import FrameType
from typing import Any, ClassVar, Final, Literal, Self, cast, final

import logfire
import logfire._internal.main as logfire_sdk_main
import opentelemetry.sdk.trace as otel_sdk_trace
import opentelemetry.trace as otel_trace

from devkit.tracing.context import Context
from devkit.tracing.level import Level

__all__: Final[tuple[str, ...]] = ("Tracer",)


@final
class Tracer:
    """Emit Logfire events under a scope with optional inherited tags."""

    __slots__: ClassVar[tuple[str, ...]] = ("__scope", "__tags", "logfire_instance")

    def __init__(self: Self, scope: str, /, *, tags: Iterable[str] | None = None) -> None:
        self.__scope: Final[str] = scope
        self.__tags: Final[tuple[str, ...]] = tuple[str, ...](tags) if tags is not None else ()
        self.logfire_instance: Final[logfire.Logfire] = logfire.DEFAULT_LOGFIRE_INSTANCE.with_settings(
            tags=self.__tags, custom_scope_suffix=scope
        )

    @property
    def level(self: Self, /) -> int:
        """Return the configured minimum severity."""
        return self.logfire_instance.config.min_level

    def set_attributes_to_current_span(self: Self, level: Level, /, **attributes: Any) -> None:
        """Add structured attributes to the active span when the level is enabled."""
        if self.level <= level:
            # Logfire has no public helper for structured attributes on the active OpenTelemetry span.
            # Keep its JSON schema alongside the values; covered by the SDK integration tests.
            # TODO: Replace when https://github.com/pydantic/logfire/issues/674 exposes a public API.
            logfire_sdk_main.set_user_attributes_on_raw_span(
                cast("otel_sdk_trace.Span", otel_trace.get_current_span()), attributes
            )

    def get_child(self: Self, scope: str, /, *, tags: Set[str] | None = None) -> Self:
        """Create a nested scope that inherits this tracer's tags."""
        # Scope is not propagated by logfire, it has to be done manually.
        return self.__class__(f"{self.__scope}.{scope}", tags=(*self.__tags, *(tags if tags is not None else ())))

    def log(
        self: Self,
        level: Level,
        name: str | None = None,
        /,
        *,
        stack_depth_: int = 0,
        should_reset_context_: bool = False,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        exception_: BaseException | None = None,
        **attributes: Any,
    ) -> None:
        """Emit a structured log or a message span with an optional exception."""
        if message_ is not None:
            span: logfire.LogfireSpan
            with (
                self.reset_context() if should_reset_context_ else contextlib.nullcontext(),
                self.span(
                    level, name, stack_depth_=stack_depth_ + 1, message_=message_, tags_=tags_, **attributes
                ) as span,
            ):
                if exception_ is not None:
                    span.record_exception(exception_)
                    if level >= Level.ERROR:
                        otel_trace.get_current_span().set_status(otel_trace.StatusCode.ERROR, str(exception_))

                return

        if tags_ is None:
            tags_ = set[str]()

        caller_name: Final[str] = self.__get_caller_fully_qualified_name(stack_depth_ + 1)
        name = f"{caller_name}.{name}" if name is not None else caller_name
        with self.reset_context() if should_reset_context_ else contextlib.nullcontext():
            self.logfire_instance.log(int(level), name, attributes, tuple[str, ...](tags_), exception_)

    def trace(
        self: Self,
        name: str | None = None,
        /,
        *,
        stack_depth_: int = 0,
        should_reset_context_: bool = False,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        exception_: BaseException | None = None,
        **attributes: Any,
    ) -> None:
        """Emit a trace-level log."""
        return self.log(
            Level.TRACE,
            name,
            stack_depth_=stack_depth_ + 1,
            should_reset_context_=should_reset_context_,
            message_=message_,
            tags_=tags_,
            exception_=exception_,
            **attributes,
        )

    def debug(
        self: Self,
        name: str | None = None,
        /,
        *,
        stack_depth_: int = 0,
        should_reset_context_: bool = False,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        exception_: BaseException | None = None,
        **attributes: Any,
    ) -> None:
        """Emit a debug-level log."""
        return self.log(
            Level.DEBUG,
            name,
            stack_depth_=stack_depth_ + 1,
            should_reset_context_=should_reset_context_,
            message_=message_,
            tags_=tags_,
            exception_=exception_,
            **attributes,
        )

    def info(
        self: Self,
        name: str | None = None,
        /,
        *,
        stack_depth_: int = 0,
        should_reset_context_: bool = False,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        exception_: BaseException | None = None,
        **attributes: Any,
    ) -> None:
        """Emit an info-level log."""
        return self.log(
            Level.INFO,
            name,
            stack_depth_=stack_depth_ + 1,
            should_reset_context_=should_reset_context_,
            message_=message_,
            tags_=tags_,
            exception_=exception_,
            **attributes,
        )

    def notice(
        self: Self,
        name: str | None = None,
        /,
        *,
        stack_depth_: int = 0,
        should_reset_context_: bool = False,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        exception_: BaseException | None = None,
        **attributes: Any,
    ) -> None:
        """Emit a notice-level log."""
        return self.log(
            Level.NOTICE,
            name,
            stack_depth_=stack_depth_ + 1,
            should_reset_context_=should_reset_context_,
            message_=message_,
            tags_=tags_,
            exception_=exception_,
            **attributes,
        )

    def warning(
        self: Self,
        name: str | None = None,
        /,
        *,
        stack_depth_: int = 0,
        should_reset_context_: bool = False,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        exception_: BaseException | None = None,
        **attributes: Any,
    ) -> None:
        """Emit a warning-level log."""
        return self.log(
            Level.WARNING,
            name,
            stack_depth_=stack_depth_ + 1,
            should_reset_context_=should_reset_context_,
            message_=message_,
            tags_=tags_,
            exception_=exception_,
            **attributes,
        )

    def error(
        self: Self,
        name: str | None = None,
        /,
        *,
        stack_depth_: int = 0,
        should_reset_context_: bool = False,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        exception_: BaseException | None = None,
        **attributes: Any,
    ) -> None:
        """Emit an error-level log."""
        return self.log(
            Level.ERROR,
            name,
            stack_depth_=stack_depth_ + 1,
            should_reset_context_=should_reset_context_,
            message_=message_,
            tags_=tags_,
            exception_=exception_,
            **attributes,
        )

    def fatal(
        self: Self,
        name: str | None = None,
        /,
        *,
        stack_depth_: int = 0,
        should_reset_context_: bool = False,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        exception_: BaseException | None = None,
        **attributes: Any,
    ) -> None:
        """Emit a fatal-level log."""
        return self.log(
            Level.FATAL,
            name,
            stack_depth_=stack_depth_ + 1,
            should_reset_context_=should_reset_context_,
            message_=message_,
            tags_=tags_,
            exception_=exception_,
            **attributes,
        )

    def span(
        self: Self,
        level: Level,
        name: str | None = None,
        /,
        *,
        stack_depth_: int = 0,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        should_keep_open_: bool = True,
        **attributes: Any,
    ) -> AbstractContextManager[logfire.LogfireSpan]:
        """Create a span named for its call site.

        With ``should_keep_open_=False``, close the span before the block runs while preserving its parent context.
        """
        caller_name: Final[str] = self.__get_caller_fully_qualified_name(stack_depth_ + 1)
        name = f"{caller_name}.{name}" if name is not None else caller_name

        if message_ is None:
            message_ = name

        if tags_ is None:
            tags_ = set[str]()

        span: Final[logfire.LogfireSpan] = self.logfire_instance.span(
            message_, _tags=tuple[str, ...](tags_), _span_name=name, _level=level.label, **attributes
        )
        if should_keep_open_:
            return span

        @contextlib.contextmanager
        def wrapper() -> Generator[logfire.LogfireSpan]:
            with span:
                context: Final[Context] = Context.get_current()

            with context.attach(tracer=self, is_remote=True):
                yield span

        return wrapper()

    def reset_context(self: Self, /) -> AbstractContextManager[None]:
        """Clear the trace parent and baggage for a block."""
        return Context().attach(tracer=self)

    def with_span_async[**P, R](
        self: Self,
        level: Level,
        /,
        *,
        name_: str | None = None,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        include_args_: bool | Set[str] | Mapping[str, str] = False,
        should_include_return_: bool = False,
        should_keep_open_: bool = True,
        **attributes: Any,
    ) -> Callable[[Callable[P, Coroutine[None, None, R]]], Callable[P, Coroutine[None, None, R]]]:
        """Decorate an async function with a span and optional argument or return capture."""
        # A short-lived span is closed before the body runs, so the return value cannot be attached to it.
        if should_include_return_ and not should_keep_open_:
            message: Final[str] = "`should_include_return_` is incompatible with `should_keep_open_=False`."
            raise RuntimeError(message)

        if message_ is None:
            message_ = name_

        if tags_ is None:
            tags_ = set[str]()

        def decorator(function: Callable[P, Coroutine[None, None, R]]) -> Callable[P, Coroutine[None, None, R]]:
            span_attributes: Final[dict[str, Any]] = {**attributes, **self.__get_code_attributes(function)}
            span_name: Final[str] = name_ if name_ is not None else self.__get_fully_qualified_name(function)
            span_message: Final[str] = message_ if message_ is not None else span_name
            signature: Final[inspect.Signature | None] = (
                inspect.signature(function, annotation_format=annotationlib.Format.STRING)
                if include_args_ is not False
                else None
            )

            if signature is not None and not isinstance(include_args_, bool):
                invalid_arg: str
                for invalid_arg in self.__get_referenced_parameters(include_args_) - signature.parameters.keys():
                    message: str = f"Cannot find argument: `{invalid_arg}`."
                    raise RuntimeError(message)

            @functools.wraps(function)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                arguments: Final[dict[str, Any]] = (
                    self.__get_arguments(signature, include_args_, *args, **kwargs)
                    if signature is not None and include_args_ is not False
                    else {}
                )

                span: Final[logfire.LogfireSpan] = self.logfire_instance.span(
                    span_message,
                    _tags=tuple[str, ...](tags_),
                    _span_name=span_name,
                    _level=level.label,
                    **(span_attributes | arguments),
                )

                # Open the span only long enough to capture its context, then close it so it is queryable
                # immediately while the wrapped work still nests under it.
                if not should_keep_open_:
                    with span:
                        context: Final[Context] = Context.get_current()

                    with context.attach(tracer=self, is_remote=True):
                        return await function(*args, **kwargs)

                with span:
                    return_value: Final[R] = await function(*args, **kwargs)

                    if should_include_return_:
                        span.set_attribute("return_value", return_value)

                    return return_value

            return wrapper

        return decorator

    def with_span_sync[**P, R](
        self: Self,
        level: Level,
        /,
        *,
        name_: str | None = None,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        include_args_: bool | Set[str] | Mapping[str, str] = False,
        should_include_return_: bool = False,
        should_keep_open_: bool = True,
        **attributes: Any,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorate a sync function with a span and optional argument or return capture."""
        # A short-lived span is closed before the body runs, so the return value cannot be attached to it.
        if should_include_return_ and not should_keep_open_:
            message: Final[str] = "`should_include_return_` is incompatible with `should_keep_open_=False`."
            raise RuntimeError(message)

        if message_ is None:
            message_ = name_

        if tags_ is None:
            tags_ = set[str]()

        def decorator(function: Callable[P, R]) -> Callable[P, R]:
            span_attributes: Final[dict[str, Any]] = {**attributes, **self.__get_code_attributes(function)}
            span_name: Final[str] = name_ if name_ is not None else self.__get_fully_qualified_name(function)
            span_message: Final[str] = message_ if message_ is not None else span_name
            signature: Final[inspect.Signature | None] = (
                inspect.signature(function, annotation_format=annotationlib.Format.STRING)
                if include_args_ is not False
                else None
            )

            if signature is not None and not isinstance(include_args_, bool):
                invalid_arg: str
                for invalid_arg in self.__get_referenced_parameters(include_args_) - signature.parameters.keys():
                    message: str = f"Cannot find argument: `{invalid_arg}`."
                    raise RuntimeError(message)

            @functools.wraps(function)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                arguments: Final[dict[str, Any]] = (
                    self.__get_arguments(signature, include_args_, *args, **kwargs)
                    if signature is not None and include_args_ is not False
                    else {}
                )

                span: Final[logfire.LogfireSpan] = self.logfire_instance.span(
                    span_message,
                    _tags=tuple[str, ...](tags_),
                    _span_name=span_name,
                    _level=level.label,
                    **(span_attributes | arguments),
                )

                # Open the span only long enough to capture its context, then close it so it is queryable
                # immediately while the wrapped work still nests under it.
                if not should_keep_open_:
                    with span:
                        context: Final[Context] = Context.get_current()

                    with context.attach(tracer=self, is_remote=True):
                        return function(*args, **kwargs)

                with span:
                    return_value: Final[R] = function(*args, **kwargs)

                    if should_include_return_:
                        span.set_attribute("return_value", return_value)

                    return return_value

            return wrapper

        return decorator

    def with_span_aiter[**P, Y](
        self: Self,
        level: Level,
        /,
        *,
        name_: str | None = None,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        include_args_: bool | Set[str] | Mapping[str, str] = False,
        should_include_consumer_: bool = False,
        **attributes: Any,
    ) -> Callable[[Callable[P, AsyncIterator[Y]]], Callable[P, AsyncGenerator[Y]]]:
        """Reattach the span context while an async iterator produces each item."""

        def decorator(function: Callable[P, AsyncIterator[Y]]) -> Callable[P, AsyncGenerator[Y]]:
            # Reuse the span decorator to open the span, capture its context, and close it at once -- an iterator
            # is long-lived, so the span is only re-attached while the iterator itself produces items.
            @self.with_span_sync(
                level, name_=name_, message_=message_, tags_=tags_, include_args_=include_args_, **attributes
            )
            @functools.wraps(function)
            # The parameters exist only to mirror the wrapped signature so `include_args_` can bind them.
            def get_span_context(*args: P.args, **kwargs: P.kwargs) -> Context:  # noqa: ARG001
                return Context.get_current()

            @functools.wraps(function)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> AsyncGenerator[Y]:
                span_context: Final[Context] = get_span_context(*args, **kwargs)
                return self.__iterate_async(
                    function(*args, **kwargs),
                    reattach=functools.partial(span_context.attach, tracer=self, is_remote=True),
                    should_include_consumer=should_include_consumer_,
                )

            return wrapper

        return decorator

    def with_span_iter[**P, Y](
        self: Self,
        level: Level,
        /,
        *,
        name_: str | None = None,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        include_args_: bool | Set[str] | Mapping[str, str] = False,
        should_include_consumer_: bool = False,
        **attributes: Any,
    ) -> Callable[[Callable[P, Iterator[Y]]], Callable[P, Generator[Y]]]:
        """Reattach the span context while an iterator produces each item."""

        def decorator(function: Callable[P, Iterator[Y]]) -> Callable[P, Generator[Y]]:
            # Reuse the span decorator to open the span, capture its context, and close it at once -- an iterator
            # is long-lived, so the span is only re-attached while the iterator itself produces items.
            @self.with_span_sync(
                level, name_=name_, message_=message_, tags_=tags_, include_args_=include_args_, **attributes
            )
            @functools.wraps(function)
            # The parameters exist only to mirror the wrapped signature so `include_args_` can bind them.
            def get_span_context(*args: P.args, **kwargs: P.kwargs) -> Context:  # noqa: ARG001
                return Context.get_current()

            @functools.wraps(function)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> Generator[Y]:
                span_context: Final[Context] = get_span_context(*args, **kwargs)
                return self.__iterate(
                    function(*args, **kwargs),
                    reattach=functools.partial(span_context.attach, tracer=self, is_remote=True),
                    should_include_consumer=should_include_consumer_,
                )

            return wrapper

        return decorator

    def with_span_acontextmanager[**P, Y](
        self: Self,
        level: Level,
        /,
        *,
        name_: str | None = None,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        include_args_: bool | Set[str] | Mapping[str, str] = False,
        **attributes: Any,
    ) -> Callable[[Callable[P, AsyncGenerator[Y]]], Callable[P, AbstractAsyncContextManager[Y]]]:
        """Propagate span context through async setup and teardown."""

        def decorator(function: Callable[P, AsyncGenerator[Y]]) -> Callable[P, AbstractAsyncContextManager[Y]]:
            # Reuse the span decorator to open the span, capture its context, and close it at once -- a context
            # manager is long-lived, so the span is only re-attached while setup and teardown run, not while the
            # caller holds the yielded value.
            @self.with_span_sync(
                level, name_=name_, message_=message_, tags_=tags_, include_args_=include_args_, **attributes
            )
            @functools.wraps(function)
            # The parameters exist only to mirror the wrapped signature so `include_args_` can bind them.
            def get_span_context(*args: P.args, **kwargs: P.kwargs) -> Context:  # noqa: ARG001
                return Context.get_current()

            @contextlib.asynccontextmanager
            @functools.wraps(function)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> AsyncGenerator[Y]:
                span_context: Final[Context] = get_span_context(*args, **kwargs)
                value: Y
                async with self.__drive_async_contextmanager(
                    function(*args, **kwargs),
                    reattach=functools.partial(span_context.attach, tracer=self, is_remote=True),
                ) as value:
                    yield value

            return wrapper

        return decorator

    def with_span_contextmanager[**P, Y](
        self: Self,
        level: Level,
        /,
        *,
        name_: str | None = None,
        message_: str | None = None,
        tags_: Set[str] | None = None,
        include_args_: bool | Set[str] | Mapping[str, str] = False,
        **attributes: Any,
    ) -> Callable[[Callable[P, Generator[Y]]], Callable[P, AbstractContextManager[Y]]]:
        """Propagate span context through setup and teardown."""

        def decorator(function: Callable[P, Generator[Y]]) -> Callable[P, AbstractContextManager[Y]]:
            # Reuse the span decorator to open the span, capture its context, and close it at once -- a context
            # manager is long-lived, so the span is only re-attached while setup and teardown run, not while the
            # caller holds the yielded value.
            @self.with_span_sync(
                level, name_=name_, message_=message_, tags_=tags_, include_args_=include_args_, **attributes
            )
            @functools.wraps(function)
            # The parameters exist only to mirror the wrapped signature so `include_args_` can bind them.
            def get_span_context(*args: P.args, **kwargs: P.kwargs) -> Context:  # noqa: ARG001
                return Context.get_current()

            @contextlib.contextmanager
            @functools.wraps(function)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> Generator[Y]:
                span_context: Final[Context] = get_span_context(*args, **kwargs)
                value: Y
                with self.__drive_contextmanager(
                    function(*args, **kwargs),
                    reattach=functools.partial(span_context.attach, tracer=self, is_remote=True),
                ) as value:
                    yield value

            return wrapper

        return decorator

    def with_reset_context_async[**P, R](
        self: Self, /, function: Callable[P, Coroutine[None, None, R]]
    ) -> Callable[P, Coroutine[None, None, R]]:
        """Run an async function with an empty trace context."""

        @functools.wraps(function)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with self.reset_context():
                return await function(*args, **kwargs)

        return wrapper

    def with_reset_context_sync[**P, R](self: Self, /, function: Callable[P, R]) -> Callable[P, R]:
        """Run a sync function with an empty trace context."""

        @functools.wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with self.reset_context():
                return function(*args, **kwargs)

        return wrapper

    def with_reset_context_aiter[**P, Y](
        self: Self, /, function: Callable[P, AsyncIterator[Y]]
    ) -> Callable[P, AsyncGenerator[Y]]:
        """Run async iterator production with an empty trace context."""

        @functools.wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> AsyncGenerator[Y]:
            return self.__iterate_async(function(*args, **kwargs), reattach=self.reset_context)

        return wrapper

    def with_reset_context_iter[**P, Y](self: Self, /, function: Callable[P, Iterator[Y]]) -> Callable[P, Generator[Y]]:
        """Run iterator production with an empty trace context."""

        @functools.wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> Generator[Y]:
            return self.__iterate(function(*args, **kwargs), reattach=self.reset_context)

        return wrapper

    def with_reset_context_acontextmanager[**P, Y](
        self: Self, /, function: Callable[P, AsyncGenerator[Y]]
    ) -> Callable[P, AbstractAsyncContextManager[Y]]:
        """Run async context-manager setup and teardown with an empty trace context."""

        @contextlib.asynccontextmanager
        @functools.wraps(function)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> AsyncGenerator[Y]:
            value: Y
            async with self.__drive_async_contextmanager(
                function(*args, **kwargs), reattach=self.reset_context
            ) as value:
                yield value

        return wrapper

    def with_reset_context_contextmanager[**P, Y](
        self: Self, /, function: Callable[P, Generator[Y]]
    ) -> Callable[P, AbstractContextManager[Y]]:
        """Run context-manager setup and teardown with an empty trace context."""

        @contextlib.contextmanager
        @functools.wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> Generator[Y]:
            value: Y
            with self.__drive_contextmanager(function(*args, **kwargs), reattach=self.reset_context) as value:
                yield value

        return wrapper

    @staticmethod
    def __get_code_attributes(function: Callable[..., Any]) -> dict[str, Any]:
        function = inspect.unwrap(function)
        return {
            "code.filepath": (Path(inspect.getfile(function)).relative_to(Path.cwd(), walk_up=True).as_posix()),
            "code.function": function.__qualname__,
            "code.lineno": getattr(getattr(function, "__code__", None), "co_firstlineno", None),
        }

    @staticmethod
    def __get_fully_qualified_name(obj: Any) -> str:
        obj_ensured: Final[Any] = (
            obj
            if inspect.isfunction(obj) or inspect.ismethod(obj) or inspect.isclass(obj)
            else getattr(obj, "__class__", obj)
        )

        module: Final[str | None] = getattr(obj_ensured, "__module__", None)
        name: Final[str] = getattr(obj_ensured, "__qualname__", getattr(obj_ensured, "__name__", repr(obj_ensured)))
        return f"{module}.{name}" if module is not None else name

    @staticmethod
    def __get_caller_fully_qualified_name(depth: int) -> str:
        """Find the call site after skipping wrapper frames."""
        frame: FrameType | None = inspect.currentframe()
        _: int
        for _ in range(depth + 1):
            if frame is None:
                break

            frame = frame.f_back

        if frame is None:
            message: Final[str] = f"Cannot get caller at depth {depth}."
            raise RuntimeError(message)

        module: Final[str | None] = frame.f_globals.get("__name__")
        return f"{module}.{frame.f_code.co_qualname}" if module is not None else frame.f_code.co_qualname

    @staticmethod
    def __get_referenced_parameters(include_args_: Set[str] | Mapping[str, str]) -> set[str]:
        if isinstance(include_args_, Mapping):
            return {path.split(".", maxsplit=1)[0] for path in include_args_.values()}

        return set(include_args_)

    @staticmethod
    def __resolve_argument_path(arguments: Mapping[str, Any], path: str) -> Any:
        parts: Final[list[str]] = path.split(".")
        value: Any = arguments[parts[0]]
        attribute: str
        for attribute in parts[1:]:
            value = getattr(value, attribute)

        return value

    @classmethod
    def __get_arguments(
        cls: type[Self],
        signature: inspect.Signature,
        include_args_: Literal[True] | Set[str] | Mapping[str, str],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Bind call arguments and select values for span attributes."""
        bound: Final[inspect.BoundArguments] = signature.bind(*args, **kwargs)
        bound.apply_defaults()

        if isinstance(include_args_, Mapping):
            return {name: cls.__resolve_argument_path(bound.arguments, path) for name, path in include_args_.items()}

        return {key: value for key, value in bound.arguments.items() if include_args_ is True or key in include_args_}

    @staticmethod
    def __iterate[Y](
        iterator: Iterator[Y],
        *,
        reattach: Callable[[], AbstractContextManager[None]],
        should_include_consumer: bool = False,
    ) -> Generator[Y]:
        """Resume and close an iterator under the supplied context."""
        try:
            while True:
                with reattach():
                    try:
                        item: Y = next(iterator)

                    except StopIteration:
                        return

                    if should_include_consumer:
                        yield item
                        continue

                # Detach before yielding so each resume restores its own caller's context.
                yield item

        finally:
            if isinstance(iterator, Generator):
                with reattach():
                    iterator.close()

    @staticmethod
    @contextlib.contextmanager
    def __drive_contextmanager[Y](
        generator: Generator[Y], *, reattach: Callable[[], AbstractContextManager[None]]
    ) -> Generator[Y]:
        """Run setup and teardown under context while the caller body stays outside."""

        def get_generator() -> Generator[Y]:
            return generator

        manager: Final[AbstractContextManager[Y]] = contextlib.contextmanager(get_generator)()
        with reattach():
            value: Final[Y] = manager.__enter__()

        try:
            yield value

        except BaseException as exception:
            with reattach():
                is_suppressed: Final[bool | None] = manager.__exit__(
                    exception.__class__, exception, exception.__traceback__
                )

                if is_suppressed is not True:
                    raise

        else:
            with reattach():
                manager.__exit__(None, None, None)

    @staticmethod
    async def __iterate_async[Y](
        iterator: AsyncIterator[Y],
        *,
        reattach: Callable[[], AbstractContextManager[None]],
        should_include_consumer: bool = False,
    ) -> AsyncGenerator[Y]:
        """Resume and close an async iterator under the supplied context."""
        try:
            while True:
                with reattach():
                    try:
                        item: Y = await anext(iterator)

                    except StopAsyncIteration:
                        return

                    if should_include_consumer:
                        yield item
                        continue

                yield item

        finally:
            if isinstance(iterator, AsyncGenerator):
                with reattach():
                    await iterator.aclose()

    @staticmethod
    @contextlib.asynccontextmanager
    async def __drive_async_contextmanager[Y](
        generator: AsyncGenerator[Y], *, reattach: Callable[[], AbstractContextManager[None]]
    ) -> AsyncGenerator[Y]:
        """Run async setup and teardown under context while the caller body stays outside."""

        def get_generator() -> AsyncGenerator[Y]:
            return generator

        manager: Final[AbstractAsyncContextManager[Y]] = contextlib.asynccontextmanager(get_generator)()
        with reattach():
            value: Final[Y] = await manager.__aenter__()

        try:
            yield value

        except BaseException as exception:
            with reattach():
                is_suppressed: Final[bool | None] = await manager.__aexit__(
                    exception.__class__, exception, exception.__traceback__
                )

                if is_suppressed is not True:
                    raise

        else:
            with reattach():
                await manager.__aexit__(None, None, None)
