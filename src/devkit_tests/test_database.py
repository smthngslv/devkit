"""Exercise database configuration, sessions, tracing, and migrations."""

import asyncio
import contextlib
import importlib.resources
import pathlib
import runpy
import unittest.mock
from collections.abc import Callable, Iterator
from typing import Any, ClassVar, Final, cast, final

import alembic.config
import alembic.context
import logfire
import opentelemetry.sdk.trace as otel_sdk_trace
import opentelemetry.sdk.trace.export as otel_sdk_trace_export
import pydantic
import pydantic_settings
import pytest
import sqlalchemy as sa
import sqlalchemy.ext.asyncio as sa_async
import sqlalchemy.orm as sa_orm
import sqlalchemy.sql.elements as sa_sql_elements
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.dialects import postgresql

import devkit.db.service as db_service_module
from devkit import db, tracing
from devkit.db.settings import Settings
from devkit.types import Entity

__all__: Final[tuple[str, ...]] = ()


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    """Collect spans emitted by database tests without a network exporter."""
    return InMemorySpanExporter()


def test_settings_read_typed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read the PostgreSQL URL and nested pool options through Pydantic Settings."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/example")
    monkeypatch.setenv("DATABASE_OPTIONS__POOL_MAX_CONNECTION_COUNT", "3")
    monkeypatch.setenv("DATABASE_OPTIONS__POOL_IDLE_TIMEOUT", "12.5")
    # Pydantic Settings supplies this required field from the environment at runtime.
    settings: Final[Settings] = Settings()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
    assert str(settings.url) == "postgresql+asyncpg://user:pass@localhost/example"
    assert settings.options.pool_max_connection_count == 3
    assert settings.options.pool_idle_timeout == 12.5


def test_settings_work_as_nested_application_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """A top-level settings model reads database.url and database.options from nested environment keys."""

    @final
    # Pydantic initializes BaseModel's generated internals when it creates the subclass.
    class ApplicationSettings(pydantic_settings.BaseSettings):  # pyright: ignore[reportUninitializedInstanceVariable]
        model_config: ClassVar[pydantic_settings.SettingsConfigDict] = pydantic_settings.SettingsConfigDict(
            env_prefix="APP_", env_nested_delimiter="__"
        )

        database: Settings

    monkeypatch.setenv("APP_DATABASE__URL", "postgresql+asyncpg://user:pass@localhost/example")
    monkeypatch.setenv("APP_DATABASE__OPTIONS__POOL_MAX_CONNECTION_COUNT", "3")
    # Pydantic Settings supplies this required field from the environment at runtime.
    settings: Final[ApplicationSettings] = ApplicationSettings()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
    assert str(settings.database.url) == "postgresql+asyncpg://user:pass@localhost/example"
    assert settings.database.options.pool_max_connection_count == 3


