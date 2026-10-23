# Coding Rules

## About This Document

This is the single source of truth for how code is written in this project. It has four parts:

- **Part I -- Design.** How the code is shaped.
- **Part II -- Correctness.** How it behaves when things go wrong.
- **Part III -- Style.** How a line looks.
- **Part IV -- Practice.** What happens around a change.

**What is already enforced.** `pyproject.toml` configures ruff (~50 rule families), mypy, and pyright in `strict`
mode. Rules that tooling enforces are referenced here by rule code, not restated. Run `make format lint test`
before considering any change complete, and fix every reported error. `make install-hooks` wires the same two
commands into a pre-commit hook, so a commit cannot skip them.

**What a test enforces.** Rules marked `[gated]` are checked by `devkit_tests/conventions/`, which parses both
packages and fails on any file that breaks them. No linter reads them, but they are not house style either: the
build says no. Read the test rather than arguing with it -- it is where the rule's exact edges are written down.

**House-style rules.** Rules marked `[unenforced]` are project conventions that **nothing mechanical will catch**.
They drift unless applied deliberately and checked in review. If a rule marked `[unenforced]` becomes mechanically
checkable, add the check, mark it `[gated]`, and delete the prose the check replaces.

**Contents.**

- **I -- Design:** 1 Pragmatic SOLID - 2 Layers - 3 SSOT - 4 Complexity budgets - 5 Fix the class -
  6 Structured facts - 7 Enforcement over prose
- **II -- Correctness:** 8 Error handling - 9 Identity and data - 10 Resources and concurrency -
  11 Determinism and numerics - 12 Bounding and disclosure - 13 Secrets and untrusted input
- **III -- Style:** 14 Type annotations - 15 Finality and immutability - 16 Self typing -
  17 Overrides and ignores - 18 Argument markers - 19 Class variables - 20 Slots - 21 Module exports -
  22 Namespaced imports - 23 Naming - 24 Privacy - 25 Direct returns - 26 Exception messages -
  27 Exception handling - 28 Blank lines - 29 Early return - 30 Explicit checks - 31 Docstrings -
  32 Comments - 33 Ordering - 34 Static vs class methods - 35 Return vs argument types - 36 Overloads -
  37 `__class__` - 38 `pop`/`remove` - 39 Formatting
- **IV -- Practice:** 40 Testing - 41 Change propagation - 42 Verification - 43 Docs mirror reality -
  44 Tracing and observability - 45 Review conventions - 46 Commit hygiene

---

# Part I -- Design

## 1. Pragmatic SOLID

SOLID is a direction for making changes legible to whoever reads the code next -- not a demand for classes or extra
framework surface.

- **SRP** -- one coherent reason and one clear authority for a unit to change.
- **OCP** -- extend an existing stable seam when it preserves the contract, instead of rewriting unrelated callers.
- **LSP** -- an implementation preserves the caller-visible behaviour of the contract it implements.
- **ISP** -- consumers depend only on the capabilities they actually use, not a broad convenience interface.
- **DIP** -- policy depends on small local `Protocol`s, not on concrete providers or third-party details.

These do **not** require a class hierarchy, a DI container, a numeric score, or a new abstraction layer. A SOLID or
minimalism objection must name the exact symbol, the concrete duplication or coupling, and a smaller alternative that
still satisfies the contract. Diff size, line count, and file count alone are not findings.

```python
from decimal import Decimal
from typing import ClassVar, Final, Protocol, Self, final

__all__: Final[tuple[str, ...]] = ("Pricing", "Quotes")


# DIP: the policy owns the narrow contract it needs, small enough that a fake is one class (ISP).
class Quotes(Protocol):
    def last(self: Self, /, symbol: str) -> Decimal:
        raise NotImplementedError


@final
class Pricing:
    __slots__: ClassVar[tuple[str, ...]] = ("__quotes",)

    def __init__(self: Self, /, *, quotes: Quotes) -> None:
        self.__quotes: Final[Quotes] = quotes
```

Prefer `Protocol` seams over ABCs unless subclasses genuinely share implementation. Prefer composition over
inheritance; inheritance is for sharing behaviour, not for reusing fields.

## 2. Layers and Boundaries

Every module belongs to exactly one layer, and the layer determines what it may contain.

- **Foundation** -- what every layer above is allowed to reach for and what reaches for nothing itself: the error
  hierarchy (section 8), the settings SSOT (section 3), the tracing API (section 44). A module belongs here only if it depends on nothing
  else in this project.
- **Adapter** -- transport only. Wraps an external API, filesystem, or process into typed calls. No business logic, no
  routing, no decisions. Primitives in, primitives out. Stateless where possible. Translates foreign errors into this
  project's error types.
- **Service** -- owns a domain concern. Holds the rules, coordinates adapters, manages state.
- **Entry point** -- CLI command, HTTP route, task, or tool. Thin: validate input, delegate, format output.

Not every call needs every layer -- a trivial read may go from entry point straight to the filesystem. What is not
allowed is a layer doing another layer's job: business logic inside an adapter, or transport details leaking into a
service.

Dependencies point inward, and the permitted edges are exactly these:

| Layer | May import |
|---|---|
| Foundation | Foundation |
| Adapter | Foundation |
| Service | Service, Adapter, Foundation |
| Entry point | Entry point, Service, Adapter, Foundation |

An adapter reaching the foundation is the one apparent exception, and it is the reason the foundation is a layer
rather than an unwritten habit: translating a foreign error into this project's error types is a thing an adapter is
*required* to do, so the error hierarchy cannot be off-limits to it. Anything beyond that is business logic, which
belongs in a service.

`[gated]` -- `conventions/test_layers.py` holds the layer of every module and the table above, so a new module is
classified before it can import anything, and a stale entry fails just as loudly as a missing one.

## 3. DRY / Single Source of Truth

Every fact, constant, rule, default, format, and threshold lives in exactly one canonical location. Every other
reference points to it.

- No magic numbers or magic strings at a call site. Name them as `Final` constants in the module that owns the concept.
- When a fact moves, every reference moves **in the same change**.
- Before adding a mechanism, name the existing one that already covers the need. A second parallel mechanism is the
  defect, not the shortcut.

A system that says two different things about itself cannot see its own contradiction. The fix is always structural:
one source, the rest are pointers.

## 4. Complexity Budgets

Complexity is the enemy of comprehension. Every line must justify its existence.

- **Module** -- target ~500 lines, hard limit 1000 `[gated]`. Crossing the target is pressure to extract; crossing the
  limit requires extraction or an explicit written justification.
- **Function/method** -- target 50 lines, hard limit 150 `[gated]`. Only the ceilings are checked: a gate that fires at
  the target is a gate nobody keeps green, and one nobody keeps green stops being read.
- **Parameters** -- at most 8 (`PLR0913`, configured; `self`/`cls` and `*args`/`**kwargs` are not counted). Prefer 5
  or fewer. Further knobs ride in a typed options object, never as new parameters -- except where the tail of the
  signature is `**attributes`/`**kwargs`, which forces reserved keywords to stay flat (section 44). That exception is the
  reason the configured limit is 8 rather than ruff's default of 5.
- **Branching** -- cyclomatic complexity at most 10 (`C901`).
- **Net growth** -- adding a feature starts by simplifying what exists. Net complexity growth per change approaches
  zero.
- **No speculative abstraction.** An abstract layer, generic parameter, or extension hook with no second concrete
  consumer *in this change* is waste. If a feature is not used yet, it is premature.
- **Delete dead code** on sight. Unused code is not free; it is read, maintained, and reviewed forever.

## 5. Fix the Class, Not the Instance

When something breaks, the response is not to fix the specific occurrence. The response is: **what must change so that
this entire class of failure becomes structurally impossible?**

- **The class test.** After a fix, ask: if this fix had existed before, could today's failure still have arrived
  through a different surface? If yes, the fix is at the wrong depth.
- **Discipline is not a fix.** Adding a bullet to a document, a comment, or a checklist item is training, not
  structure. If the same class recurs after two behavioural rules, the problem is the structure, not memory.
- **Smallest structural change wins.** Structural depth is not scope breadth. A tightened contract, a required
  argument, a deleted duplicate, or one well-placed test usually beats a new layer. If a proposed fix adds surface
  area, ask whether a subtraction works instead.

## 6. Structured Facts Over String Matching

Control flow decides on typed, structured facts -- enums, status objects, parsed results, explicit fields -- never on
keyword search, substring checks, or regex over content.

```python
# Bad - decision by string matching; breaks the moment wording changes.
if "not found" in error.message:
    return None

# Good - decision by a typed fact.
if error.kind is ErrorKind.NOT_FOUND:
    return None
```

If a decision needs a fact the data does not carry, add the field. Do not pattern-match the text.

Use `StrEnum` for closed sets, and make lookups over them total: a mapping keyed by every member, raising `KeyError`
on an unknown key rather than falling back to a default. A `match` over a closed enum must not carry a `case _` that
silently absorbs a new variant -- let `reportUnreachable` prove the cases are exhaustive.

## 7. Enforcement Over Prose

A rule that lives only in a document is a rule that will be broken. If a rule can be a lint rule, a type, a required
argument, or a test -- make it one, and let this document merely point at it.

Patterns, in order of preference:

1. **Make it a type.** An illegal state that cannot be constructed needs no rule.
2. **Required typed argument at the consuming seam.** A future call site then cannot silently skip the invariant.

   ```python
   # The caller must state the origin, or state why there is none. Omission is a type error.
   def bind(self: Self, /, task: Task, *, origin: Origin | AbsenceReason) -> None: ...
   ```

