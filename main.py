import logging
import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv


load_dotenv()
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from models import (
    CertificationRequest,
    KnowledgeObjectRegisterRequest,
    PackageDeprecateRequest,
    PackagePromoteRequest,
    PackageRegisterRequest,
    PackageStatus,
    SharedRecordDeprecateRequest,
    SharedRecordRegisterRequest,
    SharedRecordUpdateRequest,
    ValidationRequest,
)
from services.artifact_store import ArtifactStore
from services.certification_service import CertificationService
from services.knowledge_object_service import (
    KnowledgeObjectService,
    LineageValidationError,
    VersionIncompatibleError,
)
from services.mdu_client import MDUUnavailableError
from services.mdu_contract_adapter import MDUContractAdapter
from services.package_registry_service import (
    InvalidTransitionError,
    PackageNotFoundError,
    PackageRegistryService,
)
from services.report_service import ReportService
from services.retrieval_readiness_service import RetrievalReadinessService
from services.runtime_discovery_service import RuntimeDiscoveryService
from services.shared_data_registry_service import (
    SharedDataRegistryService,
    SharedDatasetNotFoundError,
)
from services.shared_dependency_resolver import SharedDependencyResolver
from services.shared_platform_services import SERVICE_CONTRACTS, build_shared_service_registry
from services.shared_record_store import (
    SharedRecordDeprecatedError,
    SharedRecordExistsError,
    SharedRecordNotFoundError,
    SharedRecordStore,
    SharedRecordValidationError,
)
from services.shared_version_compatibility import negotiate_version as shared_negotiate_version
from services.tantra_interface_service import (
    CertificationStatusNotFoundError,
    TantraInterfaceService,
)
from services.validation_service import ValidationService

from bcaes_registry.convergence_models import ConvergenceUpdateRequest as BCAESConvergenceUpdateRequest
from bcaes_registry.models import RegisterObjectRequest as BCAESRegisterObjectRequest
from bcaes_registry.models import RegistryType as BCAESRegistryType
from bcaes_registry.models import UpdateObjectRequest as BCAESUpdateObjectRequest
from bcaes_registry.service import BCAESRegistryService
from bcaes_registry.store import DependencyNotFoundError as BCAESDependencyNotFoundError
from bcaes_registry.store import ObjectNotFoundError as BCAESObjectNotFoundError
from bcaes_registry.store import PermissionDeniedError as BCAESPermissionDeniedError

from operational_sync.models import (
    UpsertOperationalTaskStateRequest,
    UpsertReviewReferenceRequest,
)
from operational_sync.service import NiyantranSyncService, ParikshakSyncService, SyncPermissionDeniedError

from services.sql_artifact_store import SqlArtifactStore
from auth.constants import ADMIN_ROLE
from auth.dependencies import build_identity_dependency
from auth.models import AuthIdentity, TokenRequest, TokenResponse
from auth.service import AuthService

from canonical_repository.models import DocumentCategory as CanonicalDocumentCategory
from canonical_repository.models import PublishVersionRequest as CanonicalPublishVersionRequest
from canonical_repository.models import RegisterDocumentRequest as CanonicalRegisterDocumentRequest
from canonical_repository.service import CanonicalRepositoryService
from canonical_repository.store import DocumentNotFoundError as CanonicalDocumentNotFoundError
from canonical_repository.store import DuplicateCategoryError as CanonicalDuplicateCategoryError
from canonical_repository.store import PermissionDeniedError as CanonicalPermissionDeniedError



app = FastAPI(
    title="MASTERDB Core Knowledge Platform",
    version="1.3.0",
)

