"""initial schema: raw/stg/core/dq/fhir medallion layers

Revision ID: 0001
Revises:
Create Date: 2026-11-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateSchema, DropSchema

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ("raw", "stg", "core", "dq", "fhir")


def upgrade() -> None:
    for name in SCHEMAS:
        op.execute(CreateSchema(name))

    # --- raw ---------------------------------------------------------------
    op.create_table(
        "ingest_message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum(
                "hl7_mllp",
                "lis2a2",
                "fhir_bundle",
                name="ingest_channel",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("external_control_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("transport_meta", postgresql.JSONB(), nullable=False),
        sa.Column(
            "ingest_status",
            sa.Enum(
                "landed",
                "parsed",
                "parse_failed",
                name="ingest_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("byte_length >= 0", name="ck_ingest_message_byte_length_non_negative"),
        sa.CheckConstraint(
            "length(payload_sha256) = 64", name="ck_ingest_message_payload_sha256_length"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_message"),
        sa.UniqueConstraint(
            "channel", "source_system", "external_control_id", name="uq_ingest_message_natural_key"
        ),
        schema="raw",
    )
    op.create_index(
        "ix_ingest_message_payload_sha256",
        "ingest_message",
        ["payload_sha256"],
        unique=False,
        schema="raw",
    )

    # --- stg ---------------------------------------------------------------
    op.create_table(
        "lab_result",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("raw_message_id", sa.Uuid(), nullable=False),
        sa.Column("source_locator", sa.String(length=32), nullable=False),
        sa.Column("patient_identifier", sa.String(length=64), nullable=False),
        sa.Column("patient_assigning_authority", sa.String(length=64), nullable=True),
        sa.Column("patient_family_name", sa.String(length=128), nullable=True),
        sa.Column("patient_given_name", sa.String(length=128), nullable=True),
        sa.Column("patient_birth_date", sa.Date(), nullable=True),
        sa.Column("patient_sex", sa.String(length=1), nullable=True),
        sa.Column("placer_order_id", sa.String(length=64), nullable=True),
        sa.Column("filler_order_id", sa.String(length=64), nullable=True),
        sa.Column("specimen_identifier", sa.String(length=64), nullable=True),
        sa.Column("specimen_type_code", sa.String(length=32), nullable=True),
        sa.Column("test_code", sa.String(length=32), nullable=False),
        sa.Column("test_code_system", sa.String(length=64), nullable=False),
        sa.Column("test_display", sa.String(length=128), nullable=True),
        sa.Column("value_numeric", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit_code", sa.String(length=32), nullable=True),
        sa.Column("reference_range_text", sa.String(length=64), nullable=True),
        sa.Column("abnormal_flag", sa.String(length=8), nullable=True),
        sa.Column("result_status", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "dqa_disposition",
            sa.Enum(
                "pending",
                "passed",
                "quarantined",
                name="dqa_disposition",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw.ingest_message.id"],
            name="fk_lab_result_raw_message_id_ingest_message",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lab_result"),
        sa.UniqueConstraint("raw_message_id", "source_locator", name="uq_stg_lab_result_locator"),
        schema="stg",
    )
    op.create_index(
        "ix_stg_lab_result_patient_identifier",
        "lab_result",
        ["patient_identifier"],
        unique=False,
        schema="stg",
    )

    # --- core --------------------------------------------------------------
    op.create_table(
        "patient",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identifier_system", sa.String(length=128), nullable=False),
        sa.Column("identifier_value", sa.String(length=64), nullable=False),
        sa.Column("family_name", sa.String(length=128), nullable=True),
        sa.Column("given_name", sa.String(length=128), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sex", sa.String(length=1), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_patient"),
        sa.UniqueConstraint("identifier_system", "identifier_value", name="uq_patient_identifier"),
        schema="core",
    )

    op.create_table(
        "lab_order",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("placer_order_id", sa.String(length=64), nullable=True),
        sa.Column("filler_order_id", sa.String(length=64), nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("panel_code", sa.String(length=32), nullable=True),
        sa.Column("panel_code_system", sa.String(length=64), nullable=True),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["core.patient.id"],
            name="fk_lab_order_patient_id_patient",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lab_order"),
        sa.UniqueConstraint("filler_order_id", "source_system", name="uq_lab_order_filler"),
        schema="core",
    )

    op.create_table(
        "specimen",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lab_order_id", sa.Uuid(), nullable=False),
        sa.Column("specimen_identifier", sa.String(length=64), nullable=False),
        sa.Column("type_code", sa.String(length=32), nullable=True),
        sa.Column("type_code_system", sa.String(length=64), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lab_order_id"],
            ["core.lab_order.id"],
            name="fk_specimen_lab_order_id_lab_order",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_specimen"),
        sa.UniqueConstraint("lab_order_id", "specimen_identifier", name="uq_specimen_per_order"),
        schema="core",
    )

    op.create_table(
        "lab_result",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("staged_result_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("lab_order_id", sa.Uuid(), nullable=False),
        sa.Column("specimen_id", sa.Uuid(), nullable=True),
        sa.Column("test_code", sa.String(length=32), nullable=False),
        sa.Column("test_code_system", sa.String(length=64), nullable=False),
        sa.Column("test_display", sa.String(length=128), nullable=True),
        sa.Column("value_numeric", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit_code", sa.String(length=32), nullable=True),
        sa.Column("unit_system", sa.String(length=64), nullable=True),
        sa.Column("reference_low", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("reference_high", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("abnormal_flag", sa.String(length=8), nullable=True),
        sa.Column("result_status", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "value_numeric IS NOT NULL OR value_text IS NOT NULL",
            name="ck_lab_result_value_present",
        ),
        sa.ForeignKeyConstraint(
            ["staged_result_id"],
            ["stg.lab_result.id"],
            name="fk_lab_result_staged_result_id_lab_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["core.patient.id"],
            name="fk_lab_result_patient_id_patient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lab_order_id"],
            ["core.lab_order.id"],
            name="fk_lab_result_lab_order_id_lab_order",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["specimen_id"],
            ["core.specimen.id"],
            name="fk_lab_result_specimen_id_specimen",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lab_result"),
        sa.UniqueConstraint("staged_result_id", name="uq_core_lab_result_staged"),
        schema="core",
    )
    op.create_index(
        "ix_core_lab_result_patient_observed",
        "lab_result",
        ["patient_id", "observed_at"],
        unique=False,
        schema="core",
    )

    # --- dq ----------------------------------------------------------------
    op.create_table(
        "finding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("raw_message_id", sa.Uuid(), nullable=False),
        sa.Column("staged_result_id", sa.Uuid(), nullable=True),
        sa.Column("rule_code", sa.String(length=32), nullable=False),
        sa.Column("rule_title", sa.String(length=128), nullable=False),
        sa.Column("dama_dimension", sa.String(length=32), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "warning",
                "error",
                name="dq_severity",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("field_name", sa.String(length=64), nullable=True),
        sa.Column("observed_value", sa.String(length=256), nullable=True),
        sa.Column("detail", sa.String(length=512), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw.ingest_message.id"],
            name="fk_finding_raw_message_id_ingest_message",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["staged_result_id"],
            ["stg.lab_result.id"],
            name="fk_finding_staged_result_id_lab_result",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_finding"),
        schema="dq",
    )
    op.create_index(
        "ix_dq_finding_staged_result_id", "finding", ["staged_result_id"], unique=False, schema="dq"
    )
    op.create_index("ix_dq_finding_rule_code", "finding", ["rule_code"], unique=False, schema="dq")

    # --- fhir --------------------------------------------------------------
    op.create_table(
        "resource",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("logical_id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=16), nullable=False),
        sa.Column("core_lab_result_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_declared", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["core_lab_result_id"],
            ["core.lab_result.id"],
            name="fk_resource_core_lab_result_id_lab_result",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resource"),
        sa.UniqueConstraint(
            "resource_type", "logical_id", "version_id", name="uq_fhir_resource_version"
        ),
        schema="fhir",
    )
    op.create_index(
        "ix_fhir_resource_core_lab_result_id",
        "resource",
        ["core_lab_result_id"],
        unique=False,
        schema="fhir",
    )


def downgrade() -> None:
    for table, schema in (
        ("resource", "fhir"),
        ("finding", "dq"),
        ("lab_result", "core"),
        ("specimen", "core"),
        ("lab_order", "core"),
        ("patient", "core"),
        ("lab_result", "stg"),
        ("ingest_message", "raw"),
    ):
        op.drop_table(table, schema=schema)
    for name in reversed(SCHEMAS):
        op.execute(DropSchema(name, cascade=True))