3. **Chokepoint plus allowlist test.** One function is the only legal way to do a dangerous thing (spawn a process,
   write durable state, construct a client), and a test walks the codebase and fails on direct use, with an explicit
   allowlist of exceptions.
4. **Gate, not report.** A recorded flag that nothing refuses on is a footnote, and a footnote cannot protect
   anything. Enforcement belongs at the boundary, *before* anything costly or mutating happens.
5. **Only then, a written rule** -- marked `[unenforced]`.

Two corollaries:

- **Fail closed.** When a check cannot be performed, refuse. Unknown success is not success: never map "no exception"
  or "exit code 0" to success when a real result is available to read.
- **Cheap checks first.** Deterministic checks run before expensive ones, so the expensive ones are never spent on a
  change that a type or a lint rule would have rejected.

---

# Part II -- Correctness

## 8. Error Handling

Semantics; formatting rules are section 26 and section 27.

- Define a package-local exception hierarchy with one root. Raise the narrowest type that describes the failure.
- **Fail loud.** No `except Exception: pass`. No silent fallback. No compatibility shim without a **concrete,
  reachable** failure mode you can name -- "just in case" is not a failure mode.
- **Unknown is not a default.** Missing, unavailable, or unverified data is represented as missing -- `None`, a typed
  absence reason, an explicit sentinel -- never as `0`, `""`, `[]`, or a plausible guess. A read failure that reports
  zero is worse than one that reports nothing, because zero looks authoritative.
- **Classify before retrying.** Authentication, quota, malformed-request, and too-large failures are terminal: record
  the category and surface a recovery hint. Only transient failures (timeout, rate limit, connection reset) take the
  retry path. Retrying a terminal failure burns budget and hides the cause.
- Chain when re-wrapping: `raise Wrapped(message) from exception` (`B904`).
- Error messages name the actual artifact -- the path, symbol, id, or value that failed -- not a category.
- Fix the smallest structural cause and then verify. Do not widen the catch to make a symptom disappear.

## 9. Identity and Data Discipline

Rules for anything that is stored, compared, reconciled, or deduplicated. Most silent data bugs come from breaking one
of these.

1. **Capture identity at creation and pass it by value as a typed reference.** Never re-derive identity later by
   matching content -- text, hashes, prefixes. Content is routinely rewritten between creation and use, so
   content-derived lookup fails exactly on the normal path.

   ```python
   # Bad - re-derives which record this was by searching for matching content.
   record = next(record for record in records if record.text == text)

   # Good - identity was captured where the record was created, and travels with it.
   record = store.get(reference.record_id)
   ```

2. **Hashes have exactly two legitimate roles:** an *integrity check* on an already-known identity (confirming the
   record was not swapped), and *content addressing* where the content genuinely **is** the identity. A hash is never
   the lookup key for a record that has an id.
3. **Sameness must be an equivalence relation.** Use one typed key, not a fallback chain of matching rules. A chain is
   not transitive -- `A` matches `B`, `B` matches `C`, while `A` and `C` are explicitly different -- so "the same"
   becomes ill-defined and order-dependent. No care at the call sites can repair a relation that is not an
   equivalence.
4. **A normalization that discards information the identity depends on is not a normalization.** Collapsing whitespace
   inside a quoted argument, trimming a path (a leading space is a legal filename byte), or lowercasing a
   case-sensitive key makes two different things compare equal.
5. **Order: canonicalize raw values -> render -> bound.** Rendering is lossy (redaction, truncation, formatting), so
   compare and deduplicate *before* it, never after.
6. **Changing a stored format means versioning it.** Stamp the record with the format that produced it, and treat
   different formats as *unknown-equal*, never as equal. Check a migration in **both** directions: what it makes fail
   that used to match, *and* what it makes match that used to fail. Reasoning about one direction only is how format
   changes introduce false positives.
7. **Whatever decides must be what is reported.** The reporting path reads the same projection the deciding path
   reads. A report re-derived beside the decision will eventually describe a decision that was never made.
8. **A property of a closed set of kinds belongs in the set.** Put it in the table keyed by kind, so a new kind cannot
   be added without answering the question, and a per-kind fix cannot be mistaken for a fix of the class.

## 10. Resources, Concurrency, and Durable State

- Every acquired resource is released by a context manager. Never a manual acquire/release pair.
- Every I/O call has an explicit timeout, taken from the constants SSOT (section 3).
- No global mutable state. Module-level names are `Final` and immutable.
- Every long-lived task defines its cancellation and shutdown semantics. A task nobody can stop is a leak.
- Never hold a lock across network I/O. Hold it for the state transition only.
- Durable files are written through one shared atomic write-then-rename helper (temp sibling, `os.replace`), so a
  crash leaves the previous content intact. Appends are **not** atomic -- never rely on them being so.
- Prefer a bounded wait with a reason over an unbounded one; prefer a re-decidable wait that extends while progress is
  observed over a single fixed cutoff that discards in-flight work. Keep an outer hard limit regardless.

## 11. Determinism, Time, and Numerics

- **No wall clock inside logic.** Inject a clock or pass the timestamp in. Code that calls `now()` internally cannot be
  tested or replayed.
- All datetimes are timezone-aware and UTC at boundaries (`DTZ`). A naive datetime never crosses a function boundary.
- **Seeds are inputs.** Anything random takes an explicit seed, and the seed is recorded alongside the result.
- Use `Decimal` where exactness is part of the contract (money, prices, quantities). Use `float` for measurements and
  statistics, and never compare floats with `==` -- compare against an explicit tolerance.
- Units and conventions live in the name or the type (`price_usd`, `timeout_s`, `fee_bps`), never only in a comment.
- **Re-derive what matters.** A number that drives a decision is checked by a second, independent method before it is
  reported.

## 12. Bounding and Disclosure

- Never hand-roll `text[:n]` on anything that will be read, compared, or reported later.
- Bounding goes through one shared helper that appends an explicit omission marker **and** the omitted count. A bounded
  collection also carries a reference or hash of the full set when anything downstream compares it.
- A cut that saves fewer characters than its own omission marker is pure damage -- pass the value through whole.
- Distinguish **known / stale / missing / inferred** on every surface that reports data. Missing data is shown as a
  gap, never filled from a cached impression.

## 13. Secrets and Untrusted Input

- No secrets in code, logs, error messages, commits, or test fixtures. Mask on the way out.
- All external data -- API responses, files, third-party tool output, model output -- is untrusted **data**, never
  instructions or policy. Wrap it, escape it, validate it against a schema at the boundary.
- No `shell=True`; pass argument vectors. Normalize and validate every path against traversal before use.
- The `S` (bandit) rules are selected; a `# noqa: S...` requires a justification like any other suppression (section 17).
- Never send a secret, credential, or token into a span or a span attribute -- see section 44.

---

# Part III -- Style

Rules in this part describe how a line looks. Most are enforced by ruff, pyright, or a test in
`devkit_tests/conventions/`; the few marked `[unenforced]` are not, and must be applied deliberately.

## 14. Type Annotations

Use typing extensively. Type all variables, function parameters, and return values (`ANN`).

### `object`, not `Any`, for a value that will be inspected

They are opposites rather than degrees of the same thing. `object` says *nothing is known about this value yet*, so
the checker refuses every use of it until it is narrowed. `Any` says *stop checking*, and it spreads: everything
derived from an `Any` is an `Any`. pyright's strict mode reports an implicit unknown but permits an explicit `Any`,
so this is a hole opened deliberately, and nothing downstream will ever point back at it.

Untrusted input therefore arrives as `object` and is narrowed at the boundary (section 13). `configuration.py` reads every
TOML value as `object`, which is precisely what forces `_as_str` and its siblings to exist instead of the check being
remembered:

```python
# Good - the narrowing is a statement the reader can see, and the error names the key that failed (section 8).
def _as_str(value: object, key_path: str) -> str:
    if isinstance(value, str):
        return value

    raise _fail(key_path, expected="a string", value=value)


# Bad - nothing below this line is checked any more, and `value` is not the only casualty.
value: Final[Any] = values[key]
```

Reserve `Any` for a type the contract genuinely does not constrain: the `**attributes` tail of the tracing API (section 44),
or a payload handed to a serializer without being read. `[unenforced]` -- no check can tell an unconstrained contract
from an unnarrowed shortcut, and `ANN401` is not that check, because it also flags `**attributes: Any`. Twenty
suppressions of one rule is a configuration problem, which is why it is off rather than waived per site (section 17).

### Where the annotation goes

Annotate loop variables before the loop, once per scope: `[gated]`

```python
i: int
for i in range(10):
    process(i)

# No need to type it a second time.
for i in range(20):
    process(i)
```

Annotate `with` statements: `[gated]`

```python
from typing import IO

file: IO[str]
with open(...) as file:
    pass
```

A bare declaration belongs **immediately above the statement it annotates, inside the same block** -- never
hoisted out of an enclosing `try`, `if`, or `with`. An annotation parked in the outer block reads as if it
described that block, and the statement it actually belongs to is left looking unannotated. `[gated]`

```python
# Bad - hoisted out of the try; the annotation and its `with` are in different blocks.
file: IO[str]
try:
    with path.open(mode="wt") as file:
        ...

# Good - same block, directly above.
try:
    file: IO[str]
    with path.open(mode="wt") as file:
        ...
```

