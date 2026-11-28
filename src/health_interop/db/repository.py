"""Idempotent persistence: land -> stage -> promote.

Transaction policy: these functions NEVER commit. The caller owns the boundary.

Idempotency is enforced by the database, not by read-then-write checks: each
insert uses ON CONFLICT DO NOTHING against a natural key and then reads back the
existing row. That is race-safe under concurrent ingest.

All data is SYNTHETIC.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from health_interop.db.models import (
    LOINC_SYSTEM,
    UCUM_SYSTEM,
    IngestMessage,
    LabOrder,
    LabResult,
    Patient,
    Specimen,
    StagedLabResult,
)

DEFAULT_IDENTIFIER_SYSTEM = "urn:health-interop:synthetic:mrn"


@dataclass(frozen=True, slots=True)
class LandingResult:
    message: IngestMessage
    created: bool


@dataclass(frozen=True, slots=True)
class StagingResult:
    staged: StagedLabResult
    created: bool


@dataclass(frozen=True, slots=True)
class PromotionResult:
    result: LabResult
    created: bool


@dataclass(frozen=True, slots=True)
class StagedResultInput:
    """Normalised observation produced by a parser (Stages 3, 4, 6)."""

    source_locator: str
    patient_identifier: str
    test_code: str
    result_status: str
    test_code_system: str = LOINC_SYSTEM
    patient_assigning_authority: str | None = None
    patient_family_name: str | None = None
    patient_given_name: str | None = None
    patient_birth_date: date | None = None
    patient_sex: str | None = None
    placer_order_id: str | None = None
    filler_order_id: str | None = None
    specimen_identifier: str | None = None
    specimen_type_code: str | None = None
    test_display: str | None = None
    value_numeric: Decimal | None = None
    value_text: str | None = None
    unit_code: str | None = None
    reference_range_text: str | None = None
    abnormal_flag: str | None = None
    observed_at: datetime | None = None
    issued_at: datetime | None = None


def payload_fingerprint(payload: str) -> tuple[str, int]:
    """Return (sha256 hex, byte length). Rejects NUL, which PostgreSQL TEXT cannot store."""
    if "\x00" in payload:
        raise ValueError(
            "payload contains NUL (0x00). Strip MLLP/LIS2-A2 framing characters before landing."
        )
    raw = payload.encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), len(raw)


def parse_reference_range(text: str | None) -> tuple[Decimal | None, Decimal | None]:
    """Parse a 'low-high' reference range into exact Decimals.

    Deliberately narrow: handles the '12.0-16.0' shape our synthetic generator
    emits. Negative bounds and '<x' / '>x' forms are NOT supported and are
    reported as unparseable rather than guessed at.
    """
    if not text:
        return (None, None)
    parts = text.strip().split("-")
    if len(parts) != 2:
        return (None, None)
    try:
        low = Decimal(parts[0].strip())
        high = Decimal(parts[1].strip())
    except InvalidOperation:
        return (None, None)
    if low > high:
        return (None, None)
    return (low, high)


def land_message(
    session: Session,
    *,
    channel: str,
    source_system: str,
    external_control_id: str,
    payload: str,
    transport_meta: dict[str, Any] | None = None,
) -> LandingResult:
    """raw: land one message. Re-delivery of the same natural key is a no-op."""
    digest, byte_length = payload_fingerprint(payload)
    stmt = (
        pg_insert(IngestMessage)
        .values(
            id=uuid.uuid4(),
            channel=channel,
            source_system=source_system,
            external_control_id=external_control_id,
            payload=payload,
            payload_sha256=digest,
            byte_length=byte_length,
            transport_meta=transport_meta or {},
            ingest_status="landed",
        )
        .on_conflict_do_nothing(index_elements=["channel", "source_system", "external_control_id"])
        .returning(IngestMessage.id)
    )
    new_id: uuid.UUID | None = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        created = session.get(IngestMessage, new_id)
        assert created is not None
        return LandingResult(message=created, created=True)

    existing = session.execute(
        select(IngestMessage).where(
            IngestMessage.channel == channel,
            IngestMessage.source_system == source_system,
            IngestMessage.external_control_id == external_control_id,
        )
    ).scalar_one()
    return LandingResult(message=existing, created=False)


def stage_result(
    session: Session, raw_message_id: uuid.UUID, data: StagedResultInput
) -> StagingResult:
    """stg: one normalised observation, unique per (raw message, source locator)."""
    stmt = (
        pg_insert(StagedLabResult)
        .values(id=uuid.uuid4(), raw_message_id=raw_message_id, **asdict(data))
        .on_conflict_do_nothing(index_elements=["raw_message_id", "source_locator"])
        .returning(StagedLabResult.id)
    )
    new_id: uuid.UUID | None = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        created = session.get(StagedLabResult, new_id)
        assert created is not None
        return StagingResult(staged=created, created=True)

    existing = session.execute(
        select(StagedLabResult).where(
            StagedLabResult.raw_message_id == raw_message_id,
            StagedLabResult.source_locator == data.source_locator,
        )
    ).scalar_one()
    return StagingResult(staged=existing, created=False)


def set_disposition(session: Session, staged_id: uuid.UUID, disposition: str) -> None:
    """Record the DQA verdict. Stage 5 writes this; here it is an explicit setter."""
    staged = session.get(StagedLabResult, staged_id)
    if staged is None:
        raise LookupError(f"staged result {staged_id} not found")
    staged.dqa_disposition = disposition
    session.flush()


def _upsert_patient(session: Session, staged: StagedLabResult) -> uuid.UUID:
    system = staged.patient_assigning_authority or DEFAULT_IDENTIFIER_SYSTEM
    stmt = (
        pg_insert(Patient)
        .values(
            id=uuid.uuid4(),
            identifier_system=system,
            identifier_value=staged.patient_identifier,
            family_name=staged.patient_family_name,
            given_name=staged.patient_given_name,
            birth_date=staged.patient_birth_date,
            sex=staged.patient_sex,
        )
        .on_conflict_do_nothing(index_elements=["identifier_system", "identifier_value"])
        .returning(Patient.id)
    )
    new_id: uuid.UUID | None = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        return new_id
    existing: uuid.UUID = session.execute(
        select(Patient.id).where(
            Patient.identifier_system == system,
            Patient.identifier_value == staged.patient_identifier,
        )
    ).scalar_one()
    return existing


def _upsert_order(
    session: Session, staged: StagedLabResult, patient_id: uuid.UUID, source_system: str
) -> uuid.UUID:
    assert staged.filler_order_id is not None
    stmt = (
        pg_insert(LabOrder)
        .values(
            id=uuid.uuid4(),
            patient_id=patient_id,
            placer_order_id=staged.placer_order_id,
            filler_order_id=staged.filler_order_id,
            source_system=source_system,
        )
        .on_conflict_do_nothing(index_elements=["filler_order_id", "source_system"])
        .returning(LabOrder.id)
    )
    new_id: uuid.UUID | None = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        return new_id
    existing: uuid.UUID = session.execute(
        select(LabOrder.id).where(
            LabOrder.filler_order_id == staged.filler_order_id,
            LabOrder.source_system == source_system,
        )
    ).scalar_one()
    return existing


def _upsert_specimen(
    session: Session, staged: StagedLabResult, order_id: uuid.UUID
) -> uuid.UUID | None:
    if staged.specimen_identifier is None:
        return None
    stmt = (
        pg_insert(Specimen)
        .values(
            id=uuid.uuid4(),
            lab_order_id=order_id,
            specimen_identifier=staged.specimen_identifier,
            type_code=staged.specimen_type_code,
            collected_at=staged.observed_at,
        )
        .on_conflict_do_nothing(index_elements=["lab_order_id", "specimen_identifier"])
        .returning(Specimen.id)
    )
    new_id: uuid.UUID | None = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        return new_id
    existing: uuid.UUID = session.execute(
        select(Specimen.id).where(
            Specimen.lab_order_id == order_id,
            Specimen.specimen_identifier == staged.specimen_identifier,
        )
    ).scalar_one()
    return existing


def promote_staged_result(session: Session, staged_id: uuid.UUID) -> PromotionResult:
    """core: promote a quality-passed observation. Idempotent on staged_result_id.

    Raises ValueError when the observation lacks fields the curated layer requires.
    Those requirements become explicit DQA rules in Stage 5.
    """
    staged = session.get(StagedLabResult, staged_id)
    if staged is None:
        raise LookupError(f"staged result {staged_id} not found")
    if staged.dqa_disposition != "passed":
        raise ValueError(
            f"disposition is {staged.dqa_disposition!r}; only 'passed' rows may be promoted"
        )
    if staged.filler_order_id is None:
        raise ValueError("cannot promote: filler_order_id is required for a curated order")
    if staged.observed_at is None:
        raise ValueError("cannot promote: observed_at is required for a curated result")
    if staged.value_numeric is None and staged.value_text is None:
        raise ValueError("cannot promote: result has neither a numeric nor a text value")

    raw = session.get(IngestMessage, staged.raw_message_id)
    if raw is None:
        raise LookupError(f"raw message {staged.raw_message_id} not found")

    patient_id = _upsert_patient(session, staged)
    order_id = _upsert_order(session, staged, patient_id, raw.source_system)
    specimen_id = _upsert_specimen(session, staged, order_id)
    low, high = parse_reference_range(staged.reference_range_text)

    stmt = (
        pg_insert(LabResult)
        .values(
            id=uuid.uuid4(),
            staged_result_id=staged.id,
            patient_id=patient_id,
            lab_order_id=order_id,
            specimen_id=specimen_id,
            test_code=staged.test_code,
            test_code_system=staged.test_code_system,
            test_display=staged.test_display,
            value_numeric=staged.value_numeric,
            value_text=staged.value_text,
            unit_code=staged.unit_code,
            unit_system=UCUM_SYSTEM if staged.unit_code else None,
            reference_low=low,
            reference_high=high,
            abnormal_flag=staged.abnormal_flag,
            result_status=staged.result_status,
            observed_at=staged.observed_at,
            issued_at=staged.issued_at,
        )
        .on_conflict_do_nothing(index_elements=["staged_result_id"])
        .returning(LabResult.id)
    )
    new_id: uuid.UUID | None = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        created = session.get(LabResult, new_id)
        assert created is not None
        return PromotionResult(result=created, created=True)

    existing = session.execute(
        select(LabResult).where(LabResult.staged_result_id == staged.id)
    ).scalar_one()
    return PromotionResult(result=existing, created=False)
