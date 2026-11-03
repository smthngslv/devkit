"""Exercise connection limits, reuse, and idle eviction."""

import asyncio
import unittest.mock
from typing import Final

import pytest
import sqlalchemy.exc as sa_exc
import sqlalchemy.pool as sa_pool
import sqlalchemy.util as sa_util

import devkit.db.pool as db_pool
from devkit import db

__all__: Final[tuple[str, ...]] = ()


def test_pool_limits_connections_and_reuses_idle_entry() -> None:
    """Allow one checked-out connection, time out a second request, then reuse the returned entry."""
    connections: Final[list[unittest.mock.Mock]] = []

    def create_connection() -> unittest.mock.Mock:
        connection: Final[unittest.mock.Mock] = unittest.mock.Mock()
        connections.append(connection)
        return connection

    async def exercise() -> None:
        pool: Final[db.TTLPool] = db.TTLPool(
            create_connection, idle_timeout=30.0, acquire_timeout=0.01, max_connection_count=1
        )
        try:
            first: Final[sa_pool.PoolProxiedConnection] = await sa_util.greenlet_spawn(pool.connect)
            with pytest.raises(sa_exc.TimeoutError, match="Could not acquire a connection"):
                await sa_util.greenlet_spawn(pool.connect)

            first.close()
            second: Final[sa_pool.PoolProxiedConnection] = await sa_util.greenlet_spawn(pool.connect)
            assert second.dbapi_connection is connections[0]
            assert len(connections) == 1
            second.close()
            assert pool.status() == "TTLPool(idle=1, max=1)"

        finally:
            pool.dispose()
            await asyncio.sleep(0)

        connections[0].close.assert_called_once_with()

    asyncio.run(exercise())


def test_pool_recreate_keeps_connection_limit() -> None:
    """Carry pool capacity into SQLAlchemy's replacement pool without starting an event loop."""
    pool: Final[db.TTLPool] = db.TTLPool(unittest.mock.Mock(), max_connection_count=2)
    replacement: Final[db.TTLPool] = pool.recreate()
    try:
        assert replacement.status() == "TTLPool(idle=0, max=2)"

    finally:
        replacement.dispose()
        pool.dispose()


def test_pool_closes_expired_idle_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Close an idle entry after its TTL without waiting for the production reaper interval."""
    original_sleep: Final = asyncio.sleep

    async def accelerate_reaper(delay: float) -> None:
        await original_sleep(min(delay, 0.001))

    monkeypatch.setattr(db_pool.asyncio, "sleep", accelerate_reaper)

    async def exercise() -> None:
        closed: Final[asyncio.Event] = asyncio.Event()
        connection: Final[unittest.mock.Mock] = unittest.mock.Mock()
        connection.close.side_effect = closed.set
        pool: Final[db.TTLPool] = db.TTLPool(
            lambda: connection, idle_timeout=0.001, acquire_timeout=0.1, max_connection_count=1
        )
        try:
            borrowed: Final[sa_pool.PoolProxiedConnection] = await sa_util.greenlet_spawn(pool.connect)
            borrowed.close()
            await asyncio.wait_for(closed.wait(), timeout=0.5)
            assert pool.status() == "TTLPool(idle=0, max=1)"

        finally:
            pool.dispose()

    asyncio.run(exercise())