The same rule governs loop variables (section 14 above), pragma reasons (section 17), and comments (section 32): whatever
explains or types a statement sits directly on top of it, in its block.

## 15. Finality and Immutability

Two separate rules, often confused:

- **`@final` on a class** unless it is explicitly designed for inheritance. A class with no subclass is `@final`.
- **`Final[...]` on a name** that is never reassigned after initialization. This is the default for constants,
  injected dependencies, and instance attributes.

```python
from typing import ClassVar, Final, Self, final

__all__: Final[tuple[str, ...]] = ("Config",)

# Module-level constants.
MAX_RETRIES: Final[int] = 3
DEFAULT_TIMEOUT: Final[float] = 30.0


@final
class Config:
    __slots__: ClassVar[tuple[str, ...]] = ("__value",)

    def __init__(self: Self, /, value: int) -> None:
        # Never reassigned - Final.
        self.__value: Final[int] = value

    @property
    def value(self: Self, /) -> int:
        return self.__value
```

Prefer immutable containers for anything shared: `tuple` over `list`, `frozenset` over `set`, a frozen dataclass or a
`Mapping` over a mutable mapping.

## 16. Self Typing

Always type `self` and `cls` explicitly -- `Self` for `self`, `type[Self]` for `cls`. `[gated]`, because ruff's
`ANN101`/`ANN102` were removed and no linter flags a missing annotation here any more.

```python
@final
class Builder:
    __slots__: ClassVar[tuple[str, ...]] = ("__name",)

    @classmethod
    def create(cls: type[Self], /, name: str) -> Self:
        return cls(name)

    def __init__(self: Self, /, name: str) -> None:
        self.__name: str = name

    def with_name(self: Self, /, name: str) -> Self:
        self.__name = name
        return self
```

### Exception: properties inside a `Protocol`

Inside a `Protocol`, **methods** keep `self: Self, /`, but **properties take a bare `self`**. Annotating `Self` on a
protocol property resolves `Self` to the protocol itself, so pyright then demands a getter accepting the protocol as
its first argument -- while a property read on an instance is already bound and has type `() -> T`. The result is a
protocol no class can ever satisfy:

```python
Type "() -> Path" is not assignable to type "(self: Concrete, /) -> Path"
  Could not bind method "path" because "WithSelf" is not assignable to parameter "self"
```

```python
from pathlib import Path
from typing import Protocol, Self


class Catalog(Protocol):
    # Bare `self`: annotating it here makes the protocol unsatisfiable.
    @property
    def path(self, /) -> Path:
        raise NotImplementedError

    # A method is unaffected; the usual rule applies.
    def coverage(self: Self, key: str, /) -> int:
        raise NotImplementedError
```

## 17. Overrides, Ignores, and Suppressions

- Every method that overrides a base method carries `@override` (`reportImplicitOverride` is an error).
- Every instance attribute is initialized in `__init__` (`reportUninitializedInstanceVariable` is an error). No
  attribute appears for the first time in another method.
- Never a blanket suppression. Use `# type: ignore[code]` or `# pyright: ignore[rule]`, narrowed to the exact
  diagnostic. Stale ones are errors -- `reportUnnecessaryTypeIgnoreComment` for pyright, `warn_unused_ignores` for
  mypy -- so a suppression that stops being needed must be deleted.
- **One pragma per tool, and only that tool reads it.** `pyproject.toml` sets `enableTypeIgnoreComments = false`,
  because pyright otherwise honours `# type: ignore` *and discards the codes in the brackets*: measured on a line
  carrying four diagnostics, `# type: ignore[reportAttributeAccessIssue]` silenced all four while
  `# pyright: ignore[reportAttributeAccessIssue]` silenced exactly one. Bracketed codes are mypy's syntax, so under
  the default setting every mypy suppression is a blanket suppression for pyright -- the thing the rule above
  forbids. With it off, `# noqa` is ruff's, `# type:` is mypy's, `# pyright:` is pyright's, and none reaches past
  its own tool.
- **A line that both type checkers object to carries both, `# type:` first.** This is the one case where a second
  pragma may be chained, and the order is not a preference: mypy reads `# type: ignore` only as the *first* comment
  on the line, while pyright finds its own in either position.

  ```python
  _level=level.name.lower(),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
  ```

- **Every suppression carries its reason, on the line above it.** The pragma itself must stay inline, because that
  is how the tool reads it. The human explanation is a normal comment on the line above, following section 32. Never chain
  *prose* onto a pragma: the pragma is machine syntax, the reason is prose, and mixing them on one line makes both
  harder to read and pushes the line past the width limit. A suppression without a reason is indistinguishable from
  a rule nobody understood -- the staleness checks remove the ones that stopped being needed, but only the reason
  tells a reader whether the remaining ones are still true. `[gated]`

```python
# Good - pragma inline, reason above.
# logfire wants a level Literal, ours comes from `Level`.
_level=level.name.lower(),  # type: ignore[arg-type]

# Good - same shape for a noqa.
# logfire exposes no public API for setting a span's status from an exception.
logfire._internal.tracer.set_exception_status(  # noqa: SLF001
    cast("opentelemetry.sdk.trace.Span", span), exception_
)

# Bad - prose chained onto the pragma. A second *pragma* is the only thing that may go there.
_level=level.name.lower(),  # type: ignore[arg-type]  # logfire wants a level Literal.

# Bad - a bare suppression nobody can re-evaluate.
_level=level.name.lower(),  # type: ignore[arg-type]
```

The reason goes directly above the pragma's own line, not further up inside some other comment's block -- three lines
away is far enough that the next reader will not connect the two. On a decorated definition it therefore sits between
the last decorator and the `def`.

A whole family of identical suppressions is not a suppression problem, it is a configuration problem: change the
setting once (as `[tool.ruff.lint.pylint] max-args` does for section 4) instead of repeating the same exception at every
site.

```python
class Interface:
    __slots__: ClassVar[tuple[str, ...]] = ()

    def read(self: Self, /) -> str:
        raise NotImplementedError


@final
class FileSource(Interface):
    __slots__: ClassVar[tuple[str, ...]] = ("__path",)

    def __init__(self: Self, /, path: Path) -> None:
        self.__path: Final[Path] = path

    @override
    def read(self: Self, /) -> str:
        return self.__path.read_text()
```

## 18. Positional-Only and Keyword-Only Arguments

### Positional-only (`/`)

Use `/` to mark positional-only arguments in these cases, and only these:

- any method with a `Self` or `type[Self]` parameter -- `[gated]`;
- any function or method used as a callback (strict in positional args) -- `[unenforced]`;
- any parameter whose name could collide with a `**kwargs` key the caller supplies -- `[unenforced]`.

The third case is the one that does mechanical work. Without `/`, a caller passing a keyword that happens to match
a positional parameter gets `TypeError: got multiple values for argument`. That is why the `/` in `Tracer.log` sits
after `name` rather than after `self`: it keeps both `self` and `name` available as span attributes (section 44).

**Do not add `/` decoratively.** On a static or module-level function that takes no `**kwargs`, it only removes a
name-dependency no caller had -- it buys nothing, and a file where half such helpers carry it and half do not is
worse than either convention applied consistently. Half `[gated]`: the check reads a callback off its name, since
section 23 spells one `on_...`, and reports a **module-level** function with a `/`, no `**kwargs`, and no `on_` prefix. A
static method in the same shape is review's, because the receiver check skips static methods entirely.

```python
@final
class User:
    __slots__: ClassVar[tuple[str, ...]] = ("__email", "__name")

    # A method: `/` after the receiver.
    def __init__(self: Self, /, name: str, email: str) -> None:
        self.__name: str = name
        self.__email: Final[str] = email


# A callback: `/` because whoever holds it calls it positionally.
def on_event(event: Event, /) -> None:
    process(event)


# Neither: a module-level helper with no `**kwargs` gains nothing from a marker.
def describe(event: Event) -> str:
    return str(event)
```

### Keyword-only (`*`)

Use `*` to mark keyword-only arguments in these cases:

- all optional arguments, even with defaults;
- all boolean arguments, even when not optional (enforced for booleans by `FBT`), except in callbacks;
- objects that are injected dependencies used via composition (models, clients, adapters).

```python
@final
class Service:
    __slots__: ClassVar[tuple[str, ...]] = ("__state",)

    def __init__(self: Self, /) -> None:
        self.__state: str = "idle"

    def process(self: Self, /, data: str, *, should_retry: bool = False, timeout: int | None = None) -> None:
        pass

    # Boolean is always keyword-only.
    def configure(self: Self, /, *, is_enabled: bool, max_retries: int = 3) -> None:
        pass


# Exception: callbacks may take positional boolean args.
def callback(event: Event, should_propagate: bool, /) -> None:
    pass
```

## 19. Class Variables

Use `ClassVar` for every class-level variable.

```python
@final
class Service:
    __slots__: ClassVar[tuple[str, ...]] = ()
    instance_count: ClassVar[int] = 0

    @classmethod
    def create(cls: type[Self], /) -> Self:
        # Mutate the class attribute through cls, not through an instance.
        cls.instance_count += 1
        return cls()
```

Never mutate a `ClassVar` through `self`: `self.instance_count += 1` reads the class attribute and then *assigns an
instance attribute* -- which raises `AttributeError` under `__slots__`, and silently shadows the class counter without
it. Mutate via `cls` in a `classmethod`.

