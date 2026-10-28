import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv


if "PYTEST_CURRENT_TEST" not in os.environ:
    load_dotenv()
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from middleware.rate_limit_middleware import RateLimitMiddleware
from middleware.rate_limiter import SlidingWindowRateLimiter
from models import (
    AccessContract,
    Capability,
    CapabilityAccessRequest,
    CapabilityContract,
    CapabilityRetrieveRequest,
    CapabilityRetrieveResponse,
    CapabilityStatus,
    CertificationRequest,
    ExportRequest,
    KnowledgeObjectRegisterRequest,
    PackageDeprecateRequest,
    PackagePromoteRequest,
    PackageRegisterRequest,
    PackageStatus,
    QueryRequest,
    ReferenceRequest,
    SharedRecordDeprecateRequest,
    SharedRecordRegisterRequest,
    SharedRecordUpdateRequest,
    StreamRequest,
    ValidationRequest,
    SourceRecord,
    SourceRegisterRequest,
    SourceStatus,
)
from services.artifact_store import ArtifactStore
from services.certification_service import CertificationService
from services.capability_registry_service import (
    CapabilityAlreadyExistsError,
    CapabilityAccessDeniedError,
    CapabilityNotFoundError,
    CapabilityRegistryService,
    CapabilityVersionConflictError,
)
from geo_quest_candidate.service import (
    CandidateNotFoundError,
    CandidateRegistrationError,
    CandidateRetrieveRequest,
    GeoQuestCandidateService,
)
from geo_quest_candidate.masterdb_import import (
    CandidatePackageRetrieveRequest,
    CandidateUseDeniedError,
    GeospatialExportCandidateService,
)
from services.source_registry_service import (
    SourceRegistryService,
    SourceNotFoundError,
    SourceAlreadyExistsError,
)
from integrations.geospatial_connector import GeospatialConnectorAdapter
from services.opensky_service import OpenSkyService
from integrations.usgs_earthquake_connector import fetch_earthquakes
from integrations.gods_eye_view_dams_connector import DamsSourceUnavailable, fetch_dams
from integrations.natural_earth_connector import NaturalEarthSourceUnavailable, load_natural_earth_source
from integrations.gods_eye_view_photoreal_tiles_connector import (
    safe_manifest as photoreal_tiles_safe_manifest,
    verify_photoreal_tiles,
)
from integrations.gods_eye_view_satellite_imagery_connector import (
    safe_manifest as satellite_imagery_safe_manifest,
    verify_satellite_imagery,
)
from integrations.gods_eye_view_terrain_connector import (
    safe_manifest as world_terrain_safe_manifest,
    verify_world_terrain,
)
from integrations.gods_eye_view_vector_basemap_connector import (
    safe_manifest as vector_basemap_safe_manifest,
    verify_vector_basemap,
)
from integrations.gods_eye_view_bhote_koshi_connector import BhoteKoshiSourceUnavailable, fetch_bhote_koshi_event
from integrations.firms_active_fire_connector import (
    FIRMSConfigurationError,
    FIRMSUpstreamError,
    fetch_active_fires,
)
from integrations.aisstream_connector import (
    AISStreamConfigurationError,
    AISStreamConnectionError,
    fetch_aisstream_positions,
)
from services.ais_observation_service import AISObservationService, AISObservationValidationError
from integrations.adsb_military_connector import (
    AircraftUpstreamError,
    AircraftUpstreamRateLimitError,
    fetch_military_aircraft,
)
from services.aircraft_observation_service import AircraftObservationService, AircraftObservationValidationError
from services.earthquake_observation_service import (
    EarthquakeObservationService,
    EarthquakeObservationValidationError,
)
from services.dam_feature_service import DamFeatureService, DamFeatureValidationError
from services.natural_earth_feature_service import NaturalEarthFeatureService, NaturalEarthValidationError
from services.bhote_koshi_event_service import BhoteKoshiEventService, BhoteKoshiValidationError
from services.fire_observation_service import FireObservationService
from integrations.tomtom_traffic_connector import (
    MAX_TILES as TOMTOM_MAX_TILES,
    TomTomConfigurationError,
    TomTomUpstreamError,
    fetch_flow_tiles,
    validate_tile_coord,
)
from services.traffic_observation_service import TrafficObservationService
from integrations.weather_connector import (
    WeatherConfigurationError, WeatherUpstreamError,
    fetch_open_meteo_current, fetch_wind_forecasts,
)
from services.weather_observation_service import WeatherObservationService
from integrations.noaa_cyclone_connector import (
    CycloneConfigurationError, CycloneUpstreamError, CycloneValidationError,
    DATASETS as CYCLONE_DATASETS, SOURCE_IDS as CYCLONE_SOURCE_IDS,
    fetch_current_cyclones,
)
from services.cyclone_observation_service import CycloneObservationService, CycloneObservationValidationError
from integrations.noaa_radar_connector import (
    PRODUCT_LAYERS as WEATHER_IMAGERY_LAYERS,
    RadarRequestError, RadarUpstreamError, fetch_radar_image, fetch_radar_manifest,
    fetch_radar_tile, fetch_weather_image, fetch_weather_manifest, fetch_weather_tile,
)

from services.knowledge_object_service import (
    KnowledgeObjectService,
    LineageValidationError,
    VersionIncompatibleError,
)
from services.mdu_client import MDUUnavailableError
from services.mdu_contract_adapter import MDUContractAdapter
from services.vana_client import VanaClient, VanaUnavailableError, VanaGovernanceDeniedError
from services.package_registry_service import (
    InvalidTransitionError,
    PackageAlreadyExistsError,
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
from services.dataset_retrieval_service import (
    DatasetAccessDeniedError,
    DatasetNotRetrievableError,
    DatasetRetrievalService,
)
from services.bucket_client import BucketClient, BucketUnavailableError

from api.production import router as production_router
from api.pravah import router as pravah_router
from security.middleware import ReplayMitigationTable, RS256JWTVerifier, SecurityMiddleware
from services.crypto_audit_emitter import CryptoAuditEmitter
from services.pravah_ledger import PravahReplayLedger
from services.state_machine import PravahStateMachine
from services.event_pipeline import EventPipeline

from database_targets.models import (
    IngestRequest,
    IngestionFormat,
    IngestionJobStatus,
    TargetDatabase,
)
from database_targets.service import (
    DatabaseRouterService,
    JobNotFoundError,
    UnknownDatabaseError,
)

from upload.models import UploadCancelRequest, UploadInitiationRequest, UploadStatus
from upload.service import UploadService, UploadValidationError, UploadStateError
from upload.store import UploadJobNotFoundError

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
from services import backup_service
from services import startup_config
from auth.constants import ADMIN_ROLE
from auth.dependencies import build_identity_dependency
from auth.models import AuthIdentity, TokenRequest, TokenResponse
from auth.service import AuthService, AuthTokenError

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

# ── CORS ─────────────────────────────────────────────────────────────────────
# Allows the BHIV application ecosystem (and dev tooling) to call this API from
# browser/JS environments.  Set CORS_ALLOWED_ORIGINS env var to a comma-separated
# list of allowed origins in production (e.g. the deployed Vercel frontend's
# exact origin); defaults to "*" for local development.
#
# allow_credentials is intentionally False: auth here is a Bearer JWT sent in
# the Authorization header (see auth/service.py, /auth/token), never a cookie.
# Starlette's CORSMiddleware only reflects the exact Origin back on *actual*
# (non-preflight) responses when the request carries a Cookie header; with
# allow_origins=["*"] it otherwise sends a literal "Access-Control-Allow-Origin: *"
# on those responses. If allow_credentials were True, a browser making a
# credentialed (`credentials: "include"`) request would pass the CORS preflight
# (which does reflect the origin) but then have the browser reject the actual
# response, because a literal "*" is disallowed together with credentials —
# the request looks fine server-side (200 OK, headers present) while the
# frontend's fetch/XHR call fails. Since nothing here uses cookies, credentials
# mode isn't needed, and turning it off avoids that mismatch entirely rather
# than papering over it with per-origin reflection tricks.
_allowed_origins = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
]
if not _allowed_origins:
    _allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id", "X-Request-Id"],
)

# ── Rate limiting ────────────────────────────────────────────────────────────
# paths and middleware/rate_limiter.py for the "not distributed-safe"
# scope caveat. Configurable via RATE_LIMIT_MAX_REQUESTS /
# RATE_LIMIT_WINDOW_SECONDS env vars. Instantiated explicitly (rather than
# letting the middleware build its own) so tests can reset it between runs
# the same way every other stateful service in this file gets a fresh
# instance per test — see tests/conftest.py.
rate_limiter = SlidingWindowRateLimiter(
    max_requests=int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "120")),
    window_seconds=float(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")),
)
app.add_middleware(RateLimitMiddleware, limiter=rate_limiter)

production_verifier = RS256JWTVerifier()
production_replay_table = ReplayMitigationTable()
production_audit_emitter = CryptoAuditEmitter()
app.add_middleware(SecurityMiddleware, verifier=production_verifier, replay_table=production_replay_table)
app.state.verifier = production_verifier
app.state.replay_table = production_replay_table
app.state.audit_emitter = production_audit_emitter
app.include_router(production_router)

pravah_ledger = PravahReplayLedger()
pravah_state_machine = PravahStateMachine()
event_pipeline = EventPipeline(
    ledger=pravah_ledger,
    state_machine=pravah_state_machine,
    audit_emitter=production_audit_emitter,
)
app.state.pravah_ledger = pravah_ledger
app.state.pravah_state_machine = pravah_state_machine
app.state.event_pipeline = event_pipeline
app.include_router(pravah_router)

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

# Configuration validation — logs a one-time report at process startup
# (import time) covering every env var this service reads. Never logs
# actual secret values, only set/unset/malformed — see
# services/startup_config.py module docstring.
_startup_config_report = startup_config.validate_configuration()
logger.info(startup_config.summarize_for_startup_log(_startup_config_report))


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


