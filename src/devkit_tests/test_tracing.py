import asyncio
import contextlib
import inspect
import json
from collections.abc import AsyncGenerator, Generator, Iterator
from typing import Final

import logfire
import opentelemetry.sdk.trace as sdk_trace
import opentelemetry.sdk.trace.export as trace_export
import opentelemetry.sdk.trace.export.in_memory_span_exporter as memory_export
import opentelemetry.trace as otel_trace
import pytest

from devkit import tracing

__all__: Final[tuple[str, ...]] = ()

_PARENT: Final[str] = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"


@pytest.fixture
def exporter() -> memory_export.InMemorySpanExporter:
    return memory_export.InMemorySpanExporter()


@pytest.fixture
def tracer(exporter: memory_export.InMemorySpanExporter) -> Iterator[tracing.Tracer]:
    instance: Final[logfire.Logfire] = logfire.configure(
        local=True,
        send_to_logfire=False,
        console=False,
        metrics=False,
        inspect_arguments=False,
        min_level=0,
        additional_span_processors=[trace_export.SimpleSpanProcessor(exporter)],
    )
    try:
        yield tracing.Tracer("tests", logfire=instance)

    finally:
        instance.shutdown()


@pytest.mark.parametrize("parent", [None, _PARENT])
def test_context_round_trips(parent: str | None) -> None:
    """Preserve empty and populated parents through JSON and compact bytes for transport between workers."""
    context: Final[tracing.Context] = tracing.Context(parent=parent)
    assert tracing.Context.from_bytes(context.to_bytes()).parent == parent
    assert tracing.Context.from_json_dict(context.to_json_dict()).parent == parent
    assert context.is_empty is (parent is None)


@pytest.mark.parametrize("packed", [b"x", bytes(26), bytes(27)])
def test_context_rejects_invalid_bytes(packed: bytes) -> None:
    """Reject truncated, oversized, and zero-ID parents instead of silently losing trace linkage."""
    with pytest.raises(ValueError, match="traceparent"):
        tracing.Context.from_bytes(packed)


@pytest.mark.parametrize("parent", [42, "", _PARENT.upper(), "ff" + _PARENT[2:], _PARENT[:36] + "0" * 16 + "-01"])
def test_context_rejects_invalid_json(parent: object) -> None:
    """Reject invalid types, formats, versions, and span IDs before accepting a remote parent."""
    with pytest.raises(ValueError, match="traceparent"):
        tracing.Context.from_json_dict({"traceparent": parent})


def test_attaching_and_resetting_restore_parent(tracer: tracing.Tracer) -> None:
    """Restore the caller's parent after nesting, resetting, or raising inside an attached context."""
    original: Final[str | None] = tracing.Context.get_current().parent
    context: Final[tracing.Context] = tracing.Context(parent=_PARENT)
    with context.attach(tracer=tracer):
        assert tracing.Context.get_current().parent == _PARENT
        with tracer.reset_context():
            assert tracing.Context.get_current().is_empty

        assert tracing.Context.get_current().parent == _PARENT
        message: Final[str] = "failure."
        with pytest.raises(ValueError, match="failure"), tracer.reset_context():
            raise ValueError(message)

        assert tracing.Context.get_current().parent == _PARENT

    assert tracing.Context.get_current().parent == original


def test_attach_decorators_preserve_result_and_parent(tracer: tracing.Tracer) -> None:
    """Attach a transported parent during sync and async calls and restore the caller afterward."""
    context: Final[tracing.Context] = tracing.Context(parent=_PARENT)
    original: Final[str | None] = tracing.Context.get_current().parent

    @context.attach_sync(tracer=tracer)
    def run_sync() -> str | None:
        return tracing.Context.get_current().parent

    @context.attach_async(tracer=tracer)
    async def run_async() -> str | None:
        return tracing.Context.get_current().parent

    assert run_sync() == _PARENT
    assert asyncio.run(run_async()) == _PARENT
    assert tracing.Context.get_current().parent == original


