import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class CertificationState(str, Enum):
    NEW = "NEW"
    VALIDATED = "VALIDATED"
    VERIFIED = "VERIFIED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class ValidationRequest(BaseModel):
    dataset_path: str
    metadata_path: Optional[str] = None
    dataset_id: Optional[str] = None


class CertificationRequest(BaseModel):
    dataset_id: Optional[str] = None
    dataset_path: Optional[str] = None
    metadata_path: Optional[str] = None


class TransitionRecord(BaseModel):
    from_state: CertificationState
    to_state: CertificationState
    rule: str
    passed: bool
    reason: str


class IngestionDecision(BaseModel):
    dataset_id: str
    eligible_for_masterdb: bool
    state: CertificationState
    classification: str
    integrity_score: float
    rejection_reasons: List[str] = Field(default_factory=list)
    audit_trail: List[TransitionRecord] = Field(default_factory=list)


class ServiceResponse(BaseModel):
    dataset_id: str
    state: CertificationState
    report: Dict[str, Any]


# ---------------------------------------------------------------------------
# Phase 1 — Knowledge Package Lifecycle Manager / Dataset Registry
# ---------------------------------------------------------------------------


class PackageStatus(str, Enum):
    REGISTERED = "REGISTERED"
    INGESTED = "INGESTED"
    VALIDATED = "VALIDATED"
    VERIFIED = "VERIFIED"
    CERTIFIED = "CERTIFIED"
    RETRIEVAL_READY = "RETRIEVAL_READY"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


# Directed edges of the allowed lifecycle graph. DEPRECATED is reachable from
# any non-terminal state (a package can be withdrawn at any point) and is the
# only path into ARCHIVED.
PACKAGE_LIFECYCLE_GRAPH: Dict[PackageStatus, List[PackageStatus]] = {
    PackageStatus.REGISTERED: [PackageStatus.INGESTED, PackageStatus.DEPRECATED],
    PackageStatus.INGESTED: [PackageStatus.VALIDATED, PackageStatus.DEPRECATED],
    PackageStatus.VALIDATED: [PackageStatus.VERIFIED, PackageStatus.DEPRECATED],
    PackageStatus.VERIFIED: [PackageStatus.CERTIFIED, PackageStatus.DEPRECATED],
    PackageStatus.CERTIFIED: [PackageStatus.RETRIEVAL_READY, PackageStatus.DEPRECATED],
    PackageStatus.RETRIEVAL_READY: [PackageStatus.DEPRECATED],
    PackageStatus.DEPRECATED: [PackageStatus.ARCHIVED],
    PackageStatus.ARCHIVED: [],
}


class PackageTransition(BaseModel):
    transition_id: str = Field(default_factory=lambda: _new_id("txn"))
    from_status: Optional[PackageStatus] = None
    to_status: PackageStatus
    reason: str
    actor: str
    timestamp: str = Field(default_factory=_utcnow)


class KnowledgePackage(BaseModel):
    package_id: str = Field(default_factory=lambda: _new_id("pkg"))
    dataset_id: str
    dataset_version: str
    schema_version: str
    board: str
    medium: str
    language: str
    owner: str
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)
    status: PackageStatus = PackageStatus.REGISTERED
    history: List[PackageTransition] = Field(default_factory=list)


class PackageRegisterRequest(BaseModel):
    dataset_id: str
    dataset_version: str
    schema_version: str
    board: str
    medium: str
    language: str
    owner: str
    actor: str = "system"
    reason: str = "Initial package registration."


class PackagePromoteRequest(BaseModel):
    package_id: str
    to_status: PackageStatus
    actor: str
    reason: str


class PackageDeprecateRequest(BaseModel):
    package_id: str
    actor: str
    reason: str


# ---------------------------------------------------------------------------
# Phase 2 — Knowledge Object & Provenance Engine
# ---------------------------------------------------------------------------


class KnowledgeObject(BaseModel):
    """
    Adapter-facing representation of a canonical Knowledge Object.

    NOTE: Knowledge Object / Provenance / Lineage semantics are owned by MDU
    (Nupur). Field names and shape below track the placeholder contract this
    service currently consumes; they are NOT a competing definition. Once MDU
    publishes MASTERDB <-> MDU Interface Contract v1, this model should be
    updated to consume it directly rather than mirror it locally.
    """

    knowledge_object_id: str = Field(default_factory=lambda: _new_id("kobj"))
    knowledge_hash: str
    package_id: str
    schema_version: str
    parent_package: Optional[str] = None
    child_packages: List[str] = Field(default_factory=list)
    source_reference: Optional[str] = None
    lineage_reference: Optional[str] = None
    derivation_path: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utcnow)


class KnowledgeObjectRegisterRequest(BaseModel):
    package_id: str
    parent_package: Optional[str] = None
    source_reference: Optional[str] = None
    lineage_reference: Optional[str] = None
    derivation_path: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 3 — Retrieval Readiness & Evidence Service
# ---------------------------------------------------------------------------


class RetrievalStatus(str, Enum):
    NOT_RETRIEVABLE = "NOT_RETRIEVABLE"
    PARTIALLY_RETRIEVABLE = "PARTIALLY_RETRIEVABLE"
    RETRIEVABLE = "RETRIEVABLE"
    CERTIFIED_RETRIEVABLE = "CERTIFIED_RETRIEVABLE"


class RetrievalRuleResult(BaseModel):
    rule: str
    passed: bool
    detail: str


class RetrievalEvidence(BaseModel):
    package_id: str
    status: RetrievalStatus
    rules: List[RetrievalRuleResult]
    corrective_actions: List[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Task 4 — Shared Data Services & MASTERDB Convergence
#
# Generic record model reused by every shared ecosystem dataset
# (Authentication, Identity, Organizations, Configuration, Knowledge
# References, Notifications, ...). One model + one engine
# (services/shared_record_store.py) instead of a bespoke model per dataset,
# so versioning/audit/replay behavior is uniform across the shared data
# platform. Domain meaning lives entirely in `payload` (a free-form dict),
# never in this model — MASTERDB is not allowed to invent ontology here.
# ---------------------------------------------------------------------------


class SharedRecordTransition(BaseModel):
    transition_id: str = Field(default_factory=lambda: _new_id("stx"))
    version: int
    action: str  # "REGISTERED" | "UPDATED" | "DEPRECATED"
    actor: str
    reason: str
    timestamp: str = Field(default_factory=_utcnow)


class SharedRecord(BaseModel):
    record_id: str
    dataset: str
    payload: Dict[str, Any]
    version: int = 1
    deprecated: bool = False
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)
    history: List[SharedRecordTransition] = Field(default_factory=list)


class SharedRecordRegisterRequest(BaseModel):
    record_id: str
    payload: Dict[str, Any]
    actor: str = "system"
    reason: str = "Initial record registration."


class SharedRecordUpdateRequest(BaseModel):
    payload: Dict[str, Any]
    actor: str
    reason: str


class SharedRecordDeprecateRequest(BaseModel):
    actor: str
    reason: str


# ---------------------------------------------------------------------------
# Phase 4 — Controlled Retrieval Request Models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    dataset_id: str
    query_params: Dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    dataset_id: str
    format: Optional[str] = None


class StreamRequest(BaseModel):
    dataset_id: str
    stream_params: Dict[str, Any] = Field(default_factory=dict)


class ReferenceRequest(BaseModel):
    dataset_id: str


