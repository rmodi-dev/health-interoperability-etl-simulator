"""Engine and session factories.

Deliberate choices:
* Refuse to build an engine with an empty password: fail fast rather than silently
  relying on trust authentication.
* pool_pre_ping=True: lab VMs suspend/resume and containers restart; stale pooled
  connections otherwise surface as confusing InterfaceErrors mid-pipeline.
* expire_on_commit=False: ETL code reads attributes of returned objects after the
  transaction ends; the default would trigger lazy refresh SELECTs (or DetachedInstanceError).
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from health_interop.config import Settings


class ConfigurationError(RuntimeError):
    """Settings are unusable for database access."""


def build_engine(settings: Settings | None = None, *, echo: bool = False) -> Engine:
    cfg = settings if settings is not None else Settings()
    if not cfg.postgres_password.get_secret_value():
        raise ConfigurationError(
            "POSTGRES_PASSWORD is empty. Run 'make env' to generate .env, "
            "then 'make db-up' to start PostgreSQL."
        )
    return create_engine(
        cfg.database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success, roll back on any exception, always close."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def server_version(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(text("select version()")).scalar_one())
