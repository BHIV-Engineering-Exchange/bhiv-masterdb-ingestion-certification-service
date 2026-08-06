"""
Service layer for the two sync stores. Both follow the same optional-actor
RBAC pattern as bcaes_registry/service.py: `actor`/`actor_roles` are
optional, and when supplied, the caller must hold `ADMIN_ROLE` or a
source-specific sync role (`parikshak-sync`, `niyantran-sync`). main.py's
HTTP routes always supply an identity from a verified JWT; direct/
programmatic callers (and tests) that don't pass one bypass the check, same
reasoning as bcaes_registry.
"""
from typing import List, Optional

from auth.constants import ADMIN_ROLE
from operational_sync.models import (
    OperationalTaskState,
    ReviewReference,
    UpsertOperationalTaskStateRequest,
    UpsertReviewReferenceRequest,
)
from operational_sync.store import UpsertSyncStore

PARIKSHAK_SYNC_ROLE = "parikshak-sync"
NIYANTRAN_SYNC_ROLE = "niyantran-sync"


class SyncPermissionDeniedError(Exception):
    pass


def _check(actor: Optional[str], actor_roles: Optional[List[str]], required_role: str) -> None:
    if actor is None:
        return
    roles = actor_roles or []
    if ADMIN_ROLE in roles or required_role in roles:
        return
    raise SyncPermissionDeniedError(
        f"'{actor}' holds none of ['{required_role}', '{ADMIN_ROLE}'] required for this sync."
    )


class ParikshakSyncService:
    def __init__(self) -> None:
        self._store: UpsertSyncStore[ReviewReference] = UpsertSyncStore()

    def upsert(
        self,
        request: UpsertReviewReferenceRequest,
        actor: Optional[str] = None,
        actor_roles: Optional[List[str]] = None,
    ) -> ReviewReference:
        _check(actor, actor_roles, PARIKSHAK_SYNC_ROLE)
        record = ReviewReference(**request.model_dump())
        return self._store.upsert(request.external_review_id, record)

    def get(self, external_review_id: str) -> ReviewReference:
        return self._store.get(external_review_id)

    def list_all(self) -> List[ReviewReference]:
        return self._store.list_all()


class NiyantranSyncService:
    def __init__(self) -> None:
        self._store: UpsertSyncStore[OperationalTaskState] = UpsertSyncStore()

    def upsert(
        self,
        request: UpsertOperationalTaskStateRequest,
        actor: Optional[str] = None,
        actor_roles: Optional[List[str]] = None,
    ) -> OperationalTaskState:
        _check(actor, actor_roles, NIYANTRAN_SYNC_ROLE)
        record = OperationalTaskState(**request.model_dump())
        return self._store.upsert(request.external_task_id, record)

    def get(self, external_task_id: str) -> OperationalTaskState:
        return self._store.get(external_task_id)

    def list_all(self) -> List[OperationalTaskState]:
        return self._store.list_all()
