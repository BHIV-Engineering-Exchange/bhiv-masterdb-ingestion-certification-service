"""Dataset Retrieval Service — Plug-and-Play Data Access (Phase 4)."""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models import KnowledgePackage, PackageStatus, RetrievalEvidence, RetrievalStatus
from services.package_registry_service import PackageNotFoundError, PackageRegistryService
from services.knowledge_object_service import KnowledgeObjectService
from services.retrieval_readiness_service import RetrievalReadinessService
from services.mdu_contract_adapter import MDUContractAdapter

logger = logging.getLogger("masterdb")


class DatasetAccessDeniedError(PermissionError):
    pass


class DatasetNotRetrievableError(RuntimeError):
    pass


class DatasetRetrievalService:
    def __init__(
        self,
        registry: Optional[PackageRegistryService] = None,
        knowledge_object_service: Optional[KnowledgeObjectService] = None,
        retrieval_readiness_service: Optional[RetrievalReadinessService] = None,
        mdu_adapter: Optional[MDUContractAdapter] = None,
    ) -> None:
        self.registry = registry or PackageRegistryService()
        self.knowledge_object_service = knowledge_object_service or KnowledgeObjectService(
            registry=self.registry
        )
        self.retrieval_readiness_service = retrieval_readiness_service or RetrievalReadinessService(
            registry=self.registry, knowledge_object_service=self.knowledge_object_service
        )
        self.mdu_adapter = mdu_adapter or MDUContractAdapter()

    def list_datasets(self) -> List[Dict[str, Any]]:
        packages = self.registry.list_all()
        return [self._to_dataset_summary(pkg) for pkg in packages]

    def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        packages = self.registry.list_all()
        package = next((p for p in packages if p.dataset_id == dataset_id), None)
        if package is None:
            raise PackageNotFoundError(f"No dataset registered with dataset_id='{dataset_id}'.")
        return self._to_dataset_detail(package)

    def get_dataset_by_package_id(self, package_id: str) -> Dict[str, Any]:
        package = self.registry.get(package_id)
        return self._to_dataset_detail(package)

    def get_dataset_schema(self, dataset_id: str, local_schema_version: Optional[str] = None) -> Dict[str, Any]:
        try:
            mdu_schema = self.mdu_adapter.fetch_schema_contract(dataset_id)
            return {
                "source": "mdu-live" if self.mdu_adapter.client.is_configured() else "placeholder",
                "dataset_id": dataset_id,
                "schema": mdu_schema,
            }
        except Exception:
            packages = self.registry.list_all()
            package = next((p for p in packages if p.dataset_id == dataset_id), None)
            declared_version = package.schema_version if package else local_schema_version
            return {
                "source": "registry-declared",
                "dataset_id": dataset_id,
                "schema_version": declared_version,
                "note": "MDU schema unavailable; returning registry-declared version only.",
            }

    def get_dataset_versions(self, dataset_id: str) -> Dict[str, Any]:
        packages = self.registry.list_all()
        versions = [p for p in packages if p.dataset_id == dataset_id]
        if not versions:
            raise PackageNotFoundError(f"No versions found for dataset_id='{dataset_id}'.")
        latest = max(versions, key=lambda p: p.created_at)
        return {
            "dataset_id": dataset_id,
            "version_count": len(versions),
            "versions": [
                {
                    "package_id": v.package_id,
                    "dataset_version": v.dataset_version,
                    "schema_version": v.schema_version,
                    "status": v.status.value,
                    "created_at": v.created_at,
                }
                for v in sorted(versions, key=lambda x: x.created_at, reverse=True)
            ],
            "latest": {
                "package_id": latest.package_id,
                "history": [t.model_dump(mode="json") for t in latest.history],
            },
        }

    def get_dataset_provenance(self, dataset_id: str) -> Dict[str, Any]:
        packages = self.registry.list_all()
        package = next((p for p in packages if p.dataset_id == dataset_id), None)
        if package is None:
            raise PackageNotFoundError(f"No dataset registered with dataset_id='{dataset_id}'.")
        masterdb_lineage = self.knowledge_object_service.lineage(package.package_id)
        mdu_provenance = []
        mdu_source = "unavailable"
        try:
            mdu_provenance = self.mdu_adapter.fetch_provenance_contract(dataset_id)
            mdu_source = "mdu-live" if self.mdu_adapter.client.is_configured() else "placeholder"
        except Exception:
            pass
        return {
            "dataset_id": dataset_id,
            "package_id": package.package_id,
            "masterdb_lineage": masterdb_lineage,
            "mdu_provenance": mdu_provenance,
            "mdu_source": mdu_source,
        }

    def query(
        self,
        dataset_id: str,
        query_params: Optional[Dict[str, Any]] = None,
        dataset_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._controlled_access(
            dataset_id, "query", query_params, dataset_version=dataset_version
        )

    def export_dataset(
        self,
        dataset_id: str,
        format: Optional[str] = None,
        dataset_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._controlled_access(
            dataset_id, "export", {"format": format}, dataset_version=dataset_version
        )

    def stream(
        self,
        dataset_id: str,
        stream_params: Optional[Dict[str, Any]] = None,
        dataset_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._controlled_access(
            dataset_id, "stream", stream_params, dataset_version=dataset_version
        )

    def reference(
        self,
        dataset_id: str,
        dataset_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._controlled_access(
            dataset_id, "reference", None, dataset_version=dataset_version
        )

    def _select_package(
        self,
        packages: List[KnowledgePackage],
        dataset_id: str,
        dataset_version: Optional[str] = None,
    ) -> Tuple[KnowledgePackage, Optional[RetrievalEvidence]]:
        all_matching = [p for p in packages if p.dataset_id == dataset_id]
        if not all_matching:
            raise PackageNotFoundError(f"No dataset registered with dataset_id='{dataset_id}'.")

        if dataset_version is not None:
            matching_version = [p for p in all_matching if p.dataset_version == dataset_version]
            if not matching_version:
                raise PackageNotFoundError(
                    f"No package found for dataset_id='{dataset_id}' with version='{dataset_version}'."
                )

            assessed_candidates: List[Tuple[KnowledgePackage, RetrievalEvidence]] = []
            for p in matching_version:
                ev = self.retrieval_readiness_service.assess(p.package_id)
                assessed_candidates.append((p, ev))

            def candidate_sort_key(item: Tuple[KnowledgePackage, RetrievalEvidence]):
                pkg, ev = item
                is_retrievable = 1 if ev.status != RetrievalStatus.NOT_RETRIEVABLE else 0
                is_certified = 1 if pkg.status in (PackageStatus.CERTIFIED, PackageStatus.RETRIEVAL_READY) else 0
                is_not_deprecated = 1 if pkg.status != PackageStatus.DEPRECATED else 0
                return (is_retrievable, is_certified, is_not_deprecated, pkg.created_at, pkg.package_id)

            assessed_candidates.sort(key=candidate_sort_key, reverse=True)
            return assessed_candidates[0]

        # dataset_version is None: Default to latest certified, retrieval-ready package
        candidates = [
            p for p in all_matching
            if p.status in (PackageStatus.CERTIFIED, PackageStatus.RETRIEVAL_READY)
        ]

        assessed_map: Dict[str, RetrievalEvidence] = {}
        eligible: List[Tuple[KnowledgePackage, RetrievalEvidence]] = []
        for p in candidates:
            ev = self.retrieval_readiness_service.assess(p.package_id)
            assessed_map[p.package_id] = ev
            if ev.status != RetrievalStatus.NOT_RETRIEVABLE:
                eligible.append((p, ev))

        if eligible:
            eligible.sort(key=lambda item: (item[0].created_at, item[0].package_id), reverse=True)
            return eligible[0]

        # Fallback when no certified candidate is eligible:
        # Select newest non-deprecated candidate by (created_at DESC, package_id DESC).
        # If all are deprecated, select newest overall.
        non_deprecated = [p for p in all_matching if p.status != PackageStatus.DEPRECATED]
        fallback_pool = non_deprecated if non_deprecated else all_matching
        fallback_sorted = sorted(
            fallback_pool,
            key=lambda p: (p.created_at, p.package_id),
            reverse=True,
        )
        selected = fallback_sorted[0]
        return selected, assessed_map.get(selected.package_id)

    def _controlled_access(
        self,
        dataset_id: str,
        operation: str,
        params: Optional[Dict[str, Any]],
        dataset_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        packages = self.registry.list_all()
        package, precomputed_evidence = self._select_package(
            packages, dataset_id, dataset_version=dataset_version
        )
        evidence = (
            precomputed_evidence
            if precomputed_evidence is not None
            else self.retrieval_readiness_service.assess(package.package_id)
        )
        if evidence.status == RetrievalStatus.NOT_RETRIEVABLE and operation != "reference":
            raise DatasetNotRetrievableError(
                f"Dataset '{dataset_id}' is not retrievable. Status: {evidence.status.value}. "
                f"Corrective actions: {evidence.corrective_actions}"
            )
        access_policy = self._resolve_access_policy(package)
        if operation not in access_policy["allowed_operations"]:
            raise DatasetAccessDeniedError(
                f"Operation '{operation}' is not permitted for dataset '{dataset_id}' "
                f"under policy '{access_policy['policy_id']}'."
            )
        now = datetime.now(timezone.utc).isoformat()
        grant = {
            "dataset_id": dataset_id,
            "dataset_version": package.dataset_version,
            "package_id": package.package_id,
            "operation": operation,
            "granted": True,
            "retrieval_status": evidence.status.value,
            "access_policy": access_policy["policy_id"],
            "timestamp": now,
            "access_location": self._build_access_location(package, operation),
            "schema_version": package.schema_version,
            "format": self._resolve_format(operation, params),
            "governance": {
                "owner": package.owner,
                "classification": access_policy["classification"],
                "sensitivity": access_policy["sensitivity"],
                "allowed_consumers": access_policy["allowed_consumers"],
                "intended_use": access_policy["intended_use"],
            },
            "traceability": {
                "dataset_version": package.dataset_version,
                "requested_version": dataset_version,
                "query_params": params,
                "retrieval_evidence_id": package.package_id,
            },
        }
        logger.info(
            "dataset_access_granted dataset_id=%s operation=%s package_id=%s status=%s",
            dataset_id, operation, package.package_id, evidence.status.value,
        )
        return grant


    def _to_dataset_summary(self, package: Any) -> Dict[str, Any]:
        return {
            "dataset_id": package.dataset_id,
            "package_id": package.package_id,
            "dataset_version": package.dataset_version,
            "schema_version": package.schema_version,
            "board": package.board,
            "medium": package.medium,
            "status": package.status.value,
            "owner": package.owner,
            "created_at": package.created_at,
        }

    def _to_dataset_detail(self, package: Any) -> Dict[str, Any]:
        knowledge_object = None
        try:
            ko = self.knowledge_object_service.get_by_package(package.package_id)
            if ko:
                knowledge_object = ko.model_dump(mode="json")
        except Exception:
            pass
        retrieval_evidence = None
        try:
            ev = self.retrieval_readiness_service.get_latest(package.package_id)
            if ev:
                retrieval_evidence = ev.model_dump(mode="json")
        except Exception:
            pass
        return {
            "dataset_id": package.dataset_id,
            "package_id": package.package_id,
            "dataset_version": package.dataset_version,
            "schema_version": package.schema_version,
            "board": package.board,
            "medium": package.medium,
            "language": package.language,
            "owner": package.owner,
            "status": package.status.value,
            "created_at": package.created_at,
            "updated_at": package.updated_at,
            "history": [t.model_dump(mode="json") for t in package.history],
            "knowledge_object": knowledge_object,
            "retrieval_evidence": retrieval_evidence,
        }

    def _resolve_access_policy(self, package: Any) -> Dict[str, Any]:
        if package.status in (PackageStatus.CERTIFIED, PackageStatus.RETRIEVAL_READY):
            return {
                "policy_id": f"policy-{package.dataset_id}-open-read",
                "classification": "BHIV-ECOSYSTEM-SHARED",
                "sensitivity": "low",
                "allowed_operations": ["query", "export", "stream", "reference"],
                "allowed_consumers": ["*"],
                "intended_use": "BHIV application data reuse",
            }
        return {
            "policy_id": f"policy-{package.dataset_id}-restricted",
            "classification": "BHIV-INTERNAL",
            "sensitivity": "medium",
            "allowed_operations": ["reference"],
            "allowed_consumers": [package.owner],
            "intended_use": "Internal review only",
        }

    def _build_access_location(self, package: Any, operation: str) -> str:
        base = os.environ.get("PRAVAH_MASTERDB_API", "https://masterdb.bhiv.eco")
        return f"{base}/datasets/{package.dataset_id}/{operation}"

    def _resolve_format(self, operation: str, params: Optional[Dict[str, Any]]) -> Optional[str]:
        if params and "format" in params:
            return params["format"]
        if operation == "stream":
            return "application/json+stream"
        if operation == "export":
            return "application/json"
        return None

