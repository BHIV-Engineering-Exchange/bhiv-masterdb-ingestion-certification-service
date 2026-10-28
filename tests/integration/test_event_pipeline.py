"""
Integration tests for Event Pipeline and Replay Orchestrator (T-GOV-002).
"""
import pytest

from models import PackageStatus
from models_pravah import (
    PipelineExecutionRequest,
    PravahEvent,
    PravahEventType,
    ReplayRequest,
)
from scripts.verify_deterministic_state import run_deterministic_verification
from services.crypto_audit_emitter import CryptoAuditEmitter
from services.event_pipeline import EventPipeline
from services.pravah_ledger import PravahReplayLedger
from services.state_machine import PravahStateMachine


@pytest.fixture
def pipeline():
    return EventPipeline(
        ledger=PravahReplayLedger(),
        state_machine=PravahStateMachine(),
        audit_emitter=CryptoAuditEmitter(),
    )


@pytest.mark.asyncio
async def test_end_to_end_single_event_processing(pipeline):
    event = PravahEvent(
        event_id="e2e-evt-01",
        topic="pravah.masterdb.events",
        event_type=PravahEventType.INGESTION_REQUESTED,
        entity_id="pkg-e2e-01",
        target_status=PackageStatus.INGESTED,
        payload={"source_verified": True},
    )

    entry, state = await pipeline.process_event(event)

    assert entry.status.value == "COMMITTED"
    assert entry.sequence_number == 1
    assert entry.state_hash_after is not None
    assert state.current_status == PackageStatus.INGESTED

    # Verify audit emitter captured the commit
    chain = pipeline.audit_emitter.get_chain()
    assert len(chain) >= 1
    assert chain[-1].event_type == "pravah_event_committed"
    assert chain[-1].payload["event_id"] == "e2e-evt-01"


@pytest.mark.asyncio
async def test_multi_step_pipeline_execution(pipeline):
    req = PipelineExecutionRequest(
        entity_id="pkg-e2e-multi",
        initial_status=PackageStatus.REGISTERED,
        target_status=PackageStatus.CERTIFIED,
        context={
            "source_verified": True,
            "schema_integrity": 0.95,
            "compliance_verified": True,
            "certification_score": 88.0,
        },
    )

    resp = await pipeline.execute_pipeline(req)

    assert resp.success is True
    assert resp.final_status == PackageStatus.CERTIFIED
    assert len(resp.transitions) == 4  # REGISTERED -> INGESTED -> VALIDATED -> VERIFIED -> CERTIFIED
    assert resp.state_hash is not None
    assert resp.ledger_sequence_end >= 4


@pytest.mark.asyncio
async def test_replay_ledger_idempotency(pipeline):
    # Process initial events
    e1 = PravahEvent(
        event_id="e2e-rep-01",
        event_type=PravahEventType.INGESTION_REQUESTED,
        entity_id="pkg-rep-01",
        target_status=PackageStatus.INGESTED,
        payload={"source_verified": True},
    )
    e2 = PravahEvent(
        event_id="e2e-rep-02",
        event_type=PravahEventType.VALIDATION_COMPLETED,
        entity_id="pkg-rep-01",
        target_status=PackageStatus.VALIDATED,
        payload={"schema_integrity": 0.9},
    )
    await pipeline.process_event(e1)
    await pipeline.process_event(e2)

    initial_hash = pipeline.state_machine.get_state("pkg-rep-01").compute_state_hash()

    # Replay all events
    replay_resp = await pipeline.replay_ledger(
        ReplayRequest(entity_id="pkg-rep-01", from_sequence=1)
    )

    assert replay_resp.replayed_count == 0  # Already applied
    assert replay_resp.skipped_duplicate_count == 2
    assert replay_resp.state_hash == initial_hash


@pytest.mark.asyncio
async def test_deterministic_50_run_verification():
    result = await run_deterministic_verification(runs=50, entity_id="pkg-integ-det")
    assert result["runs_completed"] == 50
    assert result["identical_hashes"] is True
    assert result["unique_hash_count"] == 1
    assert result["status"] == "PASS"
