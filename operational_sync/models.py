"""
Operational Sync — models for the two "MASTERDB records truth, doesn't own
the source" integrations named in the Integration Coordination brief:

- PARIKSHAK (engineering review): "Consume approved review APIs. Store
  Review References only. Store Review Summaries only. Store Readiness
  status. ... Do not duplicate engineering intelligence."
- NIYANTRAN (operational task lifecycle): "Consume task lifecycle APIs.
  Synchronize candidate operational state/progress/assignments/completion
  status. ... MASTERDB records operational truth only and must not
  execute workflow."

DIRECTION ASSUMPTION (flagged, not confirmed): both are modeled here as
MASTERDB *ingesting* records pushed to it (upsert-by-external-id), rather
than MASTERDB polling a PARIKSHAK/NIYANTRAN endpoint — because no such
endpoint has been confirmed reachable from this environment (see
CONSTITUTIONAL_RUNTIME_DEFINITION.md §4). If the real contract is
pull-based instead, the store/service below don't change — only which
side calls `upsert` does.

"Do not duplicate engineering intelligence" / "must not execute workflow"
are enforced by what fields exist here: no free-form content field wide
enough to hold full review detail or drive task execution — just
references, summaries, and status enums.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReadinessStatus(str, Enum):
    NOT_READY = "not_ready"
    IN_REVIEW = "in_review"
    READY = "ready"


class ReviewReference(BaseModel):
    """A reference to a PARIKSHAK engineering review — not the review
    itself. `summary` is a short, PARIKSHAK-authored summary string, not a
    place for MASTERDB (or anyone calling this API) to write engineering
    detail."""

    external_review_id: str
    subject: str = Field(description="What was reviewed — e.g. a bcaes_registry object id, PR, or commit ref.")
    summary: str = Field(max_length=500)
    readiness_status: ReadinessStatus
    source_url: Optional[str] = Field(default=None, description="Link back to the review in PARIKSHAK.")
    synced_at: str = Field(default_factory=_utcnow)


class UpsertReviewReferenceRequest(BaseModel):
    external_review_id: str
    subject: str
    summary: str = Field(max_length=500)
    readiness_status: ReadinessStatus
    source_url: Optional[str] = None


class TaskOperationalStatus(str, Enum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETE = "complete"


class OperationalTaskState(BaseModel):
    """Records NIYANTRAN's task state — MASTERDB's copy of the truth, not
    a place that drives what happens to the task next. No transition
    logic or workflow triggers live here."""

    external_task_id: str
    candidate: str = Field(description="Who/what the task is assigned to, as NIYANTRAN reports it.")
    progress: int = Field(ge=0, le=100)
    status: TaskOperationalStatus
    synced_at: str = Field(default_factory=_utcnow)


class UpsertOperationalTaskStateRequest(BaseModel):
    external_task_id: str
    candidate: str
    progress: int = Field(ge=0, le=100)
    status: TaskOperationalStatus
