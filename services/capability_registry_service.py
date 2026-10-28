"""
Capability Registry Service — Ecosystem-Wide Capability Discovery & Access.

Owns MASTERDB Capability registration, discovery, machine-readable contract resolution,
and authorization/access evaluation for TANTRA runtime integration.
"""
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic.fields import FieldInfo

from models import (
    AccessContract,
    Capability,
    CapabilityAccessRequest,
    CapabilityContract,
    CapabilityRetrieveRequest,
    CapabilityRetrieveResponse,
    CapabilityStatus,
    PackageStatus,
    RetrievalStatus,
)
from services.artifact_store import ArtifactStore
from services.crypto_audit_emitter import CryptoAuditEmitter
from services.dataset_retrieval_service import DatasetRetrievalService
from services.package_registry_service import PackageNotFoundError, PackageRegistryService
from services.vana_client import (
    VanaClient,
    VanaGovernanceDeniedError,
    VanaUnavailableError,
)

logger = logging.getLogger("masterdb")

# Safely register dynamic schema extension fields at runtime to support VAJRA governed
# access contracts and correlation without modifying models.py directly.
if "expires_at" not in AccessContract.model_fields:
    AccessContract.model_fields["expires_at"] = FieldInfo(annotation=Optional[str], default=None)
    AccessContract.model_rebuild(force=True)

if "trace_id" not in CapabilityRetrieveRequest.model_fields:
    CapabilityRetrieveRequest.model_fields["trace_id"] = FieldInfo(annotation=Optional[str], default=None)
    CapabilityRetrieveRequest.model_fields["execution_id"] = FieldInfo(annotation=Optional[str], default=None)
    CapabilityRetrieveRequest.model_rebuild(force=True)

if "trace_id" not in CapabilityRetrieveResponse.model_fields:
    CapabilityRetrieveResponse.model_fields["trace_id"] = FieldInfo(annotation=Optional[str], default=None)
    CapabilityRetrieveResponse.model_fields["execution_id"] = FieldInfo(annotation=Optional[str], default=None)
    CapabilityRetrieveResponse.model_fields["content_digest_sha256"] = FieldInfo(annotation=Optional[str], default=None)
    CapabilityRetrieveResponse.model_rebuild(force=True)


class CapabilityNotFoundError(KeyError):
    """Raised when a requested capability_id does not exist."""
    pass


class CapabilityAlreadyExistsError(ValueError):
    """Raised when attempting to register a capability that already exists."""
    pass


class CapabilityAccessDeniedError(PermissionError):
    """Raised when authorization for capability access fails."""
    pass


class CapabilityVersionConflictError(ValueError):
    """Raised when a capability ID/version pair is already registered."""


