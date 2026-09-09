"""
Database Targets — models for the MASTERDB database-routing / ingestion
attachment layer.

Owns the contract between the MASTERDB Dashboard & Control Center and the
8 MASTERDB target databases (VectorDB, GraphDB, MetadataDB, DocumentDB,
TimeSeriesDB, RelationalDB, ArchiveDB, AnalyticsDB). This module does not
duplicate the existing validation/certification pipeline (ValidationService
/ CertificationService) — it routes an already-CERTIFIED dataset to the
correct target database, enforcing per-database RBAC, and records a fully
auditable ingestion job. See `database_targets/registry.py` for the
per-database capability contract and `database_targets/service.py` for the
routing/gate logic.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TargetDatabase(str, Enum):
    VECTOR_DB = "VectorDB"
    GRAPH_DB = "GraphDB"
    METADATA_DB = "MetadataDB"
    DOCUMENT_DB = "DocumentDB"
    TIME_SERIES_DB = "TimeSeriesDB"
    RELATIONAL_DB = "RelationalDB"
    ARCHIVE_DB = "ArchiveDB"
    ANALYTICS_DB = "AnalyticsDB"


class IngestionFormat(str, Enum):
    CSV = "csv"
    JSON = "json"
    XLSX = "xlsx"
    PDF = "pdf"
    TXT = "txt"
    IMAGE = "image"


class IngestionJobStatus(str, Enum):
    PERSISTED = "PERSISTED"
    REJECTED = "REJECTED"


class DatabaseCapability(BaseModel):
    key: TargetDatabase
    display_name: str
    description: str
    accepted_formats: List[IngestionFormat]
    required_role: str
    status: str = "OPERATIONAL"


class IngestJobStep(BaseModel):
    step: str
    passed: bool
    detail: str
    at: str = Field(default_factory=_utcnow)


class IngestRequest(BaseModel):
    dataset_id: str
    target_database: TargetDatabase
    source_format: IngestionFormat
    package_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IngestJob(BaseModel):
    job_id: str = Field(default_factory=lambda: _new_id("ingest"))
    trace_id: str = Field(default_factory=lambda: _new_id("trace"))
    dataset_id: str
    target_database: TargetDatabase
    source_format: IngestionFormat
    package_id: Optional[str] = None
    actor: str
    roles: List[str] = Field(default_factory=list)
    status: IngestionJobStatus
    certification_state: Optional[str] = None
    integrity_score: Optional[float] = None
    steps: List[IngestJobStep] = Field(default_factory=list)
    rejection_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    submitted_at: str = Field(default_factory=_utcnow)
    completed_at: Optional[str] = None
