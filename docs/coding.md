# Coding conventions

Keep this file focused on house style and constraints that need human judgment. Tool configuration lives in
`pyproject.toml`; custom checks live in `src/devkit_tests/conventions/`. Run `make format lint test` to verify a change.
Install the source-check and Conventional Commit hooks with `make install-hooks`.
The examples below illustrate individual rules; the convention tests define the mechanically checked edge cases.

## Types and signatures

Annotate variables, parameters, and returns. Use `Final` for names that are not reassigned, and `@final` for classes
unless they are designed for inheritance. Prefer immutable containers for shared values.

Accept abstract collection types and return concrete types. Use `object` for values that need inspection and narrowing;
reserve `Any` for genuinely unconstrained contracts, not as a way around type checking.

```python
from collections.abc import Mapping
from typing import Final


def merge(base: Mapping[str, int], override: Mapping[str, int]) -> dict[str, int]:
    result: Final[dict[str, int]] = dict(base)
    result.update(override)
    return result
```

Annotate loop and context-manager targets immediately above their statement, inside the same block. Declare a loop
variable once per scope; do not repeat its annotation for later loops.

```python
index: int
for index in range(10):
    process(index)

try:
    file: IO[str]
    with path.open() as file:
        consume(file)

except OSError as exception:
    handle(exception)
```

- Type receivers as `self: Self` and `cls: type[Self]`, and make them positional-only. A generic class may
  specialize `self` to restrict a method to a type state, such as `Session[TX].commit`.
- Protocol properties use bare `self`; protocol methods still use `Self`.
- Use positional-only parameters for callbacks and to prevent collisions with caller-supplied `**kwargs` keys.
  Do not add `/` to ordinary module functions or static methods without one of those reasons.
- Make optional arguments and booleans keyword-only. Callbacks may accept positional booleans.
- Use `raise NotImplementedError` in overload stubs and unimplemented protocol methods, rather than `...`.

```python
class Catalog(Protocol):
    @property
    def path(self, /) -> Path:
        raise NotImplementedError

    def read(self: Self, /, key: str, *, should_refresh: bool = False) -> bytes:
        raise NotImplementedError


def on_event(event: Event, /) -> None:
    process(event)


def describe(event: Event) -> str:
    return str(event)
```

At call sites, pass literal values by keyword when the API permits it, so their meaning is visible without inspecting
the signature. Enum members may be passed positionally when their qualified names make the call clear, such as
`connect(Timeouts.DEFAULT)`. This exception does not change keyword-only parameter requirements.
The call-site gate checks statically resolved, undecorated functions in the same file, including nested and async
functions. Calls through imports, methods, decorators, dynamic bindings, or positional unpacking remain review
checks, as do calls inside lambdas or comprehensions and whether an enum name makes the call clear.

```python
# Name the meaning of a literal value.
connect(timeout_s=30)

# Avoid an unexplained positional literal when a keyword is accepted.
connect(30)

# A descriptive enum member can make a positional argument clear.
connect(Timeouts.DEFAULT)
```

Choose parameter order by role: first the object acted on, then the operation's payload, then modifiers or options.
Within a role, group related arguments together, such as two timeouts before a connection count. Keep that order
across related definitions and call sites. The receiver (`self` or `cls`) naturally comes first.

```python
def write(self: Self, /, record: Record, data: bytes, *, should_replace: bool = False) -> None:
    ...

def read(self: Self, /, record: Record, *, should_refresh: bool = False) -> bytes:
    ...

def open_pool(creator: Creator, idle_timeout: float, acquire_timeout: float, max_connection_count: int) -> Pool:
    ...
```

## Classes and privacy

Instance attributes are private (`__name`) by default; use protected (`_name`) only for inheritance and public names
only when direct external access is required. For a simple read-only value, prefer a public `Final` field over a
private field with a getter-only property. Use properties for computed values or controlled access to mutable internal
state. `Final` prevents reassignment through static type checking; it does not enforce runtime immutability or freeze
the referenced object. Use `ClassVar` for class attributes; mutate those through `cls`, not `self`. Use a classmethod
when a method needs the class, and a staticmethod otherwise.
Name class-owned constants in uppercase, including private ones such as `__TRACER`. Keep framework-required names
such as `model_config`, `cache_ok`, and `__slots__` in their required spelling.