@pytest.mark.parametrize("level", list(tracing.Level))
def test_log_levels_names_and_tags(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter, level: tracing.Level
) -> None:
    """Forward every convenience method's level, caller name, tags, and data without application-specific tags."""
    getattr(tracer, level.name.lower())("event", tags_={"custom"}, answer=42)
    span: Final[sdk_trace.ReadableSpan] = exporter.get_finished_spans()[-1]
    assert span.name.endswith("test_log_levels_names_and_tags.event")
    assert span.attributes is not None
    assert span.attributes["logfire.level_num"] == level.value
    assert span.attributes["logfire.tags"] == ("custom",)
    assert span.attributes["answer"] == 42


def test_child_scope_and_tags(tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter) -> None:
    """Keep nested tracer scopes and inherited tags so child events can be filtered by component."""
    child: Final[tracing.Tracer] = tracer.get_child("worker", tags={"worker"}).get_child("task", tags={"task"})
    child.info("event")
    span: Final[sdk_trace.ReadableSpan] = exporter.get_finished_spans()[-1]
    assert span.instrumentation_scope is not None
    assert span.instrumentation_scope.name == "logfire.tests.worker.task"
    assert span.attributes is not None
    assert span.attributes["logfire.tags"] == ("worker", "task")


def test_message_exception_status(tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter) -> None:
    """Record an explicit exception and ERROR status when a custom message creates a log span."""
    exception: Final[ValueError] = ValueError("failure")
    tracer.error("failed", message_="Failed {item}", exception_=exception, item="job")
    span: Final[sdk_trace.ReadableSpan] = exporter.get_finished_spans()[-1]
    assert span.status.status_code is otel_trace.StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["logfire.msg"] == "Failed job"
    assert span.events[0].attributes is not None
    assert span.events[0].attributes["exception.message"] == "failure"


def test_reset_log_starts_new_trace(tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter) -> None:
    """Allow an independent log while retaining the enclosing span for subsequent work."""
    with tracer.span(tracing.Level.INFO, "parent"):
        parent: Final[str | None] = tracing.Context.get_current().parent
        tracer.info("independent", should_reset_context_=True)
        assert tracing.Context.get_current().parent == parent

    assert exporter.get_finished_spans()[0].parent is None


def test_sync_arguments_return_and_decorator_reuse(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter
) -> None:
    """Capture defaults and results; a reused decorator keeps each function's metadata and argument overrides."""
    decorate: Final = tracer.with_span_sync(
        tracing.Level.INFO, include_args_=True, should_include_return_=True, value="static"
    )

    @decorate
    def first(value: int = 2) -> dict[str, int]:
        return {"value": value}

    @decorate
    def second(value: int = 3) -> int:
        return value

    assert first() == {"value": 2}
    assert second() == 3
    assert first.__name__ == "first"
    assert inspect.signature(first) == inspect.signature(inspect.unwrap(first))
    spans: Final = exporter.get_finished_spans()
    assert spans[0].attributes is not None
    assert spans[1].attributes is not None
    assert spans[0].attributes["code.function"] == first.__qualname__
    assert spans[1].attributes["code.function"] == second.__qualname__
    assert spans[0].attributes["value"] == 2
    assert json.loads(str(spans[0].attributes["return_value"])) == {"value": 2}
    assert spans[1].attributes["return_value"] == 3


def test_argument_selection_and_dotted_paths(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter
) -> None:
    """Select safe fields such as context.parent without recording every argument or the whole object."""

    @tracer.with_span_sync(tracing.Level.INFO, include_args_={"parent": "context.parent"})
    def mapped(context: tracing.Context) -> str | None:
        return context.parent

    @tracer.with_span_sync(tracing.Level.INFO, include_args_={"value"})
    def selected(value: int, secret: str) -> str:
        return f"{value}:{secret}"

    assert mapped(tracing.Context(parent=_PARENT)) == _PARENT
    assert selected(3, "hidden") == "3:hidden"
    spans: Final = exporter.get_finished_spans()
    assert spans[0].attributes is not None
    assert spans[1].attributes is not None
    assert spans[0].attributes["parent"] == _PARENT
    assert "context" not in spans[0].attributes
    assert spans[1].attributes["value"] == 3
    assert "secret" not in spans[1].attributes