def test_settings_reject_invalid_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail during configuration validation when the database URL is malformed, before any connection attempt."""
    monkeypatch.setenv("DATABASE_URL", "not-a-postgres-url")
    with pytest.raises(pydantic.ValidationError, match="url"):
        # Pydantic Settings supplies this required field from the environment at runtime.
        Settings()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


def test_settings_reject_invalid_nested_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject a zero connection limit supplied through the nested environment settings."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/example")
    monkeypatch.setenv("DATABASE_OPTIONS__POOL_MAX_CONNECTION_COUNT", "0")
    with pytest.raises(pydantic.ValidationError, match="pool_max_connection_count"):
        # Pydantic Settings supplies this required field from the environment at runtime.
        Settings()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


def test_options_inherit_entity_validation() -> None:
    """Database options use the shared Entity policy, including rejection of unexpected keys."""
    assert isinstance(db.Options(), Entity)
    with pytest.raises(pydantic.ValidationError, match="extra_forbidden"):
        db.Options.model_validate({"unknown": True})


def test_database_engine_is_lazy() -> None:
    """Construct and dispose the service without opening a PostgreSQL connection."""
    database: Final[db.Service] = db.Service("postgresql+asyncpg://user:pass@localhost/example")
    assert isinstance(database, db.Service)
    asyncio.run(database.dispose())


def test_service_passes_pool_and_driver_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forward bounded pool and asyncpg settings to the engine without connecting to PostgreSQL."""
    create_engine: Final = sa_async.create_async_engine
    received: Final[dict[str, Any]] = {}

    def capture_engine(url: str | sa.engine.URL, **kwargs: Any) -> sa_async.AsyncEngine:
        received.update(kwargs)
        return create_engine(url, **kwargs)

    monkeypatch.setattr(sa_async, "create_async_engine", capture_engine)
    options: Final[db.Options] = db.Options(
        pool_max_connection_count=3,
        pool_idle_timeout=5.0,
        pool_timeout=7.0,
        pool_recycle=120.0,
        pool_should_pre_ping=False,
        connect_timeout=4.0,
        command_timeout=9.0,
        application_name="example",
    )
    service: Final[db.Service] = db.Service("postgresql+asyncpg://user:pass@localhost/example", options=options)
    assert isinstance(service.get_engine().sync_engine.pool, db.TTLPool)
    assert service.get_engine().sync_engine.pool.status() == "TTLPool(idle=0, max=3)"
    assert received == {
        "poolclass": db.TTLPool,
        "max_connection_count": 3,
        "idle_timeout": 5.0,
        "acquire_timeout": 7.0,
        "pool_recycle": 120.0,
        "pool_pre_ping": False,
        "connect_args": {"timeout": 4.0, "command_timeout": 9.0, "server_settings": {"application_name": "example"}},
    }
    asyncio.run(service.dispose())


def test_database_traces_sql_without_bound_values(
    monkeypatch: pytest.MonkeyPatch, exporter: InMemorySpanExporter
) -> None:
    """The static database tracer records SQL placeholders without bound values or the URL password."""
    service: Final[db.Service] = db.Service("postgresql+asyncpg://user:password@localhost/example")
    execute: Final[unittest.mock.AsyncMock] = unittest.mock.AsyncMock()
    monkeypatch.setattr(sa_async.AsyncSession, "execute", execute)

    async def run() -> None:
        session: db.Session[db.TX]
        async with service.tx() as session:
            await session.execute(sa.text(text="SELECT :value").bindparams(value="secret"))

        await service.dispose()

    asyncio.run(run())
    spans: Final[tuple[otel_sdk_trace.ReadableSpan, ...]] = exporter.get_finished_spans()
    sql_spans: Final[list[otel_sdk_trace.ReadableSpan]] = [
        span for span in spans if span.attributes is not None and "sql" in span.attributes
    ]
    assert len(sql_spans) == 1
    attributes: Final = sql_spans[0].attributes
    assert attributes is not None
    assert "SELECT" in str(attributes["sql"])
    assert "secret" not in str(attributes)
    assert "password" not in str(attributes)
    assert execute.await_count == 1


