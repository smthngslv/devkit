"""Async PostgreSQL engine ownership, session modes, and transaction boundaries."""

import contextlib
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, ClassVar, Final, Literal, Self, cast, final, overload

import pydantic
import sqlalchemy as sa
import sqlalchemy.ext.asyncio as sa_async
import sqlalchemy.sql.elements as sa_sql_elements
import sqlalchemy.sql.selectable as sa_sql_selectable

from devkit import tracing
from devkit.db.pool import TTLPool
from devkit.types.entity import Entity

__all__: Final[tuple[str, ...]] = ("AUTO", "TX", "Options", "Service", "Session")
_TRACER: Final[tracing.Tracer] = tracing.Tracer(__name__)


@final
# Pydantic initializes BaseModel's generated internals when it creates the subclass.
class Options(Entity):  # pyright: ignore[reportUninitializedInstanceVariable]
    """Validated pool, connection, and PostgreSQL options."""

    pool_idle_timeout: float = pydantic.Field(default=30.0, gt=0, description="Idle seconds before eviction.")
    pool_timeout: float = pydantic.Field(default=30.0, gt=0, description="Seconds to wait for a pool slot.")
    pool_max_connection_count: int = pydantic.Field(default=5, gt=0, description="Maximum open connections.")
    pool_recycle: float = pydantic.Field(default=900.0, ge=-1, description="Recycle age in seconds; -1 disables it.")
    pool_should_pre_ping: bool = pydantic.Field(default=True, description="Check connections before reuse.")
    connect_timeout: float = pydantic.Field(default=10.0, gt=0, description="Seconds to establish a connection.")
    command_timeout: float = pydantic.Field(default=60.0, gt=0, description="Seconds allowed for a database command.")
    application_name: str | None = pydantic.Field(default=None, description="PostgreSQL application name.")


@final
class TX:
    """Type marker for a session whose transaction can commit or roll back."""

    __slots__: ClassVar[tuple[str, ...]] = ()


@final
class AUTO:
    """Type marker for a session using database autocommit."""

    __slots__: ClassVar[tuple[str, ...]] = ()


@final
class Session[Mode: (TX, AUTO)]:
    """Wrap one async SQLAlchemy session with a typed transaction mode.

    ``Session[TX]`` supports commit, rollback, and transaction callbacks.
    ``Session[AUTO]`` executes statements in autocommit mode. Do not share a
    session across concurrent tasks. Closing a session runs pending rollback
    callbacks; a successful commit runs commit callbacks instead.
    """

    __slots__: ClassVar[tuple[str, ...]] = ("__is_autocommit", "__on_commit", "__on_rollback", "__session")

    @overload
    def __init__(self: Session[TX], /, session: sa_async.AsyncSession, *, is_autocommit: Literal[False]) -> None:
        raise NotImplementedError

    @overload
    def __init__(self: Session[AUTO], /, session: sa_async.AsyncSession, *, is_autocommit: Literal[True]) -> None:
        raise NotImplementedError

    def __init__(self: Self, /, session: sa_async.AsyncSession, *, is_autocommit: bool) -> None:
        self.__session: Final[sa_async.AsyncSession] = session
        self.__is_autocommit: Final[bool] = is_autocommit
        self.__on_commit: Final[list[Callable[[], Awaitable[None] | None]]] = []
        self.__on_rollback: Final[list[Callable[[], Awaitable[None] | None]]] = []

    def on_commit(self: Session[TX], /, on_event_callback: Callable[[], Awaitable[None] | None]) -> None:
        """Run the callback after a successful commit, once, in registration order."""
        if self.__is_autocommit:
            message: Final[str] = "Autocommit sessions cannot register commit callbacks."
            raise RuntimeError(message)

        self.__on_commit.append(on_event_callback)

    def on_rollback(self: Session[TX], /, on_event_callback: Callable[[], Awaitable[None] | None]) -> None:
        """Run the callback after rollback or session closure without a commit."""
        if self.__is_autocommit:
            message: Final[str] = "Autocommit sessions cannot register rollback callbacks."
            raise RuntimeError(message)

        self.__on_rollback.append(on_event_callback)

    async def __aenter__(self: Self, /) -> Self:
        await self.__session.__aenter__()
        return self

    async def __aexit__(self: Self, /, *exception: object) -> None:
        try:
            await self.__session.__aexit__(*exception)

        finally:
            await self.__run_callbacks(is_commit=False)

    @overload
    async def execute[*ResultTypes](
        self: Self, /, statement: sa_sql_selectable.TypedReturnsRows[*ResultTypes]
    ) -> sa.Result[*ResultTypes]:
        raise NotImplementedError

    @overload
    async def execute(self: Self, /, statement: sa.Executable) -> sa.Result[*tuple[Any, ...]]:
        raise NotImplementedError

    async def execute(self: Self, /, statement: sa.Executable) -> sa.Result[*tuple[Any, ...]]:
        """Execute a statement and trace its compiled SQL when debug tracing is enabled.

        The trace records SQL with bind placeholders, not bound parameter values.
        A compilation failure emits a warning and does not prevent execution.
        Use bound parameters rather than embedding sensitive values in SQL text.
        """
        with _TRACER.span(tracing.Level.DEBUG, "execute", statement_type=statement.__class__.__name__):
            if _TRACER.level <= tracing.Level.DEBUG:
                compilable: Final[sa_sql_elements.CompilerElement] = cast("sa_sql_elements.CompilerElement", statement)
                try:
                    sql: Final[str] = str(compilable.compile(self.__session.bind))

                except Exception as exception:
                    _TRACER.warning("sql_compile_failed", exception_=exception)

                else:
                    _TRACER.set_attributes_to_current_span(tracing.Level.DEBUG, sql=sql)

            return await self.__session.execute(statement)

    @_TRACER.with_span_async(tracing.Level.DEBUG)
    async def get_connection(self: Self, /) -> sa_async.AsyncConnection:
        """Return the connection held by this session."""
        return await self.__session.connection()

    @_TRACER.with_span_async(tracing.Level.DEBUG)
    async def commit(self: Session[TX], /) -> None:
        """Commit the transaction and then run registered commit callbacks."""
        await self.__session.commit()
        await self.__run_callbacks(is_commit=True)

    @_TRACER.with_span_async(tracing.Level.DEBUG)
    async def rollback(self: Session[TX], /) -> None:
        """Roll back the transaction and then run registered rollback callbacks."""
        await self.__session.rollback()
        await self.__run_callbacks(is_commit=False)

    @_TRACER.with_span_async(tracing.Level.DEBUG)
    async def shutdown(self: Self, /) -> None:
        """Close the session and run pending rollback callbacks."""
        try:
            await self.__session.close()

        finally:
            await self.__run_callbacks(is_commit=False)

    async def __run_callbacks(self: Self, /, *, is_commit: bool) -> None:
        callbacks: Final[tuple[Callable[[], Awaitable[None] | None], ...]] = tuple(
            self.__on_commit if is_commit else self.__on_rollback
        )
        self.__on_commit.clear()
        self.__on_rollback.clear()
        on_event_callback: Callable[[], Awaitable[None] | None]
        for on_event_callback in callbacks:
            result: Awaitable[None] | None = on_event_callback()
            if result is not None:
                await result