@pytest.mark.parametrize("is_async", [False, True])
def test_invalid_decorator_options_fail_early(tracer: tracing.Tracer, *, is_async: bool) -> None:
    """Reject missing arguments and return capture on an already-closed span when the decorator is built."""

    def run() -> None:
        return None

    async def arun() -> None:
        return None

    if is_async:
        with pytest.raises(RuntimeError, match="incompatible"):
            tracer.with_span_async(tracing.Level.INFO, should_include_return_=True, should_keep_open_=False)

        with pytest.raises(RuntimeError, match="missing"):
            tracer.with_span_async(tracing.Level.INFO, include_args_={"missing"})(arun)

    else:
        with pytest.raises(RuntimeError, match="incompatible"):
            tracer.with_span_sync(tracing.Level.INFO, should_include_return_=True, should_keep_open_=False)

        with pytest.raises(RuntimeError, match="missing"):
            tracer.with_span_sync(tracing.Level.INFO, include_args_={"missing"})(run)


def test_current_span_attributes_and_filtering(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter
) -> None:
    """Attach structured values to the current span, including their Logfire JSON schema, and honor min_level."""
    with tracer.span(tracing.Level.INFO, "data"):
        tracer.set_attributes_to_current_span(tracing.Level.INFO, result={"ok": True})
        tracer.logfire.config.min_level = 11
        assert tracer.level == 11
        tracer.set_attributes_to_current_span(tracing.Level.INFO, hidden=True)

    span: Final[sdk_trace.ReadableSpan] = exporter.get_finished_spans()[-1]
    assert span.attributes is not None
    assert json.loads(str(span.attributes["result"])) == {"ok": True}
    assert "result" in json.loads(str(span.attributes["logfire.json_schema"]))["properties"]
    assert "hidden" not in span.attributes


@pytest.mark.parametrize("should_keep_open", [False, True])
def test_span_lifetime_and_parenting(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter, *, should_keep_open: bool
) -> None:
    """Keep child linkage whether a parent stays open or is exported before the work begins."""
    with tracer.span(tracing.Level.INFO, "parent", should_keep_open_=should_keep_open):
        assert len(exporter.get_finished_spans()) == (0 if should_keep_open else 1)
        tracer.info("child")

    spans: Final = exporter.get_finished_spans()
    parent: Final[sdk_trace.ReadableSpan] = next(span for span in spans if span.name.endswith(".parent"))
    child: Final[sdk_trace.ReadableSpan] = next(span for span in spans if span.name.endswith(".child"))
    assert parent.context is not None
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id


@pytest.mark.parametrize("should_keep_open", [False, True])
def test_sync_decorator_failure(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter, *, should_keep_open: bool
) -> None:
    """Propagate the same exception and record it even when the decorator's parent span has already ended."""
    exception: Final[ValueError] = ValueError("failure")

    @tracer.with_span_sync(tracing.Level.INFO, should_keep_open_=should_keep_open)
    def run() -> None:
        raise exception

    caught: pytest.ExceptionInfo[ValueError]
    with pytest.raises(ValueError, match="failure") as caught:
        run()

    assert caught.value is exception
    assert any(len(span.events) != 0 for span in exporter.get_finished_spans())


