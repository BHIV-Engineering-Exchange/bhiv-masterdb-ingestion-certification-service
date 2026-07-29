"""
BCAES Canonical Registry Service — orchestration layer consumed by main.py.

Wraps CanonicalRegistryStore + graph.py + validators.py behind a single
object so the FastAPI layer stays thin, matching the pattern already used
by PackageRegistryService / SharedDataRegistryService elsewhere in this repo.

RBAC (added in the production-hardening pass): `register`/`update`/`delete`
accept optional `actor`/`actor_roles`. When omitted (the default), no
check runs — this keeps every existing direct/service-level caller (and
`tests/test_bcaes_registry_service.py`) working unchanged, on the
principle that the service object itself doesn't mandate an identity
layer; `main.py`'s HTTP routes are what always supply one, sourced from a
verified JWT (see `auth/`). When `actor` is provided, the check is: does
`actor` appear in the relevant `authority_boundaries` list, or does any
role in `actor_roles` appear there, or does `actor_roles` contain
`auth.constants.ADMIN_ROLE`? For `register`, "relevant" means the
authority_boundaries being requested for the new object (you can't grant
authority you don't hold). For `update`/`delete`, it means the existing
object's current authority_boundaries.
"""
from typing import Dict, List, Optional

from auth.constants import ADMIN_ROLE
from bcaes_registry import graph, snapshot, validators
from bcaes_registry.convergence_models import ConvergenceRecord, ConvergenceUpdateRequest
from bcaes_registry.convergence_store import ConvergenceStore
from bcaes_registry.models import (
    RegisterObjectRequest,
    RegistryObject,
    RegistryType,
    UpdateObjectRequest,
)
from bcaes_registry.store import (
    CanonicalRegistryStore,
    DependencyNotFoundError,
    ObjectNotFoundError,
    PermissionDeniedError,
)

__all__ = [
    "BCAESRegistryService",
    "ObjectNotFoundError",
    "DependencyNotFoundError",
    "PermissionDeniedError",
]


def _has_authority(actor: Optional[str], actor_roles: Optional[List[str]], boundaries: List[str]) -> bool:
    if actor is None:
        return True  # no identity supplied -> enforcement not requested by the caller
    roles = actor_roles or []
    if ADMIN_ROLE in roles:
        return True
    if actor in boundaries:
        return True
    return bool(set(roles) & set(boundaries))


class BCAESRegistryService:
    def __init__(self, persist_dir: Optional[str] = None) -> None:
        self._store = CanonicalRegistryStore(persist_dir=persist_dir)
        self._convergence_store = ConvergenceStore(self._store)

    # -- registry CRUD ---------------------------------------------------

    def register(
        self,
        registry_type: RegistryType,
        request: RegisterObjectRequest,
        actor: Optional[str] = None,
        actor_roles: Optional[List[str]] = None,
    ) -> RegistryObject:
        if not _has_authority(actor, actor_roles, request.authority_boundaries):
            raise PermissionDeniedError(
                f"'{actor}' is not in the requested authority_boundaries "
                f"{request.authority_boundaries} and holds no matching role."
            )
        obj = self._store.register(registry_type, request)
        return self._store.with_derived_consumers(obj)

    def update(
        self,
        registry_type: RegistryType,
        object_id: str,
        request: UpdateObjectRequest,
        actor: Optional[str] = None,
        actor_roles: Optional[List[str]] = None,
    ) -> RegistryObject:
        existing = self._store.get(registry_type, object_id)
        if not _has_authority(actor, actor_roles, existing.authority_boundaries):
            raise PermissionDeniedError(
                f"'{actor}' is not in '{object_id}'s authority_boundaries "
                f"{existing.authority_boundaries} and holds no matching role."
            )
        obj = self._store.update(registry_type, object_id, request)
        return self._store.with_derived_consumers(obj)

    def delete(
        self,
        registry_type: RegistryType,
        object_id: str,
        actor: Optional[str] = None,
        actor_roles: Optional[List[str]] = None,
    ) -> None:
        existing = self._store.get(registry_type, object_id)
        if not _has_authority(actor, actor_roles, existing.authority_boundaries):
            raise PermissionDeniedError(
                f"'{actor}' is not in '{object_id}'s authority_boundaries "
                f"{existing.authority_boundaries} and holds no matching role."
            )
        self._store.delete(registry_type, object_id)

    def get(self, registry_type: RegistryType, object_id: str) -> RegistryObject:
        obj = self._store.get(registry_type, object_id)
        return self._store.with_derived_consumers(obj)

    def list_registry(self, registry_type: RegistryType) -> List[RegistryObject]:
        return [self._store.with_derived_consumers(o) for o in self._store.list_registry(registry_type)]

    def registry_summary(self) -> Dict[str, int]:
        return {rt.value: len(self._store.list_registry(rt)) for rt in RegistryType}

    # -- search / lookup ---------------------------------------------------

    def search(
        self,
        query: Optional[str] = None,
        registry_type: Optional[RegistryType] = None,
        owner: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[RegistryObject]:
        results = self._store.search(query=query, registry_type=registry_type, owner=owner, status=status)
        return [self._store.with_derived_consumers(o) for o in results]

    # -- relationship / dependency explorers -----------------------------

    def relationships(self, object_id: str) -> Dict:
        return graph.relationships(self._store, object_id)

    def transitive_dependencies(self, object_id: str) -> Dict:
        return graph.transitive_dependencies(self._store, object_id)

    # -- validation --------------------------------------------------------

    def validate_classification(self) -> Dict:
        return validators.validate_classification(self._store)

    def detect_duplicates(self) -> Dict:
        return validators.detect_duplicates(self._store)

    def validate_ownership(self) -> Dict:
        return validators.validate_ownership(self._store)

    def validate_authority_boundaries(self) -> Dict:
        return validators.validate_authority_boundaries(self._store)

    def validate_version_compatibility(self) -> Dict:
        return validators.validate_version_compatibility(self._store)

    def validate_dependency_integrity(self) -> Dict:
        return validators.validate_dependency_integrity(self._store)

    def capability_reuse_check(self, name: str) -> Dict:
        return validators.capability_reuse_check(self._store, name)

    def validate_architecture(self) -> Dict:
        return validators.run_architecture_validation(self._store)

    # -- production convergence (BCAES Volume 6) ---------------------------

    def upsert_convergence(self, object_id: str, request: ConvergenceUpdateRequest) -> ConvergenceRecord:
        return self._convergence_store.upsert(object_id, request)

    def get_convergence(self, object_id: str) -> ConvergenceRecord:
        return self._convergence_store.get(object_id)

    def list_convergence(self) -> List[ConvergenceRecord]:
        return self._convergence_store.all_records()

    # -- current reality snapshot (BCAES Volume 7) --------------------------

    def generate_snapshot(self) -> Dict:
        return snapshot.generate_snapshot(self._store, self._convergence_store)
