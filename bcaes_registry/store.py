"""
In-memory (optionally disk-persisted) canonical store for the eleven
BCAES registries.

One dict per registry_type, keyed by object id. Consumers are derived
(see models.RegistryObject docstring) rather than stored redundantly, so
there is exactly one place edges are written (`dependencies`) and zero
places they can silently drift.

PERSISTENCE: opt-in via `persist_dir`. Left `None` (the default), the
store behaves exactly as before — pure in-memory, reset on every process
restart, which is what every existing test relies on for isolation (see
`tests/test_bcaes_api.py`'s `_fresh_registry` fixture). Passed a
directory, every register/update/delete is mirrored to a JSON file there
via the same `ArtifactStore` pattern used elsewhere in this repo
(`services/artifact_store.py`), and existing objects are loaded back on
`__init__`. See `PRODUCTION_HARDENING.md` for the caveat about Render's
default filesystem being ephemeral without an attached persistent Disk.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bcaes_registry.models import (
    DependencyRef,
    RegisterObjectRequest,
    RegistryObject,
    RegistryType,
    UpdateObjectRequest,
    new_object_id,
)
from services.artifact_store import ArtifactStore


class ObjectNotFoundError(Exception):
    pass


class DependencyNotFoundError(Exception):
    """Raised when a registered object declares a dependency id that does
    not exist anywhere in the registry."""


class PermissionDeniedError(Exception):
    """Raised when an authenticated actor lacks authority over an object
    (see BCAESRegistryService's RBAC checks — this store itself has no
    concept of identity; the service layer decides, this just carries the
    error)."""


class CanonicalRegistryStore:
    def __init__(self, persist_dir: Optional[str] = None, artifact_store=None) -> None:
        self._objects: Dict[RegistryType, Dict[str, RegistryObject]] = {
            rt: {} for rt in RegistryType
        }
        # `artifact_store`, if given, is used as-is (e.g. a SqlArtifactStore
        # pointed at a real database) — this takes priority over persist_dir.
        # Falling back to persist_dir keeps every existing caller (including
        # every test that passes a temp directory string) working unchanged.
        if artifact_store is not None:
            self._artifact_store: Optional[object] = artifact_store
            self.reload_from_persistent_store()
        elif persist_dir is not None:
            self._artifact_store = ArtifactStore(reports_dir=persist_dir)
            self.reload_from_persistent_store()
        else:
            self._artifact_store = None

    def reload_from_persistent_store(self) -> None:
        """Re-syncs the in-memory cache from the underlying persistent
        store (if any) — clears and fully repopulates, so this is also
        correct after an external write (e.g. POST /admin/restore) that
        wrote directly to the artifact_store without going through this
        object's register()/update()/delete() methods. A no-op if running
        pure in-memory (no artifact_store configured)."""
        if self._artifact_store is None:
            return
        self._objects = {rt: {} for rt in RegistryType}
        for record in self._artifact_store.list_all():
            obj = RegistryObject(**record)
            self._objects[obj.registry_type][obj.id] = obj

    def _persist(self, obj: RegistryObject) -> None:
        if self._artifact_store is not None:
            self._artifact_store.save(obj.id, obj.model_dump(mode="json"))

    def _unpersist(self, object_id: str) -> None:
        if self._artifact_store is not None:
            self._artifact_store.delete(object_id)

    # -- lookup ----------------------------------------------------------

    def get(self, registry_type: RegistryType, object_id: str) -> RegistryObject:
        obj = self._objects[registry_type].get(object_id)
        if obj is None:
            raise ObjectNotFoundError(
                f"No object '{object_id}' in {registry_type.value} registry."
            )
        return obj

    def get_by_id(self, object_id: str) -> RegistryObject:
        """Look up an object by id without knowing its registry_type
        up front (used by the relationship/dependency explorers)."""
        for bucket in self._objects.values():
            if object_id in bucket:
                return bucket[object_id]
        raise ObjectNotFoundError(f"No object '{object_id}' in any registry.")

    def all_objects(self) -> List[RegistryObject]:
        return [obj for bucket in self._objects.values() for obj in bucket.values()]

    def list_registry(self, registry_type: RegistryType) -> List[RegistryObject]:
        return list(self._objects[registry_type].values())

    def search(
        self,
        query: Optional[str] = None,
        registry_type: Optional[RegistryType] = None,
        owner: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[RegistryObject]:
        pool = (
            self.list_registry(registry_type)
            if registry_type is not None
            else self.all_objects()
        )
        results = pool
        if query:
            q = query.lower()
            results = [
                o
                for o in results
                if q in o.name.lower() or q in o.purpose.lower()
            ]
        if owner:
            results = [o for o in results if o.owner.lower() == owner.lower()]
        if status:
            results = [o for o in results if o.status.value == status]
        return results

    # -- mutation ----------------------------------------------------------

    @property
    def artifact_store(self):
        """Read-only access to the underlying persistence backend (an
        ArtifactStore or SqlArtifactStore), or None if running pure
        in-memory. Used by services/backup_service.py — backup/restore
        operates through this same list_all()/save() interface, so it
        works identically whether the backend is JSON files or SQL."""
        return self._artifact_store

    def register(
        self, registry_type: RegistryType, request: RegisterObjectRequest
    ) -> RegistryObject:
        for dep in request.dependencies:
            if not self._exists(dep.id):
                raise DependencyNotFoundError(
                    f"Dependency '{dep.id}' does not exist in any registry."
                )

        object_id = new_object_id(registry_type)
        obj = RegistryObject(
            id=object_id,
            registry_type=registry_type,
            classification=registry_type,
            name=request.name,
            purpose=request.purpose,
            owner=request.owner,
            status=request.status,
            version=request.version,
            dependencies=request.dependencies,
            consumers=[],
            authority_boundaries=request.authority_boundaries,
            links=request.links,
        )
        self._objects[registry_type][object_id] = obj
        self._persist(obj)
        return obj

    def update(
        self,
        registry_type: RegistryType,
        object_id: str,
        request: UpdateObjectRequest,
    ) -> RegistryObject:
        obj = self.get(registry_type, object_id)
        data = obj.model_dump()

        if request.dependencies is not None:
            for dep in request.dependencies:
                if not self._exists(dep.id):
                    raise DependencyNotFoundError(
                        f"Dependency '{dep.id}' does not exist in any registry."
                    )
            data["dependencies"] = [d.model_dump() for d in request.dependencies]

        for field in ("name", "purpose", "owner", "status", "version",
                       "authority_boundaries", "links"):
            value = getattr(request, field)
            if value is not None:
                data[field] = value

        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        updated = RegistryObject(**data)
        self._objects[registry_type][object_id] = updated
        self._persist(updated)
        return updated

    def delete(self, registry_type: RegistryType, object_id: str) -> None:
        self.get(registry_type, object_id)  # raises if missing
        del self._objects[registry_type][object_id]
        self._unpersist(object_id)

    def _exists(self, object_id: str) -> bool:
        try:
            self.get_by_id(object_id)
            return True
        except ObjectNotFoundError:
            return False

    # -- derived: consumers --------------------------------------------

    def consumers_of(self, object_id: str) -> List[str]:
        """All objects that declare `object_id` as a dependency."""
        return sorted(
            o.id
            for o in self.all_objects()
            if any(d.id == object_id for d in o.dependencies)
        )

    def with_derived_consumers(self, obj: RegistryObject) -> RegistryObject:
        data = obj.model_dump()
        data["consumers"] = self.consumers_of(obj.id)
        return RegistryObject(**data)