def test_async_results_parenting_and_failure(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter
) -> None:
    """Keep independent parent spans across interleaved awaits and capture async arguments, returns, and errors."""

    @tracer.with_span_async(tracing.Level.INFO, include_args_=True, should_include_return_=True)
    async def run(value: int) -> int:
        parent: Final[str | None] = tracing.Context.get_current().parent
        await asyncio.sleep(0)
        assert tracing.Context.get_current().parent == parent
        tracer.info("child", value=value)
        return value

    @tracer.with_span_async(tracing.Level.INFO, should_keep_open_=False)
    async def fail() -> None:
        message: Final[str] = "async failure."
        raise ValueError(message)

    async def exercise() -> None:
        assert await asyncio.gather(run(1), run(2)) == [1, 2]
        with pytest.raises(ValueError, match="async failure"):
            await fail()

    asyncio.run(exercise())
    spans: Final = exporter.get_finished_spans()
    parents: Final = [span for span in spans if span.name.endswith(".run")]
    children: Final = [span for span in spans if span.name.endswith(".child")]
    assert len(parents) == len(children) == 2
    parent: sdk_trace.ReadableSpan
    for parent in parents:
        assert parent.attributes is not None
        assert parent.attributes["value"] == parent.attributes["return_value"]
        assert parent.context is not None
        assert any(child.parent is not None and child.parent.span_id == parent.context.span_id for child in children)

    assert any(len(span.events) != 0 for span in spans)


def test_async_cancellation_restores_context(tracer: tracing.Tracer) -> None:
    """Let cancellation escape a traced coroutine while restoring the task's enclosing context."""

    @tracer.with_span_async(tracing.Level.INFO)
    async def run() -> None:
        raise asyncio.CancelledError

    async def exercise() -> None:
        with tracer.span(tracing.Level.INFO, "outer"):
            parent: Final[str | None] = tracing.Context.get_current().parent
            with pytest.raises(asyncio.CancelledError):
                await run()

            assert tracing.Context.get_current().parent == parent

    asyncio.run(exercise())


@pytest.mark.parametrize("should_reset", [False, True])
def test_iterator_restores_each_consumer_and_closes(tracer: tracing.Tracer, *, should_reset: bool) -> None:
    """Resume an iterator under different callers without leaking its context, and close its producer promptly."""
    producer_parents: Final[list[str | None]] = []
    closed: Final[list[bool]] = []

    def produce() -> Generator[int]:
        try:
            producer_parents.append(tracing.Context.get_current().parent)
            yield 1
            producer_parents.append(tracing.Context.get_current().parent)
            yield 2

        finally:
            closed.append(True)

    iterator: Final = (
        tracer.with_reset_context_iter(produce)()
        if should_reset
        else tracer.with_span_iter(tracing.Level.INFO)(produce)()
    )
    assert isinstance(iterator, Generator)
    with tracer.span(tracing.Level.INFO, "first"):
        parent: Final[str | None] = tracing.Context.get_current().parent
        assert next(iterator) == 1
        assert tracing.Context.get_current().parent == parent

    with tracer.span(tracing.Level.INFO, "second"):
        other_parent: Final[str | None] = tracing.Context.get_current().parent
        assert next(iterator) == 2
        assert tracing.Context.get_current().parent == other_parent
        iterator.close()
        assert tracing.Context.get_current().parent == other_parent

    assert closed == [True]
    assert producer_parents[0] == producer_parents[1]
    assert (producer_parents[0] is None) is should_reset


@pytest.mark.parametrize("should_reset", [False, True])
def test_async_iterator_restores_each_task_and_closes(tracer: tracing.Tracer, *, should_reset: bool) -> None:
    """Allow separate tasks to advance an async iterator without stale context tokens and close it on early exit."""
    producer_parents: Final[list[str | None]] = []
    closed: Final[list[bool]] = []

    async def produce() -> AsyncGenerator[int]:
        try:
            producer_parents.append(tracing.Context.get_current().parent)
            yield 1
            producer_parents.append(tracing.Context.get_current().parent)
            yield 2

        finally:
            closed.append(True)

    async def exercise() -> None:
        iterator: Final = (
            tracer.with_reset_context_aiter(produce)()
            if should_reset
            else tracer.with_span_aiter(tracing.Level.INFO)(produce)()
        )
        assert isinstance(iterator, AsyncGenerator)

        async def consume() -> int:
            with tracer.span(tracing.Level.INFO, "consumer"):
                parent: Final[str | None] = tracing.Context.get_current().parent
                result: Final[int] = await anext(iterator)
                assert tracing.Context.get_current().parent == parent
                return result

        assert await asyncio.create_task(consume()) == 1
        assert await asyncio.create_task(consume()) == 2
        await iterator.aclose()

    asyncio.run(exercise())
    assert closed == [True]
    assert producer_parents[0] == producer_parents[1]
    assert (producer_parents[0] is None) is should_reset