def test_database_executes_when_sql_cannot_be_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Warn about SQL rendering failure but still pass the original statement to the session for execution."""
    service: Final[db.Service] = db.Service("postgresql+asyncpg://user:pass@localhost/example")
    execute: Final[unittest.mock.AsyncMock] = unittest.mock.AsyncMock()
    warning: Final[unittest.mock.MagicMock] = unittest.mock.MagicMock()
    monkeypatch.setattr(sa_async.AsyncSession, "execute", execute)
    monkeypatch.setattr(tracing.Tracer, "warning", warning)
    statement: Final[sa_sql_elements.TextClause] = sa.text(text="SELECT 1")
    error: Final[RuntimeError] = RuntimeError("Cannot compile SQL.")

    async def run() -> None:
        session: db.Session[db.TX]
        async with service.tx() as session:
            with unittest.mock.patch.object(sa_sql_elements.TextClause, "compile", side_effect=error):
                await session.execute(statement)

        await service.dispose()

    asyncio.run(run())
    execute.assert_awaited_once_with(statement)
    warning.assert_called_once_with("sql_compile_failed", exception_=error)


def test_declarative_table_uses_postgresql_types() -> None:
    """Compile a mapped table with exact PostgreSQL column types, without network or database setup."""

    class Example(db.tables.Table):
        __tablename__ = "examples"

        id: sa_orm.Mapped[int] = sa_orm.mapped_column(postgresql.INTEGER, primary_key=True)
        name: sa_orm.Mapped[str] = sa_orm.mapped_column(postgresql.TEXT, nullable=False)

    table: Final[sa.Table] = cast("sa.Table", Example.__table__)
    sql: Final[str] = str(sa.schema.CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "SERIAL" in sql
    assert "TEXT" in sql


def test_migration_template_is_packaged() -> None:
    """Ship Alembic's generator template and import the same sa alias that generated operations use."""
    template: Final[pathlib.Path] = pathlib.Path(
        str(importlib.resources.files("devkit.db.migrations") / "script.py.mako")
    )
    assert template.is_file()
    assert "import sqlalchemy as sa" in template.read_text()
    assert "import devkit.db.types" in template.read_text()


def test_migration_configuration_comes_from_pyproject() -> None:
    """Resolve Alembic's script directory from pyproject.toml without an alembic.ini file."""
    root: Final[pathlib.Path] = pathlib.Path(__file__).resolve().parents[2]
    configuration: Final[alembic.config.Config] = alembic.config.Config(toml_file=str(root / "pyproject.toml"))
    location: Final[str | None] = configuration.get_alembic_option("script_location")
    assert location == str(root / "src/devkit/db/migrations")
    assert not (root / "alembic.ini").exists()


def test_online_migrations_use_service_and_one_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run Alembic through the service and commit its connection context without opening PostgreSQL."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/example")
    monkeypatch.setenv("DATABASE_OPTIONS__POOL_MAX_CONNECTION_COUNT", "2")
    monkeypatch.setattr(alembic.context, "is_offline_mode", unittest.mock.MagicMock(return_value=False))
    sync_connection: Final[sa.engine.Connection] = cast("sa.engine.Connection", unittest.mock.sentinel.connection)
    connection: Final[unittest.mock.AsyncMock] = unittest.mock.AsyncMock()
    connection.__aenter__.return_value = connection

    def run_sync(on_migration_callback: Callable[[sa.engine.Connection], None], /) -> None:
        on_migration_callback(sync_connection)

    connection.run_sync.side_effect = run_sync
    engine: Final[unittest.mock.MagicMock] = unittest.mock.MagicMock()
    engine.begin.return_value = connection
    db_service: Final[unittest.mock.AsyncMock] = unittest.mock.AsyncMock()
    db_service.__aenter__.return_value = db_service
    db_service.get_engine = unittest.mock.MagicMock(return_value=engine)
    create_service: Final[unittest.mock.MagicMock] = unittest.mock.MagicMock(return_value=db_service)
    monkeypatch.setattr(db_service_module, "Service", create_service)
    configure: Final[unittest.mock.MagicMock] = unittest.mock.MagicMock()
    begin_transaction: Final[unittest.mock.MagicMock] = unittest.mock.MagicMock(return_value=contextlib.nullcontext())
    run_migrations: Final[unittest.mock.MagicMock] = unittest.mock.MagicMock()
    monkeypatch.setattr(alembic.context, "configure", configure)
    monkeypatch.setattr(alembic.context, "begin_transaction", begin_transaction)
    monkeypatch.setattr(alembic.context, "run_migrations", run_migrations)

    environment: Final[pathlib.Path] = pathlib.Path(__file__).resolve().parents[1] / "devkit/db/migrations/env.py"
    runpy.run_path(str(environment))

    create_service.assert_called_once_with(
        "postgresql+asyncpg://user:pass@localhost/example", options=db.Options(pool_max_connection_count=2)
    )
    engine.begin.assert_called_once_with()
    connection.run_sync.assert_awaited_once()
    configure.assert_called_once_with(
        connection=sync_connection, target_metadata=db.tables.Table.metadata, sqlalchemy_module_prefix="sa."
    )
    begin_transaction.assert_called_once_with()
    run_migrations.assert_called_once_with()
    connection.__aexit__.assert_awaited_once()
    db_service.__aexit__.assert_awaited_once()


