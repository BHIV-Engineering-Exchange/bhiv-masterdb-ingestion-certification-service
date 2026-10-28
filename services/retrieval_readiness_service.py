"""
Retrieval Readiness & Evidence Service.

Certification does not automatically imply retrieval. This service applies
a distinct set of retrieval-focused rules on top of a package's lifecycle
status and its registered Knowledge Object, and emits a replayable evidence
artifact explaining exactly why a given retrieval status was reached.

MASTERDB does not perform retrieval itself (no embeddings, no vector store,
no runtime reasoning) — it only certifies *whether* a package is eligible to
be retrieved by downstream systems, and records the evidence for that
decision.
"""
from typing import List, Optional

from models import (
    KnowledgePackage,
    PackageStatus,
    RetrievalEvidence,
    RetrievalRuleResult,
    RetrievalStatus,
)
from services.artifact_store import ArtifactStore
from services.knowledge_object_service import KnowledgeObjectService
from services.package_registry_service import PackageRegistryService


class RetrievalReadinessService:
    def __init__(
        self,
        registry: Optional[PackageRegistryService] = None,
        knowledge_object_service: Optional[KnowledgeObjectService] = None,
        store_dir: str = "retrieval_evidence_store",
        report_service: Optional[object] = None,
    ) -> None:
        self.registry = registry or PackageRegistryService()
        self.knowledge_object_service = knowledge_object_service or KnowledgeObjectService(
            registry=self.registry
        )
        self.store = ArtifactStore(reports_dir=store_dir)
        self.report_service = report_service

    def assess(self, package_id: str) -> RetrievalEvidence:
        package = self.registry.get(package_id)  # raises PackageNotFoundError
        rules: List[RetrievalRuleResult] = []

        rules.append(self._rule_certified(package))
        rules.append(self._rule_not_deprecated(package))
        rules.append(self._rule_metadata_complete(package))
        lineage_rule, has_lineage = self._rule_lineage_present(package)
        rules.append(lineage_rule)

        status = self._determine_status(package, rules, has_lineage)
        corrective_actions = [
            self._corrective_action(rule.rule) for rule in rules if not rule.passed
        ]

        evidence = RetrievalEvidence(
            package_id=package_id,
            status=status,
            rules=rules,
            corrective_actions=[action for action in corrective_actions if action],
        )
        self.store.save(package_id, evidence.model_dump(mode="json"))
        return evidence

    def get_latest(self, package_id: str) -> Optional[RetrievalEvidence]:
        raw = self.store.load(package_id)
        if raw is None:
            return None
        return RetrievalEvidence(**raw)

    # -- rules ------------------------------------------------------------

    def _rule_certified(self, package: KnowledgePackage) -> RetrievalRuleResult:
        passed = package.status in (
            PackageStatus.CERTIFIED,
            PackageStatus.RETRIEVAL_READY,
        )
        if passed and self.report_service:
            try:
                report = getattr(self.report_service, "get_report")(package.dataset_id)
                if report.get("state") == "REJECTED" or not report.get("ingestion_decision", {}).get("eligible_for_masterdb", True):
                    return RetrievalRuleResult(
                        rule="PACKAGE_CERTIFIED",
                        passed=False,
                        detail=(
                            f"Package status is {package.status.value}, but dataset {package.dataset_id} "
                            "failed certification (state: REJECTED)."
                        ),
                    )
            except KeyError:
                pass

        return RetrievalRuleResult(
            rule="PACKAGE_CERTIFIED",
            passed=passed,
            detail=(
                f"Package status is {package.status.value}."
                if passed
                else f"Package status is {package.status.value}; CERTIFIED or "
                "RETRIEVAL_READY is required."
            ),
        )

    @staticmethod
    def _rule_not_deprecated(package: KnowledgePackage) -> RetrievalRuleResult:
        passed = package.status not in (PackageStatus.DEPRECATED, PackageStatus.ARCHIVED)
        return RetrievalRuleResult(
            rule="NOT_DEPRECATED_OR_ARCHIVED",
            passed=passed,
            detail=(
                "Package is active."
                if passed
                else f"Package status is {package.status.value}."
            ),
        )

    @staticmethod
    def _rule_metadata_complete(package: KnowledgePackage) -> RetrievalRuleResult:
        required_fields = {
            "board": package.board,
            "medium": package.medium,
            "language": package.language,
            "owner": package.owner,
            "schema_version": package.schema_version,
        }
        missing = [name for name, value in required_fields.items() if not value]
        passed = not missing
        return RetrievalRuleResult(
            rule="METADATA_COMPLETE",
            passed=passed,
            detail=(
                "All required package metadata fields are present."
                if passed
                else f"Missing metadata fields: {', '.join(missing)}."
            ),
        )

    def _rule_lineage_present(self, package: KnowledgePackage) -> tuple:
        knowledge_object = self.knowledge_object_service.get_by_package(package.package_id)
        has_source_reference = bool(knowledge_object and knowledge_object.source_reference)
        return (
            RetrievalRuleResult(
                rule="LINEAGE_REGISTERED",
                passed=has_source_reference,
                detail=(
                    "Knowledge object with source_reference is registered."
                    if has_source_reference
                    else "No knowledge object with a source_reference is registered "
                    "for this package."
                ),
            ),
            has_source_reference,
        )

    # -- status derivation --------------------------------------------------

    @staticmethod
    def _determine_status(
        package: KnowledgePackage,
        rules: List[RetrievalRuleResult],
        has_lineage: bool,
    ) -> RetrievalStatus:
        rule_map = {rule.rule: rule.passed for rule in rules}

        if not rule_map["PACKAGE_CERTIFIED"] or not rule_map["NOT_DEPRECATED_OR_ARCHIVED"]:
            return RetrievalStatus.NOT_RETRIEVABLE

        if not rule_map["METADATA_COMPLETE"] or not has_lineage:
            return RetrievalStatus.PARTIALLY_RETRIEVABLE

        if package.status == PackageStatus.RETRIEVAL_READY:
            return RetrievalStatus.CERTIFIED_RETRIEVABLE

        return RetrievalStatus.RETRIEVABLE

    @staticmethod
    def _corrective_action(rule: str) -> str:
        actions = {
            "PACKAGE_CERTIFIED": "Promote the package through VERIFIED -> CERTIFIED "
            "before requesting retrieval readiness.",
            "NOT_DEPRECATED_OR_ARCHIVED": "This package has been withdrawn; register a "
            "new package version instead of retrieving this one.",
            "METADATA_COMPLETE": "Fill in the missing package metadata fields via the "
            "registry before re-running the retrieval assessment.",
            "LINEAGE_REGISTERED": "Register a Knowledge Object with a source_reference "
            "for this package via the Knowledge Object & Provenance Engine.",
        }
        return actions.get(rule, "")
