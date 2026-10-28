"""
Pravah Event-Driven API & Pipeline Automation Surface (T-GOV-002).

Exposes strict REST endpoints for event ingestion, Pravah replay ledger queries,
idempotent replaying, deterministic state verification, and pipeline automation.
"""
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from models import PackageStatus
from models_pravah import (
    DeterministicVerificationResult,
    PipelineExecutionRequest,
    PipelineExecutionResponse,
    PravahEvent,
    PravahEventStatus,
    PravahLedgerEntry,
    ReplayRequest,
    ReplayResponse,
)
from services.event_pipeline import EventPipeline
from services.state_machine import InvalidStateTransitionError

router = APIRouter(prefix="", tags=["pravah", "pipeline"])


def _get_pipeline(request: Request) -> EventPipeline:
    pipeline: Optional[EventPipeline] = getattr(request.app.state, "event_pipeline", None)
    if pipeline is None:
        pipeline = EventPipeline()
        request.app.state.event_pipeline = pipeline
    return pipeline


class EventIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    sequence_number: int
    event_id: str
    entity_id: str
    current_status: str
    version: int
    state_hash: str


class EntityStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    entity_type: str
    current_status: str
    version: int
    applied_events: List[str]
    metadata: Dict[str, Any]
    state_hash: str


class DeterministicRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runs: int = Field(default=50, ge=1, le=100)
    entity_id_prefix: str = Field(default="det-test-pkg", min_length=1)


@router.post("/pravah/events", response_model=EventIngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_event(
    event: PravahEvent,
    request: Request,
) -> EventIngestResponse:
    """
    Ingest a validated event into the Pravah replay ledger and execute
    state machine transition with strict concurrency control.
    """
    pipeline = _get_pipeline(request)
    try:
        entry, state = await pipeline.process_event(event)
    except InvalidStateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Event processing error: {exc}",
        ) from exc

    return EventIngestResponse(
        status=entry.status.value,
        sequence_number=entry.sequence_number,
        event_id=event.event_id,
        entity_id=event.entity_id,
        current_status=state.current_status.value,
        version=state.version,
        state_hash=state.compute_state_hash(),
    )


@router.get("/pravah/events/{event_id}", response_model=PravahLedgerEntry)
async def get_event(
    event_id: str,
    request: Request,
) -> PravahLedgerEntry:
    """Retrieve an event record from the replay ledger by event_id."""
    pipeline = _get_pipeline(request)
    entry = pipeline.ledger.get_entry_by_event_id(event_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event '{event_id}' not found in Pravah replay ledger.",
        )
    return entry


@router.get("/pravah/ledger", response_model=List[PravahLedgerEntry])
async def query_ledger(
    request: Request,
    from_sequence: int = Query(default=1, ge=1),
    to_sequence: Optional[int] = Query(default=None, ge=1),
    topic: Optional[str] = Query(default=None),
    entity_id: Optional[str] = Query(default=None),
    event_status: Optional[PravahEventStatus] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
) -> List[PravahLedgerEntry]:
    """Query entries from the append-only Pravah replay ledger."""
    pipeline = _get_pipeline(request)
    return pipeline.ledger.query_entries(
        from_sequence=from_sequence,
        to_sequence=to_sequence,
        topic=topic,
        entity_id=entity_id,
        status=event_status,
        limit=limit,
    )


@router.post("/pravah/replay", response_model=ReplayResponse)
async def replay_events(
    body: ReplayRequest,
    request: Request,
) -> ReplayResponse:
    """Replay events from the Pravah replay ledger with idempotent deduplication."""
    pipeline = _get_pipeline(request)
    return await pipeline.replay_ledger(body)


@router.get("/pravah/state/{entity_id}", response_model=EntityStateResponse)
async def get_entity_state(
    entity_id: str,
    request: Request,
) -> EntityStateResponse:
    """Retrieve canonical business state and SHA-256 state hash for an entity."""
    pipeline = _get_pipeline(request)
    state = pipeline.state_machine.get_state(entity_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' has no recorded state.",
        )
    return EntityStateResponse(
        entity_id=state.entity_id,
        entity_type=state.entity_type.value if hasattr(state.entity_type, "value") else str(state.entity_type),
        current_status=state.current_status.value,
        version=state.version,
        applied_events=state.applied_events,
        metadata=state.metadata,
        state_hash=state.compute_state_hash(),
    )


@router.post("/pravah/verify-determinism", response_model=DeterministicVerificationResult)
async def verify_determinism(
    request: Request,
    body: Optional[DeterministicRunRequest] = None,
) -> DeterministicVerificationResult:
    """
    Execute 50 consecutive runs from an identical initial logical state
    through an identical ordered event stream, computing and asserting
    100% SHA-256 state hash identity.
    """
    from scripts.verify_deterministic_state import run_deterministic_verification
    runs = body.runs if body else 50
    start = time.perf_counter()
    result = await run_deterministic_verification(runs=runs)
    duration_ms = (time.perf_counter() - start) * 1000.0

    return DeterministicVerificationResult(
        runs_completed=result["runs_completed"],
        identical_hashes=result["identical_hashes"],
        final_hash=result["final_hash"],
        hash_history=result["hash_history"],
        duration_ms=round(duration_ms, 2),
        status="PASS" if result["identical_hashes"] else "FAIL",
    )


@router.post("/pipeline/execute", response_model=PipelineExecutionResponse)
async def execute_pipeline_route(
    body: PipelineExecutionRequest,
    request: Request,
) -> PipelineExecutionResponse:
    """
    Automate pipeline progression across lifecycle states with strict concurrency
    control, Pravah replay ledger recording, and cryptographic auditing.
    """
    pipeline = _get_pipeline(request)
    try:
        return await pipeline.execute_pipeline(body)
    except InvalidStateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pipeline execution failed: {exc}",
        ) from exc
