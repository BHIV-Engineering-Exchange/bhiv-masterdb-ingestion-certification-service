"""
BCAES/BCAB Canonical Document Repository — store.

PERSISTENCE: opt-in via `persist_dir`, same pattern and same default
(`None` = pure in-memory, matching every existing test's isolation
assumption) as `bcaes_registry/store.py`. Passed a directory, each
document (metadata + full version history, as one JSON blob per document
id) is mirrored via `ArtifactStore` and reloaded on `__init__`.
"""
import hashlib
import uuid
from typing import Dict, List, Optional

from canonical_repository.models import (
    AccessPolicy,
    CanonicalDocument,
    DocumentCategory,
    DocumentStatus,
    DocumentVersion,
)
from services.artifact_store import ArtifactStore


class DocumentNotFoundError(Exception):
    pass


class DuplicateCategoryError(Exception):
    """One canonical document per category — a second BCAES_VOL_4 would be
    exactly the 'duplicate architectural truth' the whole bootstrap task
    exists to prevent."""


class PermissionDeniedError(Exception):
    """Raised when an authenticated actor lacks the required read/write
    role for a document (see CanonicalRepositoryService)."""


def _content_hash(content: str, previous_hash: str = "") -> str:
    return hashlib.sha256((previous_hash + content).encode("utf-8")).hexdigest()


class CanonicalRepositoryStore:
    def __init__(self, persist_dir: Optional[str] = None) -> None:
        self._documents: Dict[str, CanonicalDocument] = {}
        self._versions: Dict[str, List[DocumentVersion]] = {}
        self._category_index: Dict[DocumentCategory, str] = {}
        self._artifact_store: Optional[ArtifactStore] = None
        if persist_dir is not None:
            self._artifact_store = ArtifactStore(reports_dir=persist_dir)
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        for record in self._artifact_store.list_all():
            document = CanonicalDocument(**record["document"])
            versions = [DocumentVersion(**v) for v in record["versions"]]
            self._documents[document.id] = document
            self._versions[document.id] = versions
            self._category_index[document.category] = document.id

    def _persist(self, document_id: str) -> None:
        if self._artifact_store is not None:
            self._artifact_store.save(
                document_id,
                {
                    "document": self._documents[document_id].model_dump(mode="json"),
                    "versions": [v.model_dump(mode="json") for v in self._versions[document_id]],
                },
            )

    def register(
        self,
        category: DocumentCategory,
        title: str,
        owner: str,
        access_policy: AccessPolicy,
        initial_content: str,
        change_note: str,
        is_placeholder: bool,
    ) -> CanonicalDocument:
        if category in self._category_index:
            raise DuplicateCategoryError(
                f"A canonical document for category '{category.value}' already exists "
                f"(id={self._category_index[category]}); update it instead of "
                f"registering a duplicate."
            )

        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        document = CanonicalDocument(
            id=doc_id,
            category=category,
            title=title,
            owner=owner,
            status=DocumentStatus.PLACEHOLDER if is_placeholder else DocumentStatus.DRAFT,
            access_policy=access_policy,
            current_version=1,
        )
        version = DocumentVersion(
            document_id=doc_id,
            version_number=1,
            content=initial_content,
            content_hash=_content_hash(initial_content),
            change_note=change_note,
            published_by=owner,
            is_placeholder=is_placeholder,
        )
        self._documents[doc_id] = document
        self._versions[doc_id] = [version]
        self._category_index[category] = doc_id
        self._persist(doc_id)
        return document

    def publish_version(
        self, document_id: str, content: str, change_note: str, published_by: str
    ) -> DocumentVersion:
        document = self.get(document_id)
        history = self._versions[document_id]
        previous_hash = history[-1].content_hash
        next_number = history[-1].version_number + 1

        version = DocumentVersion(
            document_id=document_id,
            version_number=next_number,
            content=content,
            content_hash=_content_hash(content, previous_hash),
            change_note=change_note,
            published_by=published_by,
            is_placeholder=False,
        )
        history.append(version)

        updated = document.model_copy(
            update={
                "status": DocumentStatus.PUBLISHED,
                "current_version": next_number,
                "updated_at": version.published_at,
            }
        )
        self._documents[document_id] = updated
        self._persist(document_id)
        return version

    def get(self, document_id: str) -> CanonicalDocument:
        document = self._documents.get(document_id)
        if document is None:
            raise DocumentNotFoundError(f"No canonical document with id '{document_id}'.")
        return document

    def get_by_category(self, category: DocumentCategory) -> CanonicalDocument:
        doc_id = self._category_index.get(category)
        if doc_id is None:
            raise DocumentNotFoundError(f"No canonical document registered for category '{category.value}'.")
        return self._documents[doc_id]

    def list_all(self) -> List[CanonicalDocument]:
        return list(self._documents.values())

    def version_history(self, document_id: str) -> List[DocumentVersion]:
        self.get(document_id)  # 404s cleanly if unknown
        return list(self._versions[document_id])

    def get_version(self, document_id: str, version_number: int) -> DocumentVersion:
        history = self.version_history(document_id)
        for version in history:
            if version.version_number == version_number:
                return version
        raise DocumentNotFoundError(
            f"Document '{document_id}' has no version {version_number}."
        )

    def latest_version(self, document_id: str) -> DocumentVersion:
        document = self.get(document_id)
        return self.get_version(document_id, document.current_version)

    def verify_chain(self, document_id: str) -> Dict:
        """Recomputes every hash in the version chain from stored content
        and confirms it matches what's recorded — a tamper/corruption
        check, the same replay-determinism idea as
        bcaes_registry/validators.py's architecture validation."""
        history = self.version_history(document_id)
        previous_hash = ""
        mismatches = []
        for version in history:
            expected = _content_hash(version.content, previous_hash)
            if expected != version.content_hash:
                mismatches.append(version.version_number)
            previous_hash = version.content_hash
        return {
            "document_id": document_id,
            "versions_checked": len(history),
            "chain_intact": not mismatches,
            "mismatched_versions": mismatches,
        }
