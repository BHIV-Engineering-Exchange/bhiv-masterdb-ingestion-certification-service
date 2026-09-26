"""
Upload models — Canonical MASTERDB File Upload & Ingestion Contract.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class UploadStatus(str, Enum):
    """Upload lifecycle states following MASTERDB governance requirements."""

    UPLOADED = "UPLOADED"
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    REGISTERED = "REGISTERED"
    INGESTED = "INGESTED"
    AVAILABLE = "AVAILABLE"


UPLOAD_LIFECYCLE_GRAPH: Dict[UploadStatus, List[UploadStatus]] = {
    UploadStatus.UPLOADED: [UploadStatus.RECEIVED, UploadStatus.REJECTED],
    UploadStatus.RECEIVED: [UploadStatus.VALIDATING, UploadStatus.REJECTED],
    UploadStatus.VALIDATING: [UploadStatus.VALIDATED, UploadStatus.REJECTED],
    UploadStatus.VALIDATED: [UploadStatus.REGISTERED, UploadStatus.REJECTED],
    UploadStatus.REGISTERED: [UploadStatus.INGESTED, UploadStatus.REJECTED],
    UploadStatus.INGESTED: [UploadStatus.AVAILABLE, UploadStatus.REJECTED],
    UploadStatus.AVAILABLE: [UploadStatus.REJECTED],
    UploadStatus.REJECTED: [],
}


class UploadJobStep(BaseModel):
    """Single step in the upload job progression."""
    step: str
    passed: bool
    detail: str
    at: str = Field(default_factory=_utcnow)



class UploadJob(BaseModel):
    """Canonical upload job model for MASTERDB."""

    upload_id: str = Field(default_factory=lambda: _new_id("upl"))
    trace_id: str = Field(default_factory=lambda: _new_id("trace"))
    filename: str
    content_type: str
    file_size: int
    checksum_sha256: Optional[str] = None
    classification: Optional[str] = None
    source_reference: Optional[str] = None
    provenance_metadata: Dict[str, Any] = Field(default_factory=dict)
    schema_version: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_version: Optional[str] = None
    product_source: Optional[str] = None
    intended_use: Optional[str] = None
    actor: str
    roles: List[str] = Field(default_factory=list)
    status: UploadStatus = UploadStatus.UPLOADED
    rejection_reason: Optional[str] = None
    steps: List[UploadJobStep] = Field(default_factory=list)
    ingestion_job_id: Optional[str] = None
    package_id: Optional[str] = None
    artifact_id: Optional[str] = None
    uploaded_at: str = Field(default_factory=_utcnow)
    received_at: Optional[str] = None
    validated_at: Optional[str] = None
    registered_at: Optional[str] = None
    ingested_at: Optional[str] = None
    available_at: Optional[str] = None
    storage_path: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UploadInitiationRequest(BaseModel):
    """Request to initiate an upload session."""

    model_config = ConfigDict(extra="forbid")
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., pattern=r"^[\w\-]+/[\w\-]+$")
    file_size: int = Field(..., gt=0, le=500 * 1024 * 1024)
    checksum_sha256: Optional[str] = Field(None, pattern=r"^[a-fA-F0-9]{64}$")
    classification: Optional[str] = None
    source_reference: Optional[str] = None
    provenance_metadata: Dict[str, Any] = Field(default_factory=dict)
    schema_version: Optional[str] = None
    product_source: Optional[str] = None
    intended_use: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UploadInitiationResponse(BaseModel):
    """Response after initiating an upload session."""

    model_config = ConfigDict(extra="forbid")
    upload_id: str
    trace_id: str
    status: UploadStatus
    storage_path: str
    upload_url: Optional[str] = None
    max_size_bytes: int = 500 * 1024 * 1024
    allowed_content_types: List[str] = Field(default_factory=list)
    checksum_algorithm: str = "sha256"
    requires_chunked: bool = False
    chunk_size_bytes: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UploadCompletionRequest(BaseModel):
    """Request to complete an upload after file is staged."""

    model_config = ConfigDict(extra="forbid")
    upload_id: str = Field(..., min_length=1)
    checksum_sha256: Optional[str] = Field(None, pattern=r"^[a-fA-F0-9]{64}$")
    trigger_validation: bool = True


class UploadCompletionResponse(BaseModel):
    """Response after completing an upload."""

    model_config = ConfigDict(extra="forbid")
    upload_id: str
    status: UploadStatus
    validation_passed: bool
    validation_errors: List[str] = Field(default_factory=list)
    checksum_verified: bool
    file_size_bytes: int
    dataset_id: Optional[str] = None
    package_id: Optional[str] = None
    ingestion_job_id: Optional[str] = None
    next_steps: List[str] = Field(default_factory=list)
    audit_reference: Dict[str, str] = Field(default_factory=dict)


class UploadStatusResponse(BaseModel):
    """Response for upload status query."""

    model_config = ConfigDict(extra="forbid")
    upload_id: str
    status: UploadStatus
    filename: str
    content_type: str
    file_size_bytes: int
    checksum_sha256: Optional[str] = None
    classification: Optional[str] = None
    actor: str
    steps: List[UploadJobStep]
    rejection_reason: Optional[str] = None
    dataset_id: Optional[str] = None
    package_id: Optional[str] = None
    ingestion_job_id: Optional[str] = None
    timestamps: Dict[str, Optional[str]] = Field(default_factory=dict)


class UploadListResponse(BaseModel):
    """Response for listing upload jobs."""

    model_config = ConfigDict(extra="forbid")
    count: int
    uploads: List[UploadStatusResponse]
    filters_applied: Dict[str, Any] = Field(default_factory=dict)


class UploadCancelRequest(BaseModel):
    """Request to cancel a pending upload."""
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=1)