"""SQLAlchemy 2.0 models for the interoperability pipeline.

All data handled by this project is SYNTHETIC. No real patient data.

Design notes:
* Result values use Numeric(18, 6) -> decimal.Decimal. Never float: FHIR decimal
  is base-10 arbitrary precision, and binary rounding of a lab result is a defect.
* Enumerations are VARCHAR + CHECK (native_enum=False, create_constraint=True) so
  vocabularies evolve without ALTER TYPE migrations, while PostgreSQL still
  rejects out-of-vocabulary values. create_constraint must be set explicitly:
  it defaults to False since SQLAlchemy 1.4.
* Table comments are intentionally NOT used: op.create_table(comment=) proved
  unreliable across Alembic releases and caused autogenerate drift. Table purpose
  is documented in each class docstring instead.
* No ORM relationship() definitions: pipeline code uses explicit joins to avoid
  lazy-load N+1 queries and implicit I/O.
* raw.payload is TEXT; PostgreSQL cannot store 0x00, so transport layers must
  strip framing control characters before landing a message.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from health_interop.db.base import Base

CHANNELS = ("hl7_mllp", "lis2a2", "fhir_bundle")
INGEST_STATUSES = ("landed", "parsed", "parse_failed")
DQA_DISPOSITIONS = ("pending", "passed", "quarantined")
SEVERITIES = ("info", "warning", "error")

LOINC_SYSTEM = "http://loinc.org"
UCUM_SYSTEM = "http://unitsofmeasure.org"


class IngestMessage(Base):
    """raw: immutable landing record, one row per inbound message."""

    __tablename__ = "ingest_message"
    __table_args__ = (
        UniqueConstraint(
            "channel",
            "source_system",
            "external_control_id",
            name="uq_ingest_message_natural_key",
        ),
        CheckConstraint("byte_length >= 0", name="byte_length_non_negative"),
        CheckConstraint("length(payload_sha256) = 64", name="payload_sha256_length"),
        Index("ix_ingest_message_payload_sha256", "payload_sha256"),
        {"schema": "raw"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(
        Enum(
            *CHANNELS,
            name="ingest_channel",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    external_control_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    transport_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingest_status: Mapped[str] = mapped_column(
        Enum(
            *INGEST_STATUSES,
            name="ingest_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
        default="landed",
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StagedLabResult(Base):
    """stg: one normalised observation, with provenance back to the raw message."""

    __tablename__ = "lab_result"
    __table_args__ = (
        UniqueConstraint("raw_message_id", "source_locator", name="uq_stg_lab_result_locator"),
        Index("ix_stg_lab_result_patient_identifier", "patient_identifier"),
        {"schema": "stg"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    raw_message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("raw.ingest_message.id", ondelete="CASCADE"), nullable=False
    )
    source_locator: Mapped[str] = mapped_column(String(32), nullable=False)

    patient_identifier: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_assigning_authority: Mapped[str | None] = mapped_column(String(64))
    patient_family_name: Mapped[str | None] = mapped_column(String(128))
    patient_given_name: Mapped[str | None] = mapped_column(String(128))
    patient_birth_date: Mapped[date | None] = mapped_column(Date)
    patient_sex: Mapped[str | None] = mapped_column(String(1))

    placer_order_id: Mapped[str | None] = mapped_column(String(64))
    filler_order_id: Mapped[str | None] = mapped_column(String(64))
    specimen_identifier: Mapped[str | None] = mapped_column(String(64))
    specimen_type_code: Mapped[str | None] = mapped_column(String(32))

    test_code: Mapped[str] = mapped_column(String(32), nullable=False)
    test_code_system: Mapped[str] = mapped_column(String(64), nullable=False, default=LOINC_SYSTEM)
    test_display: Mapped[str | None] = mapped_column(String(128))

    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    value_text: Mapped[str | None] = mapped_column(Text)
    unit_code: Mapped[str | None] = mapped_column(String(32))
    reference_range_text: Mapped[str | None] = mapped_column(String(64))
    abnormal_flag: Mapped[str | None] = mapped_column(String(8))
    result_status: Mapped[str] = mapped_column(String(16), nullable=False)

    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dqa_disposition: Mapped[str] = mapped_column(
        Enum(
            *DQA_DISPOSITIONS,
            name="dqa_disposition",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
        default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Patient(Base):
    """core: curated patient identity, keyed by assigning authority + identifier."""

    __tablename__ = "patient"
    __table_args__ = (
        UniqueConstraint("identifier_system", "identifier_value", name="uq_patient_identifier"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    identifier_system: Mapped[str] = mapped_column(String(128), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(64), nullable=False)
    family_name: Mapped[str | None] = mapped_column(String(128))
    given_name: Mapped[str | None] = mapped_column(String(128))
    birth_date: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(1))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LabOrder(Base):
    """core: curated order, identified by filler order number + source system."""

    __tablename__ = "lab_order"
    __table_args__ = (
        UniqueConstraint("filler_order_id", "source_system", name="uq_lab_order_filler"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core.patient.id", ondelete="RESTRICT"), nullable=False
    )
    placer_order_id: Mapped[str | None] = mapped_column(String(64))
    filler_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    panel_code: Mapped[str | None] = mapped_column(String(32))
    panel_code_system: Mapped[str | None] = mapped_column(String(64))
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Specimen(Base):
    """core: curated specimen belonging to an order."""

    __tablename__ = "specimen"
    __table_args__ = (
        UniqueConstraint("lab_order_id", "specimen_identifier", name="uq_specimen_per_order"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    lab_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core.lab_order.id", ondelete="CASCADE"), nullable=False
    )
    specimen_identifier: Mapped[str] = mapped_column(String(64), nullable=False)
    type_code: Mapped[str | None] = mapped_column(String(32))
    type_code_system: Mapped[str | None] = mapped_column(String(64))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LabResult(Base):
    """core: curated result that passed data-quality gating.

    staged_result_id is UNIQUE so promotion is idempotent: re-running the
    pipeline cannot create a second curated row for the same observation.
    """

    __tablename__ = "lab_result"
    __table_args__ = (
        UniqueConstraint("staged_result_id", name="uq_core_lab_result_staged"),
        CheckConstraint(
            "value_numeric IS NOT NULL OR value_text IS NOT NULL", name="value_present"
        ),
        Index("ix_core_lab_result_patient_observed", "patient_id", "observed_at"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    staged_result_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stg.lab_result.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core.patient.id", ondelete="RESTRICT"), nullable=False
    )
    lab_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core.lab_order.id", ondelete="RESTRICT"), nullable=False
    )
    specimen_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.specimen.id", ondelete="RESTRICT")
    )

    test_code: Mapped[str] = mapped_column(String(32), nullable=False)
    test_code_system: Mapped[str] = mapped_column(String(64), nullable=False, default=LOINC_SYSTEM)
    test_display: Mapped[str | None] = mapped_column(String(128))

    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    value_text: Mapped[str | None] = mapped_column(Text)
    unit_code: Mapped[str | None] = mapped_column(String(32))
    unit_system: Mapped[str | None] = mapped_column(String(64), default=UCUM_SYSTEM)
    reference_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    reference_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    abnormal_flag: Mapped[str | None] = mapped_column(String(8))
    result_status: Mapped[str] = mapped_column(String(16), nullable=False)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DqaFinding(Base):
    """dq: one rule violation, mapped to a DAMA-DMBOK data-quality dimension."""

    __tablename__ = "finding"
    __table_args__ = (
        Index("ix_dq_finding_staged_result_id", "staged_result_id"),
        Index("ix_dq_finding_rule_code", "rule_code"),
        {"schema": "dq"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    raw_message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("raw.ingest_message.id", ondelete="CASCADE"), nullable=False
    )
    staged_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stg.lab_result.id", ondelete="CASCADE")
    )
    rule_code: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_title: Mapped[str] = mapped_column(String(128), nullable=False)
    dama_dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(
        Enum(*SEVERITIES, name="dq_severity", native_enum=False, create_constraint=True),
        nullable=False,
    )
    field_name: Mapped[str | None] = mapped_column(String(64))
    observed_value: Mapped[str | None] = mapped_column(String(256))
    detail: Mapped[str] = mapped_column(String(512), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FhirResource(Base):
    """fhir: projected R4B resource, versioned and traceable to a curated result.

    profile_declared records the honest claim: an AU Core-inspired subset,
    not AU Core conformance (AU Core is based on FHIR R4).
    """

    __tablename__ = "resource"
    __table_args__ = (
        UniqueConstraint(
            "resource_type", "logical_id", "version_id", name="uq_fhir_resource_version"
        ),
        Index("ix_fhir_resource_core_lab_result_id", "core_lab_result_id"),
        {"schema": "fhir"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    logical_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version_id: Mapped[str] = mapped_column(String(16), nullable=False, default="1")
    core_lab_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.lab_result.id", ondelete="SET NULL")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_declared: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