## 20. Slots

Always define `__slots__`, typed as a `ClassVar[tuple[str, ...]]`, including an empty one. Skip it for pydantic models
and dataclasses that manage their own layout.

```python
@final
class User:
    __slots__: ClassVar[tuple[str, ...]] = ("__email", "__id", "__name")

    def __init__(self: Self, /, name: str, email: str) -> None:
        self.__name: Final[str] = name
        self.__email: Final[str] = email
        self.__id: Final[int] = 0


# No need here.
@final
class SomeEntity(Entity):
    pass
```

Private slot names are written as declared (`"__name"`); Python mangles the slot together with the attribute.

## 21. Module Exports

Always define `__all__`, typed. Entries are auto-sorted by `RUF022` -- do not reorder manually.

```python
from typing import Final

__all__: Final[tuple[str, ...]] = ("User", "UserRepository", "UserService")
```

**`__all__` is what crosses the file boundary.** Every symbol read anywhere outside its own file is in it -- a sibling
module, an entry point, a script, a test. Every symbol read only inside its own file is `_name` and stays out (section 24).
There is no third category, and the rule is mechanical: *if it crosses, declare it; if it does not, underscore it.*
A public name deliberately absent from `__all__` is a symbol nobody can classify.

**A test is a consumer like any other.** Needing a symbol in a test *is* a reason to export it. `devkit_tests` is not
privileged, exempted, or reaching through anything -- it imports declared names by their declared spelling, which is
why nothing in it needs `SLF001` or a `reportPrivateUsage` waiver. The rule runs in both directions: a test module
declares what it offers and privatizes what it does not, exactly like the code it exercises.

Two carve-outs, both mechanical rather than judgement calls:

- **Names pytest resolves are public by pytest's requirement, and stay out of `__all__`.** A `test_*` function and a
  `@pytest.fixture` are found by the collector matching a bare name, not by any module importing them, so they cannot
  take a leading underscore and there is nothing for `__all__` to declare. They go in only when another module also
  imports them -- which is the ordinary rule, applied unchanged. `devkit_tests/data/conftest.py` is the case that
  shows the difference: its fixtures that siblings import by name are exported, and the two they only receive by
  injection are not.
- **A package marker `__init__.py` with no statements needs no `__all__`.** It declares nothing, so it has nothing to
  declare. An `__init__.py` that re-exports (section 22) is a normal module and declares its `__all__` like any other.

Both this rule and section 24's are gated by `devkit_tests/conventions/`, which walks **both** packages and `scripts/`, and
fails on a module that declares no `__all__` or that carries a module-level `__name` (section 7).

**`__all__` is not a compatibility contract.** Publicness is relative to the enclosing unit (section 24): `Metrics.iterations`
is public on its class without being a promise to the world, and `binance.parse_klines` is public on its module in
exactly the same sense. What can actually break someone is not a Python name at all -- it is the argparse flags, the
`kwuant.toml` schema, the emitted report JSON, and the on-disk catalog layout. Those are the surfaces where a change
is invisible to the type checker because the other side is not in this repository; section 9.6 governs the stored ones and
section 42 governs narrowing them. Renaming a module symbol is caught by pyright at every call site before it is committed,
which is precisely why it needs no ceremony here.

## 22. Namespaced Imports

Always use namespaced imports, with the exceptions below. Relative imports are banned (`flake8-tidy-imports`,
`ban-relative-imports = "all"`).

```python
# Good.
import package.subpackage.module as module

# Bad.
from package.subpackage.module import SomeClass

# Exception: typing is always imported directly.
from typing import ClassVar, Final

# Exception: types from the common module are always imported directly.
from kwuant.common.types import HTTPURL, Entity

# Exception: standard library may be imported directly.
from abc import abstractmethod
from collections.abc import Iterator
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

# Exception: when a module extends a library (e.g. tracing.py extends logfire), direct imports
# are acceptable - the module is treated as the same context as the library. Same when the
# library already uses fully-qualified names (e.g. LogfireSpan), where a namespace is redundant.
```

### Imports within the current package

Import the submodule by name so the call site reads with its namespace:

```python
# You are in: package.subpackage_a.module
# You want:   package.subpackage_b.another

# Good - call sites read `another.thing`.
from package.subpackage_b import another

# Good - aliased, when the bare name would collide (see below).
from package.subpackage_b import another as subpackage_b_another
```

**Alias when the module name would be shadowed by a parameter, local, or field in the importing module.** A function
taking `catalog: Catalog` shadows a module named `catalog` for its whole scope, and the usual repair -- a module-level
`type` alias for each name needed from it -- is a second mechanism for a problem the import can solve outright (section 3):

```python
# Good - the parameter cannot shadow the module.
from kwuant.data import binance, catalog as data_catalog


def ingest(instrument_ids: Sequence[InstrumentId], *, catalog: data_catalog.Catalog) -> Report: ...
```

Note this example carries no positional-only `/`: it is a module-level function with no `**kwargs`, so section 18 says the
marker would buy nothing.

Aliasing costs the reader nothing here: `data_catalog` still names the package it came from, so which side of a
boundary a symbol belongs to stays visible.

The same repair applies when a **package façade** is the shadowed name: `kwuant.backtest.session` binds a local
`data`, so it reaches the catalog as `from kwuant.data import catalog as data_catalog` rather than through
`kwuant.data`. Prefer the façade where the name is free; where it is not, the aliased submodule import is the answer,
not a renamed local.

:::note
Reaching a submodule through its package object -- `import package.sub.another` plus `from package import sub`, then
`sub.another.thing()` -- does not type-check. The condition is exact:

> `package.submodule.X` resolves if and only if `package/__init__.py` itself imports `submodule`.

Emptiness has nothing to do with it: a non-empty `__init__.py` that re-exports other names still fails. Measured
against this repository's own pyright config, one such call site produces five errors:

```
error: Import "kw.data.binance" is not accessed                      (reportUnusedImport)
error: Type of "binance" is unknown                                  (reportUnknownMemberType)
error: Type of "fetch" is unknown                                    (reportUnknownMemberType)
error: Argument type is unknown                                      (reportUnknownArgumentType)
error: "binance" is not a known attribute of module "kw.data"        (reportAttributeAccessIssue)
```

plus `F401` from ruff. `reportAttributeAccessIssue` is the same check that catches real typos (section 17), so the form is
banned rather than suppressed. Import the submodule directly, or put it in `__init__.py` and accept what that costs.
:::

### What goes in a package's `__init__.py`

Decided per package by what the submodules *are*, not by how many there are.

1. **One concept split across files** -- re-export the symbols, so the split stays an implementation detail.
   `kwuant.market` is `splits` + `universe` + `venue`: one answer to "what is traded, where, and over which period",
   read as `market.Split`, `market.VENUE`, `market.VenueProfile`. Same for `backtest.run_backtest`. Lift a symbol
   here whenever the submodule name would otherwise repeat in the call (`catalog.Catalog` -> `data.Catalog`, section 23).
2. **A cohesive sub-namespace whose bare names would read wrong** -- import the *module*, not its symbols, so the
   namespace survives: `from kwuant.backtest import metrics` gives `backtest.metrics.SHARPE`, where a lifted
   `backtest.SHARPE` would not say it is a metric.
3. **Isolated siblings** -- nothing at all. `kwuant.data`'s venue adapters (`binance`, and whatever follows) are
   separate namespaces carrying their own dependencies, so importing the package must not drag every one of them in.
   A consumer reaches one with `from kwuant.data import binance`.

Cases 2 and 3 are mutually exclusive: putting a submodule in `__init__.py` is exactly what makes
`package.submodule.X` resolve, and exactly what makes it eager. Choose the call site or the lazy import; there is no
arrangement that gives both.

Whatever the case, nothing *inside* the package imports through its own `__init__.py` -- submodules import each other
directly, so `__init__` stays a leaf of the import graph and cannot close a cycle.

## 23. Naming

Before choosing any name, check the codebase for an established pattern and follow it. Use well-known design-pattern
names (`Registry`, `Bus`, `Field`, `Pipeline`, `Protocol`) when applicable and no local pattern exists.

Mechanical conventions are enforced by `N` (pep8-naming): modules and variables `snake_case`, classes `PascalCase`,
constants `UPPER_SNAKE_CASE`. Below, the boolean prefixes, the callback spelling, and namespace-aware naming are
`[gated]`; the rest -- parts of speech, `-er` suffixes, postfixes -- is `[unenforced]`, because reading a name for what
it means is not something a parser does.

### Parts of speech

- **Classes** -- nouns (`Registry`, `Bus`, `Field`, `Pipeline`, `Document`).
- **Methods/functions** -- verbs (`create`, `validate`, `drain`, `resolve`, `process`).
- **Properties/attributes** -- nouns (`name`, `slug`, `connection`, `state`).

### Avoid `-er` suffixes

Prefer a precise noun describing what the thing *is* over an agent noun describing what it *does*.

```python
# Bad - vague `-er` names.
class EventDispatcher: ...
class DataValidator: ...
class TaskProcessor: ...
class EntityManager: ...

# Good - precise nouns.
class Bus: ...          # Not EventDispatcher - it *is* a bus.
class Validation: ...   # Not DataValidator - it *is* a validation.
class Pipeline: ...     # Not TaskProcessor - it *is* a pipeline.
class Registry: ...     # Not EntityManager - it *is* a registry.
```