class CapabilityRegistryService:
    def __init__(
        self,
        store_dir: str = "capability_store",
        package_registry: Optional[PackageRegistryService] = None,
        retrieval_service: Optional[DatasetRetrievalService] = None,
        audit_emitter: Optional[CryptoAuditEmitter] = None,
        vana_client: Optional[VanaClient] = None,
        grant_store: Optional[Any] = None,
        sql_store: Optional[Any] = None,
    ) -> None:
        self.store = ArtifactStore(reports_dir=store_dir)
        self.version_store = ArtifactStore(reports_dir=os.path.join(store_dir, "versions"))
        self.package_registry = package_registry or PackageRegistryService()
        self.retrieval_service = retrieval_service or DatasetRetrievalService(registry=self.package_registry)
        self.audit_emitter = audit_emitter or CryptoAuditEmitter()
        self.vana_client = vana_client or VanaClient()
        self.grant_store = grant_store or ArtifactStore(reports_dir=os.path.join(store_dir, "access_grants"))
        self.sql_store = sql_store
        self._access_contracts: Dict[str, AccessContract] = {}
        self._access_contract_actors: Dict[str, str] = {}
        self._seed_default_capabilities_if_empty()

    def _seed_default_capabilities_if_empty(self) -> None:
        # NOTE: Seed records below are DEMO / TEST FIXTURES for contract demonstration.
        # They demonstrate capability structure and discovery, not live production feeds.
        defaults = [
            Capability(
                capability_id="cap-mangrove-monitoring",
                capability_name="[DEMO] Mangrove Ecosystem Monitoring Service",
                description="Governed satellite and ground-truth mangrove vegetation and carbon index dataset (Demo Fixture)",
                dataset_id="ds-mangrove-001",
                source_id="src-isro-eos-001",
                purpose="environmental_monitoring",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="geospatial",
                schema_version="v1.2",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "area_of_interest", "type": "GeoJSON Polygon", "required": True},
                    {"name": "spectral_band", "type": "String", "required": False},
                ],
                outputs=[
                    {"name": "canopy_density_map", "type": "GeoJSON FeatureCollection"},
                    {"name": "biomass_index", "type": "Float"},
                ],
                dependencies=["ISRO EO Satellite Constellation (Demo)", "MDU-Semantic-Contract-Engine"],
                source_references=["src-isro-eos-001"],
                dataset_references=["ds-mangrove-001"],
                known_limitations=["Cloud cover monsoon distortion"],
                potential_consumers=["Bharat Mala (Demo)", "VANA/FIN (Demo)", "Marine Intelligence (Demo)"],
                licensing={"software_licence": "UNKNOWN", "dataset_licence": "PENDING VERIFICATION", "source_licence": "UNVERIFIED"},
                supported_access_methods=["QUERY", "EXPORT", "STREAM", "REFERENCE", "RETRIEVE"],
                required_purpose="environmental_monitoring",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "dashboard-viewer", "operator", "admin"],
                    "allowed_consumers": ["*"],
                },
                provenance={
                    "source": "ISRO/EO-Sat-Mangrove-Constellation (Demo Fixture)",
                    "certification": "MASTERDB-CERT-GEO-001-DEMO",
                    "lineage_ref": "lin-mangrove-2026-demo",
                },
            ),
            Capability(
                capability_id="cap-maritime-cargo",
                capability_name="[DEMO] Marine Vessel Tracking & Port Analytics",
                description="Real-time vessel positions, port congestion, and shipping manifest data service (Demo Fixture)",
                dataset_id="ds-maritime-001",
                source_id="src-maritime-gateway-002",
                purpose="maritime_logistics",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="maritime",
                schema_version="v2.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "vessel_id", "type": "IMO Standard ID", "required": False},
                    {"name": "port_code", "type": "UN/LOCODE", "required": False},
                ],
                outputs=[
                    {"name": "vessel_telemetry", "type": "JSON Object"},
                    {"name": "port_congestion_index", "type": "Float"},
                ],
                dependencies=["National Maritime Data Gateway (Demo)"],
                source_references=["src-maritime-gateway-002"],
                dataset_references=["ds-maritime-001"],
                known_limitations=["AIS transponder blind spots"],
                potential_consumers=["Marine (Demo)", "TANTRA", "Bharat Mala (Demo)"],
                licensing={"software_licence": "UNKNOWN", "dataset_licence": "PENDING VERIFICATION", "source_licence": "UNVERIFIED"},
                supported_access_methods=["QUERY", "EXPORT", "STREAM", "REFERENCE", "RETRIEVE"],
                required_purpose="maritime_logistics",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin"],
                    "allowed_consumers": ["Marine", "TANTRA", "*"],
                },
                provenance={
                    "source": "National Maritime Data Gateway (Demo Fixture)",
                    "certification": "MASTERDB-CERT-MAR-002-DEMO",
                    "lineage_ref": "lin-maritime-2026-demo",
                },
            ),
            Capability(
                capability_id="cap-fin-market-analytics",
                capability_name="[DEMO] Financial Market Analytics & Credit Risk Data",
                description="Governed financial transactions, credit indices, and market intelligence data (Demo Fixture)",
                dataset_id="ds-fin-001",
                source_id="src-fin-reserve-003",
                purpose="financial_analysis",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="finance",
                schema_version="v1.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[{"name": "symbol", "type": "Ticker String", "required": False}],
                outputs=[{"name": "market_index", "type": "JSON Object"}],
                dependencies=["Reserve Financial Network Gateway (Demo)"],
                source_references=["src-fin-reserve-003"],
                dataset_references=["ds-fin-001"],
                known_limitations=["Delayed after trading hours"],
                potential_consumers=["FIN (Demo)", "VANA/FIN (Demo)", "TANTRA"],
                licensing={"software_licence": "UNKNOWN", "dataset_licence": "PENDING VERIFICATION", "source_licence": "UNVERIFIED"},
                supported_access_methods=["QUERY", "EXPORT", "STREAM", "REFERENCE", "RETRIEVE"],
                required_purpose="financial_analysis",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin"],
                    "allowed_consumers": ["FIN", "TANTRA", "*"],
                },
                provenance={
                    "source": "Reserve Financial Network Gateway (Demo Fixture)",
                    "certification": "MASTERDB-CERT-FIN-003-DEMO",
                    "lineage_ref": "lin-fin-2026-demo",
                },
            ),
            Capability(
                capability_id="cap-bharat-mala-highways",
                capability_name="[DEMO] Bharat Mala Highway Infrastructure & Corridor Data",
                description="National highway construction status, toll collection, and freight corridor telemetry (Demo Fixture)",
                dataset_id="ds-bharatmala-001",
                source_id="src-nhai-corridor-003",
                purpose="infrastructure_planning",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="infrastructure",
                schema_version="v1.1",
                status=CapabilityStatus.ACTIVE,
                inputs=[{"name": "corridor_id", "type": "String", "required": False}],
                outputs=[{"name": "corridor_telemetry", "type": "JSON Object"}],
                dependencies=["NHAI Highway Infrastructure & Toll Engine (Demo)"],
                source_references=["src-nhai-corridor-003"],
                dataset_references=["ds-bharatmala-001"],
                known_limitations=["Remote toll booth connectivity delay"],
                potential_consumers=["Bharat Mala (Demo)", "VANA/FIN (Demo)", "TANTRA"],
                licensing={"software_licence": "UNKNOWN", "dataset_licence": "PENDING VERIFICATION", "source_licence": "UNVERIFIED"},
                supported_access_methods=["QUERY", "EXPORT", "STREAM", "REFERENCE", "RETRIEVE"],
                required_purpose="infrastructure_planning",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin"],
                    "allowed_consumers": ["Bharat Mala", "TANTRA", "*"],
                },
                provenance={
                    "source": "Ministry of Road Transport & Highways Data Engine (Demo Fixture)",
                    "certification": "MASTERDB-CERT-INF-004-DEMO",
                    "lineage_ref": "lin-infra-2026-demo",
                },
            ),
            Capability(
                capability_id="cap-marine-intel-ports",
                capability_name="Marine Intelligence - Indian Ports & Harbours Data Service",
                description="Governed Indian major & non-major port infrastructure, coordinates, state jurisdiction, and operational notes dataset from Marine Intelligence data layer.",
                dataset_id="ds-marine-intel-ports",
                source_id="src-marine-intel-ports",
                purpose="maritime_infrastructure_analytics",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="maritime",
                schema_version="v1.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "port_name", "type": "String", "required": False},
                    {"name": "state", "type": "String", "required": False},
                    {"name": "port_type", "type": "String", "required": False},
                ],
                outputs=[
                    {"name": "ports_list", "type": "JSON Array"},
                    {"name": "port_details", "type": "JSON Object"},
                ],
                dependencies=["Ministry of Ports, Shipping and Waterways", "Sagarmala Development Company", "Marine Intelligence Data Engine"],
                source_references=["src-marine-intel-ports"],
                dataset_references=["ds-marine-intel-ports"],
                known_limitations=["Port administrative updates subject to ministry publication cycles"],
                potential_consumers=["Marine Intelligence", "Bharat Mala", "VANA/FIN", "TANTRA"],
                licensing={"software_licence": "MIT", "dataset_licence": "PUBLIC_GOVERNMENT_DATA", "source_licence": "PUBLIC_GOVERNMENT_DATA"},
                supported_access_methods=["QUERY", "EXPORT", "RETRIEVE"],
                required_purpose="maritime_infrastructure_analytics",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin"],
                    "allowed_consumers": ["*"],
                },
                provenance={
                    "source": "Ministry of Ports, Shipping and Waterways via Marine Intelligence Data Layer",
                    "repository": "https://github.com/shravani2207-tech/marine-intelligence-task",
                    "commit": "03af9e32eeba275592a8e19041d7b51d6139dad7",
                    "certification": "MASTERDB-VERIFIED-MARINE-001",
                },
            ),
            Capability(
                capability_id="cap-gev-satellite-pass-prediction",
                capability_name="God's Eye View - Satellite Orbit Propagation & Pass Prediction",
                description="Governed orbital state vector propagation and pass prediction using CelesTrak NORAD TLE catalogs and SGP4 orbit calculation.",
                dataset_id="ds-gev-satellite-tles",
                source_id="src-gev-celestrak",
                purpose="space_situational_awareness",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="geospatial",
                schema_version="v1.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "catnr", "type": "Integer", "required": False},
                    {"name": "group", "type": "String", "required": False},
                    {"name": "observer_lat", "type": "Float", "required": False},
                    {"name": "observer_lon", "type": "Float", "required": False},
                ],
                outputs=[
                    {"name": "tle_lines", "type": "JSON Array"},
                    {"name": "predicted_passes", "type": "JSON Array"},
                ],
                dependencies=["CelesTrak TLE catalog", "GEV /api/space proxy", "GEV /api/overpass proxy", "SGP4 calculator"],
                source_references=["src-gev-celestrak"],
                dataset_references=["ds-gev-satellite-tles"],
                known_limitations=["SGP4 accuracy degradation over time without fresh TLEs"],
                potential_consumers=["Bharat Mala", "VANA/FIN", "TANTRA"],
                licensing={"software_licence": "MIT", "dataset_licence": "US_GOVERNMENT_PUBLIC_DOMAIN", "source_licence": "US_GOVERNMENT_PUBLIC_DOMAIN"},
                supported_access_methods=["QUERY", "EXPORT", "RETRIEVE"],
                required_purpose="space_situational_awareness",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin"],
                    "allowed_consumers": ["*"],
                },
                provenance={
                    "source": "CelesTrak via God's Eye View Proxy",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
                    "certification": "MASTERDB-VERIFIED-GEV-002",
                },
            ),
            Capability(
                capability_id="cap-gev-wildfire-perimeter-monitoring",
                capability_name="God's Eye View - Wildfire Incident & Perimeter Monitoring",
                description="Governed active wildfire perimeters, containment status, thermal hot-spots, and InciWeb incident narrative integration.",
                dataset_id="ds-gev-wildfire-perimeters",
                source_id="src-gev-nifc-firms",
                purpose="disaster_response_and_safety",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="geospatial",
                schema_version="v1.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "bbox", "type": "BoundingBox Array", "required": False},
                    {"name": "incident_name", "type": "String", "required": False},
                ],
                outputs=[
                    {"name": "fire_perimeters", "type": "GeoJSON FeatureCollection"},
                    {"name": "inciweb_narrative", "type": "JSON Object"},
                ],
                dependencies=["NIFC WFIGS ArcGIS FeatureServer", "GEV /api/fire-perimeters proxy", "NASA FIRMS WMTS"],
                source_references=["src-gev-nifc-firms"],
                dataset_references=["ds-gev-wildfire-perimeters"],
                known_limitations=["Agency perimeter publication lag", "Cloud and smoke coverage on optical sensors"],
                potential_consumers=["Bharat Mala", "VANA/FIN", "TANTRA"],
                licensing={"software_licence": "MIT", "dataset_licence": "US_GOVERNMENT_PUBLIC_DOMAIN", "source_licence": "US_GOVERNMENT_PUBLIC_DOMAIN"},
                supported_access_methods=["QUERY", "STREAM", "RETRIEVE"],
                required_purpose="disaster_response_and_safety",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin"],
                    "allowed_consumers": ["*"],
                },
                provenance={
                    "source": "NIFC WFIGS & NASA FIRMS via God's Eye View Proxy",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
                    "certification": "MASTERDB-VERIFIED-GEV-003",
                },
            ),
            Capability(
                capability_id="cap-gev-weather-forecast-tracking",
                capability_name="God's Eye View - Severe Weather & Cyclone Track Forecast",
                description="Governed 10m global wind vectors, rain radar, satellite clouds, lightning density, and NHC cyclone forecast cones.",
                dataset_id="ds-gev-weather-telemetry",
                source_id="src-gev-noaa-weather",
                purpose="meteorological_monitoring",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="geospatial",
                schema_version="v1.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "layer_type", "type": "String (wind/cyclones/radar/satellite/lightning)", "required": True},
                    {"name": "storm_id", "type": "String", "required": False},
                ],
                outputs=[
                    {"name": "weather_grid_or_track", "type": "JSON Object"},
                ],
                dependencies=["NOAA GFS AWS S3", "NOAA nowCOAST GeoServer WMS", "NHC Tropical Weather MapServer", "GEV /api/weather /api/cyclones /api/wind proxies"],
                source_references=["src-gev-noaa-weather"],
                dataset_references=["ds-gev-weather-telemetry"],
                known_limitations=["GFS 0.25deg grid resolution limit", "nowCOAST radar coverage limited to CONUS/Americas"],
                potential_consumers=["Bharat Mala", "VANA/FIN", "Marine Intelligence", "TANTRA"],
                licensing={"software_licence": "MIT", "dataset_licence": "US_PUBLIC_DOMAIN", "source_licence": "US_PUBLIC_DOMAIN"},
                supported_access_methods=["QUERY", "STREAM", "RETRIEVE"],
                required_purpose="meteorological_monitoring",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin"],
                    "allowed_consumers": ["*"],
                },
                provenance={
                    "source": "NOAA NWS & nowCOAST via God's Eye View Proxy",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
                    "certification": "MASTERDB-VERIFIED-GEV-004",
                },
            ),
            Capability(
                capability_id="cap-gev-earthquake-monitoring",
                capability_name="God's Eye View - Real-time Global Seismic Event Detection",
                description="Governed real-time global earthquake events, magnitudes, focal depths, and shake-map intensity indicators from USGS.",
                dataset_id="ds-gev-seismic-events",
                source_id="src-gev-usgs-seismic",
                purpose="seismic_hazard_monitoring",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="geospatial",
                schema_version="v1.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "min_magnitude", "type": "Float", "required": False},
                    {"name": "time_window", "type": "String", "required": False},
                ],
                outputs=[
                    {"name": "seismic_events", "type": "GeoJSON FeatureCollection"},
                ],
                dependencies=["USGS Earthquake API GeoJSON feed"],
                source_references=["src-gev-usgs-seismic"],
                dataset_references=["ds-gev-seismic-events"],
                known_limitations=["Automated initial magnitude estimates revised after manual analyst review"],
                potential_consumers=["Bharat Mala", "VANA/FIN", "TANTRA"],
                licensing={"software_licence": "MIT", "dataset_licence": "US_GOVERNMENT_PUBLIC_DOMAIN", "source_licence": "US_GOVERNMENT_PUBLIC_DOMAIN"},
                supported_access_methods=["QUERY", "STREAM", "RETRIEVE"],
                required_purpose="seismic_hazard_monitoring",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin"],
                    "allowed_consumers": ["*"],
                },
                provenance={
                    "source": "USGS Earthquake Hazards Program via God's Eye View Proxy",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
                    "certification": "MASTERDB-VERIFIED-GEV-005",
                },
            ),
            Capability(
                capability_id="cap-vana-forest-cover",
                capability_name="VANA - FSI ISFR 2023 Official Forest Cover Records",
                description="Governed official Forest Survey of India (ISFR 2023) district forest canopy and mangrove coverage records with immutable source provenance.",
                dataset_id="DS-FSI-ISFR-2023-FOREST-COVER",
                source_id="src-fsi-isfr-2023",
                purpose="district_canopy_analysis",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="geospatial",
                schema_version="v1.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "district", "type": "String", "required": False},
                    {"name": "state", "type": "String", "required": False},
                ],
                outputs=[
                    {"name": "forest_cover_records", "type": "Array of FSI Canopy Records"},
                    {"name": "source_provenance", "type": "JSON Object"},
                ],
                dependencies=["FSI ISFR 2023 Official Catalog", "VANA 6-Tuple Governance Evaluation Gate"],
                source_references=["src-fsi-isfr-2023"],
                dataset_references=["DS-FSI-ISFR-2023-FOREST-COVER"],
                known_limitations=["Biennial reporting cycle (2023 edition)"],
                potential_consumers=["MASTERDB", "TANTRA", "Bharat Mala", "VANA/FIN"],
                licensing={"software_licence": "GOVERNMENT_OPEN_DATA", "dataset_licence": "FSI_OFFICIAL_ISFR", "source_licence": "GOVERNMENT_OPEN_DATA"},
                supported_access_methods=["QUERY", "EXPORT", "STREAM", "RETRIEVE"],
                required_purpose="district_canopy_analysis",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin", "APPROVED_CONSUMER"],
                    "allowed_consumers": ["*"],
                },
                provenance={
                    "source": "Forest Survey of India (ISFR 2023) via VANA Governance Layer",
                    "certification": "VANA-ISFR-2023-CANONICAL",
                    "governance_gate": "6_TUPLE_EVALUATION_GATE",
                },
            ),
            Capability(
                capability_id="cap-vana-thane-creek-carbon",
                capability_name="VANA - Thane Creek Mangrove Blue Carbon Engine",
                description="Governed Thane Creek Flamingo Sanctuary mangrove blue carbon quantification with strict measured vs satellite segregation.",
                dataset_id="DS-VANA-THANE-CREEK-BLUE-CARBON",
                source_id="src-vana-thane-creek",
                purpose="carbon_quantification",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="geospatial",
                schema_version="v1.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "zone", "type": "String", "required": False},
                    {"name": "segregation_mode", "type": "String (measured/satellite/combined)", "required": False},
                ],
                outputs=[
                    {"name": "blue_carbon_stock_tC", "type": "Float"},
                    {"name": "measurement_segregation", "type": "JSON Object"},
                ],
                dependencies=["VANA Carbon Quantification Engine", "Thane Creek Blue Carbon Ground Truth"],
                source_references=["src-vana-thane-creek"],
                dataset_references=["DS-VANA-THANE-CREEK-BLUE-CARBON"],
                known_limitations=["Field measurement sample interval 30-day refresh"],
                potential_consumers=["MASTERDB", "TANTRA", "Bharat Mala", "VANA/FIN"],
                licensing={"software_licence": "PROPRIETARY_BHIV", "dataset_licence": "BHIV_RESEARCH_USE", "source_licence": "BHIV_RESEARCH_USE"},
                supported_access_methods=["QUERY", "EXPORT", "STREAM", "RETRIEVE"],
                required_purpose="carbon_quantification",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin", "APPROVED_CONSUMER"],
                    "allowed_consumers": ["*"],
                },
                provenance={
                    "source": "VANA Blue Carbon Engine (Thane Creek)",
                    "certification": "VANA-BLUE-CARBON-VERIFIED",
                    "governance_gate": "6_TUPLE_EVALUATION_GATE",
                },
            ),
            Capability(
                capability_id="cap-vana-spatial-layers",
                capability_name="VANA - Spatial GIS GeoJSON Layers",
                description="Governed RFC 7946 WGS84 GeoJSON spatial layers: sanctuary boundaries, mangrove density, and nurseries.",
                dataset_id="DS-VANA-SPATIAL-LAYERS",
                source_id="src-vana-gis",
                purpose="spatial_gis_analysis",
                capability_version="1.0.0",
                contract_version="1.0.0",
                domain="geospatial",
                schema_version="v1.0",
                status=CapabilityStatus.ACTIVE,
                inputs=[
                    {"name": "layer_id", "type": "String", "required": False},
                ],
                outputs=[
                    {"name": "geojson_layer", "type": "RFC 7946 GeoJSON FeatureCollection"},
                ],
                dependencies=["VANA Spatial GIS Layer Catalog", "RFC 7946 Specification"],
                source_references=["src-vana-gis"],
                dataset_references=["DS-VANA-SPATIAL-LAYERS"],
                known_limitations=["WGS84 projection standard"],
                potential_consumers=["MASTERDB", "TANTRA", "Bharat Mala", "God's Eye View"],
                licensing={"software_licence": "PROPRIETARY_BHIV", "dataset_licence": "GOVERNMENT_OPEN_DATA", "source_licence": "GOVERNMENT_OPEN_DATA"},
                supported_access_methods=["QUERY", "EXPORT", "STREAM", "RETRIEVE"],
                required_purpose="spatial_gis_analysis",
                authorization_requirements={
                    "required_roles": ["ecosystem-reader", "viewer", "operator", "admin", "APPROVED_CONSUMER"],
                    "allowed_consumers": ["*"],
                },
                provenance={
                    "source": "VANA Spatial GIS Layer Catalog",
                    "certification": "VANA-RFC7946-GEOJSON",
                    "governance_gate": "6_TUPLE_EVALUATION_GATE",
                },
            ),
        ]

        existing_caps = {c.capability_id for c in self.list_capabilities()}
        for cap in defaults:
            if cap.capability_id not in existing_caps:
                self.register_capability(cap)

    def register_capability(
        self, capability: Capability, check_duplicate: bool = True
    ) -> Capability:
        restricted_keywords = ["opensky", "telegeography"]
        cap_str = (
            f"{capability.capability_id} {capability.capability_name} "
            f"{capability.description} {' '.join(capability.dependencies)} "
            f"{' '.join(capability.source_references)}"
        ).lower()
        if any(keyword in cap_str for keyword in restricted_keywords):
            raise ValueError(
                f"Registration of commercially restricted/unverified capability "
                f"'{capability.capability_id}' is prohibited."
            )

        version_key = self._version_key(
            capability.capability_id, capability.capability_version
        )
        existing = self.store.load(capability.capability_id)
        if check_duplicate and existing and existing.get("capability_version") == capability.capability_version:
            raise CapabilityVersionConflictError(
                f"Capability '{capability.capability_id}' version "
                f"'{capability.capability_version}' is already registered."
            )
        if check_duplicate and self.version_store.load(version_key):
            raise CapabilityVersionConflictError(
                f"Capability '{capability.capability_id}' version "
                f"'{capability.capability_version}' is already registered."
            )

        try:
            self.package_registry.get_by_dataset_id(capability.dataset_id)
        except PackageNotFoundError:
            self.package_registry.register(
                dataset_id=capability.dataset_id,
                dataset_version=capability.capability_version,
                schema_version=capability.schema_version,
                board=capability.domain,
                medium="api",
                language="json",
                owner="masterdb-governance",
                actor="capability_registry",
                reason=f"Seeded for capability {capability.capability_id}",
            )

        serialized = capability.model_dump(mode="json")
        serialized["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.version_store.save(version_key, serialized)
        self.store.save(capability.capability_id, serialized)
        logger.info("capability_registered capability_id=%s domain=%s", capability.capability_id, capability.domain)
        return Capability.model_validate(serialized)

    def list_capabilities(
        self,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Capability]:
        records = self.store.list_all()
        capabilities: List[Capability] = []
        for rec in records:
            try:
                cap = Capability.model_validate(rec)
                capabilities.append(cap)
            except Exception as exc:
                logger.warning("Failed to parse capability record: %s", exc)

        if domain:
            capabilities = [c for c in capabilities if c.domain.lower() == domain.lower()]
        if status:
            capabilities = [c for c in capabilities if c.status.value.lower() == status.lower()]
        if search:
            s = search.lower()
            capabilities = [
                c
                for c in capabilities
                if s in c.capability_name.lower() or s in c.description.lower() or s in c.capability_id.lower()
            ]
        return sorted(capabilities, key=lambda x: x.capability_id)

    def get_capability(self, capability_id: str) -> Capability:
        data = self.store.load(capability_id)
        if not data:
            raise CapabilityNotFoundError(f"Capability '{capability_id}' not found.")
        return Capability.model_validate(data)

    def get_capability_versions(self, capability_id: str) -> List[Capability]:
        current = self.get_capability(capability_id)
        versions = [
            Capability.model_validate(record)
            for record in self.version_store.list_all()
            if record.get("capability_id") == capability_id
        ]
        if not any(item.capability_version == current.capability_version for item in versions):
            versions.append(current)
        return sorted(versions, key=lambda item: item.created_at)

    @staticmethod
    def _version_key(capability_id: str, version: str) -> str:
        digest = hashlib.sha256(f"{capability_id}\0{version}".encode("utf-8")).hexdigest()
        return f"cap-version-{digest}"

    def get_contract(self, capability_id: str) -> CapabilityContract:
        capability = self.get_capability(capability_id)
        schema_info = {}
        try:
            schema_info = self.retrieval_service.get_dataset_schema(capability.dataset_id)
        except Exception:
            schema_info = {
                "source": "capability-contract-declared",
                "dataset_id": capability.dataset_id,
                "schema_version": capability.schema_version,
            }

        provenance_info = {}
        try:
            provenance_info = self.retrieval_service.get_dataset_provenance(capability.dataset_id)
        except Exception:
            provenance_info = {
                "masterdb_lineage": None,
                "mdu_provenance": [],
                "mdu_source": "unavailable",
            }

        return CapabilityContract(
            capability_id=capability.capability_id,
            capability_name=capability.capability_name,
            purpose=capability.purpose,
            description=capability.description,
            dataset_id=capability.dataset_id,
            source_id=capability.source_id or "src-unknown",
            capability_version=capability.capability_version,
            contract_version=capability.contract_version,
            domain=capability.domain,
            schema_version=capability.schema_version,
            status=capability.status.value,
            inputs=capability.inputs,
            outputs=capability.outputs,
            dependencies=capability.dependencies,
            source_references=capability.source_references,
            dataset_references=capability.dataset_references,
            known_limitations=capability.known_limitations,
            potential_consumers=capability.potential_consumers,
            licensing_metadata=capability.licensing,
            required_purpose=capability.required_purpose,
            supported_access_methods=capability.supported_access_methods,
            authorization_requirements=capability.authorization_requirements,
            access_endpoint=f"/capabilities/{capability.capability_id}/retrieve",
            provenance_reference={
                "masterdb_lineage": provenance_info.get("masterdb_lineage"),
                "mdu_provenance": provenance_info.get("mdu_provenance"),
                "static_metadata": capability.provenance,
            },
            mdu_contract_ref=schema_info,
        )

    def request_access(
        self,
        actor: str,
        roles: List[str],
        request_data: CapabilityAccessRequest,
    ) -> AccessContract:
        req_id = request_data.request_id or f"req-{uuid.uuid4().hex[:12]}"
        try:
            capability = self.get_capability(request_data.capability_id)
        except CapabilityNotFoundError as exc:
            self._emit_audit(
                request_id=req_id,
                actor=actor,
                application_id=request_data.application_id,
                capability_id=request_data.capability_id,
                action="ACCESS_REQUEST",
                result="DENIED",
                reason=str(exc),
            )
            raise

        # Check capability status
        if capability.status not in (CapabilityStatus.ACTIVE, CapabilityStatus.CERTIFIED):
            reason = f"Capability status '{capability.status.value}' is not active for access."
            self._emit_audit(
                request_id=req_id,
                actor=actor,
                application_id=request_data.application_id,
                capability_id=request_data.capability_id,
                action="ACCESS_REQUEST",
                result="DENIED",
                reason=reason,
            )
            raise CapabilityAccessDeniedError(reason)

        if request_data.capability_version and request_data.capability_version != capability.capability_version:
            reason = (
                f"Capability '{capability.capability_id}' version "
                f"'{request_data.capability_version}' is not the current registered version "
                f"'{capability.capability_version}'."
            )
            self._emit_audit(
                request_id=req_id,
                actor=actor,
                application_id=request_data.application_id,
                capability_id=capability.capability_id,
                action="ACCESS_REQUEST",
                result="DENIED",
                reason=reason,
            )
            raise CapabilityAccessDeniedError(reason)

        # Evaluate authorization requirements
        auth_reqs = capability.authorization_requirements or {}
        req_roles = auth_reqs.get("required_roles", [])
        allowed_apps = auth_reqs.get("allowed_consumers", ["*"])

        role_ok = not req_roles or any(r in roles for r in req_roles) or "bhiv-admin" in roles or "admin" in roles
        app_ok = "*" in allowed_apps or request_data.application_id in allowed_apps

        if not role_ok:
            reason = f"Identity '{actor}' with roles {roles} lacks required authority {req_roles}."
            self._emit_audit(
                request_id=req_id,
                actor=actor,
                application_id=request_data.application_id,
                capability_id=request_data.capability_id,
                action="ACCESS_REQUEST",
                result="DENIED",
                reason=reason,
            )
            raise CapabilityAccessDeniedError(reason)

        if not app_ok:
            reason = f"Application '{request_data.application_id}' is not authorized consumer for this capability."
            self._emit_audit(
                request_id=req_id,
                actor=actor,
                application_id=request_data.application_id,
                capability_id=request_data.capability_id,
                action="ACCESS_REQUEST",
                result="DENIED",
                reason=reason,
            )
            raise CapabilityAccessDeniedError(reason)

        allowed_purposes = {
            capability.required_purpose.lower(),
            "general_reuse",
            "production_integration",
            "testing",
        }
        if capability.required_purpose and request_data.purpose.strip().lower() not in allowed_purposes:
            reason = (
                f"Purpose '{request_data.purpose}' is not permitted for capability "
                f"'{capability.capability_id}'; required purpose is '{capability.required_purpose}'."
            )
            self._emit_audit(
                request_id=req_id,
                actor=actor,
                application_id=request_data.application_id,
                capability_id=capability.capability_id,
                action="ACCESS_REQUEST",
                result="DENIED",
                reason=reason,
            )
            raise CapabilityAccessDeniedError(reason)

        # Evaluate VANA 6-tuple governance evaluation gate if configured and applicable
        if self.vana_client and self.vana_client.is_configured():
            if (
                capability.capability_id.startswith("cap-vana-")
                or capability.dataset_id.startswith("DS-FSI-")
                or capability.dataset_id.startswith("DS-VANA-")
            ):
                try:
                    primary_role = roles[0] if roles else "APPROVED_CONSUMER"
                    self.vana_client.evaluate_governance(
                        actor=actor,
                        role=primary_role,
                        dataset_id=capability.dataset_id,
                        action="READ",
                        purpose=request_data.purpose,
                    )
                except VanaGovernanceDeniedError as exc:
                    reason = f"VANA 6-tuple governance evaluation denied access: {exc}"
                    self._emit_audit(
                        request_id=req_id,
                        actor=actor,
                        application_id=request_data.application_id,
                        capability_id=capability.capability_id,
                        action="ACCESS_REQUEST",
                        result="DENIED",
                        reason=reason,
                    )
                    raise CapabilityAccessDeniedError(reason) from exc
                except Exception as exc:
                    logger.warning("VANA governance evaluation check warning: %s", exc)

        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        access_contract = AccessContract(
            request_id=req_id,
            application_id=request_data.application_id,
            capability_id=capability.capability_id,
            capability_version=capability.capability_version,
            contract_version=capability.contract_version,
            purpose=request_data.purpose,
            authorized=True,
            access_scope=capability.supported_access_methods,
            reason="Access authorized based on authenticated application identity, role, and matching purpose.",
            expires_at=expires_at,
        )

        self._access_contracts[access_contract.request_id] = access_contract
        self._access_contracts[access_contract.access_token] = access_contract
        self._access_contract_actors[access_contract.access_token] = actor

        # Persist to durable grant store
        if self.grant_store is not None:
            try:
                grant_record = {
                    "contract": access_contract.model_dump(mode="json"),
                    "actor": actor,
                    "revoked": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                self.grant_store.save(access_contract.access_token, grant_record)
                self.grant_store.save(access_contract.request_id, grant_record)
            except Exception as exc:
                logger.warning("Failed to persist access contract to grant store: %s", exc)

        self._emit_audit(
            request_id=req_id,
            actor=actor,
            application_id=request_data.application_id,
            capability_id=capability.capability_id,
            action="ACCESS_REQUEST",
            result="GRANTED",
            reason=access_contract.reason,
        )

        return access_contract

    def get_access_contract(self, request_id_or_token: str) -> Optional[AccessContract]:
        contract = self._access_contracts.get(request_id_or_token)
        if contract is not None:
            return contract
        if self.grant_store is not None:
            try:
                data = self.grant_store.load(request_id_or_token)
                if data and not data.get("revoked", False):
                    contract = AccessContract.model_validate(data["contract"])
                    self._access_contracts[contract.request_id] = contract
                    self._access_contracts[contract.access_token] = contract
                    self._access_contract_actors[contract.access_token] = data.get("actor", "")
                    return contract
            except Exception as exc:
                logger.warning("Failed to load access grant from store: %s", exc)
        return None

    def revoke_access_contract(self, request_id_or_token: str, actor: str, reason: str = "") -> bool:
        contract = self.get_access_contract(request_id_or_token)
        if not contract:
            return False

        if self.grant_store is not None:
            try:
                data = self.grant_store.load(contract.access_token) or self.grant_store.load(contract.request_id) or {}
                data["revoked"] = True
                data["revoked_at"] = datetime.now(timezone.utc).isoformat()
                data["revoked_by"] = actor
                data["revocation_reason"] = reason
                self.grant_store.save(contract.access_token, data)
                self.grant_store.save(contract.request_id, data)
            except Exception as exc:
                logger.warning("Failed to persist revocation to grant store: %s", exc)

        self._access_contracts.pop(contract.access_token, None)
        self._access_contracts.pop(contract.request_id, None)
        self._access_contract_actors.pop(contract.access_token, None)

        self._emit_audit(
            request_id=contract.request_id,
            actor=actor,
            application_id=contract.application_id,
            capability_id=contract.capability_id,
            action="ACCESS_REVOKED",
            result="REVOKED",
            reason=reason or "Access contract revoked by administrator.",
        )
        return True

    def retrieve(
        self,
        actor: str,
        roles: List[str],
        capability_id: str,
        retrieve_req: CapabilityRetrieveRequest,
    ) -> CapabilityRetrieveResponse:
        capability = self.get_capability(capability_id)
        if not capability:
            raise CapabilityNotFoundError(f"Capability '{capability_id}' not found.")

        # Resolve access grant
        contract: Optional[AccessContract] = None
        has_explicit_credential = bool(retrieve_req.access_token or retrieve_req.request_id)
        req_id = retrieve_req.request_id or f"req-ret-{uuid.uuid4().hex[:10]}"

        if retrieve_req.access_token:
            contract = self.get_access_contract(retrieve_req.access_token)
        elif retrieve_req.request_id:
            contract = self.get_access_contract(retrieve_req.request_id)

        if not contract:
            if not has_explicit_credential:
                # Direct/in-process retrieval without prior token: evaluate access on the fly
                app_id = retrieve_req.application_id or actor
                access_req = CapabilityAccessRequest(
                    application_id=app_id,
                    capability_id=capability_id,
                    purpose=capability.required_purpose or "general_reuse",
                    request_id=req_id,
                )
                contract = self.request_access(actor=actor, roles=roles, request_data=access_req)
            else:
                # Explicit credential was supplied but was not found or was revoked
                was_revoked = False
                token_key = retrieve_req.access_token or retrieve_req.request_id or ""
                if self.grant_store is not None and token_key:
                    try:
                        data = self.grant_store.load(token_key)
                        if data and data.get("revoked", False):
                            was_revoked = True
                    except Exception:
                        pass

                reason = "Access grant has been revoked." if was_revoked else "Valid access grant required. Provided token/request_id is invalid or unauthorized."
                self._emit_audit(
                    request_id=retrieve_req.request_id or "unknown",
                    actor=actor,
                    application_id=retrieve_req.application_id or "unknown",
                    capability_id=capability_id,
                    action="DATA_RETRIEVAL",
                    result="DENIED",
                    reason=reason,
                    trace_id=retrieve_req.trace_id,
                    execution_id=retrieve_req.execution_id,
                )
                raise CapabilityAccessDeniedError(reason)

        # Ensure grant authorizes the requested capability
        if contract.capability_id != capability_id:
            reason = f"Access contract '{contract.request_id}' was issued for '{contract.capability_id}', not '{capability_id}'."
            self._emit_audit(
                request_id=contract.request_id,
                actor=actor,
                application_id=retrieve_req.application_id or contract.application_id,
                capability_id=capability_id,
                action="DATA_RETRIEVAL",
                result="DENIED",
                reason=reason,
                trace_id=retrieve_req.trace_id,
                execution_id=retrieve_req.execution_id,
            )
            raise CapabilityAccessDeniedError(reason)

        # Validate consumer/application binding
        if retrieve_req.application_id and retrieve_req.application_id != contract.application_id:
            reason = f"Access contract was issued to application '{contract.application_id}', not '{retrieve_req.application_id}'."
            self._emit_audit(
                request_id=contract.request_id,
                actor=actor,
                application_id=retrieve_req.application_id,
                capability_id=capability_id,
                action="DATA_RETRIEVAL",
                result="DENIED",
                reason=reason,
                trace_id=retrieve_req.trace_id,
                execution_id=retrieve_req.execution_id,
            )
            raise CapabilityAccessDeniedError(reason)

        # Validate actor binding
        grant_actor = self._access_contract_actors.get(contract.access_token)
        if not grant_actor and self.grant_store is not None:
            try:
                g_data = self.grant_store.load(contract.access_token)
                if g_data:
                    grant_actor = g_data.get("actor")
            except Exception:
                pass

        if grant_actor and actor != grant_actor:
            reason = f"Access contract '{contract.request_id}' is bound to actor '{grant_actor}', cannot be used by '{actor}'."
            self._emit_audit(
                request_id=contract.request_id,
                actor=actor,
                application_id=retrieve_req.application_id or contract.application_id,
                capability_id=capability_id,
                action="DATA_RETRIEVAL",
                result="DENIED",
                reason=reason,
                trace_id=retrieve_req.trace_id,
                execution_id=retrieve_req.execution_id,
            )
            raise CapabilityAccessDeniedError(reason)

        # Check grant expiry
        if contract.expires_at:
            try:
                exp_dt = datetime.fromisoformat(contract.expires_at)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= exp_dt:
                    reason = f"Access contract '{contract.request_id}' has expired."
                    self._emit_audit(
                        request_id=contract.request_id,
                        actor=actor,
                        application_id=retrieve_req.application_id or contract.application_id,
                        capability_id=capability_id,
                        action="DATA_RETRIEVAL",
                        result="DENIED",
                        reason=reason,
                        trace_id=retrieve_req.trace_id,
                        execution_id=retrieve_req.execution_id,
                    )
                    raise CapabilityAccessDeniedError(reason)
            except (ValueError, TypeError) as exc:
                logger.warning("Could not parse expires_at timestamp: %s", exc)

        # Execute data retrieval via DatasetRetrievalService & SQL store / VANA live / canonical generator
        provenance = self.retrieval_service.get_dataset_provenance(capability.dataset_id)

        # Check retrieval readiness if package exists in package registry
        packages = self.package_registry.list_all()
        package = next((p for p in packages if p.dataset_id == capability.dataset_id), None)
        if package:
            is_demo_fixture = "[DEMO]" in capability.capability_name or "Demo" in capability.description
            is_registry_seeded_stub = (
                package.status == PackageStatus.REGISTERED
                and bool(package.history and package.history[0].actor == "capability_registry")
                and capability.status != CapabilityStatus.CERTIFIED
            )
            # Evaluate readiness for production/lifecycle-managed packages or deprecated packages
            if (not is_demo_fixture and not is_registry_seeded_stub) or package.status in (PackageStatus.DEPRECATED, PackageStatus.ARCHIVED):
                readiness = self.retrieval_service.retrieval_readiness_service.assess(package.package_id)
                if readiness.status == RetrievalStatus.NOT_RETRIEVABLE:
                    reason = f"Dataset '{capability.dataset_id}' for capability '{capability_id}' is NOT_RETRIEVABLE: {readiness.corrective_actions}"
                    self._emit_audit(
                        request_id=contract.request_id,
                        actor=actor,
                        application_id=contract.application_id,
                        capability_id=capability_id,
                        action="DATA_RETRIEVAL",
                        result="DENIED",
                        reason=reason,
                        trace_id=retrieve_req.trace_id,
                        execution_id=retrieve_req.execution_id,
                    )
                    raise CapabilityAccessDeniedError(reason)

        is_synthetic = False
        payload_data = None

        if self.sql_store is not None:
            try:
                records = self.sql_store.list_target_records(target_database="relational_db", dataset_id=capability.dataset_id, limit=100)
                if not records:
                    for db_name in ("analytics_db", "document_db", "metadata_db"):
                        records = self.sql_store.list_target_records(target_database=db_name, dataset_id=capability.dataset_id, limit=100)
                        if records:
                            break
                if records:
                    payload_data = {"records": records, "record_count": len(records), "dataset_id": capability.dataset_id}
            except Exception as exc:
                logger.warning("Could not query sql_store for target records: %s", exc)

        if payload_data is None and self.vana_client and self.vana_client.is_configured():
            try:
                if (
                    capability.capability_id == "cap-vana-forest-cover"
                    or capability.dataset_id == "DS-FSI-ISFR-2023-FOREST-COVER"
                ):
                    payload_data = self.vana_client.get_forest_cover_records(retrieve_req.query_params)
                elif (
                    capability.capability_id == "cap-vana-thane-creek-carbon"
                    or capability.dataset_id == "DS-VANA-THANE-CREEK-BLUE-CARBON"
                ):
                    payload_data = self.vana_client.get_carbon_thane_creek()
                elif (
                    capability.capability_id == "cap-vana-spatial-layers"
                    or capability.dataset_id == "DS-VANA-SPATIAL-LAYERS"
                ):
                    layer_id = (retrieve_req.query_params or {}).get("layer_id", "sanctuary_boundary")
                    payload_data = self.vana_client.get_spatial_geojson(layer_id)
                elif capability.capability_id == "cap-mangrove-monitoring":
                    payload_data = self.vana_client.get_real_observations(retrieve_req.query_params)
            except Exception as exc:
                logger.warning("VANA live data retrieval fallback to canonical generator: %s", exc)

        if payload_data is None:
            is_synthetic = True
            payload_data = self._generate_canonical_domain_payload(capability, retrieve_req.query_params)

        content_digest = hashlib.sha256(json.dumps(payload_data, sort_keys=True).encode()).hexdigest()

        response = CapabilityRetrieveResponse(
            data=payload_data,
            capability={
                "capability_id": capability.capability_id,
                "capability_name": capability.capability_name,
                "description": capability.description,
                "domain": capability.domain,
                "dataset_id": capability.dataset_id,
                "version": capability.capability_version,
            },
            contract_version=capability.contract_version,
            provenance={
                "dataset_id": capability.dataset_id,
                "capability_id": capability.capability_id,
                "version": capability.capability_version,
                "retrieval_timestamp": datetime.now(timezone.utc).isoformat(),
                "content_digest_sha256": content_digest,
                "is_synthetic": is_synthetic,
                "masterdb_lineage": provenance.get("masterdb_lineage"),
                "mdu_provenance": provenance.get("mdu_provenance"),
                "source": capability.provenance.get("source", "MASTERDB Canonical Data Layer"),
                "repository": capability.provenance.get("repository"),
                "commit": capability.provenance.get("commit"),
                "certification": capability.provenance.get("certification"),
            },
            content_digest_sha256=content_digest,
            request_id=contract.request_id,
            trace_id=retrieve_req.trace_id,
            execution_id=retrieve_req.execution_id,
            access_metadata={
                "application_id": contract.application_id,
                "purpose": contract.purpose,
                "access_token": contract.access_token,
                "authorization_status": "AUTHORIZED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "expires_at": contract.expires_at,
            },
        )

        self._emit_audit(
            request_id=contract.request_id,
            actor=actor,
            application_id=contract.application_id,
            capability_id=capability.capability_id,
            action="DATA_RETRIEVAL",
            result="SUCCESS",
            reason=f"Data retrieved successfully via TANTRA access contract boundary (synthetic={is_synthetic}).",
            trace_id=retrieve_req.trace_id,
            execution_id=retrieve_req.execution_id,
        )

        return response

    def _generate_canonical_domain_payload(self, capability: Capability, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate domain payload proving generic capability model works for any domain."""
        domain = capability.domain.lower()
        now = datetime.now(timezone.utc).isoformat()
        
        if domain == "geospatial":
            if capability.capability_id == "cap-vana-forest-cover" or capability.dataset_id == "DS-FSI-ISFR-2023-FOREST-COVER":
                return {
                    "dataset_id": "DS-FSI-ISFR-2023-FOREST-COVER",
                    "authority": "Forest Survey of India (ISFR 2023)",
                    "records": [
                        {"district": "Thane", "very_dense_forest": 124.5, "moderately_dense_forest": 480.2, "open_forest": 512.8, "total_canopy": 1117.5},
                        {"district": "Mumbai Suburban", "very_dense_forest": 12.0, "moderately_dense_forest": 54.0, "open_forest": 98.0, "total_canopy": 164.0},
                    ],
                    "mangrove_cover_sq_km": 66.0,
                    "observation_timestamp": now,
                    "governance_status": "CANONICAL_ISFR_2023",
                }
            elif capability.capability_id == "cap-vana-thane-creek-carbon" or capability.dataset_id == "DS-VANA-THANE-CREEK-BLUE-CARBON":
                return {
                    "dataset_id": "DS-VANA-THANE-CREEK-BLUE-CARBON",
                    "authority": "VANA Carbon Quantification Engine",
                    "mangrove_blue_carbon_stock_tC": 184500.0,
                    "measured_vs_satellite_segregation": {
                        "measured_soil_organic_carbon_tC_per_ha": 142.3,
                        "aboveground_biomass_satellite_tC_per_ha": 68.7,
                        "validation_status": "CONVERGED",
                    },
                    "observation_timestamp": now,
                }
            elif capability.capability_id == "cap-vana-spatial-layers" or capability.dataset_id == "DS-VANA-SPATIAL-LAYERS":
                return {
                    "type": "FeatureCollection",
                    "layer_id": params.get("layer_id", "sanctuary_boundary"),
                    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[72.93, 19.01], [72.99, 19.01], [72.99, 19.15], [72.93, 19.15], [72.93, 19.01]]],
                            },
                            "properties": {
                                "name": "Thane Creek Flamingo Sanctuary",
                                "area_sq_km": 16.9,
                                "boundary_classification": "OFFICIAL_WILDLIFE_SANCTUARY",
                            },
                        }
                    ],
                    "timestamp": now,
                }
            return {
                "dataset_type": "mangrove_cover_index",
                "region": params.get("region", "Sundarbans-Zone-A"),
                "canopy_density_pct": 84.5,
                "biomass_index": 0.92,
                "observation_timestamp": now,
                "coordinates": {"lat": 21.9497, "lon": 88.9439},
            }
        elif domain == "maritime":
            return {
                "dataset_type": "vessel_manifest_tracking",
                "vessel_id": params.get("vessel_id", "IMO-9823412"),
                "port_origin": "JNPT Navi Mumbai",
                "port_destination": "Port of Singapore",
                "status": "IN_TRANSIT",
                "cargo_weight_tonnes": 45000,
                "telemetry_timestamp": now,
            }
        elif domain == "finance":
            return {
                "dataset_type": "financial_market_index",
                "symbol": params.get("symbol", "BHIV-INDEX-30"),
                "value": 48291.50,
                "currency": "INR",
                "risk_rating": "AAA",
                "as_of": now,
            }
        elif domain == "infrastructure":
            return {
                "dataset_type": "highway_corridor_telemetry",
                "corridor_id": params.get("corridor_id", "NH-44-SECTOR-4"),
                "traffic_volume_vph": 3450,
                "pavement_quality_score": 9.1,
                "active_tolls": 12,
                "updated_at": now,
            }
        else:
            return {
                "dataset_type": f"{domain}_canonical_records",
                "domain": domain,
                "parameters": params,
                "record_count": 100,
                "timestamp": now,
            }

    def _emit_audit(
        self,
        request_id: str,
        actor: str,
        application_id: str,
        capability_id: str,
        action: str,
        result: str,
        reason: str,
        trace_id: Optional[str] = None,
        execution_id: Optional[str] = None,
    ) -> None:
        payload = {
            "request_id": request_id,
            "application_id": application_id,
            "capability_id": capability_id,
            "action": action,
            "result": result,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if trace_id:
            payload["trace_id"] = trace_id
        if execution_id:
            payload["execution_id"] = execution_id
        self.audit_emitter.emit(event_type=f"capability_{action.lower()}", actor=actor, payload=payload)
        logger.info(
            "capability_audit event=%s actor=%s app=%s cap=%s result=%s trace=%s exec=%s",
            action, actor, application_id, capability_id, result, trace_id, execution_id
        )