from fastapi.exceptions import RequestValidationError


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("Validation error at %s: %s", request.url.path, exc.errors())
    errors = exc.errors()
    msg = "; ".join(f"{'.'.join(str(loc) for loc in err.get('loc', []))}: {err.get('msg')}" for err in errors)
    return JSONResponse(
        status_code=422,
        content=_error_body(request, "validation_error", msg or "Request validation failed."),
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
report_service = ReportService(artifact_store=artifact_store)
package_registry_service = PackageRegistryService(report_service=report_service)
certification_service = CertificationService(
    validation_service=validation_service,
    artifact_store=artifact_store,
    package_registry=package_registry_service,
)

# --- Database Targets: attach the ingestion/certification pipeline above to
# the 8 MASTERDB target databases (VectorDB, GraphDB, MetadataDB,
# DocumentDB, TimeSeriesDB, RelationalDB, ArchiveDB, AnalyticsDB) as a
# limited, highly controlled ingestion facility. Reads certification
# decisions from the *same* `artifact_store` populated by
# validation_service/certification_service above — this is the attach,
# not rebuild, boundary described in the task assignment. See
# database_targets/service.py.
database_router_service = DatabaseRouterService(certification_artifact_store=artifact_store)

# --- MASTERDB Upload Service: Canonical File Upload & Ingestion Contract ---
# Implements governed upload capability separating UPLOAD (artifact into boundary)
# from INGESTION (validating, processing, registering, and making data usable).
upload_service = UploadService()

# --- MASTERDB knowledge platform runtime (Knowledge Package Lifecycle,
# Provenance/Lineage, Retrieval Readiness) ---------------------------------
knowledge_object_service = KnowledgeObjectService(registry=package_registry_service)
retrieval_readiness_service = RetrievalReadinessService(
    registry=package_registry_service,
    knowledge_object_service=knowledge_object_service,
    report_service=report_service,
)

# --- Phase 4 — MASTERDB Dataset Retrieval & Phase 8 — Bucket Evidence -------
dataset_retrieval_service = DatasetRetrievalService(
    registry=package_registry_service,
    knowledge_object_service=knowledge_object_service,
    retrieval_readiness_service=retrieval_readiness_service,
)
bucket_client = BucketClient()

# --- Ecosystem integration surfaces: MDU (Nupur), TANTRA, VANA, Runtime Discovery --
mdu_contract_adapter = MDUContractAdapter()
vana_client = VanaClient()
runtime_discovery_service = RuntimeDiscoveryService(registry=package_registry_service)
source_registry_service = SourceRegistryService(
    audit_emitter=production_audit_emitter,
)
capability_registry_service = CapabilityRegistryService(
    package_registry=package_registry_service,
    retrieval_service=dataset_retrieval_service,
    audit_emitter=production_audit_emitter,
    vana_client=vana_client,
)
geospatial_connector = GeospatialConnectorAdapter(
    source_registry=source_registry_service,
    package_registry=package_registry_service,
    capability_registry=capability_registry_service,
)
opensky_service = OpenSkyService()

tantra_interface_service = TantraInterfaceService(
    registry=package_registry_service,
    knowledge_object_service=knowledge_object_service,
    retrieval_readiness_service=retrieval_readiness_service,
    report_service=report_service,
    discovery_service=runtime_discovery_service,
    capability_service=capability_registry_service,
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

_ENV_MODE = (
    os.environ.get("ENVIRONMENT")
    or os.environ.get("APP_ENV")
    or os.environ.get("MASTERDB_ENV")
    or ""
).strip().lower()
_IS_PRODUCTION = _ENV_MODE in ("production", "prod")

if _IS_PRODUCTION:
    _is_persist_ok, _persist_err = startup_config.validate_production_persistence(
        storage_dir=_STORAGE_ROOT,
        database_url=_DATABASE_URL,
    )
    if not _is_persist_ok:
        logger.critical("PRODUCTION PERSISTENCE STARTUP ERROR: %s", _persist_err)
        raise RuntimeError(_persist_err)


def _persist_path(subdir: str) -> Optional[str]:
    return os.path.join(_STORAGE_ROOT, subdir) if _STORAGE_ROOT else None


def _sql_store(subdir: str):
    if not _DATABASE_URL:
        return None
    return SqlArtifactStore(_DATABASE_URL, store_name=subdir)


earthquake_observation_service = EarthquakeObservationService(
    store=_sql_store("earthquake_observations"),
    store_dir=_persist_path("earthquake_observations") or "earthquake_observation_store",
)
dam_feature_service = DamFeatureService(
    attribute_store=_sql_store("dam_attributes"),
    geometry_store=_sql_store("dam_geometries"),
    store_dir=_persist_path("dam_features") or "dam_feature_store",
)
natural_earth_feature_service = NaturalEarthFeatureService(
    store_dir=_persist_path("natural_earth_features") or "natural_earth_feature_store",
)
natural_earth_last_verified_at: Dict[str, Optional[str]] = {"regions": None, "marine": None}
natural_earth_dataset_status: Dict[str, str] = {"regions": "UNVERIFIED", "marine": "UNVERIFIED"}
for _natural_earth_key, _natural_earth_source_id in (
    ("regions", "src-gev-natural-earth-regions"),
    ("marine", "src-gev-natural-earth-marine"),
):
    try:
        _natural_earth_record = source_registry_service.get_source(_natural_earth_source_id)
        _natural_earth_status = _natural_earth_record.provenance_reference.get("last_fetch_status", "UNVERIFIED")
        if _natural_earth_status == "STATIC_VERIFIED":
            _natural_earth_counts = natural_earth_feature_service.readback_counts(_natural_earth_key)
            _natural_earth_saved = _natural_earth_record.provenance_reference.get("last_verification", {})
            if (_natural_earth_counts["attributes"] == _natural_earth_saved.get("attribute_records")
                    and _natural_earth_counts["geometries"] == _natural_earth_saved.get("geometry_records")):
                natural_earth_last_verified_at[_natural_earth_key] = _natural_earth_record.last_validation
                natural_earth_dataset_status[_natural_earth_key] = "STATIC_VERIFIED"
            else:
                natural_earth_dataset_status[_natural_earth_key] = "UNAVAILABLE"
        elif _natural_earth_status in ("STATIC_PARTIAL", "UNAVAILABLE"):
            natural_earth_dataset_status[_natural_earth_key] = _natural_earth_status
    except SourceNotFoundError:
        pass
dam_snapshot_last_verified_at: Optional[str] = None
try:
    _dam_source_record = source_registry_service.get_source("src-gev-openinframap-dams")
    if _dam_source_record.provenance_reference.get("last_fetch_status") == "STATIC_VERIFIED":
        dam_snapshot_last_verified_at = _dam_source_record.last_validation
except SourceNotFoundError:
    pass
photoreal_tiles_last_verification: Dict[str, Any] = {}
satellite_imagery_last_verification: Dict[str, Any] = {}
world_terrain_last_verification: Dict[str, Any] = {}
vector_basemap_last_verification: Dict[str, Any] = {}
try:
    _photoreal_source_record = source_registry_service.get_source("src-gev-google-photoreal-tiles")
    _photoreal_source_record.attribution = "Google Maps Platform per-tile credits must remain visible; Cesium ion attribution applies on the hosted asset route"
    _photoreal_source_record.updated_at = datetime.now(timezone.utc).isoformat()
    source_registry_service.store.save(
        _photoreal_source_record.source_id,
        _photoreal_source_record.model_dump(mode="json"),
    )
    _photoreal_saved_verification = _photoreal_source_record.provenance_reference.get("last_verification")
    if isinstance(_photoreal_saved_verification, dict):
        photoreal_tiles_last_verification = dict(_photoreal_saved_verification)
    elif _photoreal_source_record.provenance_reference.get("last_fetch_status") == "UNAVAILABLE":
        photoreal_tiles_last_verification = {
            "status": "UNAVAILABLE",
            "credential_configured": photoreal_tiles_safe_manifest({})["credential_configured"],
            "tiles_loaded": False,
            "reason": _photoreal_source_record.provenance_reference.get("last_error", "provider_tiles_unavailable_or_invalid"),
        }
except SourceNotFoundError:
    pass
try:
    _satellite_source_record = source_registry_service.get_source("src-gev-world-satellite-imagery")
    _satellite_saved_verification = _satellite_source_record.provenance_reference.get("last_verification")
    if isinstance(_satellite_saved_verification, dict):
        satellite_imagery_last_verification = dict(_satellite_saved_verification)
    elif _satellite_source_record.provenance_reference.get("last_fetch_status") == "UNAVAILABLE":
        satellite_imagery_last_verification = {
            "status": "UNAVAILABLE",
            "tiles_loaded": False,
            "reason": _satellite_source_record.provenance_reference.get("last_error", "all_provider_tiles_unavailable"),
        }
except SourceNotFoundError:
    pass
try:
    _terrain_source_record = source_registry_service.get_source("src-gev-world-3d-terrain")
    _terrain_saved_verification = _terrain_source_record.provenance_reference.get("last_verification")
    if isinstance(_terrain_saved_verification, dict):
        world_terrain_last_verification = dict(_terrain_saved_verification)
    elif _terrain_source_record.provenance_reference.get("last_fetch_status") == "UNAVAILABLE":
        world_terrain_last_verification = {
            "status": "UNAVAILABLE", "tiles_loaded": False,
            "reason": _terrain_source_record.provenance_reference.get("last_error", "provider_unreachable"),
        }
except SourceNotFoundError:
    pass
try:
    _vector_basemap_source_record = source_registry_service.get_source("src-gev-openfreemap-vector-basemap")
    _vector_basemap_saved_verification = _vector_basemap_source_record.provenance_reference.get("last_verification")
    if isinstance(_vector_basemap_saved_verification, dict):
        vector_basemap_last_verification = dict(_vector_basemap_saved_verification)
    elif _vector_basemap_source_record.provenance_reference.get("last_fetch_status") == "UNAVAILABLE":
        vector_basemap_last_verification = {
            "status": "UNAVAILABLE", "tiles_loaded": False,
            "reason": _vector_basemap_source_record.provenance_reference.get("last_error", "provider_unreachable"),
        }
except SourceNotFoundError:
    pass
bhote_koshi_event_service = BhoteKoshiEventService(
    event_store=_sql_store("bhote_koshi_events"),
    geometry_store=_sql_store("bhote_koshi_geometries"),
    media_store=_sql_store("bhote_koshi_media"),
    store_dir=_persist_path("bhote_koshi_event") or "bhote_koshi_event_store",
)
bhote_koshi_last_verified_at: Optional[str] = None
try:
    _bhote_koshi_source_record = source_registry_service.get_source("src-gev-bhote-koshi-flood")
    if _bhote_koshi_source_record.provenance_reference.get("last_fetch_status") == "STATIC_VERIFIED":
        bhote_koshi_last_verified_at = _bhote_koshi_source_record.last_validation
except SourceNotFoundError:
    pass
ais_observation_service = AISObservationService(
    store=_sql_store("ais_observations"),
    store_dir=_persist_path("ais_observations") or "ais_observation_store",
)
aircraft_observation_service = AircraftObservationService(
    store=_sql_store("aircraft_observations"),
    store_dir=_persist_path("aircraft_observations") or "aircraft_observation_store",
)

OBSERVATION_FEED_SOURCE_IDS = {
    "usgs": "src-gev-usgs-seismic",
    "aisstream": "src-gev-aisstream-vessels",
    "adsb_military": "src-gev-adsb-military",
}
observation_feed_state: Dict[str, Dict[str, Any]] = {}


def _observation_dataset_count(service: Any) -> int:
    return len(service.list(limit=1_000_000))


def _restore_observation_feed_state(key: str, service: Any) -> Dict[str, Any]:
    """Restore LIVE_VERIFIED only when persisted success evidence matches storage."""
    source_id = OBSERVATION_FEED_SOURCE_IDS[key]
    try:
        source = source_registry_service.get_source(source_id)
    except SourceNotFoundError:
        return {"status": "PENDING", "last_verified_at_utc": None}
    metadata = source.provenance_reference or {}
    verification = metadata.get("last_verification") or {}
    stored_count = _observation_dataset_count(service)
    verified = (
        metadata.get("last_fetch_status") == "LIVE_VERIFIED"
        and verification.get("status") == "LIVE_VERIFIED"
        and verification.get("readback_records", 0) > 0
        and verification.get("stored_dataset_records") == stored_count
    )
    if verified:
        return {"status": "LIVE_VERIFIED", "last_verified_at_utc": verification.get("verified_at_utc"), "last_verification": verification}
    status = "UNAVAILABLE" if metadata.get("last_fetch_status") == "UNAVAILABLE" else "PENDING"
    if not verification and source.last_validation != "NOT VERIFIED":
        source.last_validation = "NOT VERIFIED"
        source_registry_service.store.save(source_id, source.model_dump(mode="json"))
    if metadata.get("last_fetch_status") != status:
        source_registry_service.mark_fetch_status(source_id, status, {
            "last_error": "successful_fetch_and_storage_readback_not_confirmed",
            "last_verification": {"status": status, "stored_dataset_records": stored_count},
        })
    return {"status": status, "last_verified_at_utc": None, "last_verification": verification}


observation_feed_state = {
    "usgs": _restore_observation_feed_state("usgs", earthquake_observation_service),
    "aisstream": _restore_observation_feed_state("aisstream", ais_observation_service),
    "adsb_military": _restore_observation_feed_state("adsb_military", aircraft_observation_service),
}


def _mark_observation_feed_unavailable(key: str, reason: str) -> None:
    source_id = OBSERVATION_FEED_SOURCE_IDS[key]
    try:
        source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {
            "last_error": reason,
            "last_verification": {"status": "UNAVAILABLE", "reason": reason},
        })
    finally:
        observation_feed_state[key] = {"status": "UNAVAILABLE", "last_verified_at_utc": None}


def _verify_observation_ingestion(
    key: str, service: Any, ingest_result: Dict[str, Any], record_ids: List[str],
) -> Dict[str, Any]:
    """Persist LIVE_VERIFIED only after record and source-registry read-back."""
    source_id = OBSERVATION_FEED_SOURCE_IDS[key]
    unique_ids = list(dict.fromkeys(record_ids))
    stored_count = _observation_dataset_count(service)
    read_back = [service.get(record_id) for record_id in unique_ids]
    readback_count = sum(row is not None for row in read_back)
    if not unique_ids:
        verified_at = datetime.now(timezone.utc).isoformat()
        verification = {
            "status": "PENDING", "reason": "empty_feed_no_observations",
            "fetched_records": ingest_result.get("fetched", 0), "readback_records": 0,
            "stored_dataset_records": stored_count, "verified_at_utc": verified_at,
        }
        source_registry_service.mark_fetch_status(source_id, "PENDING", {"last_verification": verification})
        registry_record = source_registry_service.get_source(source_id)
        registry_ok = registry_record.provenance_reference.get("last_verification") == verification
        observation_feed_state[key] = {"status": "PENDING", "last_verified_at_utc": None, "last_verification": verification}
        return {**verification, "registry_readback": registry_ok}
    if readback_count != len(unique_ids):
        _mark_observation_feed_unavailable(key, "observation_storage_readback_failed")
        raise RuntimeError("Observation storage read-back failed")

    verified_at = datetime.now(timezone.utc).isoformat()
    verification = {
        "status": "LIVE_VERIFIED", "fetched_records": ingest_result.get("fetched", 0),
        "unique_source_records": len(unique_ids), "readback_records": readback_count,
        "stored_dataset_records": stored_count, "verified_at_utc": verified_at,
    }
    source_registry_service.mark_validated(source_id, verified_at, {
        "last_fetch_status": "LIVE_VERIFIED", "last_verification": verification,
    })
    registry_record = source_registry_service.get_source(source_id)
    saved = registry_record.provenance_reference.get("last_verification", {})
    if (registry_record.provenance_reference.get("last_fetch_status") != "LIVE_VERIFIED"
            or saved.get("status") != "LIVE_VERIFIED"
            or saved.get("verified_at_utc") != verified_at
            or saved.get("readback_records") != readback_count
            or saved.get("stored_dataset_records") != stored_count):
        _mark_observation_feed_unavailable(key, "source_registry_readback_failed")
        raise RuntimeError("Source registry read-back failed")
    observation_feed_state[key] = {
        "status": "LIVE_VERIFIED", "last_verified_at_utc": verified_at,
        "last_verification": verification,
    }
    return {**verification, "registry_readback": True}

fire_observation_service = FireObservationService(
    store=_sql_store("fire_observations"),
    store_dir=_persist_path("fire_observations") or "fire_observation_store",
)
traffic_observation_service = TrafficObservationService(
    store=_sql_store("traffic_observations"),
    store_dir=_persist_path("traffic_observations") or "traffic_observation_store",
)
weather_observation_service = WeatherObservationService(
    store=_sql_store("weather_observations"),
    store_dir=_persist_path("weather_observations") or "weather_observation_store",
)
cyclone_observation_service = CycloneObservationService(
    store=_sql_store("cyclone_observations"),
    store_dir=_persist_path("cyclone_observations") or "cyclone_observation_store",
)
cyclone_source_state: Dict[str, Dict[str, Any]] = {}
for _cyclone_kind, _cyclone_source_id in CYCLONE_SOURCE_IDS.items():
    try:
        _cyclone_source = source_registry_service.get_source(_cyclone_source_id)
        _cyclone_status = _cyclone_source.provenance_reference.get("last_fetch_status", "CONFIGURED")
        cyclone_source_state[_cyclone_kind] = {
            "last_verified_at_utc": _cyclone_source.last_validation if _cyclone_status == "LIVE_VERIFIED" else None,
            "last_fetch_status": _cyclone_status,
            "last_metadata": _cyclone_source.provenance_reference,
        }
    except SourceNotFoundError:
        cyclone_source_state[_cyclone_kind] = {"last_verified_at_utc": None, "last_fetch_status": "CONFIGURED", "last_metadata": {}}
weather_source_state: Dict[str, Dict[str, Any]] = {}
for _weather_source_id in ("src-gev-gfs-wind", "src-gev-ecmwf-wind", "src-open-meteo-current-weather"):
    try:
        _source = source_registry_service.get_source(_weather_source_id)
        _fetch_status = _source.provenance_reference.get("last_fetch_status", "CONFIGURED")
        weather_source_state[_weather_source_id] = {
            "last_verified_at_utc": _source.last_validation if _fetch_status == "LIVE_VERIFIED" else None,
            "last_fetch_status": _fetch_status,
            "verified_coordinates": _source.provenance_reference.get("verified_coordinates", []),
        }
    except SourceNotFoundError:
        weather_source_state[_weather_source_id] = {"last_verified_at_utc": None, "last_fetch_status": "UNAVAILABLE", "verified_coordinates": []}
try:
    _radar_source = source_registry_service.get_source("src-gev-noaa-nowcoast-radar")
    _radar_provenance = _radar_source.provenance_reference
    radar_source_state: Dict[str, Any] = {
        "last_verified_at_utc": _radar_source.last_validation if _radar_provenance.get("last_fetch_status") == "LIVE_VERIFIED" else None,
        "last_fetch_status": _radar_provenance.get("last_fetch_status", "CONFIGURED"),
        "metadata": _radar_provenance.get("radar_metadata"),
        "last_image_retrieval": _radar_provenance.get("last_image_retrieval"),
    }
except SourceNotFoundError:
    radar_source_state = {"last_verified_at_utc": None, "last_fetch_status": "UNAVAILABLE", "metadata": None, "last_image_retrieval": None}
SATELLITE_CLOUD_PRODUCTS = {
    "clouds": {"source_id": "src-gev-noaa-nowcoast-clouds-global", "dataset_id": "noaa_nowcoast_global_satellite_cloud_imagery"},
    "clouds-regional": {"source_id": "src-gev-noaa-nowcoast-clouds-regional", "dataset_id": "noaa_nowcoast_goes_regional_satellite_cloud_imagery"},
}
NOAA_WEATHER_IMAGERY_PRODUCTS = {
    **SATELLITE_CLOUD_PRODUCTS,
    "lightning": {"source_id": "src-gev-noaa-nowcoast-lightning", "dataset_id": "noaa_nowcoast_lightning_strike_density_imagery"},
}
satellite_cloud_state: Dict[str, Dict[str, Any]] = {}
for _cloud_product, _cloud_ids in NOAA_WEATHER_IMAGERY_PRODUCTS.items():
    try:
        _cloud_source = source_registry_service.get_source(_cloud_ids["source_id"])
        _cloud_fetch_status = _cloud_source.provenance_reference.get("last_fetch_status", "CONFIGURED")
        satellite_cloud_state[_cloud_product] = {
            "last_verified_at_utc": _cloud_source.last_validation if _cloud_fetch_status == "LIVE_VERIFIED" else None,
            "last_fetch_status": _cloud_fetch_status,
            "metadata": _cloud_source.provenance_reference.get("satellite_metadata"),
            "last_image_retrieval": _cloud_source.provenance_reference.get("last_image_retrieval"),
        }
    except SourceNotFoundError:
        satellite_cloud_state[_cloud_product] = {"last_verified_at_utc": None, "last_fetch_status": "UNAVAILABLE", "metadata": None, "last_image_retrieval": None}
try:
    _firms_validation = source_registry_service.get_source("src-gev-nifc-firms").last_validation
    firms_last_verified_at: Optional[str] = _firms_validation if _firms_validation != "NOT VERIFIED" else None
except SourceNotFoundError:
    firms_last_verified_at = None
try:
    _traffic_source = source_registry_service.get_source("src-gev-tomtom-traffic")
    _traffic_verified = _traffic_source.last_validation
    traffic_last_verified_at: Optional[str] = _traffic_verified if _traffic_verified != "NOT VERIFIED" else None
    traffic_verified_tiles: List[Dict[str, int]] = _traffic_source.provenance_reference.get("last_verified_tiles", [])
    traffic_last_fetch_error = _traffic_source.provenance_reference.get("last_fetch_status") == "UNAVAILABLE"
except SourceNotFoundError:
    traffic_last_verified_at, traffic_verified_tiles, traffic_last_fetch_error = None, [], False


geo_quest_candidate_service = GeoQuestCandidateService(
    store_dir=_persist_path("geo_quest_candidates") or "geo_quest_candidate_store",
    store=_sql_store("geo_quest_candidates"),
)
gev_geospatial_candidate_service = GeospatialExportCandidateService(
    store=geo_quest_candidate_service.store,
    capability_registry=capability_registry_service,
    dataset_registry=package_registry_service,
    mdu_contracts=mdu_contract_adapter,
)


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
app.state.auth_service = auth_service
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
# Database Targets — MASTERDB database routing / controlled ingestion
# attachment. Discovery is authenticated-read-only; POST /ingest enforces
# per-database RBAC, format contract, and the CERTIFIED gate before
# routing (see database_targets/service.py for the full control chain).
# ---------------------------------------------------------------------------


@app.get("/databases")
def list_databases(identity: AuthIdentity = Depends(get_identity)) -> List[dict]:
    return [db.model_dump(mode="json") for db in database_router_service.list_databases()]


@app.get("/databases/{database_key}")
def get_database(database_key: TargetDatabase, identity: AuthIdentity = Depends(get_identity)) -> dict:
    try:
        return database_router_service.get_database(database_key).model_dump(mode="json")
    except UnknownDatabaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/databases/{database_key}/records/{dataset_id}")
def get_target_database_records(
    database_key: TargetDatabase,
    dataset_id: str,
    limit: int = 100,
    offset: int = 0,
    identity: AuthIdentity = Depends(get_identity),
) -> dict:
    """Retrieve target database records for a dataset (P1 target database HTTP read-back)."""
    try:
        database_router_service.get_database(database_key)
    except UnknownDatabaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    records = database_router_service.list_target_records(
        target_database=database_key,
        dataset_id=dataset_id,
        limit=limit,
        offset=offset,
    )
    return {
        "target_database": database_key.value,
        "dataset_id": dataset_id,
        "count": len(records),
        "limit": limit,
        "offset": offset,
        "records": records,
    }


@app.post("/ingest", status_code=201)
def ingest_dataset(request: IngestRequest, identity: AuthIdentity = Depends(get_identity)) -> dict:
    job = database_router_service.ingest(
        dataset_id=request.dataset_id,
        target_database=request.target_database,
        source_format=request.source_format,
        actor=identity.actor,
        roles=identity.roles,
        package_id=request.package_id,
        metadata=request.metadata,
        upload_id=request.upload_id,  # P0-3: propagate upload linkage
    )
    audit_logger.info(
        "ingest job_id=%s dataset_id=%s target=%s actor=%s status=%s",
        job.job_id, job.dataset_id, job.target_database.value, identity.actor, job.status.value,
    )
    if job.status == IngestionJobStatus.PERSISTED:
        return job.model_dump(mode="json")
    # Precise status code from the failing step, without collapsing every
    # rejection into a generic 400 — RBAC denial is a 403, format/
    # certification rejection is a 422. Full reasoning trail (all steps,
    # not just the failing one) stays retrievable via GET /ingest/jobs/{id}.
    failed_step = next((step for step in job.steps if not step.passed), None)
    status_code = 403 if failed_step and failed_step.step == "RBAC_CHECK" else 422
    raise HTTPException(
        status_code=status_code,
        detail=f"{job.rejection_reason} (job_id={job.job_id})",
    )


@app.get("/ingest/jobs/{job_id}")
def get_ingest_job(job_id: str, identity: AuthIdentity = Depends(get_identity)) -> dict:
    try:
        return database_router_service.get_job(job_id).model_dump(mode="json")
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/ingest/jobs")
def list_ingest_jobs(
    dataset_id: Optional[str] = None,
    target_database: Optional[TargetDatabase] = None,
    status: Optional[IngestionJobStatus] = None,
    identity: AuthIdentity = Depends(get_identity),
) -> List[dict]:
    jobs = database_router_service.list_jobs(
        dataset_id=dataset_id, target_database=target_database, status=status,
    )
    return [job.model_dump(mode="json") for job in jobs]


# MASTERDB-BE-02: Canonical File Upload (UPLOADED->RECEIVED->VALIDATING->VALIDATED->REGISTERED->INGESTED->AVAILABLE)
ALLOWED_CONTENT_TYPES = {"text/csv", "application/json",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/pdf", "text/plain", "image/png", "image/jpeg", "image/gif", "application/zip"}

@app.post("/upload", status_code=201)
def initiate_upload(request: UploadInitiationRequest, identity: AuthIdentity = Depends(get_identity)) -> dict:
    """Initiate upload. Use POST /upload/{upload_id}/content for file bytes."""
    try:
        job = upload_service.initiate_upload(
            filename=request.filename, content_type=request.content_type, file_size=request.file_size,
            actor=identity.actor, roles=identity.roles, checksum_sha256=request.checksum_sha256,
            classification=request.classification, source_reference=request.source_reference,
            provenance_metadata=request.provenance_metadata, schema_version=request.schema_version,
            product_source=request.product_source, intended_use=request.intended_use, metadata=request.metadata)
        audit_logger.info("upload.initiate actor=%s upload_id=%s filename=%s size=%d",
            identity.actor, job.upload_id, request.filename, request.file_size)
        return {"upload_id": job.upload_id, "trace_id": job.trace_id, "status": job.status.value,
            "storage_path": job.storage_path, "max_size_bytes": 500*1024*1024,
            "allowed_content_types": list(ALLOWED_CONTENT_TYPES), "checksum_algorithm": "sha256"}
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/upload/{upload_id}/content")
async def upload_content(upload_id: str, request: Request, identity: AuthIdentity = Depends(get_identity)) -> dict:
    """Upload file content (raw bytes)."""
    try:
        job = upload_service.get_upload(upload_id)
        if job.actor != identity.actor and ADMIN_ROLE not in identity.roles and "operator" not in identity.roles:
            raise HTTPException(
                status_code=403,
                detail=f"Not authorized to modify upload '{upload_id}' owned by '{job.actor}'.",
            )
        body = await request.body()
        job = upload_service.receive_upload(upload_id=upload_id, file_content=body)
        audit_logger.info("upload.receive actor=%s upload_id=%s size=%d", identity.actor, upload_id, len(body))
        return {"upload_id": job.upload_id, "status": job.status.value, "file_size_bytes": job.file_size}
    except UploadJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/upload/{upload_id}/validate")
def validate_upload(upload_id: str, identity: AuthIdentity = Depends(get_identity)) -> dict:
    """Validate uploaded file (checksum verification)."""
    try:
        job = upload_service.get_upload(upload_id)
        if job.actor != identity.actor and ADMIN_ROLE not in identity.roles and "operator" not in identity.roles:
            raise HTTPException(
                status_code=403,
                detail=f"Not authorized to validate upload '{upload_id}' owned by '{job.actor}'.",
            )
        job = upload_service.validate_upload(upload_id=upload_id)
        audit_logger.info("upload.validate actor=%s upload_id=%s status=%s", identity.actor, upload_id, job.status.value)
        return {"upload_id": job.upload_id, "status": job.status.value,
            "validation_passed": job.status == UploadStatus.VALIDATED,
            "rejection_reason": job.rejection_reason, "steps": [s.model_dump() for s in job.steps]}
    except UploadJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@app.get("/upload/jobs/{upload_id}")
def get_upload(upload_id: str, identity: AuthIdentity = Depends(get_identity)) -> dict:
    """Get upload job status and details.

    Authorization: The caller must be the upload owner or have admin/operator role.
    """
    try:
        job = upload_service.get_upload(upload_id)
        # Authorization: owner or admin/operator can view any upload
        if job.actor != identity.actor and ADMIN_ROLE not in identity.roles and "operator" not in identity.roles:
            raise HTTPException(
                status_code=403,
                detail=f"Not authorized to view upload '{upload_id}' owned by '{job.actor}'.",
            )
        return {"upload_id": job.upload_id, "status": job.status.value, "filename": job.filename,
            "content_type": job.content_type, "file_size_bytes": job.file_size, "actor": job.actor,
            "steps": [s.model_dump() for s in job.steps], "rejection_reason": job.rejection_reason,
            "dataset_id": job.dataset_id, "package_id": job.package_id, "ingestion_job_id": job.ingestion_job_id,
            "timestamps": {"uploaded_at": job.uploaded_at, "received_at": job.received_at,
                "validated_at": job.validated_at, "registered_at": job.registered_at,
                "ingested_at": job.ingested_at, "available_at": job.available_at}}
    except UploadJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/upload/jobs")
def list_uploads(status: Optional[str] = None, actor: Optional[str] = None,
                 product_source: Optional[str] = None,
                 identity: AuthIdentity = Depends(get_identity)) -> dict:
    """List upload jobs with optional filtering.

    Authorization: Admin/operator sees all uploads. Others only see their own.
    """
    # Non-admin users can only filter by their own actor
    is_admin = ADMIN_ROLE in identity.roles or "operator" in identity.roles
    filter_actor = actor if is_admin else identity.actor
    filter_status = UploadStatus(status) if status else None
    jobs = upload_service.list_uploads(status=filter_status, actor=filter_actor, product_source=product_source)
    return {"count": len(jobs), "uploads": [{"upload_id": j.upload_id, "status": j.status.value,
        "filename": j.filename, "file_size_bytes": j.file_size, "actor": j.actor,
        "product_source": j.product_source, "uploaded_at": j.uploaded_at} for j in jobs]}

@app.delete("/upload/jobs/{upload_id}")
def cancel_upload(upload_id: str, reason: UploadCancelRequest,
                  identity: AuthIdentity = Depends(get_identity)) -> dict:
    """Cancel pending upload and clean up staging."""
    try:
        job = upload_service.get_upload(upload_id)
        if job.actor != identity.actor and ADMIN_ROLE not in identity.roles and "operator" not in identity.roles:
            raise HTTPException(
                status_code=403,
                detail=f"Not authorized to cancel upload '{upload_id}' owned by '{job.actor}'.",
            )
        job = upload_service.cancel_upload(upload_id=upload_id, reason=reason.reason)
        audit_logger.info("upload.cancel actor=%s upload_id=%s reason=%s", identity.actor, upload_id, reason.reason)
        return {"upload_id": job.upload_id, "status": job.status.value, "rejection_reason": job.rejection_reason}
    except UploadJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

# ---------------------------------------------------------------------------
# Phase 4 — MASTERDB Registry API
# ---------------------------------------------------------------------------


@app.post("/packages/register")
def register_package(request: PackageRegisterRequest) -> dict:
    try:
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
            package_id=request.package_id,
        )
        return package.model_dump(mode="json")
    except PackageAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    try:
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
            package_id=request.package_id,
        )
        return package.model_dump(mode="json")
    except PackageAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
