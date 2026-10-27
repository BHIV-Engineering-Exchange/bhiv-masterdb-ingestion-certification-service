"""
Strict Pydantic models and schemas for Pravah Replay Ledgers, Event Envelopes,
and Deterministic State Machine Transitions (T-GOV-002).
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from models import PackageStatus


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class PravahEventType(str, Enum):
    INGESTION_REQUESTED = "INGESTION_REQUESTED"
    VALIDATION_COMPLETED = "VALIDATION_COMPLETED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    CERTIFICATION_GRANTED = "CERTIFICATION_GRANTED"
    STATUS_CHANGED = "STATUS_CHANGED"
    REPLAY_REQUESTED = "REPLAY_REQUESTED"
    COMPLIANCE_EVALUATED = "COMPLIANCE_EVALUATED"
    PIPELINE_TRIGGERED = "PIPELINE_TRIGGERED"
    TRANSITION_FAILED = "TRANSITION_FAILED"


class PravahEntityType(str, Enum):
    PACKAGE = "package"
    DATASET = "dataset"
    CAPABILITY = "capability"
    TASK = "task"
    PIPELINE = "pipeline"


class PravahEventStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    REPLAYED = "REPLAYED"
    DUPLICATE = "DUPLICATE"


class PravahEvent(BaseModel):
    """
    Immutable event envelope for the Pravah event stream and replay ledger.
    Strict validation prevents arbitrary or unexpected fields.
    """
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: _new_id("evt"), min_length=1)
    topic: str = Field(default="pravah.masterdb.events", min_length=1)
    event_type: PravahEventType
    entity_type: PravahEntityType = PravahEntityType.PACKAGE
    entity_id: str = Field(..., min_length=1)
    producer: str = Field(default="masterdb", min_length=1)
    timestamp: str = Field(default_factory=_utcnow)
    target_status: Optional[PackageStatus] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None
    idempotency_key: Optional[str] = None


class PravahLedgerEntry(BaseModel):
    """
    Durable entry in the append-only Pravah replay ledger.
    """
    model_config = ConfigDict(extra="forbid")

    sequence_number: int = Field(..., ge=1)
    event: PravahEvent
    status: PravahEventStatus
    recorded_at: str = Field(default_factory=_utcnow)
    processed_at: Optional[str] = None
    state_hash_after: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_sequence: int = Field(default=1, ge=1)
    to_sequence: Optional[int] = Field(default=None, ge=1)
    topic: Optional[str] = None
    entity_id: Optional[str] = None


class ReplayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replayed_count: int
    skipped_duplicate_count: int
    failed_count: int
    state_hash: str
    entries: List[PravahLedgerEntry] = Field(default_factory=list)


class DeterministicVerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs_completed: int
    identical_hashes: bool
    final_hash: str
    hash_history: List[str]
    duration_ms: float
    status: str


class PipelineExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(..., min_length=1)
    entity_type: PravahEntityType = PravahEntityType.PACKAGE
    initial_status: PackageStatus = PackageStatus.REGISTERED
    target_status: PackageStatus = PackageStatus.CERTIFIED
    actor: str = Field(default="system", min_length=1)
    context: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PipelineExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline_id: str
    entity_id: str
    final_status: PackageStatus
    success: bool
    transitions: List[Dict[str, Any]] = Field(default_factory=list)
    state_hash: str
    ledger_sequence_start: int
    ledger_sequence_end: int
    audit_entry_hash: str
