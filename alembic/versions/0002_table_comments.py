"""add table comments as explicit COMMENT ON statements

0001 passed comment= to op.create_table; depending on Alembic release that
kwarg may not reach the database. This revision sets the same comments
explicitly so models and database agree under `alembic check`.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-28
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Constant table/comment pairs from our own schema - no external input,
# so string interpolation into DDL is safe here.
COMMENTS = {
    "raw.ingest_message": "Immutable landing records",
    "stg.lab_result": "Parsed observations awaiting quality gating",
    "core.patient": "Curated patient demographics",
    "core.lab_order": "Curated lab orders",
    "core.specimen": "Curated specimens",
    "core.lab_result": "Quality-gated lab results",
    "dq.finding": "Data quality findings and quarantine reasons",
    "fhir.resource": "Projected FHIR R4B resources",
}


def upgrade() -> None:
    for table, comment in COMMENTS.items():
        op.execute(f"COMMENT ON TABLE {table} IS '{comment}'")


def downgrade() -> None:
    for table in COMMENTS:
        op.execute(f"COMMENT ON TABLE {table} IS NULL")