@pytest.mark.parametrize("should_include_consumer", [False, True])
def test_iterator_consumer_option(tracer: tracing.Tracer, *, should_include_consumer: bool) -> None:
    """Include consumer work only when requested and restore the outer context after full iteration."""
    parents: Final[list[str | None]] = []

    @tracer.with_span_iter(tracing.Level.INFO, should_include_consumer_=should_include_consumer)
    def produce() -> Generator[int]:
        parents.append(tracing.Context.get_current().parent)
        yield 1

    with tracer.span(tracing.Level.INFO, "outer"):
        outer: Final[str | None] = tracing.Context.get_current().parent
        item: int
        for item in produce():
            assert item == 1
            assert tracing.Context.get_current().parent == (parents[0] if should_include_consumer else outer)

        assert tracing.Context.get_current().parent == outer


@pytest.mark.parametrize("should_reset", [False, True])
@pytest.mark.parametrize("should_suppress", [False, True])
def test_contextmanager_teardown_and_suppression(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter, *, should_reset: bool, should_suppress: bool
) -> None:
    """Run setup and teardown under the same context while honoring generator-based exception suppression."""
    parents: Final[list[str | None]] = []
    caught: Final[list[str]] = []

    def resource() -> Generator[str]:
        parents.append(tracing.Context.get_current().parent)
        try:
            yield "resource"

        except ValueError as exception:
            caught.append(str(exception))
            if not should_suppress:
                raise

        finally:
            parents.append(tracing.Context.get_current().parent)

    with tracer.span(tracing.Level.INFO, "caller"):
        parent: Final[str | None] = tracing.Context.get_current().parent
        with pytest.raises(ValueError, match="consumer") if not should_suppress else contextlib.nullcontext():
            value: str
            with (
                tracer.with_reset_context_contextmanager(resource)()
                if should_reset
                else tracer.with_span_contextmanager(tracing.Level.INFO)(resource)()
            ) as value:
                assert value == "resource"
                assert tracing.Context.get_current().parent == parent
                _raise_consumer_error()

        assert tracing.Context.get_current().parent == parent

    assert caught == ["consumer."]
    assert len(parents) == 2
    assert parents[0] == parents[1]
    assert (parents[0] is None) is should_reset
    error_spans: Final = [span for span in exporter.get_finished_spans() if len(span.events) != 0]
    assert len(error_spans) == (0 if should_reset or should_suppress else 1)


@pytest.mark.parametrize("should_reset", [False, True])
@pytest.mark.parametrize("should_suppress", [False, True])
def test_async_contextmanager_teardown_and_suppression(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter, *, should_reset: bool, should_suppress: bool
) -> None:
    """Preserve async setup and teardown contexts and propagate or suppress the consumer's original exception."""
    parents: Final[list[str | None]] = []

    async def resource() -> AsyncGenerator[str]:
        parents.append(tracing.Context.get_current().parent)
        try:
            yield "resource"

        except ValueError:
            if not should_suppress:
                raise

        finally:
            parents.append(tracing.Context.get_current().parent)

    async def exercise() -> None:
        with tracer.span(tracing.Level.INFO, "caller"):
            parent: Final[str | None] = tracing.Context.get_current().parent
            with pytest.raises(ValueError, match="consumer") if not should_suppress else contextlib.nullcontext():
                value: str
                async with (
                    tracer.with_reset_context_acontextmanager(resource)()
                    if should_reset
                    else tracer.with_span_acontextmanager(tracing.Level.INFO)(resource)()
                ) as value:
                    assert value == "resource"
                    assert tracing.Context.get_current().parent == parent
                    _raise_consumer_error()

            assert tracing.Context.get_current().parent == parent

    asyncio.run(exercise())
    assert len(parents) == 2
    assert parents[0] == parents[1]
    assert (parents[0] is None) is should_reset
    error_spans: Final = [span for span in exporter.get_finished_spans() if len(span.events) != 0]
    assert len(error_spans) == (0 if should_reset or should_suppress else 1)


