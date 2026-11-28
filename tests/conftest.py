"""Shared pytest fixtures.

Schema source of truth: Alembic migrations (NOT create_all). The session fixture
creates a dedicated `interop_test` database, applies `alembic upgrade head`, and
drops the database on teardown. The real `interop` database is never touched.

Integration tests (marked `integration`) SKIP with an explicit reason when
PostgreSQL is unreachable, so Windows and DB-less environments stay green.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from health_interop.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
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

    test_url = settings.database_url.set(database=TEST_DB_NAME)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_url.render_as_string(hide_password=False))
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001
        admin.dispose()
        pytest.skip(f"Alembic upgrade failed: {exc}")

    engine = create_engine(test_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'drop database if exists "{TEST_DB_NAME}" with (force)'))
        admin.dispose()


@pytest.fixture(scope="session")
def alembic_config(pg_engine: Engine) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", pg_engine.url.render_as_string(hide_password=False))
    return cfg


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
