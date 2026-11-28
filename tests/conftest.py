"""Shared pytest fixtures.

Integration tests (marked `integration`) need a reachable PostgreSQL. When it is
absent - a Windows dev box, or CI without the service container - they SKIP with
an explicit reason rather than erroring.

Isolation: tests run against a dedicated `interop_test` database, created and
dropped by the session fixture. The real `interop` database is never touched.
Each test runs inside a connection-level transaction that is rolled back.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from health_interop.config import Settings
from health_interop.db.base import SCHEMAS, Base

TEST_DB_NAME = "interop_test"  # constant identifier, never user input


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    settings = Settings()
    if not settings.postgres_password.get_secret_value():
        pytest.skip("POSTGRES_PASSWORD not set; run 'make env' then 'make db-up'.")

    admin = create_engine(
        settings.database_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as conn:
            found = conn.execute(
                text("select 1 from pg_database where datname = :name"),
                {"name": TEST_DB_NAME},
            ).scalar_one_or_none()
            if found is None:
                conn.execute(text(f'create database "{TEST_DB_NAME}"'))
    except Exception as exc:  # noqa: BLE001 - any failure means "no database available"
        admin.dispose()
        pytest.skip(f"PostgreSQL not reachable: {exc}")

    engine = create_engine(settings.database_url.set(database=TEST_DB_NAME), pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            for schema in SCHEMAS:
                conn.execute(text(f'create schema if not exists "{schema}"'))
        Base.metadata.create_all(engine)
    except Exception as exc:  # noqa: BLE001
        engine.dispose()
        admin.dispose()
        pytest.skip(f"Could not prepare test schema: {exc}")

    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'drop database if exists "{TEST_DB_NAME}" with (force)'))
        admin.dispose()


@pytest.fixture
def db_session(pg_engine: Engine) -> Iterator[Session]:
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, autoflush=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
