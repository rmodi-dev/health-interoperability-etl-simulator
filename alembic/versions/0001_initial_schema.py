"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-27 19:45:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("CREATE SCHEMA IF NOT EXISTS stg")
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS dq")
    op.execute("CREATE SCHEMA IF NOT EXISTS fhir")

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
        sa.Column("source_system", sa.String(length=128), nullable=False),
        sa.Column("external_control_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("transport_meta", sa.JSON(), nullable=False),
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
        comment="Immutable landing records",
    )
    op.create_index(
        "ix_ingest_message_payload_sha256",
        "ingest_message",
        ["payload_sha256"],
        unique=False,
        schema="raw",
    )

    op.create_table(
        "lab_result",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("raw_message_id", sa.Uuid(), nullable=False),
        sa.Column("source_locator", sa.String(length=128), nullable=False),
        sa.Column("patient_identifier", sa.String(length=128), nullable=False),
        sa.Column("patient_assigning_authority", sa.String(length=128), nullable=True),
        sa.Column("patient_demographics", sa.JSON(), nullable=False),
        sa.Column("order_info", sa.JSON(), nullable=False),
        sa.Column("specimen_info", sa.JSON(), nullable=False),
        sa.Column("test_code", sa.String(length=64), nullable=False),
        sa.Column("test_code_system", sa.String(length=128), nullable=False),
        sa.Column("test_display", sa.String(length=256), nullable=True),
        sa.Column("value_numeric", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit_code", sa.String(length=64), nullable=True),
        sa.Column("unit_system", sa.String(length=128), nullable=True),
        sa.Column("reference_range_text", sa.String(length=256), nullable=True),
        sa.Column("abnormal_flag", sa.String(length=16), nullable=True),
        sa.Column("result_status", sa.String(length=32), nullable=False),
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
        sa.UniqueConstraint(
            "raw_message_id", "source_locator", name="uq_lab_result_source_locator"
        ),
        schema="stg",
        comment="Parsed observations awaiting quality gating",
    )
    op.create_index(
        "ix_lab_result_patient_identifier",
        "lab_result",
        ["patient_identifier"],
        unique=False,
        schema="stg",
    )
    op.create_index(
        "ix_lab_result_dqa_disposition",
        "lab_result",
        ["dqa_disposition"],
        unique=False,
        schema="stg",
    )

    op.create_table(
        "patient",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identifier_system", sa.String(length=128), nullable=False),
        sa.Column("identifier_value", sa.String(length=128), nullable=False),
        sa.Column("family_name", sa.String(length=128), nullable=True),
        sa.Column("given_name", sa.String(length=128), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_patient"),
        sa.UniqueConstraint("identifier_system", "identifier_value", name="uq_patient_identifier"),
        schema="core",
        comment="Curated patient demographics",
    )

    op.create_table(
        "lab_order",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filler_order_id", sa.String(length=128), nullable=False),
        sa.Column("placer_order_id", sa.String(length=128), nullable=True),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("ordering_facility", sa.String(length=256), nullable=True),
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
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lab_order"),
        sa.UniqueConstraint("filler_order_id", name="uq_lab_order_filler_id"),
        schema="core",
        comment="Curated lab orders",
    )
    op.create_index(
        "ix_lab_order_patient_id", "lab_order", ["patient_id"], unique=False, schema="core"
    )

    op.create_table(
        "specimen",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lab_order_id", sa.Uuid(), nullable=False),
        sa.Column("specimen_identifier", sa.String(length=128), nullable=False),
        sa.Column("specimen_type", sa.String(length=128), nullable=True),
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
        sa.UniqueConstraint("lab_order_id", "specimen_identifier", name="uq_specimen_identifier"),
        schema="core",
        comment="Curated specimens",
    )

    op.create_table(
        "lab_result",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("staged_result_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("lab_order_id", sa.Uuid(), nullable=False),
        sa.Column("specimen_id", sa.Uuid(), nullable=True),
        sa.Column("test_code", sa.String(length=64), nullable=False),
        sa.Column("test_code_system", sa.String(length=128), nullable=False),
        sa.Column("test_display", sa.String(length=256), nullable=True),
        sa.Column("value_numeric", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit_code", sa.String(length=64), nullable=True),
        sa.Column("unit_system", sa.String(length=128), nullable=True),
        sa.Column("reference_range_low", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("reference_range_high", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("reference_range_text", sa.String(length=256), nullable=True),
        sa.Column("abnormal_flag", sa.String(length=16), nullable=True),
        sa.Column("result_status", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
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
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["core.patient.id"],
            name="fk_lab_result_patient_id_patient",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lab_order_id"],
            ["core.lab_order.id"],
            name="fk_lab_result_lab_order_id_lab_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["specimen_id"],
            ["core.specimen.id"],
            name="fk_lab_result_specimen_id_specimen",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lab_result"),
        sa.UniqueConstraint("staged_result_id", name="uq_lab_result_staged_id"),
        schema="core",
        comment="Quality-gated lab results",
    )
    op.create_index(
        "ix_lab_result_patient_test",
        "lab_result",
        ["patient_id", "test_code"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "finding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("staged_result_id", sa.Uuid(), nullable=False),
        sa.Column("rule_code", sa.String(length=64), nullable=False),
        sa.Column("rule_title", sa.String(length=256), nullable=False),
        sa.Column("dama_dimension", sa.String(length=64), nullable=False),
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
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("field_path", sa.String(length=256), nullable=True),
        sa.Column("observed_value", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["staged_result_id"],
            ["stg.lab_result.id"],
            name="fk_finding_staged_result_id_lab_result",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_finding"),
        schema="dq",
        comment="Data quality findings and quarantine reasons",
    )
    op.create_index(
        "ix_finding_staged_result_id", "finding", ["staged_result_id"], unique=False, schema="dq"
    )
    op.create_index("ix_finding_rule_code", "finding", ["rule_code"], unique=False, schema="dq")

    op.create_table(
        "resource",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("logical_id", sa.String(length=128), nullable=False),
        sa.Column("version_id", sa.String(length=32), nullable=False),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("core_lab_result_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_url", sa.String(length=512), nullable=True),
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
            "resource_type", "logical_id", "version_id", name="uq_resource_identity"
        ),
        schema="fhir",
        comment="Projected FHIR R4B resources",
    )
    op.create_index(
        "ix_resource_core_lab_result_id",
        "resource",
        ["core_lab_result_id"],
        unique=False,
        schema="fhir",
    )
    op.create_index(
        "ix_resource_type_logical_id",
        "resource",
        ["resource_type", "logical_id"],
        unique=False,
        schema="fhir",
    )


def downgrade() -> None:
    op.drop_table("resource", schema="fhir")
    op.drop_table("finding", schema="dq")
    op.drop_table("lab_result", schema="core")
    op.drop_table("specimen", schema="core")
    op.drop_table("lab_order", schema="core")
    op.drop_table("patient", schema="core")
    op.drop_table("lab_result", schema="stg")
    op.drop_table("ingest_message", schema="raw")
    op.execute("DROP SCHEMA IF EXISTS fhir CASCADE")
    op.execute("DROP SCHEMA IF EXISTS dq CASCADE")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
    op.execute("DROP SCHEMA IF EXISTS stg CASCADE")
    op.execute("DROP SCHEMA IF EXISTS raw CASCADE")