Not every `-er` name is wrong -- `Tracer`, `Builder` are fine when nothing better exists. The rule is: if a shorter,
more descriptive noun works, prefer it.

### Booleans

Every boolean name carries a prefix that makes the yes/no meaning unambiguous: `is_`, `has_`, `use_`, `should_`,
`can_`, `allow_`. `[gated]` with no exempted names -- a reserved keyword on a documented API is still a name someone
has to read, so section 44's `should_include_return_` and `should_reset_context_` carry the prefix like any other boolean.
The gate reads the annotation through `Final`, `ClassVar` and any namespace, and takes a bare `= True` as saying the
same thing -- `ANN` does not reach an assignment, so a boolean could otherwise dodge the rule by dropping its type.
What it still cannot see is a boolean whose type only a call reveals.

```python
# Bad.
enabled: bool = True
retry: bool = False
to_many: bool

# Good.
is_enabled: bool = True
should_retry: bool = False
is_to_many: bool
```

### Namespace-aware naming

Names are read with their module namespace. Do not repeat the module name in the class name.

```python
# Bad - redundant as schemas.DataEntitySchema.
class DataEntitySchema: ...

# Good - reads as schemas.DataEntity.
class DataEntity: ...

# Bad - reads as events.Event.
class Event: ...

# Good - the base interface, read as events.Interface.
class Interface: ...
```

So `instances.DataEntity` rather than `DataEntityInstance`, and `tracing.Context` rather than `TracingContext`.

The namespace a name is read through is the one it is reached by, which is not always its own module: a symbol lifted
into a package `__init__` is read as `data.Catalog`, and that is the repair section 22 prescribes where the submodule name
would otherwise repeat.

For base and abstract classes prefer `Interface` over `Base`; `Interface` states the contract. `Base` is acceptable but
weaker.

Types from shared modules (`common.types`) are the exception -- they are imported directly because they are
self-descriptive and a namespace adds nothing:

```python
from kwuant.common.types import HTTPURL, Dataclass, Entity

url: HTTPURL = ...
```

### Postfixes and prefixes

Use a postfix only when no submodule provides the namespace. If a submodule exists, the namespace replaces the
postfix.

```python
# Events defined inside an entity module - the postfix distinguishes them.
# Read as: schemas.DataEntityCreatedEvent.
class DataEntityCreatedEvent: ...
class DataEntityUpdatedEvent: ...

# Events in a dedicated entities.events submodule - no postfix needed.
# Read as: entities.events.DataEntityCreated.
class DataEntityCreated: ...
class DataEntityUpdated: ...
```

### Callbacks

Callback functions and methods use the `on_` prefix. A callback accepted as a parameter also takes the `_callback`
postfix, to distinguish it from a regular argument.

```python
@final
class Bus:
    __slots__: ClassVar[tuple[str, ...]] = ("__on_event_callback",)

    # Good - parameter has the _callback postfix.
    def __init__(self: Self, /, on_event_callback: Callable[[str], None]) -> None:
        self.__on_event_callback: Final[Callable[[str], None]] = on_event_callback

    # Good - the method is a callback, so it uses the on_ prefix.
    def on_event(self: Self, /, event: str) -> None:
        self.__on_event_callback(event)


# Good - standalone callback.
def on_message(message: str, /) -> None:
    process(message)


# Bad - callback parameter without the _callback postfix.
def __init__(self: Self, /, on_event: Callable[[str], None]) -> None: ...

# Bad - callback parameter without the on_ prefix.
def __init__(self: Self, /, event_callback: Callable[[str], None]) -> None: ...
```

## 24. Privacy

**Publicness is relative to the enclosing unit.** A public field is reachable from outside its *class*; an exported
symbol is reachable from outside its *file*. Neither is a statement about the world. The same question -- does anything
outside this unit read it? -- is asked at both scopes, and the answer is spelled differently at each.

### Class scope -- three tiers

Instance variables are private by default. `[unenforced]` -- the module-scope half below is `[gated]`.

- **Private** (`__variable`) -- the default.
- **Protected** (`_variable`) -- only for inheritance.
- **Public** (`variable`) -- only when direct external access is explicitly required.

```python
@final
class User:
    __slots__: ClassVar[tuple[str, ...]] = ("__email", "__name")

    def __init__(self: Self, /, name: str, email: str) -> None:
        self.__name: Final[str] = name
        self.__email: Final[str] = email

    # Read from outside, so it is reachable - through a property, not by making the field public.
    @property
    def name(self: Self, /) -> str:
        return self.__name


# Base class for inheritance - no @final.
class Interface:
    __slots__: ClassVar[tuple[str, ...]] = ("__state", "_connection")

    def __init__(self: Self, /) -> None:
        # Protected - a subclass reads this.
        self._connection: str = "active"
        # Private - nothing outside this class does.
        self.__state: int = 0


@final
class Session(Interface):
    __slots__: ClassVar[tuple[str, ...]] = ("__cache",)

    def __init__(self: Self, /) -> None:
        super().__init__()
        self.__cache: dict[str, str] = {}
        if self._connection == "active":
            self.__cache.clear()
```

Reaching into another object's private or protected members is banned (`SLF`), with no exemption for tests. A test
imports declared names by their declared spelling like every other consumer (section 21).

### Module scope -- two tiers

- **Public** -- in `__all__` (section 21). Anything read outside this file, tests included.
- **Private** (`_name`) -- read only inside this file.

There is no third tier, because the middle one exists only to serve inheritance and a module is never inherited from.
`_protected` has no module-scope meaning; do not invent one.

**Never `__name` at module scope.** It is not the module-level spelling of class privacy -- it is a different mechanism
that happens to share the notation, and at module scope it buys nothing over `_name`: both are hidden from
`import *`, and both are `reportPrivateUsage` to pyright. What it adds is a latent `NameError`. Mangling applies
inside a **class body**, so the moment a class in the same file references the name, it compiles to a symbol nobody
typed:

```python
__WINDOWS = {"a": 1}


class Window:
    # NameError: name '_Window__WINDOWS' is not defined.
    def lookup(self):
        return __WINDOWS["a"]


# Works. The same expression, outside a class body.
def lookup():
    return __WINDOWS["a"]
```

Nothing in ruff or pyright reports this, so a test does: `conventions/test_privacy.py` parses every module and fails
on any module-level name starting with `__` other than `__all__` (section 7).

## 25. Direct Returns

Never assign to a variable only to return it on the next line (`RET504`). One exception: with `await`, assigning first
avoids unreadable nesting.

```python
# Good - with await.
response = await agent.run(request)
return response.answer

# Bad - unreadable.
return (await agent.run(request)).answer

# Good - synchronous.
return compute().answer
```

## 26. Exception Message Variables

Name the variable `message` (never `msg`), annotate it, and end the sentence with a period. Passing a literal straight
to an exception constructor is banned (`EM101`/`EM102`).

For a single raise, use `Final[str]`. When a function has several raises reusing the variable, declare `str` on the
first assignment and reuse it without re-declaring.

```python
from typing import Final

# Bad - short name, no annotation, no period.
msg = f"Entity with slug {slug!r} not found"
raise ValueError(msg)

# Good - single raise.
message: Final[str] = f"Entity with slug {slug!r} not found."
raise ValueError(message)


# Good - multiple raises reusing the variable.
def validate(slug: str) -> None:
    if slug in ("doc", "quote", "source"):
        message: str = f"Slug {slug!r} is reserved."
        raise ValueError(message)

    if slug in existing_slugs:
        message = f"Entity with slug {slug!r} already exists."
        raise ValueError(message)
```

## 27. Exception Handling

Do not catch an exception only to re-raise it unchanged.

```python
# Bad - catching just to re-raise.
try:
    do_something()

except SpecificError:
    raise

except Exception as exception:
    handle(exception)

# Good - check and re-raise inside the broader handler.
try:
    do_something()

except Exception as exception:
    if isinstance(exception, SpecificError):
        raise

    handle(exception)

# Also good - do not catch it at all if it should propagate.
try:
    do_something()

except Exception as exception:
    handle(exception)
```

Use `contextlib.suppress` rather than `try/except/pass` when ignoring is genuinely correct -- and section 8 applies: it rarely
is.

## 28. Blank Lines on Indentation Changes

Add a blank line whenever the indentation level decreases -- leaving any indented block, including between an `if` body
and its `else`, and between a `try` body and its `except`. `[gated]` -- no formatter or linter checks this, so a test
does.

```python
# Bad - the eye reads `next_statement()` as the last line of the branch.
if condition:
    do_something()
next_statement()

# Good.
if condition:
    do_something()

next_statement()

# Good - the same before `else`, which is the one that looks wrong until you have seen it.
if condition:
    do_something()

else:
    do_other_thing()

# Good - and before `except`, and after the nested `if` inside the handler.
try:
    do_something()

except Exception as exception:
    if isinstance(exception, SpecificError):
        raise

    handle(exception)
```

## 29. Early Return to Reduce Nesting

Prefer early `return`/`continue`/`break` with a negated condition over nested `if` blocks.

```python
# Bad - unnecessary nesting.
def process(self: Self, /, value: Value | None) -> None:
    if value is not None:
        validate(value)
        store(value)
        notify(value)

# Good - early return.
def process(self: Self, /, value: Value | None) -> None:
    if value is None:
        return

    validate(value)
    store(value)
    notify(value)
```

## 30. Explicit Checks