@final
class Service:
    """Own async database engines, session factories, and their pool.

    Pass one service to operations that need the database, and close it at the
    application boundary. The async context manager disposes the engine and pool
    on exit. Configure Logfire once in the application entry point; this module
    emits debug spans for execution, connections, transactions, and disposal.
    """

    __slots__: ClassVar[tuple[str, ...]] = ("__auto_engine", "__auto_sessions", "__engine", "__sessions")

    def __init__(self: Self, /, url: str | sa.engine.URL, *, options: Options | None = None) -> None:
        """Create a PostgreSQL async engine from its URL and validated options."""
        if options is None:
            options = Options()

        self.__engine: Final[sa_async.AsyncEngine] = sa_async.create_async_engine(
            url,
            poolclass=TTLPool,
            idle_timeout=options.pool_idle_timeout,
            acquire_timeout=options.pool_timeout,
            max_connection_count=options.pool_max_connection_count,
            pool_recycle=options.pool_recycle,
            pool_pre_ping=options.pool_should_pre_ping,
            connect_args={
                "timeout": options.connect_timeout,
                "command_timeout": options.command_timeout,
                "server_settings": (
                    {"application_name": options.application_name} if options.application_name is not None else {}
                ),
            },
        )
        self.__auto_engine: Final[sa_async.AsyncEngine] = self.__engine.execution_options(isolation_level="AUTOCOMMIT")
        self.__sessions: Final[sa_async.async_sessionmaker[sa_async.AsyncSession]] = sa_async.async_sessionmaker(
            self.__engine, expire_on_commit=False
        )
        self.__auto_sessions: Final[sa_async.async_sessionmaker[sa_async.AsyncSession]] = sa_async.async_sessionmaker(
            self.__auto_engine, expire_on_commit=False
        )

    @overload
    def auto[Mode: (TX, AUTO)](
        self: Self, /, session: Session[Mode]
    ) -> contextlib.AbstractAsyncContextManager[Session[Mode]]:
        raise NotImplementedError

    @overload
    def auto(self: Self, /, session: None = None) -> contextlib.AbstractAsyncContextManager[Session[AUTO]]:
        raise NotImplementedError

    @_TRACER.with_span_acontextmanager(tracing.Level.DEBUG)
    async def auto(self: Self, /, session: Session[Any] | None = None) -> AsyncGenerator[Session[Any]]:
        """Yield an autocommit session for statements needing that mode.

        When ``session`` is supplied, reuse it in its existing mode without
        closing or committing it.
        """
        if session is not None:
            yield session
            return

        db_session: Session[AUTO]
        async with Session(self.__auto_sessions(), is_autocommit=True) as db_session:
            yield db_session

    def get_engine(self: Self, /, *, use_auto_commit: bool = False) -> sa_async.AsyncEngine:
        """Return the managed engine, optionally with autocommit enabled."""
        return self.__auto_engine if use_auto_commit else self.__engine

    async def __aenter__(self: Self, /) -> Self:
        return self

    async def __aexit__(self: Self, /, *exception: object) -> None:
        await self.dispose()

    @_TRACER.with_span_acontextmanager(tracing.Level.DEBUG)
    async def tx(self: Self, /, session: Session[TX] | None = None) -> AsyncGenerator[Session[TX]]:
        """Yield a transaction that commits on success and rolls back on error.

        When ``session`` is supplied, reuse it without closing or committing it.
        """
        if session is not None:
            yield session
            return

        db_session: Session[TX]
        async with Session(self.__sessions(), is_autocommit=False) as db_session:
            yield db_session
            await db_session.commit()

    @_TRACER.with_span_async(tracing.Level.DEBUG)
    async def dispose(self: Self, /) -> None:
        """Dispose the engine and its connection pool."""
        await self.__engine.dispose()
