"""
Knowledge Package Lifecycle Manager / Dataset Registry.

Owns package identity and the REGISTERED -> ... -> ARCHIVED lifecycle.
Every transition is timestamped, attributed to an actor, carries a reason,
and is stored so the full history can be replayed and re-verified later.

This module does not perform validation/certification scoring itself (that
remains ValidationService / CertificationService's job); it is the system of
record for *where a package sits* in its lifecycle and *why* it moved there.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from models import (
    PACKAGE_LIFECYCLE_GRAPH,
    KnowledgePackage,
    PackageStatus,
    PackageTransition,
)
from services.artifact_store import ArtifactStore

logger = logging.getLogger("masterdb")


class InvalidTransitionError(ValueError):
    """Raised when a requested lifecycle transition is not permitted."""


class PackageNotFoundError(KeyError):
    """Raised when a package_id does not exist in the registry."""


class PackageRegistryService:
    def __init__(self, store_dir: str = "registry_store") -> None:
        # Reuse ArtifactStore's simple JSON-per-key persistence, keyed by
        # package_id instead of dataset_id, in a dedicated directory so
        # registry records never collide with validation/certification
        # artifacts.
        self.store = ArtifactStore(reports_dir=store_dir)

    # -- lifecycle mutation ------------------------------------------------

    def register(
        self,
        dataset_id: str,
        dataset_version: str,
        schema_version: str,
        board: str,
        medium: str,
        language: str,
        owner: str,
        actor: str = "system",
        reason: str = "Initial package registration.",
    ) -> KnowledgePackage:
        package = KnowledgePackage(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            schema_version=schema_version,
            board=board,
            medium=medium,
            language=language,
            owner=owner,
        )
        transition = PackageTransition(
            from_status=None,
            to_status=PackageStatus.REGISTERED,
            reason=reason,
            actor=actor,
        )
        package.history.append(transition)
        logger.info(
            "package registered package_id=%s dataset_id=%s actor=%s",
            package.package_id, dataset_id, actor,
        )
        return self._save(package)

    def promote(
        self,
        package_id: str,
        to_status: PackageStatus,
        actor: str,
        reason: str,
    ) -> KnowledgePackage:
        package = self.get(package_id)
        current_status = package.status
        allowed_next = PACKAGE_LIFECYCLE_GRAPH.get(current_status, [])
        if to_status not in allowed_next:
            raise InvalidTransitionError(
                f"Cannot transition package {package_id} from {current_status.value} "
                f"to {to_status.value}. Allowed transitions from {current_status.value}: "
                f"{[status.value for status in allowed_next] or 'none (terminal state)'}."
            )
        transition = PackageTransition(
            from_status=current_status,
            to_status=to_status,
            reason=reason,
            actor=actor,
        )
        package.status = to_status
        package.updated_at = datetime.now(timezone.utc).isoformat()
        package.history.append(transition)
        logger.info(
            "package transitioned package_id=%s %s -> %s actor=%s",
            package_id, current_status.value, to_status.value, actor,
        )
        return self._save(package)

    def deprecate(self, package_id: str, actor: str, reason: str) -> KnowledgePackage:
        return self.promote(package_id, PackageStatus.DEPRECATED, actor, reason)

    # -- reads --------------------------------------------------------------

    def get(self, package_id: str) -> KnowledgePackage:
        raw = self.store.load(package_id)
        if raw is None:
            raise PackageNotFoundError(f"No package found for package_id={package_id}")
        return KnowledgePackage(**raw)

    def list_all(self) -> List[KnowledgePackage]:
        return [KnowledgePackage(**raw) for raw in self.store.list_all()]

    def history(self, package_id: str) -> List[PackageTransition]:
        return self.get(package_id).history

    def replay(self, package_id: str) -> PackageStatus:
        """
        Rebuild the package's status purely by walking its recorded
        transition history from scratch, validating every hop against the
        lifecycle graph. Used to detect drift or corruption between the
        stored `status` field and the audit trail that justifies it.
        """
        package = self.get(package_id)
        replayed_status: Optional[PackageStatus] = None
        for index, transition in enumerate(package.history):
            if index == 0:
                replayed_status = transition.to_status
                continue
            allowed_next = PACKAGE_LIFECYCLE_GRAPH.get(replayed_status, [])
            if transition.to_status not in allowed_next:
                raise InvalidTransitionError(
                    f"Replay failed for package {package_id} at transition "
                    f"{transition.transition_id}: {replayed_status.value} -> "
                    f"{transition.to_status.value} is not a legal hop."
                )
            replayed_status = transition.to_status
        if replayed_status != package.status:
            raise InvalidTransitionError(
                f"Replay mismatch for package {package_id}: stored status "
                f"{package.status.value} does not match replayed status "
                f"{replayed_status.value if replayed_status else 'NONE'}."
            )
        return replayed_status

    def audit_completeness(self, package_id: str) -> Dict[str, object]:
        """
        Phase 4 — audit completeness check.

        Verifies the package's history is a well-formed audit trail: a
        single root transition (from_status=None), every transition
        carrying a non-empty actor/reason/timestamp, and monotonically
        non-decreasing timestamps. Returns a report rather than raising, so
        callers (e.g. a /audit endpoint) can surface partial problems
        instead of an opaque failure.
        """
        package = self.get(package_id)
        issues: List[str] = []

        if not package.history:
            issues.append("history is empty.")
        else:
            roots = [t for t in package.history if t.from_status is None]
            if len(roots) != 1:
                issues.append(f"expected exactly 1 root transition (from_status=None), found {len(roots)}.")
            if package.history[0].from_status is not None:
                issues.append("first transition in history is not the root transition.")

            previous_timestamp: Optional[str] = None
            for transition in package.history:
                if not transition.actor:
                    issues.append(f"transition {transition.transition_id} is missing an actor.")
                if not transition.reason:
                    issues.append(f"transition {transition.transition_id} is missing a reason.")
                if previous_timestamp and transition.timestamp < previous_timestamp:
                    issues.append(
                        f"transition {transition.transition_id} timestamp out of order."
                    )
                previous_timestamp = transition.timestamp

        replay_consistent = True
        replay_error: Optional[str] = None
        try:
            self.replay(package_id)
        except InvalidTransitionError as exc:
            replay_consistent = False
            replay_error = str(exc)

        return {
            "package_id": package_id,
            "complete": not issues,
            "issues": issues,
            "replay_consistent": replay_consistent,
            "replay_error": replay_error,
            "transition_count": len(package.history),
        }

    # -- internal ------------------------------------------------------------

    def _save(self, package: KnowledgePackage) -> KnowledgePackage:
        self.store.save(package.package_id, package.model_dump(mode="json"))
        return package