@pytest.mark.parametrize("yield_count", [0, 2])
def test_invalid_contextmanager_protocol_closes_generator(tracer: tracing.Tracer, yield_count: int) -> None:
    """Reject zero or multiple yields like contextlib does, and still run the generator's final cleanup."""
    closed: Final[list[bool]] = []

    @tracer.with_span_contextmanager(tracing.Level.INFO)
    def resource() -> Generator[int]:
        try:
            yield from range(yield_count)

        finally:
            closed.append(True)

    with pytest.raises(RuntimeError, match="generator didn't"), resource():
        pass

    assert closed == [True]


def test_reset_function_decorators(tracer: tracing.Tracer) -> None:
    """Reset sync and async function calls to an empty parent without changing their caller's context."""

    @tracer.with_reset_context_sync
    def run() -> bool:
        return tracing.Context.get_current().is_empty

    @tracer.with_reset_context_async
    async def arun() -> bool:
        return tracing.Context.get_current().is_empty

    with tracer.span(tracing.Level.INFO, "outer"):
        parent: Final[str | None] = tracing.Context.get_current().parent
        assert run()
        assert asyncio.run(arun())
        assert tracing.Context.get_current().parent == parent


@pytest.mark.parametrize("yield_count", [0, 2])
def test_invalid_async_contextmanager_closes_generator(tracer: tracing.Tracer, yield_count: int) -> None:
    """Match asynccontextmanager's one-yield contract and clean up when setup or teardown violates it."""
    closed: Final[list[bool]] = []

    @tracer.with_span_acontextmanager(tracing.Level.INFO)
    async def resource() -> AsyncGenerator[int]:
        try:
            item: int
            for item in range(yield_count):
                yield item

        finally:
            closed.append(True)

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="generator didn't"):
            async with resource():
                pass

    asyncio.run(exercise())
    assert closed == [True]


@pytest.mark.parametrize("should_include_consumer", [False, True])
def test_async_iterator_consumer_option(tracer: tracing.Tracer, *, should_include_consumer: bool) -> None:
    """Choose whether async consumer work shares the producer's parent, restoring the outer context at exhaustion."""
    parents: Final[list[str | None]] = []

    @tracer.with_span_aiter(tracing.Level.INFO, should_include_consumer_=should_include_consumer)
    async def produce() -> AsyncGenerator[int]:
        parents.append(tracing.Context.get_current().parent)
        yield 1

    async def exercise() -> None:
        with tracer.span(tracing.Level.INFO, "outer"):
            outer: Final[str | None] = tracing.Context.get_current().parent
            item: int
            async for item in produce():
                assert item == 1
                assert tracing.Context.get_current().parent == (parents[0] if should_include_consumer else outer)

            assert tracing.Context.get_current().parent == outer

    asyncio.run(exercise())


def test_iterator_failure_is_recorded(tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter) -> None:
    """Record failures raised after yielding, even though the iterator's parent span was already exported."""

    @tracer.with_span_iter(tracing.Level.INFO)
    def produce() -> Generator[int]:
        yield 1
        message: Final[str] = "Producer failed."
        raise ValueError(message)

    iterator: Final[Generator[int]] = produce()
    assert next(iterator) == 1
    with pytest.raises(ValueError, match="Producer failed"):
        next(iterator)

    spans: Final = exporter.get_finished_spans()
    assert len(spans[-1].events) == 1
    assert spans[0].context is not None
    assert spans[-1].parent is not None
    assert spans[-1].parent.span_id == spans[0].context.span_id


