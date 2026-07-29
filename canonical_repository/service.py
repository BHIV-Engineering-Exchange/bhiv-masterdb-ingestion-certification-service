"""
BCAB/BCAES Canonical Document Repository — service layer.

RBAC (now enforced — this was schema-only before this pass, see
CANONICAL_REPOSITORY_ARCHITECTURE.md §3 for that earlier decision and why
it's changing now). Every method requires `actor`/`actor_roles` (no
optional default here, unlike bcaes_registry/service.py — main.py always
supplies these from a verified JWT for every canonical-repository route,
including reads, since documents are meant to be the ecosystem's single
source of truth and read access matters as much as write access for that
role). Checks:

- `register`: actor must hold a role in the *requested* access_policy's
  write_roles (or ADMIN_ROLE) — you can't create a document granting
  write access to a role you don't have.
- `publish_version`: actor must hold a role in the existing document's
  write_roles (or ADMIN_ROLE).
- every read method: actor must hold a role in the document's read_roles
  (or ADMIN_ROLE).
"""
from typing import Dict, List, Optional

from auth.constants import ADMIN_ROLE
from canonical_repository.models import (
    AccessPolicy,
    CanonicalDocument,
    DocumentCategory,
    DocumentVersion,
    PublishVersionRequest,
    RegisterDocumentRequest,
)
from canonical_repository.store import (
    CanonicalRepositoryStore,
    DocumentNotFoundError,
    DuplicateCategoryError,
    PermissionDeniedError,
)

__all__ = [
    "CanonicalRepositoryService",
    "DocumentNotFoundError",
    "DuplicateCategoryError",
    "PermissionDeniedError",
]

_PLACEHOLDER_TEMPLATE = (
    "[PLACEHOLDER — not the real {category} text]\n\n"
    "This is demo scaffolding for the BCAES Canonical Repository API. "
    "The actual {category} content will be populated centrally by the "
    "BCAES task owner once this repository is confirmed ready — see "
    "CANONICAL_REPOSITORY_ARCHITECTURE.md. Do not treat this content as "
    "authoritative for any architectural decision."
)


def _has_role(actor_roles: List[str], allowed_roles: List[str]) -> bool:
    if ADMIN_ROLE in actor_roles:
        return True
    return bool(set(actor_roles) & set(allowed_roles))


class CanonicalRepositoryService:
    def __init__(self, persist_dir: Optional[str] = None) -> None:
        self._store = CanonicalRepositoryStore(persist_dir=persist_dir)

    def register(
        self, request: RegisterDocumentRequest, actor: str, actor_roles: List[str]
    ) -> CanonicalDocument:
        access_policy = request.access_policy or AccessPolicy()
        if not _has_role(actor_roles, access_policy.write_roles):
            raise PermissionDeniedError(
                f"'{actor}' holds none of the write_roles "
                f"{access_policy.write_roles} required to register a document "
                f"with that access policy."
            )
        is_placeholder = request.initial_content is None
        content = request.initial_content or _PLACEHOLDER_TEMPLATE.format(
            category=request.category.value
        )
        return self._store.register(
            category=request.category,
            title=request.title,
            owner=request.owner,
            access_policy=access_policy,
            initial_content=content,
            change_note=request.change_note,
            is_placeholder=is_placeholder,
        )

    def publish_version(
        self,
        document_id: str,
        request: PublishVersionRequest,
        actor: str,
        actor_roles: List[str],
    ) -> DocumentVersion:
        document = self._store.get(document_id)
        if not _has_role(actor_roles, document.access_policy.write_roles):
            raise PermissionDeniedError(
                f"'{actor}' holds none of '{document_id}'s write_roles "
                f"{document.access_policy.write_roles}."
            )
        return self._store.publish_version(
            document_id=document_id,
            content=request.content,
            change_note=request.change_note,
            published_by=request.published_by,
        )

    def _check_read(self, document: CanonicalDocument, actor: str, actor_roles: List[str]) -> None:
        if not _has_role(actor_roles, document.access_policy.read_roles):
            raise PermissionDeniedError(
                f"'{actor}' holds none of '{document.id}'s read_roles "
                f"{document.access_policy.read_roles}."
            )

    def get(self, document_id: str, actor: str, actor_roles: List[str]) -> CanonicalDocument:
        document = self._store.get(document_id)
        self._check_read(document, actor, actor_roles)
        return document

    def get_by_category(
        self, category: DocumentCategory, actor: str, actor_roles: List[str]
    ) -> CanonicalDocument:
        document = self._store.get_by_category(category)
        self._check_read(document, actor, actor_roles)
        return document

    def list_all(self, actor: str, actor_roles: List[str]) -> List[CanonicalDocument]:
        """Filters to documents the actor can read, rather than 403-ing the
        whole call - a list endpoint that only ever throws isn't useful for
        an actor who can legitimately see some but not all documents."""
        return [
            d for d in self._store.list_all()
            if _has_role(actor_roles, d.access_policy.read_roles)
        ]

    def version_history(
        self, document_id: str, actor: str, actor_roles: List[str]
    ) -> List[DocumentVersion]:
        document = self._store.get(document_id)
        self._check_read(document, actor, actor_roles)
        return self._store.version_history(document_id)

    def get_version(
        self, document_id: str, version_number: int, actor: str, actor_roles: List[str]
    ) -> DocumentVersion:
        document = self._store.get(document_id)
        self._check_read(document, actor, actor_roles)
        return self._store.get_version(document_id, version_number)

    def latest_version(
        self, document_id: str, actor: str, actor_roles: List[str]
    ) -> DocumentVersion:
        document = self._store.get(document_id)
        self._check_read(document, actor, actor_roles)
        return self._store.latest_version(document_id)

    def verify_chain(self, document_id: str, actor: str, actor_roles: List[str]) -> Dict:
        document = self._store.get(document_id)
        self._check_read(document, actor, actor_roles)
        return self._store.verify_chain(document_id)