def test_migrations_reject_offline_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject offline Alembic runs before loading settings or creating a database service."""
    monkeypatch.setattr(alembic.context, "is_offline_mode", unittest.mock.MagicMock(return_value=True))
    environment: Final[pathlib.Path] = pathlib.Path(__file__).resolve().parents[1] / "devkit/db/migrations/env.py"
    with pytest.raises(NotImplementedError, match="Offline migrations are not supported"):
        runpy.run_path(str(environment))


def test_tx_and_auto_modes_reuse_sessions_without_network(exporter: InMemorySpanExporter) -> None:
    """Trace both session modes while nested reuse keeps the caller's context and commits only once."""
    database: Final[db.Service] = db.Service("postgresql+asyncpg://user:pass@localhost/example")
    events: Final[list[str]] = []

    def on_commit_callback() -> None:
        events.append("committed")

    async def exercise() -> None:
        parent: Final[str | None] = tracing.Context.get_current().parent
        tx_session: db.Session[db.TX]
        async with database.tx() as tx_session:
            assert tracing.Context.get_current().parent == parent
            tx_session.on_commit(on_commit_callback)
            reused_tx: db.Session[db.TX]
            async with database.tx(tx_session) as reused_tx:
                assert reused_tx is tx_session

            reused_auto: db.Session[db.TX]
            async with database.auto(tx_session) as reused_auto:
                assert reused_auto is tx_session

        auto_session: db.Session[db.AUTO]
        async with database.auto() as auto_session:
            assert tracing.Context.get_current().parent == parent
            reused: db.Session[db.AUTO]
            async with database.auto(auto_session) as reused:
                assert reused is auto_session

        await database.dispose()
        assert tracing.Context.get_current().parent == parent

    asyncio.run(exercise())
    assert events == ["committed"]
    span_names: Final[set[str]] = {span.name for span in exporter.get_finished_spans()}
    assert "devkit.db.service.Service.auto" in span_names
    assert "devkit.db.service.Service.tx" in span_names


def test_tx_rolls_back_and_runs_callback_on_failure() -> None:
    """A failed transaction propagates its error and runs rollback callbacks without committing."""
    database: Final[db.Service] = db.Service("postgresql+asyncpg://user:pass@localhost/example")
    events: Final[list[str]] = []

    def on_commit_callback() -> None:
        events.append("committed")

    def on_rollback_callback() -> None:
        events.append("rolled back")

    async def fail() -> None:
        tx_session: db.Session[db.TX]
        async with database.tx() as tx_session:
            tx_session.on_commit(on_commit_callback)
            tx_session.on_rollback(on_rollback_callback)
            message: Final[str] = "Transaction failure."
            raise ValueError(message)

    async def exercise() -> None:
        with pytest.raises(ValueError, match="failure"):
            await fail()

        await database.dispose()

    asyncio.run(exercise())
    assert events == ["rolled back"]


@pytest.fixture(autouse=True)
def _configure_logfire(exporter: InMemorySpanExporter) -> Iterator[None]:
    instance: Final[logfire.Logfire] = logfire.configure(
        local=False,
        send_to_logfire=False,
        console=False,
        metrics=False,
        inspect_arguments=False,
        min_level=0,
        additional_span_processors=[otel_sdk_trace_export.SimpleSpanProcessor(exporter)],
    )
    try:
        yield

    finally:
        instance.shutdown()