def test_async_iterator_failure_is_recorded(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter
) -> None:
    """Record async producer failures under their ended parent and propagate the original failure to the consumer."""

    @tracer.with_span_aiter(tracing.Level.INFO)
    async def produce() -> AsyncGenerator[int]:
        yield 1
        message: Final[str] = "Producer failed."
        raise ValueError(message)

    async def exercise() -> None:
        iterator: Final[AsyncGenerator[int]] = produce()
        assert await anext(iterator) == 1
        with pytest.raises(ValueError, match="Producer failed"):
            await anext(iterator)

    asyncio.run(exercise())
    spans: Final = exporter.get_finished_spans()
    assert len(spans[-1].events) == 1
    assert spans[0].context is not None
    assert spans[-1].parent is not None
    assert spans[-1].parent.span_id == spans[0].context.span_id


def test_contextmanager_normal_exit_and_code_location(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter
) -> None:
    """Run normal teardown and report the user's generator location instead of the tracing wrapper's source."""
    closed: Final[list[bool]] = []

    def resource() -> Generator[int]:
        yield 1
        closed.append(True)

    with tracer.with_span_contextmanager(tracing.Level.INFO)(resource)():
        pass

    span: Final[sdk_trace.ReadableSpan] = exporter.get_finished_spans()[0]
    assert span.attributes is not None
    assert span.attributes["code.lineno"] == resource.__code__.co_firstlineno
    assert span.attributes["code.filepath"] == "src/devkit_tests/test_tracing.py"
    assert closed == [True]


def test_async_contextmanager_normal_exit(tracer: tracing.Tracer) -> None:
    """Await normal teardown immediately when an async resource leaves its with block."""
    closed: Final[list[bool]] = []

    @tracer.with_span_acontextmanager(tracing.Level.INFO)
    async def resource() -> AsyncGenerator[int]:
        yield 1
        closed.append(True)

    async def exercise() -> None:
        async with resource():
            pass

        assert closed == [True]

    asyncio.run(exercise())


def test_remote_failure_preserves_traceback(
    tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter
) -> None:
    """Record a failure under its transported parent while keeping the original exception and traceback intact."""
    exception: Final[ValueError] = ValueError("failure")
    context: Final[tracing.Context] = tracing.Context(parent=_PARENT)

    @context.attach_sync(tracer=tracer, is_remote=True)
    def fail() -> None:
        raise exception

    caught: pytest.ExceptionInfo[ValueError]
    with pytest.raises(ValueError, match="failure") as caught:
        fail()

    assert caught.value is exception
    assert caught.traceback[-1].name == "fail"
    span: Final[sdk_trace.ReadableSpan] = exporter.get_finished_spans()[-1]
    assert span.parent is not None
    assert span.parent.span_id == int(_PARENT[36:52], 16)


def test_async_decorator_reuse(tracer: tracing.Tracer, exporter: memory_export.InMemorySpanExporter) -> None:
    """Keep function-specific source data and argument overrides when one async decorator wraps multiple functions."""
    decorate: Final = tracer.with_span_async(tracing.Level.INFO, include_args_=True, value="static")

    @decorate
    async def first(value: int = 2) -> int:
        return value

    @decorate
    async def second(value: int = 3) -> int:
        return value

    assert asyncio.run(first()) == 2
    assert asyncio.run(second()) == 3
    spans: Final = exporter.get_finished_spans()
    assert spans[0].attributes is not None
    assert spans[1].attributes is not None
    assert spans[0].attributes["code.function"] == first.__qualname__
    assert spans[1].attributes["code.function"] == second.__qualname__
    assert spans[0].attributes["value"] == 2
    assert spans[1].attributes["value"] == 3


def _raise_consumer_error() -> None:
    message: Final[str] = "consumer."
    raise ValueError(message)