logger = logging.getLogger("masterdb")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s masterdb: %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Separate logger/stream for audit events (every mutating bcaes_registry and
# canonical_repository call) so these can be filtered/shipped independently
# of general application logs. Same stdout-only approach as `logger` above —
# a real production setup would ship this to a dedicated log sink; that's
# infra this sandbox can't stand up (see PRODUCTION_HARDENING.md).
audit_logger = logging.getLogger("masterdb.audit")
if not audit_logger.handlers:
    _audit_handler = logging.StreamHandler()
    _audit_handler.setFormatter(logging.Formatter("%(asctime)s AUDIT masterdb: %(message)s"))
    audit_logger.addHandler(_audit_handler)
    audit_logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Phase 4 — Uniform error contract
#
# Every error response (validation failure, missing entity, invalid
# transition, upstream MDU failure, or unhandled exception) is shaped the
# same way so downstream consumers (TANTRA included) can parse errors
# generically instead of branching on endpoint-specific bodies.
#   { "error": { "type": str, "message": str, "path": str } }
# ---------------------------------------------------------------------------


def _error_body(request: Request, error_type: str, message: str) -> Dict[str, Any]:
    return {"error": {"type": error_type, "message": message, "path": request.url.path}}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    logger.warning("HTTPException %s at %s: %s", exc.status_code, request.url.path, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(request, "http_error", str(exc.detail)),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception at %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=_error_body(request, "internal_error", "An unexpected error occurred."),
    )


artifact_store = ArtifactStore()
validation_service = ValidationService(artifact_store=artifact_store)
certification_service = CertificationService(
    validation_service=validation_service,
    artifact_store=artifact_store,
)
report_service = ReportService(artifact_store=artifact_store)

# --- MASTERDB knowledge platform runtime (Knowledge Package Lifecycle,
# Provenance/Lineage, Retrieval Readiness) ---------------------------------
package_registry_service = PackageRegistryService()
knowledge_object_service = KnowledgeObjectService(registry=package_registry_service)
retrieval_readiness_service = RetrievalReadinessService(
    registry=package_registry_service,
    knowledge_object_service=knowledge_object_service,
)

# --- Ecosystem integration surfaces: MDU (Nupur), TANTRA, Runtime Discovery --
mdu_contract_adapter = MDUContractAdapter()
runtime_discovery_service = RuntimeDiscoveryService(registry=package_registry_service)
tantra_interface_service = TantraInterfaceService(
    registry=package_registry_service,
    knowledge_object_service=knowledge_object_service,
    retrieval_readiness_service=retrieval_readiness_service,
    report_service=report_service,
    discovery_service=runtime_discovery_service,
)

# --- Task 4: Shared Data Services & MASTERDB Convergence ------------------
# MASTERDB's shared operational data layer sitting between Product
# Databases and MDU. See MASTERDB_SHARED_DATA_ARCHITECTURE.md.
shared_data_registry_service = SharedDataRegistryService()
shared_service_registry = build_shared_service_registry()

# --- Storage root for opt-in disk persistence -------------------------------
# Unset (the default): both services below stay pure in-memory, exactly as
# before this pass — this matters for test isolation (every test module's
# fixtures recreate these services fresh) and for local dev where nobody
# asked for persistence. Set MASTERDB_STORAGE_DIR to opt in for real.
# NOTE: on Render's default (non-Disk) plans the filesystem is ephemeral and
# is wiped on every deploy/restart — this directory needs a persistent Disk
# attached in Render's dashboard to actually survive across restarts in
# production. See PRODUCTION_HARDENING.md.
_STORAGE_ROOT = os.environ.get("MASTERDB_STORAGE_DIR")

# --- Real database backend --------------------------------------------------
# Set MASTERDB_DATABASE_URL to back both services with a real SQL database
# (services/sql_artifact_store.py) instead of JSON files — this is what
# "MASTERDB will have a real central database" (task lead, 3 Aug 2026)
# means concretely. Takes priority over MASTERDB_STORAGE_DIR when both are
# set. Any SQLAlchemy-supported URL works (sqlite:///path.db for local/dev
# with zero external dependencies, postgresql://... for real production).
# See DATABASE.md for the schema/design rationale and why this doesn't
# change the fact that external services reach this data through the
# authenticated API, not raw database credentials.
_DATABASE_URL = os.environ.get("MASTERDB_DATABASE_URL")


def _persist_path(subdir: str) -> Optional[str]:
    return os.path.join(_STORAGE_ROOT, subdir) if _STORAGE_ROOT else None


def _sql_store(subdir: str):
    if not _DATABASE_URL:
        return None
    return SqlArtifactStore(_DATABASE_URL, store_name=subdir)


# --- BCAES Canonical Registry (ecosystem bootstrap) ------------------------
# Catalogs architectural objects (domains, capabilities, platform services,
# products, programs, frameworks, engines, runtimes, integrations, knowledge
# assets, interfaces). See BCAES_REGISTRY_ARCHITECTURE.md.
bcaes_registry_service = BCAESRegistryService(
    persist_dir=_persist_path("bcaes_registry"), artifact_store=_sql_store("bcaes_registry")
)

# --- BCAB/BCAES Canonical Document Repository -------------------------------
# Single source of truth for the BCAB and BCAES Volume 1-7 *documents*
# themselves (distinct from the object registry above, which catalogs the
# ecosystem's products/capabilities/services). See
# CANONICAL_REPOSITORY_ARCHITECTURE.md. Content is placeholder until the
# task owner populates it centrally.
canonical_repository_service = CanonicalRepositoryService(
    persist_dir=_persist_path("canonical_repository"), artifact_store=_sql_store("canonical_repository")
)

# --- Auth (JWT issuance + verification) --------------------------------------
# See auth/service.py module docstring for exactly what this does and does
# not prove. get_identity is a FastAPI dependency bound to this specific
# auth_service instance/secret.
auth_service = AuthService()
get_identity = build_identity_dependency(auth_service)

# --- Operational sync (PARIKSHAK review references, NIYANTRAN task state) ---
# See operational_sync/models.py for the direction assumption (MASTERDB
# ingests pushed records; no live PARIKSHAK/NIYANTRAN endpoint has been
# confirmed reachable to poll instead).
parikshak_sync_service = ParikshakSyncService()
niyantran_sync_service = NiyantranSyncService()
shared_dependency_resolver = SharedDependencyResolver(shared_service_registry)


def _shared_service(service_name: str) -> SharedRecordStore:
    service = shared_service_registry.get(service_name)
    if service is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown shared service '{service_name}'. Available: "
            f"{sorted(shared_service_registry.keys())}",
        )
    return service