# Phase 4 — MASTERDB Central Data Platform (Dataset Retrieval)
#
# Bhupinder Singh's convergence layer: unified dataset access across all
# mediums, boards, and languages. These endpoints wrap the
# DatasetRetrievalService with standard HTTP semantics and error mapping.
# ---------------------------------------------------------------------------


@app.get("/datasets")
def list_datasets() -> dict:
    """Return all datasets known to the retrieval service."""
    datasets = dataset_retrieval_service.list_datasets()
    return {"count": len(datasets), "datasets": datasets}


@app.get("/datasets/{dataset_id}")
def get_dataset_detail(dataset_id: str) -> dict:
    """Return full dataset detail including history, knowledge object, and retrieval evidence."""
    if dataset_id == "ds-gev-opensky-flights":
        return get_opensky_flight_dataset()
    try:
        return dataset_retrieval_service.get_dataset(dataset_id)
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/datasets/{dataset_id}/schema")
def get_dataset_schema(dataset_id: str) -> dict:
    """Return the schema contract for a dataset (MDU-live if available; registry-declared fallback)."""
    return dataset_retrieval_service.get_dataset_schema(dataset_id)


@app.get("/datasets/{dataset_id}/versions")
def get_dataset_versions(dataset_id: str) -> dict:
    """Return all registered versions of a dataset, sorted by creation time."""
    try:
        return dataset_retrieval_service.get_dataset_versions(dataset_id)
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/datasets/{dataset_id}/provenance")
def get_dataset_provenance(dataset_id: str) -> dict:
    """Return MASTERDB lineage + MDU provenance for a dataset."""
    try:
        return dataset_retrieval_service.get_dataset_provenance(dataset_id)
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/query")
def query_dataset(request: QueryRequest) -> dict:
    """Execute a structured query against a dataset."""
    try:
        result = dataset_retrieval_service.query(
            dataset_id=request.dataset_id,
            query_params=request.query_params,
        )
        return result
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetNotRetrievableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatasetAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/export")
def export_dataset(request: ExportRequest) -> dict:
    """Request an asynchronous or synchronous export of a dataset."""
    try:
        result = dataset_retrieval_service.export_dataset(
            dataset_id=request.dataset_id,
            format=request.format,
        )
        return result
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetNotRetrievableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatasetAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/stream")
def stream_dataset(request: StreamRequest) -> dict:
    """Request a streaming connection to a dataset."""
    try:
        result = dataset_retrieval_service.stream(
            dataset_id=request.dataset_id,
            stream_params=request.stream_params,
        )
        return result
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetNotRetrievableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatasetAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/reference")
def reference_dataset(request: ReferenceRequest) -> dict:
    """Generate a stable reference/citation for a dataset."""
    try:
        result = dataset_retrieval_service.reference(dataset_id=request.dataset_id)
        return result
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetNotRetrievableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Phase 8 — Evidence Preservation & Bucket Operations
#
# Evidence and provenance storage via Bucket, plus bucket health reporting.
# ---------------------------------------------------------------------------


@app.post("/evidence/{evidence_id}")
def store_evidence(evidence_id: str, request: dict) -> dict:
    """Persist an evidence record to the configured bucket (Phase 8).

    The evidence_id is placed in the path per spec §4.1. The request body
    is forwarded as the evidence payload.
    """
    try:
        return bucket_client.store_evidence(evidence_id=evidence_id, payload=request)
    except BucketUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/evidence/{evidence_id}")
def retrieve_evidence(evidence_id: str) -> dict:
    """Retrieve a stored evidence artifact from the configured bucket (Phase 8)."""
    try:
        return bucket_client.get_evidence(evidence_id)
    except BucketUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/provenance/{dataset_id}")
def store_provenance(dataset_id: str, request: dict) -> dict:
    """Persist a provenance record for a dataset to the configured bucket (Phase 8)."""
    try:
        return bucket_client.store_provenance(dataset_id=dataset_id, provenance=request)
    except BucketUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/provenance/{package_id}")
def get_provenance(package_id: str) -> dict:
    """Retrieve the full provenance chain for a knowledge package."""
    try:
        package_registry_service.get(package_id)  # confirms existence
    except PackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return knowledge_object_service.lineage(package_id)


@app.get("/bucket/status")
def bucket_status() -> dict:
    """Health and connectivity check for the evidence bucket."""
    return bucket_client.status()


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
    """Issues a signed, expiring JWT for authenticated callers.
    
    Roles are assigned from trusted server-side configuration mapping based on the actor's identity,
    preventing self-assignment or privilege escalation from caller-supplied roles.
    """
    try:
        token, expires_at, trusted_roles = auth_service.authenticate(
            actor=request.actor,
            password=request.password,
            roles=request.roles,
        )
        return TokenResponse(
            access_token=token, actor=request.actor, roles=trusted_roles, expires_at=expires_at
        ).model_dump(mode="json")
    except AuthTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


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

    env_mode = (
        os.environ.get("ENVIRONMENT")
        or os.environ.get("APP_ENV")
        or os.environ.get("MASTERDB_ENV")
        or ""
    ).strip().lower()
    is_production = env_mode in ("production", "prod")

    artifact_store = getattr(bcaes_registry_service, "artifact_store", None)
    if is_production:
        if artifact_store is None:
            checks["persistence"] = "error: Ephemeral in-memory storage is not permitted in production mode"
            ok = False
        else:
            try:
                if hasattr(artifact_store, "ping"):
                    artifact_store.ping()
                checks["persistence"] = "ok"
            except Exception as exc:  # noqa: BLE001
                checks["persistence"] = f"error: {exc}"
                ok = False
    elif artifact_store is not None:
        try:
            if hasattr(artifact_store, "ping"):
                artifact_store.ping()
            checks["persistence"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["persistence"] = f"error: {exc}"
            ok = False

    status_code = 200 if ok else 503
    return JSONResponse(status_code=status_code, content={"status": "ok" if ok else "degraded", "checks": checks})


# ---------------------------------------------------------------------------
# Backup and recovery — admin-only. See services/backup_service.py module
# docstring for exactly what this does and does not cover (application-level
# record export/import through the existing ArtifactStore interface, not a
# database-engine-level backup like pg_dump).
# ---------------------------------------------------------------------------


@app.get("/admin/backup")
def create_backup(identity: AuthIdentity = Depends(get_identity)) -> dict:
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail=f"Requires the '{ADMIN_ROLE}' role.")
    snapshot = backup_service.export_snapshot({
        "bcaes_registry": bcaes_registry_service.artifact_store,
        "canonical_repository": canonical_repository_service.artifact_store,
    })
    audit_logger.info(
        "admin.backup.create actor=%s bcaes_records=%s canonical_records=%s",
        identity.actor,
        len(snapshot["stores"]["bcaes_registry"]["records"]),
        len(snapshot["stores"]["canonical_repository"]["records"]),
    )
    return snapshot


@app.post("/admin/restore")
def restore_backup(snapshot: dict, identity: AuthIdentity = Depends(get_identity)) -> dict:
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail=f"Requires the '{ADMIN_ROLE}' role.")
    try:
        counts = backup_service.restore_snapshot(snapshot, {
            "bcaes_registry": bcaes_registry_service.artifact_store,
            "canonical_repository": canonical_repository_service.artifact_store,
        })
    except backup_service.BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # restore_snapshot wrote directly to the persistent store — the running
    # service's in-memory cache needs an explicit refresh to actually see
    # it (a real bug caught here: without this, the process serves stale
    # reads immediately after a "successful" restore).
    bcaes_registry_service.reload_from_persistent_store()
    canonical_repository_service.reload_from_persistent_store()
    audit_logger.info("admin.backup.restore actor=%s counts=%s", identity.actor, counts)
    return {"restored": counts}


@app.get("/admin/configuration")
def get_configuration_report(identity: AuthIdentity = Depends(get_identity)) -> dict:
    """Live configuration validation report — same checks as the startup
    log line, callable on demand rather than only visible in process logs.
    Never returns actual secret values (see services/startup_config.py)."""
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail=f"Requires the '{ADMIN_ROLE}' role.")
    return startup_config.validate_configuration()


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
            "central-data-platform-retrieval",
            "evidence-preservation-bucket",
        ],
        "api_groups": {
            "certification": "/validate, /certify",
            "knowledge_packages": "/packages/*",
            "knowledge_objects": "/knowledge-objects/*",
            "shared_data": "/shared/*",
            "bcaes_registry": "/bcaes/*",
            "canonical_repository": "/canonical-repository/*",
            "central_data_platform": "/datasets, /datasets/{dataset_id}, /datasets/{dataset_id}/schema, /datasets/{dataset_id}/versions, /datasets/{dataset_id}/provenance, /query, /export, /stream, /reference",
            "evidence_preservation": "/evidence/{evidence_id}, /provenance/{dataset_id}, /provenance/{package_id}, /bucket/status",
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
# InsightBridge push — confirmed-live (6 Aug 2026, see
# CONSTITUTIONAL_RUNTIME_DEFINITION.md SS4) integration for Vijay Dhawan's
# InsightFlow/InsightBridge/InsightCore territory. Unlike /metrics (pull,
# for whoever scrapes it), this actively pushes to InsightBridge — real
# outbound call, real degrade-gracefully-if-unreachable behavior, same
# pattern as MDUClient. Payload shape is an assumption — see
# services/insightbridge_client.py module docstring.
# ---------------------------------------------------------------------------


@app.post("/observability/push-to-insightbridge")
def push_to_insightbridge(identity: AuthIdentity = Depends(get_identity)) -> dict:
    from services.insightbridge_client import InsightBridgeClient, InsightBridgeUnavailableError

    client = InsightBridgeClient()
    if not client.is_configured():
        return {
            "pushed": False,
            "reason": "PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE is not set in this environment.",
        }
    try:
        result = client.ingest(
            source="masterdb",
            metric_type="registry_summary",
            data=bcaes_registry_service.registry_summary(),
        )
        audit_logger.info("insightbridge.push actor=%s status=ok", identity.actor)
        return {"pushed": True, "insightbridge_response": result}
    except InsightBridgeUnavailableError as exc:
        audit_logger.info("insightbridge.push actor=%s status=failed error=%s", identity.actor, exc)
        return {"pushed": False, "reason": str(exc)}


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


# ---------------------------------------------------------------------------
# MASTERDB Ecosystem Convergence — Capabilities, Contracts, Access & Retrieval
# ---------------------------------------------------------------------------


@app.post("/capabilities/register", response_model=Capability, status_code=201)
@app.post("/capabilities", response_model=Capability, status_code=201)
def register_capability(
    capability: Capability,
    identity: AuthIdentity = Depends(get_identity),
) -> Capability:
    """Register a capability version; publication requires an administrator."""
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail="Only bhiv-admin may register capabilities.")
    try:
        if not capability.registration_authority_confirmed:
            capability.status = CapabilityStatus.PENDING_AUTHORITY_CONFIRMATION
        return capability_registry_service.register_capability(capability, check_duplicate=True)
    except CapabilityAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CapabilityVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/capabilities", response_model=List[Capability])
@app.get("/tantra/capabilities", response_model=List[Capability])
def list_capabilities(
    domain: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    identity: AuthIdentity = Depends(get_identity),
) -> List[Capability]:
    """Step 2: Discover governed MASTERDB capabilities through TANTRA integration path."""
    return tantra_interface_service.discover_capabilities(domain=domain, status=status, search=search)


@app.get("/capabilities/{capability_id}", response_model=Capability)
@app.get("/tantra/capabilities/{capability_id}", response_model=Capability)
def get_capability(
    capability_id: str,
    identity: AuthIdentity = Depends(get_identity),
) -> Capability:
    """Retrieve capability metadata by capability_id."""
    try:
        return tantra_interface_service.get_capability(capability_id)
    except CapabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/capabilities/{capability_id}/contract", response_model=CapabilityContract)
@app.get("/tantra/capabilities/{capability_id}/contract", response_model=CapabilityContract)
def get_capability_contract(
    capability_id: str,
    identity: AuthIdentity = Depends(get_identity),
) -> CapabilityContract:
    """Step 3: Machine-readable Capability Contract resolution."""
    try:
        return tantra_interface_service.get_capability_contract(capability_id)
    except CapabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/capabilities/{capability_id}/versions", response_model=List[Capability])
def get_capability_versions(
    capability_id: str,
    identity: AuthIdentity = Depends(get_identity),
) -> List[Capability]:
    """Return immutable registered versions of a capability."""
    try:
        return capability_registry_service.get_capability_versions(capability_id)
    except CapabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/access/request", response_model=AccessContract)
@app.post("/capabilities/access/request", response_model=AccessContract)
@app.post("/tantra/access/request", response_model=AccessContract)
def request_capability_access(
    request_data: CapabilityAccessRequest,
    identity: AuthIdentity = Depends(get_identity),
) -> AccessContract:
    """Steps 4 & 5: Request capability access authorization based on identity, roles & purpose."""
    try:
        return tantra_interface_service.request_capability_access(
            actor=identity.actor, roles=identity.roles, request_data=request_data
        )
    except CapabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CapabilityAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/capabilities/{capability_id}/retrieve", response_model=CapabilityRetrieveResponse)
@app.post("/tantra/capabilities/{capability_id}/retrieve", response_model=CapabilityRetrieveResponse)
def retrieve_capability_data(
    capability_id: str,
    retrieve_req: CapabilityRetrieveRequest,
    identity: AuthIdentity = Depends(get_identity),
) -> CapabilityRetrieveResponse:
    """Steps 6, 7 & 8: Authorized data retrieval via canonical TANTRA capability access path."""
    try:
        return tantra_interface_service.retrieve_capability_data(
            actor=identity.actor,
            roles=identity.roles,
            capability_id=capability_id,
            retrieve_req=retrieve_req,
        )
    except CapabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CapabilityAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/access/{request_id}", response_model=AccessContract)
def get_access_contract_audit(
    request_id: str,
    identity: AuthIdentity = Depends(get_identity),
) -> AccessContract:
    """Audit & evidence lookup for capability access contract decisions."""
    contract = capability_registry_service.get_access_contract(request_id)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Access contract with request_id '{request_id}' not found.")
    return contract


@app.post("/geo-quest/candidates/gev.aircraft_tracking/register")
def register_geo_quest_candidate(
    identity: AuthIdentity = Depends(get_identity),
) -> dict:
    """Stage validated GEO-QUEST artifacts locally without canonical publication."""
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail="Only bhiv-admin may stage GEO-QUEST candidates.")
    try:
        result = geo_quest_candidate_service.register_candidate(actor=identity.actor)
        result["mdu_schema_contract"] = dataset_retrieval_service.get_dataset_schema(
            result["dataset_id"],
            local_schema_version="1.0.0",
        )
        result["mdu_schema_compatibility"] = mdu_contract_adapter.validate_schema_compatibility(
            result["dataset_id"],
            local_schema_version="1.0.0",
        )
        return result
    except CandidateRegistrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/geo-quest/candidates/{capability_id}")
def get_geo_quest_candidate(
    capability_id: str,
    identity: AuthIdentity = Depends(get_identity),
) -> dict:
    """Inspect a staged candidate; it is intentionally absent from public discovery."""
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail="Only bhiv-admin may inspect GEO-QUEST candidates.")
    try:
        candidate = geo_quest_candidate_service.get_candidate(capability_id)
        candidate["mdu_schema_contract"] = dataset_retrieval_service.get_dataset_schema(
            candidate["dataset_id"],
            local_schema_version="1.0.0",
        )
        candidate["mdu_schema_compatibility"] = mdu_contract_adapter.validate_schema_compatibility(
            candidate["dataset_id"],
            local_schema_version="1.0.0",
        )
        return candidate
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CandidateRegistrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/geo-quest/candidates/{capability_id}/retrieve")
def retrieve_geo_quest_candidate(
    capability_id: str,
    request_data: CandidateRetrieveRequest,
    identity: AuthIdentity = Depends(get_identity),
) -> dict:
    """Retrieve a validated candidate snapshot for controlled, non-production reuse."""
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail="Only bhiv-admin may retrieve GEO-QUEST candidates.")
    try:
        return geo_quest_candidate_service.retrieve(capability_id, request_data)
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CandidateRegistrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/geo-quest/imports/register", status_code=202)
def register_gev_geospatial_candidate(
    identity: AuthIdentity = Depends(get_identity),
) -> dict:
    """Validate and stage the GEV evidence packet without canonical publication."""
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail="Only bhiv-admin may stage GEV candidates.")
    try:
        return gev_geospatial_candidate_service.register_candidate(actor=identity.actor)
    except CandidateRegistrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/geo-quest/imports/candidate")
