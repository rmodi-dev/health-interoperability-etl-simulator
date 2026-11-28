"""Declarative base, schema registry and constraint naming convention.

Deterministic constraint names are a deliberate choice: Alembic autogenerate
produces readable diffs, and downgrade scripts can reference names reliably.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMAS: tuple[str, ...] = ("raw", "stg", "core", "dq", "fhir")

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Single declarative base shared by every model and by Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
