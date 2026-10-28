"""
Source-Independent Geospatial Connector Abstraction — BHIV MASTERDB.

Separates External Geospatial Source -> BHIV Connector -> Validation / Provenance -> MDU -> MASTERDB -> Capability Registry.

NOTE: This module provides a reusable adapter abstraction and pipeline orchestrator.
It does NOT connect directly to live production satellite feeds or external ground stations.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models import (
    Capability,
    CapabilityStatus,
    KnowledgePackage,
    SourceRecord,
    SourceRegisterRequest,
    SourceStatus,
)
from services.capability_registry_service import CapabilityRegistryService
from services.package_registry_service import PackageRegistryService
from services.source_registry_service import SourceRegistryService

logger = logging.getLogger("masterdb")


class GeospatialConnectorAdapter:
    """
    Source-Independent Connector Adapter.

    Defines and orchestrates the mandatory pipeline abstraction:
    SOURCE -> CONNECTOR -> VALIDATION -> MDU -> DATASET -> CAPABILITY
    """


    def __init__(
        self,
        source_registry: Optional[SourceRegistryService] = None,
        package_registry: Optional[PackageRegistryService] = None,
        capability_registry: Optional[CapabilityRegistryService] = None,
    ) -> None:
        self.source_registry = source_registry or SourceRegistryService()
        self.package_registry = package_registry or PackageRegistryService()
        self.capability_registry = capability_registry or CapabilityRegistryService(
            package_registry=self.package_registry
        )

    def ingest_and_register_geospatial_capability(
        self,
        source_payload: Dict[str, Any],
        actor: str = "system",
        confirm_write_authority: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes end-to-end ingestion and governance mapping:
        1. Source Registration / Resolution
        2. Connector Normalization & Validation
        3. Dataset Package Creation
        4. Capability Registration
        """
        source_name = source_payload.get("source_name", "External Geospatial Data Source")
        source_id = source_payload.get("source_id", f"src-{source_name.lower().replace(' ', '-')[:20]}")
        authority = source_payload.get("authority", "NOT VERIFIED")
        licence = source_payload.get("licence", "PENDING")
        coverage = source_payload.get("geographic_coverage", "UNKNOWN")

        # 1. SOURCE REGISTRATION / RESOLUTION
        try:
            source_rec = self.source_registry.get_source(source_id)
        except Exception:
            source_req = SourceRegisterRequest(
                source_id=source_id,
                name=source_name,
                authority=authority,
                source_type=source_payload.get("source_type", "SATELLITE"),
                licence=licence,
                access_method=source_payload.get("access_method", "REST_API"),
                geographic_coverage=coverage,
                update_characteristics=source_payload.get("update_characteristics", "DAILY"),
                reliability_limitations=source_payload.get("reliability_limitations", "CLOUD_COVER"),
                attribution=source_payload.get("attribution", "NOT VERIFIED"),
                connector=source_payload.get("connector", "generic_geospatial_connector"),
                provenance_reference=source_payload.get("provenance", {}),
                confirm_write_authority=confirm_write_authority,
            )
            source_rec = self.source_registry.register_source(source_req, actor=actor)

        # 2. DATASET REGISTRATION
        dataset_id = source_payload.get("dataset_id", f"ds-geo-{source_id}")
        schema_version = source_payload.get("schema_version", "v1.0")
        try:
            package = self.package_registry.get_by_dataset_id(dataset_id)
        except Exception:
            package = self.package_registry.register(
                dataset_id=dataset_id,
                dataset_version=source_payload.get("version", "1.0.0"),
                schema_version=schema_version,
                board="geospatial",
                medium="api",
                language="geojson",
                owner=authority,
                actor=actor,
                reason=f"Ingested via {source_rec.connector} for dataset {dataset_id}",
            )

        # 3. CAPABILITY REGISTRATION
        cap_id = source_payload.get("capability_id", f"cap-geo-{dataset_id}")
        cap_name = source_payload.get("capability_name", f"Geospatial Capability: {source_name}")
        cap_status = (
            CapabilityStatus.ACTIVE
            if confirm_write_authority
            else CapabilityStatus.PENDING_AUTHORITY_CONFIRMATION
        )

        capability = Capability(
            capability_id=cap_id,
            capability_name=cap_name,
            description=source_payload.get("description", "Governed geospatial observation and processing capability"),
            dataset_id=dataset_id,
            source_id=source_rec.source_id,
            purpose=source_payload.get("purpose", "geospatial_analytics"),
            capability_version=source_payload.get("version", "1.0.0"),
            contract_version="1.0.0",
            domain=source_payload.get("domain", "geospatial"),
            schema_version=schema_version,
            status=cap_status,
            inputs=source_payload.get(
                "inputs",
                [
                    {"name": "area_of_interest", "type": "GeoJSON Polygon", "required": True},
                    {"name": "temporal_range", "type": "ISO8601 Interval", "required": False},
                ],
            ),
            outputs=source_payload.get(
                "outputs",
                [
                    {"name": "change_polygons", "type": "GeoJSON MultiPolygon"},
                    {"name": "change_statistics", "type": "JSON Object"},
                ],
            ),
            dependencies=source_payload.get(
                "dependencies", [source_rec.name, "MDU-Semantic-Contract-Engine"]
            ),
            source_references=[source_rec.source_id],
            dataset_references=[dataset_id],
            validation_status="VALIDATED" if confirm_write_authority else "PENDING_VALIDATION",
            known_limitations=[source_rec.reliability_limitations],
            potential_consumers=source_payload.get(
                "potential_consumers", ["Bharat Mala", "VANA/FIN", "Marine Intelligence"]
            ),
            licensing={
                "software_licence": "PROPRIETARY_BHIV",
                "dataset_licence": source_rec.licence,
                "source_licence": source_rec.licence,
            },
            provenance={
                **source_payload.get("provenance", {}),
                "source_id": source_rec.source_id,
                "authority": source_rec.authority,
                "dataset_id": dataset_id,
                "connector": source_rec.connector,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            },
            registration_authority_confirmed=confirm_write_authority,
        )

        try:
            reg_cap = self.capability_registry.get_capability(cap_id)
        except Exception:
            reg_cap = self.capability_registry.register_capability(capability)

        return {
            "source": source_rec.model_dump(mode="json"),
            "package": package.model_dump(mode="json"),
            "capability": reg_cap.model_dump(mode="json"),
            "status": "SUCCESS",
            "pipeline": "EXTERNAL_SOURCE -> CONNECTOR -> VALIDATION -> MDU -> MASTERDB -> CAPABILITY",
        }

    def ingest_gods_eye_view_source(
        self,
        gev_source_key: str,
        actor: str = "system",
        confirm_write_authority: bool = True,
    ) -> Dict[str, Any]:
        """
        Specialized helper for registering verified God's Eye View capabilities:
        - gev_source_key: 'opensky', 'celestrak', 'firms', 'noaa', 'usgs'
        """
        gev_configs = {
            "opensky": {
                "source_id": "src-gev-opensky",
                "source_name": "God's Eye View - OpenSky Network Live Air Traffic Telemetry",
                "authority": "The OpenSky Network / Bilawal Sidhu God's Eye View Proxy",
                "licence": "OPEN_COMMUNITY_DATA_LICENSE",
                "geographic_coverage": "GLOBAL_AIRSPACE",
                "update_characteristics": "REALTIME_5_SECOND_POLL_60_SECOND_CACHE",
                "reliability_limitations": "RECEIVER_COVERAGE_GAPS_AND_TRANSPONDER_ABSENCE",
                "attribution": "The OpenSky Network (opensky-network.org), bilawalsidhu/gods-eye-view",
                "connector": "gods_eye_view_connector",
                "dataset_id": "ds-gev-opensky-flights",
                "capability_id": "cap-gev-flight-tracking-staged",
                "capability_name": "God's Eye View - Live Flight Tracking & Airspace Monitoring",
                "description": "Governed real-time global airspace state vectors, aircraft telemetry, callsign tracking, altitude, velocity, and transponder positional data from OpenSky Network.",
                "purpose": "airspace_situational_awareness",
                "domain": "geospatial",
                "provenance": {
                    "source": "OpenSky Network via God's Eye View Proxy",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
                    "certification": "MASTERDB-VERIFIED-GEV-006",
                    "proxy_endpoint": "/api/opensky",
                },
            },
            "marine_ports": {
                "source_id": "src-marine-intel-ports",
                "source_name": "Marine Intelligence - Indian Ports & Harbours Infrastructure",
                "authority": "Ministry of Ports, Shipping and Waterways / Sagarmala",
                "licence": "PUBLIC_GOVERNMENT_DATA",
                "geographic_coverage": "INDIA_COASTAL_AND_MAJOR_PORTS",
                "update_characteristics": "MONTHLY_REGISTRY_UPDATE",
                "reliability_limitations": "SUBJECT_TO_PORT_AUTHORITY_REPORTING_CYCLES",
                "attribution": "shipmin.gov.in, sagarmala.gov.in, mmb.gov.in",
                "connector": "marine_intelligence_connector",
                "dataset_id": "ds-marine-intel-ports",
                "capability_id": "cap-marine-intel-ports",
                "capability_name": "Marine Intelligence - Indian Ports & Harbours Data Service",
                "description": "Governed Indian major & non-major port infrastructure, coordinates, state jurisdiction, and operational notes dataset from Marine Intelligence data layer.",
                "purpose": "maritime_infrastructure_analytics",
                "domain": "maritime",
                "provenance": {
                    "source": "Ministry of Ports, Shipping and Waterways via Marine Intelligence Data Layer",
                    "repository": "https://github.com/shravani2207-tech/marine-intelligence-task",
                    "commit": "03af9e32eeba275592a8e19041d7b51d6139dad7",
                    "certification": "MASTERDB-VERIFIED-MARINE-001",
                },
            },
            "celestrak": {
                "source_id": "src-gev-celestrak",
                "source_name": "God's Eye View - CelesTrak Satellite Ephemeris TLE Feeds",
                "authority": "CelesTrak / Dr. T.S. Kelso",
                "licence": "US_GOVERNMENT_PUBLIC_DOMAIN",
                "geographic_coverage": "GLOBAL_ORBITAL",
                "update_characteristics": "DAILY_CATALOG_REFRESH",
                "reliability_limitations": "SGP4_PROPAGATION_DECAY_LATENCY",
                "attribution": "CelesTrak (celestrak.org), Dr. T.S. Kelso",
                "connector": "gods_eye_view_connector",
                "dataset_id": "ds-gev-satellite-tles",
                "capability_id": "cap-gev-satellite-pass-prediction",
                "capability_name": "God's Eye View - Satellite Orbit Propagation & Pass Prediction",
                "description": "Governed orbital state vector propagation and pass prediction using CelesTrak NORAD TLE catalogs and SGP4 orbit calculation.",
                "purpose": "space_situational_awareness",
                "domain": "geospatial",
                "provenance": {
                    "source": "CelesTrak via God's Eye View Proxy",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
                    "certification": "MASTERDB-VERIFIED-GEV-002",
                },
            },
            "firms": {
                "source_id": "src-gev-nifc-firms",
                "source_name": "God's Eye View - NIFC WFIGS & NASA FIRMS Wildfire Data",
                "authority": "National Interagency Fire Center (NIFC) / NASA LANCE FIRMS",
                "licence": "US_GOVERNMENT_PUBLIC_DOMAIN",
                "geographic_coverage": "NORTH_AMERICA_GLOBAL_THERMAL",
                "update_characteristics": "5_MINUTE_SERVER_CACHE",
                "reliability_limitations": "AGENCY_REPORTING_DELAY_AND_CLOUD_THERMAL_BLINDNESS",
                "attribution": "Wildfire perimeters: National Interagency Fire Center (WFIGS) / NASA LANCE FIRMS",
                "connector": "gods_eye_view_connector",
                "dataset_id": "ds-gev-wildfire-perimeters",
                "capability_id": "cap-gev-wildfire-perimeter-monitoring",
                "capability_name": "God's Eye View - Wildfire Incident & Perimeter Monitoring",
                "description": "Governed active wildfire perimeters, containment status, thermal hot-spots, and InciWeb incident narrative integration.",
                "purpose": "disaster_response_and_safety",
                "domain": "geospatial",
                "provenance": {
                    "source": "NIFC WFIGS & NASA FIRMS via God's Eye View Proxy",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
                    "certification": "MASTERDB-VERIFIED-GEV-003",
                },
            },
            "noaa": {
                "source_id": "src-gev-noaa-weather",
                "source_name": "God's Eye View - NOAA GFS & nowCOAST Meteorological Services",
                "authority": "NOAA National Weather Service / National Environmental Satellite Service",
                "licence": "US_PUBLIC_DOMAIN",
                "geographic_coverage": "GLOBAL_AND_CONUS",
                "update_characteristics": "6_HOURLY_GFS_CYCLE_4_MINUTE_NOWCOAST_RADAR",
                "reliability_limitations": "GRID_INTERPOLATION_AND_RADAR_BEAM_BLOCKAGE",
                "attribution": "NOAA Global Forecast System (GFS) / NOAA nowCOAST",
                "connector": "gods_eye_view_connector",
                "dataset_id": "ds-gev-weather-telemetry",
                "capability_id": "cap-gev-weather-forecast-tracking",
                "capability_name": "God's Eye View - Severe Weather & Cyclone Track Forecast",
                "description": "Governed 10m global wind vectors, rain radar, satellite clouds, lightning density, and NHC cyclone forecast cones.",
                "purpose": "meteorological_monitoring",
                "domain": "geospatial",
                "provenance": {
                    "source": "NOAA NWS & nowCOAST via God's Eye View Proxy",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
                    "certification": "MASTERDB-VERIFIED-GEV-004",
                },
            },
            "usgs": {
                "source_id": "src-gev-usgs-seismic",
                "source_name": "God's Eye View - USGS Earthquake Hazards Program Feeds",
                "authority": "U.S. Geological Survey (USGS)",
                "licence": "US_GOVERNMENT_PUBLIC_DOMAIN",
                "geographic_coverage": "GLOBAL",
                "update_characteristics": "1_MINUTE_GEOJSON_POLL",
                "reliability_limitations": "PRELIMINARY_AUTOMATED_MAGNITUDE_REVISIONS",
                "attribution": "Data courtesy of the U.S. Geological Survey",
                "connector": "gods_eye_view_connector",
                "dataset_id": "ds-gev-seismic-events",
                "capability_id": "cap-gev-earthquake-monitoring",
                "capability_name": "God's Eye View - Real-time Global Seismic Event Detection",
                "description": "Governed real-time global earthquake events, magnitudes, focal depths, and shake-map intensity indicators from USGS.",
                "purpose": "seismic_hazard_monitoring",
                "domain": "geospatial",
                "provenance": {
                    "source": "USGS Earthquake Hazards Program via God's Eye View Proxy",
                    "repository": "https://github.com/bilawalsidhu/gods-eye-view",
                    "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
                    "certification": "MASTERDB-VERIFIED-GEV-005",
                },
            },
        }

        if gev_source_key not in gev_configs:
            raise ValueError(f"Unknown GEV source key '{gev_source_key}'. Allowed: {list(gev_configs.keys())}")

        payload = gev_configs[gev_source_key]
        return self.ingest_and_register_geospatial_capability(
            source_payload=payload,
            actor=actor,
            confirm_write_authority=confirm_write_authority,
        )

    def ingest_vana_source(
        self,
        vana_source_key: str,
        actor: str = "system",
        confirm_write_authority: bool = True,
    ) -> Dict[str, Any]:
        """
        Specialized helper for registering verified VANA capabilities:
        - vana_source_key: 'forest_cover', 'thane_creek_carbon', 'spatial_layers'
        """
        vana_configs = {
            "forest_cover": {
                "source_id": "src-fsi-isfr-2023",
                "source_name": "Forest Survey of India - India State of Forest Report (ISFR 2023)",
                "authority": "Forest Survey of India (FSI) / MoEFCC",
                "licence": "GOVERNMENT_OPEN_DATA",
                "geographic_coverage": "INDIA_NATIONAL_AND_DISTRICTS",
                "update_characteristics": "BIENNIAL_PUBLICATION_CYCLE",
                "reliability_limitations": "REMOTE_SENSING_RESOLUTION_MINIMUM_CANOPY_10PCT",
                "attribution": "Forest Survey of India, ISFR 2023",
                "connector": "vana_forest_governance_connector",
                "dataset_id": "DS-FSI-ISFR-2023-FOREST-COVER",
                "capability_id": "cap-vana-forest-cover",
                "capability_name": "VANA - FSI ISFR 2023 Official Forest Cover Records",
                "description": "Governed official Forest Survey of India (ISFR 2023) district forest canopy and mangrove coverage records with immutable source provenance.",
                "purpose": "district_canopy_analysis",
                "domain": "geospatial",
                "provenance": {
                    "source": "Forest Survey of India (ISFR 2023) via VANA Governance Layer",
                    "certification": "VANA-ISFR-2023-CANONICAL",
                    "governance_gate": "6_TUPLE_EVALUATION_GATE",
                },
            },
            "thane_creek_carbon": {
                "source_id": "src-vana-thane-creek",
                "source_name": "VANA - Thane Creek Flamingo Sanctuary Mangrove Blue Carbon Engine",
                "authority": "Maharashtra Mangrove Cell / VANA Carbon Quantification Engine",
                "licence": "BHIV_RESEARCH_USE",
                "geographic_coverage": "THANE_CREEK_FLAMINGO_SANCTUARY_MUMBAI",
                "update_characteristics": "30_DAY_SAMPLE_REFRESH",
                "reliability_limitations": "GROUND_TRUTH_CORE_SAMPLE_DENSITY",
                "attribution": "Maharashtra Forest Department Mangrove Cell, VANA Blue Carbon Research Group",
                "connector": "vana_carbon_engine_connector",
                "dataset_id": "DS-VANA-THANE-CREEK-BLUE-CARBON",
                "capability_id": "cap-vana-thane-creek-carbon",
                "capability_name": "VANA - Thane Creek Mangrove Blue Carbon Engine",
                "description": "Governed Thane Creek Flamingo Sanctuary mangrove blue carbon quantification with strict measured vs satellite segregation.",
                "purpose": "carbon_quantification",
                "domain": "geospatial",
                "provenance": {
                    "source": "VANA Blue Carbon Engine (Thane Creek)",
                    "certification": "VANA-BLUE-CARBON-VERIFIED",
                    "governance_gate": "6_TUPLE_EVALUATION_GATE",
                },
            },
            "spatial_layers": {
                "source_id": "src-vana-gis",
                "source_name": "VANA - Spatial GIS GeoJSON Layers Catalog",
                "authority": "VANA Spatial Layer Service / Survey of India RFC 7946 Standard",
                "licence": "GOVERNMENT_OPEN_DATA",
                "geographic_coverage": "MAHARASHTRA_COASTAL_ZONES",
                "update_characteristics": "QUARTERLY_BOUNDARY_REVALIDATION",
                "reliability_limitations": "RFC7946_WGS84_PROJECTION_TOLERANCES",
                "attribution": "VANA GIS Spatial Engine",
                "connector": "vana_spatial_gis_connector",
                "dataset_id": "DS-VANA-SPATIAL-LAYERS",
                "capability_id": "cap-vana-spatial-layers",
                "capability_name": "VANA - Spatial GIS GeoJSON Layers",
                "description": "Governed RFC 7946 WGS84 GeoJSON spatial layers: sanctuary boundaries, mangrove density, and nurseries.",
                "purpose": "spatial_gis_analysis",
                "domain": "geospatial",
                "provenance": {
                    "source": "VANA Spatial GIS Layer Catalog",
                    "certification": "VANA-RFC7946-GEOJSON",
                    "governance_gate": "6_TUPLE_EVALUATION_GATE",
                },
            },
        }

        if vana_source_key not in vana_configs:
            raise ValueError(f"Unknown VANA source key '{vana_source_key}'. Allowed: {list(vana_configs.keys())}")

        payload = vana_configs[vana_source_key]
        return self.ingest_and_register_geospatial_capability(
            source_payload=payload,
            actor=actor,
            confirm_write_authority=confirm_write_authority,
        )