Never rely on implicit truthiness. Check explicitly -- `is None`, `is not None`, `len(...) == 0`, `!= 0`. Implicit
checks conflate distinct states: `0`, `0.0`, `""`, and empty collections are all falsy.

```python
# Bad - `0` and `None` are the same answer here, and they are not the same state.
if count:
    do_something()

if on_event_callback:
    on_event_callback()

# Good.
if count != 0:
    do_something()

if on_event_callback is not None:
    on_event_callback()
```

Ask the question the parameter type can answer. section 35 requires abstract argument types, and `Iterable` has no `__len__`:

```python
from collections.abc import Collection, Iterable
from typing import Final


# Good - Collection is Sized, so len() is valid.
def process(items: Collection[str], /) -> None:
    if len(items) == 0:
        return

    ...


# Good - an Iterable must be materialized before asking about emptiness.
def consume(items: Iterable[str], /) -> None:
    materialized: Final[tuple[str, ...]] = tuple(items)
    if len(materialized) == 0:
        return

    ...
```

## 31. Docstrings

Do not add docstrings unless explicitly asked. Code is self-documenting through clear naming. (`D1xx` -- missing
docstrings -- are disabled; the remaining `D` rules only format docstrings that exist.)

```python
# Bad - unsolicited docstring.
def drain(self: Self, /) -> tuple[Event, ...]:
    """Return all buffered events and reset the buffer."""
    ...

# Good.
def drain(self: Self, /) -> tuple[Event, ...]:
    ...
```

## 32. Comments

Comments carry **rationale**, not narration. A comment restating what the line does is noise; a comment stating why
this approach was chosen, which alternative was rejected, or what non-obvious constraint applies is the most valuable
line in the file. See section 43.

Formatting: comments sit on the line above what they describe, never inline, and end with a period. `[gated]` -- the
period is asked of the last line of a block, since a comment wrapped over four lines is one sentence.

**The only inline comments permitted are tool pragmas** -- `# noqa: CODE`, `# type: ignore[code]`,
`# pyright: ignore[rule]` -- because the tool reads them positionally and they have nowhere else to go. Everything a
human wrote is a comment on its own line, including the reason for the pragma (section 17).

```python
# Bad - inline.
a = 10  # Some comment

# Bad - no period, and narrates the obvious.
# increment the counter
counter += 1

# Good - explains why.
# Provider rejects batches above 500, so chunk before dispatch.
for chunk in chunked(items, 500):
    dispatch(chunk)

# Good - the only inline exception: a pragma, with its prose above it.
# The upstream stub types this as str; the runtime value is a Path.
resolved = library.resolve(path)  # type: ignore[assignment]
```

`TODO` is the only permitted task tag, and it states what and why (`TD`).

**A workaround for an upstream defect carries a `TODO` naming the condition that retires it.** A comment explaining
why the workaround exists tells a reader why the code is shaped that way; it does not tell them the shape is
temporary, so the workaround outlives the bug and nobody dares touch it. State the upstream condition explicitly --
"remove once the stub matches the runtime", "remove once the adapter re-exports the submodule" -- so the next person
upgrading a dependency knows what to re-check.

```python
# `nautilus_trader.adapters` does not re-export `binance` at runtime even though its stub declares it, so the
# submodule has to be imported outright.
# TODO: Drop the direct submodule import once the stub and the runtime agree; the mismatch is an upstream bug.
import nautilus_trader.adapters.binance as binance_adapter
```

This applies to **runtime** workarounds. A `# type: ignore[code]` or `# pyright: ignore[rule]` needs no `TODO`:
`reportUnnecessaryTypeIgnoreComment` is an error (section 17), so a suppression that stops being needed fails the build on
its own. Mechanical expiry beats a task tag; use the tag only where nothing mechanical will notice.

## 33. Ordering

All definitions -- classes, functions, constants, enum members -- are sorted. Use a logical order when one exists (by
entity then action, by lifecycle stage, by severity); otherwise sort alphabetically. Never leave definitions in
insertion order. `[unenforced]` -- the gate below orders definitions *by kind and visibility* and tie-breaks equal
ranks on original position, so it says nothing about how two classes, two constants, or two enum members sort against
each other. That half is review's.

`__all__` (`RUF022`), `__slots__` (`RUF023`), and imports (`I001`) are sorted by ruff -- do not reorder them by hand.

```python
from enum import StrEnum, unique
from typing import final


# Good - grouped by entity, then by action.
class OrderCreatedEvent: ...
class OrderUpdatedEvent: ...
class OrderDeletedEvent: ...
class ProductCreatedEvent: ...
class ProductUpdatedEvent: ...
class ProductDeletedEvent: ...


# Good - alphabetical when no logical grouping applies.
class AudioProcessor: ...
class CacheManager: ...
class EmailValidator: ...
class RateLimiter: ...


# Good - enum members by severity (logical), not alphabetically.
@final
@unique
# Between the last decorator and the definition, per section 17: pyright does not see that `StrEnum`
# initializes `_value_` for its members, so a `@final` StrEnum reads to it as a final class with an
# uninitialized inherited attribute.
class LogLevel(StrEnum):  # pyright: ignore[reportUninitializedInstanceVariable]
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
```

The suppression is required, not optional: `reportUninitializedInstanceVariable` is an error in this repo (section 17), so a
`@final` `StrEnum` or `IntEnum` does not lint without it. `(str, Enum)` avoids the diagnostic, but its members render
as `LogLevel.DEBUG` under `str()` and f-strings where a `StrEnum` renders as `debug` -- a silent difference wherever a
member reaches a filename, a CLI choice, or a log line. Prefer `StrEnum` with the suppression; per section 17 the ignore
expires by itself once pyright fixes the diagnostic.

### Module-level definitions

A module is ordered by the same shape as a class: by kind, then by visibility within the kind, public before private.

1. Public type aliases
2. Private type aliases
3. Public constants
4. Private constants
5. Public sync functions
6. Public async functions
7. Private sync functions
8. Private async functions
9. Public classes
10. Private classes

**This order unless the structure requires otherwise.** A module body executes top to bottom, so a definition whose
*value* is computed at import time must follow whatever it reads. Nothing else may reorder -- a preference, a reading
flow, or a diff that would be smaller is not a reason.

Three things run at import time and therefore create a real dependency:

- **A constant's value.** `market/splits.py` builds `_WINDOWS` out of `Split` and `Window`, so that one constant sits
  below both classes while every other constant in the file stays at the top.
- **A decorator, and its defaults.** Ordinary annotations are lazy (PEP 649) and a function body does not run, so a
  helper may sit below its caller and a signature may name a class defined further down.
- **A decorator that introspects the signature.** This one is easy to miss and fails at import, not at type-check
  time: `include_args_` on the tracing decorators (section 44.2) calls `inspect.signature`, which forces the annotations to
  evaluate at decoration time. `@dataclasses.dataclass` does the same to its field annotations. A decorated
  definition therefore depends on every locally-defined name it annotates.

```python
# Good - the ordinary case: annotations are lazy, so `parse` may name a class defined below it.
def parse(payload: bytes) -> Record: ...


@final
class Record: ...


# Good - forced: the value is built now, so it follows what it reads.
@final
class Split(StrEnum): ...


_WINDOWS: Final[Mapping[Split, Window]] = {Split.TRAIN: ...}


# Bad - the decorator calls `inspect.signature`, so `Source` must already exist. NameError at import.
@_TRACER.with_span_sync(tracing.Level.INFO, include_args_={"split"})
def ingest(*, source: Source) -> Report: ...


class Source(Protocol): ...
```

`[gated]`: `conventions/test_ordering.py` recomputes the order this rule produces -- lowest rank first, original
position as the tie-break, never before something a definition needs -- and fails on any module that does not already
match it (section 7). A structurally forced deviation passes because the check models the same dependency; an unforced one
does not.

### Class-level attributes

Magic attributes first, then public, then private. `[gated]` by the same check, one scope down -- with the same
allowance for what the body forces, since a member whose name shadows a module-level one is placed by what that
shadowing permits rather than by its rank.

```python
@final
class Service:
    # 1. Magic.
    __slots__: ClassVar[tuple[str, ...]] = ("__name", "__state")

    # 2. Public.
    name: Field[Self, str] = Field()

    # 3. Private.
    __TRACER: ClassVar[tracing.Tracer] = tracing.Tracer(__name__)
```

### Methods

1. Factory methods (public, then protected, then private), then `__init__`.
2. Public properties -- abstract read-only, concrete read-only, abstract read-write, concrete read-write.
3. Public sync methods -- `@staticmethod`/`@classmethod` first, then sync magic methods, then instance methods; abstract
   before concrete within each subgroup.
4. Public async methods -- same subgroup order.
5. Protected members (`_`) -- properties, then sync, then async; abstract before concrete.
6. Private members (`__`) -- properties, then sync, then async.
7. `__del__` -- always last.

```python
@final
class Service:
    __slots__: ClassVar[tuple[str, ...]] = ("__name", "__state")

    # 1. Factory, then __init__.
    @classmethod
    def create(cls: type[Self], /) -> Self:
        return cls(name="default")

    def __init__(self: Self, /, name: str) -> None:
        self.__name: Final[str] = name
        self.__state: int = 0

    # 2. Public properties.
    @property
    def name(self: Self, /) -> str:
        return self.__name

    # 3. Public sync.
    @staticmethod
    def validate(value: str, /) -> bool:
        return len(value) > 0

    def __sub__(self: Self, /, other: Self) -> int:
        return self.__state - other.__state

    def process(self: Self, /) -> str:
        return self.__name.upper()

    # 4. Public async.
    async def run(self: Self, /) -> None:
        pass

    # 5. Protected.
    @property
    def _state(self: Self, /) -> int:
        return self.__state

    def _reset(self: Self, /) -> None:
        self.__state = 0

    async def _fetch(self: Self, /) -> None:
        pass

    # 6. Private.
    def __compute(self: Self, /) -> int:
        return self.__state * 2

    async def __load(self: Self, /) -> None:
        pass

    # 7. Always last.
    def __del__(self: Self, /) -> None:
        pass
```