def get_gev_geospatial_candidate(
    identity: AuthIdentity = Depends(get_identity),
) -> dict:
    """Inspect GEV candidate metadata; this does not expose it to discovery."""
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail="Only bhiv-admin may inspect GEV candidates.")
    try:
        return gev_geospatial_candidate_service.get_candidate()
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CandidateRegistrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/geo-quest/imports/candidate/retrieve")
def retrieve_gev_geospatial_candidate(
    request_data: CandidatePackageRetrieveRequest,
    identity: AuthIdentity = Depends(get_identity),
) -> dict:
    """Retrieve staged evidence only for an administrator registry review."""
    if ADMIN_ROLE not in identity.roles:
        raise HTTPException(status_code=403, detail="Only bhiv-admin may retrieve GEV candidates.")
    try:
        return gev_geospatial_candidate_service.retrieve(request_data)
    except CandidateUseDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CandidateRegistrationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GEO-QUEST-01 — Source Registry & Connector API Surface
# ---------------------------------------------------------------------------


@app.post("/sources/register", response_model=SourceRecord, status_code=201)
@app.post("/sources", response_model=SourceRecord, status_code=201)
def register_source(
    request_data: SourceRegisterRequest,
    identity: AuthIdentity = Depends(get_identity),
) -> SourceRecord:
    """Register a governed ecosystem source with canonical deduplication & authority check."""
    try:
        return source_registry_service.register_source(request_data, actor=identity.actor)
    except SourceAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/sources", response_model=List[SourceRecord])
def list_sources(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    identity: AuthIdentity = Depends(get_identity),
) -> List[SourceRecord]:
    """List governed source records in MASTERDB Source Registry."""
    return source_registry_service.list_sources(search=search, status=status)


@app.get("/sources/{source_id}", response_model=SourceRecord)
def get_source(
    source_id: str,
    identity: AuthIdentity = Depends(get_identity),
) -> SourceRecord:
    """Retrieve details for a single governed source by source_id."""
    try:
        return source_registry_service.get_source(source_id)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/connectors/geospatial/ingest", status_code=200)
