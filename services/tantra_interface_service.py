"""
MASTERDB <-> TANTRA Runtime Interface.

This is the one module TANTRA integrates against. It does not add new
ownership: every method is a thin, read-mostly façade over services
MASTERDB already owns (PackageRegistryService, KnowledgeObjectService,
RetrievalReadinessService, ReportService, RuntimeDiscoveryService).

TANTRA needs (per the integration brief):
  - dataset registration            -> register_dataset()
  - package discovery                -> discover_packages()
  - retrieval readiness queries       -> retrieval_readiness()
  - certification status queries      -> certification_status()
  - runtime package lookup            -> runtime_package_lookup()

No vector databases, embeddings, RAG, runtime reasoning, or governance
decisions happen here — MASTERDB certifies and describes packages; TANTRA
decides what to do with that information at runtime.
"""
from typing import Any, Dict, List, Optional

from models import (
    AccessContract,
    Capability,
    CapabilityAccessRequest,
    CapabilityContract,
    CapabilityRetrieveRequest,
    CapabilityRetrieveResponse,
    KnowledgePackage,
    PackageStatus,
)
from services.package_registry_service import (
    PackageNotFoundError,
    PackageRegistryService,
)
from services.knowledge_object_service import KnowledgeObjectService
from services.report_service import ReportService
from services.retrieval_readiness_service import RetrievalReadinessService
from services.runtime_discovery_service import RuntimeDiscoveryService
from services.capability_registry_service import (
    CapabilityAccessDeniedError,
    CapabilityNotFoundError,
    CapabilityRegistryService,
)


class TantraInterfaceService:
    def __init__(
        self,
        registry: Optional[PackageRegistryService] = None,
        knowledge_object_service: Optional[KnowledgeObjectService] = None,
        retrieval_readiness_service: Optional[RetrievalReadinessService] = None,
        report_service: Optional[ReportService] = None,
        discovery_service: Optional[RuntimeDiscoveryService] = None,
        capability_service: Optional[CapabilityRegistryService] = None,
    ) -> None:
        self.registry = registry or PackageRegistryService()
        self.knowledge_object_service = knowledge_object_service or KnowledgeObjectService(
            registry=self.registry
        )
        self.retrieval_readiness_service = retrieval_readiness_service or RetrievalReadinessService(
            registry=self.registry, knowledge_object_service=self.knowledge_object_service
        )
        self.report_service = report_service or ReportService()
        self.discovery_service = discovery_service or RuntimeDiscoveryService(registry=self.registry)
        self.capability_service = capability_service or CapabilityRegistryService(
            package_registry=self.registry
        )

    # -- dataset registration -------------------------------------------------

    def register_dataset(
        self,
        dataset_id: str,
        dataset_version: str,
        schema_version: str,
        board: str,
        medium: str,
        language: str,
        owner: str,
        actor: str = "tantra",
        reason: str = "Registered via TANTRA runtime interface.",
    ) -> KnowledgePackage:
        return self.registry.register(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            schema_version=schema_version,
            board=board,
            medium=medium,
            language=language,
            owner=owner,
            actor=actor,
            reason=reason,
        )

    # -- package discovery ----------------------------------------------------

    def discover_packages(
        self,
        package_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        board: Optional[str] = None,
        medium: Optional[str] = None,
        version: Optional[str] = None,
        status: Optional[PackageStatus] = None,
    ) -> List[Dict[str, Any]]:
        return self.discovery_service.discover_as_dicts(
            package_id=package_id,
            dataset_id=dataset_id,
            board=board,
            medium=medium,
            version=version,
            status=status,
        )

    # -- capability discovery & contract resolution --------------------------

    def discover_capabilities(
        self,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Capability]:
        return self.capability_service.list_capabilities(domain=domain, status=status, search=search)

    def get_capability(self, capability_id: str) -> Capability:
        return self.capability_service.get_capability(capability_id)

    def get_capability_contract(self, capability_id: str) -> CapabilityContract:
        return self.capability_service.get_contract(capability_id)

    def request_capability_access(
        self,
        actor: str,
        roles: List[str],
        request_data: CapabilityAccessRequest,
    ) -> AccessContract:
        return self.capability_service.request_access(actor=actor, roles=roles, request_data=request_data)

    def retrieve_capability_data(
        self,
        actor: str,
        roles: List[str],
        capability_id: str,
        retrieve_req: CapabilityRetrieveRequest,
    ) -> CapabilityRetrieveResponse:
        return self.capability_service.retrieve(
            actor=actor, roles=roles, capability_id=capability_id, retrieve_req=retrieve_req
        )

    # -- retrieval readiness ---------------------------------------------------

    def retrieval_readiness(self, package_id: str) -> Dict[str, Any]:
        evidence = self.retrieval_readiness_service.assess(package_id)
        return evidence.model_dump(mode="json")

    # -- certification status --------------------------------------------------

    def certification_status(self, dataset_id: str) -> Dict[str, Any]:
        try:
            return self.report_service.get_status(dataset_id)
        except KeyError as exc:
            raise CertificationStatusNotFoundError(
                f"No certification status found for dataset_id={dataset_id}"
            ) from exc

    # -- runtime package lookup --------------------------------------------------

    def runtime_package_lookup(self, package_id: str) -> Dict[str, Any]:
        """
        The single bundled view TANTRA fetches at runtime for a package:
        lifecycle state, lineage, and retrieval readiness in one call, plus
        certification status when a matching certification report exists
        under the same identifier (best-effort — certification is keyed by
        dataset_id, package lookup is keyed by package_id, so this is
        included only when it resolves cleanly).
        """
        package = self.registry.get(package_id)  # raises PackageNotFoundError
        lineage = self.knowledge_object_service.lineage(package_id)
        retrieval = self.retrieval_readiness(package_id)

        certification: Optional[Dict[str, Any]] = None
        try:
            certification = self.report_service.get_status(package.dataset_id)
        except KeyError:
            certification = None

        return {
            "package": package.model_dump(mode="json"),
            "lineage": lineage,
            "retrieval_readiness": retrieval,
            "certification_status": certification,
        }


class CertificationStatusNotFoundError(KeyError):
    pass