Define `__slots__: ClassVar[tuple[str, ...]]`, including an empty tuple when appropriate. Skip explicit slots for
Pydantic models and dataclasses that manage their own layout. If a base class or its type stubs declare a member
incorrectly, use the correct annotation in the subclass and suppress only the resulting false-positive diagnostic.
Explain the mismatch immediately above the suppression. Assign instance attributes in parameter order.

```python
@final
class Account:
    __slots__: ClassVar[tuple[str, ...]] = ("__region", "name")

    @classmethod
    def create(cls: type[Self], /, name: str) -> Self:
        return cls(name, region="default")

    def __init__(self: Self, /, name: str, region: str) -> None:
        self.name: Final[str] = name
        self.__region: Final[str] = region
```

At module scope, use `_name` for internal symbols, never `__name`. Declare symbols consumed by other files, including
tests, in `__all__: Final[tuple[str, ...]]`. Tests use the same public interfaces as other consumers.
Pytest-discovered tests and fixtures stay out of `__all__` unless another module also imports them. Empty package
markers need no `__all__`.

## Imports and namespaces

Import a public class directly when its name is clear and its module mainly defines that class. For example, use
`from devkit.db.settings import Settings` and then `Settings()`, not `settings.Settings()`. The same applies to
`Context`, `Level`, and `Service`. Use a module namespace when it groups related concepts or adds meaning at the call
site, such as `tables.Table`. Direct imports are also allowed for shared `devkit.types`, library base classes, and
already-qualified type names.

Apply the same meaning rule to the standard library. Import clear standalone types directly, such as
`from pathlib import Path`, `from enum import StrEnum`, and `from types import FrameType`, as well as names from
`typing` and `collections.abc`. Keep modules that provide operations or shared state namespaced, such as
`import asyncio` and `import threading`. Use a module namespace when it adds meaning or resolves a collision.

When importing a module, use its own name if that is clear in context. Alias it only for a collision or when its
plain name would imply the wrong owner. For example, an application settings module imported into database code
needs `app_settings`; if both application and database settings modules are needed in one file, alias both. Also
alias a module when a parameter or local would shadow it. Do not create type aliases just to work around shadowing.

When several modules from one library are imported, choose recognizable aliases that share a prefix and identify
each module's role. Use the same scheme in related files so the names remain clear without rechecking their imports.

```python
# In devkit.tracing.tracer: each module exposes one clear public object.
from devkit.tracing.context import Context
from devkit.tracing.level import Level

# In devkit.db.migrations.env: import from the sibling package, and direct files for clear objects.
from devkit.db.tables import Table
from devkit.db.service import Service
from devkit.db.settings import Settings

# In a database module that also reads application-owned settings.
import devkit.app.settings as app_settings

# In an Alembic revision generated from the migration template.
import devkit.db.types

# In devkit.db.service: related SQLAlchemy modules share a recognizable prefix.
import sqlalchemy as sa
import sqlalchemy.ext.asyncio as sa_async

statement: sa.Executable
engine: sa_async.AsyncEngine
```

Choose package exports by meaning:

- One concept split across files: re-export its public symbols from `__init__.py`.
- A cohesive sub-namespace: import the real child module through its package when callers need that namespace.
- Independent sibling modules: leave the package marker empty and import the needed submodule directly.

Import a real child module through its parent when that namespace is useful, such as `from devkit import tracing` in
`devkit.db.service`; Python finds the subpackage even when the parent's `__init__.py` does not export it. A package
facade must explicitly export public objects imported from it. Descendants must import those objects from their
defining module or target package, not from an ancestor's re-export: `devkit.tracing.tracer` imports `Context` from
`devkit.tracing.context`, not from `devkit.tracing`. This applies to absolute and relative imports. A package
initializer may import children to define its exports. The convention gate checks these first-party boundaries.

## Naming

Follow established project terminology. Classes and attributes use nouns; functions and methods use verbs.
Prefer precise nouns over vague `Manager`, `Processor`, or `Dispatcher` names; conventional names such as `Builder`
and `Tracer` are fine when they fit.

