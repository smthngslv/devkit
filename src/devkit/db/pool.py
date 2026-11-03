"""Bounded SQLAlchemy connection pool with idle connection eviction."""

import asyncio
import collections
import threading
import time
from typing import Any, ClassVar, Final, Self, final, override

import sqlalchemy.exc as sa_exc
import sqlalchemy.pool as sa_pool
import sqlalchemy.util as sa_util

from devkit import tracing

__all__: Final[tuple[str, ...]] = ("TTLPool",)


@final
class TTLPool(sa_pool.Pool):
    """Cap open connections and close idle entries after their time to live.

    ``acquire_timeout`` bounds the wait for a pool slot. ``idle_timeout`` is
    the number of idle seconds before an entry is eligible for eviction.
    ``max_connection_count`` is a hard cap on concurrently held connections.
    Failed connection creation releases its reserved slot.
    """

    # SQLAlchemy's EventTarget types __slots__ as an instance variable, but this is class configuration.
    __slots__: ClassVar[tuple[str, ...]] = (  # type: ignore[misc]
        "__acquire_timeout",
        "__idle",
        "__idle_timeout",
        "__lock",
        "__max_connection_count",
        "__reaper_task",
        "__semaphore",
    )

    __TRACER: ClassVar[tracing.Tracer] = tracing.Tracer(__name__)

    # SQLAlchemy inspects positional-or-keyword parameters when forwarding create_engine pool options.
    def __init__(
        self: Self,
        /,
        creator: Any,
        idle_timeout: float = 30.0,
        acquire_timeout: float = 30.0,
        max_connection_count: int = 1,
        **kwargs: Any,
    ) -> None:
        super().__init__(creator, **kwargs)
        self.__idle_timeout: Final[float] = idle_timeout
        self.__acquire_timeout: Final[float] = acquire_timeout
        self.__max_connection_count: Final[int] = max_connection_count
        self.__lock: Final[threading.Lock] = threading.Lock()
        self.__semaphore: Final[asyncio.Semaphore] = asyncio.Semaphore(max_connection_count)
        self.__idle: Final[collections.deque[tuple[sa_pool.ConnectionPoolEntry, float]]] = collections.deque()
        self.__reaper_task: asyncio.Task[None] | None = None

    @override
    def status(self: Self, /) -> str:
        """Summarize the current idle count and connection limit."""
        return f"TTLPool(idle={len(self.__idle)}, max={self.__max_connection_count})"

    @override
    def recreate(self: Self, /) -> Self:
        """Build a fresh pool with the same limits and SQLAlchemy options."""
        return self.__class__(
            self._creator,
            self.__idle_timeout,
            self.__acquire_timeout,
            self.__max_connection_count,
            recycle=self._recycle,
            echo=self.echo,
            logging_name=self._orig_logging_name,
            reset_on_return=self._reset_on_return,
            pre_ping=self._pre_ping,
            dialect=self._dialect,
            _dispatch=self.dispatch,
        )

    @override
    def dispose(self: Self, /) -> None:
        """Cancel idle eviction and close every idle connection."""
        if self.__reaper_task is not None:
            self.__reaper_task.cancel()

        with self.__lock:
            entries: Final[tuple[tuple[sa_pool.ConnectionPoolEntry, float], ...]] = tuple(self.__idle)
            self.__idle.clear()

        entry: sa_pool.ConnectionPoolEntry
        for entry, _ in entries:
            try:
                entry.close()

            except BaseException as exception:
                self.__TRACER.warning("close_failed", exception_=exception)

    @override
    def _do_get(self: Self, /) -> sa_pool.ConnectionPoolEntry:
        if self.__reaper_task is None:
            self.__reaper_task = asyncio.get_running_loop().create_task(self.__reap_loop())

        elif self.__reaper_task.done():
            self.__reaper_task.result()

        sa_util.await_only(self.__acquire())
        with self.__lock:
            reused: Final[sa_pool.ConnectionPoolEntry | None] = self.__idle.pop()[0] if len(self.__idle) > 0 else None

        if reused is not None:
            return reused

        try:
            return self._create_connection()

        except BaseException:
            self.__semaphore.release()
            raise

    @override
    def _do_return_conn(self: Self, /, record: sa_pool.ConnectionPoolEntry) -> None:
        expires_at: Final[float] = time.monotonic() + self.__idle_timeout
        with self.__lock:
            self.__idle.append((record, expires_at))

        self.__semaphore.release()

    def __reap(self: Self, /) -> None:
        now: Final[float] = time.monotonic()
        expired: Final[list[sa_pool.ConnectionPoolEntry]] = []
        with self.__lock:
            while len(self.__idle) > 0 and self.__idle[0][1] <= now:
                expired.append(self.__idle.popleft()[0])

        entry: sa_pool.ConnectionPoolEntry
        for entry in expired:
            try:
                entry.close()

            except BaseException as exception:
                self.__TRACER.warning("close_failed", exception_=exception)

    async def __acquire(self: Self, /) -> None:
        try:
            await asyncio.wait_for(self.__semaphore.acquire(), self.__acquire_timeout)

        except TimeoutError:
            message: Final[str] = f"Could not acquire a connection within {self.__acquire_timeout} seconds."
            raise sa_exc.TimeoutError(message) from None

    async def __reap_loop(self: Self, /) -> None:
        interval: Final[float] = max(1.0, self.__idle_timeout / 2.0)
        try:
            while True:
                await asyncio.sleep(interval)
                if len(self.__idle) > 0:
                    await sa_util.greenlet_spawn(self.__reap)

        except asyncio.CancelledError:
            return