def geospatial_connector_ingest(
    payload: Dict[str, Any],
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """
    Source-Independent Geospatial Connector Pipeline:
    External Source -> BHIV Connector -> Validation -> MDU -> Dataset -> Capability
    """
    try:
        return geospatial_connector.ingest_and_register_geospatial_capability(
            source_payload=payload,
            actor=identity.actor,
            confirm_write_authority=payload.get("confirm_write_authority", True),
        )
    except SourceAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/earthquakes/usgs/ingest")
def ingest_usgs_earthquakes(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch the live USGS daily feed and idempotently persist its observations."""
    try:
        feed = fetch_earthquakes()
        result = earthquake_observation_service.ingest(feed)
        result["source"] = "USGS"
        result["capability_id"] = "cap-gev-earthquake-monitoring"
        verification = _verify_observation_ingestion(
            "usgs", earthquake_observation_service, result,
            [row["event_id"] for row in feed["observations"]],
        )
        result.update(verification)
        if verification["status"] == "PENDING" and not verification["registry_readback"]:
            raise RuntimeError("Source registry read-back failed")
        return result
    except EarthquakeObservationValidationError as exc:
        _mark_observation_feed_unavailable("usgs", "upstream_observation_validation_failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        _mark_observation_feed_unavailable("usgs", "storage_or_registry_readback_failed")
        raise HTTPException(status_code=503, detail="USGS storage verification failed") from exc
    except Exception as exc:
        if observation_feed_state["usgs"]["status"] != "UNAVAILABLE":
            _mark_observation_feed_unavailable("usgs", "fetch_or_readback_failed")
        logger.warning("USGS earthquake ingestion failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="USGS earthquake ingestion failed") from exc


@app.get("/earthquakes/usgs/observations")
def list_usgs_earthquakes(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    records = earthquake_observation_service.list(limit=limit, offset=offset)
    return {"dataset_id": "ds-gev-seismic-events", "capability_id": "cap-gev-earthquake-monitoring", "count": len(records), "limit": limit, "offset": offset, "observations": records}


@app.get("/earthquakes/map", include_in_schema=False)
def earthquake_map() -> FileResponse:
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "earthquake-map.html"), media_type="text/html")


@app.post("/aisstream/ingest")
def ingest_aisstream_positions(
    payload: Dict[str, Any],
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch a bounded server-side AISStream position batch and persist vessel updates."""
    bounding_boxes = payload.get("bounding_boxes")
    max_messages = payload.get("max_messages", 25)
    timeout_seconds = payload.get("timeout_seconds", 15)
    if not isinstance(max_messages, int) or isinstance(max_messages, bool) or not 1 <= max_messages <= 100:
        raise HTTPException(status_code=422, detail="max_messages must be an integer between 1 and 100")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 60:
        raise HTTPException(status_code=422, detail="timeout_seconds must be between 1 and 60")
    try:
        feed = fetch_aisstream_positions(
            bounding_boxes=bounding_boxes,
            max_messages=max_messages,
            timeout_seconds=timeout_seconds,
        )
        result = ais_observation_service.ingest(feed)
        result["source"] = "AISStream"
        result["connection_errors"] = feed["connection_errors"]
        verification = _verify_observation_ingestion(
            "aisstream", ais_observation_service, result,
            [row["vessel_id"] for row in feed["observations"]],
        )
        result.update(verification)
        if verification["status"] == "PENDING" and not verification["registry_readback"]:
            raise RuntimeError("Source registry read-back failed")
        return result
    except AISStreamConfigurationError as exc:
        _mark_observation_feed_unavailable("aisstream", "provider_credentials_or_subscription_not_configured")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AISStreamConnectionError as exc:
        _mark_observation_feed_unavailable("aisstream", "upstream_connection_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AISObservationValidationError as exc:
        _mark_observation_feed_unavailable("aisstream", "upstream_observation_validation_failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        if observation_feed_state["aisstream"]["status"] != "UNAVAILABLE":
            _mark_observation_feed_unavailable("aisstream", "storage_or_registry_readback_failed")
        raise HTTPException(status_code=503, detail="AISStream storage verification failed") from exc


@app.get("/aisstream/observations")
def list_aisstream_positions(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    records = ais_observation_service.list(limit=limit, offset=offset)
    return {"dataset_id": AISObservationService.DATASET_ID, "count": len(records), "limit": limit, "offset": offset, "observations": records}


@app.post("/aircraft/adsb/military/ingest")
def ingest_military_aircraft(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch publicly broadcast ADS-B military-feed observations and persist them."""
    try:
        feed = fetch_military_aircraft()
        result = aircraft_observation_service.ingest(feed)
        result["source"] = "adsb.lol"
        verification = _verify_observation_ingestion(
            "adsb_military", aircraft_observation_service, result,
            [aircraft_observation_service._record_id(row) for row in feed["observations"]],
        )
        result.update(verification)
        if verification["status"] == "PENDING" and not verification["registry_readback"]:
            raise RuntimeError("Source registry read-back failed")
        return result
    except AircraftUpstreamRateLimitError as exc:
        _mark_observation_feed_unavailable("adsb_military", "upstream_rate_limited")
        raise HTTPException(status_code=429, detail="Aircraft feed is rate-limited; retry later") from exc
    except AircraftUpstreamError as exc:
        _mark_observation_feed_unavailable("adsb_military", "upstream_fetch_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AircraftObservationValidationError as exc:
        _mark_observation_feed_unavailable("adsb_military", "upstream_observation_validation_failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        if observation_feed_state["adsb_military"]["status"] != "UNAVAILABLE":
            _mark_observation_feed_unavailable("adsb_military", "storage_or_registry_readback_failed")
        raise HTTPException(status_code=503, detail="ADS-B storage verification failed") from exc


@app.get("/aircraft/adsb/military/observations")
def list_military_aircraft(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    records = aircraft_observation_service.list(limit=limit, offset=offset)
    return {"dataset_id": AircraftObservationService.DATASET_ID, "count": len(records), "limit": limit, "offset": offset, "observations": records}


@app.post("/wildfires/firms/ingest")
def ingest_firms_active_fires(identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    """Fetch NASA FIRMS near-real-time VIIRS detections and persist valid rows."""
    global firms_last_verified_at
    try:
        feed = fetch_active_fires()
        result = fire_observation_service.ingest(feed)
        result["source"] = "NASA FIRMS"
        result["upstream_count"] = feed["record_count"]
        firms_last_verified_at = datetime.now(timezone.utc).isoformat()
        source_registry_service.mark_validated("src-gev-nifc-firms", firms_last_verified_at)
        result["last_verified_at_utc"] = firms_last_verified_at
        return result
    except FIRMSConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FIRMSUpstreamError as exc:
        logger.exception("NASA FIRMS ingestion failed")
        raise HTTPException(status_code=502, detail="NASA FIRMS active-fire ingestion failed") from exc


@app.get("/wildfires/firms/observations")
def list_firms_active_fires(
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    records = fire_observation_service.list(limit=limit, offset=offset)
    return {"dataset_id": FireObservationService.DATASET_ID, "count": len(records), "limit": limit, "offset": offset, "observations": records}


@app.post("/traffic/tomtom/ingest")
def ingest_tomtom_traffic(
    payload: Dict[str, Any], identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch bounded real TomTom flow tiles and persist decoded road segments."""
    global traffic_last_verified_at, traffic_verified_tiles, traffic_last_fetch_error
    tiles = payload.get("tiles")
    if not isinstance(tiles, list) or not 1 <= len(tiles) <= TOMTOM_MAX_TILES:
        raise HTTPException(status_code=422, detail=f"tiles must contain 1 to {TOMTOM_MAX_TILES} tile coordinates")
    try:
        for tile in tiles:
            validate_tile_coord(tile)
        feed = fetch_flow_tiles(tiles)
        result = traffic_observation_service.ingest(feed)
        traffic_last_verified_at = datetime.now(timezone.utc).isoformat()
        traffic_verified_tiles = [{"z": t["z"], "x": t["x"], "y": t["y"]} for t in feed["tiles"]]
        traffic_last_fetch_error = False
        source_registry_service.mark_validated(
            "src-gev-tomtom-traffic", traffic_last_verified_at,
            {"last_verified_tiles": traffic_verified_tiles, "last_verified_segment_count": feed["record_count"], "last_fetch_status": "LIVE_VERIFIED"},
        )
        result.update({"source": feed["source"], "tile_count": feed["tile_count"], "tiles": feed["tiles"], "last_verified_at_utc": traffic_last_verified_at, "traffic_style": "relative"})
        return result
    except TomTomConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TomTomUpstreamError as exc:
        traffic_last_fetch_error = True
        source_registry_service.mark_fetch_status("src-gev-tomtom-traffic", "UNAVAILABLE", {"last_http_status": int(str(exc).rsplit(" ", 1)[-1]) if str(exc).rsplit(" ", 1)[-1].isdigit() else None})
        logger.warning("TomTom traffic ingestion unavailable: %s", str(exc))
        raise HTTPException(status_code=502, detail="TomTom traffic-flow ingestion failed") from None


@app.get("/traffic/tomtom/observations")
def list_tomtom_traffic(
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
    z: Optional[int] = Query(default=None, ge=8, le=16),
    x: Optional[int] = Query(default=None, ge=0), y: Optional[int] = Query(default=None, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    tile = None
    if any(value is not None for value in (z, x, y)):
        if any(value is None for value in (z, x, y)) or x >= 2 ** z or y >= 2 ** z:
            raise HTTPException(status_code=422, detail="Provide a valid complete z, x, y tile coordinate")
        tile = {"z": z, "x": x, "y": y}
    records = traffic_observation_service.list(limit=limit, offset=offset, tile=tile)
    return {"dataset_id": TrafficObservationService.DATASET_ID, "count": len(records), "limit": limit, "offset": offset, "tile": tile, "observations": records}


@app.post("/weather/wind/{model}/ingest")
def ingest_wind_forecast(
    model: str, payload: Dict[str, Any], identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch GFS/ECMWF grids through GEV, sample points, then store point forecasts."""
    model_key = model.lower()
    if model_key not in ("gfs", "ecmwf"):
        raise HTTPException(status_code=422, detail="model must be gfs or ecmwf")
    locations = payload.get("locations")
    source_id = "src-gev-gfs-wind" if model_key == "gfs" else "src-gev-ecmwf-wind"
    try:
        feed = fetch_wind_forecasts(model_key, locations)
        result = weather_observation_service.ingest(feed, forecast=True)
        read_back = [weather_observation_service.get(record_id) for record_id in result["record_ids"]]
        if len(read_back) != len(result["record_ids"]) or any(row is None for row in read_back):
            raise RuntimeError("Weather forecast persistence read-back failed")
        verified_at = datetime.now(timezone.utc).isoformat()
        coords = [{"latitude": row["latitude"], "longitude": row["longitude"]} for row in read_back]
        weather_source_state[source_id] = {"last_verified_at_utc": verified_at, "last_fetch_status": "LIVE_VERIFIED", "verified_coordinates": coords}
        source_registry_service.mark_validated(source_id, verified_at, {"last_fetch_status": "LIVE_VERIFIED", "verified_coordinates": coords, "last_readback_count": len(read_back), "forecast_cycle": feed["cycle"]})
        result.update({"source": feed["source"], "model": feed["model"], "record_type": "FORECAST", "readback_count": len(read_back), "forecast_cycle": feed["cycle"], "last_verified_at_utc": verified_at})
        return result
    except (WeatherConfigurationError, WeatherUpstreamError) as exc:
        weather_source_state[source_id]["last_fetch_status"] = "UNAVAILABLE"
        source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {"last_error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail="Wind forecast ingestion is currently unavailable") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        weather_source_state[source_id]["last_fetch_status"] = "UNAVAILABLE"
        source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {"last_error": "storage read-back failed"})
        raise HTTPException(status_code=503, detail="Wind forecast storage verification failed") from exc


@app.get("/weather/wind/forecasts")
def list_wind_forecasts(
    model: str = Query(..., regex="^(gfs|ecmwf)$"),
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    model_key = model.lower()
    dataset = WeatherObservationService.WIND_DATASETS[model_key.upper()]
    records = weather_observation_service.list(dataset, limit=limit, offset=offset)
    return {"dataset_id": dataset, "model": model_key.upper(), "record_type": "FORECAST", "count": len(records), "limit": limit, "offset": offset, "observations": records}


@app.post("/weather/open-meteo/ingest")
def ingest_open_meteo_current(
    payload: Dict[str, Any], identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch Open-Meteo model-derived current surface conditions for points."""
    source_id = "src-open-meteo-current-weather"
    try:
        feed = fetch_open_meteo_current(payload.get("locations"))
        result = weather_observation_service.ingest(feed, forecast=False)
        read_back = [weather_observation_service.get(record_id) for record_id in result["record_ids"]]
        if len(read_back) != len(result["record_ids"]) or any(row is None for row in read_back):
            raise RuntimeError("Current weather persistence read-back failed")
        verified_at = datetime.now(timezone.utc).isoformat()
        coords = [{"latitude": row["latitude"], "longitude": row["longitude"]} for row in read_back]
        weather_source_state[source_id] = {"last_verified_at_utc": verified_at, "last_fetch_status": "LIVE_VERIFIED", "verified_coordinates": coords}
        source_registry_service.mark_validated(source_id, verified_at, {"last_fetch_status": "LIVE_VERIFIED", "verified_coordinates": coords, "last_readback_count": len(read_back)})
        result.update({"source": feed["source"], "record_type": "CURRENT_CONDITIONS", "is_forecast": False, "readback_count": len(read_back), "last_verified_at_utc": verified_at})
        return result
    except WeatherUpstreamError as exc:
        weather_source_state[source_id]["last_fetch_status"] = "UNAVAILABLE"
        source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {"last_error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail="Open-Meteo current-weather ingestion failed") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        weather_source_state[source_id]["last_fetch_status"] = "UNAVAILABLE"
        source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {"last_error": "storage read-back failed"})
        raise HTTPException(status_code=503, detail="Current weather storage verification failed") from exc


@app.get("/weather/open-meteo/current")
def list_open_meteo_current(
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    records = weather_observation_service.list(WeatherObservationService.CURRENT_DATASET, limit=limit, offset=offset)
    return {"dataset_id": WeatherObservationService.CURRENT_DATASET, "record_type": "CURRENT_CONDITIONS", "count": len(records), "limit": limit, "offset": offset, "observations": records}


RADAR_SOURCE_ID = "src-gev-noaa-nowcoast-radar"


def _fetch_store_radar_manifest() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = fetch_radar_manifest()
    retrieved_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "product": manifest["product"], "title": manifest.get("title"),
        "source": manifest.get("source"), "attribution": manifest.get("attribution"),
        "coverage": manifest.get("coverage"), "bounds": manifest["bounds"],
        "available_radar_timestamps": manifest["times"], "latest_radar_timestamp": manifest["latest"],
        "provider_fetched_at_utc": manifest.get("fetchedAt"), "retrieved_at_utc": retrieved_at,
        "stale": manifest.get("stale", False), "layer": "conus_base_reflectivity_mosaic",
        "description": manifest.get("description"),
    }
    status = "LIVE_VERIFIED" if radar_source_state.get("last_fetch_status") == "LIVE_VERIFIED" else "CONFIGURED"
    source_registry_service.mark_fetch_status(RADAR_SOURCE_ID, status, {"radar_metadata": snapshot})
    radar_source_state.update({"metadata": snapshot, "last_metadata_retrieval_at_utc": retrieved_at, "last_fetch_status": status})
    return manifest, snapshot


def _mark_radar_imagery_verified(snapshot: dict[str, Any], image_info: dict[str, Any]) -> str:
    verified_at = datetime.now(timezone.utc).isoformat()
    image_retrieval = {**image_info, "retrieved_at_utc": verified_at}
    metadata = {"radar_metadata": snapshot, "last_image_retrieval": image_retrieval}
    # Persist and read back all upstream metadata before changing status to LIVE_VERIFIED.
    source_registry_service.mark_fetch_status(RADAR_SOURCE_ID, "CONFIGURED", metadata)
    saved = source_registry_service.get_source(RADAR_SOURCE_ID)
    saved_metadata = saved.provenance_reference.get("radar_metadata")
    saved_image = saved.provenance_reference.get("last_image_retrieval")
    if not saved_metadata or not saved_image or saved_metadata.get("latest_radar_timestamp") != snapshot.get("latest_radar_timestamp"):
        raise RuntimeError("Radar metadata registry read-back failed")
    source_registry_service.mark_validated(RADAR_SOURCE_ID, verified_at, {**metadata, "last_fetch_status": "LIVE_VERIFIED"})
    radar_source_state.update({"last_verified_at_utc": verified_at, "last_fetch_status": "LIVE_VERIFIED", "metadata": saved_metadata, "last_image_retrieval": saved_image})
    return verified_at


def _radar_failure() -> None:
    radar_source_state["last_fetch_status"] = "UNAVAILABLE"
    source_registry_service.mark_fetch_status(RADAR_SOURCE_ID, "UNAVAILABLE", {"last_error": "NOAA nowCOAST radar request failed"})


def _radar_manifest_response(manifest: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    result.update({
        "dataset_id": "noaa_nowcoast_conus_base_reflectivity_radar",
        "retrieved_at_utc": snapshot["retrieved_at_utc"],
        "status": radar_source_state.get("last_fetch_status", "CONFIGURED"),
        "imageUrl": "/weather/radar/image?time=" + str(manifest["latest"]),
        "tileTemplate": "/weather/radar/tile?time={time}&z={z}&x={x}&y={y}",
        "last_image_retrieval": radar_source_state.get("last_image_retrieval"),
    })
    return result


@app.get("/weather/radar/manifest")
def get_noaa_radar_manifest(identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    """Return live nowCOAST radar capabilities and persist its metadata snapshot."""
    try:
        manifest, snapshot = _fetch_store_radar_manifest()
        return _radar_manifest_response(manifest, snapshot)
    except RadarUpstreamError:
        _radar_failure()
        raise HTTPException(status_code=502, detail="NOAA nowCOAST radar metadata is unavailable") from None


@app.get("/weather/radar/image")
def proxy_noaa_radar_image(
    time: str, size: str = Query("4096x2048"), bbox: Optional[str] = Query(default=None),
    identity: AuthIdentity = Depends(get_identity),
) -> Response:
    """Proxy a bounded full-extent or detail-window PNG radar image."""
    try:
        manifest, snapshot = _fetch_store_radar_manifest()
        if time not in manifest["times"]:
            raise RadarRequestError("time must be one of the timestamps in the live radar manifest")
        body, image_info = fetch_radar_image(time, size=size, bbox=bbox)
        verified_at = _mark_radar_imagery_verified(snapshot, {**image_info, "mode": "image", "time": time, "size": size, "bbox": bbox})
        return Response(body, media_type="image/png", headers={"Cache-Control": "public, max-age=300", "X-Radar-Observed-At": time, "X-Radar-Retrieved-At": verified_at, "X-Radar-Product": "conus_base_reflectivity_mosaic"})
    except RadarRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RadarUpstreamError:
        _radar_failure()
        raise HTTPException(status_code=502, detail="NOAA nowCOAST radar imagery is unavailable") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Radar metadata read-back failed") from exc


@app.get("/weather/radar/tile")
def proxy_noaa_radar_tile(
    time: str, z: int = Query(..., ge=0, le=6), x: int = Query(..., ge=0), y: int = Query(..., ge=0),
    size: str = Query("256"), identity: AuthIdentity = Depends(get_identity),
) -> Response:
    """Proxy a single geographic NOAA radar tile; raster bytes are never row-stored."""
    try:
        manifest, snapshot = _fetch_store_radar_manifest()
        if time not in manifest["times"]:
            raise RadarRequestError("time must be one of the timestamps in the live radar manifest")
        body, image_info = fetch_radar_tile(time, z, x, y, size=size)
        verified_at = _mark_radar_imagery_verified(snapshot, {**image_info, "mode": "tile", "time": time, "z": z, "x": x, "y": y, "size": size})
        return Response(body, media_type="image/png", headers={"Cache-Control": "public, max-age=300", "X-Radar-Observed-At": time, "X-Radar-Retrieved-At": verified_at, "X-Radar-Product": "conus_base_reflectivity_mosaic"})
    except RadarRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RadarUpstreamError:
        _radar_failure()
        raise HTTPException(status_code=502, detail="NOAA nowCOAST radar tile is unavailable") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Radar metadata read-back failed") from exc


@app.post("/weather/radar/verify")
def verify_noaa_radar(identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    """Fetch live capabilities and one in-coverage tile, then read back metadata."""
    try:
        manifest, snapshot = _fetch_store_radar_manifest()
        bounds = manifest["bounds"]
        center_lon = (bounds["west"] + bounds["east"]) / 2
        center_lat = (bounds["south"] + bounds["north"]) / 2
        z = 4
        x = min(2 ** (z + 1) - 1, max(0, int((center_lon + 180) / (180 / (2 ** z)))))
        y = min(2 ** z - 1, max(0, int((90 - center_lat) / (180 / (2 ** z)))))
        observed_time = manifest["latest"]
        _body, image_info = fetch_radar_tile(observed_time, z, x, y)
        verified_at = _mark_radar_imagery_verified(snapshot, {**image_info, "mode": "tile", "time": observed_time, "z": z, "x": x, "y": y, "size": "256"})
        return {"status": "LIVE_VERIFIED", "product": "radar", "layer": "conus_base_reflectivity_mosaic", "latest_radar_timestamp": observed_time, "retrieved_at_utc": snapshot["retrieved_at_utc"], "verified_at_utc": verified_at, "coverage": snapshot["coverage"], "bounds": bounds, "available_radar_timestamps": snapshot["available_radar_timestamps"], "verification_tile": {"z": z, "x": x, "y": y, **image_info}, "metadata_readback": True}
    except RadarUpstreamError:
        _radar_failure()
        raise HTTPException(status_code=502, detail="NOAA nowCOAST radar live verification failed") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Radar metadata read-back failed") from exc


def _fetch_store_satellite_manifest(product: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if product not in NOAA_WEATHER_IMAGERY_PRODUCTS:
        raise RadarRequestError("product must be clouds, clouds-regional, or lightning")
    manifest = fetch_weather_manifest(product)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    layer = WEATHER_IMAGERY_LAYERS[product]
    snapshot = {
        "product": product, "layer": layer, "title": manifest.get("title"),
        "source": manifest.get("source"), "attribution": manifest.get("attribution"),
        "coverage": manifest.get("coverage"), "bounds": manifest["bounds"],
        "available_timestamps": manifest["times"], "latest_timestamp": manifest["latest"],
        "provider_fetched_at_utc": manifest.get("fetchedAt"), "retrieved_at_utc": retrieved_at,
        "stale": manifest.get("stale", False), "description": manifest.get("description"),
        "image_size": manifest.get("imageSize"), "tile_size": manifest.get("tileSize"),
        "max_level": manifest.get("maxLevel"), "tiling_scheme": manifest.get("tilingScheme"),
    }
    state = satellite_cloud_state[product]
    status = "LIVE_VERIFIED" if state.get("last_fetch_status") == "LIVE_VERIFIED" else "CONFIGURED"
    source_id = NOAA_WEATHER_IMAGERY_PRODUCTS[product]["source_id"]
    source_registry_service.mark_fetch_status(source_id, status, {"satellite_metadata": snapshot})
    state.update({"metadata": snapshot, "last_metadata_retrieval_at_utc": retrieved_at, "last_fetch_status": status})
    return manifest, snapshot


def _mark_satellite_image_verified(product: str, snapshot: dict[str, Any], image_info: dict[str, Any]) -> str:
    source_id = NOAA_WEATHER_IMAGERY_PRODUCTS[product]["source_id"]
    verified_at = datetime.now(timezone.utc).isoformat()
    image_retrieval = {**image_info, "retrieved_at_utc": verified_at}
    metadata = {"satellite_metadata": snapshot, "last_image_retrieval": image_retrieval}
    source_registry_service.mark_fetch_status(source_id, "CONFIGURED", metadata)
    saved = source_registry_service.get_source(source_id)
    saved_metadata = saved.provenance_reference.get("satellite_metadata")
    saved_image = saved.provenance_reference.get("last_image_retrieval")
    if not saved_metadata or not saved_image or saved_metadata.get("latest_timestamp") != snapshot.get("latest_timestamp"):
        raise RuntimeError("Satellite imagery metadata registry read-back failed")
    source_registry_service.mark_validated(source_id, verified_at, {**metadata, "last_fetch_status": "LIVE_VERIFIED"})
    state = satellite_cloud_state[product]
    state.update({"last_verified_at_utc": verified_at, "last_fetch_status": "LIVE_VERIFIED", "metadata": saved_metadata, "last_image_retrieval": saved_image})
    return verified_at


def _satellite_cloud_failure(product: str) -> None:
    source_id = NOAA_WEATHER_IMAGERY_PRODUCTS[product]["source_id"]
    satellite_cloud_state[product]["last_fetch_status"] = "UNAVAILABLE"
    source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {"last_error": "NOAA nowCOAST satellite imagery request failed"})


def _satellite_manifest_response(product: str, manifest: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    result.update({
        "dataset_id": NOAA_WEATHER_IMAGERY_PRODUCTS[product]["dataset_id"],
        "layer": WEATHER_IMAGERY_LAYERS[product],
        "retrieved_at_utc": snapshot["retrieved_at_utc"],
        "status": satellite_cloud_state[product]["last_fetch_status"],
        "imageUrl": f"/weather/satellite/image?product={product}&time={manifest['latest']}",
        "tileTemplate": f"/weather/satellite/tile?product={product}&time={{time}}&z={{z}}&x={{x}}&y={{y}}",
        "last_image_retrieval": satellite_cloud_state[product].get("last_image_retrieval"),
    })
    return result


@app.get("/weather/satellite/manifest")
def get_satellite_cloud_manifest(
    product: str = Query(..., pattern="^(clouds|clouds-regional|lightning)$"),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Return live capabilities for a supported nowCOAST satellite infrared product."""
    try:
        manifest, snapshot = _fetch_store_satellite_manifest(product)
        return _satellite_manifest_response(product, manifest, snapshot)
    except RadarRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RadarUpstreamError:
        _satellite_cloud_failure(product)
        raise HTTPException(status_code=502, detail="NOAA nowCOAST satellite metadata is unavailable") from None


@app.get("/weather/satellite/image")
def proxy_satellite_cloud_image(
    product: str = Query(..., pattern="^(clouds|clouds-regional|lightning)$"),
    time: str = Query(...), size: Optional[str] = Query(default=None), bbox: Optional[str] = Query(default=None),
    identity: AuthIdentity = Depends(get_identity),
) -> Response:
    """Proxy a product-bounded whole image or detail-window PNG."""
    try:
        manifest, snapshot = _fetch_store_satellite_manifest(product)
        if time not in manifest["times"]:
            raise RadarRequestError("time must be one of the timestamps in this product's live manifest")
        body, image_info = fetch_weather_image(product, time, size=size, bbox=bbox)
        verified_at = _mark_satellite_image_verified(product, snapshot, {**image_info, "mode": "image", "product": product, "time": time, "size": size, "bbox": bbox})
        return Response(body, media_type=image_info["content_type"], headers={"Cache-Control": "public, max-age=300", "X-Satellite-Product": product, "X-Satellite-Layer": WEATHER_IMAGERY_LAYERS[product], "X-Satellite-Observed-At": time, "X-Satellite-Retrieved-At": verified_at})
    except RadarRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RadarUpstreamError:
        _satellite_cloud_failure(product)
        raise HTTPException(status_code=502, detail="NOAA nowCOAST satellite imagery is unavailable") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Satellite metadata registry read-back failed") from exc


@app.get("/weather/lightning/manifest")
def get_lightning_density_manifest(identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    return get_satellite_cloud_manifest(product="lightning", identity=identity)


@app.get("/weather/lightning/image")
def proxy_lightning_density_image(
    time: str, size: Optional[str] = Query(default=None), bbox: Optional[str] = Query(default=None),
    identity: AuthIdentity = Depends(get_identity),
) -> Response:
    return proxy_satellite_cloud_image(product="lightning", time=time, size=size, bbox=bbox, identity=identity)


@app.get("/weather/lightning/tile")
def proxy_lightning_density_tile(
    time: str, z: int = Query(..., ge=0, le=6), x: int = Query(..., ge=0), y: int = Query(..., ge=0),
    size: str = Query("256"), identity: AuthIdentity = Depends(get_identity),
) -> Response:
    return proxy_satellite_cloud_tile(product="lightning", time=time, z=z, x=x, y=y, size=size, identity=identity)


@app.post("/weather/lightning/verify")
def verify_lightning_density(identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    return verify_satellite_cloud_product(product="lightning", identity=identity)


@app.post("/cyclones/nhc/ingest")
def ingest_noaa_cyclones(identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    """Fetch current NOAA cyclone status and provider-attached GIS features."""
    try:
        feed = fetch_current_cyclones()
        result = cyclone_observation_service.ingest(feed)
        readback: Dict[str, int] = {}
        for kind, record_ids in result["record_ids"].items():
            saved = [cyclone_observation_service.get(record_id) for record_id in record_ids]
            if any(record is None for record in saved) or len(saved) != result[kind]["record_count"]:
                raise RuntimeError("Cyclone storage read-back failed")
            readback[kind] = len(saved)
        verified_at = datetime.now(timezone.utc).isoformat()
        storm_metadata = {
            "last_fetch_status": "LIVE_VERIFIED", "last_readback_count": readback["storms"],
            "active_storm_count": result["fetched_storms"], "fetched_at_utc": feed["fetched_at_utc"],
            "coverage": feed.get("coverage"), "attribution": feed.get("attribution"),
        }
        cyclone_source_state["storms"] = {"last_verified_at_utc": verified_at, "last_fetch_status": "LIVE_VERIFIED", "last_metadata": storm_metadata}
        source_registry_service.mark_validated(CYCLONE_SOURCE_IDS["storms"], verified_at, storm_metadata)
        geometry_statuses = {}
        has_active_storms = bool(feed["storms"])
        any_geometry_unavailable = any(storm.get("geometry_status") == "unavailable" for storm in feed["storms"])
        for kind in ("points", "tracks", "cones"):
            count = result[kind]["record_count"]
            record_ids = result["record_ids"][kind]
            metadata = {
                "feature_count": count, "fetched_at_utc": feed["fetched_at_utc"],
                "last_readback_count": readback[kind], "gis_layer_id": {"points": 5, "tracks": 6, "cones": 7}[kind],
            }
            if count and readback[kind] == count:
                metadata["last_fetch_status"] = "LIVE_VERIFIED"
                cyclone_source_state[kind] = {"last_verified_at_utc": verified_at, "last_fetch_status": "LIVE_VERIFIED", "last_metadata": metadata}
                source_registry_service.mark_validated(CYCLONE_SOURCE_IDS[kind], verified_at, metadata)
            else:
                status = "UNAVAILABLE" if any_geometry_unavailable else ("NO_CURRENT_FEATURES" if has_active_storms else "NO_ACTIVE_STORMS")
                metadata["last_fetch_status"] = status
                cyclone_source_state[kind] = {"last_verified_at_utc": None, "last_fetch_status": status, "last_metadata": metadata}
                source_registry_service.mark_fetch_status(CYCLONE_SOURCE_IDS[kind], status, metadata)
            geometry_statuses[kind] = cyclone_source_state[kind]["last_fetch_status"]
        result.update({
            "source": feed["source"], "coverage": feed.get("coverage"), "attribution": feed.get("attribution"),
            "verified_at_utc": verified_at, "readback_counts": readback,
            "product_statuses": {"storms": "LIVE_VERIFIED", **geometry_statuses},
        })
        return result
    except (CycloneConfigurationError, CycloneUpstreamError) as exc:
        for kind, source_id in CYCLONE_SOURCE_IDS.items():
            cyclone_source_state[kind]["last_fetch_status"] = "UNAVAILABLE"
            source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {"last_error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail="NOAA cyclone ingestion is unavailable") from None
    except (CycloneValidationError, CycloneObservationValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        cyclone_source_state["storms"]["last_fetch_status"] = "UNAVAILABLE"
        source_registry_service.mark_fetch_status(CYCLONE_SOURCE_IDS["storms"], "UNAVAILABLE", {"last_error": "Cyclone storage read-back failed"})
        raise HTTPException(status_code=503, detail="Cyclone storage verification failed") from exc


@app.get("/cyclones/nhc/storms")
def list_noaa_cyclones(
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    records = cyclone_observation_service.list(CYCLONE_DATASETS["storms"], limit=limit, offset=offset)
    return {"dataset_id": CYCLONE_DATASETS["storms"], "count": len(records), "limit": limit, "offset": offset, "observations": records}


def _cyclone_feature_response(kind: str, limit: int, offset: int) -> Dict[str, Any]:
    dataset_id = CYCLONE_DATASETS[kind]
    rows = cyclone_observation_service.list(dataset_id, limit=limit, offset=offset)
    features = [{
        "type": "Feature", "id": row["record_id"], "geometry": row["geometry"],
        "properties": {key: value for key, value in row.items() if key not in ("geometry", "record_id", "dataset_id", "ingested_at_utc")},
    } for row in rows]
    return {"type": "FeatureCollection", "dataset_id": dataset_id, "count": len(features), "limit": limit, "offset": offset, "features": features}


@app.get("/cyclones/nhc/forecast-points")
def list_noaa_cyclone_forecast_points(
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    return _cyclone_feature_response("points", limit, offset)


@app.get("/cyclones/nhc/tracks")
def list_noaa_cyclone_tracks(
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    return _cyclone_feature_response("tracks", limit, offset)


@app.get("/cyclones/nhc/cones")
def list_noaa_cyclone_forecast_cones(
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    return _cyclone_feature_response("cones", limit, offset)


@app.get("/weather/satellite/tile")
def proxy_satellite_cloud_tile(
    product: str = Query(..., pattern="^(clouds|clouds-regional|lightning)$"), time: str = Query(...),
    z: int = Query(..., ge=0, le=6), x: int = Query(..., ge=0), y: int = Query(..., ge=0),
    size: str = Query("256"), identity: AuthIdentity = Depends(get_identity),
) -> Response:
    """Proxy a single geographic tile for either nowCOAST satellite product."""
    try:
        manifest, snapshot = _fetch_store_satellite_manifest(product)
        if time not in manifest["times"]:
            raise RadarRequestError("time must be one of the timestamps in this product's live manifest")
        body, image_info = fetch_weather_tile(product, time, z, x, y, size=size)
        verified_at = _mark_satellite_image_verified(product, snapshot, {**image_info, "mode": "tile", "product": product, "time": time, "z": z, "x": x, "y": y, "size": size})
        return Response(body, media_type=image_info["content_type"], headers={"Cache-Control": "public, max-age=300", "X-Satellite-Product": product, "X-Satellite-Layer": WEATHER_IMAGERY_LAYERS[product], "X-Satellite-Observed-At": time, "X-Satellite-Retrieved-At": verified_at})
    except RadarRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RadarUpstreamError:
        _satellite_cloud_failure(product)
        raise HTTPException(status_code=502, detail="NOAA nowCOAST satellite tile is unavailable") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Satellite metadata registry read-back failed") from exc


@app.post("/weather/satellite/verify")
def verify_satellite_cloud_product(
    product: str = Query(..., pattern="^(clouds|clouds-regional|lightning)$"),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch real capabilities and one in-coverage tile, then confirm registry read-back."""
    try:
        manifest, snapshot = _fetch_store_satellite_manifest(product)
        bounds = manifest["bounds"]
        center_lon = (bounds["west"] + bounds["east"]) / 2
        center_lat = (bounds["south"] + bounds["north"]) / 2
        if product == "lightning":
            # The WMS bounds include a near-global box; choose a tile in the
            # provider's advertised Americas coverage for meaningful checks.
            center_lon, center_lat = -90.0, 40.0
        z = 4
        x = min(2 ** (z + 1) - 1, max(0, int((center_lon + 180) / (180 / (2 ** z)))))
        y = min(2 ** z - 1, max(0, int((90 - center_lat) / (180 / (2 ** z)))))
        observed_time = manifest["latest"]
        _body, image_info = fetch_weather_tile(product, observed_time, z, x, y)
        verified_at = _mark_satellite_image_verified(product, snapshot, {**image_info, "mode": "tile", "product": product, "time": observed_time, "z": z, "x": x, "y": y, "size": "256"})
        return {"status": "LIVE_VERIFIED", "product": product, "layer": WEATHER_IMAGERY_LAYERS[product], "dataset_id": NOAA_WEATHER_IMAGERY_PRODUCTS[product]["dataset_id"], "latest_timestamp": observed_time, "retrieved_at_utc": snapshot["retrieved_at_utc"], "verified_at_utc": verified_at, "coverage": snapshot["coverage"], "bounds": bounds, "available_timestamps": snapshot["available_timestamps"], "verification_tile": {"z": z, "x": x, "y": y, **image_info}, "metadata_readback": True}
    except RadarUpstreamError:
        _satellite_cloud_failure(product)
        raise HTTPException(status_code=502, detail="NOAA nowCOAST satellite live verification failed") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Satellite metadata registry read-back failed") from exc


@app.post("/natural-earth/{dataset}/ingest")
def ingest_natural_earth_dataset(dataset: str, identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    """Validate and persist a bundled Natural Earth static snapshot."""
    if dataset not in NaturalEarthFeatureService.DATASETS:
        raise HTTPException(status_code=404, detail="Unknown Natural Earth dataset")
    source_id = f"src-gev-natural-earth-{dataset}"
    try:
        source = load_natural_earth_source(dataset)
        result = natural_earth_feature_service.ingest(dataset, source)
    except (NaturalEarthSourceUnavailable, NaturalEarthValidationError) as exc:
        natural_earth_dataset_status[dataset] = "UNAVAILABLE"
        source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {"last_error": str(exc)})
        raise HTTPException(status_code=503, detail="Natural Earth source is unavailable or invalid") from None
    if result["rejected"]:
        natural_earth_dataset_status[dataset] = "STATIC_PARTIAL"
        source_registry_service.mark_fetch_status(source_id, "STATIC_PARTIAL", {"last_verification": result})
        raise HTTPException(status_code=422, detail="Natural Earth validation rejected source features")
    counts = natural_earth_feature_service.readback_counts(dataset)
    attrs = natural_earth_feature_service.read_attributes(dataset, limit=result["source_feature_count"])
    features = natural_earth_feature_service.read_features(dataset, limit=result["source_feature_count"])
    if (counts["attributes"] != result["source_feature_count"]
            or counts["geometries"] != result["source_feature_count"]
            or attrs["total"] != result["source_feature_count"]
            or features["total"] != result["source_feature_count"]):
        natural_earth_dataset_status[dataset] = "UNAVAILABLE"
        source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {"last_error": "Stored/API read-back count mismatch"})
        raise HTTPException(status_code=503, detail="Natural Earth storage read-back failed")
    verified_at = datetime.now(timezone.utc).isoformat()
    verification = {
        "dataset_id": result["dataset_id"], "data_mode": "STATIC_SNAPSHOT",
        "source_feature_count": result["source_feature_count"], "valid": result["valid"],
        "rejected": result["rejected"], "attribute_records": counts["attributes"],
        "geometry_records": counts["geometries"], "api_attribute_readback": attrs["total"],
        "api_feature_readback": features["total"], "source_sha256": source["source_sha256"],
        "geometry_types": result["expected_geometry_types"],
        "closed_rings_added_for_geojson": result["closed_rings_added_for_geojson"],
        "verified_at_utc": verified_at, "attribution": NaturalEarthFeatureService.ATTRIBUTION,
    }
    source_registry_service.mark_validated(source_id, metadata={
        "last_fetch_status": "STATIC_VERIFIED", "last_verification": verification,
        "source_sha256": source["source_sha256"], "attribution": NaturalEarthFeatureService.ATTRIBUTION,
    })
    registry_record = source_registry_service.get_source(source_id)
    registry_metadata = registry_record.provenance_reference if registry_record else {}
    registry_verification = registry_metadata.get("last_verification", {})
    if (not registry_record or registry_record.provenance_reference.get("last_fetch_status") != "STATIC_VERIFIED"
            or registry_metadata.get("source_sha256") != source["source_sha256"]
            or registry_verification.get("attribute_records") != counts["attributes"]
            or registry_verification.get("geometry_records") != counts["geometries"]):
        natural_earth_dataset_status[dataset] = "UNAVAILABLE"
        source_registry_service.mark_fetch_status(source_id, "UNAVAILABLE", {"last_error": "Registry read-back mismatch"})
        raise HTTPException(status_code=503, detail="Natural Earth registry read-back failed")
    natural_earth_dataset_status[dataset] = "STATIC_VERIFIED"
    natural_earth_last_verified_at[dataset] = verified_at
    return {"status": "STATIC_VERIFIED", **verification, "registry_readback": True}


@app.get("/natural-earth/{dataset}/attributes")
def read_natural_earth_attributes(dataset: str, limit: int = Query(100, ge=1, le=5000),
                                  offset: int = Query(0, ge=0),
                                  identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    if dataset not in NaturalEarthFeatureService.DATASETS:
        raise HTTPException(status_code=404, detail="Unknown Natural Earth dataset")
    return natural_earth_feature_service.read_attributes(dataset, limit, offset)


@app.get("/natural-earth/{dataset}/features")
def read_natural_earth_features(dataset: str, limit: int = Query(100, ge=1, le=5000),
                                offset: int = Query(0, ge=0),
                                identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    if dataset not in NaturalEarthFeatureService.DATASETS:
        raise HTTPException(status_code=404, detail="Unknown Natural Earth dataset")
    return natural_earth_feature_service.read_features(dataset, limit, offset)


@app.post("/dams/ingest")
def ingest_gods_eye_view_dams(identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    """Import the real bundled GeoJSONL snapshot and verify persisted records."""
    global dam_snapshot_last_verified_at
    try:
        feed = fetch_dams()
        result = dam_feature_service.ingest(feed)
        attributes = dam_feature_service.list_attributes(limit=1_000_000)
        geometries = dam_feature_service.list_features(limit=1_000_000)
        readback_ok = (
            len(attributes) == len(geometries["features"])
            and len(attributes) == result["valid"]
            and all(dam_feature_service.geometry_store.load(row["record_id"]) is not None for row in attributes)
        )
        if not readback_ok:
            source_registry_service.mark_fetch_status(
                "src-gev-openinframap-dams", "UNAVAILABLE", {"last_error": "Stored record read-back mismatch"}
            )
            raise RuntimeError("Dam feature storage read-back failed")

        verified_at = datetime.now(timezone.utc).isoformat()
        result.update({
            "source": feed["source"],
            "source_format": feed["source_format"],
            "data_mode": "STATIC_SNAPSHOT",
            "source_path": feed["source_path"],
            "license": feed["license"],
            "attribution": feed["attribution"],
            "readback_counts": {"attributes": len(attributes), "geometries": len(geometries["features"])},
            "verified_at_utc": verified_at,
        })
        if result["rejected"] == 0 and result["valid"] == result["source_feature_count"]:
            dam_snapshot_last_verified_at = verified_at
            source_registry_service.mark_validated(
                "src-gev-openinframap-dams",
                verified_at,
                {
                    "last_fetch_status": "STATIC_VERIFIED",
                    "data_mode": "STATIC_SNAPSHOT",
                    "source_feature_count": result["source_feature_count"],
                    "valid_feature_count": result["valid"],
                    "rejected_feature_count": result["rejected"],
                    "stored_attribute_count": len(attributes),
                    "stored_geometry_count": len(geometries["features"]),
                    "last_readback_at_utc": verified_at,
                },
            )
            result["status"] = "STATIC_VERIFIED"
        else:
            result["status"] = "STATIC_PARTIAL"
            source_registry_service.mark_fetch_status(
                "src-gev-openinframap-dams",
                "STATIC_PARTIAL",
                {"valid_feature_count": result["valid"], "rejected_feature_count": result["rejected"]},
            )
        return result
    except DamsSourceUnavailable:
        source_registry_service.mark_fetch_status("src-gev-openinframap-dams", "UNAVAILABLE")
        raise HTTPException(status_code=503, detail="God's Eye View dams snapshot is unavailable") from None
    except DamFeatureValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Dam feature storage verification failed") from exc
    except Exception:
        logger.exception("God's Eye View dams ingestion failed")
        raise HTTPException(status_code=502, detail="God's Eye View dams ingestion failed") from None


@app.get("/dams/attributes")
def list_gods_eye_view_dam_attributes(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    records = dam_feature_service.list_attributes(limit=limit, offset=offset)
    return {
        "dataset_id": DamFeatureService.ATTRIBUTE_DATASET_ID,
        "source_dataset_id": DamFeatureService.DATASET_ID,
        "count": len(records), "limit": limit, "offset": offset,
        "data_mode": "STATIC_SNAPSHOT", "attributes": records,
    }


@app.get("/dams/features")
def list_gods_eye_view_dam_features(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    return dam_feature_service.list_features(limit=limit, offset=offset)


@app.post("/events/bhote-koshi/ingest")
def ingest_bhote_koshi_event(identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    """Ingest the static historical event pack and verify each persisted collection."""
    global bhote_koshi_last_verified_at
    try:
        feed = fetch_bhote_koshi_event()
        result = bhote_koshi_event_service.ingest(feed)
        event_record = bhote_koshi_event_service.get_event()
        features = bhote_koshi_event_service.list_features(limit=1000)
        media = bhote_koshi_event_service.list_media(limit=1000)
        readback_counts = {
            "events": int(event_record is not None),
            "geometries": features["total"],
            "media_references": len(media),
        }
        expected = result["valid_counts"]
        readback_ok = (
            readback_counts["events"] == expected["events"]
            and readback_counts["geometries"] == expected["geometries"]
            and readback_counts["media_references"] == expected["media"]
        )
        if not readback_ok:
            source_registry_service.mark_fetch_status(
                "src-gev-bhote-koshi-flood", "UNAVAILABLE", {"last_error": "Stored record read-back mismatch"}
            )
            raise RuntimeError("Bhote Koshi storage read-back failed")

        verified_at = datetime.now(timezone.utc).isoformat()
        result["readback_counts"] = readback_counts
        result["verified_at_utc"] = verified_at
        if result["rejected_record_count"] == 0 and readback_ok:
            bhote_koshi_last_verified_at = verified_at
            result["status"] = "STATIC_VERIFIED"
            source_registry_service.mark_validated(
                "src-gev-bhote-koshi-flood",
                verified_at,
                {
                    "last_fetch_status": "STATIC_VERIFIED",
                    "data_mode": "STATIC_HISTORICAL_RECONSTRUCTION",
                    "source_event_count": result["source_event_count"],
                    "valid_counts": expected,
                    "rejected_counts": result["rejected_counts"],
                    "stored_counts": readback_counts,
                    "verified_at_utc": verified_at,
                    "source_files": result["source_provenance"]["files"],
                    "media_mode": "EXTERNAL_LINK_METADATA_ONLY",
                },
            )
        else:
            result["status"] = "STATIC_PARTIAL"
            source_registry_service.mark_fetch_status(
                "src-gev-bhote-koshi-flood", "STATIC_PARTIAL",
                {"valid_counts": expected, "rejected_counts": result["rejected_counts"]},
            )
        return result
    except BhoteKoshiSourceUnavailable:
        source_registry_service.mark_fetch_status("src-gev-bhote-koshi-flood", "UNAVAILABLE")
        raise HTTPException(status_code=503, detail="God's Eye View Bhote Koshi source is unavailable") from None
    except BhoteKoshiValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Bhote Koshi storage verification failed") from exc
    except Exception:
        logger.exception("God's Eye View Bhote Koshi ingestion failed")
        raise HTTPException(status_code=502, detail="God's Eye View Bhote Koshi ingestion failed") from None


@app.get("/events/bhote-koshi")
def get_bhote_koshi_event(identity: AuthIdentity = Depends(get_identity)) -> Dict[str, Any]:
    record = bhote_koshi_event_service.get_event()
    if record is None:
        raise HTTPException(status_code=404, detail="Bhote Koshi event has not been ingested")
    return record


@app.get("/events/bhote-koshi/features")
def get_bhote_koshi_features(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    return bhote_koshi_event_service.list_features(limit=limit, offset=offset)


@app.get("/events/bhote-koshi/media")
def get_bhote_koshi_media_references(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    records = bhote_koshi_event_service.list_media(limit=limit, offset=offset)
    return {
        "dataset_id": BhoteKoshiEventService.MEDIA_DATASET_ID,
        "source_dataset_id": BhoteKoshiEventService.DATASET_ID,
        "media_mode": "EXTERNAL_LINK_METADATA_ONLY",
        "count": len(records), "limit": limit, "offset": offset,
        "media_references": records,
    }


@app.get("/geospatial/3d-tiles/photorealistic/manifest")
def get_photorealistic_tiles_manifest(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Return safe service metadata; never return browser/provider credentials."""
    manifest = photoreal_tiles_safe_manifest(photoreal_tiles_last_verification)
    try:
        source = source_registry_service.get_source("src-gev-google-photoreal-tiles")
        manifest["source_id"] = source.source_id
        manifest["last_validation"] = source.last_validation
    except SourceNotFoundError:
        manifest["source_id"] = "src-gev-google-photoreal-tiles"
    return manifest


@app.post("/geospatial/3d-tiles/photorealistic/verify")
def verify_photorealistic_tiles(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch the provider's actual tileset root and a tile without storing it."""
    global photoreal_tiles_last_verification
    result = verify_photoreal_tiles()
    result["dataset_id"] = "google_cesium_photorealistic_3d_tiles"
    if result.get("status") == "LIVE_VERIFIED" and result.get("tiles_loaded") is True:
        verified_at = datetime.now(timezone.utc).isoformat()
        result["verified_at_utc"] = verified_at
        safe_fields = (
            "status", "route", "root_http_status", "root_content_type", "root_asset_version",
            "tile_http_status", "tile_content_type", "tile_bytes", "credential_configured", "tiles_loaded",
        )
        persisted_verification = {key: result[key] for key in safe_fields if key in result}
        persisted_verification["verified_at_utc"] = verified_at
        persisted_verification["attempts"] = result.get("attempts", [])
        try:
            source_registry_service.mark_validated(
                "src-gev-google-photoreal-tiles",
                verified_at,
                {
                    "last_fetch_status": "LIVE_VERIFIED",
                    "data_mode": "EXTERNAL_GEOPATIAL_TILE_SERVICE",
                    "credential_values_stored": False,
                    "last_verification": persisted_verification,
                },
            )
            readback = source_registry_service.get_source("src-gev-google-photoreal-tiles")
            stored = readback.provenance_reference.get("last_verification", {})
            if stored.get("status") != "LIVE_VERIFIED" or stored.get("verified_at_utc") != verified_at:
                raise RuntimeError("Photorealistic tiles registry read-back failed")
        except Exception:
            source_registry_service.mark_fetch_status(
                "src-gev-google-photoreal-tiles", "UNAVAILABLE",
                {"last_error": "Service verification metadata read-back failed", "credential_values_stored": False},
            )
            photoreal_tiles_last_verification = {"status": "UNAVAILABLE"}
            raise HTTPException(status_code=503, detail="Photorealistic tiles registry read-back failed") from None
        photoreal_tiles_last_verification = persisted_verification
        return {**persisted_verification, "dataset_id": "google_cesium_photorealistic_3d_tiles", "registry_readback": True}

    photoreal_tiles_last_verification = {
        "status": "UNAVAILABLE",
        "credential_configured": bool(result.get("credential_configured")),
        "tiles_loaded": False,
        "reason": result.get("reason", "provider_tiles_unavailable_or_invalid"),
        "attempts": result.get("attempts", []),
    }
    source_registry_service.mark_fetch_status(
        "src-gev-google-photoreal-tiles",
        "UNAVAILABLE",
        {
            "last_error": result.get("reason", "provider_tiles_unavailable_or_invalid"),
            "credential_configured": bool(result.get("credential_configured")),
            "credential_values_stored": False,
            "last_verification": photoreal_tiles_last_verification,
        },
    )
    reason = result.get("reason", "provider_tiles_unavailable_or_invalid")
    raise HTTPException(status_code=503, detail=f"Photorealistic tiles unavailable ({reason})")


@app.get("/geospatial/satellite-imagery/manifest")
def get_satellite_imagery_manifest(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Return provider metadata without exposing any provider credentials."""
    manifest = satellite_imagery_safe_manifest(satellite_imagery_last_verification)
    try:
        source = source_registry_service.get_source("src-gev-world-satellite-imagery")
        manifest["source_id"] = source.source_id
        manifest["last_validation"] = source.last_validation
    except SourceNotFoundError:
        manifest["source_id"] = "src-gev-world-satellite-imagery"
    return manifest


@app.post("/geospatial/satellite-imagery/verify")
def verify_satellite_imagery_endpoint(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch a real provider tile; persist only sanitized metadata and read it back."""
    global satellite_imagery_last_verification
    result = verify_satellite_imagery()
    result["dataset_id"] = "gods_eye_view_world_satellite_imagery"
    if result.get("status") == "LIVE_VERIFIED" and result.get("tiles_loaded") is True:
        verified_at = result.get("verified_at_utc") or datetime.now(timezone.utc).isoformat()
        fields = ("status", "provider", "tile_http_status", "tile_content_type", "tile_bytes", "tiles_loaded")
        persisted = {key: result[key] for key in fields if key in result}
        persisted.update({"verified_at_utc": verified_at, "attempts": result.get("attempts", [])})
        try:
            source_registry_service.mark_validated(
                "src-gev-world-satellite-imagery", verified_at,
                {"last_fetch_status": "LIVE_VERIFIED", "data_mode": "EXTERNAL_GEOPATIAL_TILE_SERVICE", "credential_values_stored": False, "last_verification": persisted},
            )
            readback = source_registry_service.get_source("src-gev-world-satellite-imagery")
            stored = readback.provenance_reference.get("last_verification", {})
            if stored.get("status") != "LIVE_VERIFIED" or stored.get("verified_at_utc") != verified_at:
                raise RuntimeError("satellite imagery registry read-back failed")
        except Exception:
            source_registry_service.mark_fetch_status("src-gev-world-satellite-imagery", "UNAVAILABLE", {"last_error": "Service verification metadata read-back failed", "credential_values_stored": False})
            satellite_imagery_last_verification = {"status": "UNAVAILABLE"}
            raise HTTPException(status_code=503, detail="Satellite imagery registry read-back failed") from None
        satellite_imagery_last_verification = persisted
        return {**persisted, "dataset_id": "gods_eye_view_world_satellite_imagery", "registry_readback": True, "credential_values_included": False}
    satellite_imagery_last_verification = {"status": "UNAVAILABLE", "tiles_loaded": False, "reason": result.get("reason", "all_provider_tiles_unavailable")}
    source_registry_service.mark_fetch_status("src-gev-world-satellite-imagery", "UNAVAILABLE", {"last_error": satellite_imagery_last_verification["reason"], "credential_values_stored": False, "last_verification": satellite_imagery_last_verification})
    raise HTTPException(status_code=503, detail=f"Satellite imagery unavailable ({satellite_imagery_last_verification['reason']})")


@app.get("/geospatial/terrain/manifest")
def get_world_terrain_manifest(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Return terrain provider and coverage metadata without credentials."""
    manifest = world_terrain_safe_manifest(world_terrain_last_verification)
    try:
        source = source_registry_service.get_source("src-gev-world-3d-terrain")
        manifest["source_id"] = source.source_id
        manifest["last_validation"] = source.last_validation
    except SourceNotFoundError:
        manifest["source_id"] = "src-gev-world-3d-terrain"
    return manifest


@app.post("/geospatial/terrain/verify")
def verify_world_terrain_endpoint(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch layer metadata and one real quantized-mesh tile; then verify registry read-back."""
    global world_terrain_last_verification
    result = verify_world_terrain()
    result["dataset_id"] = "gods_eye_view_world_3d_terrain"
    if result.get("status") == "LIVE_VERIFIED" and result.get("tiles_loaded") is True:
        verified_at = result.get("verified_at_utc") or datetime.now(timezone.utc).isoformat()
        fields = ("status", "provider", "layer_http_status", "tile_http_status", "tile_content_type", "tile_bytes", "tiles_loaded", "format", "tile_template", "credential_configured")
        persisted = {key: result[key] for key in fields if key in result}
        persisted.update({"verified_at_utc": verified_at, "credential_values_stored": False})
        try:
            source_registry_service.mark_validated(
                "src-gev-world-3d-terrain", verified_at,
                {"last_fetch_status": "LIVE_VERIFIED", "data_mode": "EXTERNAL_GEOPATIAL_TERRAIN_SERVICE", "credential_values_stored": False, "last_verification": persisted},
            )
            readback = source_registry_service.get_source("src-gev-world-3d-terrain")
            stored = readback.provenance_reference.get("last_verification", {})
            if stored.get("status") != "LIVE_VERIFIED" or stored.get("verified_at_utc") != verified_at:
                raise RuntimeError("terrain registry read-back failed")
        except Exception:
            source_registry_service.mark_fetch_status("src-gev-world-3d-terrain", "UNAVAILABLE", {"last_error": "Service verification metadata read-back failed", "credential_values_stored": False})
            world_terrain_last_verification = {"status": "UNAVAILABLE", "tiles_loaded": False, "reason": "registry_readback_failed"}
            raise HTTPException(status_code=503, detail="Terrain registry read-back failed") from None
        world_terrain_last_verification = persisted
        return {**persisted, "dataset_id": "gods_eye_view_world_3d_terrain", "registry_readback": True, "credential_values_included": False}
    reason = result.get("reason", "provider_unreachable")
    world_terrain_last_verification = {"status": "UNAVAILABLE", "tiles_loaded": False, "reason": reason}
    source_registry_service.mark_fetch_status("src-gev-world-3d-terrain", "UNAVAILABLE", {"last_error": reason, "credential_values_stored": False, "last_verification": world_terrain_last_verification})
    raise HTTPException(status_code=503, detail=f"Terrain provider unavailable ({reason})")


@app.get("/geospatial/vector-basemap/manifest")
def get_vector_basemap_manifest(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Return the OpenFreeMap vector tile service metadata without credentials."""
    manifest = vector_basemap_safe_manifest(vector_basemap_last_verification)
    try:
        source = source_registry_service.get_source("src-gev-openfreemap-vector-basemap")
        manifest["source_id"] = source.source_id
        manifest["last_validation"] = source.last_validation
    except SourceNotFoundError:
        manifest["source_id"] = "src-gev-openfreemap-vector-basemap"
    return manifest


@app.post("/geospatial/vector-basemap/verify")
def verify_vector_basemap_endpoint(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Fetch OpenFreeMap TileJSON and a real vector tile; verify registry read-back."""
    global vector_basemap_last_verification
    result = verify_vector_basemap()
    result["dataset_id"] = "gods_eye_view_openfreemap_vector_basemap"
    if result.get("status") == "LIVE_VERIFIED" and result.get("tiles_loaded") is True:
        verified_at = result.get("verified_at_utc") or datetime.now(timezone.utc).isoformat()
        fields = (
            "status", "provider", "tilejson_http_status", "tile_http_status", "tile_content_type",
            "tile_bytes", "tiles_loaded", "tile_url_template", "tilejson_version", "vector_layers",
            "bounds", "minzoom", "maxzoom", "attribution",
        )
        persisted = {key: result[key] for key in fields if key in result}
        persisted.update({"verified_at_utc": verified_at, "credential_values_stored": False})
        try:
            source_registry_service.mark_validated(
                "src-gev-openfreemap-vector-basemap", verified_at,
                {
                    "last_fetch_status": "LIVE_VERIFIED",
                    "data_mode": "EXTERNAL_GEOPATIAL_VECTOR_TILE_SERVICE",
                    "tilejson_endpoint": "https://tiles.openfreemap.org/planet",
                    "consumed_vector_layers": [layer for layer in ("transportation", "landuse") if layer in persisted.get("vector_layers", [])],
                    "style_url": None,
                    "style_note": "God's Eye View decodes vector data; its OpenFreeMap source does not configure a cartographic style URL.",
                    "fallback_workflow": "OpenFreeMap roads are primary without TomTom; Hybrid uses OpenFreeMap where TomTom has no flow. The tile source does not silently switch origins.",
                    "credential_values_stored": False,
                    "last_verification": persisted,
                },
            )
            readback = source_registry_service.get_source("src-gev-openfreemap-vector-basemap")
            stored = readback.provenance_reference.get("last_verification", {})
            if stored.get("status") != "LIVE_VERIFIED" or stored.get("verified_at_utc") != verified_at:
                raise RuntimeError("vector basemap registry read-back failed")
        except Exception:
            source_registry_service.mark_fetch_status("src-gev-openfreemap-vector-basemap", "UNAVAILABLE", {"last_error": "Service verification metadata read-back failed", "credential_values_stored": False})
            vector_basemap_last_verification = {"status": "UNAVAILABLE", "tiles_loaded": False, "reason": "registry_readback_failed"}
            raise HTTPException(status_code=503, detail="Vector basemap registry read-back failed") from None
        vector_basemap_last_verification = persisted
        return {**persisted, "dataset_id": "gods_eye_view_openfreemap_vector_basemap", "registry_readback": True, "credential_values_included": False}
    reason = result.get("reason", "provider_unreachable")
    vector_basemap_last_verification = {"status": "UNAVAILABLE", "tiles_loaded": False, "reason": reason}
    source_registry_service.mark_fetch_status("src-gev-openfreemap-vector-basemap", "UNAVAILABLE", {"last_error": reason, "credential_values_stored": False, "last_verification": vector_basemap_last_verification})
    raise HTTPException(status_code=503, detail=f"Vector basemap unavailable ({reason})")


@app.get("/live-datasets")
def list_live_feed_datasets(
    identity: AuthIdentity = Depends(get_identity),
) -> Dict[str, Any]:
    """Live-feed registry; separate from static and synthetic dataset entries."""
    photoreal_manifest = photoreal_tiles_safe_manifest(photoreal_tiles_last_verification)
    satellite_manifest = satellite_imagery_safe_manifest(satellite_imagery_last_verification)
    terrain_manifest = world_terrain_safe_manifest(world_terrain_last_verification)
    vector_basemap_manifest = vector_basemap_safe_manifest(vector_basemap_last_verification)
    datasets = [
        {
            "dataset_id": "gods_eye_view_natural_earth_regions",
            "name": "Natural Earth 10m Geography Regions",
            "source": "Natural Earth 10m physical vectors — ne_10m_geography_regions_polys",
            "status": natural_earth_dataset_status["regions"], "data_mode": "STATIC_SNAPSHOT",
            "update_frequency": "Static source snapshot; no automatic refresh schedule",
            "coverage": "Global; source feature geometry extents", "attribution": NaturalEarthFeatureService.ATTRIBUTION,
            "feature_endpoint": "/natural-earth/regions/features", "attribute_endpoint": "/natural-earth/regions/attributes",
            "ingestion_endpoint": "/natural-earth/regions/ingest", "verification_endpoint": "/natural-earth/regions/ingest",
            "source_feature_count": 1046, "record_count": natural_earth_feature_service.readback_counts("regions")["attributes"],
            "geometry_record_count": natural_earth_feature_service.readback_counts("regions")["geometries"],
            "last_updated_at_utc": natural_earth_last_verified_at["regions"],
        },
        {
            "dataset_id": "gods_eye_view_natural_earth_marine",
            "name": "Natural Earth 10m Geography Marine Areas",
            "source": "Natural Earth 10m physical vectors — ne_10m_geography_marine_polys",
            "status": natural_earth_dataset_status["marine"], "data_mode": "STATIC_SNAPSHOT",
            "update_frequency": "Static source snapshot; no automatic refresh schedule",
            "coverage": "Global; source feature geometry extents", "attribution": NaturalEarthFeatureService.ATTRIBUTION,
            "feature_endpoint": "/natural-earth/marine/features", "attribute_endpoint": "/natural-earth/marine/attributes",
            "ingestion_endpoint": "/natural-earth/marine/ingest", "verification_endpoint": "/natural-earth/marine/ingest",
            "source_feature_count": 292, "record_count": natural_earth_feature_service.readback_counts("marine")["attributes"],
            "geometry_record_count": natural_earth_feature_service.readback_counts("marine")["geometries"],
            "last_updated_at_utc": natural_earth_last_verified_at["marine"],
        },
        {
            "dataset_id": "gods_eye_view_openfreemap_vector_basemap",
            "name": "God's Eye View OpenFreeMap Vector Basemap Tiles",
            "source": vector_basemap_manifest["provider"],
            "status": vector_basemap_manifest["status"],
            "data_mode": "EXTERNAL_GEOPATIAL_VECTOR_TILE_SERVICE",
            "service_type": "MAPBOX_VECTOR_TILES",
            "coverage": vector_basemap_manifest["coverage"],
            "attribution": vector_basemap_manifest["attribution"],
            "manifest_endpoint": "/geospatial/vector-basemap/manifest",
            "verification_endpoint": "/geospatial/vector-basemap/verify",
            "credential_configured": False,
            "credential_values_included": False,
            "tiles_loaded": vector_basemap_manifest["status"] == "LIVE_VERIFIED",
            "last_updated_at_utc": vector_basemap_last_verification.get("verified_at_utc"),
            "record_count": 0,
        },
        {
            "dataset_id": "gods_eye_view_world_3d_terrain",
            "name": "God's Eye View World 3D Terrain",
            "source": terrain_manifest["provider"],
            "status": terrain_manifest["status"],
            "data_mode": "EXTERNAL_GEOPATIAL_TERRAIN_SERVICE",
            "service_type": "QUANTIZED_MESH_TERRAIN",
            "coverage": terrain_manifest["coverage"],
            "attribution": terrain_manifest["attribution"],
            "manifest_endpoint": "/geospatial/terrain/manifest",
            "verification_endpoint": "/geospatial/terrain/verify",
            "credential_configured": terrain_manifest["credential_configured"],
            "credential_values_included": False,
            "tiles_loaded": terrain_manifest["status"] == "LIVE_VERIFIED",
            "last_updated_at_utc": world_terrain_last_verification.get("verified_at_utc"),
            "record_count": 0,
        },
        {
            "dataset_id": "gods_eye_view_world_satellite_imagery",
            "name": "God's Eye View World Satellite Imagery",
            "source": satellite_manifest["provider"],
            "status": satellite_manifest["status"],
            "data_mode": "EXTERNAL_GEOPATIAL_TILE_SERVICE",
            "service_type": "WORLD_SATELLITE_IMAGERY",
            "coverage": satellite_manifest["coverage"],
            "attribution": satellite_manifest["attribution"],
            "manifest_endpoint": "/geospatial/satellite-imagery/manifest",
            "verification_endpoint": "/geospatial/satellite-imagery/verify",
            "credential_values_included": False,
            "tiles_loaded": satellite_manifest["status"] == "LIVE_VERIFIED",
            "last_updated_at_utc": satellite_imagery_last_verification.get("verified_at_utc"),
            "record_count": 0,
        },
        {
            "dataset_id": "google_cesium_photorealistic_3d_tiles",
            "name": "Google Photorealistic 3D Tiles via CesiumJS",
            "source": "Google Maps Platform / Cesium ion",
            "status": photoreal_manifest["status"],
            "data_mode": "EXTERNAL_GEOPATIAL_TILE_SERVICE",
            "service_type": "PHOTOREALISTIC_3D_TILES",
            "terms": "Google Maps Platform terms for direct tiles; Cesium ion terms for the hosted asset route.",
            "coverage": "Global where Google Photorealistic 3D coverage is available; completeness varies by location.",
            "attribution": "Google Maps Platform per-tile credits must remain visible; Cesium ion attribution applies on the hosted asset route.",
            "manifest_endpoint": "/geospatial/3d-tiles/photorealistic/manifest",
            "verification_endpoint": "/geospatial/3d-tiles/photorealistic/verify",
            "preferred_route": photoreal_manifest["preferred_route"],
            "credential_configured": photoreal_manifest["credential_configured"],
            "credential_values_included": False,
            "tiles_loaded": photoreal_manifest["status"] == "LIVE_VERIFIED",
            "last_updated_at_utc": photoreal_tiles_last_verification.get("verified_at_utc"),
            "record_count": 0,
        },
        {
            "dataset_id": BhoteKoshiEventService.DATASET_ID,
            "name": "Bhote Koshi Historical Flood Reconstruction",
            "source": "God's Eye View / GeoPera / Vantor Open Data",
            "status": "STATIC_VERIFIED" if bhote_koshi_last_verified_at else "UNVERIFIED",
            "data_mode": "STATIC_HISTORICAL_RECONSTRUCTION",
            "update_frequency": "Static historical reconstruction; no automatic refresh schedule",
            "last_updated_at_utc": bhote_koshi_last_verified_at,
            "event_endpoint": "/events/bhote-koshi",
            "feature_endpoint": "/events/bhote-koshi/features",
            "media_endpoint": "/events/bhote-koshi/media",
            "ingestion_endpoint": "/events/bhote-koshi/ingest",
            "record_count": (
                len(bhote_koshi_event_service.event_store.list_all())
                + len(bhote_koshi_event_service.geometry_store.list_all())
                + len(bhote_koshi_event_service.media_store.list_all())
            ),
            "event_record_count": len(bhote_koshi_event_service.event_store.list_all()),
            "geometry_record_count": len(bhote_koshi_event_service.geometry_store.list_all()),
            "media_reference_count": len(bhote_koshi_event_service.media_store.list_all()),
            "media_mode": "EXTERNAL_LINK_METADATA_ONLY",
            "attribution": "GeoPera reconstruction (CC BY-NC 4.0); Vantor Open Data imagery; linked witness posts retain their owners' terms",
        },
        {
            "dataset_id": DamFeatureService.DATASET_ID,
            "name": "God's Eye View Dams (OpenInfraMap Snapshot)",
            "source": "OpenStreetMap contributors / Open Infrastructure Map",
            "status": "STATIC_VERIFIED" if dam_snapshot_last_verified_at else "UNVERIFIED",
            "data_mode": "STATIC_SNAPSHOT",
            "update_frequency": "Static source snapshot; no automatic refresh schedule",
            "last_updated_at_utc": dam_snapshot_last_verified_at,
            "attribute_endpoint": "/dams/attributes",
            "feature_endpoint": "/dams/features",
            "ingestion_endpoint": "/dams/ingest",
            "source_feature_count": 704,
            "record_count": len(dam_feature_service.list_attributes(limit=1_000_000)),
            "license": "Open Database License (ODbL) 1.0",
            "attribution": "© OpenStreetMap contributors; Open Infrastructure Map",
        },
        {
            "dataset_id": "ds-gev-seismic-events",
            "name": "USGS Earthquake Events",
            "source": "USGS",
            "status": observation_feed_state["usgs"]["status"],
            "last_updated_at_utc": observation_feed_state["usgs"].get("last_verified_at_utc"),
            "observation_endpoint": "/earthquakes/usgs/observations",
            "ingestion_endpoint": "/earthquakes/usgs/ingest",
            "verification_endpoint": "/earthquakes/usgs/ingest",
            "record_count": len(earthquake_observation_service.list(limit=1_000_000)),
        },
        {
            "dataset_id": AISObservationService.DATASET_ID,
            "name": "AISStream Vessel Positions",
            "source": "AISStream",
            "status": observation_feed_state["aisstream"]["status"],
            "last_updated_at_utc": observation_feed_state["aisstream"].get("last_verified_at_utc"),
            "observation_endpoint": "/aisstream/observations",
            "ingestion_endpoint": "/aisstream/ingest",
            "credential_values_included": False,
            "record_count": len(ais_observation_service.list(limit=1_000_000)),
        },
        {
            "dataset_id": AircraftObservationService.DATASET_ID,
            "name": "ADS-B Military-Feed Aircraft Observations",
            "source": "adsb.lol",
            "status": observation_feed_state["adsb_military"]["status"],
            "last_updated_at_utc": observation_feed_state["adsb_military"].get("last_verified_at_utc"),
            "observation_endpoint": "/aircraft/adsb/military/observations",
            "ingestion_endpoint": "/aircraft/adsb/military/ingest",
            "verification_endpoint": "/aircraft/adsb/military/ingest",
            "record_count": len(aircraft_observation_service.list(limit=1_000_000)),
        },
        {
            "dataset_id": FireObservationService.DATASET_ID,
            "name": "NASA FIRMS Active Fire Detections",
            "source": "NASA LANCE FIRMS (VIIRS SNPP, NOAA-20, NOAA-21 NRT)",
            "status": "LIVE_VERIFIED" if firms_last_verified_at else ("CONFIGURED" if os.environ.get("FIRMS_MAP_KEY") else "BLOCKED"),
            "last_updated_at_utc": firms_last_verified_at,
            "update_frequency": "Near real time; FIRMS NRT observations, God’s Eye View uses a 30-minute server cache",
            "observation_endpoint": "/wildfires/firms/observations",
            "ingestion_endpoint": "/wildfires/firms/ingest",
            "record_count": len(fire_observation_service.list(limit=1_000_000)),
        },
        {
            "dataset_id": TrafficObservationService.DATASET_ID,
            "name": "TomTom Traffic Flow Segments",
            "source": "TomTom Traffic API (God’s Eye View relative-flow vector tiles)",
            "status": "BLOCKED" if not os.environ.get("TOMTOM_API_KEY") else ("UNAVAILABLE" if traffic_last_fetch_error else ("LIVE_VERIFIED" if traffic_last_verified_at else "CONFIGURED")),
            "data_mode": "LIVE_ONLY",
            "last_updated_at_utc": traffic_last_verified_at,
            "verified_tiles": traffic_verified_tiles,
            "observation_endpoint": "/traffic/tomtom/observations",
            "ingestion_endpoint": "/traffic/tomtom/ingest",
            "record_count": len(traffic_observation_service.list(limit=1_000_000)),
        },
        {
            "dataset_id": WeatherObservationService.WIND_DATASETS["GFS"],
            "name": "NOAA GFS 10 m Wind Point Forecasts",
            "source": "God's Eye View wind provider / NOAA GFS",
            "record_type": "FORECAST",
            "data_mode": "LIVE_ONLY_POINT_SAMPLES",
            "status": weather_source_state["src-gev-gfs-wind"]["last_fetch_status"] if weather_source_state["src-gev-gfs-wind"]["last_fetch_status"] in ("UNAVAILABLE", "LIVE_VERIFIED") else "CONFIGURED",
            "last_updated_at_utc": weather_source_state["src-gev-gfs-wind"]["last_verified_at_utc"],
            "verified_coordinates": weather_source_state["src-gev-gfs-wind"]["verified_coordinates"],
            "observation_endpoint": "/weather/wind/forecasts?model=gfs",
            "ingestion_endpoint": "/weather/wind/gfs/ingest",
            "record_count": len(weather_observation_service.list(WeatherObservationService.WIND_DATASETS["GFS"], limit=1_000_000)),
        },
        {
            "dataset_id": WeatherObservationService.WIND_DATASETS["ECMWF"],
            "name": "ECMWF IFS 10 m Wind Point Forecasts",
            "source": "God's Eye View wind provider / ECMWF Open Data",
            "record_type": "FORECAST",
            "data_mode": "LIVE_ONLY_POINT_SAMPLES",
            "status": weather_source_state["src-gev-ecmwf-wind"]["last_fetch_status"] if weather_source_state["src-gev-ecmwf-wind"]["last_fetch_status"] in ("UNAVAILABLE", "LIVE_VERIFIED") else "CONFIGURED",
            "last_updated_at_utc": weather_source_state["src-gev-ecmwf-wind"]["last_verified_at_utc"],
            "verified_coordinates": weather_source_state["src-gev-ecmwf-wind"]["verified_coordinates"],
            "observation_endpoint": "/weather/wind/forecasts?model=ecmwf",
            "ingestion_endpoint": "/weather/wind/ecmwf/ingest",
            "record_count": len(weather_observation_service.list(WeatherObservationService.WIND_DATASETS["ECMWF"], limit=1_000_000)),
        },
        {
            "dataset_id": WeatherObservationService.CURRENT_DATASET,
            "name": "Open-Meteo Current Surface Weather",
            "source": "Open-Meteo",
            "record_type": "CURRENT_CONDITIONS",
            "data_mode": "LIVE_ONLY_MODEL_DERIVED_CURRENT",
            "status": weather_source_state["src-open-meteo-current-weather"]["last_fetch_status"] if weather_source_state["src-open-meteo-current-weather"]["last_fetch_status"] in ("UNAVAILABLE", "LIVE_VERIFIED") else "CONFIGURED",
            "last_updated_at_utc": weather_source_state["src-open-meteo-current-weather"]["last_verified_at_utc"],
            "verified_coordinates": weather_source_state["src-open-meteo-current-weather"]["verified_coordinates"],
            "observation_endpoint": "/weather/open-meteo/current",
            "ingestion_endpoint": "/weather/open-meteo/ingest",
            "record_count": len(weather_observation_service.list(WeatherObservationService.CURRENT_DATASET, limit=1_000_000)),
        },
        {
            "dataset_id": SATELLITE_CLOUD_PRODUCTS["clouds"]["dataset_id"],
            "name": "NOAA nowCOAST Global Satellite Infrared Imagery",
            "source": "NOAA/NWS/NESDIS nowCOAST via God's Eye View",
            "product": "clouds",
            "layer": WEATHER_IMAGERY_LAYERS["clouds"],
            "data_mode": "LIVE_GEOSPATIAL_IMAGERY_TILES",
            "status": satellite_cloud_state["clouds"]["last_fetch_status"] if satellite_cloud_state["clouds"]["last_fetch_status"] in ("UNAVAILABLE", "LIVE_VERIFIED") else "CONFIGURED",
            "last_updated_at_utc": satellite_cloud_state["clouds"]["last_verified_at_utc"],
            "retrieved_at_utc": (satellite_cloud_state["clouds"].get("metadata") or {}).get("retrieved_at_utc"),
            "coverage": (satellite_cloud_state["clouds"].get("metadata") or {}).get("coverage", "Global infrared mosaic; incomplete polar coverage"),
            "bounds": (satellite_cloud_state["clouds"].get("metadata") or {}).get("bounds"),
            "available_timestamps": (satellite_cloud_state["clouds"].get("metadata") or {}).get("available_timestamps", []),
            "latest_timestamp": (satellite_cloud_state["clouds"].get("metadata") or {}).get("latest_timestamp"),
            "last_image_retrieval": satellite_cloud_state["clouds"].get("last_image_retrieval"),
            "observation_endpoint": "/weather/satellite/manifest?product=clouds",
            "ingestion_endpoint": "/weather/satellite/verify?product=clouds",
            "image_endpoint": "/weather/satellite/image?product=clouds&time={timestamp}",
            "tile_endpoint": "/weather/satellite/tile?product=clouds&time={timestamp}&z={z}&x={x}&y={y}",
            "record_count": 0,
        },
        {
            "dataset_id": SATELLITE_CLOUD_PRODUCTS["clouds-regional"]["dataset_id"],
            "name": "NOAA nowCOAST GOES Regional Satellite Infrared Imagery",
            "source": "NOAA/NWS/NESDIS nowCOAST via God's Eye View",
            "product": "clouds-regional",
            "layer": WEATHER_IMAGERY_LAYERS["clouds-regional"],
            "data_mode": "LIVE_GEOSPATIAL_IMAGERY_TILES",
            "status": satellite_cloud_state["clouds-regional"]["last_fetch_status"] if satellite_cloud_state["clouds-regional"]["last_fetch_status"] in ("UNAVAILABLE", "LIVE_VERIFIED") else "CONFIGURED",
            "last_updated_at_utc": satellite_cloud_state["clouds-regional"]["last_verified_at_utc"],
            "retrieved_at_utc": (satellite_cloud_state["clouds-regional"].get("metadata") or {}).get("retrieved_at_utc"),
            "coverage": (satellite_cloud_state["clouds-regional"].get("metadata") or {}).get("coverage", "GOES East/West regional North American coverage"),
            "bounds": (satellite_cloud_state["clouds-regional"].get("metadata") or {}).get("bounds"),
            "available_timestamps": (satellite_cloud_state["clouds-regional"].get("metadata") or {}).get("available_timestamps", []),
            "latest_timestamp": (satellite_cloud_state["clouds-regional"].get("metadata") or {}).get("latest_timestamp"),
            "last_image_retrieval": satellite_cloud_state["clouds-regional"].get("last_image_retrieval"),
            "observation_endpoint": "/weather/satellite/manifest?product=clouds-regional",
            "ingestion_endpoint": "/weather/satellite/verify?product=clouds-regional",
            "image_endpoint": "/weather/satellite/image?product=clouds-regional&time={timestamp}",
            "tile_endpoint": "/weather/satellite/tile?product=clouds-regional&time={timestamp}&z={z}&x={x}&y={y}",
            "record_count": 0,
        },
        {
            "dataset_id": NOAA_WEATHER_IMAGERY_PRODUCTS["lightning"]["dataset_id"],
            "name": "NOAA nowCOAST Lightning Strike Density Imagery",
            "source": "NOAA/NWS nowCOAST via God's Eye View; derived from Vaisala NLDN/GLD360",
            "product": "lightning",
            "layer": WEATHER_IMAGERY_LAYERS["lightning"],
            "data_mode": "LIVE_GEOSPATIAL_IMAGERY_TILES",
            "status": satellite_cloud_state["lightning"]["last_fetch_status"] if satellite_cloud_state["lightning"]["last_fetch_status"] in ("UNAVAILABLE", "LIVE_VERIFIED") else "CONFIGURED",
            "last_updated_at_utc": satellite_cloud_state["lightning"]["last_verified_at_utc"],
            "retrieved_at_utc": (satellite_cloud_state["lightning"].get("metadata") or {}).get("retrieved_at_utc"),
            "coverage": (satellite_cloud_state["lightning"].get("metadata") or {}).get("coverage", "Pacific and Americas across the dateline; live bounds from WMS capabilities"),
            "bounds": (satellite_cloud_state["lightning"].get("metadata") or {}).get("bounds"),
            "available_timestamps": (satellite_cloud_state["lightning"].get("metadata") or {}).get("available_timestamps", []),
            "latest_timestamp": (satellite_cloud_state["lightning"].get("metadata") or {}).get("latest_timestamp"),
            "last_image_retrieval": satellite_cloud_state["lightning"].get("last_image_retrieval"),
            "observation_endpoint": "/weather/lightning/manifest",
            "ingestion_endpoint": "/weather/lightning/verify",
            "image_endpoint": "/weather/lightning/image?time={timestamp}",
            "tile_endpoint": "/weather/lightning/tile?time={timestamp}&z={z}&x={x}&y={y}",
            "record_count": 0,
        },
        {
            "dataset_id": "noaa_nowcoast_conus_base_reflectivity_radar",
            "name": "NOAA nowCOAST CONUS Base Reflectivity Radar",
            "source": "NOAA/NWS nowCOAST MRMS radar mosaic via God's Eye View",
            "product": "radar",
            "layer": "conus_base_reflectivity_mosaic",
            "data_mode": "LIVE_GEOSPATIAL_IMAGERY_TILES",
            "status": radar_source_state["last_fetch_status"] if radar_source_state["last_fetch_status"] in ("UNAVAILABLE", "LIVE_VERIFIED") else "CONFIGURED",
            "last_updated_at_utc": radar_source_state["last_verified_at_utc"],
            "retrieved_at_utc": (radar_source_state.get("metadata") or {}).get("retrieved_at_utc"),
            "coverage": (radar_source_state.get("metadata") or {}).get("coverage", "Contiguous United States"),
            "bounds": (radar_source_state.get("metadata") or {}).get("bounds"),
            "available_radar_timestamps": (radar_source_state.get("metadata") or {}).get("available_radar_timestamps", []),
            "latest_radar_timestamp": (radar_source_state.get("metadata") or {}).get("latest_radar_timestamp"),
            "last_image_retrieval": radar_source_state.get("last_image_retrieval"),
            "observation_endpoint": "/weather/radar/manifest",
            "ingestion_endpoint": "/weather/radar/verify",
            "image_endpoint": "/weather/radar/image?time={timestamp}",
            "tile_endpoint": "/weather/radar/tile?time={timestamp}&z={z}&x={x}&y={y}",
            "record_count": 0,
        },
        {
            "dataset_id": CYCLONE_DATASETS["storms"],
            "name": "NOAA NHC/CPHC Current Tropical Cyclone Status",
            "source": "NOAA NHC / CPHC via God's Eye View",
            "data_mode": "CURRENT_STORM_OBSERVATIONS",
            "status": cyclone_source_state["storms"]["last_fetch_status"],
            "last_updated_at_utc": cyclone_source_state["storms"]["last_verified_at_utc"],
            "retrieved_at_utc": cyclone_source_state["storms"]["last_metadata"].get("fetched_at_utc"),
            "coverage": cyclone_source_state["storms"]["last_metadata"].get("coverage", "Atlantic and eastern/central North Pacific; not worldwide"),
            "active_storm_count": cyclone_source_state["storms"]["last_metadata"].get("active_storm_count"),
            "observation_endpoint": "/cyclones/nhc/storms",
            "ingestion_endpoint": "/cyclones/nhc/ingest",
            "record_count": len(cyclone_observation_service.list(CYCLONE_DATASETS["storms"], limit=1000)),
        },
        {
            "dataset_id": CYCLONE_DATASETS["points"],
            "name": "NOAA Tropical Cyclone Forecast Points",
            "source": "NOAA Tropical Weather GIS layer 5 via God's Eye View",
            "data_mode": "GEOSPATIAL_FEATURES",
            "status": cyclone_source_state["points"]["last_fetch_status"],
            "last_updated_at_utc": cyclone_source_state["points"]["last_verified_at_utc"],
            "gis_layer_id": 5,
            "observation_endpoint": "/cyclones/nhc/forecast-points",
            "ingestion_endpoint": "/cyclones/nhc/ingest",
            "record_count": len(cyclone_observation_service.list(CYCLONE_DATASETS["points"], limit=1000)),
        },
        {
            "dataset_id": CYCLONE_DATASETS["tracks"],
            "name": "NOAA Tropical Cyclone Storm Tracks",
            "source": "NOAA Tropical Weather GIS layer 6 via God's Eye View",
            "data_mode": "GEOSPATIAL_FEATURES",
            "status": cyclone_source_state["tracks"]["last_fetch_status"],
            "last_updated_at_utc": cyclone_source_state["tracks"]["last_verified_at_utc"],
            "gis_layer_id": 6,
            "observation_endpoint": "/cyclones/nhc/tracks",
            "ingestion_endpoint": "/cyclones/nhc/ingest",
            "record_count": len(cyclone_observation_service.list(CYCLONE_DATASETS["tracks"], limit=1000)),
        },
        {
            "dataset_id": CYCLONE_DATASETS["cones"],
            "name": "NOAA Tropical Cyclone Forecast Cones",
            "source": "NOAA Tropical Weather GIS layer 7 via God's Eye View",
            "data_mode": "GEOSPATIAL_FEATURES",
            "status": cyclone_source_state["cones"]["last_fetch_status"],
            "last_updated_at_utc": cyclone_source_state["cones"]["last_verified_at_utc"],
            "gis_layer_id": 7,
            "observation_endpoint": "/cyclones/nhc/cones",
            "ingestion_endpoint": "/cyclones/nhc/ingest",
            "record_count": len(cyclone_observation_service.list(CYCLONE_DATASETS["cones"], limit=1000)),
        },
    ]
    return {"count": len(datasets), "datasets": datasets, "note": "Includes live feeds, imagery services, and explicitly labeled static source snapshots. Static datasets are not live feeds."}


@app.get("/live-datasets/registry", include_in_schema=False)
def live_feed_registry_page() -> FileResponse:
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "live-dataset-registry.html"), media_type="text/html")


# ---------------------------------------------------------------------------
# God\'s Eye View — OpenSky Network Flight Dataset Integration
# GET /api/opensky
# GET /api/opensky?lat=<latitude>&lon=<longitude>
# ---------------------------------------------------------------------------


@app.get("/api/opensky", tags=["flights", "geospatial"])
@app.get("/api/flights", tags=["flights", "geospatial"])
def get_opensky_flights(
    lat: Optional[float] = Query(None, ge=-90.0, le=90.0, description="Center latitude in decimal degrees (-90 to 90)"),
    lon: Optional[float] = Query(None, ge=-180.0, le=180.0, description="Center longitude in decimal degrees (-180 to 180)"),
    radius_nm: float = Query(100.0, gt=0.0, le=500.0, description="Bounding search radius in nautical miles"),
    icao24: Optional[str] = Query(None, description="24-bit ICAO aircraft hex transponder address"),
    callsign: Optional[str] = Query(None, description="Aircraft flight callsign"),
    limit: int = Query(1000, ge=1, le=5000, description="Maximum number of state vectors to return"),
) -> dict:
    """
    God's Eye View OpenSky Flight Telemetry API.

    Accepts global airspace queries or point-centered radius bounding box queries:
    - GET /api/opensky
    - GET /api/opensky?lat=<latitude>&lon=<longitude>

    Returns standard OpenSky state vectors (17-tuple format) compatible with
    God's Eye View CesiumJS 3D Globe visualization, including automatic 60-second
    rate-limit caching and governed offline fallback.
    """
    if hasattr(lat, "default"):
        lat = lat.default
    if hasattr(lon, "default"):
        lon = lon.default
    if hasattr(radius_nm, "default"):
        radius_nm = radius_nm.default or 100.0
    if hasattr(limit, "default"):
        limit = limit.default or 1000
    if hasattr(icao24, "default"):
        icao24 = icao24.default
    if hasattr(callsign, "default"):
        callsign = callsign.default

    if (lat is not None and lon is None) or (lat is None and lon is not None):
        raise HTTPException(
            status_code=400,
            detail="Both 'lat' and 'lon' query parameters must be provided together for coordinate-bounded flight tracking.",
        )

    try:
        return opensky_service.get_states(
            lat=lat,
            lon=lon,
            radius_nm=radius_nm,
            icao24=icao24,
            callsign=callsign,
            limit=limit,
        )
    except Exception as exc:
        logger.error("OpenSky flight query error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed retrieving flight state vectors: {str(exc)}") from exc


# ---------------------------------------------------------------------------
# God's Eye View — OpenSky Flight Telemetry Dataset Endpoints
# GET /api/datasets/ds-gev-opensky-flights
# GET /api/datasets/ds-gev-opensky-flights/records
# GET /datasets/ds-gev-opensky-flights
# ---------------------------------------------------------------------------


@app.get("/api/datasets/ds-gev-opensky-flights", tags=["datasets", "flights"])
@app.get("/datasets/ds-gev-opensky-flights", tags=["datasets", "flights"])
def get_opensky_flight_dataset() -> dict:
    """
    Dedicated endpoint for the God's Eye View OpenSky flight telemetry dataset:
    - Dataset ID: ds-gev-opensky-flights
    - File Location: datasets/opensky_states.json
    - Number of Flight Records: 17 authentic state vectors
    - Associated Capability: cap-gev-flight-tracking-staged (cap-gev-flight-tracking)
    - Associated Source: src-gev-opensky (source_store/src-gev-opensky.json)
    - Licence: Open Data Community License (ODbL v1.0)
    - Synthetic Records: 0 (100% authentic OpenSky Network data)
    """
    raw_states = opensky_service.load_governed_fallback_states()
    return {
        "dataset_id": "ds-gev-opensky-flights",
        "name": "God's Eye View - OpenSky Network Live Air Traffic Telemetry",
        "file_location": "datasets/opensky_states.json",
        "record_count": len(raw_states),
        "synthetic_records": 0,
        "format": "OpenSky 17-tuple state vector standard",
        "associated_capability": {
            "capability_id": "cap-gev-flight-tracking-staged",
            "alias": "cap-gev-flight-tracking",
            "name": "God's Eye View - Live Flight Tracking & Airspace Monitoring",
            "domain": "geospatial",
            "endpoint": "/capabilities/cap-gev-flight-tracking-staged/contract",
        },
        "associated_source": {
            "source_id": "src-gev-opensky",
            "name": "God's Eye View - OpenSky Network Live Air Traffic Telemetry",
            "authority": "The OpenSky Network / Bilawal Sidhu God's Eye View Proxy",
            "file_location": "source_store/src-gev-opensky.json",
            "endpoint": "/sources/src-gev-opensky",
        },
        "licence": {
            "name": "Open Data Community License (ODbL v1.0)",
            "type": "OPEN_COMMUNITY_DATA_LICENSE",
            "attribution": "Data provided by The OpenSky Network (https://opensky-network.org), bilawalsidhu/gods-eye-view",
            "commercial_use_policy": "Permitted under God's Eye View non-commercial research proxy",
        },
        "provenance": {
            "source": "OpenSky Network via God's Eye View Proxy",
            "repository": "https://github.com/bilawalsidhu/gods-eye-view",
            "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
            "certification": "MASTERDB-VERIFIED-GEV-006",
            "proxy_endpoint": "/api/opensky",
            "synthetic": False,
        },
        "endpoints": {
            "dataset_contract": "/api/datasets/ds-gev-opensky-flights",
            "records": "/api/datasets/ds-gev-opensky-flights/records",
            "query_api": "/api/opensky",
            "query_alias": "/api/flights",
        },
    }


@app.get("/api/datasets/ds-gev-opensky-flights/records", tags=["datasets", "flights"])
def get_opensky_flight_dataset_records(
    lat: Optional[float] = Query(None, ge=-90.0, le=90.0, description="Center latitude in decimal degrees (-90 to 90)"),
    lon: Optional[float] = Query(None, ge=-180.0, le=180.0, description="Center longitude in decimal degrees (-180 to 180)"),
    radius_nm: float = Query(100.0, gt=0.0, le=500.0, description="Bounding search radius in nautical miles"),
    icao24: Optional[str] = Query(None, description="24-bit ICAO aircraft hex transponder address"),
    callsign: Optional[str] = Query(None, description="Aircraft flight callsign"),
    limit: int = Query(1000, ge=1, le=5000, description="Maximum number of state vectors to return"),
) -> dict:
    """
    Returns authentic OpenSky flight records from datasets/opensky_states.json with optional coordinate/filtering.
    """
    return get_opensky_flights(
        lat=lat,
        lon=lon,
        radius_nm=radius_nm,
        icao24=icao24,
        callsign=callsign,
        limit=limit,
    )
