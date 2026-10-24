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

- Type receivers as `self: Self` and `cls: type[Self]`, and make them positional-only.
- Protocol properties use bare `self`; protocol methods still use `Self`.
- Use positional-only parameters for callbacks and to prevent collisions with caller-supplied `**kwargs` keys.
  Do not add `/` to ordinary module functions or static methods without one of those reasons.
- Make optional arguments, booleans, and injected dependencies keyword-only. Callbacks may accept positional booleans.
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

## Classes and privacy

Instance attributes are private (`__name`) by default; use protected (`_name`) only for inheritance and public names
only when direct external access is required. For a simple read-only value, prefer a public `Final` field over a
private field with a getter-only property. Use properties for computed values or controlled access to mutable internal
state. `Final` prevents reassignment through static type checking; it does not enforce runtime immutability or freeze
the referenced object. Use `ClassVar` for class attributes; mutate those through `cls`, not `self`. Use a classmethod
when a method needs the class, and a staticmethod otherwise.

Define `__slots__: ClassVar[tuple[str, ...]]`, including an empty tuple when appropriate. Skip explicit slots for
Pydantic models and dataclasses that manage their own layout. Assign instance attributes in parameter order.

```python
@final
class Account:
    __slots__: ClassVar[tuple[str, ...]] = ("__region", "name")

    @classmethod
    def create(cls: type[Self], /, name: str) -> Self:
        return cls(name, region="default")

    def __init__(self: Self, /, name: str, *, region: str) -> None:
        self.name: Final[str] = name
        self.__region: Final[str] = region
```

At module scope, use `_name` for internal symbols, never `__name`. Declare symbols consumed by other files, including
tests, in `__all__: Final[tuple[str, ...]]`. Tests use the same public interfaces as other consumers.
Pytest-discovered tests and fixtures stay out of `__all__` unless another module also imports them. Empty package
markers need no `__all__`.

## Imports and namespaces

Use module namespaces for project and third-party imports. Direct imports are allowed for the standard library,
`typing`, shared `common.types`, and when extending a library or using its already-qualified type names.
Alias a module when a parameter or local would shadow it; do not create type aliases just to work around shadowing.

```python
# Namespace stays visible at the call site.
from devkit.data import catalog as data_catalog

# Standard-library types can be imported directly.
from pathlib import Path
from typing import Final


def load(path: Path, *, catalog: data_catalog.Interface) -> bytes:
    return catalog.read(path)
```

Choose package exports by meaning:

- One concept split across files: re-export its public symbols from `__init__.py`.
- A cohesive sub-namespace: re-export the module when callers need that namespace.
- Independent sibling modules: leave the package marker empty and import the needed submodule directly.

Submodules import siblings directly, not through their own package facade. Only access a submodule through a package
object when its `__init__.py` explicitly exports that submodule.

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

Boolean names start with `is_`, `has_`, `use_`, `should_`, `can_`, or `allow_`. Callback functions and methods start
with `on_`; callback parameters also end with `_callback`, such as `on_event_callback`.
Include units in names when the type does not express them: `timeout_s`, `price_usd`, `fee_bps`.

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
For other code, do not add docstrings unless requested. Comments explain non-obvious rationale, not what the code already says.
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
