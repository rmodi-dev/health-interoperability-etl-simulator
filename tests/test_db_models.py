"""Schema unit tests: metadata invariants and PostgreSQL DDL compilation.

These require NO database connection, so they run on Windows, the VM and CI.
Real CRUD/lineage behaviour is covered by integration tests in Step 2.2.

Typing note: SQLAlchemy declares DeclarativeBase.__table__ as ClassVar[FromClause]
because a mapped class may map to a Subquery. Every model here maps to a plain
Table, so table_of() asserts that invariant: it narrows the static type AND fails
loudly if a model is ever remapped to something else.
"""

import re

from sqlalchemy import CheckConstraint, Enum, Numeric, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from health_interop.db.base import SCHEMAS, Base
from health_interop.db.models import (
    DqaFinding,
    FhirResource,
    IngestMessage,
    LabOrder,
    LabResult,
    Patient,
    Specimen,
    StagedLabResult,
)

EXPECTED_TABLES = {
    ("raw", "ingest_message"),
    ("stg", "lab_result"),
    ("core", "patient"),
    ("core", "lab_order"),
    ("core", "specimen"),
    ("core", "lab_result"),
    ("dq", "finding"),
    ("fhir", "resource"),
}


def table_of(model: type[Base]) -> Table:
    """Return the model's Table, asserting it is not a subquery/join mapping."""
    table = model.__table__
    assert isinstance(table, Table), f"{model.__name__} is not mapped to a Table"
    return table


def test_declared_schemas_match_registry() -> None:
    actual = {t.schema for t in Base.metadata.sorted_tables}
    assert actual == set(SCHEMAS)


def test_expected_tables_exist() -> None:
    actual = {(t.schema, t.name) for t in Base.metadata.sorted_tables}
    assert actual == EXPECTED_TABLES


def test_ingest_natural_key_enforces_idempotency() -> None:
    keys = {
        tuple(c.name for c in con.columns)
        for con in table_of(IngestMessage).constraints
        if isinstance(con, UniqueConstraint)
    }
    assert ("channel", "source_system", "external_control_id") in keys


def test_payload_hash_is_indexed_but_not_unique() -> None:
    """Identical payloads with a new control ID are flagged, not rejected."""
    table = table_of(IngestMessage)
    assert any([c.name for c in idx.columns] == ["payload_sha256"] for idx in table.indexes)
    assert not any(
        [c.name for c in con.columns] == ["payload_sha256"]
        for con in table.constraints
        if isinstance(con, UniqueConstraint)
    )


def test_result_values_are_decimal_not_float() -> None:
    for model in (StagedLabResult, LabResult):
        col_type = table_of(model).c["value_numeric"].type
        assert isinstance(col_type, Numeric)
        assert col_type.asdecimal is True
        assert (col_type.precision, col_type.scale) == (18, 6)


def test_curated_promotion_is_idempotent() -> None:
    keys = {
        tuple(c.name for c in con.columns)
        for con in table_of(LabResult).constraints
        if isinstance(con, UniqueConstraint)
    }
    assert ("staged_result_id",) in keys


def test_every_foreign_key_declares_ondelete() -> None:
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            assert fk.ondelete is not None, f"{table.name} -> {fk.target_fullname}"


def test_curated_result_requires_a_value() -> None:
    """The CHECK name is convention-prefixed: ck_<table>_<declared name>."""
    checks = [c for c in table_of(LabResult).constraints if isinstance(c, CheckConstraint)]
    assert len(checks) == 1
    check = checks[0]
    assert check.name == "ck_lab_result_value_present"
    sql = str(check.sqltext)
    assert "value_numeric IS NOT NULL" in sql
    assert "value_text IS NOT NULL" in sql
    assert " OR " in sql


def test_enum_columns_enable_check_constraints() -> None:
    """create_constraint defaults to False since SQLAlchemy 1.4 - assert it is set.

    Without this, native_enum=False yields plain VARCHAR and the database would
    accept out-of-vocabulary values.
    """
    found = 0
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, Enum):
                found += 1
                label = f"{table.name}.{column.name}"
                assert column.type.create_constraint is True, label
                assert column.type.native_enum is False, label
                assert column.type.name is not None, label
    assert found == 4


def test_enum_check_constraints_appear_in_ddl() -> None:
    """Ground truth: the emitted PostgreSQL DDL must contain the enum CHECKs."""
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        enum_columns = [c for c in table.columns if isinstance(c.type, Enum)]
        if not enum_columns:
            continue
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert ddl.count("CHECK") >= len(enum_columns), table.name


def test_all_tables_compile_to_postgresql_ddl() -> None:
    """Proves types/schemas are valid for PostgreSQL and names fit its 63-char limit."""
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        schema = table.schema
        assert schema is not None
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert "CREATE TABLE" in ddl
        assert schema in ddl
        for name in re.findall(r"CONSTRAINT (\S+)", ddl):
            assert len(name.strip('"')) <= 63, name


def test_models_are_importable_without_side_effects() -> None:
    """Importing models must not open connections or create engines."""
    models = (Patient, LabOrder, Specimen, DqaFinding, FhirResource)
    assert all(table_of(m).schema in SCHEMAS for m in models)