@app.post("/validate")
def validate_dataset(request: ValidationRequest) -> dict:
    try:
        report = validation_service.validate(
            dataset_path=request.dataset_path,
            metadata_path=request.metadata_path,
            dataset_id=request.dataset_id,
        )
        return {
            "dataset_id": report["dataset_id"],
            "state": report["state"],
            "report": report,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/certify")
def certify_dataset(request: CertificationRequest) -> dict:
    try:
        report = certification_service.certify(
            dataset_id=request.dataset_id,
            dataset_path=request.dataset_path,
            metadata_path=request.metadata_path,
        )
        return {
            "dataset_id": report["dataset_id"],
            "state": report["state"],
            "decision": report["ingestion_decision"],
            "report": report,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/status/{dataset_id}")
def get_status(dataset_id: str) -> dict:
    try:
        return report_service.get_status(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/report/{dataset_id}")
def get_report(dataset_id: str) -> dict:
    try:
        return report_service.get_report(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Phase 4 — MASTERDB Registry API
# ---------------------------------------------------------------------------


@app.post("/packages/register")
def register_package(request: PackageRegisterRequest) -> dict:
    package = package_registry_service.register(
        dataset_id=request.dataset_id,
        dataset_version=request.dataset_version,
        schema_version=request.schema_version,
        board=request.board,
        medium=request.medium,
        language=request.language,
        owner=request.owner,
        actor=request.actor,
        reason=request.reason,
    )
    return package.model_dump(mode="json")


@app.post("/packages/promote")
def promote_package(request: PackagePromoteRequest) -> dict:
    try:
        package = package_registry_service.promote(
            package_id=request.package_id,
            to_status=request.to_status,
            actor=request.actor,
            reason=request.reason,
        )
        return package.model_dump(mode="json")
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/packages/deprecate")
def deprecate_package(request: PackageDeprecateRequest) -> dict:
    try:
        package = package_registry_service.deprecate(
            package_id=request.package_id,
            actor=request.actor,
            reason=request.reason,
        )
        return package.model_dump(mode="json")
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/packages/{package_id}")
def get_package(package_id: str) -> dict:
    try:
        return package_registry_service.get(package_id).model_dump(mode="json")
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/packages/{package_id}/history")
def get_package_history(package_id: str) -> dict:
    try:
        history = package_registry_service.history(package_id)
        return {
            "package_id": package_id,
            "history": [record.model_dump(mode="json") for record in history],
        }
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/packages/{package_id}/replay")
def replay_package(package_id: str) -> dict:
    """Phase 4 — replay consistency: recompute status purely from history."""
    try:
        replayed_status = package_registry_service.replay(package_id)
        return {
            "package_id": package_id,
            "replay_consistent": True,
            "replayed_status": replayed_status.value,
        }
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        return {
            "package_id": package_id,
            "replay_consistent": False,
            "replay_error": str(exc),
        }


@app.get("/packages/{package_id}/audit")
def audit_package(package_id: str) -> dict:
    """Phase 4 — audit completeness report for a package's transition history."""
    try:
        return package_registry_service.audit_completeness(package_id)
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/packages/{package_id}/knowledge-object")
def register_knowledge_object(package_id: str, request: KnowledgeObjectRegisterRequest) -> dict:
    if request.package_id != package_id:
        raise HTTPException(
            status_code=400,
            detail="package_id in the path and request body must match.",
        )
    try:
        knowledge_object = knowledge_object_service.register_object(
            package_id=request.package_id,
            parent_package=request.parent_package,
            source_reference=request.source_reference,
            lineage_reference=request.lineage_reference,
            derivation_path=request.derivation_path,
        )
        return knowledge_object.model_dump(mode="json")
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (VersionIncompatibleError, LineageValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/packages/{package_id}/lineage")
def get_package_lineage(package_id: str) -> dict:
    try:
        package_registry_service.get(package_id)  # confirms the package exists
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return knowledge_object_service.lineage(package_id)


@app.get("/packages/{package_id}/retrieval")
def get_package_retrieval(package_id: str) -> dict:
    try:
        evidence = retrieval_readiness_service.assess(package_id)
        return evidence.model_dump(mode="json")
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Phase 1 — Live MDU Integration
#
# MASTERDB does not own schema/provenance/lineage semantics; these endpoints
# expose what MDU reports, plus MASTERDB's own version-negotiation decision
# on top of it. If MDU is unconfigured/unreachable, responses degrade to a
# flagged placeholder rather than failing the caller outright.
# ---------------------------------------------------------------------------


@app.get("/mdu/status")
def mdu_status() -> dict:
    return {
        "live": mdu_contract_adapter.is_live(),
        "contract_finalized": mdu_contract_adapter.is_contract_finalized(),
        "known_gaps": mdu_contract_adapter.known_gaps(),
    }


@app.get("/mdu/schema/{dataset_id}")
def mdu_schema(dataset_id: str) -> dict:
    try:
        return mdu_contract_adapter.fetch_schema_contract(dataset_id)
    except MDUUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/mdu/provenance/{dataset_id}")
def mdu_provenance(dataset_id: str) -> list:
    try:
        return mdu_contract_adapter.fetch_provenance_contract(dataset_id)
    except MDUUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/mdu/schema-compatibility/{dataset_id}")
def mdu_schema_compatibility(dataset_id: str, local_schema_version: str) -> dict:
    return mdu_contract_adapter.validate_schema_compatibility(
        dataset_id=dataset_id, local_schema_version=local_schema_version
    )


# ---------------------------------------------------------------------------
# Phase 2 — MASTERDB <-> TANTRA Runtime Interface
# ---------------------------------------------------------------------------


@app.post("/tantra/datasets/register")
def tantra_register_dataset(request: PackageRegisterRequest) -> dict:
    package = tantra_interface_service.register_dataset(
        dataset_id=request.dataset_id,
        dataset_version=request.dataset_version,
        schema_version=request.schema_version,
        board=request.board,
        medium=request.medium,
        language=request.language,
        owner=request.owner,
        actor=request.actor,
        reason=request.reason,
    )
    return package.model_dump(mode="json")


@app.get("/tantra/packages/{package_id}/retrieval-readiness")
def tantra_retrieval_readiness(package_id: str) -> dict:
    try:
        return tantra_interface_service.retrieval_readiness(package_id)
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/tantra/certification/{dataset_id}")
def tantra_certification_status(dataset_id: str) -> dict:
    try:
        return tantra_interface_service.certification_status(dataset_id)
    except CertificationStatusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/tantra/packages/{package_id}/runtime")
def tantra_runtime_package_lookup(package_id: str) -> dict:
    try:
        return tantra_interface_service.runtime_package_lookup(package_id)
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Phase 3 — Runtime Discovery API
#
# Shared by TANTRA and any other downstream consumer. Deterministic filtered
# lookup only — no ranking, no relevance scoring.
# ---------------------------------------------------------------------------


@app.get("/discovery/packages")
def discover_packages(
    package_id: Optional[str] = Query(default=None),
    dataset_id: Optional[str] = Query(default=None),
    board: Optional[str] = Query(default=None),
    medium: Optional[str] = Query(default=None),
    version: Optional[str] = Query(default=None),
    status: Optional[PackageStatus] = Query(default=None),
) -> dict:
    results = runtime_discovery_service.discover_as_dicts(
        package_id=package_id,
        dataset_id=dataset_id,
        board=board,
        medium=medium,
        version=version,
        status=status,
    )
    return {"count": len(results), "packages": results}


# ---------------------------------------------------------------------------
# Task 4 — Shared Data Services & MASTERDB Convergence
#
# MASTERDB's shared operational data layer: reusable ecosystem datasets
# (Authentication, Identity, Organizations, Configuration, Knowledge
# References, Notifications, ...) sitting between Product Databases and
# MDU. See MASTERDB_SHARED_DATA_ARCHITECTURE.md for the full model.
#
# Route order matters: static paths (/shared/registry, /shared/contracts,
# /shared/version-compatibility) are declared BEFORE the generic
# /shared/{service_name} catch-alls so they are never shadowed.
# ---------------------------------------------------------------------------


@app.get("/shared/registry")
def list_shared_data_registry() -> dict:
    entries = shared_data_registry_service.list_all()
    return {"count": len(entries), "datasets": entries}


@app.get("/shared/registry/{dataset_name}")
def get_shared_dataset_definition(dataset_name: str) -> dict:
    try:
        return shared_data_registry_service.get(dataset_name)
    except SharedDatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/shared/contracts")
def list_shared_service_contracts() -> dict:
    return {"count": len(SERVICE_CONTRACTS), "contracts": SERVICE_CONTRACTS}


@app.get("/shared/contracts/{service_name}")
def get_shared_service_contract(service_name: str) -> dict:
    contract = SERVICE_CONTRACTS.get(service_name)
    if contract is None:
        raise HTTPException(
            status_code=404, detail=f"No contract found for service '{service_name}'."
        )
    return {"service": service_name, **contract}


@app.get("/shared/version-compatibility")
def shared_version_compatibility(local_version: str, remote_version: str) -> dict:
    return shared_negotiate_version(local_version, remote_version)


@app.post("/shared/{service_name}/register")
def register_shared_record(service_name: str, request: SharedRecordRegisterRequest) -> dict:
    service = _shared_service(service_name)
    try:
        record = service.register(
            record_id=request.record_id,
            payload=request.payload,
            actor=request.actor,
            reason=request.reason,
        )
        return record.model_dump(mode="json")
    except SharedRecordExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SharedRecordValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/shared/{service_name}/{record_id}")
def update_shared_record(service_name: str, record_id: str, request: SharedRecordUpdateRequest) -> dict:
    service = _shared_service(service_name)
    try:
        record = service.update(
            record_id=record_id,
            payload=request.payload,
            actor=request.actor,
            reason=request.reason,
        )
        return record.model_dump(mode="json")
    except SharedRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SharedRecordValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SharedRecordDeprecatedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/shared/{service_name}/{record_id}/deprecate")
def deprecate_shared_record(service_name: str, record_id: str, request: SharedRecordDeprecateRequest) -> dict:
    service = _shared_service(service_name)
    try:
        record = service.deprecate(record_id=record_id, actor=request.actor, reason=request.reason)
        return record.model_dump(mode="json")
    except SharedRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SharedRecordDeprecatedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/shared/{service_name}")
def list_shared_records(service_name: str) -> dict:
    service = _shared_service(service_name)
    records = [r.model_dump(mode="json") for r in service.list_all()]
    return {"service": service_name, "count": len(records), "records": records}


@app.get("/shared/{service_name}/{record_id}")
def get_shared_record(service_name: str, record_id: str) -> dict:
    service = _shared_service(service_name)
    try:
        return service.get(record_id).model_dump(mode="json")
    except SharedRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/shared/{service_name}/{record_id}/history")
def get_shared_record_history(service_name: str, record_id: str) -> dict:
    service = _shared_service(service_name)
    try:
        history = service.history(record_id)
        return {
            "service": service_name,
            "record_id": record_id,
            "history": [t.model_dump(mode="json") for t in history],
        }
    except SharedRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/shared/{service_name}/{record_id}/replay")
def replay_shared_record(service_name: str, record_id: str) -> dict:
    service = _shared_service(service_name)
    try:
        return service.replay(record_id)
    except SharedRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/shared/{service_name}/{record_id}/resolve")
def resolve_shared_record_dependencies(service_name: str, record_id: str) -> dict:
    _shared_service(service_name)  # validates service_name, 404s cleanly if unknown
    try:
        return shared_dependency_resolver.resolve(service_name, record_id)
    except SharedRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

# ---------------------------------------------------------------------------
# BCAES Canonical Registry API — ecosystem bootstrap (BCAES Volumes 4-7)
# ---------------------------------------------------------------------------


def _bcaes_registry_type(registry_type: str) -> BCAESRegistryType:
    try:
        return BCAESRegistryType(registry_type)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown registry type '{registry_type}'.",
        )


@app.post("/bcaes/registries/{registry_type}/objects")
def register_bcaes_object(
    registry_type: str, request: BCAESRegisterObjectRequest, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    rt = _bcaes_registry_type(registry_type)
    try:
        obj = bcaes_registry_service.register(rt, request, actor=identity.actor, actor_roles=identity.roles)
        audit_logger.info(
            "bcaes.register actor=%s registry_type=%s object_id=%s", identity.actor, registry_type, obj.id
        )
        return obj.model_dump(mode="json")
    except BCAESDependencyNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BCAESPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/bcaes/registries")
def list_bcaes_registries() -> dict:
    return {"registries": bcaes_registry_service.registry_summary()}


@app.get("/bcaes/registries/{registry_type}/objects")
def list_bcaes_registry_objects(registry_type: str) -> dict:
    rt = _bcaes_registry_type(registry_type)
    objects = bcaes_registry_service.list_registry(rt)
    return {"registry_type": rt.value, "objects": [o.model_dump(mode="json") for o in objects]}


@app.get("/bcaes/registries/{registry_type}/objects/{object_id}")
def get_bcaes_object(registry_type: str, object_id: str) -> dict:
    rt = _bcaes_registry_type(registry_type)
    try:
        return bcaes_registry_service.get(rt, object_id).model_dump(mode="json")
    except BCAESObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/bcaes/registries/{registry_type}/objects/{object_id}")
def update_bcaes_object(
    registry_type: str,
    object_id: str,
    request: BCAESUpdateObjectRequest,
    identity: AuthIdentity = Depends(get_identity),
) -> dict:
    rt = _bcaes_registry_type(registry_type)
    try:
        obj = bcaes_registry_service.update(
            rt, object_id, request, actor=identity.actor, actor_roles=identity.roles
        )
        audit_logger.info("bcaes.update actor=%s object_id=%s", identity.actor, object_id)
        return obj.model_dump(mode="json")
    except BCAESObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BCAESDependencyNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BCAESPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.delete("/bcaes/registries/{registry_type}/objects/{object_id}")
def delete_bcaes_object(
    registry_type: str, object_id: str, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    rt = _bcaes_registry_type(registry_type)
    try:
        bcaes_registry_service.delete(rt, object_id, actor=identity.actor, actor_roles=identity.roles)
        audit_logger.info("bcaes.delete actor=%s object_id=%s", identity.actor, object_id)
        return {"deleted": object_id}
    except BCAESObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BCAESPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/bcaes/search")
def search_bcaes_registry(
    q: Optional[str] = Query(default=None),
    registry_type: Optional[str] = Query(default=None),
    owner: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
) -> dict:
    rt = _bcaes_registry_type(registry_type) if registry_type else None
    results = bcaes_registry_service.search(query=q, registry_type=rt, owner=owner, status=status)
    return {"count": len(results), "results": [o.model_dump(mode="json") for o in results]}


@app.get("/bcaes/relationships/{object_id}")
def get_bcaes_relationships(object_id: str) -> dict:
    try:
        return bcaes_registry_service.relationships(object_id)
    except BCAESObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/bcaes/dependencies/{object_id}")
def get_bcaes_dependencies(object_id: str) -> dict:
    try:
        return bcaes_registry_service.transitive_dependencies(object_id)
    except BCAESObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/bcaes/capability-reuse-check")
def bcaes_capability_reuse_check(name: str) -> dict:
    return bcaes_registry_service.capability_reuse_check(name)


@app.get("/bcaes/validate/classification")
def validate_bcaes_classification() -> dict:
    return bcaes_registry_service.validate_classification()


@app.get("/bcaes/validate/duplicates")
def validate_bcaes_duplicates() -> dict:
    return bcaes_registry_service.detect_duplicates()


@app.get("/bcaes/validate/ownership")
def validate_bcaes_ownership() -> dict:
    return bcaes_registry_service.validate_ownership()


@app.get("/bcaes/validate/authority-boundaries")
def validate_bcaes_authority_boundaries() -> dict:
    return bcaes_registry_service.validate_authority_boundaries()


@app.get("/bcaes/validate/version-compatibility")
def validate_bcaes_version_compatibility() -> dict:
    return bcaes_registry_service.validate_version_compatibility()


@app.get("/bcaes/validate/dependency-integrity")
def validate_bcaes_dependency_integrity() -> dict:
    return bcaes_registry_service.validate_dependency_integrity()


@app.get("/bcaes/validate/architecture")
def validate_bcaes_architecture() -> dict:
    return bcaes_registry_service.validate_architecture()


# ---------------------------------------------------------------------------
# BCAES Production Convergence (Volume 6) & Current Reality Snapshot (Volume 7)
# ---------------------------------------------------------------------------


@app.post("/bcaes/convergence/{object_id}")
def upsert_bcaes_convergence(object_id: str, request: BCAESConvergenceUpdateRequest) -> dict:
    try:
        record = bcaes_registry_service.upsert_convergence(object_id, request)
        return record.model_dump(mode="json")
    except BCAESObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/bcaes/convergence/{object_id}")
def get_bcaes_convergence(object_id: str) -> dict:
    try:
        record = bcaes_registry_service.get_convergence(object_id)
        return record.model_dump(mode="json") | {"maturity_score": record.maturity_score}
    except BCAESObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/bcaes/convergence")
def list_bcaes_convergence() -> dict:
    records = bcaes_registry_service.list_convergence()
    return {
        "count": len(records),
        "records": [
            r.model_dump(mode="json") | {"maturity_score": r.maturity_score} for r in records
        ],
    }


@app.get("/bcaes/snapshot")
def get_bcaes_snapshot() -> dict:
    return bcaes_registry_service.generate_snapshot()


# ---------------------------------------------------------------------------
# BCAB/BCAES Canonical Document Repository
# ---------------------------------------------------------------------------
# Every route requires a verified JWT (Authorization: Bearer <token>, issued
# by POST /auth/token) — reads included, not just writes. This replaced a
# schema-only pass (self-reported `actor`/`roles` query params, nothing
# checked) once real signed-token infrastructure existed to enforce against.
# See canonical_repository/service.py module docstring for exactly what's
# checked, and auth/service.py for what "verified" does and doesn't mean.


@app.post("/canonical-repository/documents")
def register_canonical_document(
    request: CanonicalRegisterDocumentRequest, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    try:
        doc = canonical_repository_service.register(request, identity.actor, identity.roles)
        audit_logger.info(
            "canonical_repository.register actor=%s category=%s document_id=%s",
            identity.actor, request.category.value, doc.id,
        )
        return doc.model_dump(mode="json")
    except CanonicalDuplicateCategoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CanonicalPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/canonical-repository/documents")
def list_canonical_documents(identity: AuthIdentity = Depends(get_identity)) -> dict:
    docs = canonical_repository_service.list_all(identity.actor, identity.roles)
    return {"count": len(docs), "documents": [d.model_dump(mode="json") for d in docs]}


@app.get("/canonical-repository/documents/{document_id}")
def get_canonical_document(document_id: str, identity: AuthIdentity = Depends(get_identity)) -> dict:
    try:
        return canonical_repository_service.get(document_id, identity.actor, identity.roles).model_dump(
            mode="json"
        )
    except CanonicalDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CanonicalPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/canonical-repository/by-category/{category}")
def get_canonical_document_by_category(
    category: str, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    try:
        cat = CanonicalDocumentCategory(category)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown document category '{category}'.")
    try:
        return canonical_repository_service.get_by_category(
            cat, identity.actor, identity.roles
        ).model_dump(mode="json")
    except CanonicalDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CanonicalPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/canonical-repository/documents/{document_id}/versions")
def publish_canonical_document_version(
    document_id: str,
    request: CanonicalPublishVersionRequest,
    identity: AuthIdentity = Depends(get_identity),
) -> dict:
    try:
        version = canonical_repository_service.publish_version(
            document_id, request, identity.actor, identity.roles
        )
        audit_logger.info(
            "canonical_repository.publish_version actor=%s document_id=%s version=%s",
            identity.actor, document_id, version.version_number,
        )
        return version.model_dump(mode="json")
    except CanonicalDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CanonicalPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/canonical-repository/documents/{document_id}/versions")
def list_canonical_document_versions(
    document_id: str, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    try:
        versions = canonical_repository_service.version_history(document_id, identity.actor, identity.roles)
        return {"document_id": document_id, "versions": [v.model_dump(mode="json") for v in versions]}
    except CanonicalDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CanonicalPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/canonical-repository/documents/{document_id}/versions/{version_number}")
def get_canonical_document_version(
    document_id: str, version_number: int, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    try:
        version = canonical_repository_service.get_version(
            document_id, version_number, identity.actor, identity.roles
        )
        return version.model_dump(mode="json")
    except CanonicalDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CanonicalPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/canonical-repository/documents/{document_id}/latest")
def get_canonical_document_latest(
    document_id: str, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    try:
        version = canonical_repository_service.latest_version(document_id, identity.actor, identity.roles)
        return version.model_dump(mode="json")
    except CanonicalDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CanonicalPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/canonical-repository/documents/{document_id}/verify")
def verify_canonical_document_chain(
    document_id: str, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    try:
        return canonical_repository_service.verify_chain(document_id, identity.actor, identity.roles)
    except CanonicalDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CanonicalPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Auth — token issuance
# ---------------------------------------------------------------------------


@app.post("/auth/token", response_model=None)
def issue_token(request: TokenRequest) -> dict:
    """Issues a signed, expiring JWT for the given actor/roles. See
    auth/service.py and auth/models.py module docstrings: this does not
    verify the caller's real-world identity (no login step exists), but
    the token itself is real — signed, tamper-evident, and time-limited —
    and every write (and, for the canonical repository, every read) checks
    the roles inside it for real."""
    token, expires_at = auth_service.issue_token(request.actor, request.roles)
    return TokenResponse(
        access_token=token, actor=request.actor, roles=request.roles, expires_at=expires_at
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up and able to respond. Does not touch any
    store or dependency."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    """Readiness: the process is up AND its core stores are reachable and
    responding. Deliberately does not check TANTRA/MDU/Bucket/InsightFlow —
    this service has no live connection to any of them to check (see
    PRODUCTION_HARDENING.md)."""
    checks = {}
    ok = True
    try:
        bcaes_registry_service.registry_summary()
        checks["bcaes_registry"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness probe, report any failure
        checks["bcaes_registry"] = f"error: {exc}"
        ok = False
    try:
        canonical_repository_service.list_all(actor="_readiness_probe", actor_roles=[])
        checks["canonical_repository"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["canonical_repository"] = f"error: {exc}"
        ok = False
    status_code = 200 if ok else 503
    return JSONResponse(status_code=status_code, content={"status": "ok" if ok else "degraded", "checks": checks})


# ---------------------------------------------------------------------------
# Runtime Identity — self-description manifest for TANTRA Runtime Registry
# registration (Rajaryan Verma's integration point per the Constitutional
# Runtime Convergence brief). MASTERDB exposes this; it does not call out to
# a TANTRA registry endpoint, since no such endpoint/contract has been
# confirmed as reachable from this environment. This is the shape a real
# registration call would need to read FROM MASTERDB.
# ---------------------------------------------------------------------------


@app.get("/runtime/identity")
def runtime_identity() -> dict:
    return {
        "service_name": "MASTERDB",
        "version": app.version,
        "constitutional_role": "Knowledge Layer participant",
        "capabilities": [
            "dataset-validation-certification",
            "knowledge-package-lifecycle",
            "knowledge-object-provenance-consumption",
            "retrieval-readiness-evidence",
            "bcaes-canonical-registry",
            "bcaes-canonical-document-repository",
            "shared-data-services",
        ],
        "api_groups": {
            "certification": "/validate, /certify",
            "knowledge_packages": "/packages/*",
            "knowledge_objects": "/knowledge-objects/*",
            "shared_data": "/shared/*",
            "bcaes_registry": "/bcaes/*",
            "canonical_repository": "/canonical-repository/*",
            "auth": "/auth/token",
            "runtime": "/runtime/identity, /health, /ready, /metrics",
        },
        "auth": {
            "method": "bearer_jwt",
            "token_endpoint": "/auth/token",
            "note": "Signed/expiring tokens; issuance does not itself verify "
            "caller identity — see auth/service.py for the exact boundary.",
        },
        "health_check_url": "/health",
        "readiness_check_url": "/ready",
        "openapi_url": "/openapi.json",
        "replay_endpoints": {
            "bcaes_registry_architecture": "/bcaes/validate/architecture",
            "canonical_repository_document": "/canonical-repository/documents/{document_id}/verify",
        },
        "status": "not_yet_registered",
        "note": "Self-description manifest only. No live TANTRA Runtime "
        "Registry endpoint has been confirmed reachable from this "
        "environment, so no registration call has actually been made — "
        "this is what such a call would read from MASTERDB, not proof "
        "one has succeeded.",
    }


# ---------------------------------------------------------------------------
# Metrics — for InsightFlow/InsightBridge/InsightCore (Vijay Dhawan) runtime
# telemetry/observability. Prometheus text exposition format, since that's
# the closest thing to an industry default for a not-yet-confirmed scrape
# contract (also named in the original brief's Learning Kit). Format is an
# assumption pending Vijay Dhawan confirming InsightFlow's actual expected
# shape — flagged as such in CONSTITUTIONAL_RUNTIME_DEFINITION.md.
# ---------------------------------------------------------------------------


@app.get("/metrics")
def metrics() -> Any:
    from fastapi import Response

    lines = [
        "# HELP masterdb_bcaes_registry_objects_total Objects registered per BCAES registry type.",
        "# TYPE masterdb_bcaes_registry_objects_total gauge",
    ]
    for registry_type, count in bcaes_registry_service.registry_summary().items():
        lines.append(f'masterdb_bcaes_registry_objects_total{{registry_type="{registry_type}"}} {count}')

    lines.append("# HELP masterdb_canonical_documents_total Documents in the canonical repository.")
    lines.append("# TYPE masterdb_canonical_documents_total gauge")
    # An aggregate count needs to see every document regardless of its
    # read_roles — this is an internal ops metric, not a content leak, so
    # the probe uses ADMIN_ROLE rather than an empty/anonymous identity
    # (which would silently undercount to whatever a reader-less caller
    # can see, i.e. usually nothing).
    doc_count = len(canonical_repository_service.list_all(actor="_metrics_probe", actor_roles=[ADMIN_ROLE]))
    lines.append(f"masterdb_canonical_documents_total {doc_count}")

    lines.append("# HELP masterdb_up Process liveness (always 1 if this endpoint responds).")
    lines.append("# TYPE masterdb_up gauge")
    lines.append("masterdb_up 1")

    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


# ---------------------------------------------------------------------------
# PARIKSHAK — engineering review reference sync
# ---------------------------------------------------------------------------
# See operational_sync/models.py for the ingestion-direction assumption.
# Requires a token with the "parikshak-sync" role (or bhiv-admin) to write;
# reads are open, since these are references/summaries/status only — not
# engineering intelligence — and multiple ecosystem consumers plausibly
# need to read readiness status without needing sync rights.


@app.post("/parikshak/review-references")
def upsert_review_reference(
    request: UpsertReviewReferenceRequest, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    try:
        record = parikshak_sync_service.upsert(request, actor=identity.actor, actor_roles=identity.roles)
        audit_logger.info(
            "parikshak.upsert actor=%s external_review_id=%s", identity.actor, request.external_review_id
        )
        return record.model_dump(mode="json")
    except SyncPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/parikshak/review-references")
def list_review_references() -> dict:
    records = parikshak_sync_service.list_all()
    return {"count": len(records), "records": [r.model_dump(mode="json") for r in records]}


@app.get("/parikshak/review-references/{external_review_id}")
def get_review_reference(external_review_id: str) -> dict:
    try:
        return parikshak_sync_service.get(external_review_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No review reference '{external_review_id}'.") from exc


# ---------------------------------------------------------------------------
# NIYANTRAN — operational task lifecycle sync
# ---------------------------------------------------------------------------
# Requires a token with the "niyantran-sync" role (or bhiv-admin) to write.
# MASTERDB records this state; nothing here triggers or executes workflow.


@app.post("/niyantran/task-state")
def upsert_operational_task_state(
    request: UpsertOperationalTaskStateRequest, identity: AuthIdentity = Depends(get_identity)
) -> dict:
    try:
        record = niyantran_sync_service.upsert(request, actor=identity.actor, actor_roles=identity.roles)
        audit_logger.info(
            "niyantran.upsert actor=%s external_task_id=%s", identity.actor, request.external_task_id
        )
        return record.model_dump(mode="json")
    except SyncPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/niyantran/task-state")
def list_operational_task_state() -> dict:
    records = niyantran_sync_service.list_all()
    return {"count": len(records), "records": [r.model_dump(mode="json") for r in records]}


@app.get("/niyantran/task-state/{external_task_id}")
def get_operational_task_state(external_task_id: str) -> dict:
    try:
        return niyantran_sync_service.get(external_task_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No task state '{external_task_id}'.") from exc


# ---------------------------------------------------------------------------
# Replay Registry — unified manifest of everything replay-capable in
# MASTERDB, for an eventual external Replay Registry Owner to consume. No
# such owner/endpoint has been confirmed reachable — this is what MASTERDB
# exposes, not proof of registration.
# ---------------------------------------------------------------------------


@app.get("/replay-registry/manifest")
def replay_registry_manifest() -> dict:
    architecture = bcaes_registry_service.validate_architecture()
    return {
        "service_name": "MASTERDB",
        "replay_capabilities": [
            {
                "name": "bcaes_registry_architecture",
                "endpoint": "/bcaes/validate/architecture",
                "mechanism": "replay_hash over full registry state; identical across repeated calls "
                "against unchanged state",
                "current_replay_hash": architecture["replay_hash"],
                "currently_passes": architecture["passed"],
            },
            {
                "name": "canonical_repository_document_chain",
                "endpoint": "/canonical-repository/documents/{document_id}/verify",
                "mechanism": "sha256 hash chain over a document's full version history; "
                "recomputed and compared on every call",
            },
            {
                "name": "knowledge_package_lifecycle",
                "endpoint": "/packages/{package_id}/replay",
                "mechanism": "rebuilds a package's status from its full recorded transition history",
            },
        ],
        "status": "not_yet_registered",
        "note": "No Replay Registry Owner or endpoint has been named/confirmed reachable "
        "as of this manifest — see CONSTITUTIONAL_RUNTIME_DEFINITION.md §4.",
    }