### Attribute assignment

Assignments in `__init__` (and any method) follow the parameter order. `[gated]` for what the check can attribute
to a parameter: an assignment made directly in the method body, whose value is the parameter name itself. One made
inside an `if`, or one that transforms the value first, is review's -- the order of the first is forced by its
branch, and the second cannot be traced to a single parameter.

```python
# Good.
def __init__(self: Self, /, name: str, email: str, age: int) -> None:
    self.__name: Final[str] = name
    self.__email: Final[str] = email
    self.__age: Final[int] = age

# Bad - assignment order differs from parameter order.
def __init__(self: Self, /, name: str, email: str, age: int) -> None:
    self.__age: Final[int] = age
    self.__name: Final[str] = name
    self.__email: Final[str] = email
```

## 34. Static Methods vs Class Methods

Use `@staticmethod` only when the method does not reference the class at all. If it needs another class member, it is a
`@classmethod`. Referencing the class by name inside a static method is a smell -- it breaks on rename and bypasses
method resolution.

```python
@final
class Processor:
    __slots__: ClassVar[tuple[str, ...]] = ()

    # Bad - a static method reaching the class by name: breaks on rename, bypasses resolution.
    @staticmethod
    def process(value: int) -> int:
        return Processor.__transform(value)

    # Good - a classmethod, because it needs a class member.
    @classmethod
    def process(cls: type[Self], /, value: int) -> int:
        return cls.__transform(value)

    # Good - genuinely standalone.
    @staticmethod
    def validate(value: int, /) -> bool:
        return value > 0

    @classmethod
    def __transform(cls: type[Self], /, value: int) -> int:
        return value * 2
```

## 35. Return Types vs Argument Types

Return exact concrete types; accept abstract ones. This keeps arguments immutable from the callee's side and gives
callers flexibility -- it is LSP and ISP applied to signatures.

- **Return** -- `dict`, `list`, `tuple`, `set`, `frozenset`.
- **Accept** -- `Mapping`, `Sequence`, `Collection`, `Iterable`, `AbstractSet`.

```python
# Good - concrete return, abstract arguments.
def merge_configs(base: Mapping[str, int], override: Mapping[str, int]) -> dict[str, int]:
    merged: dict[str, int] = dict(base)
    merged.update(override)
    return merged


# Bad - the abstract return hides what the caller is actually handed.
def get_config() -> Mapping[str, int]:
    return {"key": 1}


# Bad - the concrete argument refuses a tuple the body would have been happy with.
def process_list(items: list[str]) -> list[str]:
    return items
```

## 36. Overload Declarations

Overload stubs use `raise NotImplementedError` as the body, never `...`.

```python
@overload
def create(self: Self, /, override: DataEntityOverride) -> DataEntity:
    raise NotImplementedError


@overload
def create(self: Self, /, override: RelationEntityOverride) -> RelationEntity:
    raise NotImplementedError


def create(self: Self, /, override: DataEntityOverride | RelationEntityOverride) -> DataEntity | RelationEntity:
    ...
```

## 37. Use `__class__`, Not `type()`

Always use `obj.__class__` to get an object's type. Applies to `self`, parameters, and any other object. `[gated]`

```python
# Bad.
return type(self).__qualname__
return type(other).__name__

# Good.
return self.__class__.__qualname__
return other.__class__.__name__
```

## 38. Prefer `.pop()` and `.remove()` Over `del`

Method calls are more explicit than the `del` statement. `[gated]`

```python
# Bad.
del items[key]
del items[0]

# Good.
items.pop(key)
items.pop(0)
items.remove(value)
```

## 39. Formatting

Formatting is owned by ruff (`make format`); do not argue with it in review.

- Line width 120 (`line-length`). Do not break a line that fits.
- LF line endings; no magic trailing comma.
- When splitting a string across lines by implicit concatenation, the trailing space goes at the **end** of the current
  line, never at the start of the next one. `[gated]`

```python
# Good.
description = (
    "The therapeutic modality describing what the drug is (e.g. small molecule, mAb, ADC, cell therapy, gene "
    "therapy) and any modality-defining subtype."
)

# Bad - leading space on the continuation line.
description = (
    "The therapeutic modality describing what the drug is (e.g. small molecule, mAb, ADC, cell therapy, gene"
    " therapy) and any modality-defining subtype."
)
```

---

# Part IV -- Practice

## 40. Testing

- **Name the scenario.** For every changed behaviour, state in plain words the scenario it introduces, and make sure a
  test asserts on *that* scenario. "Tests exist for the module" is not "tests cover this behaviour." Adjacent tests in
  the same module count as coverage; a second, distinct failure mode needs its own test.
- **Adversarial paths are mandatory** for parsers, state machines, reconciliation, and finalization logic: malformed
  and empty input, partial failure, premature or false completion, restart and replay durability. A state-machine
  change that only passes the happy-path test is incomplete.
- **New guard or validation?** Before committing it, name three concrete ways it could break: wrong bounds, legitimate
  input it silently rejects, environment-specific edges. If you cannot name three, think longer.
- **Parallel-safe by default.** Use `tmp_path`, not fixed paths; `monkeypatch.setenv`/`setattr`, not bare
  `os.environ[...]` or attribute assignment; no execution-order assumptions; reset any mutated module-level state. A
  test that binds a real port, spawns a real process, or mutates a global registry is marked `serial`.
- **No network in unit tests.** Slow, networked, and environment-dependent tests live behind registered markers,
  excluded from the default local run.
- Tests are deterministic: fixed seeds, injected clocks (section 11).
- Record the exact command and its outcome. "Tests pass" without a command is not evidence.

## 41. Change Propagation

When changing anything shared -- a signature, a data format, a constant, a schema, a route, a config key:

1. find **all** readers and writers first, by search and by LSP references, never from memory;
2. update code, tests, and docs in the **same** change;
3. when adding or renaming a public symbol, verify the chosen name against real call sites and any declared interface.

A change that updates a format on the write side and not the read side is not a partial change; it is a bug that passes
review.

## 42. Verification and Definition of Done

- Verify against the **most authoritative** surface, not the nearest proxy -- the running process, the current file, the
  actual output; not a repo copy, a cached config, or remembered state.
- **Probe the deliverable the way its consumer invokes it**, not by replaying the steps that produced it.
- Exercise every input the task provided. A provided input never fed through the code is an untested branch.
- Re-read the original requirement and check each explicit item literally, on the surface it names.
- **Capability regression is a named defect class.** A path, flag, mode, or input that worked before must not silently
  start failing or become gated more tightly. If narrowing is intentional, say so explicitly in the change
  description -- an undisclosed narrowing is the failure this rule names. The surfaces this bites on are the ones no
  type checker can see across: the argparse flags, the `kwuant.toml` keys, the emitted report JSON, and the on-disk
  catalog layout (section 21, and section 9.6 for the stored ones).
- `make format lint test` passes before anything is called done.
- **Report honestly:** solved (verified), partial (real deliverable with the unverified parts named), or blocked (what
  blocked it, the evidence, and the next action). Never inflate a tier -- an honest partial is an expected outcome, a
  false green is not.
- Treat confident memory of external APIs, library versions, and tool syntax as potentially stale. Verify against a
  current authoritative source before an implementation-affecting claim.
- Never overwrite a working result without a recoverable copy.

## 43. Docs Mirror Reality

- A structural change -- new module, entry point, data file, config key, endpoint -- updates the architecture document in
  the same change.
- **Record the why** for every non-obvious decision, next to the decision: what was chosen, what was rejected, and the
  trade-off. A design without its rationale gets undone by the next reader who cannot see why it exists.
- Read before write. Never reconstruct a version, path, or config value from memory.

## 44. Tracing and Observability

`devkit.tracing` is the **only** observability API: a `Tracer`/`Context` wrapper over Logfire and OpenTelemetry.
There is no `logging` module usage and no `print` (`T20`). Everything is a span or an event on a span, so a failure is
debuggable with its full context, its arguments, and its place in the call tree.

Structured attributes always beat prose: pass `total=len(rows)`, not a formatted sentence. Distinguish "the call
failed" from "the call succeeded and returned a warning" -- they are different events at different levels.

### 44.1 Tracer setup

Every module or class that traces owns exactly one tracer -- module-level **or** class-level, not both.

```python
from typing import ClassVar, Final, Self, final

from devkit import tracing

__all__: Final[tuple[str, ...]] = ("Search",)

# Module-level tracer: `_TRACER`. Nothing outside the module traces through it, so it is private at
# module scope, and module scope means one underscore (section 24).
_TRACER: Final[tracing.Tracer] = tracing.Tracer(__name__)


@final
class Search:
    __slots__: ClassVar[tuple[str, ...]] = ()

    # Class-level tracer: `__TRACER`, a class attribute (section 33 puts it last). Two underscores here, because
    # this is a class body, where mangling is the mechanism actually being asked for.
    __TRACER: ClassVar[tracing.Tracer] = tracing.Tracer(__name__)
```