Names are read with their namespace. Avoid repeating that namespace in a class name or suffix. Prefer `Interface`
for a base contract. Use suffixes only when no namespace already communicates the distinction.

```python
# Prefer these call-site spellings.
tracing.Context
schemas.DataEntity
events.Interface

# Avoid redundant spellings.
tracing.TracingContext
schemas.DataEntitySchema
```

Prefer boolean names that read as yes-or-no questions, often starting with `is_`, `has_`, `use_`, `should_`, `can_`, or
`allow_`. This is a review guideline, not a convention gate. Callback functions and methods start
with `on_`; callback parameters also end with `_callback`, such as `on_event_callback`.
Include units in names when the type does not express them: `timeout_s`, `price_usd`, `fee_bps`.
Keep names required by third-party APIs, such as SQLAlchemy's `cache_ok`, even when they do not follow these prefixes.
When a configuration field follows an established external option name, such as SQLAlchemy's `pool_timeout` or
`pool_should_pre_ping`, or asyncpg's `command_timeout`, keep that name and document time units where the
configuration is described.

## Expressions and control flow

Use explicit checks for non-boolean values: `is None`, `is not None`, `len(items) == 0`, or `count != 0`.
Prefer early returns and loop exits over nesting. Return synchronous expressions directly; split an awaited call
from subsequent attribute access when that reads more clearly.

```python
if on_event_callback is not None:
    on_event_callback(event)

if len(items) == 0:
    return

response: Final[Response] = await client.run(request)
return response.answer
```

Use `value.__class__` instead of `type(value)`. Use `.pop()` or `.remove()` instead of `del`.

Keep a simple assignment on one line when it fits. Put an explanatory comment above the assignment; do not wrap
the right-hand side in parentheses only to fit the comment. Inline a temporary used once when the resulting
expression remains clear and evaluates its inputs in the same order. Keep a named value when it is reused, names a
meaningful result, or makes an awaited operation easier to read.

When an existing parameter already holds the desired value unless it is missing, assign only in the missing branch.
Use an `if` block instead of assigning the parameter in both branches of a conditional expression. A conditional
expression is suitable when defining a new value from two alternatives.

```python
# The environment supplies the required value at runtime.
settings: Final[Settings] = Settings()

# Preserve an explicitly supplied options object.
if options is None:
    options = Options()

# This is a new value selected from two alternatives.
mode: Final[str] = "read" if should_read else "write"

# A one-use forwarding variable adds no meaning here.
return normalize(source.read())

# Keep this result because both fields are used.
response: Final[Response] = await client.run(request)
record(response.answer, response.usage)
```

## Errors and suppressions

Name exception message variables `message`, annotate them, and end the message with a period. Include the actual
path, identifier, or value that failed. Use `Final[str]` for a single assignment; use `str` when reusing the name
for several raises in the same scope.

```python
if path.is_dir():
    message: Final[str] = f"Expected a file, got directory {path!s}."
    raise ValueError(message)
```

Do not catch an exception only to re-raise it unchanged. When intentionally ignoring an error, prefer
`contextlib.suppress`. Record an exception where it is handled; do not log it and re-raise it for another handler
to log again. Represent unavailable data explicitly rather than substituting a plausible empty value.

Use tool-specific diagnostic codes and place the reason immediately above the suppressed line. When both type
checkers require suppression, put mypy's pragma first. Do not append prose to pragmas.

```python
# The library's stub accepts str, but its runtime also accepts Path.
result = library.read(path)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
```

A runtime workaround for an upstream bug needs a `TODO` stating when it can be removed. Type suppressions need a
reason, but no expiry TODO: the type checkers already detect unnecessary ignores.

## Text and punctuation

Use ASCII characters in prompts, comments, documentation, and skills. Avoid Unicode lookalikes: use `--` instead
of an em dash, `-` instead of an en dash or non-breaking hyphen, and `->` instead of an arrow.

## Comments and layout

