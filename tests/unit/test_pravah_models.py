"""
Unit tests for Pravah Pydantic schemas and event validation (T-GOV-002).
"""
import pytest
from pydantic import ValidationError

from models import PackageStatus
from models_pravah import (
    DeterministicVerificationResult,
    PipelineExecutionRequest,
    PravahEntityType,
    PravahEvent,
    PravahEventStatus,
    PravahEventType,
    PravahLedgerEntry,
    ReplayRequest,
)


def test_pravah_event_valid_instantiation():
    event = PravahEvent(
        event_id="evt-101",
        topic="pravah.masterdb.events",
        event_type=PravahEventType.INGESTION_REQUESTED,
        entity_type=PravahEntityType.PACKAGE,
        entity_id="pkg-101",
        producer="test-suite",
        target_status=PackageStatus.INGESTED,
        payload={"source_verified": True},
    )
    assert event.event_id == "evt-101"
    assert event.event_type == PravahEventType.INGESTION_REQUESTED
    assert event.entity_type == PravahEntityType.PACKAGE
    assert event.payload["source_verified"] is True


def test_pravah_event_rejects_extra_fields():
    with pytest.raises(ValidationError) as exc_info:
        PravahEvent(
            event_id="evt-102",
            event_type=PravahEventType.VALIDATION_COMPLETED,
            entity_id="pkg-102",
            unexpected_field="disallowed",
        )
    assert "extra_forbidden" in str(exc_info.value)


def test_pravah_event_rejects_empty_ids():
    with pytest.raises(ValidationError):
        PravahEvent(
            event_id="",
            event_type=PravahEventType.VALIDATION_COMPLETED,
            entity_id="pkg-103",
        )

    with pytest.raises(ValidationError):
        PravahEvent(
            event_id="evt-103",
            event_type=PravahEventType.VALIDATION_COMPLETED,
            entity_id="",
        )


def test_pravah_event_rejects_invalid_enum():
    with pytest.raises(ValidationError):
        PravahEvent(
            event_id="evt-104",
            event_type="INVALID_TYPE",  # type: ignore
            entity_id="pkg-104",
        )


def test_pravah_ledger_entry_schema():
    event = PravahEvent(
        event_id="evt-105",
        event_type=PravahEventType.CERTIFICATION_GRANTED,
        entity_id="pkg-105",
    )
    entry = PravahLedgerEntry(
        sequence_number=1,
        event=event,
        status=PravahEventStatus.PENDING,
    )
    assert entry.sequence_number == 1
    assert entry.status == PravahEventStatus.PENDING
    assert entry.retry_count == 0


def test_pravah_ledger_entry_rejects_extra_fields():
    event = PravahEvent(
        event_id="evt-106",
        event_type=PravahEventType.CERTIFICATION_GRANTED,
        entity_id="pkg-106",
    )
    with pytest.raises(ValidationError):
        PravahLedgerEntry(
            sequence_number=1,
            event=event,
            status=PravahEventStatus.COMMITTED,
            rogue_field="prohibited",
        )


def test_replay_request_validation():
    req = ReplayRequest(from_sequence=5, to_sequence=10, entity_id="pkg-107")
    assert req.from_sequence == 5
    assert req.to_sequence == 10

    with pytest.raises(ValidationError):
        ReplayRequest(from_sequence=0)  # ge=1 violated


def test_pipeline_execution_request_validation():
    req = PipelineExecutionRequest(
        entity_id="pkg-108",
        initial_status=PackageStatus.REGISTERED,
        target_status=PackageStatus.CERTIFIED,
        context={"schema_integrity": 0.95},
    )
    assert req.entity_id == "pkg-108"
    assert req.target_status == PackageStatus.CERTIFIED

    with pytest.raises(ValidationError):
        PipelineExecutionRequest(
            entity_id="pkg-108",
            unauthorized_param="hacked",
        )