- `scope` is **positional-only**: `tracing.Tracer(__name__)`, never `tracing.Tracer(scope=__name__)`.
- Pass `__name__` so spans are scoped to the module.
- `tags` and `logfire` are keyword-only; the default tag set is a project constant and belongs in one place (section 3), not
  re-specified per call site.
- A logical subsystem gets a child tracer instead of a second root:
  `_TRACER.get_child("subsystem", tags={"subsystem_tag"})` -> scope `parent.module.subsystem`.

### 44.2 Spans: decorate entry points

Decorate the operation, not every helper. Six decorators, by the shape of what they wrap:

| Wrapped shape | Decorator | Options beyond `name_` / `message_` / `tags_` / `include_args_` |
|---|---|---|
| `async def` returning a value | `with_span_async` | `should_include_return_`, `should_keep_open_` |
| `def` returning a value | `with_span_sync` | `should_include_return_`, `should_keep_open_` |
| async iterator / async generator | `with_span_aiter` | `should_include_consumer_` |
| iterator / generator | `with_span_iter` | `should_include_consumer_` |
| `@asynccontextmanager` body | `with_span_acontextmanager` | -- |
| `@contextmanager` body | `with_span_contextmanager` | -- |

The option sets differ because the shapes differ: a return value only exists for the first two, and only an iterator
has a consumer whose per-item work could fall inside the span. Do not assume an option exists on a decorator that has
no use for it.

```python
@__TRACER.with_span_async(
    tracing.Level.INFO,
    include_args_={"query"},
    should_include_return_=True,
)
async def run(self: Self, /, query: str, assets: Sequence[Asset]) -> tuple[Asset, ...]:
    ...
```

`level` is positional-only. Everything else is keyword-only and **carries a trailing underscore** -- `name_`,
`message_`, `tags_`, `include_args_`, `should_include_return_`, `should_keep_open_`, `should_include_consumer_` --
because the tail of the signature is `**attributes`, and an attribute of the same name would otherwise collide with a
reserved keyword. Any new reserved keyword on these APIs takes the same trailing underscore; that is the whole reason
the convention exists. The underscore is orthogonal to section 23: a reserved keyword that is a boolean carries both, as
`should_keep_open_` does.

- `include_args_` -- `False` (default) records no arguments; `True` records all of them; `{"a", "b"}` records those
  arguments; `{"chat_id": "request.chat_id"}` records a mapping of attribute name to a dotted path *into* an argument.
- `should_include_return_` -- records the return value. Incompatible with `should_keep_open_=False`, which raises at
  decoration time.
- `should_keep_open_` -- `True` (default) keeps the span open around the body. `False` opens it just long enough to
  capture its context and closes it immediately, so the span is queryable while the work still nests under it; use it
  for long-running work whose parent span should not stay open.
- `name_` / `message_` override the auto-generated span name and message. Pass them only to override.
- `should_include_consumer_` on the iterator decorators controls whether the consumer's per-item work is inside the
  span; by default the caller's context is restored around each `yield`.

For a block that is not a whole function, `tracer.span(level, name=None, /, *, stack_depth_=0, message_=None,
tags_=None, should_keep_open_=True, **attributes)` returns the span as a context manager. Prefer a decorator when the
unit being traced is a function -- the decorator also records the code location automatically.

### 44.3 Events: inline log methods

`trace` - `debug` - `info` - `notice` - `warning` - `error` - `fatal`, all with the same signature:

```python
tracer.info(name=None, /, *, stack_depth_=0, should_reset_context_=False, message_=None, tags_=None,
            exception_=None, **attributes)
```

The caller's fully qualified name (`<module>.<class>.<method>`) is resolved from the stack and **prepended
automatically**, so pass only the trailing event suffix:

```python
# Final name: <module>.Search.run.deduplication_stats
self.__TRACER.info("deduplication_stats", before=len(discovered), after=len(deduplicated))

# Final name: <module>.Search.run.error
self.__TRACER.warning("error", exception_=exception, retry_count=retry)

# No suffix - logs under the bare caller name.
self.__TRACER.info(progress=0.5)
```

- `message_` changes the semantics: with a message the call opens a **span** instead of emitting a one-off event.
- `stack_depth_` -- increase it when wrapping these methods in a helper, so the auto-detected caller skips the wrapper
  frames.
- `exception_` -- attaches the exception and its full traceback.
- `should_reset_context_` -- emits the event detached from the current span context.
- Dynamic attributes on the span already in progress:
  `tracer.set_attributes_to_current_span(tracing.Level.DEBUG, current_index=index)`.

### 44.4 Levels

| Level | Use for |
|---|---|
| `TRACE` | Exhaustive detail, for rare deep debugging. |
| `DEBUG` | Internal helpers, background ticks, frequent operations. |
| `INFO` | Main entry points and significant operations. |
| `NOTICE` | Significant events worth surfacing above INFO. |
| `WARNING` | Recoverable errors, retries, degraded performance. |
| `ERROR` | Unrecoverable errors that propagate. |
| `FATAL` | Service-level failures. |

### 44.5 What goes into a span

Include: identifiers, counts, sizes, durations, configuration flags, small structured results.

Never include: passwords, API keys, tokens, or any credential (section 13); large payloads (full documents, binary data,
lists of hundreds of objects); user PII unless it is necessary and anonymized.

`include_args_=True` is a smell -- it ships whatever the signature happens to carry today, including the secret someone
adds tomorrow. Name the arguments you want.

### 44.6 Log it or raise it, never both

If you record an exception at some level, do not also re-raise it -- the outer handler records it again and the trace
shows one failure twice. Either handle it and record it, or let it propagate and be recorded once where it is handled.
This is the observability half of section 27.

```python
# Good - handled here, recorded here, not re-raised.
try:
    await risky_operation()

except Exception as exception:
    self.__TRACER.warning("operation_failed", exception_=exception, retry_count=retry)

# Good - propagates, recorded once by whoever handles it.
await risky_operation()
```

An error raised without a message cannot be diagnosed from the trace. Every raise carries a message naming the
artifact that failed (section 8, section 26) -- a bare `raise RuntimeError` records nothing but a line number.

### 44.7 Do not over-trace

Trace logical operations, not every function. A span around a one-line field parser is noise that costs money and
buries the spans that matter.

```python
# Bad - too granular.
@__TRACER.with_span_async(tracing.Level.DEBUG)
async def __parse_field(self: Self, /, field: str) -> str:
    return field.strip()

# Good - trace the operation; its helpers ride inside it.
@__TRACER.with_span_async(tracing.Level.INFO)
async def parse_document(self: Self, /, document: Document) -> ParsedDocument:
    ...
```

### 44.8 Cross-process and detached context

`tracing.Context` carries the trace across a process, queue, or service boundary so one logical operation stays one
trace.

```python
# Producer: capture and serialize.
context: Final[tracing.Context] = tracing.Context.get_current()
await queue.put({"payload": payload, **context.to_json_dict()})

# Consumer: restore. `is_remote=True` records the exception on the restored context, because
# the original span is already closed and cannot be updated.
context = tracing.Context.from_json_dict(message)
with context.attach(_TRACER, is_remote=True):
    await handle(message["payload"])
```

- `get_current()` / `from_json_dict()` / `from_bytes()` to obtain one; `to_json_dict()` / `to_bytes()` to carry it;
  `is_empty` to tell "no parent" from "parent unknown" (section 12).
- `attach_sync(tracer)` / `attach_async(tracer)` are the decorator forms of `attach`.
- `reset_context()` and the `with_reset_context_*` decorators detach work from the current trace -- for a background
  task that must not be nested under whoever happened to spawn it.
- Never re-derive a trace context from message content; carry it as the typed reference it already is (section 9).

## 45. Review Conventions

For reviewing a change, whether by a human or an agent.

- **Blocking threshold.** A blocking finding must satisfy all three: (a) it names the exact file, symbol, or path that
  makes the problem live *right now*; (b) that artifact is in this change; (c) the fix requires changing *this* change,
  not a follow-up. Otherwise it is advisory.
- **One root cause, one finding.** Do not split one underlying problem into several findings that all need the same
  fix. Do not keep a fixed finding alive by reformulating it as a broader future risk.
- **Coverage is semantic, not numerical.** Zero findings is a valid result. Never invent findings to reach a count.
- **Severity.** Blocking categories: public API and schemas, safety and permission guards, behavioural documentation
  that is now factually wrong, release metadata, the module map. Comment wording, changelog prose, and stylistic
  mismatch are advisory regardless of how concretely they are cited.
- **A missing-test finding must name** the specific behaviour this change introduces, and why existing tests do not
  catch it. "I would feel better with another test" is advisory.
- **Review is generative, not only audit.** Say what you would have done instead, and name the existing function or
  module that already solves the problem. That is worth more than a defect list.
- **Before retrying a blocked change**, group all findings by root cause, write the plan naming each group and the one
  change that resolves it, and only then start editing. Patching findings one at a time is the documented way to spend
  five rounds on a two-round problem.

## 46. Commit Hygiene

- One coherent purpose per commit, with explicit non-goals.
- The description states: the problem, what changed and why this approach fits, what is deliberately out of scope, the
  risks, and the exact verification performed with its result.
- English, imperative mood.
- Never commit secrets, local settings, runtime state, logs, caches, or build artifacts.