Give each test a plain-English docstring explaining what it covers and why, with a small example when useful.
Give public modules, classes, and methods concise docstrings that state their current purpose and important behavior.
Document a private helper only when its role or contract is not clear from its name and code. Write for the reader of
the current API; omit migration history and notes about removed alternatives. Treat docstrings as Markdown: separate
paragraphs with a blank line rather than a single newline. Use a Pydantic `Field(description=...)` for a field-specific
explanation when that is clearer than expanding the class docstring. Keep one blank line after a class docstring, as
Ruff requires. Ruff also checks public docstring coverage. Comments explain non-obvious rationale, not what the code
already says.
Place comments immediately above the statement they describe, in the same block, and end the comment block with a
period. Only tool pragmas belong inline.

Add a blank line whenever indentation decreases, including before `else`, `except`, and `finally`.
For implicitly concatenated strings, put separating spaces at the end of the previous fragment.

```python
if should_retry:
    retry()

else:
    finish()

message: Final[str] = (
    "The first fragment ends with a space so "
    "the continuation starts with a word."
)
```

Let Ruff handle line width, quotes, imports, and formatting. Do not manually wrap a line that fits.

## Definition order

Within a group, use a meaningful order (entity, lifecycle, severity); otherwise sort alphabetically.
Ruff sorts imports, `__all__`, and `__slots__`.

Module groups appear in this order:

1. Public, then private type aliases.
2. Public, then private constants.
3. Public sync, public async, private sync, private async functions.
4. Public, then private classes.

Deviate only for actual definition-time dependencies: constant values, bases, defaults, decorators, or decorators
that evaluate annotations. Ordinary lazy annotations alone do not require reordering.

Class groups appear in this order:

1. Magic, public, protected, then private class attributes.
2. Public, protected, then private factories; then initialization (`__new__`, `__init__`, `__post_init__`).
3. Public properties: abstract read-only, concrete read-only, abstract read-write, concrete read-write.
4. Public sync methods: static/class methods, magic methods, instance methods; abstract before concrete in each group.
5. Public async methods, with the same subgroup order.
6. Protected properties, sync methods, then async methods; abstract before concrete.
7. Private properties, sync methods, then async methods.
8. `__del__` last.

## Custom checks

The convention suite checks annotations, receiver signatures, names, exports, privacy, comments, spacing, statement
choices, and definition order. Keep semantic choices above in review even when a related syntax check exists.
Size ceilings live in `conventions/test_size.py`; they remain enforced independently of this guide.
When changing a convention gate, cover both a violating example and a legitimate example that must still pass.

## Stack and architecture

Group `pyproject.toml` tables by owner: keep `[project]` with its `[project.*]` tables, and keep each tool's
`[tool.NAME]` tables and subsections together.

Use `pydantic-settings` for application configuration and environment values. Define a typed settings model and
validate values at the boundary; do not load `.env` with `python-dotenv` or read `os.environ` directly in application
code. Pass the resulting settings to the part of the application that needs them.

For PostgreSQL-backed applications, prefer PostgreSQL with SQLAlchemy's async declarative ORM. Declare columns with
PostgreSQL dialect types (`sqlalchemy.dialects.postgresql`) when the schema is PostgreSQL-specific; avoid generic
SQLAlchemy types that obscure the exact database schema. Start from the optional template in `src/devkit/db/` and
adapt its table definitions and session boundaries to the application. Put Alembic configuration in
`[tool.alembic]` in `pyproject.toml`, without a separate `alembic.ini`.

Keep modules in coherent layers: foundation holds shared types and policies; adapters handle external systems;
services own application rules; entry points validate requests, call services, and format responses. Dependencies
point toward the foundation. Keep business decisions out of adapters, and keep transport details out of services.
Use only the layers a feature needs; a simple operation does not require four modules.

## Concurrency and resources

Release acquired resources with context managers. Give I/O a bounded timeout. Define how long-lived tasks are
cancelled and shut down. Do not hold a lock across network I/O; protect only the state transition. Write durable
files through an atomic write-then-rename operation so a crash leaves the previous complete version. Keep waits
bounded and avoid unobserved background tasks.

## Tests

Cover both a successful path and relevant failures for each changed behavior. Unit tests should use isolated,
local inputs and avoid network access, long sleeps, and long timeouts. Add a few smoke tests that exercise the
public entry points and wiring, including package import and configuration, without requiring external services.
Use temporary paths and deterministic inputs. If a test needs a real external service, make it a separate
integration test rather than part of the default local suite.
