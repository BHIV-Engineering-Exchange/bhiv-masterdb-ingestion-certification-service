"""
Source Registry Service — Governed Ecosystem Source Records.

Owns MASTERDB Source registration, discovery, duplicate checking, write authority confirmation,
and lifecycle tracking for geospatial and generic ecosystem sources.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models import SourceRecord, SourceRegisterRequest, SourceStatus
from services.artifact_store import ArtifactStore
from services.crypto_audit_emitter import CryptoAuditEmitter

logger = logging.getLogger("masterdb")


class SourceNotFoundError(KeyError):
    """Raised when a requested source_id does not exist."""
    pass


class SourceAlreadyExistsError(ValueError):
    """Raised when attempting to register a source that already exists."""
    pass


class SourceRegistryService:
    def __init__(
        self,
        store_dir: str = "source_store",
        audit_emitter: Optional[CryptoAuditEmitter] = None,
    ) -> None:
        self.store = ArtifactStore(reports_dir=store_dir)
        self.audit_emitter = audit_emitter or CryptoAuditEmitter()
        self._seed_default_sources_if_empty()

    def _seed_default_sources_if_empty(self) -> None:
        defaults = [
            # NOTE: Seed records below are DEMO / TEST FIXTURES for API contract demonstration.
            # They do NOT represent live production connections to real external ground stations or gateways.
            SourceRecord(
                source_id="src-marine-intel-ports",
                name="Marine Intelligence - Indian Ports & Harbours Infrastructure",
                authority="Ministry of Ports, Shipping and Waterways / Sagarmala",
                source_type="MARITIME_PORT_REGISTRY",
                licence="PUBLIC_GOVERNMENT_DATA",
                access_method="REST_API",
                geographic_coverage="INDIA_COASTAL_AND_MAJOR_PORTS",
                update_characteristics="MONTHLY_REGISTRY_UPDATE",
                reliability_limitations="SUBJECT_TO_PORT_AUTHORITY_REPORTING_CYCLES",
                attribution="shipmin.gov.in, sagarmala.gov.in, mmb.gov.in",
                connector="marine_intelligence_connector",
                last_validation=datetime.now(timezone.utc).isoformat(),
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "Ministry of Ports, Shipping and Waterways", "repository": "https://github.com/shravani2207-tech/marine-intelligence-task", "commit": "03af9e32eeba275592a8e19041d7b51d6139dad7"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-celestrak",
                name="God's Eye View - CelesTrak Satellite Ephemeris TLE Feeds",
                authority="CelesTrak / Dr. T.S. Kelso",
                source_type="SATELLITE_NORAD_TLE_CATALOG",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="REST_API_PROXY",
                geographic_coverage="GLOBAL_ORBITAL",
                update_characteristics="DAILY_CATALOG_REFRESH",
                reliability_limitations="SGP4_PROPAGATION_DECAY_LATENCY",
                attribution="CelesTrak (celestrak.org), Dr. T.S. Kelso",
                connector="gods_eye_view_connector",
                last_validation=datetime.now(timezone.utc).isoformat(),
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "CelesTrak", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-nifc-firms",
                name="God's Eye View - NIFC WFIGS & NASA FIRMS Wildfire Data",
                authority="National Interagency Fire Center (NIFC) / NASA LANCE FIRMS",
                source_type="ARCGIS_FEATURE_SERVICE_AND_WMTS",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="REST_API_PROXY",
                geographic_coverage="NORTH_AMERICA_GLOBAL_THERMAL",
                update_characteristics="5_MINUTE_SERVER_CACHE",
                reliability_limitations="AGENCY_REPORTING_DELAY_AND_CLOUD_THERMAL_BLINDNESS",
                attribution="Wildfire perimeters: National Interagency Fire Center (WFIGS) / NASA LANCE FIRMS",
                connector="gods_eye_view_connector",
                last_validation=datetime.now(timezone.utc).isoformat(),
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NIFC WFIGS / NASA FIRMS", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-noaa-weather",
                name="God's Eye View - NOAA GFS & nowCOAST Meteorological Services",
                authority="NOAA National Weather Service / National Environmental Satellite Service",
                source_type="WEATHER_GRIB2_AND_WMS_RASTER",
                licence="US_PUBLIC_DOMAIN",
                access_method="S3_BYTE_RANGE_AND_WMS",
                geographic_coverage="GLOBAL_AND_CONUS",
                update_characteristics="6_HOURLY_GFS_CYCLE_4_MINUTE_NOWCOAST_RADAR",
                reliability_limitations="GRID_INTERPOLATION_AND_RADAR_BEAM_BLOCKAGE",
                attribution="NOAA Global Forecast System (GFS) / NOAA nowCOAST",
                connector="gods_eye_view_connector",
                last_validation=datetime.now(timezone.utc).isoformat(),
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "NOAA NWS", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30"},
                write_authority_confirmed=True,
            ),
            SourceRecord(
                source_id="src-gev-usgs-seismic",
                name="God's Eye View - USGS Earthquake Hazards Program Feeds",
                authority="U.S. Geological Survey (USGS)",
                source_type="SEISMIC_EVENT_FEED",
                licence="US_GOVERNMENT_PUBLIC_DOMAIN",
                access_method="REST_GEOJSON",
                geographic_coverage="GLOBAL",
                update_characteristics="1_MINUTE_GEOJSON_POLL",
                reliability_limitations="PRELIMINARY_AUTOMATED_MAGNITUDE_REVISIONS",
                attribution="Data courtesy of the U.S. Geological Survey",
                connector="gods_eye_view_connector",
                last_validation=datetime.now(timezone.utc).isoformat(),
                status=SourceStatus.ACTIVE,
                provenance_reference={"provider": "USGS", "repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30"},
                write_authority_confirmed=True,
            ),
        ]
        for src in defaults:
            if not self.store.load(src.source_id):
                self.register_source(
                    SourceRegisterRequest(
                        source_id=src.source_id,
                        name=src.name,
                        authority=src.authority,
                        source_type=src.source_type,
                        licence=src.licence,
                        access_method=src.access_method,
                        geographic_coverage=src.geographic_coverage,
                        update_characteristics=src.update_characteristics,
                        reliability_limitations=src.reliability_limitations,
                        attribution=src.attribution,
                        connector=src.connector,
                        provenance_reference=src.provenance_reference,
                        confirm_write_authority=True,
                    )
                )

    def register_source(self, req: SourceRegisterRequest, actor: str = "system") -> SourceRecord:
        # Enforce license-safe restriction on commercially prohibited/unverified sources
        # (exempts verified God's Eye View proxy integration)
        restricted_keywords = ["opensky", "telegeography"]
        src_id_low = (req.source_id or "").lower()
        src_name_low = (req.name or "").lower()
        is_verified_gev_proxy = (
            src_id_low == "src-gev-opensky"
            and isinstance(req.provenance_reference, dict)
            and "gods-eye-view" in req.provenance_reference.get("repository", "")
        )
        if not is_verified_gev_proxy and any(kw in src_id_low or kw in src_name_low for kw in restricted_keywords):
            raise ValueError(f"Registration of commercially restricted/unverified source '{req.source_id or req.name}' is prohibited.")

        # Check canonical existence / duplicate detection
        existing = self.list_sources()
        for s in existing:
            if req.source_id and s.source_id.lower() == req.source_id.lower():
                raise SourceAlreadyExistsError(f"Source with ID '{req.source_id}' already exists.")
            if s.name.lower() == req.name.lower():
                raise SourceAlreadyExistsError(f"Source with name '{req.name}' already exists.")

        # Determine authority confirmation status
        status = SourceStatus.ACTIVE if req.confirm_write_authority else SourceStatus.PENDING_AUTHORITY_CONFIRMATION
        authority_val = req.authority or "NOT VERIFIED"
        licence_val = req.licence or "PENDING"
        geographic_coverage = req.geographic_coverage or "UNKNOWN"
        update_characteristics = req.update_characteristics or "UNKNOWN"
        reliability_limitations = req.reliability_limitations or "UNKNOWN"
        attribution_val = req.attribution or "NOT VERIFIED"

        source_record = SourceRecord(
            source_id=req.source_id or f"src-{req.name.lower().replace(' ', '-')[:20]}",
            name=req.name,
            authority=authority_val,
            source_type=req.source_type or "GEOSPATIAL_PORTAL",
            licence=licence_val,
            access_method=req.access_method or "REST_API",
            geographic_coverage=geographic_coverage,
            update_characteristics=update_characteristics,
            reliability_limitations=reliability_limitations,
            attribution=attribution_val,
            connector=req.connector or "generic_connector",
            last_validation=datetime.now(timezone.utc).isoformat() if req.confirm_write_authority else "NOT VERIFIED",
            status=status,
            provenance_reference=req.provenance_reference,
            write_authority_confirmed=req.confirm_write_authority,
        )

        self.store.save(source_record.source_id, source_record.model_dump(mode="json"))

        self.audit_emitter.emit(
            event_type="source_registered",
            actor=actor,
            payload={
                "source_id": source_record.source_id,
                "name": source_record.name,
                "status": source_record.status.value,
                "write_authority_confirmed": source_record.write_authority_confirmed,
            },
        )
        logger.info(
            "source_registered source_id=%s name='%s' status=%s authority_confirmed=%s",
            source_record.source_id,
            source_record.name,
            source_record.status.value,
            source_record.write_authority_confirmed,
        )
        return source_record

    def get_source(self, source_id: str) -> SourceRecord:
        data = self.store.load(source_id)
        if not data:
            raise SourceNotFoundError(f"Source '{source_id}' not found.")
        return SourceRecord.model_validate(data)

    def list_sources(self, search: Optional[str] = None, status: Optional[str] = None) -> List[SourceRecord]:
        records = self.store.list_all()
        sources: List[SourceRecord] = []
        for rec in records:
            try:
                sources.append(SourceRecord.model_validate(rec))
            except Exception as exc:
                logger.warning("Failed to parse source record: %s", exc)

        if status:
            sources = [s for s in sources if s.status.value.lower() == status.lower()]
        if search:
            s_low = search.lower()
            sources = [
                s
                for s in sources
                if s_low in s.name.lower() or s_low in s.source_id.lower() or s_low in s.authority.lower()
            ]
        return sorted(sources, key=lambda x: x.source_id)
