# Tracing

`devkit.tracing` wraps Logfire with caller-based names, explicit levels, portable parent contexts, and decorators
for functions, iterators, and context managers. Importing the package does not configure Logfire. Configure it once
in the application's entry point; the application owns exporter settings, credentials, flushing, and shutdown.

```python
from typing import Final

import logfire

from devkit import tracing

logfire.configure(send_to_logfire=False)
tracer: Final[tracing.Tracer] = tracing.Tracer(__name__)


@tracer.with_span_sync(tracing.Level.INFO, include_args_={"item_id"}, should_include_return_=True)
def load(item_id: str) -> str:
    tracer.info("loaded", item_id=item_id)
    return item_id
```

This example writes to the console without uploading to Logfire. Use the
[Logfire configuration reference](https://pydantic.dev/docs/logfire/api/logfire/) to configure your application's
export destination. Every `Tracer` uses Logfire's default instance, so module-level tracers can be created before
`logfire.configure()` runs. The wrapper does not add application-specific tags.
`get_child("worker", tags={"worker"})` extends the scope
and inherits existing tags.

## Logs and spans

`trace`, `debug`, `info`, `notice`, `warning`, `error`, and `fatal` emit events. Each accepts an optional name suffix,
`message_`, `tags_`, `exception_`, `should_reset_context_`, and arbitrary attributes. The trailing underscores
separate control options from ordinary event attributes. Names include the caller's module and qualified function
name; a suffix such as `"loaded"` is appended to it.

```python
with tracer.span(tracing.Level.INFO, "fetch", item_id="item-1"):
    tracer.info("cached", item_id="item-1")
    tracer.set_attributes_to_current_span(tracing.Level.INFO, result={"cached": True})
```

A span normally stays open until its block finishes. `should_keep_open_=False` exports the parent immediately,
then attaches its context while the body runs. Children retain that parent; failures become separate error events.
The closed parent cannot receive later attributes or a return value. Its duration measures span creation, not the
whole operation. Use this mode only when immediate parent visibility matters more than measuring total duration.

`Level` values use OpenTelemetry severity numbers. `tracer.level` is the configured numeric minimum, including
custom thresholds between named levels. `tracer.logfire_instance` exposes the scoped default instance as a public `Final` field.
Structured current-span attributes currently use a Logfire internal serialization helper to retain JSON schemas;
the integration tests cover that dependency when upgrading the SDK.

## Decorators

| Work | Decorator | Lifetime |
| --- | --- | --- |
| Synchronous function | `with_span_sync` | Open during the call by default |
| Coroutine | `with_span_async` | Open across awaits by default |
| Iterator | `with_span_iter` | Parent exported when called; context attached during iteration |
| Async iterator | `with_span_aiter` | Parent exported when called; context attached during async iteration |
| Generator-based context manager | `with_span_contextmanager` | Parent exported at entry; context attached for setup and teardown |
| Async generator-based context manager | `with_span_acontextmanager` | Parent exported at entry; context attached for async setup and teardown |

All accept a level, optional `name_`, `message_`, `tags_`, and static attributes. `name_` replaces the qualified
function name for decorators. `include_args_` defaults to `False`; use `True` for all arguments, a set of parameter
names for a subset, or a mapping from attribute names to argument paths, such as `{"user_id": "user.id"}`.
Selected arguments include default values and override static attributes with the same name. Argument binding
uses string annotations, so creating a decorator does not evaluate Python 3.14 deferred annotations.

Argument and return capture are opt-in. Choose fields deliberately because traces can contain sensitive data.
`should_include_return_=True` is available on function and coroutine decorators with open spans.

Iterator decorators return generators with `close()` or `aclose()`. They restore the current caller's context
before yielding and close wrapped generators when explicitly closed. Use `contextlib.closing` or
`contextlib.aclosing` if iteration may stop early; a `break` alone does not close a generator. These wrappers expose
item iteration, not the producer's `send`/`throw` protocol. Context-manager decorators preserve exception propagation,
suppression, and cleanup through the standard library's context-manager protocol.

`should_include_consumer_=True` on iterator decorators keeps the producer's context active while the consumer
handles each item. Finish or close such an iterator in the same execution context that advances it. Leave the option
disabled when separate tasks may take turns consuming an async iterator.

The context-manager decorators replace `contextlib.contextmanager` and `contextlib.asynccontextmanager`; apply them
directly to generator functions. Their caller's `with` body keeps the caller's context.

```python
from collections.abc import Generator


@tracer.with_span_contextmanager(tracing.Level.INFO)
def resource() -> Generator[str]:
    tracer.info("setup")
    try:
        yield "resource"

    finally:
        tracer.info("teardown")
```

## Context propagation and reset

Capture the current trace parent and baggage with `Context.get_current()`. `to_json_dict()` and `from_json_dict()`
transport an optional `traceparent` and a `baggage` mapping. `to_bytes()` and `from_bytes()` use MessagePack for the
same values. The parent supports W3C version-00 traceparent values and rejects malformed values and zero IDs.
Baggage keys and values must be strings. Keep baggage small and free of secrets because it can propagate to other
services. `Context.is_empty` is true only when both parent and baggage are absent.

```python
with logfire.set_baggage(tenant="alpha"):
    context: Final[tracing.Context] = tracing.Context.get_current()

payload: Final[dict[str, str | dict[str, str]]] = context.to_json_dict()

with tracing.Context.from_json_dict(payload).attach(tracer=tracer, is_remote=True):
    tracer.info("worker_started")
```

Attaching replaces the current parent and baggage, then restores both on exit, including exceptional exits.
Use `is_remote=True` when errors
need their own child log because the attached parent is no longer a writable local span. Ordinary exceptions are
recorded and re-raised unchanged; cancellation and generator shutdown propagate without an extra error log.
`attach_sync` and `attach_async` provide the same behavior as decorators.

`tracer.reset_context()` temporarily starts from an empty parent and baggage. Decorator equivalents are
`with_reset_context_sync`, `with_reset_context_async`, `with_reset_context_iter`, `with_reset_context_aiter`,
`with_reset_context_contextmanager`, and `with_reset_context_acontextmanager`. Reset iterator and context-manager
wrappers isolate producer/setup/teardown work while preserving the consumer's context.
