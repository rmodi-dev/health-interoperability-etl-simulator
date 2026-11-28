"""Repository tests. All clinical values are SYNTHETIC.

Pure-function tests run anywhere. Tests marked `integration` need PostgreSQL.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from health_interop.db.models import IngestMessage, LabResult, StagedLabResult
from health_interop.db.repository import (
    StagedResultInput,
    land_message,
    parse_reference_range,
    payload_fingerprint,
    promote_staged_result,
    set_disposition,
    stage_result,
)

SYNTHETIC_PAYLOAD = "MSH|^~\\&|SYNTH_LIS|LAB|SYNTH_EMR|CLINIC|20261126080000||ORU^R01|SYN|P|2.5.1\r"


def _input(**overrides: Any) -> StagedResultInput:
    base: dict[str, Any] = {
        "source_locator": "OBX-1",
        "patient_identifier": "SYN-MRN-0001",
        "patient_assigning_authority": "SYNTH",
        "patient_family_name": "SYNTHETIC",
        "patient_given_name": "Test",
        "test_code": "718-7",
        "test_display": "Hemoglobin",
        "result_status": "final",
        "filler_order_id": "FIL-0001",
        "placer_order_id": "ORD-0001",
        "specimen_identifier": "SPEC-0001",
        "value_numeric": Decimal("13.5"),
        "unit_code": "g/dL",
        "reference_range_text": "12.0-16.0",
        "observed_at": datetime(2026, 11, 26, 7, 30, tzinfo=UTC),
    }
    base.update(overrides)
    return StagedResultInput(**base)


def _land(
    session: Session,
    control_id: str,
    *,
    payload: str = SYNTHETIC_PAYLOAD,
    transport_meta: dict[str, Any] | None = None,
) -> IngestMessage:
    """Land one synthetic HL7 message. Explicitly typed: no **kwargs unpacking."""
    return land_message(
        session,
        channel="hl7_mllp",
        source_system="SYNTH_LIS",
        external_control_id=control_id,
        payload=payload,
        transport_meta=transport_meta,
    ).message


def _land_and_stage(session: Session, control_id: str, **overrides: Any) -> StagedLabResult:
    message = _land(session, control_id)
    return stage_result(session, message.id, _input(**overrides)).staged


# --- pure functions (no database) -------------------------------------------


def test_payload_fingerprint_is_stable() -> None:
    first, size = payload_fingerprint(SYNTHETIC_PAYLOAD)
    second, _ = payload_fingerprint(SYNTHETIC_PAYLOAD)
    assert first == second
    assert len(first) == 64
    assert size == len(SYNTHETIC_PAYLOAD.encode("utf-8"))


def test_payload_fingerprint_rejects_nul() -> None:
    with pytest.raises(ValueError, match="NUL"):
        payload_fingerprint("MSH|^~\\&\x00")


def test_parse_reference_range_valid() -> None:
    low, high = parse_reference_range("12.0-16.0")
    assert low == Decimal("12.0")
    assert high == Decimal("16.0")


def test_parse_reference_range_unparseable() -> None:
    for value in (None, "", "<5", "12.0", "abc-def"):
        assert parse_reference_range(value) == (None, None)


def test_parse_reference_range_rejects_inverted() -> None:
    assert parse_reference_range("16.0-12.0") == (None, None)


# --- integration ------------------------------------------------------------


@pytest.mark.integration
def test_land_message_is_idempotent(db_session: Session) -> None:
    first = land_message(
        db_session,
        channel="hl7_mllp",
        source_system="SYNTH_LIS",
        external_control_id="CTRL-1",
        payload=SYNTHETIC_PAYLOAD,
    )
    second = land_message(
        db_session,
        channel="hl7_mllp",
        source_system="SYNTH_LIS",
        external_control_id="CTRL-1",
        payload=SYNTHETIC_PAYLOAD,
    )
    assert first.created is True
    assert second.created is False
    assert first.message.id == second.message.id


@pytest.mark.integration
def test_same_payload_new_control_id_is_kept(db_session: Session) -> None:
    """A clinically real repeat send is flagged by hash, not rejected."""
    a = _land(db_session, "CTRL-A")
    b = _land(db_session, "CTRL-B")
    assert a.id != b.id
    assert a.payload_sha256 == b.payload_sha256
    count = (
        db_session.execute(
            select(IngestMessage).where(IngestMessage.payload_sha256 == a.payload_sha256)
        )
        .scalars()
        .all()
    )
    assert len(count) == 2


@pytest.mark.integration
def test_stage_result_is_idempotent(db_session: Session) -> None:
    message = _land(db_session, "CTRL-2")
    first = stage_result(db_session, message.id, _input())
    second = stage_result(db_session, message.id, _input())
    assert first.created is True
    assert second.created is False
    assert first.staged.id == second.staged.id


@pytest.mark.integration
def test_promotion_requires_passed_disposition(db_session: Session) -> None:
    staged = _land_and_stage(db_session, "CTRL-3")
    assert staged.dqa_disposition == "pending"
    with pytest.raises(ValueError, match="only 'passed'"):
        promote_staged_result(db_session, staged.id)


@pytest.mark.integration
def test_promotion_requires_order_and_observed_at(db_session: Session) -> None:
    staged = _land_and_stage(db_session, "CTRL-4", filler_order_id=None)
    set_disposition(db_session, staged.id, "passed")
    with pytest.raises(ValueError, match="filler_order_id"):
        promote_staged_result(db_session, staged.id)


@pytest.mark.integration
def test_promotion_is_idempotent_and_links_lineage(db_session: Session) -> None:
    staged = _land_and_stage(db_session, "CTRL-5")
    set_disposition(db_session, staged.id, "passed")

    first = promote_staged_result(db_session, staged.id)
    second = promote_staged_result(db_session, staged.id)
    assert first.created is True
    assert second.created is False
    assert first.result.id == second.result.id

    row = db_session.execute(
        select(LabResult, StagedLabResult, IngestMessage)
        .join(StagedLabResult, LabResult.staged_result_id == StagedLabResult.id)
        .join(IngestMessage, StagedLabResult.raw_message_id == IngestMessage.id)
        .where(LabResult.id == first.result.id)
    ).one()
    assert row[2].external_control_id == "CTRL-5"
    assert first.result.reference_low == Decimal("12.0")
    assert first.result.reference_high == Decimal("16.0")
    assert first.result.unit_system == "http://unitsofmeasure.org"


@pytest.mark.integration
def test_decimal_precision_survives_round_trip(db_session: Session) -> None:
    staged = _land_and_stage(db_session, "CTRL-6", value_numeric=Decimal("0.1"))
    db_session.flush()
    db_session.refresh(staged)
    assert isinstance(staged.value_numeric, Decimal)
    assert staged.value_numeric == Decimal("0.1")


@pytest.mark.integration
def test_database_rejects_out_of_vocabulary_enum(db_session: Session) -> None:
    """Proves create_constraint=True: the CHECK lives in PostgreSQL, not just Python.

    Raw SQL is used deliberately - SQLAlchemy's Enum would raise LookupError in
    Python before the value ever reached the database, hiding the DB-level guard.
    The invalid value is intentionally shorter than the longest valid enum value
    (parse_failed = 12 chars) so it passes the VARCHAR type check and is caught
    by the CHECK constraint -> IntegrityError, which is the proof the constraint
    is active.
    """
    message = _land(db_session, "CTRL-7")
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            text("update raw.ingest_message set ingest_status = :bad where id = :id"),
            {"bad": "bad", "id": message.id},
        )


@pytest.mark.integration
def test_unknown_staged_id_raises_lookup(db_session: Session) -> None:
    with pytest.raises(LookupError):
        promote_staged_result(db_session, uuid.uuid4())
